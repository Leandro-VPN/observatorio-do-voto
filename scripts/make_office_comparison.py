"""President x Governor on the same sections: BU consistency, vote alignment, late-vote patterns and FE associations (PT and PL candidates)."""
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

import make_bahia_reports as M
import make_late_votes_study as S

OUT = Path('relatorios/comparativo_presidente_governador')
FIG = OUT / 'figuras'
FIG.mkdir(parents=True, exist_ok=True)
ORDER = S.ORDER
RUNS = S.RUNS
KEY = ['municipality', 'zone', 'section']
PARTIES = ['PT', 'PL']


def pdir(uf, k):
    return (Path('research/bahia-presidente-2022-2026') if uf == 'BA' else Path('research/estados') / uf) / k / 'analysis'


def gdir(uf, k):
    return Path('research/analysis/GOVERNADOR') / uf / k


def n(x, d=0):
    return M.n(x, d)


def main():
    base, align, grp, reg = [], [], [], []
    for uf in ORDER:
        for k, lab in RUNS:
            if not (gdir(uf, k) / 'summary.json').exists():
                continue
            cols = KEY + ['voting_place', 'eligible', 'attendance', 'valid_votes', 'total_votes', 'turnout', 'operational_eligible', 'after_17_recorded', 'vote_events',
                          'raw_high_late', 'raw_high_turnout', 'manual_sequence_votes', 'winner_party']
            p = pd.read_parquet(pdir(uf, k) / 'sections.parquet', columns=cols)
            g = pd.read_parquet(gdir(uf, k) / 'sections.parquet', columns=cols)
            m = p.merge(g, on=KEY, suffixes=('_p', '_g'))
            cp = pd.read_parquet(pdir(uf, k) / 'candidate_sections.parquet')
            cg = pd.read_parquet(gdir(uf, k) / 'candidate_sections.parquet')
            same_att = (m.attendance_p == m.attendance_g)
            both_el = (m.operational_eligible_p == True) & (m.operational_eligible_g == True)
            base.append(dict(uf=uf, k=k, lab=lab, sec_p=len(p), sec_g=len(g), matched=len(m), same_att=100 * same_att.mean(),
                             el_p=int((p.operational_eligible == True).sum()), el_g=int((g.operational_eligible == True).sum()), el_both=int(both_el.sum()),
                             turnout_p=100 * p.attendance.sum() / p.eligible.sum(), turnout_g=100 * g.attendance.sum() / g.eligible.sum(),
                             bn_p=100 * (1 - p.valid_votes.sum() / p.total_votes.sum()), bn_g=100 * (1 - g.valid_votes.sum() / g.total_votes.sum()),
                             late_p=100 * p.after_17_recorded.sum() / p.vote_events.sum(), late_g=100 * g.after_17_recorded.sum() / g.vote_events.sum(),
                             flagB_p=int((p.raw_high_late == True).sum()), flagB_g=int((g.raw_high_late == True).sum()),
                             flagB_both=int(((m.raw_high_late_p == True) & (m.raw_high_late_g == True)).sum()),
                             flagA_both=int(((m.raw_high_turnout_p == True) & (m.raw_high_turnout_g == True)).sum()), flagA_p=int((p.raw_high_turnout == True).sum()),
                             flagA_g=int((g.raw_high_turnout == True).sum())))
            e = m[both_el & (m.valid_votes_p > 0) & (m.valid_votes_g > 0) & (m.eligible_p >= 50)].copy()
            e['late'] = 100 * e.after_17_recorded_p / e.vote_events_p / 10.0
            e['lelig'] = np.log(e.eligible_p)
            e['turn'] = e.turnout_p * 10.0
            e['cl'] = e.zone.astype(str)
            e['place'] = e.municipality.astype(str) + '|' + e.zone.astype(str) + '|' + e.voting_place_p.astype(str)
            e['vc_sum'] = e.valid_votes_p.astype(float)
            e['any_late'] = e.after_17_recorded_p >= 1
            idx = e.set_index(KEY).index
            for party in PARTIES:
                vp = cp[cp.party == party].set_index(KEY).votes.reindex(idx).fillna(0).values
                gsub = cg[cg.party == party]
                if gsub.empty or gsub.candidate_number.nunique() != 1:
                    continue
                vg = gsub.set_index(KEY).votes.reindex(idx).fillna(0).values
                cand_g = gsub.candidate.iloc[0]
                cand_p = cp[cp.party == party].candidate.iloc[0]
                e['yp'] = 100 * vp / e.valid_votes_p
                e['yg'] = 100 * vg / e.valid_votes_g
                e['yd'] = e.yg - e.yp
                rho = stats.spearmanr(e.yp, e.yg)[0]
                align.append(dict(uf=uf, k=k, lab=lab, party=party, cand_p=cand_p, cand_g=cand_g, n=len(e), rho=rho,
                                  mean_p=np.average(e.yp, weights=e.vc_sum), mean_g=np.average(e.yg, weights=e.vc_sum),
                                  mad=np.average((e.yg - e.yp).abs(), weights=e.vc_sum), gov_votes=int(vg.sum()), pres_votes=int(vp.sum())))
                for gname, mask in (('Sem voto tardio', ~e.any_late), ('Com voto tardio', e.any_late),
                                    ('Decil mais tardio', e.late >= e.late.quantile(.9) if e.late.quantile(.9) > 0 else e.late > 0)):
                    s = e[mask]
                    if len(s) == 0:
                        continue
                    w = s.vc_sum
                    grp.append(dict(uf=uf, k=k, lab=lab, party=party, grupo=gname, sections=len(s), pres=np.average(s.yp, weights=w), gov=np.average(s.yg, weights=w)))
                for fe, cols_ in (('município', ['municipality']), ('local de votação', ['place'])):
                    row = dict(uf=uf, k=k, lab=lab, party=party, fe=fe, n=len(e))
                    for tag, y in (('pres', 'yp'), ('gov', 'yg'), ('diff', 'yd')):
                        b, se, nobs, ng = S.fe_regression(e, y, cols_)
                        row[f'{tag}_coef'], row[f'{tag}_se'] = b, se
                    reg.append(row)
        print('done', uf, flush=True)
    B, A, G, R = pd.DataFrame(base), pd.DataFrame(align), pd.DataFrame(grp), pd.DataFrame(reg)
    for tag in ('pres', 'gov', 'diff'):
        R[f'{tag}_lo'] = R[f'{tag}_coef'] - 1.96 * R[f'{tag}_se']
        R[f'{tag}_hi'] = R[f'{tag}_coef'] + 1.96 * R[f'{tag}_se']
        z = R[f'{tag}_coef'] / R[f'{tag}_se']
        R[f'{tag}_p'] = 2 * (1 - stats.norm.cdf(z.abs()))
    for fe in R.fe.unique():
        mk = R.fe == fe
        R.loc[mk, 'diff_q'] = S.bh(R.loc[mk, 'diff_p'].values)
    for name, df in (('base_bu', B), ('alinhamento', A), ('grupos_tardios', G), ('associacao', R)):
        df.round(4).to_csv(OUT / f'{name}.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    figures(R, G)
    pdf(B, A, G, R)
    print('ok')


def img(p, w):
    iw, ih = PI.open(p).size
    return Image(str(p), width=w * cm, height=w * cm * ih / iw)


def figures(R, G):
    for fe, tag in (('município', 'mun'), ('local de votação', 'place')):
        f, ax = plt.subplots(figsize=(5.8, 5.2))
        r = R[(R.fe == fe) & (R.k != '2022-t2')]
        for party, c in (('PT', '#d62728'), ('PL', '#1f77b4')):
            s = r[r.party == party]
            ax.errorbar(s.pres_coef, s.gov_coef, xerr=1.96 * s.pres_se, yerr=1.96 * s.gov_se, fmt='o', ms=4, color=c, alpha=.7, ecolor=c, elinewidth=.6, label=f'candidato do {party}')
        lim = max(abs(r.pres_coef).max(), abs(r.gov_coef).max()) * 1.2
        ax.plot([-lim, lim], [-lim, lim], 'k--', lw=.7)
        ax.axhline(0, color='k', lw=.5)
        ax.axvline(0, color='k', lw=.5)
        ax.set(xlabel='coeficiente — presidente (p.p. por +10 p.p. tardios)', ylabel='coeficiente — governador', title=f'Mesmas seções, efeito fixo de {fe}\n(1º turnos 2022 e 2026; linha tracejada = iguais)')
        ax.title.set_fontsize(8)
        ax.legend(fontsize=7)
        f.tight_layout()
        f.savefig(FIG / f'coef_{tag}.png', dpi=150)
        plt.close(f)


def pdf(B, A, G, R):
    P, H1, H2, SM, NOTE = M.P, M.H1, M.H2, M.SM, M.NOTE
    st = [Paragraph('Presidente × Governador nas mesmas seções — seguem a mesma lógica?', H1),
          Paragraph('Mesmas seções, mesmos logs de urna (o log registra a sessão inteira), cargos diferentes. Partidos comparados: PT e PL, que têm candidato nos dois cargos em parte dos estados e pleitos '
                    '(não há mapa de coligações no BU; candidatos apoiados mas de outro partido não entram). Pleitos: 2022 T1, 2022 T2 (governador só em BA, SP, RS, PE, SC) e 2026 T1.', P),
          Paragraph('Como ler: o que depende só do horário (votos após 17h, comparecimento) é praticamente o mesmo nos dois cargos por construção; o que difere entre cargos é o voto. '
                    'Comparações são entre seções, não entre eleitores.', NOTE),
          Paragraph('1. Base do boletim: os dois cargos descrevem as mesmas seções?', H2)]
    t = [['UF', 'Pleito', 'Seções pres.', 'Seções gov.', 'Pareadas', 'Compar. igual %', 'Elegíveis pres.', 'Elegíveis gov.', 'Elegíveis nos 2', 'Brancos+nulos pres. %', 'gov. %', '% tardio pres.', 'gov.', 'B nos dois / pres. / gov.', 'A nos dois / pres. / gov.']]
    for r in B.itertuples():
        t.append([r.uf, r.lab, n(r.sec_p), n(r.sec_g), n(r.matched), n(r.same_att, 1), n(r.el_p), n(r.el_g), n(r.el_both), n(r.bn_p, 1), n(r.bn_g, 1), n(r.late_p, 2), n(r.late_g, 2),
                  f'{n(r.flagB_both)} / {n(r.flagB_p)} / {n(r.flagB_g)}', f'{n(r.flagA_both)} / {n(r.flagA_p)} / {n(r.flagA_g)}'])
    st += [M.table(t, font=5.8),
           Paragraph('“Compar. igual %”: seções em que o comparecimento do BU de presidente e governador coincide. As seções “elegíveis” exigem log = comparecimento do cargo; por isso há menos elegíveis no governador. '
                     'Sinalizações A e B coincidem nos dois cargos apenas quando as seções são elegíveis nos dois.', SM), PageBreak()]
    st += [Paragraph('2. Alinhamento do voto nas mesmas seções (candidato do partido nos dois cargos)', H2),
           Paragraph('Para cada partido com candidato nos dois cargos: correlação (Spearman) entre a % do candidato a presidente e a do candidato a governador nas mesmas seções, e diferença absoluta média '
                     '(em p.p., ponderada por votos). Valor alto = o eleitorado da seção vota de forma parecida nos dois cargos.', P)]
    t = [['UF', 'Pleito', 'Partido', 'Candidato presidente', 'Candidato governador', 'Seções', 'Spearman', '% pres. (pond.)', '% gov. (pond.)', 'Dif. abs. média (p.p.)']]
    for r in A.itertuples():
        t.append([r.uf, r.lab, r.party, r.cand_p, r.cand_g, n(r.n), n(r.rho, 2), n(r.mean_p, 1), n(r.mean_g, 1), n(r.mad, 1)])
    st += [M.table(t, font=6.2), PageBreak()]
    st += [Paragraph('3. Seções com e sem votos tardios: o padrão dos dois cargos se parece?', H2),
           Paragraph('% dos votos válidos do candidato do partido, ponderada, em seções sem voto após 17h, com ≥1 voto e no decil mais tardio, para presidente e governador, nas mesmas seções. '
                     '“Lacuna” = (decil mais tardio) − (sem voto tardio): se presidente e governador tiverem lacunas de mesmo sinal e tamanho parecido, a diferença entre os grupos de seções '
                     'vem de características das seções (comuns aos dois cargos); se não, é específica do cargo.', P)]
    gp = G.pivot_table(index=['uf', 'k', 'lab', 'party'], columns='grupo', values=['pres', 'gov']).reset_index()
    gp.columns = ['_'.join([c for c in col if c]) for col in gp.columns]
    t = [['UF', 'Pleito', 'Partido', 'Pres. sem tardio', 'Pres. com tardio', 'Pres. decil', 'Gov. sem tardio', 'Gov. com tardio', 'Gov. decil', 'Lacuna pres. (decil − sem)', 'Lacuna gov.', 'Mesmo sinal?']]
    gaps = []
    for _, d in gp.iterrows():
        gp_ = d['pres_Decil mais tardio'] - d['pres_Sem voto tardio']
        gg = d['gov_Decil mais tardio'] - d['gov_Sem voto tardio']
        gaps.append((d['uf'], d['k'], d['party'], gp_, gg))
        t.append([d['uf'], d['lab'], d['party'], n(d['pres_Sem voto tardio'], 1), n(d['pres_Com voto tardio'], 1), n(d['pres_Decil mais tardio'], 1), n(d['gov_Sem voto tardio'], 1),
                  n(d['gov_Com voto tardio'], 1), n(d['gov_Decil mais tardio'], 1), n(gp_, 1), n(gg, 1), 'sim' if np.sign(gp_) == np.sign(gg) else 'não'])
    GP = pd.DataFrame(gaps, columns=['uf', 'k', 'party', 'gap_pres', 'gap_gov'])
    st += [M.table(t, font=6), PageBreak()]
    st += [Paragraph('4. Associação ajustada: % de votos tardios × voto, presidente vs governador (mesmas seções)', H2),
           Paragraph('Coeficiente de uma regressão da % do candidato na seção sobre a % de votos tardios (por +10 p.p.), com controle de log(aptos) e comparecimento, ponderada pelos votos válidos do presidente, '
                     'com efeito fixo de município (ou de local de votação). Mesmas seções nos dois cargos. “Diferença (gov − pres)” é a regressão da diferença entre as duas %, com seu próprio erro-padrão '
                     'agrupado por zona; q = Benjamini–Hochberg dentro de cada especificação.', P),
           img(FIG / 'coef_mun.png', 11.5), img(FIG / 'coef_place.png', 11.5), PageBreak()]
    for fe in ('município', 'local de votação'):
        t = [['UF', 'Pleito', 'Partido', 'Presidente: coef. [IC 95%]', 'Governador: coef. [IC 95%]', 'Diferença gov − pres [IC 95%]', 'q (diferença)']]
        for r in R[R.fe == fe].itertuples():
            t.append([r.uf, r.lab, r.party, f'{n(r.pres_coef, 2)} [{n(r.pres_lo, 2)}; {n(r.pres_hi, 2)}]', f'{n(r.gov_coef, 2)} [{n(r.gov_lo, 2)}; {n(r.gov_hi, 2)}]',
                      f'{n(r.diff_coef, 2)} [{n(r.diff_lo, 2)}; {n(r.diff_hi, 2)}]', n(r.diff_q, 3)])
        st += [Paragraph(f'Efeito fixo de {fe}', M.P), M.table(t, font=6.2), PageBreak()]
    # synthesis
    st += [Paragraph('5. Síntese (gerada dos números)', H2)]
    lines = []
    b1 = B[B.k != '2022-t2']
    lines.append(f'As mesmas seções: o comparecimento do BU coincide entre presidente e governador em {n(B.same_att.min(), 1)}% a {n(B.same_att.max(), 1)}% das seções, conforme estado e pleito. '
                 f'Nos 1º turnos, a % de votos após 17h é praticamente a mesma nos dois cargos (diferença máxima {n((b1.late_p - b1.late_g).abs().max(), 2)} p.p.).')
    lines.append(f'Brancos+nulos: governador {n((B.bn_g - B.bn_p).median(), 1)} p.p. a mais que presidente em mediana (mín. {n((B.bn_g - B.bn_p).min(), 1)}, máx. {n((B.bn_g - B.bn_p).max(), 1)}).')
    a1 = A[A.k != '2022-t2']
    for party in PARTIES:
        s = a1[a1.party == party]
        if len(s):
            lines.append(f'Candidatos do {party} nos dois cargos ({len(s)} casos, 1º turnos): correlação seção a seção entre as % mediana {n(s.rho.median(), 2)} (de {n(s.rho.min(), 2)} a {n(s.rho.max(), 2)}); '
                         f'diferença absoluta média mediana {n(s.mad.median(), 1)} p.p.')
    g1 = GP[GP.k != '2022-t2']
    lines.append(f'Lacuna entre seções do decil mais tardio e sem voto tardio (1º turnos): presidente e governador têm o mesmo sinal em {int((np.sign(g1.gap_pres) == np.sign(g1.gap_gov)).sum())} de {len(g1)} casos; '
                 f'correlação entre as lacunas {n(g1.gap_pres.corr(g1.gap_gov), 2)}; lacuna mediana presidente {n(g1.gap_pres.median(), 1)} p.p., governador {n(g1.gap_gov.median(), 1)} p.p.')
    for fe in ('município', 'local de votação'):
        r = R[(R.fe == fe) & (R.k != '2022-t2')]
        lines.append(f'Efeito fixo de {fe} (1º turnos, {len(r)} casos): mesmo sinal presidente/governador em {int((np.sign(r.pres_coef) == np.sign(r.gov_coef)).sum())}; '
                     f'correlação entre os coeficientes {n(r.pres_coef.corr(r.gov_coef), 2)}; |coef.| mediano presidente {n(r.pres_coef.abs().median(), 2)}, governador {n(r.gov_coef.abs().median(), 2)} p.p.; '
                     f'diferença gov−pres com q&lt;0,05 em {int((r.diff_q < .05).sum())} de {len(r)}.')
    for l in lines:
        st.append(Paragraph('• ' + l, P))
    st += [Paragraph('Limites', H2)]
    for t_ in ['A comparação só cobre PT e PL e só onde o partido tem candidato aos dois cargos; não há dados de coligação no BU.',
               'Associação entre seções não é efeito sobre eleitores; o log não liga voto a candidato nem a cargo.',
               'Seções “elegíveis” exigem log = comparecimento do cargo; restringir às elegíveis nos dois cargos reduz a amostra.',
               'Em 2022 T2 quase não há votos tardios e há poucas disputas de governador; as estimativas dessa rodada são instáveis (excluídas dos resumos de 1º turno).',
               'Nenhum resultado aqui indica irregularidade nem a descarta.']:
        st.append(Paragraph('• ' + t_, P))

    def foot(c, d):
        c.setFont('Helvetica', 7)
        c.setFillColor(colors.grey)
        c.drawString(2 * cm, 1 * cm, 'Descritivo e estatístico — não indica irregularidade nem a descarta')
        c.drawRightString(27.5 * cm, 1 * cm, f'pág. {d.page}')
    SimpleDocTemplate(str(OUT / 'COMPARATIVO_PRESIDENTE_X_GOVERNADOR.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                      topMargin=1.4 * cm, bottomMargin=1.6 * cm).build(st, onFirstPage=foot, onLaterPages=foot)


if __name__ == '__main__':
    main()
