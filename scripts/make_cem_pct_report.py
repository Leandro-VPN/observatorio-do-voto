"""Relatorio: secoes com 100% dos validos para um candidato no 2o turno, eleicao por eleicao (le relatorios/verificacoes/cem_pct_2t/,
gerado por scripts/cem_pct_2t_anos.py). Saida: CEM_PCT_2T_ELEICOES.pdf
"""
import os
import sys
from pathlib import Path

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
os.environ.setdefault('UF', 'BA')
from make_bahia_reports import P, H1, H2, SM, NOTE, table, n  # noqa: E402

D = ROOT / 'relatorios' / 'verificacoes' / 'cem_pct_2t'
CSV = dict(sep=';', encoding='utf-8-sig', decimal=',')
LIM = 120  # lista completa no PDF ate este numero de secoes por eleicao; acima disso, as maiores (todas no XLSX)


def main():
    R = pd.read_csv(D / 'resumo_por_eleicao.csv', **CSV)
    UF = pd.read_csv(D / 'secoes_100pct_por_uf.csv', **CSV).set_index('uf')
    REG = pd.read_csv(D / 'secoes_100pct_por_regiao.csv', **CSV).set_index('regiao')
    L = pd.read_csv(D / 'secoes_100pct_todas_eleicoes.csv', low_memory=False, **CSV)
    pres = R[R.eleicao.str.startswith('Presidente')]

    st = [Paragraph('Seções com 100% dos votos válidos para um candidato no 2º turno: 2014 a 2026', H1),
          Paragraph('Para cada eleição com 2º turno, as seções em que um dos dois candidatos teve todos os votos válidos (branco e nulo à parte), '
                    'comparadas ao 1º turno da mesma seção e às outras seções do mesmo local de votação. Presidente em 2014, 2018, 2022 e 2026 '
                    '(país inteiro e exterior) e, em bloco separado, prefeito em 2024 nos municípios que tiveram 2º turno.', P),
          Paragraph('Fontes: 2014, 2018 e 2022, boletim de urna em CSV (BWEB) publicado pelo TSE por UF; 2026 e 2024, o boletim de urna de cada '
                    'urna nos arquivos de dados abertos. Mesma definição em todas as eleições. Seção com voto unânime acontece onde o eleitorado '
                    'é pequeno e homogêneo; nada aqui indica irregularidade por si só.', NOTE),
          Paragraph('Por eleição', H2)]
    t = [['Eleição', 'Seções\n(2º turno)', 'Seções\n100%', 'Por 100 mil\nseções', 'Seções com\n99% ou mais', 'Válidos no 2º\n(mediana)',
          '% no 1º turno\n(mediana)', 'Já 100%\nno 1º turno', 'Seção única\nno local', 'Outras do local:\n% (mediana)']]
    for r in R.itertuples():
        t.append([r.eleicao, n(r.secoes), n(r.secoes_100pct), n(r.por_100_mil_secoes, 1), n(r.secoes_99pct_ou_mais), n(r.validos_2t_mediana),
                  n(r.pct_1t_mesmo_cand_mediana, 1), n(r.ja_100pct_no_1t), n(r.secao_unica_no_local), n(r.outras_do_local_pct_mediana, 1)])
    st += [table(t, font=7, widths=[3 * cm, 2 * cm, 1.6 * cm, 2 * cm, 2 * cm, 2.2 * cm, 2.6 * cm, 2 * cm, 2 * cm, 2.6 * cm]),
           Paragraph('% do mesmo candidato no 1º turno: fatia que o candidato que teve 100% no 2º turno já tinha nos válidos do 1º turno, na mesma seção. '
                     'Outras do local: fatia do mesmo candidato no 2º turno nas outras seções do mesmo local de votação.', SM)]
    t = [['Eleição', 'Seções 100% por candidato', 'UFs com mais casos']]
    for r in R.itertuples():
        t.append([r.eleicao, r.por_candidato, r.ufs_com_mais_casos])
    st += [table(t, font=7, widths=[3 * cm, 12 * cm, 9 * cm])]
    if len(pres) > 1:
        ult, ant = pres.iloc[-1], pres.iloc[:-1]
        st += [Paragraph(f'<b>{ult.eleicao}</b>: {n(ult.secoes_100pct)} seções com 100% ({n(ult.por_100_mil_secoes, 1)} por 100 mil seções). '
                         + 'Nas eleições anteriores para presidente: ' + '; '.join(f'{r.eleicao[-4:]}, {n(r.secoes_100pct)} ({n(r.por_100_mil_secoes, 1)} por 100 mil)'
                                                                                   for r in ant.itertuples()) + '.', P)]

    st += [PageBreak()]
    t = [['Válidos no 2º turno'] + list(R.eleicao)]
    for k in ('1 a 10', '11 a 50', '51 a 100', '101 a 200', 'mais de 200'):
        t.append([k] + [n(v) for v in R[f'validos_{k}']])
    st += [Paragraph('Tamanho das seções com 100%', H2), table(t, font=7.5, widths=[3.5 * cm] + [3 * cm] * len(R))]

    cols = list(R.eleicao)
    ordem = ['Norte', 'Nordeste', 'Centro-Oeste (sem DF)', 'Distrito Federal', 'Sudeste', 'Sul', 'Exterior']
    t = [['Região'] + cols] + [[g] + [n(REG.loc[g, c]) if g in REG.index and c in REG and pd.notna(REG.loc[g, c]) else '—' for c in cols] for g in ordem]
    st += [Paragraph('Seções com 100% por região', H2), table(t, font=7.5, widths=[4 * cm] + [3 * cm] * len(cols)),
           Paragraph('Seções com 100% por UF', H2)]
    t = [['UF'] + cols] + [[u] + [n(UF.loc[u, c]) if c in UF and pd.notna(UF.loc[u, c]) else '—' for c in cols] for u in UF.index]
    st += [table(t, font=7, widths=[2 * cm] + [3 * cm] * len(cols)),
           Paragraph('Prefeito 2024: só os municípios com 2º turno; “—” = UF sem 2º turno municipal (o DF não tem eleição municipal).', SM)]

    for el in cols:
        c = L[L.eleicao == el]
        st += [PageBreak(), Paragraph(f'{el}: {n(len(c))} seções com 100%' + ('' if len(c) <= LIM else f' (as {LIM} maiores; todas no XLSX)'), H2)]
        if not len(c):
            st += [Paragraph('Nenhuma seção.', P)]
            continue
        t = [['UF', 'Município', 'Zona', 'Local', 'Seção', '100% para', 'Válidos\n2º t.', 'Branco+\nnulo 2º', 'Válidos\n1º t.', '% no 1º\n(mesmo cand.)',
              'Outras do local:\n% no 2º']]
        for r in c.sort_values('t2_validos', ascending=False).head(LIM).itertuples():
            t.append([r.uf, str(r.municipio)[:24], r.zone, r.voting_place, r.section, str(r.candidato)[:30], n(r.t2_validos), n(r.t2_branco + r.t2_nulo),
                      n(r.t1_validos), n(r.t1_pct_cand, 1), n(r.local_outras_t2_pct_cand, 1) if r.local_outras_secoes else 'seção única'])
        st += [table(t, font=6.6, widths=[0.9 * cm, 3.8 * cm, 1 * cm, 1.1 * cm, 1.1 * cm, 5.2 * cm, 1.5 * cm, 1.5 * cm, 1.5 * cm, 2 * cm, 2.6 * cm])]

    st += [Paragraph('Limites: só seções que existem nos dois turnos; seções agregadas ou criadas entre os turnos ficam de fora ou mudam de eleitorado. '
                     'O voto é secreto: uma seção com 100% diz o total da urna, não quem votou. Como repetir: scripts/bu_capture_all.py --offices PRESIDENTE, '
                     'scripts/virada_1t_2t_2026.py, scripts/cem_pct_2t_anos.py (coleta_2024 e analise) e scripts/make_cem_pct_report.py. '
                     'Arquivos: CEM_PCT_2T_ELEICOES.xlsx, resumo_por_eleicao.csv, secoes_100pct_todas_eleicoes.csv, secoes_100pct_por_uf.csv, '
                     'secoes_100pct_por_regiao.csv.', SM)]

    def footer(cv, doc):
        cv.setFont('Helvetica', 7); cv.setFillColor(colors.grey)
        cv.drawString(1.5 * cm, 1 * cm, 'Análise independente e apartidária de dados públicos do TSE · descritivo — não indica irregularidade por si só')
        cv.drawRightString(28.2 * cm, 1 * cm, f'pág. {doc.page}')
    SimpleDocTemplate(str(D / 'CEM_PCT_2T_ELEICOES.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm,
                      bottomMargin=1.6 * cm, title='Seções com 100% no 2º turno, 2014 a 2026', author='AuditaBR').build(st, onFirstPage=footer, onLaterPages=footer)
    print('OK', D / 'CEM_PCT_2T_ELEICOES.pdf')


if __name__ == '__main__':
    main()
