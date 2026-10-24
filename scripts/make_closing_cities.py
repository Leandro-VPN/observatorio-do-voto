"""Closing-time base by city: number of urns (sections), mean/median closing time, urns outside the state pattern, and who wins (city and outlier urns).

Closing time = BU field DT_ENCERRAMENTO, minutes after 17:00. Available 2018 onward (2012, 2014, 2016 BUs have no closing time).
Outlier rule: closing minutes above (state mean + 2 SD) = 'tardia fora do padrão'; below (mean - 2 SD) = 'cedo fora do padrão'. Mean/SD per state and election, sections with >=50 voters.
Output: relatorios/encerramento_cidades/{PRESIDENTE,GOVERNADOR,PREFEITO}_encerramento_por_cidade.xlsx + CSV + PDF summary."""
import os
from pathlib import Path

import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

os.environ.setdefault('UF', 'BA')
import make_bahia_reports as M

OUT = Path('relatorios/encerramento_cidades')
OUT.mkdir(parents=True, exist_ok=True)
ORDER = ['BA', 'SP', 'MG', 'RJ', 'PR', 'RS', 'PE', 'CE', 'PA', 'SC']
KEY = ['municipality', 'zone', 'section']
ELECS = [('PRESIDENTE', 2018, 1), ('PRESIDENTE', 2018, 2), ('PRESIDENTE', 2022, 1), ('PRESIDENTE', 2022, 2), ('PRESIDENTE', 2026, 1),
         ('GOVERNADOR', 2018, 1), ('GOVERNADOR', 2018, 2), ('GOVERNADOR', 2022, 1), ('GOVERNADOR', 2022, 2), ('GOVERNADOR', 2026, 1),
         ('PREFEITO', 2020, 1), ('PREFEITO', 2020, 2), ('PREFEITO', 2024, 1), ('PREFEITO', 2024, 2)]


def n(x, d=0):
    return M.n(x, d)


def adir(office, uf, year, turn):
    if office == 'PRESIDENTE' and year in (2022, 2026):
        return (Path('research/bahia-presidente-2022-2026') if uf == 'BA' else Path('research/estados') / uf) / f'{year}-t{turn}' / 'analysis'
    return Path('research/analysis') / office / uf / f'{year}-t{turn}'


def closing_minutes(s):
    t = pd.to_datetime(s, format='%d/%m/%Y %H:%M:%S', errors='coerce')
    t = t.fillna(pd.to_datetime(s, format='%Y-%m-%d %H:%M:%S', errors='coerce'))
    return t.dt.hour * 60 + t.dt.minute + t.dt.second / 60 - 1020


def one(office, year, turn):
    cities, params, ofc = [], [], []
    for uf in ORDER:
        f = adir(office, uf, year, turn)
        if not (f / 'summary.json').exists():
            continue
        s = pd.read_parquet(f / 'sections.parquet', columns=KEY + ['municipality_name', 'eligible', 'attendance', 'valid_votes', 'closure_bu'])
        c = pd.read_parquet(f / 'candidate_sections.parquet')
        s['close'] = closing_minutes(s.closure_bu)
        base = s[(s.eligible >= 50) & s.close.notna()]
        mu, sd = base.close.mean(), base.close.std()
        s['late_out'] = s.close > mu + 2 * sd
        s['early_out'] = s.close < mu - 2 * sd
        params.append(dict(uf=uf, sections=len(s), with_time=int(s.close.notna().sum()), mean=mu, sd=sd, threshold=mu + 2 * sd, late_out=int(s.late_out.sum()), early_out=int(s.early_out.sum())))
        g = s.groupby('municipality').agg(municipio=('municipality_name', 'first'), urnas=('section', 'size'), aptos=('eligible', 'sum'), comparecimento=('attendance', 'sum'),
                                          media_min=('close', 'mean'), mediana_min=('close', 'median'), max_min=('close', 'max'), fora_tarde=('late_out', 'sum'),
                                          fora_cedo=('early_out', 'sum'), aptos_fora=('eligible', lambda x: 0)).reset_index()
        g['aptos_fora'] = g.municipality.map(s[s.late_out].groupby('municipality').eligible.sum()).fillna(0)
        cc = c.merge(s[KEY + ['late_out']], on=KEY, how='left')

        def top2(df):
            t = df.groupby(['municipality', 'candidate_number', 'candidate', 'party']).votes.sum().reset_index()
            t['valid'] = t.groupby('municipality').votes.transform('sum')
            t = t.sort_values(['municipality', 'votes', 'candidate_number'], ascending=[True, False, True])
            t['r'] = t.groupby('municipality').cumcount() + 1
            w = t[t.r == 1].set_index('municipality')
            r2 = t[t.r == 2].set_index('municipality')
            out = pd.DataFrame({'venc': w.candidate, 'venc_partido': w.party, 'venc_votos': w.votes, 'valid': w.valid, 'seg': r2.candidate, 'seg_partido': r2.party, 'seg_votos': r2.votes})
            out['venc_pct'] = 100 * out.venc_votos / out.valid
            out['seg_pct'] = 100 * out.seg_votos / out.valid
            return out
        a = top2(cc).add_prefix('c_')
        b = top2(cc[cc.late_out == True]).add_prefix('o_')
        g = g.join(a, on='municipality').join(b, on='municipality')
        g.insert(0, 'uf', uf)
        cities.append(g)
    return pd.concat(cities, ignore_index=True), pd.DataFrame(params)


def main():
    summary, pdf_blocks = [], []
    writers = {o: pd.ExcelWriter(OUT / f'{o}_encerramento_por_cidade.xlsx', engine='xlsxwriter') for o in ('PRESIDENTE', 'GOVERNADOR', 'PREFEITO')}
    allrows = []
    for office, year, turn in ELECS:
        g, P = one(office, year, turn)
        g['pct_fora'] = 100 * g.fora_tarde / g.urnas
        g['mesmo_vencedor'] = np.where(g.o_venc.notna(), np.where(g.o_venc == g.c_venc, 'sim', 'não'), '—')
        tag = f'{year}_T{turn}'
        t = g[['uf', 'municipality', 'municipio', 'urnas', 'aptos', 'comparecimento', 'media_min', 'mediana_min', 'max_min', 'fora_tarde', 'pct_fora', 'fora_cedo', 'aptos_fora',
               'c_venc', 'c_venc_partido', 'c_venc_pct', 'c_seg', 'c_seg_partido', 'c_seg_pct', 'o_venc', 'o_venc_partido', 'o_venc_pct', 'o_seg', 'o_seg_pct', 'mesmo_vencedor']].copy()
        t.columns = ['UF', 'Cód. município', 'Município', 'Urnas (seções)', 'Aptos', 'Comparecimento', 'Média min. após 17h (cidade)', 'Mediana min.', 'Máx. min.',
                     'Urnas tardias fora do padrão (> média+2DP do estado)', '% das urnas', 'Urnas cedo fora do padrão', 'Aptos nas urnas tardias fora do padrão',
                     'Vencedor na cidade', 'Partido', '% votos válidos', '2º colocado', 'Partido 2º', '% 2º', 'Vencedor nas urnas tardias fora do padrão', 'Partido (urnas fora)',
                     '% votos válidos (urnas fora)', '2º nas urnas fora', '% 2º (urnas fora)', 'Mesmo vencedor da cidade?']
        t.round(2).to_excel(writers[office], sheet_name=tag, index=False, freeze_panes=(1, 3))
        ws = writers[office].sheets[tag]
        ws.autofilter(0, 0, len(t), len(t.columns) - 1)
        ws.set_column(0, 1, 9)
        ws.set_column(2, 2, 28)
        ws.set_column(3, 30, 15)
        P2 = P.assign(office=office, year=year, turn=turn)
        P2.round(2).to_excel(writers[office], sheet_name=f'param_{tag}', index=False)
        t.insert(0, 'Cargo', office)
        t.insert(1, 'Ano', year)
        t.insert(2, 'Turno', turn)
        allrows.append(t)
        out = g[g.fora_tarde > 0]
        tot_c, tot_f = g.urnas.sum(), g.fora_tarde.sum()
        summary.append(dict(office=office, year=year, turn=turn, cities=len(g), urnas=int(tot_c), mean=np.average(P['mean'], weights=P.with_time), late_out=int(tot_f), pct_out=100 * tot_f / tot_c,
                            cities_with_out=len(out), same_winner=100 * (out.mesmo_vencedor == 'sim').mean() if len(out) else np.nan,
                            share_diff=(out.o_venc_pct - out.c_venc_pct).where(out.mesmo_vencedor == 'sim').mean() if len(out) else np.nan))
        print('done', office, year, turn, len(g), flush=True)
        pdf_blocks.append((office, year, turn, g, P))
    for w in writers.values():
        w.close()
    pd.concat(allrows, ignore_index=True).to_csv(OUT / 'encerramento_por_cidade_todas_as_eleicoes.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig', float_format='%.2f')
    SM = pd.DataFrame(summary)
    SM.round(3).to_csv(OUT / 'resumo_por_eleicao.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    build_pdf(SM, pdf_blocks)
    print('ok')


def build_pdf(SM, blocks):
    P, H1, H2, SMs, NOTE = M.P, M.H1, M.H2, M.SM, M.NOTE
    st = [Paragraph('Encerramento de seção por cidade — urnas fora do padrão e quem ganha', H1),
          Paragraph('Base: horário de encerramento da seção no boletim de urna (DT_ENCERRAMENTO), em minutos após as 17h00, disponível de 2018 em diante. '
                    '“Urna” = seção. Para cada eleição e estado calculei a média e o desvio-padrão do tempo de encerramento (seções com ≥50 eleitores); “urna tardia fora do padrão” = encerra mais de '
                    '2 desvios-padrão acima da média do estado (“cedo fora do padrão”: abaixo). Por cidade: número de urnas, média/mediana, quantas urnas fora do padrão, e quem ganha na cidade '
                    'e nessas urnas (% dos votos válidos). Listas completas por cidade: planilhas .xlsx desta pasta.', P),
          Paragraph('O encerramento inclui o tempo de fechar a urna (mediana de 5 a 9 min depois do último voto, medido em 2022 e 2026) e é aproximação dos votos tardios, não a contagem deles. '
                    'Urna fora do padrão pode refletir fila, atraso de abertura, substituição de urna ou seção grande. A urna ganhar ou perder um candidato nessas urnas descreve onde elas estão; '
                    'não mede efeito do horário.', NOTE),
          Paragraph('1. Resumo por eleição (10 estados)', H2)]
    t = [['Cargo', 'Ano', 'Turno', 'Cidades', 'Urnas', 'Média min. após 17h (média dos estados)', 'Urnas tardias fora do padrão', '% das urnas', 'Cidades com ≥1', 'Mesmo vencedor da cidade nas urnas fora %', 'Dif. média % do vencedor (urnas fora − cidade), p.p.']]
    for r in SM.itertuples():
        t.append([r.office.title(), str(r.year), str(r.turn), n(r.cities), n(r.urnas), n(r.mean, 1), n(r.late_out), n(r.pct_out, 2), n(r.cities_with_out), n(r.same_winner, 1), n(r.share_diff, 1)])
    st += [M.table(t, font=6.5), PageBreak()]
    for office, year, turn, g, Pp in blocks:
        if turn != 1:
            continue
        st += [Paragraph(f'{office.title()} {year} — 1º turno', H2)]
        tt = [['UF', 'Urnas', 'Com horário', 'Média min.', 'DP min.', 'Limite (média+2DP) min.', 'Urnas tardias fora', 'Urnas cedo fora']]
        for r in Pp.itertuples():
            tt.append([r.uf, n(r.sections), n(r.with_time), n(r.mean, 1), n(r.sd, 1), n(r.threshold, 1), n(r.late_out), n(r.early_out)])
        st += [M.table(tt, font=6.8), Paragraph('Cidades com maior % de urnas tardias fora do padrão (≥20 urnas):', M.P)]
        top = g[g.urnas >= 20].sort_values(['pct_fora', 'fora_tarde'], ascending=False).head(12)
        tt = [['UF', 'Município', 'Urnas', 'Média min.', 'Fora do padrão', '% das urnas', 'Vencedor na cidade', '% venc.', 'Vencedor nas urnas fora', '% venc. (fora)']]
        for r in top.itertuples():
            tt.append([r.uf, r.municipio, n(r.urnas), n(r.media_min, 1), n(r.fora_tarde), n(r.pct_fora, 1), f'{r.c_venc} ({r.c_venc_partido})', n(r.c_venc_pct, 1),
                       f'{r.o_venc} ({r.o_venc_partido})' if isinstance(r.o_venc, str) else '—', n(r.o_venc_pct, 1)])
        st += [M.table(tt, font=6.5), PageBreak()]

    def foot(c, d):
        c.setFont('Helvetica', 7)
        c.setFillColor(colors.grey)
        c.drawString(2 * cm, 1 * cm, 'Descritivo — não indica irregularidade nem a descarta')
        c.drawRightString(27.5 * cm, 1 * cm, f'pág. {d.page}')
    SimpleDocTemplate(str(OUT / 'ENCERRAMENTO_POR_CIDADE.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.4 * cm, bottomMargin=1.6 * cm).build(st, onFirstPage=foot, onLaterPages=foot)


if __name__ == '__main__':
    main()
