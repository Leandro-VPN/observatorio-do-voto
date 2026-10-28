"""Horario do ultimo voto por secao no 2o turno de 2026 (prorrogacao ate 19h), lido do log da urna.

Para cada secao com log no HD: primeiro e ultimo voto computado no dia, votos apos 17h e apos 19h, todos
em hora de Brasilia (deslocamento por municipio estimado pela abertura, ver fechamento_recebimento_2026t2.py).
Faixas do ultimo voto: ate 17h00 / 17h00-19h00 / depois das 19h00, cruzadas com os cenarios A/B/C de
encerramento x recebimento e com o resultado de presidente da secao.

Cobertura: enquanto os logs do 2o turno nao estiverem todos no HD, as secoes que encerraram a partir de
17h10 tem log (todas) e as que encerraram antes entram por uma amostra aleatoria (controle de 3%). Cada
secao recebe peso = secoes do estrato na UF / secoes do estrato com log. Com todos os logs, peso 1.
Saida: relatorios/verificacoes/ultimo_voto_2026t2/
"""
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from auditabr.logs import read_log  # noqa: E402

LOGS = ROOT / 'research' / 'segundo_turno_2026' / 'logs'
FECH = ROOT / 'relatorios' / 'verificacoes' / 'fechamento_2026t2' / 'secoes_fechamento_recebimento.parquet'
BU = ROOT / 'research' / 'segundo_turno_2026' / 'bu_todos_decodificados.parquet'
OUT = ROOT / 'relatorios' / 'verificacoes' / 'ultimo_voto_2026t2'
DIA = '25/10/2026'
NOME = re.compile(r'^o0*\d+(?P<uf>[a-z]{2})(?P<mun>\d{5})(?P<zona>\d{4})(?P<sec>\d{4})-log\.jez$')
KEY = ['uf', 'municipality', 'zone', 'section']


def votos(path):
    """Segundos (desde 0h, hora local da urna) de cada voto computado no dia."""
    try:
        text = read_log(path).decode('latin-1')
    except Exception as exc:  # noqa: BLE001
        return path.name, None, repr(exc)[:100]
    t = []
    for line in text.splitlines():
        f = line.split('\t', 5)
        if len(f) > 4 and f[3] == 'VOTA' and f[0].startswith(DIA) and f[4] == 'O voto do eleitor foi computado':
            h, m, s = f[0][11:19].split(':')
            t.append(int(h) * 3600 + int(m) * 60 + int(s))
    return path.name, t, None


def logs_no_hd():
    rows = []
    for d in sorted(LOGS.iterdir()):
        for p in d.glob('*-log.jez'):
            m = NOME.match(p.name)
            if m:
                rows.append({'uf': m['uf'].upper(), 'municipality': int(m['mun']), 'zone': int(m['zona']), 'section': int(m['sec']), 'path': str(p)})
    return pd.DataFrame(rows).drop_duplicates(KEY)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    s = pd.read_parquet(FECH, columns=KEY + ['voting_place', 'desloc_h', 'encerramento', 'recebimento', 'cenario', 'v13', 'v22', 'validos', 'vencedor_secao'])
    s = s[s.uf != 'ZZ']
    lg = logs_no_hd()
    s = s.merge(lg, on=KEY, how='left')
    # estratos de amostragem: encerrou >= 17h10 (todas com log) x antes (amostra de controle)
    s['estrato'] = np.where(s.encerramento >= pd.Timestamp('2026-10-25 17:10'), 'encerrou_17h10_ou_depois', 'encerrou_antes_17h10')
    try:  # nos estratos amostrados, so a amostra aleatoria de controle representa o estrato (cidades da BA entram por outro criterio)
        why = pd.read_parquet(BU, columns=['uf', 'municipality', 'zone', 'section', 'log_why'])
        extra = ROOT / 'research' / 'segundo_turno_2026' / 'amostra_controle_dados_abertos.csv'
        if extra.exists():  # amostra aleatoria das UFs cujos logs vieram dos dados abertos (amostra_logs_2026t2.py)
            why = pd.concat([why, pd.read_csv(extra, sep=';', encoding='utf-8-sig')])
        for c in ('municipality', 'zone', 'section'):
            why[c] = pd.to_numeric(why[c], errors='coerce')
        s = s.merge(why.drop_duplicates(KEY), on=KEY, how='left')
    except Exception:  # noqa: BLE001
        s['log_why'] = None
    cobertura = s.groupby('uf').path.apply(lambda x: x.notna().mean())
    completa = set(cobertura[cobertura >= .99].index)
    usa = s.path.notna() & (s.uf.isin(completa) | (s.estrato == 'encerrou_17h10_ou_depois') | (s.log_why == 'control'))
    s['usa_log'] = usa
    n_estr = s.groupby(['uf', 'estrato']).size().rename('N')
    n_log = s[usa].groupby(['uf', 'estrato']).size().rename('n')
    w = pd.concat([n_estr, n_log], axis=1).fillna(0)
    w['peso'] = np.where(w.n > 0, w.N / w.n.replace(0, np.nan), np.nan)
    s = s.merge(w.peso.reset_index(), on=['uf', 'estrato'], how='left')
    print('secoes', len(s), '| com log usado', int(usa.sum()), '| UFs com cobertura completa', sorted(completa), flush=True)

    todo = s[usa].path.tolist()
    res = {}
    with ProcessPoolExecutor(6) as ex:
        for k, (nome, t, err) in enumerate(ex.map(votos, map(Path, todo), chunksize=25), 1):
            res[nome] = (t, err)
            if k % 5000 == 0:
                print(k, len(todo), flush=True)
    base = pd.Timestamp('2026-10-25')
    rows = []
    for r in s[usa].itertuples():
        t, err = res.get(Path(r.path).name, (None, 'nao lido'))
        if not t:
            rows.append({**{k: getattr(r, k) for k in KEY}, 'erro_log': err or 'sem votos no dia'})
            continue
        off = (r.desloc_h if pd.notna(r.desloc_h) else 0) * 3600
        tb = np.array(t) + off  # hora de Brasilia
        rows.append({**{k: getattr(r, k) for k in KEY}, 'votos_log': len(tb),
                     'primeiro_voto': base + pd.to_timedelta(int(tb.min()), unit='s'),
                     'ultimo_voto': base + pd.to_timedelta(int(tb.max()), unit='s'),
                     'votos_apos_17h': int((tb > 17 * 3600).sum()), 'votos_apos_19h': int((tb > 19 * 3600).sum())})
    V = pd.DataFrame(rows)
    d = s.merge(V, on=KEY, how='inner')
    d = d[d.ultimo_voto.notna()].copy()
    d['min_ultimo_apos_17h'] = (d.ultimo_voto - pd.Timestamp('2026-10-25 17:00')).dt.total_seconds() / 60
    d['faixa'] = pd.cut(d.min_ultimo_apos_17h, [-1e9, 0, 120, 1e9], labels=['até 17h00', '17h00–19h00', 'depois das 19h00'])
    d['faixa_fina'] = pd.cut(d.min_ultimo_apos_17h, [-1e9, 0, 15, 30, 60, 90, 120, 135, 1e9],
                             labels=['até 17h00', '17h00–17h15', '17h15–17h30', '17h30–18h00', '18h00–18h30', '18h30–19h00', '19h00–19h15', 'depois de 19h15'])
    d['min_enc_menos_ultimo'] = (d.encerramento - d.ultimo_voto).dt.total_seconds() / 60
    d.to_csv(OUT / 'ultimo_voto_por_secao.csv', index=False, sep=';', encoding='utf-8-sig', decimal=',')

    def resumo(g):
        w_ = g.peso
        val = (w_ * g.validos).sum()
        sl = (w_ * g.v13).sum()
        hhmm = lambda m: (pd.Timestamp('2026-10-25 17:00') + pd.to_timedelta(m, unit='m')).strftime('%H:%M')  # noqa: E731
        return pd.Series({'secoes_com_log': len(g), 'secoes_estimadas': round(w_.sum()),
                          'ultimo_voto_medio': hhmm(np.average(g.min_ultimo_apos_17h, weights=w_)),
                          'ultimo_voto_mediano': hhmm(g.min_ultimo_apos_17h.median()),
                          'votos_apos_17h_media': round(np.average(g.votos_apos_17h, weights=w_), 1),
                          'votos_apos_19h_media': round(np.average(g.votos_apos_19h, weights=w_), 1),
                          'min_entre_ultimo_voto_e_encerramento_mediana': round(g.min_enc_menos_ultimo.median(), 1),
                          'pct_lula': round(100 * sl / val, 2) if val else np.nan, 'pct_flavio': round(100 - 100 * sl / val, 2) if val else np.nan,
                          'secoes_lula_est': round((w_ * (g.vencedor_secao == 'LULA')).sum()),
                          'secoes_flavio_est': round((w_ * (g.vencedor_secao == 'FLÁVIO')).sum()),
                          'vencedor_votos': 'LULA' if sl > val - sl else 'FLÁVIO BOLSONARO'})
    F = d.groupby('faixa', observed=True).apply(resumo).reset_index()
    F['pct_secoes'] = (100 * F.secoes_estimadas / F.secoes_estimadas.sum()).round(2)
    FF = d.groupby('faixa_fina', observed=True).apply(resumo).reset_index()
    FF['pct_secoes'] = (100 * FF.secoes_estimadas / FF.secoes_estimadas.sum()).round(2)
    X = d.groupby(['cenario', 'faixa'], observed=True).apply(resumo).reset_index()
    U = d.groupby(['uf', 'faixa'], observed=True).apply(resumo).reset_index()
    cob = s.groupby('uf').agg(secoes=('section', 'size'), com_log_usado=('usa_log', 'sum')).reset_index()
    for nm, df in (('faixas', F), ('faixas_finas', FF), ('cenario_x_faixa', X), ('por_uf', U), ('cobertura', cob)):
        df.to_csv(OUT / f'{nm}.csv', index=False, sep=';', encoding='utf-8-sig', decimal=',')
    with pd.ExcelWriter(OUT / 'ULTIMO_VOTO_2026T2.xlsx') as xw:
        for nm, df in (('faixas', F), ('faixas_finas', FF), ('cenario_x_faixa', X), ('por_uf', U), ('cobertura', cob)):
            df.to_excel(xw, sheet_name=nm, index=False)
        d.drop(columns=['path']).head(1_000_000).to_excel(xw, sheet_name='por_secao', index=False)
    pd.set_option('display.width', 250)
    print(F.to_string(index=False)); print(FF[['faixa_fina', 'secoes_com_log', 'secoes_estimadas', 'pct_secoes', 'pct_lula', 'vencedor_votos']].to_string(index=False))
    print(X[['cenario', 'faixa', 'secoes_com_log', 'secoes_estimadas', 'ultimo_voto_medio', 'votos_apos_17h_media', 'pct_lula']].to_string(index=False))


if __name__ == '__main__':
    main()
