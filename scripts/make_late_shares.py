"""Vote share (% of valid votes) of each candidate in section groups defined by votes after 17:00; per state and election."""
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer
from PIL import Image as PI

import make_bahia_reports as M
import make_late_votes_study as S

OUT = S.OUT
FIG = S.FIG
L1, L2 = ('PT', 'PL') if M.OFFICE == 'PRESIDENTE' else ('1º colocado', '2º colocado')
GROUPS = ['Estado inteiro (todas as seções)', 'Seções sem voto após 17h', 'Seções com ≥1 voto após 17h',
          'Seções no decil mais tardio (≥P90 do % tardio)', 'Seções sinalizadas regra B (>P99 e ≥20 votos)']
SHORT = ['Estado', 'Sem tardio', 'Com tardio', 'Decil tardio', 'Regra B']


def shares(d):
    v = d.vc_sum.sum()
    pt, pl = d.c1_votes.sum(), d.c2_votes.sum()
    return dict(secoes=len(d), validos=int(v), pt=100 * pt / v if v else np.nan, pl=100 * pl / v if v else np.nan,
                outros=100 * (v - pt - pl) / v if v else np.nan, pt_votos=int(pt), pl_votos=int(pl), outros_votos=int(v - pt - pl))


def main():
    all_, cands = S.load_all()
    rows = []
    for (uf, k, lab), df in all_.groupby(['uf', 'k', 'recorte'], sort=False):
        d = S.late_df(df)
        e = d[(d.operational_eligible == True) & (d.vc_sum > 0)]
        p90 = e.late_pct.quantile(.9)
        c = cands[(uf, k, 'pt_pl')]
        sel = {GROUPS[0]: df[df.vc_sum > 0], GROUPS[1]: e[e.after_17_recorded == 0], GROUPS[2]: e[e.after_17_recorded >= 1],
               GROUPS[3]: e[(e.late_pct >= p90) & (e.late_pct > 0)], GROUPS[4]: e[e.raw_high_late == True]}
        for g, sub in sel.items():
            rows.append(dict(uf=uf, estado=M.NAMES[uf], k=k, pleito=lab, grupo=g, pt_cand=c[0]['name'], pl_cand=c[1]['name'], c1_party=c[0]['party'], c2_party=c[1]['party'],
                             late_votes=int(sub.after_17_recorded.fillna(0).sum()), **shares(sub)))
    R = pd.DataFrame(rows)
    R.to_csv(OUT / 'percentual_por_candidato.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig', float_format='%.2f')
    with pd.ExcelWriter(OUT / 'percentual_por_candidato.xlsx', engine='xlsxwriter') as xw:
        for k, lab in S.RUNS:
            t = R[R.k == k][['estado', 'grupo', 'pt_cand', 'pl_cand', 'secoes', 'validos', 'pt', 'pl', 'outros', 'pt_votos', 'pl_votos', 'outros_votos']]
            t.columns = ['Estado', 'Grupo de seções', f'Candidato {L1}', f'Candidato {L2}', 'Seções', 'Votos válidos', f'% {L1}', f'% {L2}', '% Outros', f'Votos {L1}', f'Votos {L2}', 'Votos Outros']
            name = lab.replace('º', '').replace('·', '-').replace(' ', '_')
            t.round(2).to_excel(xw, sheet_name=name, index=False, freeze_panes=(1, 0))
            xw.sheets[name].set_column(0, 3, 30)
            xw.sheets[name].set_column(4, 11, 14)
    # figure: PT and PL share, groups side by side, per election
    for k, lab in S.RUNS:
        f, ax = plt.subplots(1, 2, figsize=(13, 3.8), sharey=True)
        x = np.arange(len(S.ORDER))
        for a, col, nm in zip(ax, ['pt', 'pl'], [f'Candidato: {L1}', f'Candidato: {L2}']):
            for i, (g, sh) in enumerate(zip(GROUPS[1:4], SHORT[1:4])):
                s = R[(R.k == k) & (R.grupo == g)].set_index('uf').reindex(S.ORDER)
                a.bar(x + (i - 1) * .27, s[col], .27, label=sh, color=['#8da0b8', '#2b6cb0', '#c05621'][i])
            s0 = R[(R.k == k) & (R.grupo == GROUPS[0])].set_index('uf').reindex(S.ORDER)
            a.scatter(x, s0[col], marker='_', s=300, color='k', zorder=3, label='Estado inteiro')
            a.set_xticks(x)
            a.set_xticklabels(S.ORDER)
            a.set_title(f'{nm} — % dos votos válidos · {lab}', fontsize=9)
        ax[0].set_ylabel('% dos votos válidos')
        ax[1].legend(fontsize=7, ncol=2)
        f.tight_layout()
        f.savefig(FIG / f'shares_{k}.png', dpi=140)
        plt.close(f)
    # PDF
    P, H1, H2, SM, NOTE = M.P, M.H1, M.H2, M.SM, M.NOTE
    st = [Paragraph('Percentual de votos de cada candidato nas seções com e sem votos após as 17h', H1),
          Paragraph(f'Para cada estado e pleito: % dos votos válidos do candidato {L1}, do candidato {L2} e dos demais candidatos (somados), em cinco grupos de seções. '
                    'Os grupos usam seções elegíveis (log identificado, igual ao BU, relógio coerente, ≥50 aptos); a linha “Estado inteiro” usa todas as seções do BU. '
                    'Percentuais são votos do candidato ÷ votos válidos do grupo (brancos e nulos fora). “Decil tardio” = seções com % de votos tardios no décimo superior do estado.', P),
          Paragraph('Atenção: diferença entre grupos mostra como as seções se distinguem, não o efeito dos votos tardios. Seções com mais votos tardios tendem a ser maiores e urbanas; '
                    'a comparação ajustada (mesmo município, mesmo local de votação) está em ANALISE_VOTOS_APOS_17H.pdf.', NOTE)]
    for k, lab in S.RUNS:
        sub = R[R.k == k]
        st += [PageBreak(), Paragraph(lab, H2), Image(str(FIG / f'shares_{k}.png'), width=25 * cm, height=25 * cm * 3.8 / 13)]
        t = [['Estado', f'Candidatos ({L1} · {L2})', 'Grupo de seções', 'Seções', 'Votos válidos', f'% {L1}', f'% {L2}', '% Outros']]
        for r in sub.itertuples():
            t.append([r.uf if r.grupo == GROUPS[0] else '', f'{r.pt_cand} · {r.pl_cand}' if r.grupo == GROUPS[0] else '', r.grupo.split(' (')[0],
                      M.n(r.secoes), M.n(r.validos), M.n(r.pt, 1), M.n(r.pl, 1), M.n(r.outros, 1)])
        half = 26
        st += [M.table(t[:half + 1], [1.3 * cm, 7 * cm, 7 * cm, 1.8 * cm, 2.6 * cm, 1.5 * cm, 1.5 * cm, 1.8 * cm], font=6.3), PageBreak(),
               M.table([t[0]] + t[half + 1:], [1.3 * cm, 7 * cm, 7 * cm, 1.8 * cm, 2.6 * cm, 1.5 * cm, 1.5 * cm, 1.8 * cm], font=6.3)]
    st += [Paragraph('Em 2022/2º turno os grupos “com tardio”, “decil” e “regra B” têm poucas seções (quase não houve voto após 17h): leia com cautela.', SM)]

    def foot(c, d):
        c.setFont('Helvetica', 7)
        c.setFillColor(colors.grey)
        c.drawString(2 * cm, 1 * cm, 'Descritivo — não indica irregularidade nem a descarta')
        c.drawRightString(27.5 * cm, 1 * cm, f'pág. {d.page}')
    SimpleDocTemplate(str(OUT / 'PERCENTUAL_POR_CANDIDATO.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                      topMargin=1.4 * cm, bottomMargin=1.6 * cm).build(st, onFirstPage=foot, onLaterPages=foot)
    print('ok')


if __name__ == '__main__':
    main()
