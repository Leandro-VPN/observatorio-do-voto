"""Varredura forense, camada C7 (espelhamento e duplicidade): checagens leves sobre os parquet/CSV ja existentes.

"Espelho" no restante do repositorio (padroes_aberta.espelho) significa inversao de fatia entre pleitos. Aqui cada
medida tem nome proprio: "vetor identico" (mesmo vetor completo do 2o turno em duas secoes distintas), "par A/B
trocado" (vetor de uma secao igual ao da outra com A e B permutados), "comparecimento igual em sequencia",
"progressao aritmetica no predio", "serie de urna repetida", "linha BWEB duplicada".

Uma funcao por checagem: as `c7_XX_*` sao puras (DataFrames -> DataFrames/dicionarios); os carregadores leem o disco
com projecao de colunas e DuckDB limitado (400 MB, 2 threads). `main()` grava relatorios/verificacoes/varredura_forense/C7/
(CSVs `C7-XX_*.csv`, `C7_resumo.json`, `C7_achados.json`, `quarentena_C7.csv`). Importavel sem efeito pesado.

Protocolo: relatorios/verificacoes/varredura_forense/PROTOCOLO.md v1.0. Tudo aqui e descritivo: coincidencia e
"diferenca acima do limiar" nao indicam irregularidade por si so.
Uso: python scripts/varredura_forense_c7.py [C7-01 C7-02 ...]   (sem argumentos: todas as checagens leves)
"""
import datetime as dt
import gc
import hashlib
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / 'research'
REL = ROOT / 'relatorios'
OUT = REL / 'verificacoes' / 'varredura_forense' / 'C7'
QUAR = R / 'varredura_forense' / 'quarentena'
CSV = dict(sep=';', decimal=',', encoding='utf-8-sig', index=False)
PARSER_VERSION = 'varredura-forense-c7-1'
KEY = ['uf', 'municipality', 'zone', 'section']
ANOS = [2014, 2018, 2022, 2026]
VEC_T2 = ['t2_aptos', 't2_comp', 't2_A', 't2_B', 't2_branco', 't2_nulo']
VEC_T2_SEM_APTOS = ['t2_comp', 't2_A', 't2_B', 't2_branco', 't2_nulo']
VEC_T2_TROCADO = ['t2_aptos', 't2_comp', 't2_B', 't2_A', 't2_branco', 't2_nulo']
COMP_MIN = 50
R_PARAM = 100       # repeticoes do nulo parametrico (C7-01)
R_PERM = 200        # repeticoes dos nulos por permutacao (C7-01, C7-05, C7-06)
R_SENS = 30         # repeticoes do nulo 1 sem sobredispersao (sensibilidade de C7-01)
SEED = 20261105
EPS = 1e-6
FAIXAS_COMP = [50, 100, 200, 300, 400, 10_000]
NIVEIS = ['mesmo_local', 'mesmo_municipio', 'mesma_uf', 'outra_uf']
NOT_COMP = 'NOT_COMPARABLE'
UFS11 = ['BA', 'CE', 'MA', 'MG', 'PA', 'PE', 'PR', 'RJ', 'RS', 'SC', 'SP']
PLEITOS_BWEB = {'2012-t1': 'PREFEITO', '2012-t2': 'PREFEITO', '2014-t1': 'PRESIDENTE', '2014-t2': 'PRESIDENTE',
                '2016-t1': 'PREFEITO', '2016-t2': 'PREFEITO', '2018-t1': 'PRESIDENTE', '2018-t2': 'PRESIDENTE',
                '2020-t1': 'PREFEITO', '2020-t2': 'PREFEITO', '2022-t1': 'PRESIDENTE', '2022-t2': 'PRESIDENTE',
                '2024-t1': 'PREFEITO', '2024-t2': 'PREFEITO', '2026-t1': 'GOVERNADOR'}
PLEITOS_URNA = ['2022-t1', '2022-t2', '2024-t1', '2024-t2', '2026-t1', '2026-t2']
# CEFT 2012-2016 (sem cabecalho), na ordem do layout de 2018 com cabecalho: c9 = SQ_CORRESPONDENCIA_ESPERADA,
# c10 = NR_URNA_ESPERADA, c17 = SQ_CORRESPONDENCIA_EFETIVADA, c18 = NR_URNA_EFETIVADA, c25 = codigo da origem do voto,
# c26 = divergencia (conferido em research/ceft/2012-t1, 2014-t1 e 2016-t1/BA.parquet: c10/c18 com 7 digitos, faixa 1.000.067-1.770.626)
CEFT_SEM_CABECALHO = {'esperada': 'c10', 'efetivada': 'c18', 'origem': 'c25', 'divergencia': 'c26',
                      'municipality': 'c5', 'zone': 'c7', 'section': 'c8'}
BRANCO, NULO = '95', '96'
_QUARENTENA: list[dict] = []
# fatos apurados na sessao de 04-05/11/2026 (dossie C2-01 / C7-11), gravados como evidencia; nao sao relidos aqui
FATOS_C7_11 = [
    dict(uf='ES', municipality=57932, zone=9, section=85, pacote='research/segundo_turno_2026/logs/ES/o03221es5793200090085-log.jez',
         bytes=399475, n_logd=3, votos_log_leitor_antigo=612, votos_log_releitura=308, bu=308,
         fato='3 logd.dat: externo (depth 0) urna 01758779, 725 linhas, 0 votos, declara "Secao Eleitoral" 0000 ("Urna de '
              'contingencia") e depois 0112, usada em 25/10 19:39 e 21:24 ("Log interno da urna de contingencia validado"); '
              'aninhado urna 01841837 (secao 85, 10.849 linhas, 297 votos em 04/10 e 308 em 25/10 = BU); aninhado urna '
              '01750820 (secao 112, 304 votos em 04/10 e 304 em 25/10). O filtro por secao declarada nao escolhia (externo '
              'declara 2 secoes) e somava 308+304 = 612. Corrigido em src/auditabr/logs.py (section_hint pelo nome do '
              'arquivo, 04/11, nao commitado): agora 308. O pacote da secao 112 (...0112-log.jez) tem so a contingencia + urna '
              '01750820 = 304 = BU. Releitura do ultimo voto refeita: ultimo_voto_por_secao.csv ja mostra 308.',
         classificacao='ARTEFATO do leitor (log de outra secao embalado no pacote: urna de contingencia que recuperou 2 secoes)',
         status='ARTEFATO'),
    dict(uf='BA', municipality=35653, zone=173, section=235, pacote='research/segundo_turno_2026/logs/BA/o03221ba3565301730235-log.jez',
         bytes=None, n_logd=3, votos_log_leitor_antigo=204, votos_log_releitura=204, bu=217,
         fato='externo = contingencia 01656557 com 204 votos em 25/10 (declara 0000 e 0235); aninhados: log de T1 da urna '
              '01833178 (secao 235, 209 votos em 04/10) e um log de 170 linhas da mesma urna 01833178 iniciado 25/10 09:04 '
              'declarando secao 0083, sem votos. BU = 217: faltam 13 votos de uma urna intermediaria cujo log nao esta no pacote.',
         classificacao='pacote publicado sem o log de uma urna intermediaria (13 votos sem log; troca de urna)',
         status='NAO_TESTAVEL'),
    dict(uf='MA', municipality=8893, zone=47, section=609, pacote='research/segundo_turno_2026/logs/MA/o03221ma0889300470609-log.jez',
         bytes=None, n_logd=2, votos_log_leitor_antigo=188, votos_log_releitura=188, bu=224,
         fato='externo = contingencia 01664037 com 188 votos em 25/10 (declara 0000 e 0609); aninhado: log de T1 da urna '
              '01813459 declarando secao 0445 (306 votos em 04/10). BU = 224: faltam 36 votos; o log da urna original do 2o '
              'turno nao esta no pacote.',
         classificacao='pacote publicado sem o log de uma urna intermediaria (36 votos sem log; troca de urna)',
         status='NAO_TESTAVEL'),
]


# ----------------------------------------------------------------------------------------------- utilidades
def duck():
    import duckdb
    con = duckdb.connect()
    con.execute("SET memory_limit='400MB'")
    con.execute('SET threads=2')
    return con


def pq_names(path):
    import pyarrow.parquet as pq
    return pq.ParquetFile(path).schema_arrow.names


def sha_entrada(path):
    path = Path(path)
    rec = path.with_suffix('.json')
    if rec.exists():
        try:
            j = json.loads(rec.read_text(encoding='utf-8'))
            if isinstance(j, dict) and j.get('sha256'):
                return j['sha256']
        except (ValueError, OSError):
            pass
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def quarentena(checagem, df, reason):
    """Linhas que falham invariante: valores originais como string + motivo (JSON por checagem e CSV unico)."""
    if df is None or len(df) == 0:
        return 0
    rows = [{k: ('' if pd.isna(v) else str(v)) for k, v in r.items()} | {'reason': reason, 'checagem': checagem}
            for r in df.to_dict('records')]
    QUAR.mkdir(parents=True, exist_ok=True)
    p = QUAR / f'rows-{checagem}.json'
    old = json.loads(p.read_text(encoding='utf-8')) if p.exists() else []
    p.write_text(json.dumps(old + rows, ensure_ascii=False, indent=1), encoding='utf-8')
    _QUARENTENA.extend(rows)
    return len(rows)


def csv_out(nome, df):
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / nome, **CSV)
    return str(OUT / nome)


def _t():
    return time.perf_counter()


def _rec(resumo, cid, status, numeros, arquivos, motivo=''):
    resumo[cid] = {'status': status, 'motivo': motivo, 'numeros_chave': numeros, 'arquivos': arquivos,
                   'gerado_em': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}


def p_empirico(sims, obs):
    """p-valor empirico bilateral-informativo: fracao de simulacoes >= obs (excesso) e <= obs (deficit)."""
    s = np.asarray(sims, dtype=float)
    return {'p_excesso': float((np.sum(s >= obs) + 1) / (len(s) + 1)), 'p_deficit': float((np.sum(s <= obs) + 1) / (len(s) + 1))}


def faixa_comp(x):
    return pd.cut(x, FAIXAS_COMP, right=False, labels=[f'{a}-{b - 1}' if b < 10_000 else f'{a}+' for a, b in
                                                      zip(FAIXAS_COMP[:-1], FAIXAS_COMP[1:])]).astype(str)


# ----------------------------------------------------------------------------------------------- carregadores
def carrega_base(ano, extra=()):
    """base_<ano>.parquet com as colunas do vetor do 2o turno (+ extra); flag `elegivel` (sem ZZ, comp >= 50, A e B > 0)."""
    p = R / 'padroes_2t' / f'base_{ano}.parquet'
    names = pq_names(p)
    cols = KEY + ['voting_place'] + VEC_T2 + [c for c in extra if c in names]
    d = pd.read_parquet(p, columns=list(dict.fromkeys(cols)))
    for c in VEC_T2:
        d[c] = d[c].astype('int64')
    d['ano'] = ano
    d['elegivel'] = (d.uf != 'ZZ') & (d.t2_comp >= COMP_MIN) & (d.t2_A > 0) & (d.t2_B > 0)
    return d


def carrega_ibge():
    """Chave TSE (uf, municipality) -> microrregiao / regiao imediata do IBGE, via o casamento ja feito em eleitorado_populacao."""
    p_m = REL / 'verificacoes' / 'eleitorado_populacao' / 'municipios.csv'
    p_j = R / 'ibge' / 'municipios.json'
    if not p_m.exists() or not p_j.exists():
        return None
    m = pd.read_csv(p_m, sep=';', decimal=',', encoding='utf-8-sig', usecols=['uf', 'municipality', 'ibge'])
    j = pd.DataFrame(json.loads(p_j.read_text(encoding='utf-8')))
    j = j.rename(columns={'municipio-id': 'ibge', 'microrregiao-id': 'microrregiao', 'regiao-imediata-id': 'regiao_imediata'})
    m = m.dropna(subset=['ibge']).merge(j[['ibge', 'microrregiao', 'regiao_imediata']], on='ibge', how='left')
    m['municipality'] = m.municipality.astype(int)
    return m[['uf', 'municipality', 'microrregiao', 'regiao_imediata']]


# ----------------------------------------------------------------------------------------------- pares (puro)
def hash_vetor(df, cols):
    return pd.util.hash_pandas_object(df[list(cols)], index=False).to_numpy()


def conta_pares_iguais(h):
    """Pares (i<j) com o mesmo hash: C(k,2) somado nos grupos; tambem nº de grupos e de secoes em grupo."""
    _, cnt = np.unique(h, return_counts=True)
    k = cnt[cnt >= 2]
    return int((k * (k - 1) // 2).sum()), int(len(k)), int(k.sum())


def conta_pares_trocados(df, cols, cols_trocado, a='t2_A', b='t2_B'):
    """Pares (i, j) com vetor_i = vetor_j com A e B permutados, so entre secoes com A != B (A = B e vetor identico)."""
    d = df[df[a] != df[b]]
    if d.empty:
        return 0
    h1 = pd.Series(hash_vetor(d, cols))
    h2 = pd.Series(hash_vetor(d, cols_trocado))
    c2 = h2.value_counts()
    return int(h1.map(c2).fillna(0).sum() // 2)


def enumera_pares(df, cols, campos=('uf', 'municipality', 'zone', 'section', 'voting_place')):
    """Lista os pares (i<j) de secoes com vetor identico, com a classificacao geografica (nivel)."""
    d = df[list(dict.fromkeys(list(campos) + list(cols)))].copy()
    d['_h'] = hash_vetor(d, cols)
    d['_i'] = np.arange(len(d))
    vc = d._h.value_counts()
    d = d[d._h.map(vc) >= 2]
    if d.empty:
        m = pd.DataFrame(columns=[f'{c}_1' for c in campos] + [f'{c}_2' for c in campos] + list(cols) + ['nivel'])
        return m
    m = d.merge(d, on='_h', suffixes=('_1', '_2'))
    m = m[m._i_1 < m._i_2]
    for c in cols:
        m = m[m[f'{c}_1'] == m[f'{c}_2']]
    m = m.rename(columns={f'{c}_1': c for c in cols}).drop(columns=[f'{c}_2' for c in cols] + ['_h', '_i_1', '_i_2'])
    m['nivel'] = classifica_nivel(m)
    return m.reset_index(drop=True)


def classifica_nivel(m):
    same_uf = m.uf_1 == m.uf_2
    same_mun = same_uf & (m.municipality_1 == m.municipality_2)
    same_local = same_mun & (m.voting_place_1 == m.voting_place_2)
    return np.select([same_local, same_mun, same_uf], NIVEIS[:3], NIVEIS[3])


def permuta_dentro(v, gid, rng, base=None):
    """Permuta os valores de v dentro de cada grupo (gid), preservando o multiconjunto de cada grupo."""
    v = np.asarray(v)
    base = np.argsort(gid, kind='stable') if base is None else base
    order = np.lexsort((rng.random(len(v)), gid))
    out = np.empty_like(v)
    out[base] = v[order]
    return out


# ----------------------------------------------------------------------------------------------- C7-01
def taxas_loo(d, num, den, niveis=(('uf', 'municipality', 'voting_place'), ('uf', 'municipality'), ('uf',))):
    """Taxa num/den leave-one-out do nivel mais fino com outras secoes (predio > municipio > UF), em (EPS, 1-EPS)."""
    num_v, den_v = d[num].to_numpy(dtype=float), d[den].to_numpy(dtype=float)
    out = np.full(len(d), np.nan)
    for k in niveis:
        g = d.groupby(list(k), sort=False)
        sn = g[num].transform('sum').to_numpy(dtype=float) - num_v
        sd = g[den].transform('sum').to_numpy(dtype=float) - den_v
        ok = np.isnan(out) & (sd > 0)
        out[ok] = sn[ok] / sd[ok]
    tot = (num_v.sum() - num_v) / np.maximum(den_v.sum() - den_v, 1)
    out = np.where(np.isnan(out), tot, out)
    return np.clip(out, EPS, 1 - EPS)


def phi_de(x, n, p):
    """Sobredispersao (phi) pelo desvio absoluto mediano do z binomial, como em padroes_lib.modelo_local (>= 1)."""
    ok = n > 0
    z = (x[ok] - n[ok] * p[ok]) / np.sqrt(n[ok] * p[ok] * (1 - p[ok]))
    return max(float((1.4826 * np.median(np.abs(z - np.median(z)))) ** 2), 1.0)


def beta_binomial(rng, n, p, phi):
    n = np.asarray(n)
    rho = np.clip((phi - 1) / np.maximum(n - 1, 1), 1e-9, .99)
    q = rng.beta(p * (1 / rho - 1), (1 - p) * (1 / rho - 1))
    return rng.binomial(n, q)


def modelo_parametrico(d):
    """Parametros do nulo 1 por secao: taxa LOO de branco e de nulo (sobre comp), fatia A LOO (sobre validos) e phi."""
    m = d[KEY + ['voting_place', 't2_comp', 't2_A', 't2_B', 't2_branco', 't2_nulo']].copy()
    m['t2_validos'] = m.t2_A + m.t2_B
    m['p_branco'] = taxas_loo(m, 't2_branco', 't2_comp')
    m['t2_nb'] = m.t2_comp - m.t2_branco
    m['p_nulo'] = taxas_loo(m, 't2_nulo', 't2_nb')
    m['p_A'] = taxas_loo(m, 't2_A', 't2_validos')
    phi = {'phi_A': phi_de(m.t2_A.to_numpy(float), m.t2_validos.to_numpy(float), m.p_A.to_numpy()),
           'phi_branco': phi_de(m.t2_branco.to_numpy(float), m.t2_comp.to_numpy(float), m.p_branco.to_numpy()),
           'phi_nulo': phi_de(m.t2_nulo.to_numpy(float), m.t2_nb.to_numpy(float), m.p_nulo.to_numpy())}
    return m, phi


def simula_vetores(m, phi, rng):
    """Um sorteio do vetor (branco, nulo, A, B) de cada secao com comp e aptos fixos (nulo 1, parametrico)."""
    n = m.t2_comp.to_numpy()
    branco = beta_binomial(rng, n, m.p_branco.to_numpy(), phi['phi_branco'])
    nulo = beta_binomial(rng, n - branco, m.p_nulo.to_numpy(), phi['phi_nulo'])
    val = n - branco - nulo
    a = beta_binomial(rng, val, m.p_A.to_numpy(), phi['phi_A'])
    return pd.DataFrame({'t2_branco': branco, 't2_nulo': nulo, 't2_A': a, 't2_B': val - a})


def medidas_coincidencia(d, por=('uf', 'faixa')):
    """Contagens de uma base (observada ou simulada): pares identicos, secoes, pares A/B trocados, pares por nivel/UF/faixa."""
    h = hash_vetor(d, VEC_T2)
    pares, grupos, secoes = conta_pares_iguais(h)
    o = {'pares_identicos': pares, 'grupos': grupos, 'secoes_em_par': secoes,
         'pares_trocados': conta_pares_trocados(d, VEC_T2, VEC_T2_TROCADO)}
    m = enumera_pares(d, VEC_T2, campos=('uf', 'municipality', 'voting_place', 'faixa'))
    for n in NIVEIS:
        o[f'pares_{n}'] = int((m.nivel == n).sum())
    por_uf = m.uf_1.value_counts().add(m.uf_2.value_counts(), fill_value=0) if len(m) else pd.Series(dtype=float)
    por_faixa = m.faixa_1.value_counts() if len(m) else pd.Series(dtype=float)
    return o, por_uf, por_faixa


def c7_01_calibracao(d, rng, r_param=R_PARAM, r_perm=R_PERM):
    """Observado x nulo parametrico (nulo 1), permutacao por componente (nulo 2) e geografia (nulo 3) para uma eleicao."""
    d = d[d.elegivel].reset_index(drop=True).copy()
    d['faixa'] = faixa_comp(d.t2_comp)
    obs, obs_uf, obs_faixa = medidas_coincidencia(d)
    # nulo 1
    m, phi = modelo_parametrico(d)
    sims, sim_uf, sim_faixa = [], [], []
    for _ in range(r_param):
        s = simula_vetores(m, phi, rng)
        s['t2_aptos'], s['t2_comp'] = d.t2_aptos.to_numpy(), d.t2_comp.to_numpy()
        for c in ('uf', 'municipality', 'voting_place', 'faixa'):
            s[c] = d[c].to_numpy()
        o, u, f = medidas_coincidencia(s)
        sims.append(o)
        sim_uf.append(u)
        sim_faixa.append(f)
    sims = pd.DataFrame(sims)
    # nulo 2: permutacao de A (e, separadamente, de branco) entre secoes do mesmo estrato nacional (comp, validos)
    val = (d.t2_A + d.t2_B).to_numpy()
    gid = pd.factorize(d.t2_comp.astype(str) + '_' + pd.Series(val).astype(str))[0]
    base = np.argsort(gid, kind='stable')
    perms = []
    A, Br = d.t2_A.to_numpy(), d.t2_branco.to_numpy()
    for _ in range(r_perm):
        s = d[['t2_aptos', 't2_comp']].copy()
        a = permuta_dentro(A, gid, rng, base)
        b = permuta_dentro(Br, gid, rng, base)
        s['t2_A'], s['t2_B'], s['t2_branco'], s['t2_nulo'] = a, val - a, b, d.t2_comp.to_numpy() - val - b
        h = hash_vetor(s, VEC_T2)
        p, _, _ = conta_pares_iguais(h)
        perms.append({'pares_identicos': p, 'pares_trocados': conta_pares_trocados(s, VEC_T2, VEC_T2_TROCADO)})
    perms = pd.DataFrame(perms)
    # nulo 3 (estrutural): entre todos os pares do mesmo estrato (aptos, comp, validos), fracao no mesmo UF/municipio/local
    est = d.groupby(['t2_aptos', 't2_comp']).size()
    tot_pares = float((est * (est - 1) // 2).sum())
    e_uf = d.groupby(['t2_aptos', 't2_comp', 'uf']).size()
    e_mun = d.groupby(['t2_aptos', 't2_comp', 'uf', 'municipality']).size()
    e_loc = d.groupby(['t2_aptos', 't2_comp', 'uf', 'municipality', 'voting_place']).size()
    estrutural = {k: float((v * (v - 1) // 2).sum() / max(tot_pares, 1)) for k, v in
                  (('mesma_uf_ou_mais', e_uf), ('mesmo_municipio_ou_mais', e_mun), ('mesmo_local', e_loc))}
    linhas = []
    for medida in ('pares_identicos', 'pares_trocados') + tuple(f'pares_{n}' for n in NIVEIS):
        o = obs[medida]
        s1 = sims[medida].to_numpy(float)
        row = {'medida': medida, 'observado': o, 'nulo1_media': float(s1.mean()), 'nulo1_dp': float(s1.std(ddof=1)) if len(s1) > 1 else np.nan,
               'nulo1_razao': float(o / s1.mean()) if s1.mean() > 0 else np.nan, **{f'nulo1_{k}': v for k, v in p_empirico(s1, o).items()}}
        if medida in perms:
            s2 = perms[medida].to_numpy(float)
            row.update({'nulo2_media': float(s2.mean()), 'nulo2_dp': float(s2.std(ddof=1)), 'nulo2_razao': float(o / s2.mean()) if s2.mean() > 0 else np.nan,
                        **{f'nulo2_{k}': v for k, v in p_empirico(s2, o).items()}})
        linhas.append(row)
    geo = {'pares_identicos_obs': obs['pares_identicos']}
    tot_obs = max(obs['pares_identicos'], 1)
    tot_sim = max(sims['pares_identicos'].sum(), 1)
    for n in NIVEIS:
        geo[f'frac_obs_{n}'] = obs[f'pares_{n}'] / tot_obs
        geo[f'frac_nulo1_{n}'] = float(sims[f'pares_{n}'].sum() / tot_sim)
    geo.update({f'frac_estrutural_{k}': v for k, v in estrutural.items()})
    uf = pd.DataFrame({'observado': obs_uf, 'nulo1_media': pd.concat(sim_uf, axis=1).fillna(0).mean(axis=1) if sim_uf else np.nan}).fillna(0)
    uf.index.name = 'uf'
    fx = pd.DataFrame({'observado': obs_faixa, 'nulo1_media': pd.concat(sim_faixa, axis=1).fillna(0).mean(axis=1) if sim_faixa else np.nan}).fillna(0)
    fx.index.name = 'faixa_comp'
    fx['secoes'] = d.faixa.value_counts()
    info = {'secoes_elegiveis': int(len(d)), 'r_param': r_param, 'r_perm': r_perm, **{k: float(v) for k, v in phi.items()},
            'secoes_em_par': obs['secoes_em_par'], 'grupos': obs['grupos']}
    return pd.DataFrame(linhas), geo, uf.reset_index(), fx.reset_index(), info


def c7_01_sensibilidade_phi(d, rng, r=R_SENS, phi_fixo=1.0):
    """Sensibilidade do nulo 1: mesmo modelo local, mas sem sobredispersao (phi = 1, piso binomial). Dentro do predio as
    secoes de 2022/2026 variam menos que o binomial (detectores dentro_local_sobre_piso 0,15/0,16), entao o phi global
    (> 2) subestima as coincidencias no mesmo local; este nulo da o limite oposto."""
    d = d[d.elegivel].reset_index(drop=True).copy()
    d['faixa'] = faixa_comp(d.t2_comp)
    m, _ = modelo_parametrico(d)
    phi = {'phi_A': phi_fixo, 'phi_branco': phi_fixo, 'phi_nulo': phi_fixo}
    sims = []
    for _ in range(r):
        sv = simula_vetores(m, phi, rng)
        sv['t2_aptos'], sv['t2_comp'] = d.t2_aptos.to_numpy(), d.t2_comp.to_numpy()
        for c in ('uf', 'municipality', 'voting_place', 'faixa'):
            sv[c] = d[c].to_numpy()
        o, _, _ = medidas_coincidencia(sv)
        sims.append(o)
    return pd.DataFrame(sims)


# ----------------------------------------------------------------------------------------------- C7-02
def c7_02_pares(d, ibge=None):
    """Pares de secoes elegiveis com vetor T2 identico (aptos, comp, A, B, branco, nulo), com nivel geografico e IBGE."""
    e = d[d.elegivel]
    m = enumera_pares(e, VEC_T2)
    if ibge is not None and len(m):
        for s in ('1', '2'):
            m = m.merge(ibge.rename(columns={'uf': f'uf_{s}', 'municipality': f'municipality_{s}', 'microrregiao': f'micro_{s}',
                                             'regiao_imediata': f'rimed_{s}'}), on=[f'uf_{s}', f'municipality_{s}'], how='left')
        m['mesma_microrregiao'] = (m.micro_1 == m.micro_2) & m.micro_1.notna()
        m['mesma_regiao_imediata'] = (m.rimed_1 == m.rimed_2) & m.rimed_1.notna()
        m = m.drop(columns=['micro_1', 'micro_2', 'rimed_1', 'rimed_2'])
    m['fatia_A_pct'] = 100 * m.t2_A / (m.t2_A + m.t2_B)
    return m


def c7_02_resumo(pares, secoes_elegiveis, calib=None):
    o = {'secoes_elegiveis': int(secoes_elegiveis), 'pares': int(len(pares)),
         'secoes_em_par': int(pd.concat([pares[[f'{c}_1' for c in KEY]].set_axis(KEY, axis=1),
                                         pares[[f'{c}_2' for c in KEY]].set_axis(KEY, axis=1)]).drop_duplicates().shape[0]) if len(pares) else 0}
    for n in NIVEIS:
        o[f'pares_{n}'] = int((pares.nivel == n).sum()) if len(pares) else 0
    o['pct_secoes_em_par'] = 100 * o['secoes_em_par'] / max(secoes_elegiveis, 1)
    o['frac_mesma_uf_ou_mais'] = (o['pares_mesmo_local'] + o['pares_mesmo_municipio'] + o['pares_mesma_uf']) / max(o['pares'], 1)
    if calib is not None:
        c = calib.set_index('medida')
        o['nulo1_media_pares'] = float(c.loc['pares_identicos', 'nulo1_media'])
        o['nulo1_razao'] = float(c.loc['pares_identicos', 'nulo1_razao'])
        o['nulo1_p_excesso'] = float(c.loc['pares_identicos', 'nulo1_p_excesso'])
        o['nulo2_media_pares'] = float(c.loc['pares_identicos', 'nulo2_media'])
        o['nulo2_p_excesso'] = float(c.loc['pares_identicos', 'nulo2_p_excesso'])
    return o


def carrega_bins_para(chaves, ano):
    """Histograma de 15 min (64 bins), n_logs e contingencia so das secoes listadas (DuckDB com join numa tabela temporaria)."""
    p = R / 'janelas_horario' / f'bins_{ano}.parquet'
    if not p.exists() or chaves.empty:
        return None
    con = duck()
    con.register('chaves', chaves[KEY].drop_duplicates())
    df = con.execute(f"select b.* from read_parquet('{p.as_posix()}') b join chaves c using (uf, municipality, zone, section)").df()
    con.close()
    return df


def c7_02_logs_dos_pares(pares, bins, hab=None):
    """Para cada par de 2022/2026: distancia L1 entre os histogramas de 15 min, n_logs/contingencia e horarios (quando houver)."""
    if bins is None or pares.empty:
        return pares.assign(bins_L1=np.nan, bins_identicos=False, status_bins=f'{NOT_COMP}: sem bins')
    bcols = [c for c in bins.columns if re.match(r'b\d\dh\d\d$', c)]
    b = bins.set_index(KEY)
    out = pares.copy()
    for s in ('1', '2'):
        k = out[[f'{c}_{s}' for c in KEY]].set_axis(KEY, axis=1)
        idx = pd.MultiIndex.from_frame(k)
        got = b.reindex(idx)
        out[f'n_logs_{s}'] = got.n_logs.to_numpy()
        out[f'contingencia_{s}'] = got.contingencia.to_numpy()
        out[f'votos_log_{s}'] = got[bcols].sum(axis=1).to_numpy()
        out[f'_bins_{s}'] = list(got[bcols].fillna(-1).to_numpy())
    l1 = [np.abs(np.asarray(a) - np.asarray(b_)).sum() if (np.asarray(a) >= 0).all() and (np.asarray(b_) >= 0).all() else np.nan
          for a, b_ in zip(out._bins_1, out._bins_2)]
    out['bins_L1'] = l1
    out['bins_identicos'] = out.bins_L1 == 0
    out['status_bins'] = np.where(out.bins_L1.isna(), f'{NOT_COMP}: secao sem histograma de log', 'comparado')
    out = out.drop(columns=['_bins_1', '_bins_2'])
    if hab is not None:
        h = hab.set_index(KEY)
        for s in ('1', '2'):
            idx = pd.MultiIndex.from_frame(out[[f'{c}_{s}' for c in KEY]].set_axis(KEY, axis=1))
            got = h.reindex(idx)
            for c in ('opening', 'closing', 'hab_0', 'hab_1', 'hab_2'):
                if c in got:
                    out[f'{c}_{s}'] = got[c].to_numpy()
    return out


# ----------------------------------------------------------------------------------------------- C7-03
def vetor_t1_2026(d):
    """Vetor completo do 1o turno de 2026 (todos os NR_VOTAVEL de secoes_t1_t2 + branco, nulo, comp, aptos) como string."""
    cols = sorted([c for c in d.columns if re.match(r't1_v\d+$', c)]) + ['t1_branco', 't1_nulo', 't1_comparecimento', 't1_aptos']
    cols = [c for c in cols if c in d.columns]
    v = d[cols].fillna(-1).astype('int64').astype(str)
    return v.agg('|'.join, axis=1), cols


def carrega_t1_bweb(pleito, con=None):
    """Vetor completo do 1o turno (QT_VOTOS por NR_VOTAVEL ordenado + aptos + comp) por secao, pais inteiro, via BWEB."""
    own = con is None
    con = con or duck()
    out = []
    for p in sorted((R / 'bu' / pleito).glob('*_PRESIDENTE.parquet')):
        uf = p.name.split('_')[0]
        q = f"""select '{uf}' uf, try_cast(CD_MUNICIPIO as integer) municipality, try_cast(NR_ZONA as integer) zone,
 try_cast(NR_SECAO as integer) section, max(try_cast(NR_LOCAL_VOTACAO as integer)) voting_place,
 max(try_cast(QT_APTOS as bigint)) t1_aptos, max(try_cast(QT_COMPARECIMENTO as bigint)) t1_comp,
 string_agg(NR_VOTAVEL || ':' || QT_VOTOS, '|' order by try_cast(NR_VOTAVEL as integer)) votos,
 count(distinct NR_VOTAVEL) n_votaveis,
 max(case when NR_VOTAVEL not in ('{BRANCO}','{NULO}') then try_cast(QT_VOTOS as bigint) else 0 end) max_cand,
 sum(case when NR_VOTAVEL not in ('{BRANCO}','{NULO}') then try_cast(QT_VOTOS as bigint) else 0 end) validos
 from read_parquet('{p.as_posix()}') group by 1,2,3,4"""
        out.append(con.execute(q).df())
    if own:
        con.close()
    d = pd.concat(out, ignore_index=True)
    d['vetor_t1'] = d.t1_aptos.astype(str) + '|' + d.t1_comp.astype(str) + '|' + d.votos
    return d.drop(columns='votos')


def c7_03_t1(d, chave_t1='vetor_t1', comp='t1_comp', uf='uf', degenerado=None):
    """Pares de secoes com vetor T1 identico (sem ZZ, comp >= 50, sem secoes 100% para um candidato)."""
    e = d[(d[uf] != 'ZZ') & (d[comp] >= COMP_MIN)]
    if degenerado is not None:
        e = e[~degenerado.loc[e.index]]
    m = enumera_pares(e.assign(_v=e[chave_t1]), ['_v']).rename(columns={'_v': 'vetor_t1'})
    return m, int(len(e))


def c7_03_t1_e_t2(pares_t2, t1_hash):
    """Entre os pares com T2 identico, os que tambem tem o vetor T1 identico (t1_hash: Series indexada por KEY)."""
    if pares_t2.empty:
        return pares_t2.assign(t1_identico=pd.Series(dtype=bool))
    h = {}
    for s in ('1', '2'):
        idx = pd.MultiIndex.from_frame(pares_t2[[f'{c}_{s}' for c in KEY]].set_axis(KEY, axis=1))
        h[s] = t1_hash.reindex(idx).to_numpy()
    out = pares_t2.copy()
    out['t1_identico'] = (h['1'] == h['2']) & pd.notna(h['1']) & pd.notna(h['2'])
    out['t1_status'] = np.where(pd.isna(h['1']) | pd.isna(h['2']), f'{NOT_COMP}: secao sem vetor T1', 'comparado')
    return out


# ----------------------------------------------------------------------------------------------- C7-04
def c7_04_entre_pleitos(b0, b1, a0, a1, m_sim=None):
    """Mesma secao em dois pleitos: vetor de votos T2 identico, par A/B trocado, proporcao A/(A+B) exatamente igual."""
    k0 = b0[b0.elegivel][KEY + VEC_T2].rename(columns={c: f'{c}_0' for c in VEC_T2})
    k1 = b1[b1.elegivel][KEY + VEC_T2].rename(columns={c: f'{c}_1' for c in VEC_T2})
    m = k0.merge(k1, on=KEY, how='inner')
    m = m[(m.t2_aptos_1 / m.t2_aptos_0 - 1).abs() <= .25].copy()
    m['comp_igual'] = m.t2_comp_0 == m.t2_comp_1
    m['votos_identicos'] = m.comp_igual & (m.t2_A_0 == m.t2_A_1) & (m.t2_B_0 == m.t2_B_1) & (m.t2_branco_0 == m.t2_branco_1) & (m.t2_nulo_0 == m.t2_nulo_1)
    m['ab_identicos'] = (m.t2_A_0 == m.t2_A_1) & (m.t2_B_0 == m.t2_B_1)
    m['ab_trocados'] = (m.t2_A_0 == m.t2_B_1) & (m.t2_B_0 == m.t2_A_1) & (m.t2_A_0 != m.t2_B_0)
    n0, n1 = m.t2_A_0 + m.t2_B_0, m.t2_A_1 + m.t2_B_1
    m['proporcao_igual_n_diferente'] = (m.t2_A_0 * n1 == m.t2_A_1 * n0) & (n0 != n1)
    m['proporcao_igual_trocada_n_diferente'] = (m.t2_A_0 * n1 == m.t2_B_1 * n0) & (n0 != n1) & (m.t2_A_0 != m.t2_B_0)
    o = {'de': a0, 'para': a1, 'secoes_pareadas': int(len(m)), 'comp_igual': int(m.comp_igual.sum()),
         'votos_identicos': int(m.votos_identicos.sum()), 'ab_identicos': int(m.ab_identicos.sum()), 'ab_trocados': int(m.ab_trocados.sum()),
         'proporcao_igual_n_diferente': int(m.proporcao_igual_n_diferente.sum()),
         'proporcao_igual_trocada_n_diferente': int(m.proporcao_igual_trocada_n_diferente.sum())}
    return m, o


def c7_04_esperado_parametrico(m, modelo, phi, rng, r=R_PARAM):
    """Esperado de 'votos identicos' / 'ab identicos' / 'ab trocados' se o pleito 1 fosse sorteado do seu modelo local
    com comp fixo (condicional ao comparecimento observado): o pleito 0 fica como esta."""
    sims = []
    idx = pd.MultiIndex.from_frame(modelo[KEY])
    sel = idx.get_indexer(pd.MultiIndex.from_frame(m[KEY]))
    ok = sel >= 0
    mm = modelo.iloc[sel[ok]].reset_index(drop=True)
    m_ok = m[ok].reset_index(drop=True)
    for _ in range(r):
        s = simula_vetores(mm, phi, rng)
        vi = m_ok.comp_igual & (s.t2_A == m_ok.t2_A_0) & (s.t2_B == m_ok.t2_B_0) & (s.t2_branco == m_ok.t2_branco_0) & (s.t2_nulo == m_ok.t2_nulo_0)
        ab = (s.t2_A == m_ok.t2_A_0) & (s.t2_B == m_ok.t2_B_0)
        tr = (s.t2_A == m_ok.t2_B_0) & (s.t2_B == m_ok.t2_A_0) & (m_ok.t2_A_0 != m_ok.t2_B_0)
        n0, n1 = m_ok.t2_A_0 + m_ok.t2_B_0, s.t2_A + s.t2_B
        pr = (m_ok.t2_A_0 * n1 == s.t2_A * n0) & (n0 != n1)
        sims.append({'votos_identicos': int(vi.sum()), 'ab_identicos': int(ab.sum()), 'ab_trocados': int(tr.sum()),
                     'proporcao_igual_n_diferente': int(pr.sum())})
    return pd.DataFrame(sims), int(ok.sum())


def _logit(p):
    p = np.clip(p, EPS, 1 - EPS)
    return np.log(p / (1 - p))


def fatia_persistencia(m, grupos=(('uf', 'municipality', 'voting_place'), ('uf', 'municipality'), ('uf',))):
    """Fatia A esperada no pleito 1 se cada secao conserva o seu desvio do pleito 0 (logito) e recebe a mudanca do seu predio
    (leave-one-out; cai para municipio e UF quando o predio nao tem outra secao pareada). Colunas: t2_A_0, t2_B_0, t2_A_1, t2_B_1."""
    a0, v0 = m.t2_A_0.to_numpy(float), (m.t2_A_0 + m.t2_B_0).to_numpy(float)
    a1, v1 = m.t2_A_1.to_numpy(float), (m.t2_A_1 + m.t2_B_1).to_numpy(float)
    tmp = pd.DataFrame({'a0': a0, 'v0': v0, 'a1': a1, 'v1': v1})
    for k in grupos[0]:
        tmp[k] = m[k].to_numpy()
    delta = np.full(len(m), np.nan)
    for g in grupos:
        gg = tmp.groupby(list(g), sort=False)
        s = {c: gg[c].transform('sum').to_numpy(float) - tmp[c].to_numpy(float) for c in ('a0', 'v0', 'a1', 'v1')}
        ok = np.isnan(delta) & (s['v0'] > 0) & (s['v1'] > 0)
        d = _logit(s['a1'] / np.maximum(s['v1'], 1)) - _logit(s['a0'] / np.maximum(s['v0'], 1))
        delta[ok] = d[ok]
    delta = np.where(np.isnan(delta), 0.0, delta)
    p0 = (a0 + .5) / (v0 + 1)
    return 1 / (1 + np.exp(-(_logit(p0) + delta)))


def c7_04_esperado_persistencia(m, modelo, phi, rng, r=R_PARAM):
    """Nulo de persistencia: como o parametrico, mas a fatia A do pleito 1 parte da fatia da propria secao no pleito 0 mais a
    mudanca do predio (preserva a correlacao secao a secao entre pleitos, que o nulo local ignora)."""
    idx = pd.MultiIndex.from_frame(modelo[KEY])
    sel = idx.get_indexer(pd.MultiIndex.from_frame(m[KEY]))
    ok = sel >= 0
    mm = modelo.iloc[sel[ok]].reset_index(drop=True).copy()
    m_ok = m[ok].reset_index(drop=True).copy()
    m_ok['voting_place'] = mm.voting_place.to_numpy()
    mm['p_A'] = np.clip(fatia_persistencia(m_ok), EPS, 1 - EPS)
    v1 = (m_ok.t2_A_1 + m_ok.t2_B_1).to_numpy(float)
    phi_p = dict(phi)
    phi_p['phi_A'] = phi_de(m_ok.t2_A_1.to_numpy(float), v1, mm.p_A.to_numpy())
    sims = []
    for _ in range(r):
        s = simula_vetores(mm, phi_p, rng)
        vi = m_ok.comp_igual & (s.t2_A == m_ok.t2_A_0) & (s.t2_B == m_ok.t2_B_0) & (s.t2_branco == m_ok.t2_branco_0) & (s.t2_nulo == m_ok.t2_nulo_0)
        ab = (s.t2_A == m_ok.t2_A_0) & (s.t2_B == m_ok.t2_B_0)
        tr = (s.t2_A == m_ok.t2_B_0) & (s.t2_B == m_ok.t2_A_0) & (m_ok.t2_A_0 != m_ok.t2_B_0)
        n0, n1 = m_ok.t2_A_0 + m_ok.t2_B_0, s.t2_A + s.t2_B
        pr = (m_ok.t2_A_0 * n1 == s.t2_A * n0) & (n0 != n1)
        sims.append({'votos_identicos': int(vi.sum()), 'ab_identicos': int(ab.sum()), 'ab_trocados': int(tr.sum()),
                     'proporcao_igual_n_diferente': int(pr.sum())})
    return pd.DataFrame(sims), float(phi_p['phi_A'])


def c7_04_espelho_forte(b0, b1, a0, a1):
    """Reproduz padroes_aberta.espelho no nivel secao e devolve as secoes 'espelho_forte' (inversao de fatia, nao copia)."""
    x0, x1 = b0[b0.uf != 'ZZ'], b1[b1.uf != 'ZZ']
    g0 = x0.set_index(KEY)[['t2_A', 't2_B', 't2_aptos']]
    g1 = x1.set_index(KEY)[['t2_A', 't2_B', 't2_aptos']]
    m = g0.join(g1, lsuffix='_0', rsuffix='_1', how='inner')
    m = m[(m.t2_A_0 + m.t2_B_0 >= 30) & (m.t2_A_1 + m.t2_B_1 >= 30)]
    m = m[(m.t2_aptos_1 / m.t2_aptos_0 - 1).abs() <= .25]
    p0 = m.t2_A_0 / (m.t2_A_0 + m.t2_B_0)
    p1 = m.t2_A_1 / (m.t2_A_1 + m.t2_B_1)
    dn = x1.t2_A.sum() / (x1.t2_A.sum() + x1.t2_B.sum()) - x0.t2_A.sum() / (x0.t2_A.sum() + x0.t2_B.sum())
    r = p1 - (p0 + dn)
    rm = p1 - (1 - p0 - dn)
    vis = (1 - 2 * p0).abs() >= .25
    forte = vis & (r.abs() >= .15) & (rm.abs() <= .05)
    out = m[forte].assign(de=a0, para=a1, fatia_A_antes_pct=100 * p0[forte], fatia_A_depois_pct=100 * p1[forte],
                          residuo_pp=100 * r[forte], residuo_espelho_pp=100 * rm[forte]).reset_index()
    return out, {'de': a0, 'para': a1, 'unidades': int(len(m)), 'visiveis': int(vis.sum()), 'espelho_forte': int(forte.sum()),
                 'mudanca_nacional_pp': 100 * float(dn)}


def contexto_espelho(fortes, bases):
    """Acrescenta a cada secao 'espelho_forte' o 1o turno dos dois pleitos, o local de votacao e a fatia A do predio inteiro
    (bases: {ano: DataFrame com KEY, voting_place, t1_A, t1_B, t2_A, t2_B}). Secao unica no predio -> fatia do predio = da secao."""
    out = fortes.copy()
    for suf, col in (('0', 'de'), ('1', 'para')):
        partes = []
        for ano, g in out.groupby(col):
            b = bases(ano) if callable(bases) else bases[ano]
            pr = b.groupby(['uf', 'municipality', 'voting_place']).agg(pA=('t2_A', 'sum'), pB=('t2_B', 'sum'), secoes_predio=('t2_A', 'size'))
            pr = pr.reset_index()
            x = g[KEY].merge(b[KEY + ['voting_place', 't1_A', 't1_B']], on=KEY, how='left').merge(pr, on=['uf', 'municipality', 'voting_place'], how='left')
            x['fatia_A_predio_pct'] = 100 * x.pA / (x.pA + x.pB)
            x['fatia_A_t1_pct'] = 100 * x.t1_A / (x.t1_A + x.t1_B)
            x.index = g.index
            partes.append(x[['voting_place', 't1_A', 't1_B', 'fatia_A_t1_pct', 'fatia_A_predio_pct', 'secoes_predio']])
        ctx = pd.concat(partes).add_suffix(f'_{suf}')
        out = out.join(ctx)
    return out


# ----------------------------------------------------------------------------------------------- C7-05
def runs_iguais(valores, gid):
    """Numero de pares adjacentes iguais, trios adjacentes iguais e maior run, dentro de cada grupo (ordem dada)."""
    v = np.asarray(valores)
    g = np.asarray(gid)
    same = (v[1:] == v[:-1]) & (g[1:] == g[:-1])
    pares = int(same.sum())
    trios = int((same[1:] & same[:-1]).sum())
    maior = 0
    if len(v):
        runs = np.diff(np.flatnonzero(np.concatenate(([True], ~same, [True]))))
        maior = int(runs.max()) if len(runs) else 1
    return pares, trios, maior


def c7_05_comparecimento(d, rng, r=R_PERM):
    """Comparecimento identico em secoes consecutivas da zona (ordem numerica da secao): observado x permutacoes."""
    e = d[d.uf != 'ZZ'].sort_values(KEY).reset_index(drop=True)
    e = e[e.t2_comp >= COMP_MIN].reset_index(drop=True)
    gz = pd.factorize(e.uf + '_' + e.municipality.astype(str) + '_' + e.zone.astype(str))[0]
    comp, aptos = e.t2_comp.to_numpy(), e.t2_aptos.to_numpy()
    pares, trios, maior = runs_iguais(comp, gz)
    same = (comp[1:] == comp[:-1]) & (gz[1:] == gz[:-1])
    aptos_dif = int((same & (aptos[1:] != aptos[:-1])).sum())
    sec_consec = int((same & (e.section.to_numpy()[1:] - e.section.to_numpy()[:-1] == 1)).sum())
    # predios (>= 3 secoes) com todas as secoes com o mesmo comparecimento
    gl = e.groupby(['uf', 'municipality', 'voting_place'])
    nun = gl.t2_comp.transform('nunique')
    nloc = gl.t2_comp.transform('size')
    predios_iguais = int(((nun == 1) & (nloc >= 3)).groupby([e.uf, e.municipality, e.voting_place]).any().sum())
    predios_3mais = int((gl.size() >= 3).sum())
    # nulos: permutar comp dentro da zona (A) e dentro de (zona, aptos) (B)
    ga = pd.factorize(pd.Series(gz).astype(str) + '_' + pd.Series(aptos).astype(str))[0]
    base_z, base_a = np.argsort(gz, kind='stable'), np.argsort(ga, kind='stable')
    sa, sb = [], []
    for _ in range(r):
        ca = permuta_dentro(comp, gz, rng, base_z)
        pa, ta, _ = runs_iguais(ca, gz)
        sa.append((pa, ta))
        cb = permuta_dentro(comp, ga, rng, base_a)
        pb, tb, _ = runs_iguais(cb, gz)
        sb.append((pb, tb))
    sa, sb = np.array(sa, float), np.array(sb, float)
    o = {'secoes': int(len(e)), 'pares_consecutivos_iguais': pares, 'trios_consecutivos_iguais': trios, 'maior_run': maior,
         'pares_iguais_com_aptos_diferente': aptos_dif, 'pares_iguais_secoes_numeradas_em_sequencia': sec_consec,
         'predios_3mais': predios_3mais, 'predios_todas_secoes_comp_igual': predios_iguais,
         'nuloA_zona_pares_media': float(sa[:, 0].mean()), 'nuloA_zona_pares_dp': float(sa[:, 0].std(ddof=1)),
         'nuloA_razao': pares / max(sa[:, 0].mean(), 1e-9), **{f'nuloA_{k}': v for k, v in p_empirico(sa[:, 0], pares).items()},
         'nuloA_trios_media': float(sa[:, 1].mean()),
         'nuloB_zona_aptos_pares_media': float(sb[:, 0].mean()), 'nuloB_zona_aptos_pares_dp': float(sb[:, 0].std(ddof=1)),
         'nuloB_razao': pares / max(sb[:, 0].mean(), 1e-9), **{f'nuloB_{k}': v for k, v in p_empirico(sb[:, 0], pares).items()},
         'nuloB_trios_media': float(sb[:, 1].mean()), 'r': r}
    # por UF e por faixa de aptos (observado e nulo B, uma permutacao media por estrato: usa o ultimo sorteio e o observado)
    pos = np.flatnonzero(same) + 1
    por_uf = e.uf.iloc[pos].value_counts().rename('pares_iguais').to_frame()
    por_uf['secoes'] = e.uf.value_counts()
    por_uf['por_mil_secoes'] = 1000 * por_uf.pares_iguais / por_uf.secoes
    por_uf.index.name = 'uf'
    fx = faixa_comp(e.t2_aptos.clip(upper=9999))
    por_faixa = fx.iloc[pos].value_counts().rename('pares_iguais').to_frame()
    por_faixa['secoes'] = fx.value_counts()
    por_faixa['por_mil_secoes'] = 1000 * por_faixa.pares_iguais / por_faixa.secoes
    por_faixa.index.name = 'faixa_aptos'
    pares_lista = pd.DataFrame({'uf': e.uf.iloc[pos].to_numpy(), 'municipality': e.municipality.iloc[pos].to_numpy(),
                                'zone': e.zone.iloc[pos].to_numpy(), 'section_1': e.section.iloc[pos - 1].to_numpy(),
                                'section_2': e.section.iloc[pos].to_numpy(), 't2_comp': comp[pos], 't2_aptos_1': aptos[pos - 1],
                                't2_aptos_2': aptos[pos], 'mesmo_local': (e.voting_place.to_numpy()[pos - 1] == e.voting_place.to_numpy()[pos])})
    return o, por_uf.reset_index(), por_faixa.reset_index(), pares_lista


# ----------------------------------------------------------------------------------------------- C7-06
def medidas_predio(v, gid, section=None):
    """Por predio (ordem dada): trios em progressao aritmetica (2a diferenca zero, nao constantes), trios constantes,
    comprimento do maior run estritamente monotono."""
    v = np.asarray(v, dtype=np.int64)
    g = np.asarray(gid)
    d1 = v[1:] - v[:-1]
    okg = g[1:] == g[:-1]
    d2 = d1[1:] - d1[:-1]
    trio_ok = okg[1:] & okg[:-1]
    const = trio_ok & (d1[1:] == 0) & (d1[:-1] == 0)
    prog = trio_ok & (d2 == 0) & ~const
    up = okg & (d1 > 0)
    down = okg & (d1 < 0)
    best = 1
    for s in (up, down):
        if len(s):
            runs = np.diff(np.flatnonzero(np.concatenate(([True], ~s, [True]))))
            best = max(best, int(runs.max()) if len(runs) else 1)
    return int(prog.sum()), int(const.sum()), best


def c7_06_sequencias(d, rng, r=R_PERM):
    """Sequencias numericas entre secoes consecutivas do mesmo predio (>= 3 secoes), observado x permutacoes."""
    e = d[(d.uf != 'ZZ') & d.elegivel].sort_values(KEY).reset_index(drop=True)
    gl = pd.factorize(e.uf + '_' + e.municipality.astype(str) + '_' + e.voting_place.astype(str))[0]
    nl = pd.Series(gl).map(pd.Series(gl).value_counts())
    e = e[(nl >= 3).to_numpy()].reset_index(drop=True)
    gl = pd.factorize(e.uf + '_' + e.municipality.astype(str) + '_' + e.voting_place.astype(str))[0]
    gm = pd.factorize(e.uf + '_' + e.municipality.astype(str))[0]
    out = {'predios_3mais': int(len(np.unique(gl))), 'secoes': int(len(e)), 'r': r}
    base_l, base_m = np.argsort(gl, kind='stable'), np.argsort(gm, kind='stable')
    A, B = e.t2_A.to_numpy(), e.t2_B.to_numpy()
    diff = A - B
    lastA = A % 10
    # observados
    for nome, v in (('A', A), ('B', B)):
        prog, const, run = medidas_predio(v, gl)
        out[f'{nome}_trios_progressao'] = prog
        out[f'{nome}_trios_constantes'] = const
        out[f'{nome}_maior_run_monotono'] = run
    # por predio: ultimo digito de A igual em todas; A-B constante em todas; run monotono >= 5
    def por_predio(v):
        s = pd.Series(v)
        return s.groupby(gl).nunique()
    out['predios_ultimo_digito_A_igual'] = int((por_predio(lastA) == 1).sum())
    out['predios_A_menos_B_constante'] = int((por_predio(diff) == 1).sum())
    out['predios_A_constante'] = int((por_predio(A) == 1).sum())
    sims = []
    for _ in range(r):
        ap = permuta_dentro(A, gl, rng, base_l)
        bp = permuta_dentro(B, gl, rng, base_l)
        pa, _, ra = medidas_predio(ap, gl)
        pb, _, rb = medidas_predio(bp, gl)
        am = permuta_dentro(A, gm, rng, base_m)  # A embaralhado entre predios do municipio
        ld = int((pd.Series(am % 10).groupby(gl).nunique() == 1).sum())
        dc = int((pd.Series(am - B).groupby(gl).nunique() == 1).sum())
        sims.append({'A_trios_progressao': pa, 'B_trios_progressao': pb, 'A_maior_run_monotono': ra, 'B_maior_run_monotono': rb,
                     'predios_ultimo_digito_A_igual': ld, 'predios_A_menos_B_constante': dc})
    sims = pd.DataFrame(sims)
    linhas = []
    for med in sims.columns:
        s = sims[med].to_numpy(float)
        o = out[med]
        linhas.append({'medida': med, 'observado': o, 'nulo_media': float(s.mean()), 'nulo_dp': float(s.std(ddof=1)),
                       'razao': o / s.mean() if s.mean() > 0 else np.nan, **p_empirico(s, o),
                       'nulo': 'ordem das secoes permutada no predio' if 'trios' in med or 'run' in med else 'A embaralhado entre predios do municipio'})
    # predios sinalizados (listagem descritiva): ultimo digito igual com >= 4 secoes, ou A-B constante com >= 3
    npred = pd.Series(gl).value_counts()
    flags = pd.DataFrame({'gl': np.arange(len(npred)), 'secoes': npred.sort_index().to_numpy()})
    flags['ultimo_digito_A_igual'] = (por_predio(lastA) == 1).to_numpy()
    flags['A_menos_B_constante'] = (por_predio(diff) == 1).to_numpy()
    flags['A_constante'] = (por_predio(A) == 1).to_numpy()
    sel = flags[(flags.ultimo_digito_A_igual & (flags.secoes >= 4)) | flags.A_menos_B_constante | flags.A_constante]
    first = e.groupby(gl).first()[['uf', 'municipality', 'voting_place']]
    lista = sel.merge(first, left_on='gl', right_index=True, how='left').drop(columns='gl')
    lista['secoes_A'] = sel.gl.map(pd.Series(A).groupby(gl).agg(lambda s: '|'.join(map(str, s)))).to_numpy()
    lista['secoes_B'] = sel.gl.map(pd.Series(B).groupby(gl).agg(lambda s: '|'.join(map(str, s)))).to_numpy()
    return out, pd.DataFrame(linhas), lista


# ----------------------------------------------------------------------------------------------- C7-07
def _nulos_dict(s):
    try:
        d = json.loads(s) if isinstance(s, str) and s else {}
    except ValueError:
        d = {}
    return {str(k): int(v) for k, v in d.items()}


def l1_dicts(a, b):
    ks = set(a) | set(b)
    return int(sum(abs(a.get(k, 0) - b.get(k, 0)) for k in ks))


def c7_07_quase_duplicatas(rdv, rng, r=20):
    """Pares de secoes com (v13, v22, branco, nulo) identicos: distancia L1 entre as contagens por codigo nulo digitado,
    contra um nulo que embaralha os codigos entre secoes com o mesmo total de nulos."""
    e = rdv[(rdv.uf != 'ZZ')].copy()
    e['comp'] = e.v13 + e.v22 + e.branco + e.nulo
    e = e[(e.comp >= COMP_MIN) & (e.v13 > 0) & (e.v22 > 0)].reset_index(drop=True)
    m = enumera_pares(e.assign(voting_place=-1), ['v13', 'v22', 'branco', 'nulo'], campos=('uf', 'municipality', 'zone', 'section', 'voting_place'))
    m = m.drop(columns=['voting_place_1', 'voting_place_2', 'nivel'], errors='ignore')
    raw = e.nulos.to_numpy()
    _cache = {}

    def nd(i):  # parse preguicoso do JSON de nulos (evita ~490 mil dicionarios em memoria)
        i = int(i)
        if i not in _cache:
            _cache[i] = _nulos_dict(raw[i])
        return _cache[i]
    idx = pd.MultiIndex.from_frame(e[KEY])
    pos1 = idx.get_indexer(pd.MultiIndex.from_frame(m[[f'{c}_1' for c in KEY]].set_axis(KEY, axis=1)))
    pos2 = idx.get_indexer(pd.MultiIndex.from_frame(m[[f'{c}_2' for c in KEY]].set_axis(KEY, axis=1)))
    m['nulos_L1'] = [l1_dicts(nd(i), nd(j)) for i, j in zip(pos1, pos2)]
    m['nulos_identicos'] = m.nulos_L1 == 0
    m['n_codigos_1'] = [len(nd(i)) for i in pos1]
    # nulos: para cada par, trocar os codigos da secao 2 pelos de outra secao com o mesmo total de nulos, sorteada
    # (a) no pais inteiro, (b) na mesma UF da secao 2 (habito regional de digitacao de nulos), (c) no mesmo decil da fatia
    # v13/(v13+v22) (o padrao de codigos nulos acompanha o perfil de voto da secao)
    def _key(j, chave):
        return tuple(e.loc[j, chave]) if len(chave) > 1 else e.loc[j, chave[0]]

    def simula(chave, reserva=('nulo',)):
        """Sorteia a secao substituta no estrato `chave`, excluindo as duas secoes do par; estrato sem outra secao cai para
        `reserva` (so o total de nulos). Devolve o nº de pares com codigos nulos identicos em cada repeticao."""
        pools = e.groupby(chave if len(chave) > 1 else chave[0]).indices
        pools_r = e.groupby(list(reserva) if len(reserva) > 1 else reserva[0]).indices
        alvo = [(_key(j, chave), _key(j, list(reserva))) for j in pos2]
        sims = []
        for _ in range(r):
            ident = 0
            for i, j, (a, ar) in zip(pos1, pos2, alvo):
                cand = pools[a]
                cand = cand[(cand != j) & (cand != i)]
                if len(cand) == 0:
                    cand = pools_r[ar]
                    cand = cand[(cand != j) & (cand != i)]
                if len(cand) == 0:
                    continue
                k = cand[rng.integers(len(cand))]
                ident += l1_dicts(nd(i), nd(k)) == 0
            sims.append(ident)
        return np.asarray(sims, float)
    obs = int(m.nulos_identicos.sum())
    e['decil_A'] = pd.qcut(e.v13 / (e.v13 + e.v22), 10, labels=False, duplicates='drop')
    s_nac, s_uf, s_dec = simula(['nulo']), simula(['uf', 'nulo']), simula(['decil_A', 'nulo'])
    s_conj = simula(['uf', 'decil_A', 'nulo'])
    mesma_uf = m.uf_1 == m.uf_2
    o = {'secoes': int(len(e)), 'pares_votos_identicos': int(len(m)), 'pares_nulos_identicos': obs,
         'pares_nulos_identicos_nulo_ge3': int((m.nulos_identicos & (m.nulo >= 3)).sum()),
         'frac_mesma_uf_todos_os_pares': float(mesma_uf.mean()) if len(m) else np.nan,
         'frac_mesma_uf_pares_nulos_identicos': float(mesma_uf[m.nulos_identicos].mean()) if obs else np.nan,
         'nulo_media_identicos': float(s_nac.mean()) if r else np.nan, 'nulo_dp': float(s_nac.std(ddof=1)) if r > 1 else np.nan,
         **p_empirico(s_nac, obs),
         'nulo_uf_media_identicos': float(s_uf.mean()) if r else np.nan, 'nulo_uf_dp': float(s_uf.std(ddof=1)) if r > 1 else np.nan,
         **{f'nulo_uf_{k}': v for k, v in p_empirico(s_uf, obs).items()},
         'nulo_decilA_media_identicos': float(s_dec.mean()) if r else np.nan, 'nulo_decilA_dp': float(s_dec.std(ddof=1)) if r > 1 else np.nan,
         **{f'nulo_decilA_{k}': v for k, v in p_empirico(s_dec, obs).items()},
         'nulo_uf_decilA_media_identicos': float(s_conj.mean()) if r else np.nan, 'nulo_uf_decilA_dp': float(s_conj.std(ddof=1)) if r > 1 else np.nan,
         **{f'nulo_uf_decilA_{k}': v for k, v in p_empirico(s_conj, obs).items()}, 'r': r}
    return m, o


def carrega_rdv_2026():
    cols = ['uf', 'municipio', 'zona', 'secao', 'v13', 'v22', 'branco', 'nulo', 'nulos']
    out = []
    for p in sorted((R / 'rdv_gatilho' / '2026-t2').glob('*.parquet')):
        d = pd.read_parquet(p, columns=cols)
        out.append(d)
    d = pd.concat(out, ignore_index=True).rename(columns={'municipio': 'municipality', 'zona': 'zone', 'secao': 'section'})
    for c in ('municipality', 'zone', 'section', 'v13', 'v22', 'branco', 'nulo'):
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d = d.dropna(subset=['municipality', 'zone', 'section'])
    for c in ('municipality', 'zone', 'section', 'v13', 'v22', 'branco', 'nulo'):
        d[c] = d[c].astype('int64')
    return d


# ----------------------------------------------------------------------------------------------- C7-08 (lista fase A)
def c7_08_lista_fase_a(bins, ano, caminhos=None):
    """Secoes com mais de um log distinto no pacote (n_logs >= 2), com e sem marca de contingencia: alvo da fase A."""
    b = bins[bins.n_logs >= 2][KEY + ['n_logs', 'contingencia']].copy()
    b['ano'] = ano
    b['classe'] = np.where(b.contingencia, 'n_logs>=2 com contingencia', 'n_logs>=2 sem marca de contingencia')
    if caminhos is not None:
        b = b.merge(caminhos, on=KEY, how='left')
    return b


# ----------------------------------------------------------------------------------------------- C7-09
SERIES_NULAS = {'', '-1', '0', '#NULO#', '#NE#', 'NAN', 'NONE'}


def serie_nula(x):
    """Serie de urna ausente ou marcador de nulo do TSE (#NULO#, #NE#, -1, 0, vazio)."""
    x = pd.Series(x)
    return x.isna() | x.astype(str).str.strip().str.upper().isin(SERIES_NULAS)


def c7_09_series_repetidas(sec):
    """Series (NR_URNA_EFETIVADA) em mais de uma secao do mesmo pleito/UF: lista por secao e resumo da serie."""
    s = sec.dropna(subset=['urna']).copy()
    s = s[~serie_nula(s.urna)]
    g = s.groupby(['pleito', 'uf', 'urna'])
    n = g.section.transform('size')
    rep = s[n > 1].sort_values(['pleito', 'uf', 'urna', 'municipality', 'zone', 'section']).copy()
    if rep.empty:
        return rep, pd.DataFrame(columns=['pleito', 'uf', 'urna', 'secoes', 'municipios', 'tipos_urna', 'vetores_distintos', 'vetores_identicos'])
    gg = rep.groupby(['pleito', 'uf', 'urna'])
    cols = {'secoes': gg.size(), 'municipios': gg.municipality.nunique(), 'zonas': gg.zone.nunique(),
            'tipos_urna': gg.tipo_urna.agg(lambda x: '|'.join(sorted(set(map(str, x))))), 'comp_distintos': gg.comp.nunique()}
    if 'vetor' in rep:  # o carregador leve traz o vetor e os horarios depois, so para as secoes repetidas
        cols['vetores_distintos'] = gg.vetor.nunique()
    for c, nome in (('abertura', 'aberturas'), ('encerramento', 'encerramentos')):
        if c in rep:
            cols[nome] = gg[c].agg(lambda x: '|'.join(sorted(set(map(str, x.dropna())))))
    res = pd.DataFrame(cols).reset_index()
    if 'vetores_distintos' in res:
        res['vetores_identicos'] = res.vetores_distintos < res.secoes
    return rep, res


def c7_09_resumo_pleito(sec, rep):
    g = sec.groupby('pleito')
    o = pd.DataFrame({'secoes': g.size(), 'secoes_sem_serie': g.urna.apply(lambda x: int(serie_nula(x).sum())),
                      'series_distintas': g.urna.nunique(), 'secoes_mais_de_uma_serie': g.n_urna.apply(lambda x: int((x > 1).sum()))})
    if len(rep):
        r = rep.groupby('pleito')
        o['series_repetidas'] = r.urna.nunique()
        o['secoes_em_serie_repetida'] = r.size()
        o['secoes_repetidas_tipo'] = r.tipo_urna.apply(lambda x: json.dumps(x.astype(str).value_counts().to_dict(), ensure_ascii=False))
    o = o.fillna({'series_repetidas': 0, 'secoes_em_serie_repetida': 0, 'secoes_repetidas_tipo': '{}'})
    return o.reset_index()


def carrega_ceft(pleito, uf, con=None):
    """CEFT por secao, com ou sem cabecalho (2012-2016 mapeado por posicao); None se nao houver."""
    p = R / 'ceft' / pleito / f'{uf}.parquet'
    if not p.exists():
        return None
    names = pq_names(p)
    own = con is None
    con = con or duck()
    if 'NR_URNA_ESPERADA' in names:
        div = 'DS_DIVERGENCIA' if 'DS_DIVERGENCIA' in names else 'TP_DIVERGENCIA' if 'TP_DIVERGENCIA' in names else 'NULL'
        q = f"""select '{uf}' uf, try_cast(CD_MUNICIPIO as integer) municipality, try_cast(NR_ZONA as integer) zone,
 try_cast(NR_SECAO as integer) section, NR_URNA_ESPERADA esperada, NR_URNA_EFETIVADA efetivada, DS_ORIGEM_VOTO origem,
 {div} divergencia from read_parquet('{p.as_posix()}')"""
        layout = 'com cabecalho'
    else:
        c = CEFT_SEM_CABECALHO
        q = f"""select '{uf}' uf, try_cast({c['municipality']} as integer) municipality, try_cast({c['zone']} as integer) zone,
 try_cast({c['section']} as integer) section, {c['esperada']} esperada, {c['efetivada']} efetivada, {c['origem']} origem,
 {c['divergencia']} divergencia from read_parquet('{p.as_posix()}')"""
        layout = 'sem cabecalho (c9/c17/c25/c26 por posicao)'
    df = con.execute(q).df()
    if own:
        con.close()
    df['pleito'], df['layout'] = pleito, layout
    df['troca'] = (df.esperada.astype(str) != df.efetivada.astype(str)) & df.esperada.notna() & df.efetivada.notna()
    return df


def ceft_series_repetidas(ceft):
    """Linhas do CEFT cuja urna efetivada aparece em mais de uma SECAO distinta (linhas repetidas da mesma secao nao contam)."""
    c = ceft.dropna(subset=['efetivada'])
    c = c[c.efetivada.astype(str).str.strip().ne('')]
    u = c.drop_duplicates(['pleito', 'uf'] + KEY + ['efetivada'])
    n = u.groupby(['pleito', 'uf', 'efetivada']).section.size().rename('secoes_com_a_serie')
    n = n[n > 1].reset_index()
    return c.merge(n, on=['pleito', 'uf', 'efetivada'], how='inner')


def c7_09_ceft_resumo(ceft):
    g = ceft.groupby(['pleito', 'uf'])
    o = pd.DataFrame({'linhas': g.size(), 'secoes': g.apply(lambda x: int(x[['municipality', 'zone', 'section']].drop_duplicates().shape[0])),
                      'efetivada_diferente_da_esperada': g.troca.sum(), 'layout': g.layout.first(),
                      'origens': g.origem.apply(lambda x: json.dumps(x.astype(str).value_counts().to_dict(), ensure_ascii=False)),
                      'divergencias': g.divergencia.apply(lambda x: json.dumps(x.astype(str).value_counts().to_dict(), ensure_ascii=False))})
    o['linhas_alem_de_uma_por_secao'] = o.linhas - o.secoes
    o['pct_troca'] = 100 * o.efetivada_diferente_da_esperada / o.linhas
    rep = ceft_series_repetidas(ceft)
    if len(rep):
        r = rep.groupby(['pleito', 'uf'])
        o['series_efetivadas_em_mais_de_uma_secao'] = r.efetivada.nunique()
        o['secoes_com_serie_efetivada_repetida'] = r.apply(lambda x: int(x[['municipality', 'zone', 'section']].drop_duplicates().shape[0]))
    else:
        o['series_efetivadas_em_mais_de_uma_secao'] = 0
        o['secoes_com_serie_efetivada_repetida'] = 0
    return o.fillna({'series_efetivadas_em_mais_de_uma_secao': 0, 'secoes_com_serie_efetivada_repetida': 0}).reset_index()


# ----------------------------------------------------------------------------------------------- C7-13
def dup_bweb_uf(con, path, uf, pleito, cargo):
    q = f"""with l as (select CD_MUNICIPIO, NR_ZONA, NR_SECAO, CD_CARGO_PERGUNTA, NR_VOTAVEL, QT_VOTOS from read_parquet('{Path(path).as_posix()}')),
 g as (select CD_MUNICIPIO, NR_ZONA, NR_SECAO, CD_CARGO_PERGUNTA, NR_VOTAVEL, count(*) n, count(distinct QT_VOTOS) nv from l group by all)
 select '{pleito}' pleito, '{cargo}' cargo, '{uf}' uf, (select count(*) from l) linhas, count(*) chaves,
 sum(case when n > 1 then 1 else 0 end) chaves_duplicadas, sum(case when n > 1 then n - 1 else 0 end) linhas_excedentes,
 sum(case when nv > 1 then 1 else 0 end) chaves_duplicadas_com_votos_diferentes from g"""
    res = con.execute(q).df()
    casos = pd.DataFrame()
    if int(res.chaves_duplicadas.iloc[0]) > 0:
        casos = con.execute(f"""select '{pleito}' pleito, '{cargo}' cargo, '{uf}' uf, CD_MUNICIPIO, NR_ZONA, NR_SECAO, CD_CARGO_PERGUNTA, NR_VOTAVEL,
 count(*) n, string_agg(QT_VOTOS, '|') votos from read_parquet('{Path(path).as_posix()}') group by all having count(*) > 1 limit 5000""").df()
    return res, casos


def c7_13_stems(con, pleito):
    out = []
    base = R / 'bu_urna' / pleito
    if not base.exists():
        return pd.DataFrame()
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        parts = sorted(d.glob('part-*.parquet'))
        if not parts:
            continue
        q = f"""select '{pleito}' pleito, '{d.name}' uf, count(*) linhas, count(distinct stem) stems, count(distinct arquivo) arquivos,
 count(*) - count(distinct stem) stems_repetidos from read_parquet({[p.as_posix() for p in parts]!r})"""
        out.append(con.execute(q).df())
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def c7_13_sistema_resultados(con):
    p = R / 'segundo_turno_2026' / 'bu_todos_decodificados.parquet'
    if not p.exists():
        return None, None
    res = con.execute(f"""select count(*) linhas, count(distinct (uf, municipality, zone, section)) chaves,
 count(log_name) com_log_name, count(distinct log_name) log_names_distintos, count(hash) com_hash, count(distinct hash) hashes_distintos
 from read_parquet('{p.as_posix()}')""").df()
    dup = con.execute(f"""select hash, count(*) n, string_agg(uf || '/' || municipality || '/' || zone || '/' || section, '|') secoes
 from read_parquet('{p.as_posix()}') where hash is not null group by 1 having count(*) > 1
 union all
 select log_name, count(*) n, string_agg(uf || '/' || municipality || '/' || zone || '/' || section, '|') secoes
 from read_parquet('{p.as_posix()}') where log_name is not null group by 1 having count(*) > 1""").df()
    return res, dup


def c7_13_duplicatas_chave(df, chave, valor):
    """Puro: linhas com a mesma chave; quantas tem o valor igual (republicacao) e quantas diferente."""
    g = df.groupby(chave)
    n = g[valor].transform('size')
    nv = g[valor].transform('nunique')
    dup = df[n > 1].copy()
    dup['valor_diferente'] = (nv > 1)[n > 1]
    return {'linhas': int(len(df)), 'chaves': int(g.ngroups), 'chaves_duplicadas': int((g.size() > 1).sum()),
            'chaves_duplicadas_com_valor_diferente': int((g[valor].nunique() > 1).sum())}, dup


# ----------------------------------------------------------------------------------------------- runners
def _carrega_todas(cache, extra=()):
    for ano in ANOS:
        if ano not in cache:
            cache[ano] = carrega_base(ano, extra=extra)
    return cache


def roda_c7_01(resumo, achados, cache):
    rng = np.random.default_rng(SEED)
    calibs, geos, ufs, fxs, infos = [], [], [], [], []
    for ano in ANOS:
        d = carrega_base(ano)
        inv = d[d.t2_comp != d.t2_A + d.t2_B + d.t2_branco + d.t2_nulo]
        quarentena('C7-01', inv, 'comp != A + B + branco + nulo')
        d = d[d.t2_comp == d.t2_A + d.t2_B + d.t2_branco + d.t2_nulo]
        cal, geo, uf, fx, info = c7_01_calibracao(d, rng)
        cal.insert(0, 'ano', ano)
        uf.insert(0, 'ano', ano)
        fx.insert(0, 'ano', ano)
        calibs.append(cal)
        geos.append({'ano': ano, **geo})
        ufs.append(uf)
        fxs.append(fx)
        infos.append({'ano': ano, 'secoes_total': int(len(d)), 'secoes_zz': int((d.uf == 'ZZ').sum()),
                      'secoes_comp_lt_50': int((d.t2_comp < COMP_MIN).sum()), 'secoes_degeneradas_A0_ou_B0': int(((d.t2_A == 0) | (d.t2_B == 0)).sum()), **info})
        cache[ano] = d
        print(f'  C7-01 {ano}: {info}', flush=True)
        gc.collect()
    cal = pd.concat(calibs, ignore_index=True)
    files = [csv_out('C7-01_calibracao.csv', cal), csv_out('C7-01_geografia_dos_pares.csv', pd.DataFrame(geos)),
             csv_out('C7-01_por_uf.csv', pd.concat(ufs, ignore_index=True)), csv_out('C7-01_por_faixa_comp.csv', pd.concat(fxs, ignore_index=True)),
             csv_out('C7-01_parametros.csv', pd.DataFrame(infos))]
    cache['calib'] = cal
    nums = {}
    for ano in ANOS:
        c = cal[(cal.ano == ano)].set_index('medida')
        i = [x for x in infos if x['ano'] == ano][0]
        g = [x for x in geos if x['ano'] == ano][0]
        nums[str(ano)] = {'secoes_elegiveis': i['secoes_elegiveis'], 'pares_identicos_obs': int(c.loc['pares_identicos', 'observado']),
                          'nulo1_media': round(float(c.loc['pares_identicos', 'nulo1_media']), 1), 'nulo1_dp': round(float(c.loc['pares_identicos', 'nulo1_dp']), 1),
                          'nulo1_razao': round(float(c.loc['pares_identicos', 'nulo1_razao']), 3), 'nulo1_p_excesso': float(c.loc['pares_identicos', 'nulo1_p_excesso']),
                          'nulo1_p_deficit': float(c.loc['pares_identicos', 'nulo1_p_deficit']),
                          'nulo2_media': round(float(c.loc['pares_identicos', 'nulo2_media']), 1), 'nulo2_p_excesso': float(c.loc['pares_identicos', 'nulo2_p_excesso']),
                          'pares_trocados_obs': int(c.loc['pares_trocados', 'observado']), 'pares_trocados_nulo1': round(float(c.loc['pares_trocados', 'nulo1_media']), 1),
                          'frac_obs_mesma_uf_ou_mais': round(g['frac_obs_mesmo_local'] + g['frac_obs_mesmo_municipio'] + g['frac_obs_mesma_uf'], 3),
                          'frac_nulo1_mesma_uf_ou_mais': round(g['frac_nulo1_mesmo_local'] + g['frac_nulo1_mesmo_municipio'] + g['frac_nulo1_mesma_uf'], 3),
                          'frac_estrutural_mesma_uf_ou_mais': round(g['frac_estrutural_mesma_uf_ou_mais'], 3),
                          'phi_A': round(i['phi_A'], 2), 'phi_branco': round(i['phi_branco'], 2), 'phi_nulo': round(i['phi_nulo'], 2)}
    _rec(resumo, 'C7-01', 'feita', nums, files, motivo=f'nulo 1 parametrico ({R_PARAM} rep.), nulo 2 permutacao por componente ({R_PERM} rep.), nulo 3 geografia')
    for ano in ANOS:
        n = nums[str(ano)]
        if n['nulo1_p_excesso'] < .05 or n['nulo1_p_deficit'] < .05:
            sentido = 'acima' if n['nulo1_p_excesso'] < .05 else 'abaixo'
            achados.append({
                'id_sugerido': f'C7-01-{ano}', 'titulo': f'{ano} T2: numero de pares de secoes com vetor identico {sentido} do esperado pelo nulo parametrico',
                'pleito': f'{ano}-t2', 'cargo': 'presidente', 'uf': 'BR', 'escopo': f'{n["secoes_elegiveis"]} secoes elegiveis; {n["pares_identicos_obs"]} pares',
                'tipo': 'calibracao de coincidencias exatas (vetor identico)',
                'efeito': f'observado {n["pares_identicos_obs"]} pares vs nulo 1 {n["nulo1_media"]} ± {n["nulo1_dp"]} (razao {n["nulo1_razao"]}); nulo 2 {n["nulo2_media"]}',
                'efeito_num': n['nulo1_razao'], 'materialidade_min': 0, 'materialidade_max': 0,
                'margem_referencia': 'nao se aplica (contagem de coincidencias; nenhum voto e movido por um par coincidir)',
                'artefato_excluido': 'invariante comp = A+B+branco+nulo conferido (quarentena C7-01); ZZ, comp < 50 e A ou B = 0 excluidos',
                'controles': 'as outras 3 presidenciais com o mesmo nulo (C7-01_calibracao.csv); fracao dos pares na mesma UF vs estrutural',
                'hipoteses': ['modelo parametrico (beta-binomial por predio) sub/superestima a dispersao real entre secoes de tamanho igual',
                              'heterogeneidade de aptos/comp (seccoes de mesmo tamanho concentradas) nao capturada pela fatia local'],
                'status_sugerido': 'PLAUSIVEL-EXPLICAVEL', 'dados_externos': 'nenhum (calibracao interna)',
                'fonte': files[:2], 'prioridade': 3})
    return cal


def roda_c7_01s(resumo, achados, cache):
    """C7-01 (sensibilidade): nulo 1 com phi = 1, para as 4 eleicoes; acrescenta ao resumo de C7-01."""
    rng = np.random.default_rng(SEED + 11)
    obs = pd.read_csv(OUT / 'C7-01_calibracao.csv', sep=';', decimal=',', encoding='utf-8-sig')
    linhas = []
    for ano in ANOS:
        d = carrega_base(ano)
        d = d[d.t2_comp == d.t2_A + d.t2_B + d.t2_branco + d.t2_nulo]
        sims = c7_01_sensibilidade_phi(d, rng)
        o = obs[obs.ano == ano].set_index('medida')
        for med in ['pares_identicos', 'pares_trocados'] + [f'pares_{n}' for n in NIVEIS]:
            sv = sims[med].to_numpy(float)
            ob = float(o.loc[med, 'observado'])
            linhas.append({'ano': ano, 'medida': med, 'observado': ob, 'nulo_phi1_media': float(sv.mean()), 'nulo_phi1_dp': float(sv.std(ddof=1)),
                           'razao': ob / sv.mean() if sv.mean() > 0 else np.nan, **p_empirico(sv, ob), 'r': R_SENS})
        print(f'  C7-01s {ano}', flush=True)
        del d
        gc.collect()
    t = pd.DataFrame(linhas)
    f = csv_out('C7-01_sensibilidade_phi1.csv', t)
    if 'C7-01' in resumo:
        resumo['C7-01']['arquivos'] = list(dict.fromkeys(resumo['C7-01']['arquivos'] + [f]))
        resumo['C7-01']['numeros_chave']['sensibilidade_phi1'] = {
            f'{r.ano}|{r.medida}': {'obs': r.observado, 'nulo': round(r.nulo_phi1_media, 2), 'p_excesso': round(r.p_excesso, 3)}
            for r in t.itertuples() if r.medida in ('pares_identicos', 'pares_mesmo_local')}
    _rec(resumo, 'C7-01s', 'feita', {f'{r.ano}|{r.medida}': round(r.razao, 3) for r in t.itertuples()}, [f],
         motivo='sensibilidade do nulo 1 (phi = 1); complementa C7-01')


def roda_c7_02(resumo, achados, cache):
    _carrega_todas(cache)
    calib = cache.get('calib')
    ibge = carrega_ibge()
    hab = None
    p_hab = R / 'padroes_2t' / 'hab_2026_t2.parquet'
    if p_hab.exists():
        hab = pd.read_parquet(p_hab, columns=KEY + ['opening', 'closing', 'hab_0', 'hab_1', 'hab_2'])
    todos, res, logs = [], [], []
    for ano in ANOS:
        d = cache[ano]
        pares = c7_02_pares(d, ibge)
        pares.insert(0, 'ano', ano)
        r = c7_02_resumo(pares, int(d.elegivel.sum()), calib[calib.ano == ano] if calib is not None else None)
        r['ano'] = ano
        res.append(r)
        if ano in (2022, 2026) and len(pares):
            ch = pd.concat([pares[[f'{c}_1' for c in KEY]].set_axis(KEY, axis=1), pares[[f'{c}_2' for c in KEY]].set_axis(KEY, axis=1)])
            bins = carrega_bins_para(ch, ano)
            pl = c7_02_logs_dos_pares(pares, bins, hab if ano == 2026 else None)
            logs.append(pl)
            del bins
        todos.append(pares)
        print(f'  C7-02 {ano}: {r}', flush=True)
    pares = pd.concat(todos, ignore_index=True)
    logs = pd.concat(logs, ignore_index=True) if logs else pd.DataFrame()
    res = pd.DataFrame(res)
    cols_first = ['ano', 'nivel'] + [f'{c}_1' for c in KEY + ['voting_place']] + [f'{c}_2' for c in KEY + ['voting_place']] + VEC_T2
    pares = pares[cols_first + [c for c in pares.columns if c not in cols_first]]
    files = [csv_out('C7-02_pares_vetor_identico.csv', pares), csv_out('C7-02_resumo_por_eleicao.csv', res),
             csv_out('C7-02_pares_mesmo_local_ou_municipio.csv', pares[pares.nivel.isin(['mesmo_local', 'mesmo_municipio'])]),
             csv_out('C7-02_pares_2022_2026_logs.csv', logs)]
    por_uf = pares.groupby(['ano', 'uf_1']).size().rename('pares_com_secao_na_uf').reset_index().rename(columns={'uf_1': 'uf'})
    files.append(csv_out('C7-02_pares_por_uf.csv', por_uf))
    nums = {str(r['ano']): {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items() if k != 'ano'} for r in res.to_dict('records')}
    if len(logs):
        nums['logs_2022_2026'] = {'pares_comparados': int((logs.status_bins == 'comparado').sum()), 'bins_identicos': int(logs.bins_identicos.sum()),
                                  'bins_L1_min': float(logs.bins_L1.min()), 'bins_L1_mediana': float(logs.bins_L1.median()),
                                  'pares_sem_histograma': int((logs.status_bins != 'comparado').sum())}
    _rec(resumo, 'C7-02', 'feita', nums, files)
    # achado descritivo: pares no mesmo local em 2026 (lista) e leitura contra a calibracao
    n26 = nums['2026']
    n22 = nums['2022']
    ml = pares[(pares.ano == 2026) & (pares.nivel == 'mesmo_local')]
    achados.append({
        'id_sugerido': 'C7-02-2026', 'titulo': '2026 T2: pares de secoes com vetor completo identico (A, B, branco, nulo, comparecimento, aptos)',
        'pleito': '2026-t2', 'cargo': 'presidente', 'uf': 'BR', 'escopo': f'{n26["pares"]} pares / {n26["secoes_em_par"]} secoes de {n26["secoes_elegiveis"]} elegiveis; {len(ml)} pares no mesmo local',
        'tipo': 'vetores identicos entre secoes distintas', 'efeito': f'{n26["pct_secoes_em_par"]:.3f}% das secoes em par (2022: {n22["pct_secoes_em_par"]:.3f}%); '
        f'nulo 1 esperava {n26.get("nulo1_media_pares")} pares (razao {n26.get("nulo1_razao")}, p_excesso {n26.get("nulo1_p_excesso")}); '
        f'fracao na mesma UF ou mais proxima {n26["frac_mesma_uf_ou_mais"]:.3f} (2022: {n22["frac_mesma_uf_ou_mais"]:.3f}); histogramas de log identicos: {nums.get("logs_2022_2026", {}).get("bins_identicos")}',
        'efeito_num': n26.get('nulo1_razao'), 'materialidade_min': 0, 'materialidade_max': int(pares[pares.ano == 2026].t2_comp.sum()) if len(pares) else 0,
        'margem_referencia': 'maximo = soma dos comparecimentos das secoes em par (limite superior formal; coincidencia nao move voto)',
        'artefato_excluido': 'ZZ, comp < 50 e A ou B = 0 excluidos; pares no mesmo local listados com n_logs, contingencia, histograma de 15 min e habilitacao',
        'controles': '2014, 2018 e 2022 com a mesma regra e o mesmo nulo (C7-02_resumo_por_eleicao.csv, C7-01_calibracao.csv)',
        'hipoteses': ['coincidencia ao acaso entre secoes de tamanho parecido (nulo 1 e 2)', 'mais secoes e comparecimento mais concentrado em 2026 elevam as coincidencias'],
        'status_sugerido': 'PLAUSIVEL-EXPLICAVEL' if (n26.get('nulo1_p_excesso') or 1) >= .05 else 'INEXPLICADO',
        'dados_externos': 'nenhum para a contagem; para os pares no mesmo local, hash dos logs (C7-08)', 'fonte': files[:3], 'prioridade': 3})
    cache['pares_t2'] = pares
    return pares


def roda_c7_03(resumo, achados, cache):
    _carrega_todas(cache)
    pares_t2 = cache.get('pares_t2')
    con = duck()
    res, lista, both = [], [], []
    for ano in ANOS:
        if ano == 2026:
            p = REL / 'verificacoes' / 'virada_1t_2t_2026' / 'secoes_t1_t2.parquet'
            d = pd.read_parquet(p)
            d = d[d._merge == 'both'] if '_merge' in d else d
            d = d.rename(columns={'t1_voting_place': 'voting_place'})
            d['voting_place'] = d.voting_place.fillna(-1).astype(int)
            d['vetor_t1'], cols = vetor_t1_2026(d)
            vcols = [c for c in cols if re.match(r't1_v\d+$', c)]
            d['t1_comp'] = d.t1_comparecimento
            validos = d[vcols].fillna(0).sum(axis=1)
            degen = (d[vcols].fillna(0).max(axis=1) == validos) & (validos > 0)
        else:
            d = carrega_t1_bweb(f'{ano}-t1', con)
            degen = (d.max_cand == d.validos) & (d.validos > 0)
        d = d.reset_index(drop=True)
        degen = pd.Series(np.asarray(degen), index=d.index)
        m, n_eleg = c7_03_t1(d, degenerado=degen)
        m.insert(0, 'ano', ano)
        pares_t1, grupos, secs = conta_pares_iguais(hash_vetor(d[(d.uf != 'ZZ') & (d.t1_comp >= COMP_MIN) & ~degen], ['vetor_t1']))
        r = {'ano': ano, 'secoes_elegiveis_t1': n_eleg, 'pares_t1_identicos': int(len(m)), 'secoes_em_par_t1': secs,
             'secoes_t1_degeneradas_excluidas': int(degen.sum())}
        for n in NIVEIS:
            r[f'pares_{n}'] = int((m.nivel == n).sum())
        # T1 e T2 ambos identicos
        t1h = pd.Series(hash_vetor(d, ['vetor_t1']), index=pd.MultiIndex.from_frame(d[KEY]))
        if pares_t2 is not None:
            b = c7_03_t1_e_t2(pares_t2[pares_t2.ano == ano], t1h)
            r['pares_t2_identicos'] = int(len(b))
            r['pares_t1_e_t2_identicos'] = int(b.t1_identico.sum())
            r['pares_t2_sem_vetor_t1'] = int((b.t1_status != 'comparado').sum())
            both.append(b[b.t1_identico])
        res.append(r)
        lista.append(m)
        print(f'  C7-03 {ano}: {r}', flush=True)
        del d
        gc.collect()
    con.close()
    res = pd.DataFrame(res)
    lista = pd.concat(lista, ignore_index=True)
    both = pd.concat(both, ignore_index=True) if both else pd.DataFrame()
    files = [csv_out('C7-03_t1_resumo_por_eleicao.csv', res), csv_out('C7-03_pares_t1_identicos.csv', lista),
             csv_out('C7-03_pares_t1_e_t2_identicos.csv', both)]
    nums = {str(r['ano']): {k: v for k, v in r.items() if k != 'ano'} for r in res.to_dict('records')}
    _rec(resumo, 'C7-03', 'feita', nums, files, motivo='vetor T1 completo (todos os NR_VOTAVEL + branco + nulo + comp + aptos); calibrado so pelo controle entre eleicoes')


def roda_c7_04(resumo, achados, cache):
    _carrega_todas(cache)
    rng = np.random.default_rng(SEED + 4)
    res, listas, fortes, fres = [], [], [], []
    for a0, a1 in ((2014, 2018), (2018, 2022), (2022, 2026)):
        m, o = c7_04_entre_pleitos(cache[a0], cache[a1], a0, a1)
        d1 = cache[a1]
        modelo, phi = modelo_parametrico(d1[d1.elegivel].reset_index(drop=True))
        sims, n_ok = c7_04_esperado_parametrico(m, modelo, phi, rng, r=R_PARAM)
        for med in sims.columns:
            s = sims[med].to_numpy(float)
            o[f'{med}_esperado'] = float(s.mean())
            o[f'{med}_esperado_dp'] = float(s.std(ddof=1))
            o[f'{med}_razao'] = o[med] / s.mean() if s.mean() > 0 else np.nan
            o[f'{med}_p_excesso'] = p_empirico(s, o[med])['p_excesso']
        o['secoes_no_modelo'] = n_ok
        sims_p, phi_p = c7_04_esperado_persistencia(m, modelo, phi, rng, r=R_PARAM)
        for med in sims_p.columns:
            s = sims_p[med].to_numpy(float)
            o[f'{med}_persist_esperado'] = float(s.mean())
            o[f'{med}_persist_dp'] = float(s.std(ddof=1))
            o[f'{med}_persist_razao'] = o[med] / s.mean() if s.mean() > 0 else np.nan
            o[f'{med}_persist_p_excesso'] = p_empirico(s, o[med])['p_excesso']
            o[f'{med}_persist_p_deficit'] = p_empirico(s, o[med])['p_deficit']
        o['phi_A_persistencia'] = phi_p
        res.append(o)
        sel = m[m.votos_identicos | m.ab_trocados | m.ab_identicos].copy()
        sel.insert(0, 'de', a0)
        sel.insert(1, 'para', a1)
        listas.append(sel)
        f, fr = c7_04_espelho_forte(cache[a0], cache[a1], a0, a1)
        fortes.append(f)
        fres.append(fr)
        print(f'  C7-04 {a0}->{a1}: {o}', flush=True)
    # dentro do mesmo ano: T1 = T2 (votos identicos) nas 4 eleicoes
    intra = []
    for ano in ANOS:
        d = cache[ano]
        if ano in (2014, 2018, 2022, 2026):
            p = R / 'padroes_2t' / f'base_{ano}.parquet'
            t1 = pd.read_parquet(p, columns=KEY + ['t1_comp', 't1_A', 't1_B', 't1_branco', 't1_nulo'])
            e = d[d.elegivel].merge(t1, on=KEY)
            ig = (e.t1_comp == e.t2_comp) & (e.t1_A == e.t2_A) & (e.t1_B == e.t2_B) & (e.t1_branco == e.t2_branco) & (e.t1_nulo == e.t2_nulo)
            ab = (e.t1_A == e.t2_A) & (e.t1_B == e.t2_B)
            intra.append({'ano': ano, 'secoes': int(len(e)), 'comp_igual_t1_t2': int((e.t1_comp == e.t2_comp).sum()),
                          'votos_identicos_t1_t2': int(ig.sum()), 'ab_identicos_t1_t2': int(ab.sum())})
            del t1, e
    res = pd.DataFrame(res)
    fortes = pd.concat(fortes, ignore_index=True)
    fortes = contexto_espelho(fortes, lambda ano: pd.read_parquet(R / 'padroes_2t' / f'base_{ano}.parquet',
                                                                 columns=KEY + ['voting_place', 't1_A', 't1_B', 't2_A', 't2_B']))
    files = [csv_out('C7-04_entre_pleitos_resumo.csv', res), csv_out('C7-04_secoes_iguais_ou_trocadas_entre_pleitos.csv', pd.concat(listas, ignore_index=True)),
             csv_out('C7-04_t1_igual_t2_mesmo_ano.csv', pd.DataFrame(intra)), csv_out('C7-04_espelho_forte_secoes.csv', fortes),
             csv_out('C7-04_espelho_forte_resumo.csv', pd.DataFrame(fres)),
             csv_out('C7-04_espelho_forte_por_uf.csv', fortes.groupby(['de', 'para', 'uf']).size().rename('espelho_forte').reset_index())]
    nums = {f'{r["de"]}->{r["para"]}': {k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items() if k not in ('de', 'para')} for r in res.to_dict('records')}
    nums['t1_igual_t2_mesmo_ano'] = {str(r['ano']): {k: v for k, v in r.items() if k != 'ano'} for r in intra}
    nums['espelho_forte_2022_2026'] = int(fres[-1]['espelho_forte'])
    _rec(resumo, 'C7-04', 'feita', nums, files)
    r26 = res[res.para == 2026].iloc[0]
    r22 = res[res.para == 2022].iloc[0]
    r18 = res[res.para == 2018].iloc[0]
    achados.append({
        'id_sugerido': 'C7-04-2022-2026', 'titulo': 'Mesma secao 2022 x 2026: (A, B) exatamente iguais nos dois pleitos acima do nulo local',
        'pleito': '2026-t2', 'cargo': 'presidente', 'uf': 'BR', 'escopo': f'{int(r26.secoes_pareadas)} secoes pareadas (aptos +-25%)',
        'tipo': 'coincidencia entre pleitos (mesma secao)',
        'efeito': f'(A,B) iguais {int(r26.ab_identicos)} vs nulo local {r26.ab_identicos_esperado:.1f} (razao {r26.ab_identicos_razao:.2f}) e vs nulo de '
                  f'persistencia {r26.ab_identicos_persist_esperado:.1f} (razao {r26.ab_identicos_persist_razao:.2f}, p_excesso '
                  f'{r26.ab_identicos_persist_p_excesso:.3f}); vetor inteiro igual {int(r26.votos_identicos)} vs {r26.votos_identicos_esperado:.1f} / '
                  f'{r26.votos_identicos_persist_esperado:.1f}; A/B trocados {int(r26.ab_trocados)} vs {r26.ab_trocados_esperado:.1f} / '
                  f'{r26.ab_trocados_persist_esperado:.1f}. Controles: 2018->2022 (A,B) iguais {int(r22.ab_identicos)} vs {r22.ab_identicos_esperado:.1f} / '
                  f'{r22.ab_identicos_persist_esperado:.1f}; 2014->2018 {int(r18.ab_identicos)} vs {r18.ab_identicos_esperado:.1f} / '
                  f'{r18.ab_identicos_persist_esperado:.1f}',
        'efeito_num': float(r26.ab_identicos_persist_razao), 'materialidade_min': 0, 'materialidade_max': 0,
        'margem_referencia': 'nao se aplica (coincidencia de contagens; nenhum voto e movido por repetir o resultado)',
        'artefato_excluido': 'mesma chave de secao com aptos +-25% (como padroes_aberta.espelho); ZZ, comp < 50, A ou B = 0 excluidos',
        'controles': '2014->2018 e 2018->2022 com os mesmos dois nulos (C7-04_entre_pleitos_resumo.csv)',
        'hipoteses': ['persistencia secao a secao da fatia (correlacao 0,855 / 0,951 / 0,973) que o nulo local nao preserva',
                      'mesmo eleitorado e comparecimento estavel entre 2022 e 2026'],
        'status_sugerido': 'PLAUSIVEL-EXPLICAVEL' if r26.ab_identicos_persist_p_excesso >= .05 else 'INEXPLICADO',
        'dados_externos': 'nenhum', 'fonte': files[:2], 'prioridade': 3})


def roda_c7_05(resumo, achados, cache):
    _carrega_todas(cache)
    rng = np.random.default_rng(SEED + 5)
    res, ufs, fxs, listas = [], [], [], []
    for ano in ANOS:
        o, uf, fx, lista = c7_05_comparecimento(cache[ano], rng)
        o['ano'] = ano
        uf.insert(0, 'ano', ano)
        fx.insert(0, 'ano', ano)
        lista.insert(0, 'ano', ano)
        res.append(o)
        ufs.append(uf)
        fxs.append(fx)
        listas.append(lista)
        print(f'  C7-05 {ano}: {o}', flush=True)
    res = pd.DataFrame(res)
    files = [csv_out('C7-05_comparecimento_consecutivo_resumo.csv', res), csv_out('C7-05_por_uf.csv', pd.concat(ufs, ignore_index=True)),
             csv_out('C7-05_por_faixa_aptos.csv', pd.concat(fxs, ignore_index=True)), csv_out('C7-05_pares_consecutivos_iguais.csv', pd.concat(listas, ignore_index=True))]
    nums = {str(r['ano']): {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items() if k != 'ano'} for r in res.to_dict('records')}
    _rec(resumo, 'C7-05', 'feita', nums, files, motivo='nulo A: comp permutado dentro da zona; nulo B: dentro de (zona, aptos)')
    for r in res.to_dict('records'):
        if r['nuloB_p_excesso'] < .05:
            achados.append({
                'id_sugerido': f'C7-05-{r["ano"]}', 'titulo': f'{r["ano"]} T2: comparecimento identico em secoes consecutivas acima do nulo condicionado a aptos',
                'pleito': f'{r["ano"]}-t2', 'cargo': 'presidente', 'uf': 'BR', 'escopo': f'{r["secoes"]} secoes; {r["pares_consecutivos_iguais"]} pares',
                'tipo': 'comparecimento igual em sequencia', 'efeito': f'observado {r["pares_consecutivos_iguais"]} vs nulo B {r["nuloB_zona_aptos_pares_media"]:.1f} ± {r["nuloB_zona_aptos_pares_dp"]:.1f} '
                f'(razao {r["nuloB_razao"]:.3f}); nulo A {r["nuloA_zona_pares_media"]:.1f} (razao {r["nuloA_razao"]:.3f})', 'efeito_num': float(r['nuloB_razao']),
                'materialidade_min': 0, 'materialidade_max': 0, 'margem_referencia': 'nao se aplica',
                'artefato_excluido': 'ZZ e comp < 50 excluidos; ordem numerica da secao dentro da zona',
                'controles': 'as outras 3 presidenciais com o mesmo nulo', 'hipoteses': ['secoes vizinhas do mesmo predio tem taxa de comparecimento parecida (correlacao espacial que o nulo B nao preserva)'],
                'status_sugerido': 'PLAUSIVEL-EXPLICAVEL', 'dados_externos': 'nenhum', 'fonte': files[:1], 'prioridade': 3})


def roda_c7_06(resumo, achados, cache):
    _carrega_todas(cache)
    rng = np.random.default_rng(SEED + 6)
    res, tabs, listas = [], [], []
    for ano in ANOS:
        o, tab, lista = c7_06_sequencias(cache[ano], rng)
        o['ano'] = ano
        tab.insert(0, 'ano', ano)
        lista.insert(0, 'ano', ano)
        res.append(o)
        tabs.append(tab)
        listas.append(lista)
        print(f'  C7-06 {ano}: {o}', flush=True)
    tab = pd.concat(tabs, ignore_index=True)
    files = [csv_out('C7-06_sequencias_resumo.csv', tab), csv_out('C7-06_contagens.csv', pd.DataFrame(res)),
             csv_out('C7-06_predios_sinalizados.csv', pd.concat(listas, ignore_index=True))]
    nums = {str(r['ano']): {k: v for k, v in r.items() if k != 'ano'} for r in res}
    nums['razoes'] = {f'{r.ano}|{r.medida}': {'obs': r.observado, 'nulo': round(r.nulo_media, 2), 'razao': round(r.razao, 3) if pd.notna(r.razao) else None,
                                              'p_excesso': round(r.p_excesso, 4)} for r in tab.itertuples()}
    _rec(resumo, 'C7-06', 'feita', nums, files)


def roda_c7_07(resumo, achados, cache):
    p = R / 'rdv_gatilho' / '2026-t2'
    if not p.exists():
        _rec(resumo, 'C7-07', 'nao_feita', {}, [], motivo='research/rdv_gatilho/2026-t2 ausente')
        return
    rng = np.random.default_rng(SEED + 7)
    rdv = carrega_rdv_2026()
    m, o = c7_07_quase_duplicatas(rdv, rng)
    del rdv
    gc.collect()
    bins = carrega_bins_para(pd.concat([m[[f'{c}_1' for c in KEY]].set_axis(KEY, axis=1), m[[f'{c}_2' for c in KEY]].set_axis(KEY, axis=1)]), 2026) if len(m) else None
    ml = c7_02_logs_dos_pares(m.assign(voting_place_1=-1, voting_place_2=-1), bins) if len(m) else m
    o['pares_bins_identicos'] = int(ml.bins_identicos.sum()) if len(ml) else 0
    o['pares_nulos_e_bins_identicos'] = int((ml.bins_identicos & ml.nulos_identicos).sum()) if len(ml) else 0
    files = [csv_out('C7-07_pares_votos_identicos_rdv.csv', ml), csv_out('C7-07_resumo.csv', pd.DataFrame([o]))]
    _rec(resumo, 'C7-07', 'feita', o, files, motivo='so 2026 T2 (unico pleito com RDV por secao em disco); impressao digital = contagem por codigo nulo digitado')


def roda_c7_08(resumo, achados, cache):
    files = []
    nums = {}
    cam = None
    p_uv = REL / 'verificacoes' / 'ultimo_voto_2026t2' / 'ultimo_voto_por_secao.csv'
    if p_uv.exists():
        cam = pd.read_csv(p_uv, sep=';', decimal=',', encoding='utf-8-sig', usecols=KEY + ['path', 'votos_log', 'erro_log'])
        for c in ('municipality', 'zone', 'section'):
            cam[c] = pd.to_numeric(cam[c], errors='coerce')
        cam = cam.dropna(subset=['municipality', 'zone', 'section'])
        for c in ('municipality', 'zone', 'section'):
            cam[c] = cam[c].astype(int)
    for ano in (2022, 2026):
        p = R / 'janelas_horario' / f'bins_{ano}.parquet'
        if not p.exists():
            continue
        b = pd.read_parquet(p, columns=KEY + ['n_logs', 'contingencia'])
        lst = c7_08_lista_fase_a(b, ano, cam if ano == 2026 else None)
        files.append(csv_out(f'C7-08_fase_A_lista_{ano}.csv', lst))
        nums[str(ano)] = lst.groupby(['classe', 'n_logs']).size().rename('secoes').reset_index().to_dict('records')
        del b
    _rec(resumo, 'C7-08', 'nao_feita', nums, files, motivo='depende da passada pesada de logs. A passada deve, por pacote (comecando pelas secoes listadas em '
         'C7-08_fase_A_lista_<ano>.csv, depois todas): listar cada logd.dat com profundidade, nome do membro, bytes, primeira linha, 3o campo (serie em 2026), '
         'secoes declaradas ("Secao Eleitoral: NNNN"), nº de "O voto do eleitor foi computado" no dia do pleito e no 1o turno, e SHA-256 do logd.dat apos dedup '
         'por primeira linha; depois cruzar SHA-256 entre pacotes (mesmo log em mais de uma secao), pacotes com log de OUTRA secao (e se a dona tem o mesmo log) '
         'e explicar as secoes com 2 logs distintos sem marca de contingencia.')


def _bweb_files(pleito, cargo):
    return [p for p in sorted((R / 'bu' / pleito).glob(f'*_{cargo}.parquet'))]


def secoes_bweb_pleito(con, pleito, cargo):
    """Tabela leve por secao (sem vetor nem datas) de um pleito inteiro: serie efetivada, nº de series, tipo, aptos, comp."""
    out = []
    for path in _bweb_files(pleito, cargo):
        uf = path.name.split('_')[0]
        q = f"""select '{uf}' uf, try_cast(CD_MUNICIPIO as integer) municipality, try_cast(NR_ZONA as integer) zone,
 try_cast(NR_SECAO as integer) section, max(try_cast(NR_LOCAL_VOTACAO as integer)) voting_place,
 max(trim(cast(NR_URNA_EFETIVADA as varchar))) urna, count(distinct NR_URNA_EFETIVADA) n_urna, max(DS_TIPO_URNA) tipo_urna,
 max(try_cast(QT_APTOS as bigint)) aptos, max(try_cast(QT_COMPARECIMENTO as bigint)) comp
 from read_parquet('{path.as_posix()}') group by 1,2,3,4"""
        out.append(con.execute(q).df())
    d = pd.concat(out, ignore_index=True)
    d['pleito'], d['cargo'] = pleito, cargo
    return d


def detalhe_bweb_secoes(con, pleito, cargo, chaves):
    """Vetor (NR_VOTAVEL:QT_VOTOS), abertura, encerramento e carga so das secoes listadas (por UF, join numa tabela temporaria)."""
    out = []
    for path in _bweb_files(pleito, cargo):
        uf = path.name.split('_')[0]
        k = chaves[chaves.uf == uf][['municipality', 'zone', 'section']].drop_duplicates()
        if k.empty:
            continue
        names = pq_names(path)
        ab = 'b.DT_ABERTURA' if 'DT_ABERTURA' in names else 'NULL'
        en = 'b.DT_ENCERRAMENTO' if 'DT_ENCERRAMENTO' in names else 'NULL'
        carga = 'b.DT_CARGA_URNA_EFETIVADA' if 'DT_CARGA_URNA_EFETIVADA' in names else 'b.DT_CARGA' if 'DT_CARGA' in names else 'NULL'
        con.register('k_det', k)
        q = f"""select '{uf}' uf, try_cast(b.CD_MUNICIPIO as integer) municipality, try_cast(b.NR_ZONA as integer) zone,
 try_cast(b.NR_SECAO as integer) section, max({ab}) abertura, max({en}) encerramento, max({carga}) carga,
 string_agg(b.NR_VOTAVEL || ':' || b.QT_VOTOS, '|' order by try_cast(b.NR_VOTAVEL as integer)) vetor
 from read_parquet('{path.as_posix()}') b join k_det k on try_cast(b.CD_MUNICIPIO as integer) = k.municipality
 and try_cast(b.NR_ZONA as integer) = k.zone and try_cast(b.NR_SECAO as integer) = k.section group by 1,2,3,4"""
        out.append(con.execute(q).df())
        con.unregister('k_det')
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=KEY + ['abertura', 'encerramento', 'carga', 'vetor'])


def series_entre_ufs(sec):
    """Series que aparecem em mais de uma UF no mesmo pleito (o agrupamento principal e por UF)."""
    s = sec.dropna(subset=['urna'])
    s = s[~serie_nula(s.urna)]
    g = s.groupby(['pleito', 'urna']).uf.nunique()
    return g[g > 1].rename('ufs').reset_index()


def carrega_ceft_pleito(con, pleito):
    out = []
    for uf in UFS11:
        c = carrega_ceft(pleito, uf, con)
        if c is not None:
            out.append(c)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def roda_c7_09(resumo, achados, cache):
    con = duck()
    # relogio_por_secao: serie por secao em 2022-t1/t2 e 2026-t1 (11 UFs); 2026-t2 sem serie. So as linhas com serie repetida.
    p_rel = REL / 'verificacoes' / 'relogio_por_secao.parquet'
    rel_rep = pd.DataFrame()
    rel_res = pd.DataFrame()
    if p_rel.exists():
        pr = p_rel.as_posix()
        rel_res = con.execute(f"""select eleicao pleito, count(*) secoes, count(urna) secoes_com_serie, count(distinct urna) series_distintas
 from read_parquet('{pr}') group by 1 order by 1""").df()
        rel_rep = con.execute(f"""with r as (select eleicao, uf, municipio, zona, secao, local, urna, abertura, encerramento, recebido_tse,
 count(*) over (partition by eleicao, uf, urna) n from read_parquet('{pr}') where urna is not null)
 select * exclude (n) from r where n > 1 order by eleicao, uf, urna, municipio, zona, secao""").df()
        rel_rep = rel_rep.rename(columns={'eleicao': 'pleito', 'municipio': 'municipality', 'zona': 'zone', 'secao': 'section'})
        for c in ('municipality', 'zone', 'section'):
            rel_rep[c] = rel_rep[c].astype(int)
    reps, res_series, res_pleitos, rel_bweb, cross, ceft_res, ceft_reps = [], [], [], [], [], [], []
    for pleito, cargo in PLEITOS_BWEB.items():
        if not (R / 'bu' / pleito).exists():
            continue
        sec = secoes_bweb_pleito(con, pleito, cargo)
        rep, res_serie = c7_09_series_repetidas(sec)
        cross.append(series_entre_ufs(sec))
        res_pleitos.append(c7_09_resumo_pleito(sec, rep).assign(cargo=cargo))
        if len(rel_rep):
            k = rel_rep[rel_rep.pleito == pleito][['pleito'] + KEY]
            if len(k):
                rel_bweb.append(k.merge(sec[['pleito'] + KEY + ['tipo_urna', 'comp', 'aptos', 'urna']].rename(columns={'urna': 'urna_bweb'}),
                                        on=['pleito'] + KEY, how='left'))
        del sec
        if len(rep):
            det = detalhe_bweb_secoes(con, pleito, cargo, rep[KEY])
            rep = rep.merge(det, on=KEY, how='left')
            g = rep.groupby(['pleito', 'uf', 'urna'])
            res_serie = res_serie.drop(columns=['vetores_distintos', 'aberturas', 'encerramentos', 'vetores_identicos'], errors='ignore').merge(
                pd.DataFrame({'vetores_distintos': g.vetor.nunique(),
                              'aberturas': g.abertura.agg(lambda x: '|'.join(sorted(set(map(str, x.dropna()))))),
                              'encerramentos': g.encerramento.agg(lambda x: '|'.join(sorted(set(map(str, x.dropna())))))}).reset_index(),
                on=['pleito', 'uf', 'urna'], how='left')
            res_serie['vetores_identicos'] = res_serie.vetores_distintos < res_serie.secoes
        # CEFT do mesmo pleito (11 UFs)
        tem_ceft = (R / 'ceft' / pleito).exists()
        ceft = carrega_ceft_pleito(con, pleito) if tem_ceft else pd.DataFrame()
        if len(ceft):
            ceft_res.append(c7_09_ceft_resumo(ceft))
            ceft_reps.append(ceft_series_repetidas(ceft).drop(columns='layout'))
            if len(rep):
                rep = rep.merge(ceft[['pleito'] + KEY + ['esperada', 'efetivada', 'origem', 'divergencia']].drop_duplicates(['pleito'] + KEY),
                                on=['pleito'] + KEY, how='left')
        if len(rep):
            if 'efetivada' not in rep:
                rep['efetivada'] = np.nan
            rep['ceft'] = np.where(rep.uf.isin(UFS11) & tem_ceft,
                                   np.where(rep.efetivada.notna(), 'secao no CEFT', 'secao ausente do CEFT'), f'{NOT_COMP}: UF/pleito sem CEFT no HD')
        reps.append(rep)
        res_series.append(res_serie)
        print(f'  C7-09 {pleito} {cargo}: {int(res_pleitos[-1].secoes.iloc[0])} secoes, {len(res_serie)} series repetidas, CEFT {len(ceft)}', flush=True)
        del ceft
        gc.collect()
    con.close()
    rep = pd.concat([r for r in reps if len(r)], ignore_index=True) if any(len(r) for r in reps) else pd.DataFrame()
    res_serie = pd.concat([r for r in res_series if len(r)], ignore_index=True) if any(len(r) for r in res_series) else pd.DataFrame()
    res_pleito = pd.concat(res_pleitos, ignore_index=True)
    cross = pd.concat(cross, ignore_index=True)
    ceft_res = pd.concat(ceft_res, ignore_index=True) if ceft_res else pd.DataFrame()
    ceft_rep = pd.concat(ceft_reps, ignore_index=True) if ceft_reps else pd.DataFrame()
    if len(rel_rep):
        if rel_bweb:
            rel_rep = rel_rep.merge(pd.concat(rel_bweb, ignore_index=True), on=['pleito'] + KEY, how='left')
        else:
            rel_rep['tipo_urna'] = np.nan
        rel_rep['status_tipo'] = np.where(rel_rep.tipo_urna.notna(), 'tipo conferido no BWEB',
                                          f'{NOT_COMP}: sem BWEB do mesmo pleito/cargo para a secao')
    files = [csv_out('C7-09_series_repetidas_secoes.csv', rep), csv_out('C7-09_series_repetidas_resumo.csv', res_serie),
             csv_out('C7-09_resumo_por_pleito.csv', res_pleito), csv_out('C7-09_relogio_series_repetidas.csv', rel_rep),
             csv_out('C7-09_relogio_resumo.csv', rel_res), csv_out('C7-09_series_em_mais_de_uma_uf.csv', cross),
             csv_out('C7-09_ceft_por_pleito_uf.csv', ceft_res), csv_out('C7-09_ceft_series_efetivadas_repetidas.csv', ceft_rep)]
    cp = ceft_res.groupby('pleito')[['linhas', 'efetivada_diferente_da_esperada']].sum() if len(ceft_res) else pd.DataFrame()
    nums = {'bweb': {f'{r["pleito"]} {r["cargo"]}': {k: v for k, v in r.items() if k not in ('pleito', 'cargo')} for r in res_pleito.to_dict('records')},
            'series_repetidas_total': int(len(res_serie)), 'secoes_em_serie_repetida': int(len(rep)),
            'series_repetidas_vetores_identicos': int(res_serie.vetores_identicos.sum()) if len(res_serie) else 0,
            'tipos_urna_nas_repetidas': rep.tipo_urna.astype(str).value_counts().to_dict() if len(rep) else {},
            'series_em_mais_de_uma_uf': int(len(cross)),
            'relogio_series_repetidas': rel_rep.groupby('pleito').urna.nunique().to_dict() if len(rel_rep) else {},
            'relogio_tipos_urna': rel_rep.tipo_urna.astype(str).value_counts(dropna=False).to_dict() if len(rel_rep) else {},
            'ceft_pleitos': sorted(ceft_res.pleito.unique().tolist()) if len(ceft_res) else [],
            'ceft_pct_troca_por_pleito': (100 * cp.efetivada_diferente_da_esperada / cp.linhas).round(2).to_dict() if len(cp) else {},
            'ceft_series_efetivadas_repetidas': int(ceft_rep.groupby(['pleito', 'uf', 'efetivada']).ngroups) if len(ceft_rep) else 0,
            '2026-t2': f'{NOT_COMP}: sem serie por secao em tabela (sem BWEB, sem CEFT; relogio_por_secao nao cobre 2026-t2)'}
    _rec(resumo, 'C7-09', 'feita', nums, files, motivo='BWEB 2012-2026-t1 (presidente 27 UFs+ZZ, prefeito/governador 10-11 UFs); relogio 11 UFs; '
         'CEFT 11 UFs; 2026-t2 NOT_COMPARABLE')
    cache['c7_09'] = {'rep': rep, 'res_serie': res_serie, 'rel_rep': rel_rep, 'cross': cross, 'ceft_res': ceft_res, 'files': files, 'nums': nums}
    tipo = rep.tipo_urna.astype(str).str.upper() if len(rep) else pd.Series(dtype=str)
    nao_apurada = rep[~tipo.str.startswith('APURADA')] if len(rep) else pd.DataFrame()
    achados.append({
        'id_sugerido': 'C7-09-series', 'titulo': 'Mesma serie de urna efetivada em mais de uma secao (BWEB 2012-2026-t1, relogio 2022/2026-t1)',
        'pleito': 'varios', 'cargo': 'presidente/prefeito/governador', 'uf': 'BR',
        'escopo': f'{len(res_serie)} series repetidas em {len(rep)} secoes (BWEB); relogio: {nums["relogio_series_repetidas"]}',
        'tipo': 'duplicidade fisica (serie)',
        'efeito': f'tipos de urna nas secoes com serie repetida: {nums["tipos_urna_nas_repetidas"]}; secoes com tipo diferente de APURADA: '
                  f'{len(nao_apurada)}; series com vetores identicos entre secoes: {nums["series_repetidas_vetores_identicos"]}',
        'efeito_num': float(len(rep)), 'materialidade_min': 0,
        'materialidade_max': int(pd.to_numeric(rep.comp, errors='coerce').fillna(0).sum()) if len(rep) else 0,
        'margem_referencia': 'local (secoes individuais)',
        'artefato_excluido': 'serie nula/vazia excluida; tipo de urna e vetor conferidos no BWEB; CEFT (11 UFs) e relogio cruzados',
        'controles': 'todos os pleitos 2012-2026-t1 lado a lado (C7-09_resumo_por_pleito.csv)',
        'hipoteses': ['apuracao em junta (DS_TIPO_URNA APURADA)', 'urna de contingencia que serviu duas secoes', 'RED'],
        'status_sugerido': 'EXPLICADO' if len(nao_apurada) == 0 else 'PLAUSIVEL-EXPLICAVEL',
        'dados_externos': 'lista oficial do TSE de urnas substituidas/apuradas em junta; CEFT das 16 UFs restantes e de 2026-t2',
        'fonte': files[:4], 'prioridade': 2})
    return nums


def roda_c7_11(resumo, achados, cache):
    fatos = pd.DataFrame(FATOS_C7_11)
    ctx = []
    p_uv = REL / 'verificacoes' / 'ultimo_voto_2026t2' / 'ultimo_voto_por_secao.csv'
    uv = None
    if p_uv.exists():
        uv = pd.read_csv(p_uv, sep=';', decimal=',', encoding='utf-8-sig', usecols=KEY + ['votos_log', 'erro_log', 'path', 'primeiro_voto', 'ultimo_voto', 'encerramento'])
        for c in ('municipality', 'zone', 'section'):
            uv[c] = pd.to_numeric(uv[c], errors='coerce')
    b26 = cache.get(2026)
    if b26 is None:
        b26 = carrega_base(2026)
        cache[2026] = b26
    bins = pd.read_parquet(R / 'janelas_horario' / 'bins_2026.parquet', columns=KEY + ['n_logs', 'contingencia'])
    alvo = [(r['uf'], r['municipality'], r['zone'], r['section']) for r in FATOS_C7_11] + [('ES', 57932, 9, 112)]
    for uf, mun, zona, sec in alvo:
        row = {'uf': uf, 'municipality': mun, 'zone': zona, 'section': sec}
        b = b26[(b26.uf == uf) & (b26.municipality == mun) & (b26.zone == zona) & (b26.section == sec)]
        if len(b):
            row.update({c: int(b[c].iloc[0]) for c in VEC_T2})
            row['voting_place'] = int(b.voting_place.iloc[0])
        bb = bins[(bins.uf == uf) & (bins.municipality == mun) & (bins.zone == zona) & (bins.section == sec)]
        if len(bb):
            row['n_logs_bins'], row['contingencia_bins'] = int(bb.n_logs.iloc[0]), bool(bb.contingencia.iloc[0])
        if uv is not None:
            u = uv[(uv.uf == uf) & (uv.municipality == mun) & (uv.zone == zona) & (uv.section == sec)]
            if len(u):
                row.update({f'uv_{c}': u[c].iloc[0] for c in ('votos_log', 'erro_log', 'primeiro_voto', 'ultimo_voto', 'encerramento', 'path')})
        row['log_igual_bu'] = (row.get('uv_votos_log') == row.get('t2_comp')) if 'uv_votos_log' in row and 't2_comp' in row else None
        ctx.append(row)
    ctx = pd.DataFrame(ctx)
    # vizinhas do mesmo predio das 3 secoes do dossie
    viz = []
    for r in FATOS_C7_11:
        b = b26[(b26.uf == r['uf']) & (b26.municipality == r['municipality']) & (b26.zone == r['zone']) & (b26.section == r['section'])]
        if len(b):
            vp = int(b.voting_place.iloc[0])
            v = b26[(b26.uf == r['uf']) & (b26.municipality == r['municipality']) & (b26.voting_place == vp)][KEY + ['voting_place'] + VEC_T2].copy()
            v['dossie'] = f'{r["uf"]} {r["municipality"]}/{r["zone"]}/{r["section"]}'
            v['fatia_A_pct'] = 100 * v.t2_A / (v.t2_A + v.t2_B)
            viz.append(v)
    viz = pd.concat(viz, ignore_index=True) if viz else pd.DataFrame()
    files = [csv_out('C7-11_dossie_fatos.csv', fatos), csv_out('C7-11_secoes_contexto.csv', ctx), csv_out('C7-11_vizinhas_mesmo_predio.csv', viz)]
    nums = {'secoes_no_dossie': 3, 'status': {r['status']: int(sum(1 for x in FATOS_C7_11 if x['status'] == r['status'])) for r in FATOS_C7_11},
            'es_57932_9_85': 'log 612 (leitor antigo) -> 308 = BU apos section_hint; log de outra secao (112) embalado por urna de contingencia que serviu 2 secoes',
            'es_57932_9_112_log_igual_bu': bool(ctx[(ctx.section == 112)].log_igual_bu.iloc[0]) if len(ctx[ctx.section == 112]) else None,
            'ba_35653_173_235_faltam': 13, 'ma_8893_47_609_faltam': 36}
    _rec(resumo, 'C7-11', 'feita', nums, files, motivo='fatos apurados na sessao de 04-05/11 (nenhum pacote relido aqui); cruzado com C2-01')
    achados.append({
        'id_sugerido': 'C7-11-ES-57932-9-85', 'titulo': 'ES 57932/9/85 (2026 T2): log com 612 votos vs 308 no BU era artefato do leitor (log de outra secao no pacote)',
        'pleito': '2026-t2', 'cargo': 'presidente', 'uf': 'ES', 'escopo': '1 secao (e a secao 112 do mesmo pacote de contingencia)', 'tipo': 'duplicidade de log (log de outra secao embalado)',
        'efeito': 'leitor antigo somava 308 + 304 = 612; com section_hint o log da secao = 308 = BU; secao 112: 304 = BU', 'efeito_num': 0.0,
        'materialidade_min': 0, 'materialidade_max': 0, 'margem_referencia': 'local', 'artefato_excluido': 'pacote aberto membro a membro (C2-01_logs_por_pacote.csv); RDV = BU',
        'controles': 'secao 112 do mesmo pacote; vizinhas do predio (C7-11_vizinhas_mesmo_predio.csv)', 'hipoteses': ['urna de contingencia que recuperou 2 secoes exporta o log das duas'],
        'status_sugerido': 'ARTEFATO', 'dados_externos': 'nenhum', 'fonte': files, 'prioridade': 2})
    achados.append({
        'id_sugerido': 'C7-11-urna-intermediaria', 'titulo': 'BA 35653/173/235 e MA 8893/47/609 (2026 T2): BU > log porque o pacote nao traz o log de uma urna intermediaria',
        'pleito': '2026-t2', 'cargo': 'presidente', 'uf': 'BA/MA', 'escopo': '2 secoes', 'tipo': 'reconciliacao log x BU (log ausente de urna intermediaria)',
        'efeito': 'faltam 13 (BA) e 36 (MA) votos no log; BU e RDV coincidem', 'efeito_num': 49.0, 'materialidade_min': 49, 'materialidade_max': 49,
        'margem_referencia': 'local (49 votos sem log; margem nacional de milhoes)', 'artefato_excluido': 'pacote aberto membro a membro; logs aninhados lidos; RDV = BU',
        'controles': 'demais 499.169 secoes com log = BU', 'hipoteses': ['troca de urna em que o log da urna intermediaria nao foi embalado no pacote publicado'],
        'status_sugerido': 'NAO_TESTAVEL', 'dados_externos': 'log da urna intermediaria (so o TSE pode fornecer) e ata da secao', 'fonte': files, 'prioridade': 2})


def roda_c7_13(resumo, achados, cache):
    con = duck()
    res, casos = [], []
    for pleito, cargo in PLEITOS_BWEB.items():
        base = R / 'bu' / pleito
        if not base.exists():
            continue
        for path in sorted(base.glob(f'*_{cargo}.parquet')):
            r, c = dup_bweb_uf(con, path, path.name.split('_')[0], pleito, cargo)
            res.append(r)
            if len(c):
                casos.append(c)
        print(f'  C7-13 BWEB {pleito}', flush=True)
    res = pd.concat(res, ignore_index=True)
    casos = pd.concat(casos, ignore_index=True) if casos else pd.DataFrame()
    stems = pd.concat([c7_13_stems(con, p) for p in PLEITOS_URNA], ignore_index=True)
    sr, sr_dup = c7_13_sistema_resultados(con)
    con.close()
    files = [csv_out('C7-13_bweb_duplicatas_por_pleito_uf.csv', res), csv_out('C7-13_bweb_duplicatas_casos.csv', casos),
             csv_out('C7-13_bu_urna_stems_por_pleito_uf.csv', stems),
             csv_out('C7-13_sistema_resultados_2026t2.csv', sr if sr is not None else pd.DataFrame()),
             csv_out('C7-13_sistema_resultados_2026t2_repetidos.csv', sr_dup if sr_dup is not None else pd.DataFrame())]
    por_pleito = res.groupby(['pleito', 'cargo'])[['linhas', 'chaves', 'chaves_duplicadas', 'linhas_excedentes', 'chaves_duplicadas_com_votos_diferentes']].sum()
    nums = {'bweb_por_pleito': {f'{k[0]} {k[1]}': {c: int(v) for c, v in r.items()} for k, r in por_pleito.iterrows()},
            'bweb_chaves_duplicadas_total': int(res.chaves_duplicadas.sum()), 'bweb_duplicadas_com_votos_diferentes_total': int(res.chaves_duplicadas_com_votos_diferentes.sum()),
            'bu_urna_stems_repetidos_total': int(stems.stems_repetidos.sum()) if len(stems) else None,
            'bu_urna_por_pleito': stems.groupby('pleito')[['linhas', 'stems', 'stems_repetidos']].sum().astype(int).to_dict('index') if len(stems) else {},
            'sistema_resultados_2026t2': sr.iloc[0].astype(int).to_dict() if sr is not None else None,
            'sistema_resultados_repetidos': int(len(sr_dup)) if sr_dup is not None else None}
    _rec(resumo, 'C7-13', 'feita', nums, files)


def _le(nome):
    return pd.read_csv(OUT / nome, sep=';', decimal=',', encoding='utf-8-sig')


def _f(nome):
    return str((OUT / nome).relative_to(ROOT)).replace('\\', '/')


def roda_consolida(resumo, achados, cache):
    """Reescreve C7_achados.json a partir dos CSVs ja gravados (um achado por resultado, com controles lado a lado) e grava
    quarentena_C7.csv (mesmo vazia). Nao recalcula nada."""
    A = []
    cal = _le('C7-01_calibracao.csv').set_index(['ano', 'medida'])
    sens = _le('C7-01_sensibilidade_phi1.csv').set_index(['ano', 'medida'])
    geo = _le('C7-01_geografia_dos_pares.csv').set_index('ano')
    res2 = _le('C7-02_resumo_por_eleicao.csv').set_index('ano')
    logs = _le('C7-02_pares_2022_2026_logs.csv')

    def c(ano, med, col):
        return float(cal.loc[(ano, med), col])

    def sv(ano, med, col):
        return float(sens.loc[(ano, med), col])
    txt = '; '.join(f'{a}: {int(c(a, "pares_identicos", "observado"))} obs / nulo local {c(a, "pares_identicos", "nulo1_media"):.0f} '
                    f'/ permutacao {c(a, "pares_identicos", "nulo2_media"):.0f} (p {c(a, "pares_identicos", "nulo2_p_excesso"):.2f}) / phi=1 '
                    f'{sv(a, "pares_identicos", "nulo_phi1_media"):.0f} (p {sv(a, "pares_identicos", "p_excesso"):.2f})' for a in ANOS)
    A.append({
        'id_sugerido': 'C7-02-vetores-identicos', 'titulo': 'Pares de secoes com vetor completo do 2o turno identico: o dobro de 2022 em 2026, '
        'dentro do esperado ao acaso pelos tres nulos', 'pleito': '2026-t2', 'cargo': 'presidente', 'uf': 'BR',
        'escopo': f'{int(res2.loc[2026, "pares"])} pares / {int(res2.loc[2026, "secoes_em_par"])} secoes de {int(res2.loc[2026, "secoes_elegiveis"])} '
                  f'(2022: {int(res2.loc[2022, "pares"])} / {int(res2.loc[2022, "secoes_em_par"])} de {int(res2.loc[2022, "secoes_elegiveis"])})',
        'tipo': 'vetores identicos entre secoes distintas (aptos, comp, A, B, branco, nulo)',
        'efeito': f'{txt}. Fracao dos pares na mesma UF ou mais perto: 2026 {res2.loc[2026, "frac_mesma_uf_ou_mais"]:.3f}, 2022 '
                  f'{res2.loc[2022, "frac_mesma_uf_ou_mais"]:.3f} (nulo local 2026 {1 - geo.loc[2026, "frac_nulo1_outra_uf"]:.3f}). Histograma de 15 min '
                  f'do log identico em {int(logs.bins_identicos.sum())} de {len(logs)} pares de 2022/2026 (L1 minimo {logs.bins_L1.min():.0f}).',
        'efeito_num': round(c(2026, 'pares_identicos', 'observado') / sv(2026, 'pares_identicos', 'nulo_phi1_media'), 3),
        'materialidade_min': 0, 'materialidade_max': 0,
        'margem_referencia': 'nao se aplica: coincidencia de contagens nao move voto',
        'artefato_excluido': 'invariante comp = A+B+branco+nulo em todas as secoes (0 em quarentena); ZZ, comp < 50 e A ou B = 0 excluidos; '
                             'logs de cada par comparados (bins_2022/2026)',
        'controles': '2014, 2018 e 2022 com a mesma regra e os mesmos nulos; o nulo reproduz o salto 2022 -> 2026 (466 -> 1.028 no local; '
                     '547 -> 1.200 com phi = 1) porque 2026 concentra 319.779 secoes com comparecimento 200-299 (2022: 275.408)',
        'hipoteses': ['coincidencia ao acaso entre secoes de tamanho parecido (todos os nulos ficam entre 0,90 e 1,26 vezes o observado nas 4 eleicoes)',
                      'concentracao maior do comparecimento em 2026 eleva as coincidencias'],
        'status_sugerido': 'PLAUSIVEL-EXPLICAVEL', 'dados_externos': 'nenhum',
        'fonte': [_f('C7-01_calibracao.csv'), _f('C7-01_sensibilidade_phi1.csv'), _f('C7-02_resumo_por_eleicao.csv'),
                  _f('C7-02_pares_2022_2026_logs.csv')], 'prioridade': 3})
    ml = logs[(logs.nivel == 'mesmo_local') & (logs.ano == 2026)]
    A.append({
        'id_sugerido': 'C7-02-mesmo-local-2026', 'titulo': '2026 T2: 9 pares de secoes do mesmo predio com vetor identico (2022: 1)',
        'pleito': '2026-t2', 'cargo': 'presidente', 'uf': ','.join(sorted(ml.uf_1.unique())), 'escopo': f'{len(ml)} pares / {2 * len(ml)} secoes',
        'tipo': 'vetores identicos no mesmo local de votacao',
        'efeito': f'observado {int(c(2026, "pares_mesmo_local", "observado"))}; nulo local {c(2026, "pares_mesmo_local", "nulo1_media"):.1f} '
                  f'(p {c(2026, "pares_mesmo_local", "nulo1_p_excesso"):.3f}); nulo phi = 1 {sv(2026, "pares_mesmo_local", "nulo_phi1_media"):.1f} '
                  f'(p {sv(2026, "pares_mesmo_local", "p_excesso"):.2f}); 2014 {int(c(2014, "pares_mesmo_local", "observado"))}, 2018 '
                  f'{int(c(2018, "pares_mesmo_local", "observado"))}, 2022 {int(c(2022, "pares_mesmo_local", "observado"))}. Todos os 9 pares: 1 log por '
                  f'secao, sem contingencia, histogramas de 15 min diferentes (L1 {ml.bins_L1.min():.0f}-{ml.bins_L1.max():.0f}), encerramentos e '
                  'liberacoes por codigo (hab_2) diferentes.',
        'efeito_num': float(c(2026, 'pares_mesmo_local', 'observado')), 'materialidade_min': 0,
        'materialidade_max': int(2 * ml.t2_comp.sum()), 'margem_referencia': 'local; soma do comparecimento das 18 secoes como teto formal',
        'artefato_excluido': 'log, horario e habilitacao de cada secao conferidos: nada indica copia de uma secao para outra',
        'controles': '2014/2018/2022 (3/1/1 pares); dois nulos que cercam a dispersao dentro do predio (phi global e phi = 1)',
        'hipoteses': ['dentro do predio as secoes de 2022/2026 variam no piso binomial (dentro_local_sobre_piso 0,15/0,16), o que torna o nulo local '
                      'conservador; com phi = 1 o observado fica dentro do esperado'],
        'status_sugerido': 'PLAUSIVEL-EXPLICAVEL', 'dados_externos': 'nenhum',
        'fonte': [_f('C7-02_pares_mesmo_local_ou_municipio.csv'), _f('C7-02_pares_2022_2026_logs.csv'), _f('C7-01_sensibilidade_phi1.csv')],
        'prioridade': 3})
    r4 = _le('C7-04_entre_pleitos_resumo.csv').set_index('para')
    A.append({
        'id_sugerido': 'C7-04-mesma-secao-entre-pleitos', 'titulo': 'Mesma secao 2022 x 2026 com (A, B) exatamente iguais: acima do nulo local, '
        'dentro do nulo de persistencia', 'pleito': '2026-t2', 'cargo': 'presidente', 'uf': 'BR',
        'escopo': f'{int(r4.loc[2026, "secoes_pareadas"])} secoes pareadas (aptos +-25%)', 'tipo': 'coincidencia entre pleitos (mesma secao)',
        'efeito': '; '.join(f'{int(r4.loc[p, "de"])}->{p}: (A,B) iguais {int(r4.loc[p, "ab_identicos"])} vs local {r4.loc[p, "ab_identicos_esperado"]:.0f} '
                            f'/ persistencia {r4.loc[p, "ab_identicos_persist_esperado"]:.0f} (p {r4.loc[p, "ab_identicos_persist_p_excesso"]:.2f}); vetor '
                            f'inteiro {int(r4.loc[p, "votos_identicos"])} vs {r4.loc[p, "votos_identicos_persist_esperado"]:.1f}; A/B trocados '
                            f'{int(r4.loc[p, "ab_trocados"])} vs {r4.loc[p, "ab_trocados_persist_esperado"]:.1f}' for p in (2018, 2022, 2026)),
        'efeito_num': round(float(r4.loc[2026, 'ab_identicos_persist_razao']), 3), 'materialidade_min': 0, 'materialidade_max': 0,
        'margem_referencia': 'nao se aplica', 'artefato_excluido': 'mesma chave de secao e aptos +-25% (regra de padroes_aberta.espelho)',
        'controles': '2014->2018 e 2018->2022 com os mesmos dois nulos',
        'hipoteses': ['persistencia secao a secao da fatia (correlacao 0,855 / 0,951 / 0,973), que o nulo local ignora e o de persistencia preserva'],
        'status_sugerido': 'EXPLICADO', 'dados_externos': 'nenhum', 'fonte': [_f('C7-04_entre_pleitos_resumo.csv'),
                                                                               _f('C7-04_secoes_iguais_ou_trocadas_entre_pleitos.csv')], 'prioridade': 3})
    ef = _le('C7-04_espelho_forte_secoes.csv')
    ef26 = ef[ef.para == 2026]
    fr = _le('C7-04_espelho_forte_resumo.csv').set_index('para')
    A.append({
        'id_sugerido': 'C7-04-espelho-forte-2022-2026', 'titulo': 'As 9 secoes "espelho_forte" 2022->2026 (inversao de fatia; nao e copia de vetor)',
        'pleito': '2026-t2', 'cargo': 'presidente', 'uf': ','.join(sorted(ef26.uf.unique())), 'escopo': f'{len(ef26)} secoes',
        'tipo': 'inversao de fatia entre pleitos (padroes_aberta.espelho)',
        'efeito': f'2022->2026 {int(fr.loc[2026, "espelho_forte"])} de {int(fr.loc[2026, "visiveis"])} visiveis; 2018->2022 '
                  f'{int(fr.loc[2022, "espelho_forte"])}; 2014->2018 {int(fr.loc[2018, "espelho_forte"])}. {int((ef26.secoes_predio_1 == 1).sum())} das 9 '
                  'sao secao unica no predio em 2026 (fatia do predio = da secao); o 1o turno de cada ano acompanha o 2o turno do mesmo ano '
                  '(ex.: RS 85391/54/210 2022 T1 67%/T2 63% -> 2026 T1 41%/T2 37%).',
        'efeito_num': float(len(ef26)), 'materialidade_min': 0, 'materialidade_max': int((ef26.t2_A_1 + ef26.t2_B_1).sum()),
        'margem_referencia': 'local (votos validos das 9 secoes em 2026); margem nacional de milhoes',
        'artefato_excluido': 'mesma chave e aptos +-25%; 1o turno coerente com o 2o em cada ano afasta troca de vetor no 2o turno',
        'controles': '2014->2018 (4.285) e 2018->2022 (421) com a mesma regra',
        'hipoteses': ['mudanca de composicao do eleitorado de locais pequenos (secao unica, rural/aldeia)', 'renumeracao/agregacao de secao com aptos parecido'],
        'status_sugerido': 'PLAUSIVEL-EXPLICAVEL', 'dados_externos': 'historico de agregacao/remanejamento das secoes (cadastro eleitoral por secao 2022-2026)',
        'fonte': [_f('C7-04_espelho_forte_secoes.csv'), _f('C7-04_espelho_forte_resumo.csv')], 'prioridade': 3})
    r5 = _le('C7-05_comparecimento_consecutivo_resumo.csv').set_index('ano')
    A.append({
        'id_sugerido': 'C7-05-comparecimento-em-sequencia', 'titulo': 'Comparecimento identico em secoes consecutivas: excesso estavel de 12-16% '
        'sobre o nulo condicionado a aptos nas quatro eleicoes', 'pleito': '2014-2026 t2', 'cargo': 'presidente', 'uf': 'BR',
        'escopo': f'{int(r5.loc[2026, "secoes"])} secoes (2026)', 'tipo': 'comparecimento igual em sequencia',
        'efeito': '; '.join(f'{a}: {int(r5.loc[a, "pares_consecutivos_iguais"])} pares (trios {int(r5.loc[a, "trios_consecutivos_iguais"])}) vs nulo '
                            f'(zona, aptos) {r5.loc[a, "nuloB_zona_aptos_pares_media"]:.0f} -> razao {r5.loc[a, "nuloB_razao"]:.3f}' for a in ANOS),
        'efeito_num': round(float(r5.loc[2026, 'nuloB_razao']), 3), 'materialidade_min': 0, 'materialidade_max': 0,
        'margem_referencia': 'nao se aplica', 'artefato_excluido': 'ZZ e comp < 50 excluidos; ordem numerica da secao na zona',
        'controles': '2014/2018/2022 com o mesmo nulo: razao 1,119 / 1,143 / 1,155; 2026 1,131 (sem diferenca de regime)',
        'hipoteses': ['secoes vizinhas (mesmo predio, mesma epoca de criacao) tem taxa de comparecimento parecida; o nulo por (zona, aptos) nao preserva essa '
                      'correlacao espacial'],
        'status_sugerido': 'PLAUSIVEL-EXPLICAVEL', 'dados_externos': 'nenhum', 'fonte': [_f('C7-05_comparecimento_consecutivo_resumo.csv'),
                                                                                         _f('C7-05_por_faixa_aptos.csv')], 'prioridade': 3})
    s6 = _le('C7-06_sequencias_resumo.csv').set_index(['ano', 'medida'])
    A.append({
        'id_sugerido': 'C7-06-sequencias-no-predio', 'titulo': 'Progressoes aritmeticas entre secoes consecutivas do predio acima da permutacao da ordem, '
        'nas quatro eleicoes (2026 com a menor razao)', 'pleito': '2014-2026 t2', 'cargo': 'presidente', 'uf': 'BR', 'escopo': 'predios com >= 3 secoes',
        'tipo': 'sequencias numericas', 'efeito': '; '.join(
            f'{a}: trios em progressao A {int(s6.loc[(a, "A_trios_progressao"), "observado"])} vs {s6.loc[(a, "A_trios_progressao"), "nulo_media"]:.0f} '
            f'(razao {s6.loc[(a, "A_trios_progressao"), "razao"]:.2f}); A-B constante {int(s6.loc[(a, "predios_A_menos_B_constante"), "observado"])} vs '
            f'{s6.loc[(a, "predios_A_menos_B_constante"), "nulo_media"]:.1f}; ultimo digito de A igual {int(s6.loc[(a, "predios_ultimo_digito_A_igual"), "observado"])}'
            f' vs {s6.loc[(a, "predios_ultimo_digito_A_igual"), "nulo_media"]:.0f}' for a in ANOS) + '. Maior run monotono dentro do nulo em todas.',
        'efeito_num': round(float(s6.loc[(2026, 'A_trios_progressao'), 'razao']), 3), 'materialidade_min': 0, 'materialidade_max': 0,
        'margem_referencia': 'nao se aplica', 'artefato_excluido': 'mesmo filtro das demais (ZZ, comp < 50, A ou B = 0); ordem numerica da secao',
        'controles': '2014 1,64 / 2018 1,39 / 2022 1,39 / 2026 1,34 (progressao de A); A-B constante 2026 4 vs 1,3 (p 0,03) e 2014 4 vs 0,8; '
                     'BH a 5% na familia de 2026 (6 medidas): passam so as progressoes',
        'hipoteses': ['secoes numeradas em sequencia tem tamanhos que variam de forma suave (criacao em lotes), o que gera segundas diferencas pequenas; '
                      'a permutacao da ordem destroi essa suavidade'],
        'status_sugerido': 'PLAUSIVEL-EXPLICAVEL', 'dados_externos': 'nenhum',
        'fonte': [_f('C7-06_sequencias_resumo.csv'), _f('C7-06_predios_sinalizados.csv')], 'prioridade': 3})
    r7 = _le('C7-07_resumo.csv').iloc[0]
    A.append({
        'id_sugerido': 'C7-07-codigos-nulos-rdv', 'titulo': '2026 T2: pares com votos identicos e mesma impressao digital de nulos digitados no RDV '
        'dentro do nulo estratificado por UF e perfil de voto', 'pleito': '2026-t2', 'cargo': 'presidente', 'uf': 'BR',
        'escopo': f'{int(r7.pares_votos_identicos)} pares com (v13, v22, branco, nulo) iguais em {int(r7.secoes)} secoes',
        'tipo': 'quase-duplicata (RDV)', 'efeito': f'codigos nulos identicos em {int(r7.pares_nulos_identicos)} pares; nulo nacional '
        f'{r7.nulo_media_identicos:.0f}, por UF {r7.nulo_uf_media_identicos:.0f}, por decil da fatia {r7.nulo_decilA_media_identicos:.0f}, por UF x decil '
        f'{r7.nulo_uf_decilA_media_identicos:.0f} +- {r7.nulo_uf_decilA_dp:.0f} (p {r7.nulo_uf_decilA_p_excesso:.2f}); histograma de log identico em '
        f'{int(r7.pares_bins_identicos)} pares', 'efeito_num': round(float(r7.pares_nulos_identicos / r7.nulo_uf_decilA_media_identicos), 3),
        'materialidade_min': 0, 'materialidade_max': 0, 'margem_referencia': 'nao se aplica',
        'artefato_excluido': 'ZZ, comp < 50, v13 ou v22 = 0 excluidos; o par e as duas secoes do par ficam fora do sorteio do nulo',
        'controles': 'sem controle 2022 (RDV de 2022 so em amostra de 2.030 urnas de 7 UFs); controle interno = nulos estratificados',
        'hipoteses': ['habito regional de digitacao de nulos combinado com o perfil de voto da secao'],
        'status_sugerido': 'PLAUSIVEL-EXPLICAVEL', 'dados_externos': 'RDV de 2022 T2 de todas as secoes (para o controle entre eleicoes)',
        'fonte': [_f('C7-07_resumo.csv'), _f('C7-07_pares_votos_identicos_rdv.csv')], 'prioridade': 3})
    rp = _le('C7-09_resumo_por_pleito.csv')
    rep = _le('C7-09_series_repetidas_secoes.csv')
    rel = _le('C7-09_relogio_series_repetidas.csv')
    sp = rep[(rep.uf == 'SP') & (rep.municipality == 71072) & (rep.zone == 389)]
    A.append({
        'id_sugerido': 'C7-09-series-repetidas', 'titulo': 'Mesma serie de urna efetivada em mais de uma secao: sempre urna APURADA, '
        'explicada pela origem do voto no CEFT (sistema de apuracao ou RED em urna de contingencia)', 'pleito': '2012-2026-t1',
        'cargo': 'presidente/prefeito/governador', 'uf': 'BR',
        'escopo': f'{int(rp.series_repetidas.fillna(0).sum())} series em {int(rp.secoes_em_serie_repetida.fillna(0).sum())} secoes de 15 pleitos '
                  f'({int((rep.uf == "ZZ").sum())} no exterior); 0 em 2020, 2024 e 2026-t1 (governador, 10 UFs)',
        'tipo': 'duplicidade fisica (serie de urna)',
        'efeito': 'tipo de urna nas secoes com serie repetida: ' + json.dumps(rep.tipo_urna.astype(str).value_counts().to_dict(), ensure_ascii=False)
                  + f'; series com vetores identicos entre as suas secoes: {int(_le("C7-09_series_repetidas_resumo.csv").vetores_identicos.sum())}; '
                  + f'series em mais de uma UF: {len(_le("C7-09_series_em_mais_de_uma_uf.csv"))}. CEFT (11 UFs) das secoes repetidas: '
                  + json.dumps(rep.origem.fillna('sem CEFT').astype(str).value_counts().to_dict(), ensure_ascii=False)
                  + f'. SP 71072/389/524 e 529 (2022-t1, serie {sp.urna.iloc[0] if len(sp) else "?"}): CEFT "BU gerado por RED em urna de contingencia" nas '
                  'duas, urnas esperadas 1003632 e 1087092 diferentes; abertura 08:00:01 e encerramentos 20:10:06 / 20:24:02 sao das urnas originais.',
        'efeito_num': float(len(rep)), 'materialidade_min': 0, 'materialidade_max': int(rep.comp.fillna(0).sum()),
        'margem_referencia': 'local (secoes individuais)',
        'artefato_excluido': 'marcadores #NULO#/-1/vazio tratados como serie ausente (72 secoes em 2018-t1); tipo e vetor conferidos no BWEB; CEFT mapeado '
                             'por posicao em 2012-2016 (c10/c18 = numero da urna)',
        'controles': 'todos os pleitos 2012-2026-t1 lado a lado; relogio_por_secao 2022-t1/t2: ' + str(rel.groupby('pleito').urna.nunique().to_dict()),
        'hipoteses': ['urna de uma secao usada pela junta para apurar outra (sistema de apuracao)', 'RED em urna de contingencia que atendeu duas secoes'],
        'status_sugerido': 'EXPLICADO', 'dados_externos': 'CEFT das 16 UFs restantes e de 2026-t2; BWEB/serie de 2026-t2',
        'fonte': [_f('C7-09_series_repetidas_secoes.csv'), _f('C7-09_series_repetidas_resumo.csv'), _f('C7-09_resumo_por_pleito.csv'),
                  _f('C7-09_relogio_series_repetidas.csv')], 'prioridade': 3})
    cp = _le('C7-09_ceft_por_pleito_uf.csv').groupby('pleito')[['linhas', 'secoes', 'linhas_alem_de_uma_por_secao', 'efetivada_diferente_da_esperada']].sum()
    A.append({
        'id_sugerido': 'C7-09-ceft-2012-t2-linhas-duplas', 'titulo': 'CEFT 2012-t2 com linhas a mais por secao (dado de origem)',
        'pleito': '2012-t2', 'cargo': 'prefeito', 'uf': '11 UFs', 'escopo': f'{int(cp.loc["2012-t2", "linhas"])} linhas para {int(cp.loc["2012-t2", "secoes"])} secoes',
        'tipo': 'duplicidade de linhas (fonte ou aquisicao)', 'efeito': f'{int(cp.loc["2012-t2", "linhas_alem_de_uma_por_secao"])} linhas alem de uma por '
        'secao; linhas inteiras repetidas (conferido em BA: 10.484 linhas, 5.242 distintas), como no BWEB do mesmo pleito; demais pleitos 0 (2016-t1: 13)', 'efeito_num': float(cp.loc['2012-t2', 'linhas_alem_de_uma_por_secao']), 'materialidade_min': 0, 'materialidade_max': 0,
        'margem_referencia': 'nao se aplica (tabela de correspondencia, sem votos)', 'artefato_excluido': 'contagem por chave de secao distinta',
        'controles': 'CEFT 2012-t1 .. 2026-t1',
        'hipoteses': ['arquivo de origem do TSE com o conteudo repetido', 'captura que concatenou duas copias (mesmo padrao do BWEB 2012-t2)'],
        'status_sugerido': 'ARTEFATO', 'dados_externos': 'zip original de 2012-t2 (C1)', 'fonte': [_f('C7-09_ceft_por_pleito_uf.csv')], 'prioridade': 2})
    b13 = _le('C7-13_bweb_duplicatas_por_pleito_uf.csv').groupby('pleito')[['linhas', 'chaves', 'chaves_duplicadas', 'chaves_duplicadas_com_votos_diferentes']].sum()
    vot = None
    try:
        con = duck()
        fs = [p.as_posix() for p in _bweb_files('2012-t2', 'PREFEITO')]
        vot = int(con.execute(f"select sum(try_cast(QT_VOTOS as bigint)) from read_parquet({fs!r})").fetchone()[0])
        con.close()
    except Exception:  # noqa: BLE001
        vot = None
    A.append({
        'id_sugerido': 'C7-13-bweb-2012-t2-duplicado', 'titulo': 'BWEB prefeito 2012-t2: toda linha aparece duas vezes, com os mesmos votos',
        'pleito': '2012-t2', 'cargo': 'prefeito', 'uf': '10 UFs', 'escopo': f'{int(b13.loc["2012-t2", "chaves"])} chaves (secao x votavel), '
        f'{int(b13.loc["2012-t2", "linhas"])} linhas', 'tipo': 'duplicidade de linhas (fonte ou aquisicao)',
        'efeito': f'{int(b13.loc["2012-t2", "chaves_duplicadas"])} chaves duplicadas, {int(b13.loc["2012-t2", "chaves_duplicadas_com_votos_diferentes"])} '
                  'com votos diferentes; os outros 14 pleitos tem 0 chaves duplicadas', 'efeito_num': float(b13.loc['2012-t2', 'chaves_duplicadas']),
        'materialidade_min': 0, 'materialidade_max': int(vot / 2) if vot else 0,
        'margem_referencia': 'votos que seriam contados duas vezes por quem somar o arquivo sem deduplicar (metade da soma bruta)',
        'artefato_excluido': 'contagem por (municipio, zona, secao, cargo, votavel); valores comparados', 'controles': 'os outros 14 pleitos do BWEB em disco',
        'hipoteses': ['zip de origem com o CSV repetido ou captura que concatenou duas copias (linhas inteiras identicas: BA 40.880 linhas, '
                      '20.440 distintas); quem somar o arquivo sem deduplicar dobra os votos de 2012-t2'], 'status_sugerido': 'ARTEFATO',
        'dados_externos': 'conferir o zip original de 2012-t2 (C1)', 'fonte': [_f('C7-13_bweb_duplicatas_por_pleito_uf.csv'),
                                                                                _f('C7-13_bweb_duplicatas_casos.csv')], 'prioridade': 2})
    A.append({
        'id_sugerido': 'C7-11-ES-57932-9-85', 'titulo': 'ES 57932/9/85 (2026 T2): 612 votos no log contra 308 no BU era artefato do leitor',
        'pleito': '2026-t2', 'cargo': 'presidente', 'uf': 'ES', 'escopo': '1 secao (mais a secao 112, servida pela mesma urna de contingencia)',
        'tipo': 'log de outra secao embalado no pacote', 'efeito': 'pacote com 3 logd.dat: contingencia 01758779 (0 votos; declara 0000 e 0112, '
        'usada em 25/10 19:39 e 21:24), urna 01841837 (secao 85: 308 em 25/10 = BU) e urna 01750820 (secao 112: 304 = BU); o leitor antigo somava '
        '308 + 304 = 612; com section_hint (04/11, nao commitado) = 308. Pacote da 112: contingencia + 01750820 = 304 = BU.',
        'efeito_num': 0.0, 'materialidade_min': 0, 'materialidade_max': 0, 'margem_referencia': 'local',
        'artefato_excluido': 'pacotes abertos membro a membro; ultimo_voto_por_secao.csv relido = 308 e 304; RDV = BU',
        'controles': 'secao 112 do mesmo pacote de contingencia; vizinhas do predio (C7-11_vizinhas_mesmo_predio.csv)',
        'hipoteses': ['urna de contingencia que recuperou duas secoes exporta o log das duas'], 'status_sugerido': 'ARTEFATO',
        'dados_externos': 'nenhum', 'fonte': [_f('C7-11_dossie_fatos.csv'), _f('C7-11_secoes_contexto.csv')], 'prioridade': 2})
    A.append({
        'id_sugerido': 'C7-11-urna-intermediaria', 'titulo': 'BA 35653/173/235 e MA 8893/47/609 (2026 T2): BU maior que o log porque o pacote nao traz '
        'o log de uma urna intermediaria', 'pleito': '2026-t2', 'cargo': 'presidente', 'uf': 'BA,MA', 'escopo': '2 secoes',
        'tipo': 'reconciliacao log x BU', 'efeito': 'BA: contingencia 01656557 com 204 votos + log de T1 da 01833178 + log de 170 linhas da 01833178 '
        '(25/10 09:04, declara 0083, sem votos); BU 217 -> faltam 13. MA: contingencia 01664037 com 188 votos + log de T1 da 01813459 (declara 0445); '
        'BU 224 -> faltam 36.', 'efeito_num': 49.0, 'materialidade_min': 49, 'materialidade_max': 49,
        'margem_referencia': 'local; 49 votos sem log contra uma margem nacional de milhoes',
        'artefato_excluido': 'logs aninhados lidos; RDV = BU nas duas secoes; demais secoes com log = BU',
        'controles': 'vizinhas do predio (BA 3 secoes, MA 9) sem diferenca log x BU', 'hipoteses': ['troca de urna sem o log da urna intermediaria no pacote publicado'],
        'status_sugerido': 'NAO_TESTAVEL', 'dados_externos': 'log da urna intermediaria e ata da mesa (TSE/TRE)',
        'fonte': [_f('C7-11_dossie_fatos.csv'), _f('C7-11_secoes_contexto.csv')], 'prioridade': 2})
    achados.clear()
    achados.extend(A)
    q = OUT / 'quarentena_C7.csv'
    if not q.exists():
        pd.DataFrame(columns=['checagem', 'reason']).to_csv(q, **CSV)
    _rec(resumo, 'C7-achados', 'feita', {'achados': len(A), 'quarentena_linhas': int(len(pd.read_csv(q, sep=';', encoding='utf-8-sig')))},
         [_f('C7_achados.json'), _f('quarentena_C7.csv')], motivo='consolidacao dos achados a partir dos CSVs (sem recalculo)')


def roda_pendentes(resumo):
    if 'C7-08' not in resumo:
        _rec(resumo, 'C7-08', 'nao_feita', {}, [], motivo='depende da passada pesada de logs (hash SHA-256 por logd.dat; ver roda_c7_08)')
    _rec(resumo, 'C7-10', 'nao_feita', {}, [], motivo='depende da passada pesada de BUs: SHA-256 de bu_raw em research/segundo_turno_2026/bu/<UF>.parquet (14 UFs) e em '
         'research/bu_urna/2026-t2/<UF>/part-*.parquet, por UF e por parte, join por stem/secao; contar iguais/diferentes/so-em-um; group by hash para BU identico em '
         'secoes distintas; depois estender integridade_check "zips" ao rotulo 2026-t2')
    _rec(resumo, 'C7-12', 'nao_feita', {}, [], motivo='depende da passada pesada de logs: reler com read_log(merge=True) as secoes das 11 UFs com vote_events != attendance '
         '(secoes_indicadores_P2022/P2022b/P2026) e refazer log_x_boletim.csv com iguais/menor/maior e explicacao')
    _rec(resumo, 'C7-14', 'nao_feita', {}, [], motivo='exige rede (HEAD + diretorio central dos 164 zips); nao permitido nesta fase')


CHECAGENS = ['C7-01', 'C7-01s', 'C7-02', 'C7-04', 'C7-05', 'C7-09', 'C7-13', 'C7-03', 'C7-06', 'C7-11', 'C7-08', 'C7-07', 'C7-achados']
RUNNERS = {'C7-01': roda_c7_01, 'C7-01s': roda_c7_01s, 'C7-02': roda_c7_02, 'C7-03': roda_c7_03, 'C7-04': roda_c7_04, 'C7-05': roda_c7_05,
           'C7-06': roda_c7_06, 'C7-07': roda_c7_07, 'C7-08': roda_c7_08, 'C7-09': roda_c7_09, 'C7-11': roda_c7_11, 'C7-13': roda_c7_13,
           'C7-achados': roda_consolida}


def _grava_estado(resumo, achados):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'C7_resumo.json').write_text(json.dumps({'camada': 'C7', 'protocolo': 'v1.0', 'parser_version': PARSER_VERSION,
                                                    'checagens': resumo}, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    (OUT / 'C7_achados.json').write_text(json.dumps(achados, ensure_ascii=False, indent=1, default=str), encoding='utf-8')


def main(ids=None):
    ids = ids or CHECAGENS
    OUT.mkdir(parents=True, exist_ok=True)
    resumo, achados, cache = {}, [], {}
    p_res, p_ach = OUT / 'C7_resumo.json', OUT / 'C7_achados.json'
    if p_res.exists():
        try:
            resumo = json.loads(p_res.read_text(encoding='utf-8')).get('checagens', {})
        except ValueError:
            resumo = {}
    if p_ach.exists():
        try:
            achados = [a for a in json.loads(p_ach.read_text(encoding='utf-8')) if '-'.join(a['id_sugerido'].split('-')[:2]) not in ids]
        except (ValueError, KeyError):
            achados = []
    if 'C7-01' not in ids and (OUT / 'C7-01_calibracao.csv').exists():
        cache['calib'] = pd.read_csv(OUT / 'C7-01_calibracao.csv', sep=';', decimal=',', encoding='utf-8-sig')
    if 'C7-02' not in ids and (OUT / 'C7-02_pares_vetor_identico.csv').exists():
        cache['pares_t2'] = pd.read_csv(OUT / 'C7-02_pares_vetor_identico.csv', sep=';', decimal=',', encoding='utf-8-sig')
    for cid in ids:
        t0 = _t()
        try:
            RUNNERS[cid](resumo, achados, cache)
            resumo[cid]['minutos'] = round((_t() - t0) / 60, 2)
            print(f'{cid}: {resumo[cid]["status"]} em {_t() - t0:.0f} s', flush=True)
        except Exception as exc:  # noqa: BLE001
            _rec(resumo, cid, 'nao_feita', {}, [], motivo=f'erro: {exc!r}'[:500])
            print(f'{cid}: ERRO {exc!r}', flush=True)
            _grava_estado(resumo, achados)
            raise
        gc.collect()
        _grava_estado(resumo, achados)
    roda_pendentes(resumo)
    _grava_estado(resumo, achados)
    if _QUARENTENA:
        q = pd.DataFrame(_QUARENTENA)
        old = OUT / 'quarentena_C7.csv'
        if old.exists():
            q = pd.concat([pd.read_csv(old, sep=';', encoding='utf-8-sig', dtype=str), q], ignore_index=True).drop_duplicates()
        q.to_csv(old, **CSV)
    print(json.dumps({k: v['status'] for k, v in resumo.items()}, ensure_ascii=False))


if __name__ == '__main__':
    main([a for a in sys.argv[1:] if a.startswith('C7-')] or None)
