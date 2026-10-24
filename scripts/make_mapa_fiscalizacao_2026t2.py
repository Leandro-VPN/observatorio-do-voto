"""Mapa operacional de fiscalização para o 2º turno de 2026 (25/10/2026): por estado, zona e local de votação, com as seções a checar.

Entrada: relatorios/fiscalizacao/varredura/ (prioridade_locais_2026_T2.csv, secoes_historico.csv, secoes_com_comportamento_por_eleicao.csv)
Saída:   relatorios/fiscalizacao/mapa_2026_T2/
         MAPA_FISCALIZACAO_2026T2_<UF>.xlsx  (abas: leia_me, resumo_zonas, locais, secoes_checklist)
         MAPA_FISCALIZACAO_2026T2_<UF>.pdf   (documento de campo: zona → locais → seções)
         MAPA_FISCALIZACAO_2026T2_GERAL.xlsx / .pdf (todos os estados)

Entram os locais de risco ALTO e MÉDIO da varredura. Seções a checar = seções do local com comportamento em 2026 T1 ou recorrente
(2+ eleições), existentes nos dados de 2026. Sinalização não é acusação.
"""
import os
from pathlib import Path

import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

os.environ.setdefault('UF', 'BA')
import make_bahia_reports as M  # noqa: E402

SRC = Path('relatorios/fiscalizacao/varredura')
OUT = Path('relatorios/fiscalizacao/mapa_2026_T2')
OUT.mkdir(parents=True, exist_ok=True)
KEY = ['municipality', 'zone', 'section']
PKEY = ['uf', 'municipality', 'zone', 'voting_place']
ORDER = ['BA', 'SP', 'MG', 'RJ', 'PR', 'RS', 'PE', 'CE', 'PA', 'SC', 'MA']
NAMES = M.NAMES
ELECS = [('P2022', '2022 T1'), ('P2022b', '2022 T2'), ('M2024', 'Pref 2024 T1'), ('M2024b', 'Pref 2024 T2'), ('P2026', '2026 T1')]
LAB = dict(ELECS)
CSV = dict(sep=';', decimal=',', encoding='utf-8-sig')
CHECK_COLS = ['fiscal_responsavel', 'hora_chegada', 'fila_as_17h (sim/não; nº pessoas)', 'habilitacoes_manuais_observadas (nº)', 'hora_ultimo_voto', 'hora_encerramento', 'troca_de_urna (sim/não)', 'observacoes']


def n(x, d=0):
    return M.n(x, d)


def tf(s):
    return s.astype(str).str.strip().isin(['True', 'true', '1', '1.0'])


def load():
    pl = pd.read_csv(SRC / 'prioridade_locais_2026_T2.csv', low_memory=False, **CSV)
    if 'prioridade_observacao' in pl:
        pl['nivel_risco'] = pl.prioridade_observacao      # nome interno mantido; rótulo de saída é "prioridade de observação"
    for c in ('pts_operacional', 'pts_resultado', 'sinal_resultado', 'secoes_dif_real_pres_local'):
        if c not in pl:
            pl[c] = np.nan
    pl = pl[pl.nivel_risco.isin(['alta', 'média'])].copy()
    pl['voting_place'] = pl.voting_place.astype(str)
    pl['place_name'] = pl.place_name.fillna('').astype(str)
    h = pd.read_csv(SRC / 'secoes_historico.csv', low_memory=False, **CSV)
    h['voting_place'] = h.voting_place.astype(str)
    h = h.merge(pl[PKEY + ['nivel_risco', 'pontos', 'direcao', 'secoes_dif_real_pres', 'recorrentes_2plus']].rename(columns={'direcao': 'direcao_local'}), on=PKEY, how='inner')
    present26 = h.BEH_P2026.notna() & (h.BEH_P2026.astype(str) != '')
    beh26 = tf(h.BEH_P2026)
    h = h[present26 & (beh26 | (h.n_eleicoes_comportamento >= 2))].copy()
    lg = pd.read_csv(SRC / 'secoes_com_comportamento_por_eleicao.csv', low_memory=False, **CSV)
    lg = lg[lg.eid == 'P2026'][['uf'] + KEY + ['after_17_recorded', 'after_17_manual_sequence', 'last_vote', 'close_min', 'swap', 'contingency', 'local_inteiro', 'cmp_level', 'cmp_n']]
    lg.columns = ['uf'] + KEY + ['tardios_26', 'manuais17_26', 'ultimo_voto_26', 'encerramento_min_apos_17h_26', 'troca_urna_26', 'contingencia_26', 'local_inteiro_26', 'comparacao_26', 'pares_26']
    h = h.merge(lg, on=['uf'] + KEY, how='left')
    return pl, h


def motivos(r):
    tard = [LAB[e] for e, _ in ELECS if r[f'_L_{e}']]
    man = [LAB[e] for e, _ in ELECS if r[f'_M_{e}']]
    parts = []
    if tard:
        parts.append('tardia: ' + ', '.join(tard))
    if man:
        parts.append('manual: ' + ', '.join(man))
    reais = []
    for e, lab in ELECS:
        if r[f'_B_{e}'] and r[f'_R_{e}'] and pd.notna(r[f'_D_{e}']):
            reais.append(f'{lab} {float(r[f"_D_{e}"]):+.1f} p.p. ({r[f"dir_{e}"]})')
    if reais:
        parts.append('dif. real vs vizinhas: ' + '; '.join(reais))
    if r.n_eleicoes_comportamento >= 2:
        parts.append(f'recorrente em {int(r.n_eleicoes_comportamento)} eleições')
    return ' | '.join(parts)


def observar(r):
    o = []
    if any(r[f'_L_{e}'] for e, _ in ELECS):
        o.append('fila e votação após 17h; horário do último voto e do encerramento')
    if any(r[f'_M_{e}'] for e, _ in ELECS):
        o.append('habilitação manual pelo mesário (eleitor sem biometria): quantas, com que justificativa')
    if str(r['local_inteiro_26']) == 'True':
        o.append('todo o local se comporta assim: observar também a coordenação do prédio')
    return '; '.join(o)


def build_tables(pl, h):
    # seções (checklist)
    s = h.copy()
    for e, _ in ELECS:
        s[f'_L_{e}'] = tf(s[f'LATE_{e}'])
        s[f'_M_{e}'] = tf(s[f'MANUAL_{e}'])
        s[f'_B_{e}'] = tf(s[f'BEH_{e}'])
        s[f'_R_{e}'] = tf(s[f'real_{e}'])
        s[f'_D_{e}'] = pd.to_numeric(s[f'dif_{e}'], errors='coerce')
    s['motivos'] = s.apply(motivos, axis=1)
    s['o_que_observar'] = s.apply(observar, axis=1)
    s['comportamento_2026_T1'] = np.where(tf(s.BEH_P2026), np.where(tf(s.LATE_P2026) & tf(s.MANUAL_P2026), 'tardia+manual', np.where(tf(s.LATE_P2026), 'tardia', 'manual')), 'não (recorrente)')
    s['dif_2026_T1_pp'] = pd.to_numeric(s.dif_P2026, errors='coerce')
    s['dif_real_2026_T1'] = np.where(tf(s.real_P2026), s.dir_P2026.astype(str) + np.where(s.cmp_P2026.astype(str) == 'local', '', ' (vs município)'), '')
    s['lado_A_2026_T1_pct'] = pd.to_numeric(s.A_P2026, errors='coerce')
    s['venc_secao_vs_vizinhas_2026'] = s.venc_P2026.astype(str) + ' vs ' + s.venc_cmp_P2026.astype(str)
    s['ultimo_voto_26'] = s.ultimo_voto_26.astype(str).str[-8:].replace({'nan': ''})
    cols = ['uf', 'municipality', 'municipality_name', 'zone', 'voting_place', 'place_name', 'nivel_risco', 'pontos', 'section', 'comportamento_2026_T1', 'tardios_26', 'manuais17_26', 'ultimo_voto_26',
            'encerramento_min_apos_17h_26', 'troca_urna_26', 'contingencia_26', 'dif_2026_T1_pp', 'dif_real_2026_T1', 'lado_A_2026_T1_pct', 'venc_secao_vs_vizinhas_2026', 'comparacao_26', 'pares_26',
            'n_eleicoes_comportamento', 'n_pres_dif_real', 'direcao', 'padrao_comportamento', 'padrao_desvio_resultado', 'votos_tardios_total', 'manuais_apos_17h_total', 'motivos', 'o_que_observar']
    s = s[cols].rename(columns={'municipality': 'cod_municipio', 'municipality_name': 'municipio', 'zone': 'zona', 'voting_place': 'cod_local', 'place_name': 'local', 'section': 'secao', 'nivel_risco': 'prioridade_local',
                                'pontos': 'pontos_local', 'direcao': 'direcao_secao'})
    s['nivel_local'] = s.prioridade_local   # alias do nome anterior
    for c in CHECK_COLS:
        s[c] = ''
    s['_lv'] = s.nivel_local.map({'alta': 0, 'média': 1})
    s = s.sort_values(['uf', 'zona', '_lv', 'pontos_local', 'cod_local', 'secao'], ascending=[True, True, True, False, True, True]).drop(columns='_lv')
    # locais
    s['tardios_26'] = s.tardios_26.fillna(0).astype(int)
    s['manuais17_26'] = s.manuais17_26.fillna(0).astype(int)
    agg = s.groupby(['uf', 'cod_municipio', 'zona', 'cod_local']).agg(secoes_a_checar_n=('secao', 'size'), secoes_a_checar=('secao', lambda x: ', '.join(str(int(v)) for v in sorted(x))),
                                                     secoes_comp_2026=('comportamento_2026_T1', lambda x: int((x != 'não (recorrente)').sum())), tardios_2026=('tardios_26', 'sum'),
                                                     manuais17_2026=('manuais17_26', 'sum'), secoes_dif_real_2026=('dif_real_2026_T1', lambda x: int((x != '').sum())),
                                                     ultimo_voto_mais_tarde_2026=('ultimo_voto_26', 'max'), local_inteiro_2026=('o_que_observar', lambda x: bool(x.str.contains('todo o local').any()))).reset_index()
    agg['voting_place'] = agg.cod_local
    L = pl.drop(columns=['secoes_a_checar']).merge(agg.drop(columns='cod_local'), left_on=['uf', 'municipality', 'zone', 'voting_place'], right_on=['uf', 'cod_municipio', 'zona', 'voting_place'], how='inner').drop(columns=['cod_municipio', 'zona'])
    L = L[['uf', 'municipality', 'municipality_name', 'zone', 'voting_place', 'place_name', 'nivel_risco', 'pontos', 'pts_operacional', 'pts_resultado', 'sinal_resultado', 'secoes_max', 'secoes_a_checar_n', 'secoes_a_checar',
           'secoes_comp_2026', 'secoes_dif_real_2026', 'tardios_2026', 'manuais17_2026', 'ultimo_voto_mais_tarde_2026', 'local_inteiro_2026', 'recorrentes_2plus', 'secoes_dif_real_pres', 'secoes_dif_real_pres_local', 'direcao',
           'votos_tardios_total', 'manuais_apos_17h_total', 'pts_recorrencia', 'pts_desvio_real_pres', 'pts_direcao_unica', 'pts_comportamento_2026', 'pts_local_inteiro', 'pts_volume', 'pts_so_presidenciais']]
    L = L.rename(columns={'municipality': 'cod_municipio', 'municipality_name': 'municipio', 'zone': 'zona', 'voting_place': 'cod_local', 'place_name': 'local', 'secoes_max': 'secoes_no_local', 'nivel_risco': 'prioridade_observacao'})
    L['nivel_risco'] = L.prioridade_observacao   # alias do nome anterior
    L['_lv'] = L.nivel_risco.map({'alta': 0, 'média': 1})
    L = L.sort_values(['uf', 'zona', '_lv', 'pontos'], ascending=[True, True, True, False]).drop(columns='_lv')
    # zonas
    Z = L.groupby(['uf', 'zona']).agg(municipios=('municipio', lambda x: ', '.join(sorted(set(x)))[:80]), locais=('cod_local', 'size'), locais_alta=('nivel_risco', lambda x: int((x == 'alta').sum())),
                                      locais_media=('nivel_risco', lambda x: int((x == 'média').sum())), locais_com_sinal_resultado=('sinal_resultado', lambda x: int(x.isin(['seções', 'seções + local']).sum())),
                                      secoes_a_checar=('secoes_a_checar_n', 'sum'), secoes_comp_2026=('secoes_comp_2026', 'sum'),
                                      tardios_2026=('tardios_2026', 'sum'), manuais17_2026=('manuais17_2026', 'sum'), pontos_max=('pontos', 'max')).reset_index()
    Z['fiscais_sugeridos'] = (Z.locais_alta + np.ceil(Z.locais_media / 2)).astype(int)
    Z = Z.sort_values(['uf', 'locais_alta', 'pontos_max'], ascending=[True, False, False])
    U = L.groupby('uf').agg(zonas=('zona', 'nunique'), municipios=('cod_municipio', 'nunique'), locais=('cod_local', 'size'), locais_alta=('nivel_risco', lambda x: int((x == 'alta').sum())),
                            locais_media=('nivel_risco', lambda x: int((x == 'média').sum())), locais_com_sinal_resultado=('sinal_resultado', lambda x: int(x.isin(['seções', 'seções + local']).sum())),
                            secoes_a_checar=('secoes_a_checar_n', 'sum'), tardios_2026=('tardios_2026', 'sum'), manuais17_2026=('manuais17_2026', 'sum')).reset_index()
    U['fiscais_sugeridos'] = Z.groupby('uf').fiscais_sugeridos.sum().reindex(U.uf).values
    U = U.set_index('uf').reindex([u for u in ORDER if u in U.uf.values]).reset_index()
    return s, L, Z, U


def readme():
    rows = [('Para que serve', 'Mapa para posicionar fiscais no 2º turno de 2026 (25/10/2026). Vem da varredura por local de votação: locais de prioridade de observação ALTA e MÉDIA, com as seções a checar. 11 estados.'),
            ('Como foi feito', 'Seções com votação tardia (após 17h acima do P99 do estado, último voto após 19h ou encerramento >60 min sem troca de urna) e/ou habilitação manual pelo mesário acima do esperado, '
                               'comparadas às demais seções do mesmo local. A prioridade do local soma recorrência, diferença acima do limiar frente às vizinhas, direção (presidenciais), comportamento em 2026 T1, volume e local inteiro atípico.'),
            ('Prioridade, não risco', 'A prioridade é uma ordem para observação presencial, não probabilidade de irregularidade. pts_operacional (fila/manual recorrente, volume, comportamento em 2026) e pts_resultado (diferenças de resultado) vêm separados; '
                                      'sinal_resultado diz se o local tem alguma seção com diferença acima do limiar ("seções"), só o prédio inteiro divergindo do município ("só local") ou nenhum.'),
            ('Seções a checar', 'Seções do local com comportamento em 2026 T1 ou recorrentes (2+ eleições), existentes em 2026. A coluna comportamento_2026_T1 diz o que ocorreu no 1º turno.'),
            ('Aba resumo_zonas', 'Locais alta/média por zona e sugestão de fiscais (1 por local de prioridade alta + 1 a cada 2 de média). É ponto de partida para alocação, não regra.'),
            ('Aba locais', 'Um local por linha, ordenado por zona e prioridade; pts_* mostram de onde vêm os pontos.'),
            ('Aba secoes_checklist', 'Uma seção por linha, com motivos, o que observar e colunas em branco para o fiscal preencher (chegada, fila às 17h, habilitações manuais, último voto, encerramento, troca de urna, observações).'),
            ('O que observar', 'Fila e votação após 17h (horário do último voto e do encerramento); habilitação manual de eleitor sem biometria (quantas e com que justificativa); troca/contingência de urna; coordenação do prédio quando o local inteiro se comporta assim.'),
            ('Lado A / B', 'Presidente: PT / PL. dif_2026_T1_pp = % do lado A na seção menos % nas seções vizinhas sem comportamento (ou nas seções comuns do município, quando não há vizinha comparável: marcado "(vs município)"); '
                           'dif_real = a diferença supera o limiar do estudo (|z| ≥ 2 e ≥5 p.p.).'),
            ('Limites', 'Nada aqui observa compra de voto ou intenção, nem em quem votaram os eleitores tardios ou habilitados manualmente; mede desvio operacional e de resultado frente aos vizinhos. Sinalização não é acusação. Use para olhar presencialmente e registrar.')]
    return pd.DataFrame(rows, columns=['campo', 'descricao'])


def xlsx(path, sheets, widths=None):
    with pd.ExcelWriter(path, engine='xlsxwriter') as xw:
        for nm, df in sheets:
            df = df.round(2)
            df.to_excel(xw, sheet_name=nm[:31], index=False, freeze_panes=(1, 0))
            ws = xw.sheets[nm[:31]]
            ws.autofilter(0, 0, len(df), max(len(df.columns) - 1, 0))
            if nm == 'leia_me':
                ws.set_column(0, 0, 22)
                ws.set_column(1, 1, 150)
            elif nm == 'secoes_checklist':
                for i, c in enumerate(df.columns):
                    ws.set_column(i, i, 34 if c in ('motivos', 'o_que_observar', 'observacoes') else (24 if c in CHECK_COLS or c == 'local' else 12))
            elif nm == 'locais':
                for i, c in enumerate(df.columns):
                    ws.set_column(i, i, 30 if c in ('local', 'secoes_a_checar') else 12)


def pdf_uf(uf, s, L, Z):
    P, H1, H2, SM, NOTE = M.P, M.H1, M.H2, M.SM, M.NOTE
    Lu, Zu, su = L[L.uf == uf], Z[Z.uf == uf], s[s.uf == uf]
    st = [Paragraph(f'Mapa de fiscalização — {NAMES[uf]} — 2º turno de 2026 (25/10/2026)', H1),
          Paragraph(f'{n(len(Lu))} locais de votação ({n(int((Lu.nivel_risco == "alta").sum()))} prioridade alta, {n(int((Lu.nivel_risco == "média").sum()))} média) em {n(Zu.zona.nunique())} zonas; '
                    f'{n(int(Lu.secoes_a_checar_n.sum()))} seções a checar. Fiscais sugeridos: {n(int(Zu.fiscais_sugeridos.sum()))} (1 por local de prioridade alta + 1 a cada 2 de média). '
                    f'Locais com alguma seção com diferença de resultado acima do limiar: {n(int(Lu.sinal_resultado.isin(["seções", "seções + local"]).sum()))}; os demais entram por fila/habilitação manual recorrentes, volume ou prédio inteiro divergente.', P),
          Paragraph('O que observar e registrar em cada seção: fila e votação após 17h (horário do último voto e do encerramento); habilitação manual de eleitor sem biometria (quantas e justificativa); '
                    'troca ou contingência de urna; quem coordena o prédio. Planilha com checklist por seção: MAPA_FISCALIZACAO_2026T2_' + uf + '.xlsx. Prioridade é ordem de observação, não probabilidade de irregularidade. Sinalização não é acusação.', NOTE),
          Paragraph('1. Zonas (ordem: mais locais de prioridade alta)', H2)]
    t = [['Zona', 'Municípios', 'Locais', 'Alta', 'Média', 'c/ sinal de resultado', 'Seções a checar', 'c/ comp. 2026 T1', 'Após 17h (2026 T1)', 'Manuais após 17h', 'Pontos máx.', 'Fiscais sug.']]
    for r in Zu.itertuples():
        t.append([str(r.zona), r.municipios[:60], n(r.locais), n(r.locais_alta), n(r.locais_media), n(r.locais_com_sinal_resultado), n(r.secoes_a_checar), n(r.secoes_comp_2026), n(r.tardios_2026), n(r.manuais17_2026), n(r.pontos_max), n(r.fiscais_sugeridos)])
    st += [M.table(t, font=6.2), PageBreak(), Paragraph('2. Locais por zona (prioridade alta primeiro) e seções a checar', H2)]
    for z, g in Lu.groupby('zona', sort=True):
        st.append(Paragraph(f'Zona {int(z)} — {", ".join(sorted(set(g.municipio)))[:90]} — {n(len(g))} locais ({n(int((g.nivel_risco == "alta").sum()))} alta), {n(int(g.secoes_a_checar_n.sum()))} seções', M.H2))
        t = [['Prior.', 'Pts', 'Oper.', 'Result.', 'Sinal de resultado', 'Município', 'Local', 'Nome do local', 'Seções no local', 'Seções a checar', 'Comp. 2026', 'Dif. 2026', 'Após 17h 26', 'Manuais 17h 26', 'Último voto 26', 'Direção', 'Local inteiro']]
        for r in g.itertuples():
            t.append([r.nivel_risco, n(r.pontos), n(r.pts_operacional), n(r.pts_resultado), str(r.sinal_resultado)[:18], r.municipio[:18], str(r.cod_local), (r.local or '')[:30], n(r.secoes_no_local), r.secoes_a_checar[:40], n(r.secoes_comp_2026), n(r.secoes_dif_real_2026),
                      n(r.tardios_2026), n(r.manuais17_2026), str(r.ultimo_voto_mais_tarde_2026)[-8:], r.direcao, 'sim' if r.local_inteiro_2026 else ''])
        st += [M.table(t, font=5.2), Spacer(1, 4)]
    alta = su[su.nivel_local == 'alta']
    if len(alta):
        st += [PageBreak(), Paragraph(f'3. Seções dos locais de prioridade ALTA ({n(len(alta))} seções) — motivos', H2)]
        t = [['Zona', 'Município', 'Local', 'Seção', '2026 T1', 'Após 17h', 'Man. 17h', 'Último voto', 'Encerr. (+min)', 'Dif. 26 p.p.', 'Acima do limiar', 'Venc. × viz.', 'Motivos']]
        for r in alta.itertuples():
            t.append([str(r.zona), r.municipio[:16], str(r.cod_local), str(int(r.secao)), r.comportamento_2026_T1, n(r.tardios_26), n(r.manuais17_26), r.ultimo_voto_26, n(r.encerramento_min_apos_17h_26),
                      n(r.dif_2026_T1_pp, 1), r.dif_real_2026_T1, r.venc_secao_vs_vizinhas_2026, r.motivos[:150]])
        st += [M.table(t, [1 * cm, 2.4 * cm, 1.1 * cm, 1 * cm, 1.9 * cm, 1.3 * cm, 1.3 * cm, 1.5 * cm, 1.5 * cm, 1.4 * cm, 1.6 * cm, 1.5 * cm, 8.7 * cm], font=5.2)]
    st += [Paragraph('Limites: a lista indica onde olhar, não conclui nada; fila pode ser só fila e habilitação manual pode ser só falha de biometria; não se sabe em quem votaram os eleitores tardios. Registre o observado com horário.', SM)]

    def foot(c, d_):
        c.setFont('Helvetica', 7)
        c.setFillColor(colors.grey)
        c.drawString(2 * cm, 1 * cm, f'Mapa de fiscalização {uf} — 2º turno 2026 — sinalização não é acusação')
        c.drawRightString(27.5 * cm, 1 * cm, f'pág. {d_.page}')
    SimpleDocTemplate(str(OUT / f'MAPA_FISCALIZACAO_2026T2_{uf}.pdf'), pagesize=landscape(A4), leftMargin=1.2 * cm, rightMargin=1.2 * cm, topMargin=1.3 * cm, bottomMargin=1.5 * cm).build(st, onFirstPage=foot, onLaterPages=foot)


def pdf_geral(L, Z, U):
    P, H1, H2, SM, NOTE = M.P, M.H1, M.H2, M.SM, M.NOTE
    st = [Paragraph(f'Mapa de fiscalização — 2º turno de 2026 (25/10/2026) — visão geral dos {n(U.uf.nunique())} estados', H1),
          Paragraph(f'{n(len(L))} locais de votação de prioridade alta ou média ({n(int((L.nivel_risco == "alta").sum()))} alta), {n(int(L.secoes_a_checar_n.sum()))} seções a checar, {n(int(U.fiscais_sugeridos.sum()))} fiscais sugeridos. '
                    f'{n(int(L.sinal_resultado.isin(["seções", "seções + local"]).sum()))} locais têm alguma seção com diferença de resultado acima do limiar; os demais entram por fila/habilitação manual recorrentes, volume ou prédio inteiro divergente. '
                    'Documentos por estado: MAPA_FISCALIZACAO_2026T2_<UF>.pdf e .xlsx (checklist por seção).', P),
          Paragraph('Ordem de alocação: locais de prioridade alta primeiro; dentro da zona, por pontos. Observar fila e votação após 17h, habilitação manual sem biometria, troca de urna e encerramento. '
                    'Prioridade é ordem de observação, não probabilidade de irregularidade. Sinalização não é acusação.', NOTE),
          Paragraph('1. Por estado', H2)]
    t = [['UF', 'Zonas', 'Municípios', 'Locais', 'Alta', 'Média', 'c/ sinal de resultado', 'Seções a checar', 'Após 17h (2026 T1)', 'Manuais após 17h', 'Fiscais sugeridos']]
    for r in U.itertuples():
        t.append([r.uf, n(r.zonas), n(r.municipios), n(r.locais), n(r.locais_alta), n(r.locais_media), n(r.locais_com_sinal_resultado), n(r.secoes_a_checar), n(r.tardios_2026), n(r.manuais17_2026), n(r.fiscais_sugeridos)])
    st += [M.table(t, font=7), Paragraph('2. Zonas com mais locais de prioridade alta (todas as UFs)', H2)]
    zz = Z.sort_values(['locais_alta', 'pontos_max'], ascending=False).head(40)
    t = [['UF', 'Zona', 'Municípios', 'Locais', 'Alta', 'Média', 'c/ sinal de resultado', 'Seções a checar', 'Após 17h 26', 'Manuais 17h 26', 'Pontos máx.', 'Fiscais sug.']]
    for r in zz.itertuples():
        t.append([r.uf, str(r.zona), r.municipios[:50], n(r.locais), n(r.locais_alta), n(r.locais_media), n(r.locais_com_sinal_resultado), n(r.secoes_a_checar), n(r.tardios_2026), n(r.manuais17_2026), n(r.pontos_max), n(r.fiscais_sugeridos)])
    st += [M.table(t, font=6.2), PageBreak(), Paragraph('3. Locais de prioridade alta (60 primeiros por pontos)', H2)]
    t = [['UF', 'Município', 'Zona', 'Local', 'Nome do local', 'Pts', 'Oper.', 'Result.', 'Sinal de resultado', 'Seções a checar', 'Comp. 26', 'Dif. 26', 'Após 17h 26', 'Man. 17h 26', 'Direção']]
    for r in L[L.nivel_risco == 'alta'].sort_values('pontos', ascending=False).head(60).itertuples():
        t.append([r.uf, r.municipio[:18], str(r.zona), str(r.cod_local), (r.local or '')[:30], n(r.pontos), n(r.pts_operacional), n(r.pts_resultado), str(r.sinal_resultado)[:18], r.secoes_a_checar[:40], n(r.secoes_comp_2026), n(r.secoes_dif_real_2026),
                  n(r.tardios_2026), n(r.manuais17_2026), r.direcao])
    st += [M.table(t, font=5.4), Paragraph('Limites: instrumento de priorização; fila pode ser só fila e habilitação manual pode ser só falha de biometria; não se sabe em quem votaram os eleitores tardios. Nada aqui indica irregularidade nem a descarta.', SM)]

    def foot(c, d_):
        c.setFont('Helvetica', 7)
        c.setFillColor(colors.grey)
        c.drawString(2 * cm, 1 * cm, 'Mapa de fiscalização — 2º turno 2026 — sinalização não é acusação')
        c.drawRightString(27.5 * cm, 1 * cm, f'pág. {d_.page}')
    SimpleDocTemplate(str(OUT / 'MAPA_FISCALIZACAO_2026T2_GERAL.pdf'), pagesize=landscape(A4), leftMargin=1.2 * cm, rightMargin=1.2 * cm, topMargin=1.3 * cm, bottomMargin=1.5 * cm).build(st, onFirstPage=foot, onLaterPages=foot)


def main():
    pl, h = load()
    s, L, Z, U = build_tables(pl, h)
    s.to_csv(OUT / 'secoes_checklist_todas.csv', index=False, **CSV)
    L.to_csv(OUT / 'locais_todos.csv', index=False, **CSV)
    Z.to_csv(OUT / 'zonas_todas.csv', index=False, **CSV)
    U.to_csv(OUT / 'resumo_por_uf.csv', index=False, **CSV)
    xlsx(OUT / 'MAPA_FISCALIZACAO_2026T2_GERAL.xlsx', [('leia_me', readme()), ('resumo_uf', U), ('resumo_zonas', Z), ('locais', L), ('secoes_checklist', s)])
    for uf in ORDER:
        if uf not in L.uf.values:
            continue
        xlsx(OUT / f'MAPA_FISCALIZACAO_2026T2_{uf}.xlsx', [('leia_me', readme()), ('resumo_zonas', Z[Z.uf == uf]), ('locais', L[L.uf == uf]), ('secoes_checklist', s[s.uf == uf])])
        pdf_uf(uf, s, L, Z)
        print('uf', uf, 'locais', int((L.uf == uf).sum()), 'secoes', int((s.uf == uf).sum()), flush=True)
    pdf_geral(L, Z, U)
    print(U.to_string(index=False))
    print('ok locais', len(L), 'secoes', len(s))


if __name__ == '__main__':
    main()
