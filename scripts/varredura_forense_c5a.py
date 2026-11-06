"""Varredura forense, camada C5 parte A (padroes estatisticos entre secoes): calibracao do modelo do predio, branco/nulo,
ultimo digito calibrado, outliers RJ 2014/2018 e localizacao dos picos de fatia/razao.

Checagens (ids do mapa relatorios/verificacoes/varredura_forense/mapa/mapa_C5.json):
  C5-01  calibracao do modelo do local entre as 4 presidenciais (piso phi=1, phi livre, permutacao dentro do predio,
         modelo com a fatia de terceiros do 1o turno, secoes agregadas, tamanho)
  C5-03  branco+nulo por secao contra as vizinhas do predio (nivel por turno e mudanca 1o->2o), zeros observados x esperados
  C5-06  ultimo digito e amontoamento (multiplos de 5/10, fracoes exatas) contra referencia simulada (binomial por secao)
  C5-09  secoes fora do modelo (|z|>4) em 2014/2018 (RJ 2018: 294) com causa provavel, ao lado das 4+4 de 2022/2026
  C5-12  localizacao (UF, tamanho, pares de contagem) dos picos de fatia e de razao 2o/1o turno

Funcoes `c5_*` e auxiliares sao puras (DataFrames sinteticos nos testes); `carrega_*` leem o disco com projecao de colunas
e DuckDB limitado (400 MB, 2 threads). `main()` roda ano a ano (uma base por vez) e grava
relatorios/verificacoes/varredura_forense/C5/ (C5-XX_*.csv, C5_resumo.json) e research/varredura_forense/C5/ (parquet por
secao + recibo .json). Usa scripts/padroes_lib.py sem altera-lo. Importavel sem efeito pesado.

Protocolo: relatorios/verificacoes/varredura_forense/PROTOCOLO.md v1.0. Tudo aqui e exploratorio e descritivo:
"diferenca acima do limiar" e "prioridade de observacao" nao indicam irregularidade por si so.
Uso: python scripts/varredura_forense_c5a.py [C5-01 C5-03 C5-06 C5-09 C5-12] [--anos 2014,2018,2022,2026]
"""
import datetime as dt
import gc
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from scipy.special import betaln, expit, logit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import padroes_lib as pl  # noqa: E402

R = ROOT / 'research'
REL = ROOT / 'relatorios'
OUT = REL / 'verificacoes' / 'varredura_forense' / 'C5'
CACHE = R / 'varredura_forense' / 'C5'
QUAR = R / 'varredura_forense' / 'quarentena'
BASES = R / 'padroes_2t'
AGREG_2026 = REL / 'verificacoes' / 'varredura_forense' / 'C4' / 'C4-02_2026-t{t}_secoes_agregadas_cs_json.csv'
CSV = dict(sep=';', decimal=',', encoding='utf-8-sig', index=False)
PARSER_VERSION = 'varredura-forense-c5a-1'
KEY = ['uf', 'municipality', 'zone', 'section']
ANOS = (2014, 2018, 2022, 2026)
NOMES = {2014: ('Dilma', 'Aécio'), 2018: ('Haddad', 'Bolsonaro'), 2022: ('Lula', 'Bolsonaro'), 2026: ('Lula', 'Flávio')}
NOT_COMP = 'NOT_COMPARABLE'
SEED = 20261105
Z_LIM = 4.0               # |z| >= 4 para secao isolada (protocolo, secao 6)
R_SIM = 20                # replicas das referencias simuladas de fora4 (igual ao padroes_lib.trocas)
R_PERM = 5                # replicas da permutacao da mudanca dentro do predio (cada uma refaz o modelo inteiro)
R_DIG = 200               # replicas da referencia do ultimo digito
M_TERCEIROS = 300         # votos de terceiros "a priori" (municipio) na transferencia do predio; grade de sensibilidade abaixo
M_GRADE = (0, 100, 300, 1000)
MIN_APTOS_PROTOCOLO = 50  # secoes com < 50 aptos e exterior (ZZ) ficam fora das referencias estatisticas (protocolo, secao 2)
MIN_CONTAGEM_DIG = 100    # ultimo digito so em contagens >= 100 (como padroes_lib.digitos)
MIN_COMP_BN = 30          # branco/nulo: comparecimento minimo por turno para entrar no modelo do predio
MIN_COMP_ZERO = 100       # zeros de branco+nulo contados so com comparecimento >= 100 (como no mapa)
FRACOES = ((1, 2), (1, 3), (2, 3), (1, 4), (3, 4), (1, 5), (2, 5), (3, 5), (4, 5))
MIN_VALIDOS_FRACAO = 20
FAIXAS_N2 = (30, 100, 200, 300, 10 ** 6)
FAIXAS_TERC = (0, .10, .20, .35, 1.01)
_QUARENTENA: list[dict] = []


# ----------------------------------------------------------------------------------------------- utilidades
def duck():
    import duckdb
    con = duckdb.connect()
    con.execute("SET memory_limit='400MB'")
    con.execute('SET threads=2')
    return con


def sha_arquivo(path):
    """SHA-256 de uma entrada: reutiliza o recibo <arquivo>.json ao lado quando existir."""
    path = Path(path)
    rec = path.with_suffix('.json')
    if path.suffix == '.parquet' and rec.exists():
        try:
            j = json.loads(rec.read_text(encoding='utf-8'))
            if isinstance(j, dict) and j.get('sha256'):
                return j['sha256']
        except (ValueError, OSError):
            pass
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def grava_parquet(df, path, inputs):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    with open(path, 'rb') as f:
        sha = hashlib.file_digest(f, 'sha256').hexdigest()
    rec = {'at': dt.datetime.now(dt.timezone.utc).isoformat(), 'inputs': {str(k): v for k, v in inputs.items()},
           'sha256': sha, 'rows': int(len(df)), 'bytes': path.stat().st_size, 'parser_version': PARSER_VERSION}
    path.with_suffix('.json').write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding='utf-8')
    return rec


def quarentena(checagem, df, reason):
    """Linhas que falham invariante: valores originais como string + motivo (JSON por checagem)."""
    if df is None or len(df) == 0:
        return 0
    rows = [{k: ('' if pd.isna(v) else str(v)) for k, v in r.items()} | {'reason': reason, 'checagem': checagem}
            for r in df.to_dict('records')]
    QUAR.mkdir(parents=True, exist_ok=True)
    p = QUAR / f'rows-C5-{checagem}.json'
    old = json.loads(p.read_text(encoding='utf-8')) if p.exists() else []
    p.write_text(json.dumps(old + rows, ensure_ascii=False, indent=1), encoding='utf-8')
    _QUARENTENA.extend(rows)
    return len(rows)


def csv_out(nome, df):
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(df).to_csv(OUT / nome, **CSV)
    return str(OUT / nome).replace('\\', '/')


def bh(p):
    """q-valores de Benjamini-Hochberg (NaN preservado)."""
    p = np.asarray(p, float)
    q = np.full(len(p), np.nan)
    ok = ~np.isnan(p)
    if not ok.any():
        return q
    pv = p[ok]
    o = np.argsort(pv)
    m = len(pv)
    r = pv[o] * m / np.arange(1, m + 1)
    r = np.minimum.accumulate(r[::-1])[::-1]
    qq = np.empty(m)
    qq[o] = np.clip(r, 0, 1)
    q[ok] = qq
    return q


def phi_robusto(z):
    """Variancia robusta (MAD^2) do z bruto, SEM o piso 1 do padroes_lib."""
    z = np.asarray(z, float)
    z = z[np.isfinite(z)]
    return float((1.4826 * np.median(np.abs(z - np.median(z)))) ** 2)


def faixa(x, cortes, fmt='{:g}-{:g}'):
    lab = [fmt.format(a, b) for a, b in zip(cortes[:-1], cortes[1:])]
    return pd.cut(x, list(cortes), right=False, labels=lab).astype(str)


# ----------------------------------------------------------------------------------------------- carregadores
def carrega_base(ano):
    """research/padroes_2t/base_<ano>.parquet so com as colunas usadas aqui (sem horarios), contagens em int32
    (pool de memoria do sistema no pyarrow, para devolver a memoria depois da conversao)."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    pa.set_memory_pool(pa.system_memory_pool())
    p = BASES / f'base_{ano}.parquet'
    names = pq.ParquetFile(p).schema_arrow.names
    keep = [c for c in names if c in KEY + ['voting_place', 'municipio', 't1_menores'] or
            (c[:3] in ('t1_', 't2_') and c[3:] in ('aptos', 'comp', 'branco', 'nulo', 'A', 'B', 'validos')) or
            (c.startswith('t1_v') and c[4:].isdigit())]
    b = pq.read_table(p, columns=keep).to_pandas(self_destruct=True)
    for c in b:
        if c not in ('uf', 'municipio') and b[c].dtype.kind in 'if' and not b[c].isna().any():
            b[c] = b[c].astype('int32')
    gc.collect()
    return b


def invariantes_base(b, ano):
    """Invariantes por secao da base: comp <= aptos, validos + branco + nulo = comp, A + B <= validos, nada negativo."""
    falhas = []
    for t in ('t1', 't2'):
        num = b[[f'{t}_{c}' for c in ('aptos', 'comp', 'branco', 'nulo', 'A', 'B', 'validos')]]
        m = ((b[f'{t}_comp'] > b[f'{t}_aptos']) | (b[f'{t}_validos'] + b[f'{t}_branco'] + b[f'{t}_nulo'] != b[f'{t}_comp']) |
             (b[f'{t}_A'] + b[f'{t}_B'] > b[f'{t}_validos']) | (num < 0).any(axis=1))
        if m.any():
            falhas.append(b.loc[m, KEY + list(num.columns)].assign(turno=t, ano=ano))
    return pd.concat(falhas, ignore_index=True) if falhas else pd.DataFrame(columns=KEY)


def formato(b):
    """Formato comum do padroes_lib (A = X, B = Y), so com as colunas usadas na camada (validos, branco, nulo separados)."""
    d = pd.DataFrame({c: b[c] for c in KEY + ['voting_place']})
    for t in ('t1', 't2'):
        d[f'{t}_X'] = b[f'{t}_A']
        d[f'{t}_Y'] = b[f'{t}_B']
        for c in ('comp', 'aptos', 'validos', 'branco', 'nulo'):
            d[f'{t}_{c}'] = b[f'{t}_{c}']
    return pl.prepara(d)


def carrega_agregacao_bweb(ano, turno, con=None):
    """BWEB presidente por secao: aptos e no de secoes agregadas (DS_AGREGADAS; 2014 nao tem o campo -> NaN)."""
    import pyarrow.parquet as pq
    fs = sorted((R / 'bu' / f'{ano}-t{turno}').glob('*_PRESIDENTE.parquet'))
    names = pq.ParquetFile(fs[0]).schema_arrow.names
    col = next((c for c in ('DS_AGREGADAS', 'DS_SECOES_AGREGADAS') if c in names), None)
    con = con or duck()
    ag = (f"max(CASE WHEN {col} IS NULL OR {col} IN ('#NULO#', '#NE#', '') THEN 0 "
          f"ELSE len(regexp_extract_all({col}, '[0-9]+')) END)") if col else 'NULL'
    lista = '[' + ', '.join("'" + str(f).replace('\\', '/') + "'" for f in fs) + ']'
    q = f"""SELECT SG_UF AS uf, TRY_CAST(CD_MUNICIPIO AS INTEGER) AS municipality, TRY_CAST(NR_ZONA AS INTEGER) AS zone,
                   TRY_CAST(NR_SECAO AS INTEGER) AS section, max(TRY_CAST(QT_APTOS AS INTEGER)) AS aptos_bweb,
                   {ag} AS n_agregadas
            FROM read_parquet({lista}, union_by_name=true) GROUP BY ALL"""
    return con.execute(q).df()


def carrega_agregacao_2026(turno):
    """2026: secoes principais (que absorveram outras) a partir do inventario do C4 (cs.json do pacote de urna)."""
    p = Path(str(AGREG_2026).format(t=turno))
    if not p.exists():
        return None
    a = pd.read_csv(p, sep=';', decimal=',', encoding='utf-8-sig')
    a = a.dropna(subset=['secao_principal'])
    a['section'] = a.secao_principal.astype(int)
    return a.groupby(['uf', 'municipality', 'zone', 'section']).size().rename('n_agregadas').reset_index()


def flags_agregacao(ano, base_keys):
    """Por secao da base: n de agregadas no 1o e no 2o turno, e se a agregacao muda entre turnos.
    2014: sem campo (NaN, motivo); 2026: inventario C4 (cs.json); 2018/2022: BWEB DS_AGREGADAS."""
    k = base_keys[KEY].copy()
    if ano == 2026:
        for t in (1, 2):
            a = carrega_agregacao_2026(t)
            if a is None:
                k[f'n_agreg_t{t}'] = np.nan
                continue
            k = k.merge(a.rename(columns={'n_agregadas': f'n_agreg_t{t}'}), on=KEY, how='left')
            k[f'n_agreg_t{t}'] = k[f'n_agreg_t{t}'].fillna(0)
        k['fonte_agregacao'] = 'C4-02 cs.json 2026'
        extra = {}
    elif ano == 2014:
        k['n_agreg_t1'] = np.nan
        k['n_agreg_t2'] = np.nan
        k['fonte_agregacao'] = 'sem campo DS_AGREGADAS no BWEB 2014'
        extra = {}
    else:
        con = duck()
        extra = {}
        for t in (1, 2):
            a = carrega_agregacao_bweb(ano, t, con)
            extra[t] = a
            k = k.merge(a[KEY + ['n_agregadas']].rename(columns={'n_agregadas': f'n_agreg_t{t}'}), on=KEY, how='left')
        con.close()
        k['fonte_agregacao'] = f'BWEB {ano} DS_AGREGADAS'
    return k, extra


def secoes_t2_sem_t1(ano, base_keys):
    """Secoes do 2o turno (BWEB; 2026: secoes_t1_t2) que nao entraram na base por nao terem 1o turno: NOT_COMPARABLE."""
    if ano == 2026:
        s = pd.read_parquet(REL / 'verificacoes' / 'virada_1t_2t_2026' / 'secoes_t1_t2.parquet', columns=KEY + ['t1_stem', 't2_stem'])
        s = s[s.t2_stem.notna()]
        t2 = s[KEY]
    else:
        t2 = carrega_agregacao_bweb(ano, 2)[KEY]
    m = t2.merge(base_keys[KEY].drop_duplicates(), on=KEY, how='left', indicator=True)
    return m[m._merge == 'left_only'][KEY].assign(ano=ano, status=NOT_COMP, motivo='secao do 2o turno sem 1o turno na base')


# ----------------------------------------------------------------------------------------------- C5-01: calibracao
def modelo_terceiros(e, M=M_TERCEIROS):
    """Modelo do local com a fatia de terceiros do 1o turno: a secao repete X e Y do 1o turno e recebe uma fracao tau dos
    votos de terceiros (T = validos - X - Y), tau estimado nas OUTRAS secoes do predio com M votos a priori do municipio
    (deixando a propria secao de fora); depois o deslocamento logit residual das outras secoes do predio (comparecimento).
    Recebe e (secoes elegiveis do modelo_local, com t1_validos) e devolve (p previsto, z bruto) alinhados a e."""
    T = (e.t1_validos - e.t1_X - e.t1_Y).clip(lower=0).astype(float)
    num = (e.t2_X / e.n2) * (e.n1 + T) - e.t1_X
    mk = e.municipality.to_numpy()  # codigo TSE do municipio e unico no pais
    Nm, Tm = num.groupby(mk).transform('sum'), T.groupby(mk).transform('sum')
    tau_m = ((Nm - num) / (Tm - T).where(Tm - T > 0)).clip(0, 1).fillna(.5)
    Sn, ST = num.groupby(e.place).transform('sum'), T.groupby(e.place).transform('sum')
    tau = ((Sn - num + M * tau_m) / (ST - T + M)).clip(0, 1) if M > 0 else \
        ((Sn - num) / (ST - T).where(ST - T > 0)).clip(0, 1).fillna(tau_m)
    q = ((e.t1_X + tau * T + .5) / (e.n1 + T + 1)).clip(pl.EPS, 1 - pl.EPS)
    S2X, S2N = e.groupby('place').t2_X.transform('sum'), e.groupby('place').n2.transform('sum')
    qn = q * e.n2
    Sq = qn.groupby(e.place).transform('sum')
    sh = pl._lg(S2X - e.t2_X, S2N - e.n2) - logit(((Sq - qn) / (S2N - e.n2)).clip(pl.EPS, 1 - pl.EPS))
    p = np.clip(expit(logit(q) + sh), pl.EPS, 1 - pl.EPS)
    z = (e.t2_X - e.n2 * p) / np.sqrt(e.n2 * p * (1 - p))
    return p, z


def ajusta(d, M=M_TERCEIROS):
    """modelo_local (padroes_lib) + escalas: z_lib (com piso phi=1), z_livre (phi robusto sem piso), z_terc_livre."""
    e, phi_lib = pl.modelo_local(d)
    e['z_bruto'] = e.z * np.sqrt(phi_lib)
    phi_livre = phi_robusto(e.z_bruto)
    e['z_livre'] = e.z_bruto / np.sqrt(phi_livre)
    p_t, z_t = modelo_terceiros(e, M)
    e['p_terc'] = p_t
    e['z_terc_bruto'] = z_t
    phi_terc = phi_robusto(z_t)
    e['z_terc_livre'] = z_t / np.sqrt(phi_terc)
    e['terc_t1'] = ((e.t1_validos - e.t1_X - e.t1_Y).clip(lower=0) / e.t1_validos.where(e.t1_validos > 0)).fillna(0)
    return e, dict(phi_lib=phi_lib, phi_livre=phi_livre, phi_terc=phi_terc)


def sorteio_escalado(n, p, phi, rng):
    """Votos de X sorteados com variancia phi * binomial: beta-binomial se phi >= 1, binomial encolhida se phi < 1."""
    n = np.asarray(n)
    p = np.asarray(p)
    if phi >= 1:
        rho = np.clip((phi - 1) / np.maximum(n - 1, 1), 1e-9, .99)
        q = rng.beta(p * (1 / rho - 1), (1 - p) * (1 / rho - 1))
        return rng.binomial(n, q)
    x = rng.binomial(n, p)
    return np.clip(np.rint(n * p + np.sqrt(phi) * (x - n * p)), 0, n).astype(int)


def fora_simulado(n, p, phi, rng, R=R_SIM, lim=Z_LIM):
    """Contagens |z| > lim sob a referencia escalada (z = (x - n p) / sqrt(phi n p (1-p)))."""
    n, p = np.asarray(n), np.asarray(p)
    sd = np.sqrt(phi * n * p * (1 - p))
    return np.array([int((np.abs(sorteio_escalado(n, p, phi, rng) - n * p) / sd > lim).sum()) for _ in range(R)])


def permuta_dentro(grupo, rng):
    """Indice de permutacao dentro de cada grupo: v[perm] embaralha v so entre linhas do mesmo grupo."""
    g = np.asarray(grupo)
    o1 = np.argsort(g, kind='stable')
    o2 = np.lexsort((rng.random(len(g)), g))
    perm = np.empty(len(g), dtype=int)
    perm[o1] = o2
    return perm


def permuta_mudanca(e, rng):
    """Base sintetica: cada secao recebe a mudanca logit (1o -> 2o turno) de outra secao do mesmo predio, sorteada."""
    delta = (pl._lg(e.t2_X, e.n2) - pl._lg(e.t1_X, e.n1)).to_numpy()
    perm = permuta_dentro(e.place.to_numpy(), rng)
    x = np.clip(np.rint(e.n2 * expit(pl._lg(e.t1_X, e.n1).to_numpy() + delta[perm])), 0, e.n2).astype(int)
    s = e[['place', 't1_X', 't1_Y', 'n1', 'n2']].copy()
    s['t2_X'] = x
    s['t2_Y'] = s.n2 - x
    return s


def referencia_permutacao(e, rng, R=R_PERM, lim=Z_LIM):
    """fora4 sob permutacao da mudanca dentro do predio, refazendo o modelo_local em cada replica."""
    out = []
    for _ in range(R):
        s = permuta_mudanca(e, rng)
        es, phi = pl.modelo_local(s)
        zb = es.z * np.sqrt(phi)
        out.append(dict(fora_livre=int((np.abs(zb) / np.sqrt(phi_robusto(zb)) > lim).sum()), fora_lib=int((np.abs(es.z) > lim).sum()),
                        phi_livre=phi_robusto(zb), secoes=len(es)))
    return pd.DataFrame(out)


def dispersao_calibrada(e, col_p='p_full'):
    """Teste de dispersao do predio (estatistica 'ganho' do padroes_lib) com e sem escala: o fator phi_disp e a mediana de
    r/mediana_chi2(df) entre os locais; calibrado, cada cauda deveria ter ~1% dos locais."""
    g = e.groupby('place')
    df = g.size() - 1
    r = ((e.t2_X - e.n2 * e[col_p]) ** 2 / (e.n2 * e[col_p] * (1 - e[col_p]))).groupby(e.place).sum()
    phi_disp = float(np.median(r / stats.chi2.ppf(.5, df)))
    o = dict(locais=int(len(df)), phi_disp=phi_disp)
    for nome, x in (('lib', r), ('calibrado', r / phi_disp)):
        o[f'pct_uniforme_demais_{nome}'] = 100 * float((stats.chi2.cdf(x, df) < .01).mean())
        o[f'pct_disperso_demais_{nome}'] = 100 * float((stats.chi2.sf(x, df) < .01).mean())
    return o


def faixa_codigo(x, cortes, fmt='{:g}-{:g}'):
    """Codigo inteiro da faixa [a, b) de cada valor e os rotulos (sem criar strings por linha)."""
    lab = np.array([fmt.format(a, b) for a, b in zip(cortes[:-1], cortes[1:])] + ['fora'], dtype=object)
    c = np.searchsorted(np.asarray(cortes, float), np.asarray(x, float), side='right') - 1
    return np.where((c < 0) | (c >= len(cortes) - 1), len(cortes) - 1, c), lab


def estratos_fora(e, ano, lim=Z_LIM):
    """fora4 e variancia do z por estrato (tamanho, terceiros do 1o turno, aptos iguais entre turnos, agregacao)."""
    zl, zt, zb = e.z_livre.to_numpy(), e.z_terc_livre.to_numpy(), e.z.to_numpy()
    cods = {'faixa_n2': faixa_codigo(e.n2, FAIXAS_N2), 'faixa_terceiros_t1': faixa_codigo(e.terc_t1, FAIXAS_TERC),
            'aptos_t1_t2': ((e.t1_aptos != e.t2_aptos).to_numpy().astype(int), np.array(['iguais', 'diferentes'], dtype=object))}
    if 'n_agreg_t1' in e:
        a1, a2 = e.n_agreg_t1.to_numpy(float), e.n_agreg_t2.to_numpy(float)
        c = np.select([np.isnan(a1) | np.isnan(a2), a1 != a2, a2 > 0], [0, 1, 2], 3)
        cods['agregacao'] = (c, np.array(['sem informacao', 'muda entre turnos', 'principal (igual nos turnos)', 'sem agregacao'],
                                         dtype=object))
    rows = []
    for tipo, (c, lab) in cods.items():
        G = len(lab)

        def bc(w):
            return np.bincount(c, weights=np.asarray(w, float), minlength=G)
        n = bc(np.ones(len(c)))
        t = pd.DataFrame(dict(ano=ano, estrato_tipo=tipo, estrato=lab, secoes=n, var_z_livre=bc(zl ** 2) / np.maximum(n, 1),
                              var_z_terc_livre=bc(zt ** 2) / np.maximum(n, 1), fora4_lib=bc(np.abs(zb) > lim),
                              fora4_livre=bc(np.abs(zl) > lim), fora4_terc_livre=bc(np.abs(zt) > lim)))
        t['fora4_lib_por_10mil'] = 1e4 * t.fora4_lib / t.secoes.clip(lower=1)
        t['fora4_terc_livre_por_10mil'] = 1e4 * t.fora4_terc_livre / t.secoes.clip(lower=1)
        rows.append(t[t.secoes > 0])
    return pd.concat(rows, ignore_index=True)


def c5_01_calibracao(d, ano, rng, R=R_SIM, R_perm=R_PERM):
    """Uma eleicao: referencias de fora4 (R0 lib, R1 phi livre, R2 permutacao, R3 normal, R4 modelo com terceiros),
    universo original (como padroes_2t) e universo do protocolo (sem ZZ, aptos >= 50), dispersao calibrada e estratos."""
    linhas, disp, estr = [], [], None
    e_orig = None
    for universo in ('protocolo', 'original'):
        prot = d.prot if 'prot' in d else (d.uf != 'ZZ') & (d.t2_aptos >= MIN_APTOS_PROTOCOLO)
        e, ph = ajusta(d if universo == 'original' else d[prot])
        del prot
        N = len(e)
        base = dict(ano=ano, universo=universo, secoes_no_modelo=N, phi_lib=ph['phi_lib'], phi_livre=ph['phi_livre'],
                    phi_terc=ph['phi_terc'], var_z_bruto=float(e.z_bruto.var()), curtose_z=float(stats.kurtosis(e.z_bruto)),
                    var_z_terc_bruto=float(e.z_terc_bruto.var()), curtose_z_terc=float(stats.kurtosis(e.z_terc_bruto)))
        o, _ = pl.trocas(e, ph['phi_lib'], rng, R=R)
        linhas.append(base | dict(modelo='local (padroes_lib)', referencia='R0 beta-binomial com piso phi=1 (padroes_lib)',
                                  fora4_obs=o['fora4_obs'], fora4_ref=o['fora4_sim'], fora4_ref_p95=np.nan))
        sim = fora_simulado(e.n2, e.p_loo, ph['phi_livre'], rng, R)
        linhas.append(base | dict(modelo='local (padroes_lib)', referencia='R1 phi livre (sem piso)',
                                  fora4_obs=int((e.z_livre.abs() > Z_LIM).sum()), fora4_ref=float(sim.mean()),
                                  fora4_ref_p95=float(np.percentile(sim, 95))))
        pr = referencia_permutacao(e, rng, R_perm)
        linhas.append(base | dict(modelo='local (padroes_lib)', referencia='R2 permutacao da mudanca dentro do predio (phi livre)',
                                  fora4_obs=int((e.z_livre.abs() > Z_LIM).sum()), fora4_ref=float(pr.fora_livre.mean()),
                                  fora4_ref_p95=float(np.percentile(pr.fora_livre, 95)), phi_ref=float(pr.phi_livre.mean())))
        linhas.append(base | dict(modelo='local (padroes_lib)', referencia='R3 normal (2*Phi(-4)*N)',
                                  fora4_obs=int((e.z_livre.abs() > Z_LIM).sum()), fora4_ref=float(2 * stats.norm.sf(Z_LIM) * N),
                                  fora4_ref_p95=np.nan))
        sim = fora_simulado(e.n2, e.p_terc, ph['phi_terc'], rng, R)
        linhas.append(base | dict(modelo=f'local com terceiros do 1o turno (M={M_TERCEIROS})', referencia='R1 phi livre (sem piso)',
                                  fora4_obs=int((e.z_terc_livre.abs() > Z_LIM).sum()), fora4_ref=float(sim.mean()),
                                  fora4_ref_p95=float(np.percentile(sim, 95))))
        disp.append(dict(ano=ano, universo=universo) | dispersao_calibrada(e))
        if universo == 'original':
            e_orig = e
            estr = estratos_fora(e, ano)
        else:
            del e
            gc.collect()
    t = pd.DataFrame(linhas)
    t['razao_obs_ref'] = t.fora4_obs / t.fora4_ref.clip(lower=1)
    t['fora4_obs_por_10mil'] = 1e4 * t.fora4_obs / t.secoes_no_modelo
    return t, pd.DataFrame(disp), estr, e_orig


def grade_terceiros(e, ano, grade=M_GRADE):
    """Sensibilidade do modelo com terceiros ao peso M (mesma grade nas 4 eleicoes)."""
    rows = []
    for M in grade:
        _, z = modelo_terceiros(e, M)
        phi = phi_robusto(z)
        rows.append(dict(ano=ano, M=M, var_z_bruto=float(z.var()), phi_livre=phi, curtose=float(stats.kurtosis(z)),
                         fora4_livre=int((np.abs(z) / np.sqrt(phi) > Z_LIM).sum()), secoes=len(z),
                         fora4_por_10mil=1e4 * float((np.abs(z) / np.sqrt(phi) > Z_LIM).mean())))
    return pd.DataFrame(rows)


def status_secoes(d, e, ano):
    """Status por secao da base (d preparado, com n1/n2): IN_MODEL ou NOT_COMPARABLE com motivo (n < 30 em X+Y num turno;
    predio com < 3 secoes elegiveis)."""
    s = d[KEY + ['voting_place']].copy()
    s['ano'] = ano
    s['universo_protocolo'] = (d.uf != 'ZZ') & (d.t2_aptos >= MIN_APTOS_PROTOCOLO)
    inm = s.index.isin(e.index)  # e herda o indice de d
    s['status'] = pd.Categorical(np.where(inm, 'IN_MODEL', NOT_COMP))
    s['motivo'] = pd.Categorical(np.select([inm, (d.n1 < pl.MIN_N) | (d.n2 < pl.MIN_N)],
                                           ['', f'menos de {pl.MIN_N} votos nos finalistas num dos turnos'],
                                           'local de votacao com menos de 3 secoes elegiveis (sem vizinhas)'))
    return s


# ----------------------------------------------------------------------------------------------- C5-09: causas dos outliers
def c5_09_causas(o):
    """Causa provavel de cada secao fora do modelo (|z_lib| > 4), na ordem: eleitorado/agregacao diferente entre turnos,
    absorvida pelo modelo com terceiros (|z_terc_livre| < 4), secao pequena (n2 < 100), restante."""
    o = o.copy()
    agr_muda = (o.n_agreg_t1.notna() & o.n_agreg_t2.notna() & (o.n_agreg_t1 != o.n_agreg_t2)) if 'n_agreg_t1' in o else False
    apt_muda = (o.t1_aptos - o.t2_aptos).abs() > .05 * o.t2_aptos
    o['causa'] = np.select(
        [agr_muda | apt_muda, o.z_terc_livre.abs() < Z_LIM, o.n2 < 100],
        ['eleitorado ou agregacao diferente entre turnos', 'absorvida pelo modelo com terceiros do 1o turno',
         'secao pequena (n2 < 100)'], 'nao absorvida (restante)')
    return o


def terceiro_principal(b_rows, cols_terc):
    """Candidato de terceiros com mais votos no 1o turno na secao e sua fatia dos validos."""
    if not cols_terc:
        return pd.Series('', index=b_rows.index), pd.Series(0.0, index=b_rows.index)
    m = b_rows[cols_terc]
    top = m.idxmax(axis=1).str.replace('t1_v', '', regex=False)
    return top, m.max(axis=1) / b_rows.t1_validos.where(b_rows.t1_validos > 0)


# ----------------------------------------------------------------------------------------------- C5-03: branco/nulo
def loo_nivel(k, n, place):
    """Fatia das OUTRAS secoes do predio (deixa a propria de fora) e z binomial da secao."""
    Sk = k.groupby(place).transform('sum')
    Sn = n.groupby(place).transform('sum')
    p = ((Sk - k + .5) / (Sn - n + 1)).clip(1e-4, 1 - 1e-4)
    z = (k - n * p) / np.sqrt(n * p * (1 - p))
    return p, z


def loo_mudanca(k1, n1, k2, n2, place):
    """Modelo do local aplicado a k/n: o proprio 1o turno + a mudanca logit das outras secoes do predio."""
    S1k, S1n = k1.groupby(place).transform('sum'), n1.groupby(place).transform('sum')
    S2k, S2n = k2.groupby(place).transform('sum'), n2.groupby(place).transform('sum')
    p = np.clip(expit(pl._lg(k1, n1) + pl._lg(S2k - k2, S2n - n2) - pl._lg(S1k - k1, S1n - n1)), pl.EPS, 1 - pl.EPS)
    return p, (k2 - n2 * p) / np.sqrt(n2 * p * (1 - p))


def p_zero_betabin(n, p, phi):
    """P(k = 0) numa beta-binomial com media p e sobredispersao phi (phi <= 1 -> binomial)."""
    n, p = np.asarray(n, float), np.asarray(p, float)
    if phi <= 1:
        return (1 - p) ** n
    rho = np.clip((phi - 1) / np.maximum(n - 1, 1), 1e-9, .99)
    a, b = p * (1 / rho - 1), (1 - p) * (1 / rho - 1)
    return np.exp(betaln(a, b + n) - betaln(a, b))


def elegiveis_bn(d, cols_n, min_comp=MIN_COMP_BN):
    m = np.ones(len(d), bool)
    for c in cols_n:
        m &= (d[c] >= min_comp).to_numpy()
    x = d[m]
    k = x.groupby('place').place.transform('size').to_numpy()
    return x[k >= 3]


def cruzamento_bn(m, ano):
    """Correlacao do z da mudanca de branco+nulo (z_bn) com o z do modelo do predio para A (z_livre) e com a variacao de
    comparecimento (dcomp, p.p.); media de z_livre nas secoes com |z_bn| >= 4."""
    lo, hi = m.z_bn < -Z_LIM, m.z_bn > Z_LIM
    return dict(ano=ano, secoes=len(m), corr_zbn_zA=float(np.corrcoef(m.z_bn, m.z_livre)[0, 1]),
                corr_zbn_dcomp=float(np.corrcoef(m.z_bn, m.dcomp)[0, 1]),
                spearman_zbn_zA=float(stats.spearmanr(m.z_bn, m.z_livre).statistic),
                media_zA_bn_baixo4=float(m.z_livre[lo].mean()) if lo.any() else np.nan,
                media_zA_bn_alto4=float(m.z_livre[hi].mean()) if hi.any() else np.nan,
                n_bn_baixo4=int(lo.sum()), n_bn_alto4=int(hi.sum()))


def c5_03_branco_nulo(d, ano, e_pt=None, devolve_z=False):
    """Branco+nulo (e branco, nulo separados) contra o predio: nivel por turno e mudanca 1o -> 2o; zeros obs x esperados.
    Devolve (resumo, por_uf, destoantes, zeros, cruzamento) e, com devolve_z, o quadro z_bn/dcomp por secao (indice de d)."""
    d = d[(d.uf != 'ZZ') & (d.t2_aptos >= MIN_APTOS_PROTOCOLO)]
    resumo, por_uf, dest, zeros = [], [], [], []
    for t in ('t1', 't2'):
        x = elegiveis_bn(d, [f'{t}_comp'])
        for medida, kcol in (('branco+nulo', None), ('branco', f'{t}_branco'), ('nulo', f'{t}_nulo')):
            k = (x[f'{t}_branco'] + x[f'{t}_nulo']) if kcol is None else x[kcol]
            n = x[f'{t}_comp']
            p, z = loo_nivel(k, n, x.place)
            phi_r, phi_p = phi_robusto(z), float(np.mean(np.clip(z, -50, 50) ** 2))
            zl = z / np.sqrt(phi_r)
            row = dict(ano=ano, turno=t, modelo='nivel (predio, deixa a secao de fora)', medida=medida, secoes_no_modelo=len(x),
                       total_k=int(k.sum()), total_comp=int(n.sum()), pct_k=100 * float(k.sum() / n.sum()),
                       mediana_pct_secao=100 * float((k / n).median()), phi_robusto=phi_r, phi_pearson=phi_p,
                       fora4_alto=int((zl > Z_LIM).sum()), fora4_baixo=int((zl < -Z_LIM).sum()),
                       fora4_ref_normal=float(2 * stats.norm.sf(Z_LIM) * len(x)))
            if medida == 'branco+nulo':
                mz = (n >= MIN_COMP_ZERO).to_numpy()
                z0 = mz & (k == 0).to_numpy()
                p0b = (1 - p.to_numpy()) ** n.to_numpy()
                p0bb = p_zero_betabin(n.to_numpy(), p.to_numpy(), phi_p)
                row |= dict(secoes_comp_100=int(mz.sum()), zeros_obs=int(z0.sum()), zeros_esp_binomial=float(p0b[mz].sum()),
                            zeros_esp_betabin=float(p0bb[mz].sum()), zeros_p0_betabin_menor_1e4=int((z0 & (p0bb < 1e-4)).sum()))
                zla, pa, ka = zl.to_numpy(), p.to_numpy(), k.to_numpy()
                cu, lu = pd.factorize(x.uf)
                G = len(lu)

                def bc(w):
                    return np.bincount(cu, weights=np.asarray(w, float), minlength=G)
                por_uf.append(pd.DataFrame(dict(ano=ano, turno=t, uf=np.asarray(lu, dtype=object), secoes_no_modelo=bc(np.ones(len(cu))),
                                                pct_bn=100 * bc(ka) / bc(n.to_numpy()), secoes_comp_100=bc(mz), zeros_obs=bc(z0),
                                                zeros_esp_binomial=bc(np.where(mz, p0b, 0)), zeros_esp_betabin=bc(np.where(mz, p0bb, 0)),
                                                fora4_alto=bc(zla > Z_LIM), fora4_baixo=bc(zla < -Z_LIM))))
                zz = x[z0]
                zeros.append(zz[KEY + ['voting_place', f'{t}_comp', f'{t}_aptos']].rename(columns={f'{t}_comp': 'comp', f'{t}_aptos': 'aptos'})
                             .assign(ano=ano, turno=t, fatia_bn_predio=pa[z0], p0_binomial=p0b[z0], p0_betabin=p0bb[z0],
                                     z_nivel_livre=zla[z0]))
                mo = np.abs(zla) >= Z_LIM
                o = x[mo]
                dest.append(o[KEY + ['voting_place', f'{t}_comp']].rename(columns={f'{t}_comp': 'comp'})
                            .assign(ano=ano, turno=t, modelo='nivel', branco_nulo=ka[mo], fatia_predio=pa[mo], z_livre=zla[mo]))
            resumo.append(row)
    # mudanca 1o -> 2o turno
    x = elegiveis_bn(d, ['t1_comp', 't2_comp'])
    k1, k2 = x.t1_branco + x.t1_nulo, x.t2_branco + x.t2_nulo
    p, z = loo_mudanca(k1, x.t1_comp, k2, x.t2_comp, x.place)
    phi_r = phi_robusto(z)
    zl = z / np.sqrt(phi_r)
    resumo.append(dict(ano=ano, turno='t1->t2', modelo='mudanca (proprio 1o turno + mudanca das outras secoes do predio)',
                       medida='branco+nulo', secoes_no_modelo=len(x), total_k=int(k2.sum()), total_comp=int(x.t2_comp.sum()),
                       pct_k=100 * float(k2.sum() / x.t2_comp.sum()), mediana_pct_secao=100 * float((k2 / x.t2_comp).median()),
                       phi_robusto=phi_r, phi_pearson=float(np.mean(np.clip(z, -50, 50) ** 2)),
                       fora4_alto=int((zl > Z_LIM).sum()), fora4_baixo=int((zl < -Z_LIM).sum()),
                       fora4_ref_normal=float(2 * stats.norm.sf(Z_LIM) * len(x)), queda_bn_total=int(k1.sum() - k2.sum())))
    o = x[np.abs(zl) >= Z_LIM]
    dest.append(o[KEY + ['voting_place', 't2_comp']].rename(columns={'t2_comp': 'comp'})
                .assign(ano=ano, turno='t1->t2', modelo='mudanca', branco_nulo=(o.t2_branco + o.t2_nulo).to_numpy(),
                        branco_nulo_t1=(o.t1_branco + o.t1_nulo).to_numpy(), fatia_predio=p[np.abs(zl) >= Z_LIM].to_numpy(),
                        z_livre=zl[np.abs(zl) >= Z_LIM].to_numpy()))
    zbn = pd.DataFrame({'z_bn': zl, 'dcomp': 100 * (x.t2_comp / x.t2_aptos - x.t1_comp / x.t1_aptos)})
    cruz = {}
    if e_pt is not None:
        cruz = cruzamento_bn(zbn.join(e_pt[['z_livre']], how='inner'), ano)  # mesmo indice (o de d)
    out = (pd.DataFrame(resumo), pd.concat(por_uf, ignore_index=True), pd.concat(dest, ignore_index=True),
           pd.concat(zeros, ignore_index=True), pd.DataFrame([cruz]) if cruz else pd.DataFrame())
    return out + (zbn,) if devolve_z else out


# ----------------------------------------------------------------------------------------------- C5-06: ultimo digito
def sorteia_contagem(x, n, kind, rng):
    """Referencia suave: binomial(n, x/n) por secao (votos, comparecimento) ou normal(x, sqrt(x)) arredondada (aptos)."""
    if kind == 'binomial':
        p = np.where(n > 0, x / np.maximum(n, 1), 0)
        return rng.binomial(n, np.clip(p, 0, 1))
    return np.maximum(np.rint(x + rng.normal(0, np.sqrt(np.maximum(x, 1)))), 0).astype(int)


def digitos_referencia(x, n, grupo, n_grupos, kind, rng, R=R_DIG, minimo=MIN_CONTAGEM_DIG):
    """Histograma do ultimo digito (contagens >= minimo) por grupo: observado (G x 10) e R replicas simuladas (R x G x 10)."""
    x, n, grupo = np.asarray(x).astype(int), np.asarray(n).astype(int), np.asarray(grupo).astype(int)

    def hist(v):
        m = v >= minimo
        return np.bincount(grupo[m] * 10 + v[m] % 10, minlength=n_grupos * 10).reshape(n_grupos, 10)
    obs = hist(x)
    sims = np.empty((R, n_grupos, 10))
    for r in range(R):
        sims[r] = hist(sorteia_contagem(x, n, kind, rng))
    return obs, sims


def testa_digitos(o, s):
    """Um grupo: o (10,), s (R, 10). chi2 contra a media simulada, p empirico, p com escala calibrada pelas replicas,
    p do teste antigo contra uniforme, z por digito, excesso de multiplos de 10 e de 5 (digitos 0 e 5)."""
    R = s.shape[0]
    m = s.mean(axis=0)
    tot = o.sum()
    if tot == 0 or (m <= 0).any():
        return None
    chi_obs = float(((o - m) ** 2 / m).sum())
    mloo = (R * m - s) / (R - 1)
    chi_r = ((s - mloo) ** 2 / np.where(mloo > 0, mloo, 1)).sum(axis=1)
    esc = float(chi_r.mean() / 9)
    sd = s.std(axis=0, ddof=1)
    z = (o - m) / np.where(sd > 0, sd, np.nan)
    m10, s10 = s[:, 0], s[:, 0] + s[:, 5]
    out = dict(n_contagens=int(tot), chi2_obs=chi_obs, chi2_ref_media=float(chi_r.mean()), escala=esc,
               p_empirico=float((1 + (chi_r >= chi_obs).sum()) / (R + 1)), p_calibrado=float(stats.chi2.sf(chi_obs / max(esc, 1e-9), 9)),
               p_uniforme_antigo=float(stats.chisquare(o).pvalue), desvio_max_pp_vs_ref=float(100 * np.abs(o - m).max() / tot),
               desvio_max_pp_vs_uniforme=float(100 * np.abs(o / tot - .1).max()),
               mult10_obs=int(o[0]), mult10_ref=float(m[0]), mult10_z=float((o[0] - m10.mean()) / max(m10.std(ddof=1), 1e-9)),
               mult5_obs=int(o[0] + o[5]), mult5_ref=float(m[0] + m[5]),
               mult5_z=float((o[0] + o[5] - s10.mean()) / max(s10.std(ddof=1), 1e-9)))
    for k in range(10):
        out[f'obs_d{k}'] = int(o[k])
        out[f'ref_d{k}'] = float(m[k])
        out[f'z_d{k}'] = float(z[k])
    return out


def fracoes_exatas(x, v, rng, R=R_DIG, fracoes=FRACOES, minimo=MIN_VALIDOS_FRACAO):
    """Secoes cuja fatia x/v e exatamente uma fracao simples (1/2, 2/3, ...): observado x referencia binomial(v, x/v)."""
    x, v = np.asarray(x).astype(int), np.asarray(v).astype(int)
    ok = v >= minimo
    x, v = x[ok], v[ok]

    def conta(xx):
        return np.array([int(((xx * b) == (a * v)).sum()) for a, b in fracoes])
    o = conta(x)
    p = np.where(v > 0, x / np.maximum(v, 1), 0)
    s = np.array([conta(rng.binomial(v, p)) for _ in range(R)])
    rows = []
    for i, (a, b) in enumerate(fracoes):
        sd = s[:, i].std(ddof=1)
        rows.append(dict(fracao=f'{a}/{b}', obs=int(o[i]), ref=float(s[:, i].mean()), z=float((o[i] - s[:, i].mean()) / sd) if sd > 0 else np.nan))
    rows.append(dict(fracao='todas', obs=int(o.sum()), ref=float(s.sum(axis=1).mean()),
                     z=float((o.sum() - s.sum(axis=1).mean()) / max(s.sum(axis=1).std(ddof=1), 1e-9))))
    return pd.DataFrame(rows).assign(secoes=int(ok.sum()))


def series_digitos(b):
    """(nome, coluna x, coluna n, tipo) de cada serie de contagens por secao numa base de presidente."""
    out = []
    for t in ('t1', 't2'):
        for c in ['A', 'B'] + ([c[3:] for c in b if c.startswith('t1_v') and c[4:].isdigit()] if t == 't1' else []) + ['branco', 'nulo']:
            out.append((f'{t}_{c}', f'{t}_{c}', f'{t}_comp', 'binomial'))
        out.append((f'{t}_comp', f'{t}_comp', f'{t}_aptos', 'binomial'))
        out.append((f'{t}_aptos', f'{t}_aptos', f'{t}_aptos', 'normal'))
    return out


def c5_06_digitos(b, ano, rng, R=R_DIG):
    """Ultimo digito de todas as series (nacional e por UF) contra referencia simulada; fracoes exatas da fatia de A."""
    b = b[(b.uf != 'ZZ') & (b.t2_aptos >= MIN_APTOS_PROTOCOLO)]
    ufs = sorted(b.uf.unique())
    g = b.uf.map({u: i for i, u in enumerate(ufs)}).to_numpy()
    nac, puf, ref = [], [], []
    # so contagens >= 100: abaixo disso a referencia "em torno do valor observado" alarga a distribuicao (vies de forma,
    # medido no teste sintetico) e a referencia por modelo depende da especificacao; branco/nulo ficam com o C5-03 (zeros)
    for minimo, RR in ((MIN_CONTAGEM_DIG, R),):
        for nome, cx, cn, kind in series_digitos(b):
            o, s = digitos_referencia(b[cx], b[cn], g, len(ufs), kind, rng, RR, minimo)
            refn = f'{kind} em torno do valor observado'
            r = testa_digitos(o.sum(axis=0), s.sum(axis=1))
            if r:
                nac.append(dict(ano=ano, serie=nome, minimo=minimo, referencia=refn) | r)
                ref.append(dict(ano=ano, serie=nome, minimo=minimo, referencia=refn, replicas=RR) |
                           {f'ref_d{k}': float(s.sum(axis=1)[:, k].mean()) for k in range(10)} |
                           {f'ref_sd_d{k}': float(s.sum(axis=1)[:, k].std(ddof=1)) for k in range(10)})
            for i, uf in enumerate(ufs):
                r = testa_digitos(o[i], s[:, i])
                if r and r['n_contagens'] >= 200:
                    puf.append(dict(ano=ano, uf=uf, serie=nome, minimo=minimo) |
                               {k: v for k, v in r.items() if not k.startswith(('obs_d', 'ref_d'))})
    fr = []
    for t in ('t1', 't2'):
        f = fracoes_exatas(b[f'{t}_A'], b[f'{t}_validos'] if t == 't1' else b.t2_A + b.t2_B, rng, R)
        fr.append(f.assign(ano=ano, serie=f'{t}_A sobre {"validos" if t == "t1" else "A+B"}'))
    return pd.DataFrame(nac), pd.DataFrame(puf), pd.DataFrame(ref), pd.concat(fr, ignore_index=True)


# ----------------------------------------------------------------------------------------------- C5-12: picos
def histogramas_picos(e, phi, rng, R=10):
    """Reproduz padroes_lib.amontoamento (mesma ordem de sorteios) e devolve os arrays: bordas, obs, sim medio, z e sims."""
    ok = (e.t1_X >= 20).to_numpy()
    b1 = np.arange(.5, 4.0001, .005)
    b2 = np.arange(0, 1.0001, .002)
    x1, n2 = e.t1_X.to_numpy()[ok], e.n2.to_numpy()
    o1 = np.histogram(e.t2_X.to_numpy()[ok] / x1, b1)[0]
    o2 = np.histogram(e.t2_X / e.n2, b2)[0]
    s1, s2 = np.zeros(len(b1) - 1), np.zeros(len(b2) - 1)
    xs = []
    for _ in range(R):
        x = pl.simula(e, phi, rng)
        xs.append(x.astype(np.int32))
        s1 += np.histogram(x[ok] / x1, b1)[0] / R
        s2 += np.histogram(x / n2, b2)[0] / R
    return dict(razao=(b1, o1, s1, pl._picos(o1, s1), ok), fatia=(b2, o2, s2, pl._picos(o2, s2), np.ones(len(e), bool))), xs


def localiza_pico(e, xs, serie, b, z, ok, i):
    """Secoes no bin i de uma serie: observado x simulado por UF e por faixa de n2; pares de contagem repetidos."""
    lo, hi = b[i], b[i + 1]
    t2x = e.t2_X.to_numpy()[ok]
    n2 = e.n2.to_numpy()[ok]
    den = e.t1_X.to_numpy()[ok] if serie == 'razao' else n2
    v = t2x / den
    m = (v >= lo) & (v < hi)
    sel = e.loc[e.index[ok][m]]
    S = np.zeros(len(v))   # vezes (0..R) que cada secao caiu no bin nas replicas
    tot_sim = []
    for x in xs:
        vv = x[ok] / den
        h = (vv >= lo) & (vv < hi)
        S += h
        tot_sim.append(int(h.sum()))
    cu, lu = pd.factorize(e.uf.to_numpy()[ok])
    uf_sim = pd.Series(np.bincount(cu, weights=S, minlength=len(lu)) / len(xs), index=lu)
    uf_obs = pd.Series(np.bincount(cu[m], minlength=len(lu)), index=lu)
    cn, ln = faixa_codigo(n2, FAIXAS_N2)
    n_sim = pd.Series(np.bincount(cn, weights=S, minlength=len(ln)) / len(xs), index=ln)
    n_obs = pd.Series(np.bincount(cn[m], minlength=len(ln)), index=ln)
    por_uf = pd.DataFrame({'obs': uf_obs, 'sim': uf_sim}).fillna(0)
    por_uf = por_uf[(por_uf.obs > 0) | (por_uf.sim > 0)]
    por_n = pd.DataFrame({'obs': n_obs, 'sim': n_sim}).fillna(0)
    por_n = por_n[(por_n.obs > 0) | (por_n.sim > 0)]
    pares = (sel.t2_X.astype(str) + '/' + (sel.t1_X if serie == 'razao' else sel.n2).astype(str)).value_counts()
    resumo = dict(serie=serie, bin_ini=float(lo), bin_fim=float(hi), z_pico=float(z[i]), obs=int(m.sum()), sim=float(np.mean(tot_sim)),
                  municipios=int(sel[['uf', 'municipality']].drop_duplicates().shape[0]), locais=int(sel.place.nunique()),
                  pares_distintos=int(len(pares)), par_mais_comum=pares.index[0] if len(pares) else '',
                  par_mais_comum_n=int(pares.iloc[0]) if len(pares) else 0,
                  uf_maior_excesso=str((por_uf.obs - por_uf.sim).idxmax()) if len(por_uf) else '',
                  uf_maior_excesso_obs=int((por_uf.obs).loc[(por_uf.obs - por_uf.sim).idxmax()]) if len(por_uf) else 0,
                  uf_maior_excesso_sim=float((por_uf.sim).loc[(por_uf.obs - por_uf.sim).idxmax()]) if len(por_uf) else 0,
                  n2_mediana=float(sel.n2.median()) if len(sel) else np.nan, n2_mediana_geral=float(np.median(n2)))
    return resumo, por_uf.reset_index(names='uf'), por_n.reset_index(names='faixa_n2'), sel


def c5_12_picos(d, ano, top=3):
    """Picos de razao e de fatia (rng = seed do padroes_aberta: o ano), maiores z por serie, localizados."""
    rng = np.random.default_rng(ano)
    e, phi = pl.modelo_local(d)
    pl.trocas(e, phi, rng)  # consome os sorteios na mesma ordem do padroes_lib.todos
    h, xs = histogramas_picos(e, phi, rng)
    res, ufs, ns, secs = [], [], [], []
    for serie, (b, o, s, z, ok) in h.items():
        zz = np.where(np.isfinite(z), z, -np.inf)
        for rank, i in enumerate(np.argsort(-zz)[:top], 1):
            r, pu, pn, sel = localiza_pico(e, xs, serie, b, z, ok, i)
            res.append(dict(ano=ano, rank=rank) | r)
            ufs.append(pu.assign(ano=ano, serie=serie, rank=rank, bin_ini=float(b[i])))
            ns.append(pn.assign(ano=ano, serie=serie, rank=rank, bin_ini=float(b[i])))
            if rank == 1:
                secs.append(sel[KEY + ['voting_place', 't1_X', 't1_Y', 't2_X', 't2_Y', 'n2']].assign(ano=ano, serie=serie, bin_ini=float(b[i])))
    resumo = pd.DataFrame(res)
    resumo['max_z_serie'] = resumo.groupby('serie').z_pico.transform('max')
    return resumo, pd.concat(ufs, ignore_index=True), pd.concat(ns, ignore_index=True), pd.concat(secs, ignore_index=True)


# ----------------------------------------------------------------------------------------------- execucao
PARTES = CACHE / 'partes'
TODAS = ('C5-01', 'C5-03', 'C5-06', 'C5-09', 'C5-12')
# colunas que cada checagem leva (quadros estreitos: o modelo_local copia todas as colunas que recebe)
COLS_MOD = ['prot', 'municipality', 'place', 't1_X', 't1_Y', 't2_X', 't2_Y', 'n1', 'n2', 't1_validos', 't1_aptos', 't2_aptos',
            'n_agreg_t1', 'n_agreg_t2']
COLS_BN = KEY + ['voting_place', 'place'] + [f'{t}_{c}' for t in ('t1', 't2') for c in ('comp', 'aptos', 'branco', 'nulo')]
COLS_PK = KEY + ['voting_place', 'place', 't1_X', 't1_Y', 't2_X', 't2_Y', 'n1', 'n2']
PARTES_NOMES = ('cal', 'disp', 'estr', 'grade', 'status', 'c9', 'bn_res', 'bn_uf', 'bn_dest', 'bn_zero', 'bn_cruz', 'dig_nac',
                'dig_uf', 'dig_ref', 'dig_fr', 'pk', 'pk_uf', 'pk_n', 'pk_sec', 'quar')


def _resumo_merge(novo):
    p = OUT / 'C5_resumo.json'
    old = {}
    if p.exists():
        try:
            old = json.loads(p.read_text(encoding='utf-8'))
        except ValueError:
            old = {}
    old.setdefault('checagens', {}).update(novo)
    old['atualizado_em'] = dt.datetime.now(dt.timezone.utc).isoformat()
    old['protocolo'] = 'relatorios/verificacoes/varredura_forense/PROTOCOLO.md v1.0'
    old['aviso'] = 'descritivo - nao indica irregularidade por si so'
    p.write_text(json.dumps(old, ensure_ascii=False, indent=1, default=float), encoding='utf-8')


def fase_agregacao(anos=ANOS):
    """Fase 1 (so DuckDB, processo pequeno): flags de agregacao por secao e secoes do 2o turno sem 1o turno, por ano."""
    for ano in anos:
        bk = pd.read_parquet(BASES / f'base_{ano}.parquet', columns=KEY + ['t1_aptos', 't2_aptos'])
        flags, _ = flags_agregacao(ano, bk)
        ins = {f'research/padroes_2t/base_{ano}.parquet': sha_arquivo(BASES / f'base_{ano}.parquet')}
        grava_parquet(flags, CACHE / f'agregacao_{ano}.parquet', ins)
        grava_parquet(secoes_t2_sem_t1(ano, bk), CACHE / f'secoes_t2_sem_t1_{ano}.parquet', ins)
        print(ano, 'agregacao ok', flush=True)
        del bk, flags
        gc.collect()


def _parte(nome, ano, df):
    PARTES.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(df).copy()
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].map(lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else str(v))
    df.to_parquet(PARTES / f'{nome}_{ano}.parquet', index=False)


def roda_ano(ano, pedidas=TODAS):
    """Fase 2: todas as checagens de um ano (uma base na memoria); grava as partes em research/varredura_forense/C5/partes/."""
    t0 = time.time()
    rng = np.random.default_rng(SEED + ano)
    b = carrega_base(ano)
    q = invariantes_base(b, ano)
    _parte('quar', ano, q)
    quarentena('C5-01', q, 'invariante da base por secao (comp<=aptos, validos+branco+nulo=comp, A+B<=validos, >=0)')
    d = formato(b)
    gc.collect()
    flags = pd.read_parquet(CACHE / f'agregacao_{ano}.parquet', columns=KEY + ['n_agreg_t1', 'n_agreg_t2'])
    alinhado = len(flags) == len(b) and all((flags[c].to_numpy() == b[c].to_numpy()).all() for c in KEY)
    if not alinhado:  # o cache foi gravado na ordem da base; se nao estiver, junta pela chave
        flags = b[KEY].merge(flags, on=KEY, how='left')
    for c in ('n_agreg_t1', 'n_agreg_t2'):
        d[c] = flags[c].to_numpy()
    del flags
    # da base so fica o que o C5-09 usa (nome do municipio e terceiros do 1o turno); o C5-06 rele a base no fim
    b = b[KEY + ['voting_place', 'municipio', 't1_validos'] + [c for c in b if c.startswith('t1_v') and c[4:].isdigit()]]
    gc.collect()
    d['prot'] = (d.uf != 'ZZ') & (d.t2_aptos >= MIN_APTOS_PROTOCOLO)  # universo do protocolo (sem ZZ, aptos >= 50)
    e = o = zbn = None
    if 'C5-03' in pedidas:
        r = c5_03_branco_nulo(d[COLS_BN], ano, devolve_z=True)
        for k, v in zip(('bn_res', 'bn_uf', 'bn_dest', 'bn_zero'), r[:4]):
            _parte(k, ano, v)
        zbn = r[5]
        del r
        gc.collect()
        print(ano, 'C5-03', round(time.time() - t0), 's', flush=True)
    if {'C5-01', 'C5-09'} & set(pedidas):
        cal, disp, estr, e = c5_01_calibracao(d[COLS_MOD], ano, rng)
        _parte('cal', ano, cal)
        _parte('disp', ano, disp)
        _parte('estr', ano, estr)
        _parte('grade', ano, grade_terceiros(e, ano))
        st = status_secoes(d, e, ano)
        _parte('status', ano, st.groupby(['ano', 'universo_protocolo', 'status', 'motivo'], observed=True).size()
               .rename('secoes').reset_index())
        par = st.join(e[['z', 'z_livre', 'z_terc_livre', 'p_loo', 'p_terc', 'terc_t1']]).join(d[['n_agreg_t1', 'n_agreg_t2']])
        grava_parquet(par, CACHE / f'secoes_c5a_{ano}.parquet',
                      {f'research/padroes_2t/base_{ano}.parquet': sha_arquivo(BASES / f'base_{ano}.parquet'),
                       f'research/varredura_forense/C5/agregacao_{ano}.parquet': sha_arquivo(CACHE / f'agregacao_{ano}.parquet')})
        del par, st
        print(ano, 'C5-01', round(time.time() - t0), 's', flush=True)
    if 'C5-09' in pedidas and e is not None:
        o = c5_09_causas(e[e.z.abs() > Z_LIM])
        bo = b.loc[o.index]
        terc = [c for c in bo if c.startswith('t1_v') and c[4:].isdigit()]
        top, fat = terceiro_principal(bo, terc)
        o = o.assign(**{c: bo[c].to_numpy() for c in KEY + ['municipio', 'voting_place']}, terceiro_principal=top.to_numpy(),
                     fatia_terceiro_principal=fat.to_numpy())
        _parte('c9', ano, o[KEY + ['municipio', 'voting_place', 't1_X', 't1_Y', 't2_X', 't2_Y', 'n1', 'n2', 't1_aptos', 't2_aptos',
                                   't1_validos', 'terc_t1', 'terceiro_principal', 'fatia_terceiro_principal', 'n_agreg_t1',
                                   'n_agreg_t2', 'p_loo', 'z', 'z_livre', 'z_terc_livre', 'causa']].assign(ano=ano))
    if zbn is not None and e is not None:
        _parte('bn_cruz', ano, pd.DataFrame([cruzamento_bn(zbn.join(e[['z_livre']], how='inner'), ano)]))
    del e, o, zbn
    gc.collect()
    if 'C5-12' in pedidas:
        for k, v in zip(('pk', 'pk_uf', 'pk_n', 'pk_sec'), c5_12_picos(d[COLS_PK], ano)):
            _parte(k, ano, v)
        print(ano, 'C5-12', round(time.time() - t0), 's', flush=True)
    del d
    gc.collect()
    if 'C5-06' in pedidas:
        del b
        gc.collect()
        b = carrega_base(ano)
        b = b[[c for c in b if c not in ('municipio', 'regiao')]]
        for k, v in zip(('dig_nac', 'dig_uf', 'dig_ref', 'dig_fr'), c5_06_digitos(b, ano, rng)):
            _parte(k, ano, v)
        print(ano, 'C5-06', round(time.time() - t0), 's', flush=True)
    try:
        import psutil
        print(ano, 'pico de memoria MB', round(psutil.Process().memory_info().peak_wset / 1e6), flush=True)
    except (ImportError, AttributeError):
        pass


def _junta_partes(nome, anos):
    fs = [PARTES / f'{nome}_{a}.parquet' for a in anos if (PARTES / f'{nome}_{a}.parquet').exists()]
    xs = [x for x in (pd.read_parquet(f) for f in fs) if len(x)]
    return pd.concat(xs, ignore_index=True) if xs else pd.DataFrame()


def tabela_causas(c9):
    """C5-09: secoes fora do modelo por ano x UF x causa, com o sentido (a favor de A ou de B)."""
    tab = c9.groupby(['ano', 'uf', 'causa']).size().unstack('causa', fill_value=0)
    tab['total'] = tab.sum(axis=1)
    sentido = c9.assign(a_favor=np.where(c9.z > 0, 'A', 'B')).groupby(['ano', 'uf', 'a_favor']).size().unstack(fill_value=0)
    return tab.join(sentido.add_prefix('a_favor_')).fillna(0).reset_index()


def fase_junta(anos=ANOS, pedidas=TODAS):
    """Fase 3: junta as partes dos anos nos CSVs de saida e atualiza o C5_resumo.json (lista de arquivos)."""
    J = {k: _junta_partes(k, anos) for k in PARTES_NOMES}
    semt1 = [pd.read_parquet(CACHE / f'secoes_t2_sem_t1_{a}.parquet') for a in anos if (CACHE / f'secoes_t2_sem_t1_{a}.parquet').exists()]
    semt1 = pd.concat(semt1, ignore_index=True) if semt1 else pd.DataFrame()
    if not len(semt1):
        semt1 = pd.DataFrame(columns=KEY + ['ano', 'status', 'motivo'])
    arq = {}
    if len(J['cal']):
        arq['C5-01'] = [csv_out('C5-01_calibracao_referencias.csv', J['cal']), csv_out('C5-01_dispersao_calibrada.csv', J['disp']),
                        csv_out('C5-01_fora4_por_estrato.csv', J['estr']), csv_out('C5-01_grade_M_terceiros.csv', J['grade']),
                        csv_out('C5-01_status_secoes.csv', J['status']), csv_out('C5-01_secoes_t2_sem_t1.csv', semt1)]
    if len(J['c9']):
        c9 = J['c9']
        arq['C5-09'] = [csv_out('C5-09_secoes_fora_do_modelo_2014_2026.csv', c9), csv_out('C5-09_causas_por_uf.csv', tabela_causas(c9)),
                        csv_out('C5-09_causas_por_ano.csv', c9.groupby(['ano', 'causa']).size().rename('secoes').reset_index())]
    if len(J['bn_res']):
        arq['C5-03'] = [csv_out('C5-03_resumo_por_eleicao.csv', J['bn_res']), csv_out('C5-03_por_uf.csv', J['bn_uf']),
                        csv_out('C5-03_secoes_destoantes.csv', J['bn_dest']), csv_out('C5-03_zeros_secoes.csv', J['bn_zero']),
                        csv_out('C5-03_cruzamento_zA_comparecimento.csv', J['bn_cruz'])]
    if len(J['dig_nac']):
        n, u = J['dig_nac'], J['dig_uf']
        n['q_bh_familia'] = n.groupby(['ano', 'minimo']).p_calibrado.transform(lambda s: pd.Series(bh(s.to_numpy()), index=s.index))
        u['q_bh_familia'] = u.groupby(['ano', 'minimo']).p_calibrado.transform(lambda s: pd.Series(bh(s.to_numpy()), index=s.index))
        arq['C5-06'] = [csv_out('C5-06_ultimo_digito_nacional.csv', n), csv_out('C5-06_ultimo_digito_por_uf.csv', u),
                        csv_out('C5-06_referencia_simulada.csv', J['dig_ref']), csv_out('C5-06_fracoes_exatas.csv', J['dig_fr'])]
    if len(J['pk']):
        arq['C5-12'] = [csv_out('C5-12_picos.csv', J['pk']), csv_out('C5-12_picos_por_uf.csv', J['pk_uf']),
                        csv_out('C5-12_picos_por_faixa_n2.csv', J['pk_n']), csv_out('C5-12_secoes_no_pico_principal.csv', J['pk_sec'])]
    q = J['quar']
    csv_out('quarentena_c5a.csv', q if len(q) else pd.DataFrame(columns=KEY + ['ano', 'turno', 'reason']))
    _resumo_merge({k: {'arquivos': v} for k, v in arq.items()})
    return J


def main(argv=None):
    """Sem argumentos: fase de agregacao, um subprocesso por ano (em serie, para limitar a memoria) e a juncao.
    Subcomandos: agregacao | ano <ano> [checagens...] | junta; opcao --anos 2014,2018."""
    import subprocess
    argv = list(sys.argv[1:] if argv is None else argv)
    anos = ANOS
    if '--anos' in argv:
        i = argv.index('--anos')
        anos = tuple(int(a) for a in argv[i + 1].split(','))
        del argv[i:i + 2]
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    if argv and argv[0] == 'agregacao':
        return fase_agregacao(anos)
    if argv and argv[0] == 'ano':
        return roda_ano(int(argv[1]), tuple(argv[2:]) or TODAS)
    if argv and argv[0] == 'junta':
        return fase_junta(anos)
    pedidas = tuple(a for a in argv if a in TODAS) or TODAS
    fase_agregacao(anos)
    for ano in anos:
        subprocess.run([sys.executable, str(Path(__file__).resolve()), 'ano', str(ano), *pedidas], check=True)
    return fase_junta(anos, pedidas)


if __name__ == '__main__':
    main()
