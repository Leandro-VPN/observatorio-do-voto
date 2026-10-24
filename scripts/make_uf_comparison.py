"""Cross-state comparison PDF/CSV from per-UF analysis outputs (descriptive only)."""
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

import make_bahia_reports as M

ORDER = ['BA', 'SP', 'MG', 'RJ', 'PR', 'RS', 'PE', 'CE', 'PA', 'SC']
RUNS = [('2022-t1', '2022 T1'), ('2022-t2', '2022 T2'), ('2026-t1', '2026 T1')]
OUT = Path('relatorios') if M.OFFICE == 'PRESIDENTE' else Path('relatorios/governador')
OUT.mkdir(parents=True, exist_ok=True)


def root(uf):
    return Path('research/bahia-presidente-2022-2026') if uf == 'BA' else Path('research/estados') / uf


rows = []
for uf in ORDER:
    for k, lab in RUNS:
        f = M.analysis_dir(uf, k) / 'sections.parquet'
        if not f.exists():
            continue
        d = pd.read_parquet(f)
        t = d[d.vote_events > 0]
        e = d[d.operational_eligible == True]
        p99 = e.loc[:, 'vote_events'].index  # placeholder to keep e used
        ml = (t.manual_sequence_votes / t.vote_events) * 100
        c_thr = (e.manual_sequence_votes / e.vote_events).quantile(.99)
        c = (e.manual_sequence_votes / e.vote_events) > c_thr
        b = e.raw_high_late == True
        a_ = d.raw_high_turnout == True
        top = d.winner_party.value_counts()
        rows.append(dict(
            uf=uf, recorte=lab, secoes=len(d), aptos=int(d.eligible.sum()), comparecimento_pct=100 * d.attendance.sum() / d.eligible.sum(),
            votos_log=int(e.vote_events.sum()), apos_17h=int(e.after_17_recorded.sum()),
            apos_17h_pct=100 * e.after_17_recorded.sum() / max(e.vote_events.sum(), 1),
            secoes_com_voto_tardio_pct=100 * (e.after_17_recorded > 0).mean(),
            manual_bu=int(d.manual_bu.sum()), manual_bu_pct=100 * d.manual_bu.sum() / d.attendance.sum(),
            manual_log=int(t.manual_sequence_votes.sum()), manual_p99_pct=100 * c_thr,
            A=int(a_.sum()), B=int(b.sum()), C=int(c.sum()),
            A_pct=100 * a_.sum() / len(d), B_pct=100 * b.sum() / max(len(e), 1), C_pct=100 * c.sum() / max(len(e), 1),
            BC=int((b & c).sum()), ABC=int((a_.loc[e.index] & b & c).sum()),
            partido_mais_secoes=top.index[0], partido_mais_secoes_pct=100 * top.iloc[0] / len(d),
            cobertura_log_pct=100 * d.member.notna().mean()))
df = pd.DataFrame(rows)
df.to_csv(OUT / 'comparativo_estados.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig', float_format='%.3f')
M.FIG = OUT / 'figuras_comparativo'
M.FIG.mkdir(exist_ok=True, parents=True)

f, ax = plt.subplots(1, 4, figsize=(15, 4.2))
x = np.arange(len(ORDER))
for i, (k, lab) in enumerate(RUNS):
    s = df[df.recorte == lab].set_index('uf').reindex(ORDER)
    for a, col, ttl in zip(ax, ['comparecimento_pct', 'apos_17h_pct', 'manual_bu_pct', 'secoes_com_voto_tardio_pct'],
                           ['Comparecimento (%)', 'Votos após 17h (% dos votos)', 'Manual — BU (% do comparecimento)', 'Seções com ≥1 voto após 17h (%)']):
        a.bar(x + (i - 1) * .27, s[col], .27, label=lab if col == 'comparecimento_pct' else None, color=list(M.COL.values())[i])
        a.set_title(ttl, fontsize=9)
        a.set_xticks(x)
        a.set_xticklabels(ORDER, fontsize=8)
ax[0].legend(fontsize=7)
ax[0].set_ylim(60, 90)
f.tight_layout()
f.savefig(M.FIG / 'estados.png', dpi=150)
plt.close(f)

st = [Paragraph(M.OFFICE_LABEL + ' · Comparativo entre estados — 2022 (1º e 2º turnos) e 2026 (1º turno)', M.H1),
      Paragraph('Estados processados: ' + ', '.join(sorted(set(df.uf))) + '. Mesmo método e mesmos critérios brutos (A, B, C) em todos. '
                'Descritivo: comparar estados exige cuidado — porte das seções, filas, perfil do eleitorado e equipamento diferem.', M.P),
      M.Image(str(M.FIG / 'estados.png'), width=25 * cm, height=25 * cm * 4.2 / 15), Spacer(1, 6)]
hdr = ['UF', 'Recorte', 'Seções', 'Aptos', 'Compar. %', 'Após 17h %', 'Seções c/ tardio %', 'Manual BU %', 'P99 manual %', 'A', 'B', 'C', 'B∩C', 'A∩B∩C', 'Partido + seções', 'Cobertura log %']
tab = [hdr]
for r in df.itertuples():
    tab.append([r.uf, r.recorte, M.n(r.secoes), M.n(r.aptos), M.n(r.comparecimento_pct, 1), M.n(r.apos_17h_pct, 2), M.n(r.secoes_com_voto_tardio_pct, 1),
                M.n(r.manual_bu_pct, 1), M.n(r.manual_p99_pct, 1), M.n(r.A), M.n(r.B), M.n(r.C), M.n(r.BC), M.n(r.ABC),
                f'{r.partido_mais_secoes} ({M.n(r.partido_mais_secoes_pct, 0)}%)', M.n(r.cobertura_log_pct, 1)])
st += [PageBreak(), M.table(tab, font=6.5),
       Paragraph('A: comparecimento alto (z>3 e ≥10 p.p. acima da mediana municipal). B: fração de votos após 17h acima do P99 estadual e ≥20 votos. '
                 'C: proporção manual (log) acima do P99 estadual. Todos são triagem estatística, não evidência de irregularidade. '
                 'Pleitos de turno único de um mesmo ano e turnos diferentes não são comparáveis em fila/tarde.', M.SM)]


def foot(c, d):
    c.setFont('Helvetica', 7)
    c.setFillColor(colors.grey)
    c.drawString(2 * cm, 1 * cm, 'Descritivo — não indica irregularidade por si só')
    c.drawRightString(27.5 * cm, 1 * cm, f'pág. {d.page}')


SimpleDocTemplate(str(OUT / '00_comparativo_estados.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                  topMargin=1.5 * cm, bottomMargin=1.6 * cm).build(st, onFirstPage=foot, onLaterPages=foot)
print('ok', sorted(set(df.uf)))
