"""Simple table: result (winner, %, margin) in sections that had >=1 vote after 17:00, per state and election."""
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
import make_bahia_reports as M

OUT = M.Path('relatorios/votos_apos_17h') if M.OFFICE == 'PRESIDENTE' else M.Path('relatorios/governador/votos_apos_17h')
R = pd.read_csv(OUT / 'percentual_por_candidato.csv', sep=';', decimal=',')
R = R[R.grupo.str.startswith('Seções com ≥1')].copy()
R['vencedor'] = R.apply(lambda r: r.pt_cand if r.pt >= r.pl else r.pl_cand, axis=1)
R['partido'] = R.apply(lambda r: r.c1_party if r.pt >= r.pl else r.c2_party, axis=1)
R['pct_vencedor'] = R[['pt', 'pl']].max(axis=1)
R['pct_segundo'] = R[['pt', 'pl']].min(axis=1)
R['margem_pp'] = R.pct_vencedor - R.pct_segundo
R['votos_vencedor'] = R[['pt_votos', 'pl_votos']].max(axis=1)
R['votos_segundo'] = R[['pt_votos', 'pl_votos']].min(axis=1)
R['margem_votos'] = R.votos_vencedor - R.votos_segundo




wins = []
for r in R.itertuples():
    d = pd.read_parquet(M.analysis_dir(r.uf, r.k) / 'sections.parquet',
                        columns=['operational_eligible', 'vote_events', 'after_17_recorded', 'valid_votes', 'winner_party'])
    d = d[(d.operational_eligible == True) & (d.vote_events > 0) & (d.valid_votes > 0) & (d.after_17_recorded >= 1)]
    assert len(d) == r.secoes, (r.uf, r.k, len(d), r.secoes)
    w = d.winner_party.value_counts()
    wins.append(dict(sec_pt=int(w.get(r.c1_party, 0)), sec_pl=int(w.get(r.c2_party, 0)), sec_outros=int(len(d) - w.get(r.c1_party, 0) - w.get(r.c2_party, 0))))
R = pd.concat([R.reset_index(drop=True), pd.DataFrame(wins)], axis=1)
cols = ['uf', 'estado', 'pleito', 'secoes', 'sec_pt', 'sec_pl', 'sec_outros', 'validos', 'pt_votos', 'pl_votos', 'outros_votos', 'vencedor', 'partido', 'pct_vencedor', 'pct_segundo', 'margem_pp', 'margem_votos', 'outros', 'pt', 'pl']
R[cols].to_csv(OUT / 'resultado_secoes_com_votos_tardios.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig', float_format='%.2f')
R[cols].round(2).to_excel(OUT / 'resultado_secoes_com_votos_tardios.xlsx', index=False)
P = M.P
st = [Paragraph('Resultado nas seções que tiveram votos após as 17h — 10 estados', M.H1),
      Paragraph('Universo: apenas seções com pelo menos 1 voto concluído após as 17h (seções elegíveis: log = BU, relógio coerente, ≥50 aptos). '
                '% = votos do candidato ÷ votos válidos dessas seções (brancos e nulos fora). “Margem” = vencedor − 2º colocado, em pontos percentuais. '
                'O log não liga o voto a candidato: o resultado é o das seções, e não só dos eleitores que votaram tarde.', P)]
for k, lab in [('2022-t1', '2022 · 1º turno'), ('2022-t2', '2022 · 2º turno'), ('2026-t1', '2026 · 1º turno')]:
    s = R[R.k == k]
    t = [['UF', 'Seções com voto tardio', 'Seções vencidas: 1º', 'Seções vencidas: 2º', 'Outros', 'Votos do 1º', 'Votos do 2º', 'Vencedor (votos)', '% do 1º', '% do 2º', '% Outros', 'Margem (votos)']]
    for r in s.itertuples():
        t.append([r.uf, M.n(r.secoes), f'{M.n(r.sec_pt)} ({M.n(100 * r.sec_pt / r.secoes, 1)}%)', f'{M.n(r.sec_pl)} ({M.n(100 * r.sec_pl / r.secoes, 1)}%)', M.n(r.sec_outros),
                  M.n(r.pt_votos), M.n(r.pl_votos), f'{r.vencedor} ({r.partido})', M.n(r.pt, 1), M.n(r.pl, 1), M.n(r.outros, 1), M.n(r.margem_votos)])
    st += [Paragraph(lab, M.H2), M.table(t, [1.1 * cm, 2.4 * cm, 3.2 * cm, 3.2 * cm, 1.5 * cm, 2.3 * cm, 2.3 * cm, 4 * cm, 1.2 * cm, 1.2 * cm, 1.4 * cm, 2.2 * cm], font=6.8), Spacer(1, 6)]
def foot(c, d):
    c.setFont('Helvetica', 7); c.setFillColor(colors.grey); c.drawString(2 * cm, 1 * cm, 'Descritivo — não indica irregularidade nem a descarta')
SimpleDocTemplate(str(OUT / 'RESULTADO_SECOES_COM_VOTOS_TARDIOS.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.4 * cm, bottomMargin=1.6 * cm).build(st, onFirstPage=foot, onLaterPages=foot)
for k in ['2022-t1', '2022-t2', '2026-t1']:
    print('###', k)
    for r in R[R.k == k].itertuples():
        print(f"| {r.uf} | {r.secoes:,} | {r.sec_pt:,} ({100*r.sec_pt/r.secoes:.1f}%) | {r.sec_pl:,} ({100*r.sec_pl/r.secoes:.1f}%) | {r.sec_outros} | {r.pt_votos:,} | {r.pl_votos:,} | {r.pct_vencedor:.1f}% {r.partido} |".replace(',', '.'))
