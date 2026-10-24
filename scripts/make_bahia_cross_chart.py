"""Chart + full written data: manual enabling x late votes x winning party, per section (any state/office with logs)."""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate
import make_bahia_reports as M

OUT = M.OUT
CSV = OUT / 'dados_secoes'
CSV.mkdir(parents=True, exist_ok=True)
PCOL = {'PT': '#d62728', 'PL': '#1f77b4', 'PSD': '#ff7f0e', 'MDB': '#2ca02c', 'PSDB': '#17becf', 'UNIÃO': '#9467bd', 'PP': '#8c564b', 'PSB': '#e377c2',
        'PDT': '#bcbd22', 'REPUBLICANOS': '#7f7f7f', 'NOVO': '#ff9896', 'PODE': '#c5b0d5', 'DEM': '#98df8a', 'PSOL': '#f781bf', 'PV': '#2ca02c', 'PCdoB': '#d62728',
        'PSC': '#aec7e8', 'PROS': '#ffbb78', 'SD': '#c49c94', 'PMDB': '#2ca02c', 'PTB': '#9edae5', 'PRB': '#7f7f7f', 'PPS': '#dbdb8d', 'PSL': '#1f77b4', 'AVANTE': '#ff7f0e'}
FALLBACK = ['#e6550d', '#3182bd', '#31a354', '#756bb1', '#636363']
COLS = {'municipality': 'cod_municipio', 'municipality_name': 'municipio', 'zone': 'zona', 'section': 'secao', 'voting_place': 'local_votacao',
        'eligible': 'aptos', 'attendance': 'comparecimento', 'turnout_pct': 'comparecimento_pct', 'manual_bu': 'manual_bu',
        'manual_bu_pct': 'manual_bu_pct', 'manual_sequence_votes': 'manual_log', 'manual_log_pct': 'manual_log_pct',
        'vote_events': 'votos_log', 'after_17_recorded': 'votos_apos_17h', 'late_pct': 'apos_17h_pct',
        'after_17_manual_sequence': 'manuais_apos_17h', 'last_vote': 'ultimo_voto', 'winner': 'vencedor', 'winner_party': 'partido_vencedor',
        'winner_pct': 'vencedor_pct', 'margin_pp': 'margem_pp', 'raw_high_turnout': 'A_comparecimento_alto',
        'raw_high_late': 'B_tarde_alto', 'C_manual_alto': 'C_manual_alto', 'aggregation_raw': 'agregacao'}


def pcol(party, i):
    return PCOL.get(party, FALLBACK[i % len(FALLBACK)])


rows = []
tops = []
for k, label in M.RUNS:
    d = pd.read_parquet(M.analysis_dir(M.UF, k) / 'sections.parquet')
    summ = M.json.loads((M.analysis_dir(M.UF, k) / 'summary.json').read_text(encoding='utf-8'))
    tops.append([c['party'] for c in summ['candidates'][:2]])
    ok = d.vote_events.where(d.vote_events > 0)
    d['manual_log_pct'] = 100 * d.manual_sequence_votes / ok
    d['manual_bu_pct'] = 100 * d.manual_bu / d.attendance.where(d.attendance > 0)
    d['late_pct'] = 100 * d.after_17_recorded / ok
    d['turnout_pct'] = 100 * d.turnout
    d['recorte'] = label
    elig = d.operational_eligible == True
    d['manual_p99'] = d.loc[elig, 'manual_log_pct'].quantile(.99)
    d['late_p99'] = d.loc[elig, 'late_pct'].quantile(.99)
    d['C_manual_alto'] = (d.manual_log_pct > d.manual_p99).where(elig)
    d[['recorte'] + list(COLS)].rename(columns=COLS).to_csv(
        CSV / f'secoes_{k}.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig', float_format='%.2f')
    rows.append(d[d.vote_events > 0].copy())

n = len(rows)
f, ax = plt.subplots(1, n, figsize=(5 * n, 5.4), sharex=True, sharey=True, squeeze=False)
ax = ax[0]
for a, d, (p1, p2) in zip(ax, rows, tops):
    for i, (lab, m, c) in enumerate([(p1, d.winner_party == p1, pcol(p1, 0)), (p2, d.winner_party == p2, pcol(p2, 1)),
                                     ('Outros', ~d.winner_party.isin([p1, p2]), '#2ca02c')]):
        s = d[m]
        big = i > 0
        a.scatter(s.manual_log_pct, s.late_pct, s=np.clip(s.eligible / 40, 1, 14) * (2.5 if big else 1), alpha=.7 if big else .15, color=c, lw=0,
                  zorder=3 if big else 2, label=f'{lab} vence ({M.n(len(s))})')
    p, lp = d.manual_p99.iloc[0], d.late_p99.iloc[0]
    a.axvline(p, color='k', ls=':', lw=.8)
    a.axhline(lp, color='k', ls=':', lw=.8)
    hi = d[(d.manual_log_pct > p) & (d.late_pct > lp)]
    a.scatter(hi.manual_log_pct, hi.late_pct, s=40, facecolors='none', edgecolors='k', lw=.9, label=f'manual e tardio > P99 ({len(hi)})')
    a.set_title(d.recorte.iloc[0])
    a.set_xlabel('habilitação manual (% dos votos da seção, log)')
    a.legend(fontsize=7, loc='upper right', markerscale=2)
ax[0].set_ylabel('votos após 17h (% dos votos da seção)')
f.suptitle(f'{M.UFNAME} · {M.OFFICE_LABEL} — cada ponto é uma seção: manual × votos após 17h; cor = partido vencedor na seção; tamanho = aptos\n'
           'Linhas pontilhadas = P99 de cada eixo (2º colocado e outros desenhados por cima)', fontsize=10)
f.tight_layout()
f.savefig(M.FIG / 'cruzamento_secoes.png', dpi=170)
plt.close(f)


def base_rates(rows):
    out = []
    for d in rows:
        top = d.winner_party.value_counts()
        out.append(f"{d.recorte.iloc[0]}: {top.index[0]} vence {M.n(100 * top.iloc[0] / len(d), 1)}% das seções")
    return 'Base de vitórias por seção — ' + '; '.join(out) + '.'


st = [Paragraph(f'{M.UFNAME} · {M.OFFICE_LABEL} — Seções: habilitação manual × votos após 17h × partido vencedor', M.H1),
      Paragraph('Gráfico com todas as seções com log casado ao BU, seguido dos dados escritos. A lista completa de cada seção (local de votação, '
                'comparecimento, manual, votos após 17h, vencedor) está nos CSVs de <b>dados_secoes/</b>.', M.P),
      M.Image(str(M.FIG / 'cruzamento_secoes.png'), width=25.5 * cm, height=25.5 * cm * 5.4 / (5 * n)),
      Paragraph('Leitura: ' + base_rates(rows) + ' A composição partidária das seções sinalizadas deve ser lida contra essa base, não isoladamente.', M.SM),
      Paragraph('O local de votação aparece como o número do local (NR_LOCAL_VOTACAO) dentro do município; o nome do local não consta nos BUs usados.', M.SM),
      PageBreak(), Paragraph('Resumo: partido vencedor por perfil da seção', M.H2)]
data = [['Recorte', 'Perfil da seção', 'Seções', '1º do estado vence', '2º do estado vence', 'Outros', '% seções do 1º', 'Votos após 17h', 'Manuais (log)']]
for d, (p1, p2) in zip(rows, tops):
    p, lp = d.manual_p99.iloc[0], d.late_p99.iloc[0]
    hm, ht = d.manual_log_pct > p, d.late_pct > lp
    for name, m in [('Todas', hm | ~hm), ('Manual > P99', hm), ('Tardio > P99', ht), ('Manual > P99 e tardio > P99', hm & ht), ('Restante (nenhum > P99)', ~hm & ~ht)]:
        s = d[m]
        a1, a2 = (s.winner_party == p1).sum(), (s.winner_party == p2).sum()
        data.append([f'{d.recorte.iloc[0]} (1º {p1}, 2º {p2})' if name == 'Todas' else d.recorte.iloc[0], name, M.n(len(s)), M.n(a1), M.n(a2), M.n(len(s) - a1 - a2),
                     M.n(100 * a1 / len(s) if len(s) else np.nan, 1) + '%', M.n(s.after_17_recorded.sum()), M.n(s.manual_sequence_votes.sum())])
st += [M.table(data, [5.4 * cm, 5.4 * cm, 1.8 * cm, 2.4 * cm, 2.4 * cm, 1.6 * cm, 2.2 * cm, 2.6 * cm, 2.4 * cm], font=7),
       Paragraph('P99 do manual (log): ' + ' · '.join(f"{d.recorte.iloc[0]} {M.n(d.manual_p99.iloc[0], 1)}%" for d in rows) +
                 '; P99 de votos após 17h: ' + ' · '.join(f"{d.recorte.iloc[0]} {M.n(d.late_p99.iloc[0], 1)}%" for d in rows) +
                 '. “% seções do 1º” é a fração de seções em que o 1º colocado do estado teve mais votos, não o percentual de votos. Os perfis se sobrepõem: não somar as linhas.', M.SM)]
for d, (p1, p2) in zip(rows, tops):
    p, lp = d.manual_p99.iloc[0], d.late_p99.iloc[0]
    hi = d[(d.manual_log_pct > p) & (d.late_pct > lp)].sort_values('late_pct', ascending=False)
    st += [PageBreak(), Paragraph(f'{d.recorte.iloc[0]} — seções com manual e votos após 17h ambos acima do P99 ({len(hi)})', M.H2)]
    if hi.empty:
        st.append(Paragraph('Nenhuma seção.', M.P))
        continue
    r = [['Município', 'Zona', 'Seção', 'Local', 'Aptos', 'Comp.', 'Manual BU', 'Manual log', '% manual', 'Após 17h', '% após', 'Partido venc.', '% venc.']]
    for x in hi.itertuples():
        r.append([x.municipality_name, str(x.zone), str(x.section), str(x.voting_place), M.n(x.eligible), M.n(x.attendance), M.n(x.manual_bu),
                  M.n(x.manual_sequence_votes), M.n(x.manual_log_pct, 1), M.n(x.after_17_recorded), M.n(x.late_pct, 1), x.winner_party, M.n(x.winner_pct, 1)])
    st.append(M.table(r, font=7))
st.append(Paragraph('Sinalização descritiva: fila, falha do leitor biométrico, atraso de abertura ou seção grande explicam esses casos sem qualquer irregularidade. '
                    'O vencedor da seção descreve o resultado e não mede efeito de habilitação manual ou de horário.', M.NOTE))


def foot(c, d):
    c.setFont('Helvetica', 7)
    c.setFillColor(colors.grey)
    c.drawString(2 * cm, 1 * cm, 'Descritivo — não indica irregularidade por si só')
    c.drawRightString(27.5 * cm, 1 * cm, f'pág. {d.page}')


SimpleDocTemplate(str(OUT / '06_secoes_manual_tardio_partido.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                  topMargin=1.5 * cm, bottomMargin=1.6 * cm).build(st, onFirstPage=foot, onLaterPages=foot)
print('ok')
