"""2o turno de 2026 (votacao prorrogada ate as 19h): encerramento da urna x recebimento do BU pelo TSE.

Cenarios (horarios de Brasilia):
  A  encerrou antes das 19h e o BU chegou ao TSE antes das 19h
  B  encerrou antes das 19h e o BU chegou depois das 19h
  C  encerrou as 19h ou depois (ficou aberta ate o fim da prorrogacao)
  X  encerrou as 19h ou depois mas o BU consta recebido antes das 19h (inconsistencia de relogio; contado a parte)
Para cada cenario: secoes, %, votos de cada candidato a presidente e vencedor (por votos e por secoes).

Fontes: research/segundo_turno_2026/bu_todos_decodificados.parquet (14 UFs: BU + recebimento) e, para as
demais UFs, o BU dos dados abertos (research/bu_urna/2026-t2/<UF>, scripts/baixa_pais.py) com o horario de
recebimento do arquivo de configuracao do sistema de resultados (t2_2026_collect.sections).
Fuso: a urna registra hora local e o recebimento e em hora de Brasilia. O deslocamento de cada urna e
estimado pela abertura (a votacao abre as 8h de Brasilia em todo o pais; abriu ~7h local => +1 h).
Exterior (ZZ) vota no horario local de cada pais: fica fora dos cenarios.
Uso: python scripts/fechamento_recebimento_2026t2.py coleta | analise
Saida: relatorios/verificacoes/fechamento_2026t2/
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]

R = ROOT / 'research'
OUT = ROOT / 'relatorios' / 'verificacoes' / 'fechamento_2026t2'
T2 = R / 'segundo_turno_2026'
FALTAM = ['AC', 'AL', 'AM', 'AP', 'DF', 'ES', 'GO', 'MA', 'MS', 'MT', 'RO', 'RR', 'TO', 'ZZ']
URL = 'https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/arqurnatot/bu_imgbu_logjez_rdv_vscmr_2026_2t_{}.zip'
CAND = {'v13': 'LULA (13)', 'v22': 'FLÁVIO BOLSONARO (22)'}


def coleta():
    import baixa_pais as B
    import t2_2026_collect as T
    for uf in FALTAM:
        cfg = T2 / 'config' / f'{uf}-cs.json'
        if not cfg.exists():
            T.sections(uf)  # grava o config com data/hora de recebimento por secao
            print(uf, 'config ok', flush=True)
        B.run('2026-t2', uf, URL.format(uf), 'so_bu', 16)


def recebimento(uf):
    import json
    cfg = json.loads((T2 / 'config' / f'{uf}-cs.json').read_text(encoding='utf-8'))
    return pd.DataFrame([(int(mu['cd']), int(z['cd']), int(s['ns']), s.get('da'), s.get('ha'))
                         for ab in cfg['abr'] for mu in ab['mu'] for z in mu['zon'] for s in z['sec']],
                        columns=['municipality', 'zone', 'section', 'receipt_date', 'receipt_time'])


def carrega():
    from t2_2026_collect import decode_bu
    cols = ['uf', 'municipality', 'zone', 'voting_place', 'section', 'opening', 'closing', 'receipt_date', 'receipt_time',
            'e6258_aptos', 'e6258_comparecimento', 'e6258_c1_v13', 'e6258_c1_v22', 'e6258_c1_branco', 'e6258_c1_nulo']
    a = pd.read_parquet(T2 / 'bu_todos_decodificados.parquet', columns=cols + ['status'])
    a = a[a.status == 'OK'].drop(columns='status')
    partes = [a]
    for uf in FALTAM:
        pp = sorted((R / 'bu_urna' / '2026-t2' / uf).glob('part-*.parquet'))
        if not pp:
            print(uf, 'sem BU baixado', flush=True)
            continue
        b = pd.concat([pd.read_parquet(p) for p in pp])
        rec = pd.DataFrame([decode_bu(x) for x in b.bu_raw])
        rec['uf'] = uf
        rec = rec.merge(recebimento(uf), on=['municipality', 'zone', 'section'], how='left')
        partes.append(rec.reindex(columns=cols))
    d = pd.concat(partes, ignore_index=True)
    for c in ('municipality', 'zone', 'section'):
        d[c] = pd.to_numeric(d[c], errors='coerce')
    return d.drop_duplicates(['uf', 'municipality', 'zone', 'section'])


def analise():
    OUT.mkdir(parents=True, exist_ok=True)
    d = carrega()
    d['abertura'] = pd.to_datetime(d.opening, format='%Y%m%dT%H%M%S', errors='coerce')
    d['encerramento_local'] = pd.to_datetime(d.closing, format='%Y%m%dT%H%M%S', errors='coerce')
    d['recebimento'] = pd.to_datetime(d.receipt_date + ' ' + d.receipt_time, format='%d/%m/%Y %H:%M:%S', errors='coerce')
    # deslocamento ate Brasilia pela abertura (8h de Brasilia): abriu 7h local -> +1h; 6h -> +2h; 9h (Noronha) -> -1h.
    # Estimado por municipio (moda das urnas), para uma urna que abriu atrasada nao mudar de fuso.
    h_ab = d.abertura.dt.hour + d.abertura.dt.minute / 60
    d['_desl_urna'] = (8 - np.floor(h_ab)).where(h_ab.between(5.5, 9.99))
    moda = d.dropna(subset=['_desl_urna']).groupby(['uf', 'municipality'])._desl_urna.agg(lambda s: s.mode().iloc[0]).rename('desloc_h')
    d = d.drop(columns='_desl_urna').merge(moda.reset_index(), on=['uf', 'municipality'], how='left')
    d.loc[d.uf == 'ZZ', 'desloc_h'] = np.nan
    d['encerramento'] = d.encerramento_local + pd.to_timedelta(d.desloc_h, unit='h')
    dia19 = pd.Timestamp('2026-10-25 19:00:00')
    enc_antes = d.encerramento < dia19
    rec_antes = d.recebimento < dia19
    d['cenario'] = np.select([enc_antes & rec_antes, enc_antes & ~rec_antes, ~enc_antes & ~rec_antes, ~enc_antes & rec_antes],
                             ['A', 'B', 'C', 'X'], default='sem dado')
    d.loc[d.uf == 'ZZ', 'cenario'] = 'exterior'
    d.loc[d.encerramento.isna() | d.recebimento.isna(), 'cenario'] = d.loc[d.encerramento.isna() | d.recebimento.isna(), 'cenario'].where(d.uf == 'ZZ', 'sem dado')
    for k in ('v13', 'v22', 'branco', 'nulo'):
        d[k] = pd.to_numeric(d[f'e6258_c1_{k}'], errors='coerce').fillna(0)
    d['validos'] = d.v13 + d.v22
    d['vencedor_secao'] = np.where(d.v13 > d.v22, 'LULA', np.where(d.v22 > d.v13, 'FLÁVIO', 'empate'))
    d['min_enc_apos_17h'] = (d.encerramento - pd.Timestamp('2026-10-25 17:00:00')).dt.total_seconds() / 60
    d['min_rec_apos_enc'] = (d.recebimento - d.encerramento).dt.total_seconds() / 60
    d.drop(columns=['opening', 'closing']).to_parquet(OUT / 'secoes_fechamento_recebimento.parquet', index=False)

    rot = {'A': 'A · encerrou e foi recebido antes das 19h', 'B': 'B · encerrou antes das 19h, recebido depois',
           'C': 'C · encerrou às 19h ou depois (prorrogação)', 'X': 'X · encerrou às 19h+ mas consta recebido antes (relógio)',
           'sem dado': 'sem horário de encerramento ou recebimento', 'exterior': 'exterior (horário local de cada país)'}

    def resumo(g):
        s = pd.Series({'secoes': len(g), 'comparecimento': int(pd.to_numeric(g.e6258_comparecimento, errors='coerce').sum()),
                       'votos_lula': int(g.v13.sum()), 'votos_flavio': int(g.v22.sum()), 'brancos': int(g.branco.sum()), 'nulos': int(g.nulo.sum()),
                       'secoes_lula': int((g.vencedor_secao == 'LULA').sum()), 'secoes_flavio': int((g.vencedor_secao == 'FLÁVIO').sum()),
                       'secoes_empate': int((g.vencedor_secao == 'empate').sum()),
                       'mediana_encerramento': (pd.Timestamp('2026-10-25 17:00') + pd.to_timedelta(g.min_enc_apos_17h.median(), unit='m')).strftime('%H:%M') if g.min_enc_apos_17h.notna().any() else '',
                       'mediana_min_ate_receber': round(g.min_rec_apos_enc.median(), 1) if g.min_rec_apos_enc.notna().any() else np.nan})
        val = s.votos_lula + s.votos_flavio
        s['pct_lula'] = round(100 * s.votos_lula / val, 2) if val else np.nan
        s['pct_flavio'] = round(100 * s.votos_flavio / val, 2) if val else np.nan
        s['vencedor_votos'] = 'LULA' if s.votos_lula > s.votos_flavio else ('FLÁVIO BOLSONARO' if s.votos_flavio > s.votos_lula else 'empate')
        return s
    tot = d.groupby('cenario').apply(resumo).reset_index()
    tot['pct_secoes'] = (100 * tot.secoes / tot.secoes.sum()).round(2)
    tot['cenario_desc'] = tot.cenario.map(rot)
    poruf = d[d.uf != 'ZZ'].groupby(['uf', 'cenario']).apply(resumo).reset_index()
    poruf['pct_secoes_uf'] = (100 * poruf.secoes / poruf.groupby('uf').secoes.transform('sum')).round(2)
    faixas = pd.cut(d.min_enc_apos_17h, [-1e9, 0, 30, 60, 90, 115, 119, 120, 125, 180, 1e9],
                    labels=['antes 17h', '17h00–17h30', '17h30–18h', '18h–18h30', '18h30–18h55', '18h55–18h59', '18h59–19h00', '19h00–19h05', '19h05–20h', 'depois de 20h'])
    fx = d[d.uf != 'ZZ'].groupby(faixas, observed=False).apply(resumo).reset_index().rename(columns={'min_enc_apos_17h': 'faixa_encerramento'})
    # recebimento ao longo da noite (o TSE so recebeu apos as 19h?)
    rec_h = d[d.uf != 'ZZ'].recebimento
    rec = pd.Series({'primeiro_recebimento': rec_h.min(), 'recebidos_antes_19h': int((rec_h < dia19).sum()),
                     'recebidos_19h00_19h10': int(rec_h.between(dia19, dia19 + pd.Timedelta(minutes=10)).sum()),
                     'mediana_recebimento': rec_h.median(), 'ultimo_recebimento': rec_h.max()})
    rec_min = d[d.uf != 'ZZ'].assign(h=lambda x: x.recebimento.dt.floor('15min')).groupby('h').size().rename('bus_recebidos').reset_index()
    # comparacao justa: secoes do cenario C contra as do mesmo predio que encerraram antes das 19h (A ou B)
    d['pct_lula'] = 100 * d.v13 / d.validos.replace(0, np.nan)
    loc = ['uf', 'municipality', 'zone', 'voting_place']
    base = d[d.cenario.isin(['A', 'B'])].groupby(loc).agg(v13_viz=('v13', 'sum'), val_viz=('validos', 'sum'), n_viz=('section', 'size')).reset_index()
    c = d[d.cenario == 'C'].merge(base, on=loc, how='left')
    c['pct_lula_vizinhas'] = 100 * c.v13_viz / c.val_viz.replace(0, np.nan)
    c['dif_pp'] = c.pct_lula - c.pct_lula_vizinhas
    pc = c.dropna(subset=['dif_pp'])
    viz = pd.Series({'secoes_C': len(c), 'com_vizinhas_no_predio': len(pc), 'predios': pc.groupby(loc).ngroups,
                     'pct_lula_C': round(100 * pc.v13.sum() / pc.validos.sum(), 2),
                     'pct_lula_vizinhas': round(100 * pc.v13_viz.sum() / pc.val_viz.sum(), 2),
                     'mediana_dif_pp': round(pc.dif_pp.median(), 2),
                     'C_mais_lula_que_vizinhas_pct': round(100 * (pc.dif_pp > 0).mean(), 1),
                     'secoes_C_sem_vizinha': int(c.dif_pp.isna().sum())})
    tot.to_csv(OUT / 'cenarios_total.csv', index=False, sep=';', encoding='utf-8-sig', decimal=',')
    rec_min.to_csv(OUT / 'recebimentos_por_15min.csv', index=False, sep=';', encoding='utf-8-sig')
    pd.concat([rec.astype(str), viz.astype(str)]).to_frame('valor').to_csv(OUT / 'resumo_recebimento_e_predio.csv', sep=';', encoding='utf-8-sig')
    c.to_csv(OUT / 'cenario_C_vs_mesmo_predio.csv', index=False, sep=';', encoding='utf-8-sig', decimal=',')
    poruf.to_csv(OUT / 'cenarios_por_uf.csv', index=False, sep=';', encoding='utf-8-sig', decimal=',')
    fx.to_csv(OUT / 'faixas_encerramento.csv', index=False, sep=';', encoding='utf-8-sig', decimal=',')
    with pd.ExcelWriter(OUT / 'FECHAMENTO_X_RECEBIMENTO_2026T2.xlsx') as xw:
        tot.to_excel(xw, sheet_name='cenarios', index=False)
        poruf.to_excel(xw, sheet_name='por_uf', index=False)
        fx.to_excel(xw, sheet_name='faixas_encerramento', index=False)
        d.groupby('uf').desloc_h.value_counts(dropna=False).rename('urnas').reset_index().to_excel(xw, sheet_name='fuso_estimado', index=False)
        rec_min.to_excel(xw, sheet_name='recebimentos_15min', index=False)
        pd.concat([rec.astype(str), viz.astype(str)]).to_frame('valor').to_excel(xw, sheet_name='resumo_receb_predio')
        c.to_excel(xw, sheet_name='C_vs_mesmo_predio', index=False)
    print(rec.to_string()); print(viz.to_string())
    pd.set_option('display.width', 250)
    print('secoes:', len(d), '| UFs:', d.uf.nunique())
    print(tot[['cenario', 'secoes', 'pct_secoes', 'votos_lula', 'votos_flavio', 'pct_lula', 'pct_flavio', 'vencedor_votos', 'secoes_lula', 'secoes_flavio', 'mediana_encerramento', 'mediana_min_ate_receber']].to_string(index=False))
    print(fx[['faixa_encerramento', 'secoes', 'pct_lula', 'pct_flavio']].to_string(index=False))
    print(d.groupby('uf').desloc_h.value_counts(dropna=False).unstack(fill_value=0).to_string())


if __name__ == '__main__':
    {'coleta': coleta, 'analise': analise}[sys.argv[1]]()
