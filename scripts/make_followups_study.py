"""Follow-up analyses: (a) 'vote not registered' cases 2024 T2; (b) recurrent queue by voting place across 2018/2022/2026 generals vs place size and voter profile (2022);
(c) aggregated sections as a queue factor; (d) second-round 'contingency-looking' logs vs recorded swaps. Descriptive only."""
import os
import re
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer
from PIL import Image as PI

os.environ.setdefault('UF', 'BA')
import make_bahia_reports as M
import make_closing_swaps_study as X

OUT = Path('relatorios/fechamento_e_trocas/desdobramentos')
FIG = OUT / 'figuras'
FIG.mkdir(parents=True, exist_ok=True)
ORDER = X.ORDER
KEY = X.KEY
n = X.n


def img(p, w):
    iw, ih = PI.open(p).size
    return Image(str(p), width=w * cm, height=w * cm * ih / iw)


# ------------------------------------------------------------------ (a)
def part_a():
    f = Path('research/contingencia/_scan_voto_nao_registrado.csv')
    scan = pd.read_csv(f) if f.exists() else None
    cases = []
    for g in Path('research/contingencia').glob('municipais_*_2024-t2.parquet'):
        d = pd.read_parquet(g)
        d = d[d.error_msgs.fillna('').str.contains('foi registrado')]
        uf = g.name.split('_')[1]
        for r in d.itertuples():
            bu = pd.read_parquet(f'research/analysis/PREFEITO/{uf}/2024-t2/sections.parquet', columns=KEY + ['municipality_name', 'attendance', 'opening_bu', 'closure_bu', 'winner', 'winner_pct'])
            b = bu[(bu.municipality == r.municipality) & (bu.zone == r.zone) & (bu.section == r.section)]
            code = '9350 (mídia externa ausente)' if '9350' in r.error_msgs else '8044 (MarcaUltimoVoto)'
            cases.append(dict(uf=uf, municipio=b.municipality_name.iloc[0] if len(b) else '', zona=r.zone, secao=r.section, erro=code, hora_erro=re.search(r'\d\d:\d\d:\d\d', r.power_off or '').group(0) if r.power_off else '',
                              religada=r.power_on.split(';')[-1] if r.power_on else '', primeiro_voto=r.first_vote, votos_log=r.votes, comparecimento_bu=int(b.attendance.iloc[0]) if len(b) else None,
                              abertura_bu=str(b.opening_bu.iloc[0])[-8:] if len(b) else '', encerramento_bu=str(b.closure_bu.iloc[0])[-8:] if len(b) else '', vencedor=f'{b.winner.iloc[0]} {b.winner_pct.iloc[0]:.1f}%' if len(b) else ''))
    return pd.DataFrame(cases), scan


# ------------------------------------------------------------------ (b)
def load_profile():
    fr = []
    for uf in ORDER:
        f = Path('research/perfil/2022') / f'{uf}.parquet'
        if f.exists():
            d = pd.read_parquet(f)
            d['uf'] = uf
            fr.append(d)
    if not fr:
        return None
    p = pd.concat(fr, ignore_index=True)
    p['voting_place'] = p.voting_place.astype(str)
    return p


def part_b():
    prof = load_profile()
    places = {}
    for eid in ['P2018', 'P2022', 'P2026']:
        d = X.DATA[eid]
        e = d[d.eligible >= 50].copy()
        e['place'] = e.uf + '|' + e.municipality.astype(str) + '|' + e.zone.astype(str) + '|' + e.voting_place
        g = e.groupby('place').agg(uf=('uf', 'first'), municipality=('municipality', 'first'), municipality_name=('municipality_name', 'first'), zone=('zone', 'first'),
                                   voting_place=('voting_place', 'first'), sections=('section', 'size'), eligible=('eligible', 'sum'), attendance=('attendance', 'sum'),
                                   close_med=('close_min', 'median'), late_share=('close_min', lambda x: (x > 60).mean()), manual=('manual_bu', 'sum'),
                                   late_votes=('after_17_recorded', 'sum') if 'after_17_recorded' in e else ('eligible', lambda x: np.nan))
        g['manual_pct'] = 100 * g.manual / g.attendance
        g['late_place'] = g.late_share >= .5
        places[eid] = g
    # recurrence across three generals (same place key)
    j = places['P2018'][['sections', 'eligible', 'close_med', 'late_share', 'late_place', 'manual_pct']].join(
        places['P2022'][['sections', 'eligible', 'close_med', 'late_share', 'late_place', 'manual_pct', 'late_votes']].rename(columns={'late_votes': 'late_votes_22'}), lsuffix='_18', rsuffix='_22', how='inner').join(
        places['P2026'][['sections', 'eligible', 'close_med', 'late_share', 'late_place', 'manual_pct', 'late_votes', 'uf', 'municipality', 'municipality_name', 'zone', 'voting_place']].rename(
            columns={'sections': 'sections_26', 'eligible': 'eligible_26', 'close_med': 'close_med_26', 'late_share': 'late_share_26', 'late_place': 'late_place_26', 'manual_pct': 'manual_pct_26', 'late_votes': 'late_votes_26'}), how='inner')
    j['n_late'] = j[['late_place_18', 'late_place_22', 'late_place_26']].sum(axis=1)
    p = [j.late_place_18.mean(), j.late_place_22.mean(), j.late_place_26.mean()]
    pdist = np.array([1.0])
    for pi in p:
        pdist = np.convolve(pdist, [1 - pi, pi])
    rec = dict(places=len(j), obs=j.n_late.value_counts().reindex(range(4), fill_value=0).to_dict(), exp={k: float(pdist[k] * len(j)) for k in range(4)},
               rho_18_22=stats.spearmanr(j.close_med_18, j.close_med_22)[0], rho_22_26=stats.spearmanr(j.close_med_22, j.close_med_26)[0], rho_18_26=stats.spearmanr(j.close_med_18, j.close_med_26)[0])
    # size effect: late share by number of sections per place and by voters per section (2022)
    g22 = places['P2022'].copy()
    g22['size_bin'] = pd.cut(g22.sections, [0, 1, 2, 4, 8, 16, 1000], labels=['1', '2', '3–4', '5–8', '9–16', '17+'])
    size_tab = g22.groupby('size_bin', observed=True).agg(places=('sections', 'size'), sections=('sections', 'sum'), late_place_pct=('late_place', lambda x: 100 * x.mean()),
                                                           late_share_mean=('late_share', lambda x: 100 * x.mean()), close_med=('close_med', 'median')).reset_index()
    prof_tab, prof_reg, top = None, None, None
    if prof is not None:
        prof['place'] = prof.uf + '|' + prof.municipality.astype(str) + '|' + prof.zone.astype(str) + '|' + prof.voting_place
        pp = prof.groupby('place').agg(place_name=('place_name', 'first'), voters=('voters', 'sum'), age60=('age60', 'sum'), age70=('age70', 'sum'), low_school=('low_school', 'sum'),
                                       higher_ed=('higher_ed', 'sum'), biometria=('biometria', 'sum'), age16_17=('age16_17', 'sum'))
        for c in ['age60', 'age70', 'low_school', 'higher_ed', 'biometria', 'age16_17']:
            pp[f'{c}_pct'] = 100 * pp[c] / pp.voters
        g = g22.join(pp, how='inner')
        rows = []
        for var, lab in [('age60_pct', '% eleitores com 60 anos ou mais'), ('low_school_pct', '% até fundamental incompleto'), ('higher_ed_pct', '% com superior (completo ou incompleto)'),
                         ('biometria_pct', '% com biometria cadastrada'), ('manual_pct', '% habilitação manual (BU)')]:
            q = pd.qcut(g[var].rank(method='first'), 5, labels=['Q1 (menor)', 'Q2', 'Q3', 'Q4', 'Q5 (maior)'])
            for lv in ['Q1 (menor)', 'Q2', 'Q3', 'Q4', 'Q5 (maior)']:
                s = g[q == lv]
                rows.append(dict(variavel=lab, quintil=lv, locais=len(s), media_var=s[var].mean(), late_place_pct=100 * s.late_place.mean(), close_med=s.close_med.median(), secoes_por_local=s.sections.mean()))
        prof_tab = pd.DataFrame(rows)
        # partial: within size bin
        g['logsec'] = np.log(g.sections)
        g['y'] = g.late_share * 100
        Xm = np.column_stack([np.ones(len(g)), g.logsec, g.age60_pct, g.low_school_pct, g.biometria_pct, g.manual_pct])
        ok = np.isfinite(Xm).all(axis=1) & np.isfinite(g.y)
        beta, *_ = np.linalg.lstsq(Xm[ok], g.y[ok], rcond=None)
        resid = g.y[ok] - Xm[ok] @ beta
        sigma2 = (resid ** 2).sum() / (ok.sum() - Xm.shape[1])
        cov = sigma2 * np.linalg.inv(Xm[ok].T @ Xm[ok])
        se = np.sqrt(np.diag(cov))
        prof_reg = pd.DataFrame(dict(termo=['constante', 'log(seções no local)', '% 60+', '% até fund. incompleto', '% biometria', '% manual (BU)'], coef=beta, se=se, n=ok.sum()))
        top = j.join(pp[['place_name', 'voters', 'age60_pct', 'low_school_pct', 'biometria_pct']], how='left')
        top = top[top.n_late == 3].sort_values('late_votes_26', ascending=False)
    return places, j, rec, size_tab, prof_tab, prof_reg, top


# ------------------------------------------------------------------ (c)
def part_c():
    rows = []
    for eid in X.FIRST:
        d = X.DATA[eid]
        e = d[d.eligible >= 50].copy()
        e['bin'] = pd.cut(e.eligible, [0, 200, 300, 400, 500, 10000], labels=['≤200', '201–300', '301–400', '401–500', '>500'])
        for b in e.bin.cat.categories:
            for ag in (False, True):
                s = e[(e.bin == b) & (e.is_agg == ag)]
                if len(s) < 30:
                    continue
                rows.append(dict(eid=eid, lab=X.LAB[eid], aptos=b, agregada='sim' if ag else 'não', secoes=len(s), close_med=s.close_min.median(), gt60=100 * (s.close_min > 60).mean(),
                                 late_pct=100 * s.after_17_recorded.sum() / s.vote_events.sum() if 'after_17_recorded' in s and s.vote_events.notna().any() else np.nan,
                                 manual_pct=100 * s.manual_bu.sum() / s.attendance.sum()))
        tot = e[e.is_agg]
        rows.append(dict(eid=eid, lab=X.LAB[eid], aptos='TODAS', agregada='sim', secoes=len(tot), close_med=tot.close_min.median(), gt60=100 * (tot.close_min > 60).mean(),
                         late_pct=100 * tot.after_17_recorded.sum() / tot.vote_events.sum() if 'after_17_recorded' in tot and tot.vote_events.notna().any() else np.nan, manual_pct=100 * tot.manual_bu.sum() / tot.attendance.sum(),
                         aptos_med=tot.eligible.median(), share_late_closers=100 * ((e.close_min > 60) & e.is_agg).sum() / max((e.close_min > 60).sum(), 1),
                         share_late_votes=100 * tot.after_17_recorded.sum() / e.after_17_recorded.sum() if 'after_17_recorded' in e and e.after_17_recorded.notna().any() else np.nan))
        nt = e[~e.is_agg]
        rows.append(dict(eid=eid, lab=X.LAB[eid], aptos='TODAS', agregada='não', secoes=len(nt), close_med=nt.close_min.median(), gt60=100 * (nt.close_min > 60).mean(),
                         late_pct=100 * nt.after_17_recorded.sum() / nt.vote_events.sum() if 'after_17_recorded' in nt and nt.vote_events.notna().any() else np.nan, manual_pct=100 * nt.manual_bu.sum() / nt.attendance.sum(),
                         aptos_med=nt.eligible.median()))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ (d)
def part_d():
    rows = []
    for eid, year in [('P2022b', 2022), ('M2024b', 2024)]:
        d = X.DATA[eid]
        c = d[d.cont_member.notna()].copy()
        prev = X.DATA['P2022' if year == 2022 else 'M2024']
        c = c.merge(prev[KEY + ['uf', 'urn_effective']].rename(columns={'urn_effective': 'urn_t1'}), on=['uf'] + KEY, how='left')
        c['cont'] = c.cont_start.notna()
        c['same_urn_as_t1'] = c.urn_effective == c.urn_t1
        fv = c.cont_first_vote_min
        rows.append(dict(lab=X.LAB[eid], logs_ambiguos=len(c), trocas_ceft=int((c.swap == True).sum()), com_contingencia=int(c.cont.sum()),
                         sem_troca_sem_contingencia=int(((c.swap != True) & ~c.cont).sum()), sem_troca_mesma_urna_t1=int(((c.swap != True) & c.same_urn_as_t1).sum()),
                         sem_troca_primeiro_voto_antes_8h15=int(((c.swap != True) & (fv < 495)).sum()), sem_troca_local_zero=int(((c.swap != True) & (c.locale_zero == True)).sum()),
                         troca_com_contingencia=int(((c.swap == True) & c.cont).sum()), troca_sem_contingencia=int(((c.swap == True) & ~c.cont).sum()),
                         trocas_ceft_total=int((d.swap == True).sum()), trocas_sem_log_ambiguo=int((d.swap == True).sum() - (c.swap == True).sum())))
    return pd.DataFrame(rows)


def build(A, scan, places, j, rec, size_tab, prof_tab, prof_reg, top, C, D):
    P, H1, H2, SM, NOTE = M.P, M.H1, M.H2, M.SM, M.NOTE
    st = [Paragraph('Desdobramentos: votos não registrados, fila recorrente por local, seções agregadas e logs do 2º turno', H1),
          Paragraph('Continuação da análise de encerramento e troca de urnas. Mesmos 10 estados. Descritivo; horários do relógio de cada urna.', P),
          Paragraph('(a) Os casos “O voto do eleitor NÃO foi registrado” — 2º turno de 2024', H2),
          Paragraph('Foram localizados nos logs das urnas recarregadas para o 2º turno (os que o leitor não identificava). Em cada caso: a urna habilitou o eleitor, registrou “voto confirmado para Prefeito” '
                    'e em seguida o erro; foi desligada e religada em 1 a 7 minutos; a votação seguiu. O comparecimento do boletim é igual ao número de votos computados no log, ou seja, o voto com erro não foi contado '
                    'e o eleitor votou depois (o log não identifica eleitores, então isso é inferido da igualdade das contagens).', P)]
    if len(A):
        t = [['UF', 'Município', 'Zona', 'Seção', 'Erro', 'Urna desligada', 'Religada', '1º voto computado', 'Votos no log', 'Comparecimento BU', 'Abertura BU', 'Encerramento BU', 'Vencedor na seção']]
        for r in A.sort_values(['erro', 'uf']).itertuples():
            t.append([r.uf, r.municipio, str(r.zona), str(r.secao), r.erro, r.hora_erro, r.religada, r.primeiro_voto, n(r.votos_log), n(r.comparecimento_bu), r.abertura_bu, r.encerramento_bu, r.vencedor])
        st += [M.table(t, font=6.3)]
    if scan is not None and len(scan):
        st += [Paragraph(f'Varredura de todos os logs do 2º turno de 2024 (inclusive os identificados normalmente): {n(len(scan))} urnas com a mensagem; códigos: ' +
                         ', '.join(f'{k}: {v}' for k, v in scan.codes.value_counts().items()) + '. Lista: _scan_voto_nao_registrado.csv.', P)]
    elif scan is not None:
        st += [Paragraph('Varredura de todos os logs do 2º turno de 2024 (inclusive os identificados normalmente): nenhuma outra urna com a mensagem além das listadas.', P)]
    st += [Paragraph('9 dos 10 casos têm o mesmo código (8044) e ocorrem no primeiro eleitor do dia, entre 8h01 e 8h10, em urnas recarregadas para o 2º turno; o 10º é falha de mídia externa ao meio-dia. '
                     'Isso aponta para um defeito de software na primeira votação após a recarga, não para algo relacionado ao eleitor ou à seção.', SM), PageBreak()]
    # (b)
    st += [Paragraph('(b) Locais de votação com fila recorrente nas três eleições gerais (2018, 2022, 2026)', H2),
           Paragraph('Local “tardio” = metade ou mais das suas seções encerrou >60 min após 17h. Recorrência = tardio nas três eleições, comparado ao esperado se cada eleição fosse independente (taxas observadas).', P)]
    t = [['Locais presentes nas 3 eleições', 'Tardio em 0', '1', '2', '3 eleições', 'Esperado em 2', 'Esperado em 3', 'ρ mediana encerr. 18×22', '22×26', '18×26']]
    t.append([n(rec['places']), n(rec['obs'][0]), n(rec['obs'][1]), n(rec['obs'][2]), n(rec['obs'][3]), n(rec['exp'][2], 1), n(rec['exp'][3], 1), n(rec['rho_18_22'], 2), n(rec['rho_22_26'], 2), n(rec['rho_18_26'], 2)])
    st += [M.table(t, font=7), Paragraph('Tamanho do local (2022): quanto mais seções no mesmo local, mais fila?', M.P)]
    t = [['Seções no local', 'Locais', 'Seções', 'Locais tardios %', 'Média da fração de seções tardias %', 'Mediana encerr. (min.)']]
    for r in size_tab.itertuples():
        t.append([str(r.size_bin), n(r.places), n(r.sections), n(r.late_place_pct, 2), n(r.late_share_mean, 2), n(r.close_med, 1)])
    st += [M.table(t, font=7)]
    if prof_tab is not None:
        st += [Paragraph('Perfil do eleitorado do local (perfil_eleitor_secao 2022, TSE) por quintis — % de locais tardios e encerramento mediano em 2022:', M.P)]
        t = [['Variável', 'Quintil', 'Locais', 'Média da variável', 'Locais tardios %', 'Mediana encerr. (min.)', 'Seções por local (média)']]
        for r in prof_tab.itertuples():
            t.append([r.variavel, r.quintil, n(r.locais), n(r.media_var, 1), n(r.late_place_pct, 2), n(r.close_med, 1), n(r.secoes_por_local, 1)])
        st += [M.table(t, font=6.3),
               Paragraph('Regressão linear simples (local = unidade; y = % de seções do local que encerraram >60 min, 2022) com todos os fatores juntos; coeficiente = variação em p.p. por +1 unidade da variável:', M.P)]
        t = [['Termo', 'Coeficiente', 'Erro-padrão', 'Locais']]
        for r in prof_reg.itertuples():
            t.append([r.termo, n(r.coef, 3), n(r.se, 3), n(r.n)])
        st += [M.table(t, [6 * cm, 3 * cm, 3 * cm, 3 * cm], font=7)]
    if top is not None and len(top):
        st += [PageBreak(), Paragraph(f'Locais tardios nas três eleições gerais ({n(len(top))}); 25 com mais votos após 17h em 2026', H2)]
        t = [['UF', 'Município', 'Zona', 'Local nº', 'Nome do local (2022)', 'Seções', 'Eleitores', '% 60+', '% até fund. inc.', '% biometria', 'Encerr. mediano 18 / 22 / 26 (min.)', 'Votos após 17h 2022 / 2026']]
        for r in top.head(25).itertuples():
            t.append([r.uf, r.municipality_name, str(r.zone), str(r.voting_place), (r.place_name or '')[:38], n(r.sections_26), n(r.voters), n(r.age60_pct, 1), n(r.low_school_pct, 1), n(r.biometria_pct, 1),
                      f'{n(r.close_med_18, 0)} / {n(r.close_med_22, 0)} / {n(r.close_med_26, 0)}', f'{n(r.late_votes_22)} / {n(r.late_votes_26)}'])
        st += [M.table(t, font=5.8), Paragraph('Lista completa: locais_tardios_recorrentes.csv.', SM)]
    # (c)
    st += [PageBreak(), Paragraph('(c) Seções agregadas como fator de fila', H2),
           Paragraph('Seção agregada = duas ou mais seções reunidas numa única urna (campo DS_AGREGADAS/DS_SECOES_AGREGADAS do boletim). Comparação com seções não agregadas de porte semelhante (faixas de aptos).', P)]
    t = [['Eleição', 'Aptos', 'Agregada', 'Seções', 'Mediana encerr. (min.)', '>60 min %', 'Votos após 17h (% dos votos)', 'Manual BU %']]
    for r in C[C.aptos != 'TODAS'].itertuples():
        t.append([r.lab, str(r.aptos), r.agregada, n(r.secoes), n(r.close_med, 1), n(r.gt60, 2), n(r.late_pct, 2), n(r.manual_pct, 1)])
    st += [M.table(t, font=6.3)]
    t = [['Eleição', 'Agregadas', 'Aptos (mediana)', 'Mediana encerr.', '>60 min %', 'Votos após 17h %', 'Não agregadas: aptos (mediana)', 'Mediana encerr.', '>60 min %', 'Parcela das seções >60 min que são agregadas', 'Parcela dos votos após 17h em agregadas']]
    for eid in X.FIRST:
        a = C[(C.eid == eid) & (C.aptos == 'TODAS') & (C.agregada == 'sim')].iloc[0]
        b = C[(C.eid == eid) & (C.aptos == 'TODAS') & (C.agregada == 'não')].iloc[0]
        t.append([a.lab, n(a.secoes), n(a.aptos_med), n(a.close_med, 1), n(a.gt60, 2), n(a.late_pct, 2), n(b.aptos_med), n(b.close_med, 1), n(b.gt60, 2), n(a.share_late_closers, 1), n(a.share_late_votes, 1)])
    st += [Paragraph('Totais:', M.P), M.table(t, font=6.3)]
    # (d)
    st += [PageBreak(), Paragraph('(d) Por que há mais logs “de contingência” do que trocas nos 2º turnos', H2),
           Paragraph('Os logs cujo conteúdo não identifica a seção (“ambíguos”) são de dois tipos: (1) urnas de contingência, que registram o “início do procedimento de contingência” no dia; '
                     '(2) urnas recarregadas entre o 1º e o 2º turno com a identificação do local de votação em branco (“Local de Votação: 0000”), que iniciaram normalmente às 8h e não constam como troca na '
                     'correspondência. O segundo tipo só existe nos 2º turnos.', P)]
    t = [['Eleição', 'Logs ambíguos', 'Trocas (CEFT) entre eles', 'Com procedimento de contingência', 'Sem troca e sem contingência', '… mesma urna do 1º turno', '… 1º voto antes de 8h15', '… local 0000',
          'Troca com contingência', 'Troca sem contingência no log', 'Trocas CEFT (total)', 'Trocas sem log ambíguo']]
    for r in D.itertuples():
        t.append([r.lab, n(r.logs_ambiguos), n(r.trocas_ceft), n(r.com_contingencia), n(r.sem_troca_sem_contingencia), n(r.sem_troca_mesma_urna_t1), n(r.sem_troca_primeiro_voto_antes_8h15),
                  n(r.sem_troca_local_zero), n(r.troca_com_contingencia), n(r.troca_sem_contingencia), n(r.trocas_ceft_total), n(r.trocas_sem_log_ambiguo)])
    st += [M.table(t, font=6.2),
           Paragraph('Conclusão: a diferença não é de trocas não registradas; é de urnas recarregadas para o 2º turno que perderam a identificação da seção no log. Para os 1º turnos, logs ambíguos e trocas coincidem quase um a um.', SM),
           Paragraph('Limites', H2)]
    for t_ in ['Horários são do relógio de cada urna; comparações entre tipos de eleição misturam anos.', 'O perfil do eleitorado é de 2022 e foi aplicado aos locais das três eleições gerais; locais mudam de composição.',
               'Associação entre perfil do local e fila não é causa: idade, escolaridade, biometria e porte do local são correlacionados entre si.', 'Nada aqui indica irregularidade nem a descarta.']:
        st.append(Paragraph('• ' + t_, P))

    def foot(c, d):
        c.setFont('Helvetica', 7)
        c.setFillColor(colors.grey)
        c.drawString(2 * cm, 1 * cm, 'Descritivo — não indica irregularidade nem a descarta')
        c.drawRightString(27.5 * cm, 1 * cm, f'pág. {d.page}')
    SimpleDocTemplate(str(OUT / 'DESDOBRAMENTOS.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.4 * cm, bottomMargin=1.6 * cm).build(st, onFirstPage=foot, onLaterPages=foot)


if __name__ == '__main__':
    for eid in ['P2018', 'P2022', 'P2022b', 'M2024', 'M2024b', 'P2026', 'M2020']:
        X.DATA[eid] = X.load(eid)
        print('loaded', eid, flush=True)
    A, scan = part_a()
    places, j, rec, size_tab, prof_tab, prof_reg, top = part_b()
    C = part_c()
    D = part_d()
    OUT.mkdir(parents=True, exist_ok=True)
    A.to_csv(OUT / 'a_votos_nao_registrados_2024t2.csv', sep=';', index=False, encoding='utf-8-sig')
    j.reset_index().round(3).to_csv(OUT / 'b_locais_tres_gerais.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    if top is not None:
        top.reset_index().round(3).to_csv(OUT / 'locais_tardios_recorrentes.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    size_tab.round(3).to_csv(OUT / 'b_tamanho_do_local.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    if prof_tab is not None:
        prof_tab.round(3).to_csv(OUT / 'b_perfil_quintis.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
        prof_reg.round(4).to_csv(OUT / 'b_regressao_local.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    C.round(3).to_csv(OUT / 'c_secoes_agregadas.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    D.to_csv(OUT / 'd_segundo_turno_logs_vs_trocas.csv', sep=';', index=False, encoding='utf-8-sig')
    build(A, scan, places, j, rec, size_tab, prof_tab, prof_reg, top, C, D)
    print('ok')
