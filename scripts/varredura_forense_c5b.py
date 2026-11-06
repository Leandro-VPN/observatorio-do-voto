"""Varredura forense, camada C5 parte B (padrões estatísticos entre seções): comparação simétrica com as vizinhas do
mesmo prédio para todos os candidatos, brancos, nulos e a margem A-B (C5-02), comparecimento presidente x governador na
mesma seção (C5-10), teste de >=5 p.p./|z|>=2 da varredura de fiscalização replicado nas 27 UFs e nos dois lados (C5-11) e
100% para um candidato / comparecimento = aptos no BWEB (C5-07, parte BWEB).

Funções puras (`residuo_predio`, `estima_rho`, `bh`, `bweb_para_secoes`, `compara_vizinhas`, `classifica_pres_gov`,
`marca_extremos`...) recebem arrays/DataFrames e não leem disco; os carregadores leem os parquet com projeção de colunas,
um arquivo por vez (por UF e pleito). `main()` roda tudo e grava relatorios/verificacoes/varredura_forense/C5/ (CSVs
`C5-XX_*.csv`, `C5b_resumo.json`, `quarentena_c5b.csv`; o `C5_resumo.json` recebe as entradas desta parte por id de
checagem); z por seção em research/varredura_forense/C5b/ (parquet + recibo .json). Importável sem efeito pesado.

Modelo do prédio (C5-02): para cada categoria c (candidato, branco, nulo) a fatia esperada da seção é a fatia das OUTRAS
seções elegíveis do mesmo local de votação (uf, município, zona, local; deixa-uma-de-fora), com >= 3 pares. A variância
é beta-binomial: n p (1-p) [1 + (n-1) rho] para a seção mais a incerteza da média dos pares; rho (e um fator phi < 1
quando há subdispersão) é estimado de forma robusta por pleito, UF e categoria, fazendo a mediana de r^2/D(rho) igual à
mediana do qui-quadrado com 1 g.l. A margem A-B usa x = votos A - votos B e a variância da diferença multinomial. A
referência das caudas (|z| >= 4) vem de simulação sob o nulo (todas as seções do prédio com a mesma fatia, mesma
dispersão rho, z recalculado com a mesma estimação), N_SIM réplicas. Multiplicidade: Benjamini-Hochberg a 5% por família
(pleito x categoria, país sem exterior; exterior em família própria). Seções isoladas só são listadas com |z| >= 4 e BH.

Protocolo: relatorios/verificacoes/varredura_forense/PROTOCOLO.md v1.0. Tudo é descritivo e exploratório: "diferença
acima do limiar" não indica irregularidade por si só.
Uso: python scripts/varredura_forense_c5b.py [C5-02 C5-10 C5-11 C5-07]   (sem argumentos: todas)
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
from scipy.stats import norm

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / 'research'
REL = ROOT / 'relatorios'
OUT = REL / 'verificacoes' / 'varredura_forense' / 'C5'
CACHE = R / 'varredura_forense' / 'C5b'
QUAR = R / 'varredura_forense' / 'quarentena'
BWEB = R / 'bu'
SECOES_2026 = REL / 'verificacoes' / 'virada_1t_2t_2026' / 'secoes_t1_t2.parquet'
BASE = R / 'padroes_2t'
CEM_PCT_RESUMO = REL / 'verificacoes' / 'cem_pct_2t' / 'resumo_por_eleicao.csv'
PARSER_VERSION = 'c5b-1.1'
CSV = dict(sep=';', decimal=',', index=False, encoding='utf-8-sig')

UFS = ['AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MG', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI', 'PR', 'RJ',
       'RN', 'RO', 'RR', 'RS', 'SC', 'SE', 'SP', 'TO']
EXTERIOR = 'ZZ'
UFS_FISCALIZACAO = ['BA', 'SP', 'MG', 'RJ', 'PR', 'RS', 'PE', 'CE', 'PA', 'SC', 'MA']
PLEITOS_PRES = ['2014-t1', '2014-t2', '2018-t1', '2018-t2', '2022-t1', '2022-t2', '2026-t1', '2026-t2']
LADO_A = '13'                                                  # PT nas quatro presidenciais
LADO_B = {'2014': '45', '2018': '17', '2022': '22', '2026': '22'}  # adversário do 2º turno
PLEITOS_GOV = ['2014-t1', '2014-t2', '2018-t1', '2018-t2', '2022-t1', '2022-t2', '2026-t1']
LOC = ['uf', 'municipality', 'zone', 'voting_place']
KEY = ['uf', 'municipality', 'zone', 'section']

MIN_APTOS = 50           # protocolo: seções com < 50 aptos ficam fora das referências estatísticas
MIN_PARES = 3            # pares mínimos no mesmo prédio
MIN_ESPERADO = 5.0       # contagem esperada mínima (n * min(p, 1-p)) para a aproximação normal valer
MIN_SECOES_RHO = 30      # seções testáveis mínimas para estimar rho numa UF/categoria
Z_LIM = 4.0              # protocolo: seção isolada só é listada com |z| >= 4
Z3 = 3.0
BH_Q = 0.05
N_SIM = 10
SEED = 20261105
CHI2_MED = 0.454936423119572  # mediana do qui-quadrado com 1 g.l.
# C5-11 (mesma regra de make_varredura_locais.compare)
MIN_PP = 5.0
ZMIN = 2.0
P_MANUAL = 0.99          # comportamento "manual" por aproximação: fração manual/comparecimento > P99 da UF no pleito

_INPUTS = {}
_QUARENTENA = []


# ----------------------------------------------------------------------------------------------------------- utilidades
def agora():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def bh(p, q=BH_Q):
    """Benjamini-Hochberg: devolve máscara de rejeição (NaN nunca rejeita)."""
    p = np.asarray(p, dtype=float)
    out = np.zeros(p.shape, dtype=bool)
    ok = np.isfinite(p)
    m = int(ok.sum())
    if m == 0:
        return out
    pv = p[ok]
    order = np.argsort(pv)
    thr = q * np.arange(1, m + 1) / m
    passa = pv[order] <= thr
    if passa.any():
        kmax = np.nonzero(passa)[0].max()
        rej = np.zeros(m, dtype=bool)
        rej[order[:kmax + 1]] = True
        out[np.nonzero(ok)[0]] = rej
    return out


def p_bilateral(z):
    z = np.asarray(z, dtype=float)
    with np.errstate(invalid='ignore'):
        return 2 * norm.sf(np.abs(z))


def csv_out(nome, df):
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / nome, **CSV)
    return str(OUT / nome).replace('\\', '/')


def grava_parquet(df, path, inputs):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    with open(path, 'rb') as f:
        sha = hashlib.file_digest(f, 'sha256').hexdigest()
    rec = {'at': agora(), 'inputs': {str(k): v for k, v in inputs.items()}, 'sha256': sha, 'rows': int(len(df)),
           'bytes': path.stat().st_size, 'parser_version': PARSER_VERSION}
    path.with_suffix('.json').write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding='utf-8')
    return rec


def quarentena(checagem, df, reason):
    """Linhas que falham invariante: valores originais como string + motivo (JSON por checagem e CSV único)."""
    if df is None or len(df) == 0:
        return 0
    rows = [{k: ('' if pd.isna(v) else str(v)) for k, v in r.items()} | {'reason': reason, 'checagem': checagem}
            for r in df.to_dict('records')]
    _QUARENTENA.extend(rows)
    return len(rows)


def grava_quarentena():
    QUAR.mkdir(parents=True, exist_ok=True)
    por = {}
    for r in _QUARENTENA:
        por.setdefault(r['checagem'], []).append(r)
    arqs = []
    for chk, rows in por.items():
        p = QUAR / f'rows-C5-{chk}.json'
        p.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
        arqs.append(str(p).replace('\\', '/'))
    cols = ['checagem', 'reason', 'pleito', 'cargo', 'uf', 'CD_MUNICIPIO', 'NR_ZONA', 'NR_SECAO']
    df = pd.DataFrame(_QUARENTENA)
    if len(df) == 0:
        df = pd.DataFrame(columns=cols)
    arqs.append(csv_out('quarentena_c5b.csv', df))
    return arqs


# ------------------------------------------------------------------------------------------------------------ leitura
def le_parquet(path, cols):
    """Lê só as colunas pedidas (as que existirem); registra o SHA-256 do arquivo como entrada."""
    import pyarrow.parquet as pq
    registra_entrada(path)
    names = pq.read_schema(path).names
    t = pq.read_table(path, columns=[c for c in cols if c in names])
    d = t.to_pandas()
    del t
    libera_arrow()
    return d, names


def registra_entrada(path):
    with open(path, 'rb') as f:
        _INPUTS[str(path).replace('\\', '/')] = hashlib.file_digest(f, 'sha256').hexdigest()


def libera_arrow():
    try:
        import pyarrow as pa
        pa.default_memory_pool().release_unused()
    except Exception:  # noqa: BLE001
        pass


def duck():
    import duckdb
    con = duckdb.connect()
    con.execute("SET memory_limit='300MB'")   # abaixo do teto de 400 MB: o processo inteiro precisa caber em 500 MB
    con.execute('SET threads=2')
    con.execute('SET preserve_insertion_order=false')
    return con


def le_bweb_duckdb(path, uf, pleito, cargo, checagem):
    """Lê o BWEB com DuckDB (400 MB, 2 threads): linhas idênticas repetidas (todas as colunas) contadas e removidas,
    linhas com chave/contagem não numérica para a quarentena com os valores originais, e o resto já convertido para
    inteiros (o pandas nunca vê as colunas de texto inteiras). Devolve (longo numérico, nomes)."""
    import pyarrow as pa
    registra_entrada(path)
    f = str(path).replace('\\', '/')
    con = duck()
    names = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{f}')").fetchall()]
    n_tot = con.execute(f"SELECT count(*) FROM read_parquet('{f}')").fetchone()[0]
    # detecção por hash da linha inteira (barata); a remoção, só quando há repetição, usa DISTINCT de verdade
    n_dist = con.execute(f"SELECT count(DISTINCT hash(*COLUMNS(*))) FROM read_parquet('{f}')").fetchone()[0]
    if n_dist < n_tot:
        n_dist = con.execute(f"SELECT count(*) FROM (SELECT DISTINCT * FROM read_parquet('{f}'))").fetchone()[0]
    ctx = {'pleito': pleito, 'cargo': cargo, 'uf': uf}
    src = f"read_parquet('{f}')"
    if n_dist < n_tot:
        ex = con.execute(f"SELECT * FROM {src} GROUP BY ALL HAVING count(*) > 1 LIMIT 1").df()
        quarentena(checagem, ex.assign(**ctx, linhas_identicas_removidas=int(n_tot - n_dist), linhas_no_arquivo=n_tot),
                   'linhas idênticas repetidas no arquivo (todas as colunas); cópia removida')
        src = f"(SELECT DISTINCT * FROM read_parquet('{f}'))"
    numc = ['CD_MUNICIPIO', 'NR_ZONA', 'NR_SECAO', 'QT_APTOS', 'QT_COMPARECIMENTO', 'QT_VOTOS', 'CD_TIPO_VOTAVEL']
    ruim = ' OR '.join(f'TRY_CAST("{c}" AS BIGINT) IS NULL' for c in numc)
    bad = con.execute(f'SELECT * FROM {src} WHERE {ruim}').df()
    if len(bad):
        quarentena(checagem, bad.assign(**ctx), 'valor não numérico em chave/contagem')
    agcol = 'DS_AGREGADAS' if 'DS_AGREGADAS' in names else (
        'DS_SECOES_AGREGADAS' if 'DS_SECOES_AGREGADAS' in names else None)
    sel = [f'CAST("{c}" AS INTEGER) AS "{c}"' for c in numc]
    sel.append('TRY_CAST("NR_LOCAL_VOTACAO" AS INTEGER) AS "NR_LOCAL_VOTACAO"' if 'NR_LOCAL_VOTACAO' in names
               else 'CAST(NULL AS INTEGER) AS "NR_LOCAL_VOTACAO"')
    sel.append('"NR_VOTAVEL"')
    if 'DS_TIPO_URNA' in names:
        sel.append('"DS_TIPO_URNA"')
    if agcol:
        sel.append(f'"{agcol}"')
    tb = con.sql(f"SELECT {', '.join(sel)} FROM {src} WHERE NOT ({ruim})").to_arrow_table()
    if hasattr(tb, 'read_all'):
        tb = tb.read_all()
    cols = {}
    for c in tb.column_names:
        col = tb.column(c)
        texto = pa.types.is_string(col.type) or pa.types.is_large_string(col.type) or pa.types.is_string_view(col.type)
        cols[c] = col.cast(pa.string()).dictionary_encode() if texto else col
    d = pa.table(cols).to_pandas()
    del tb, cols
    nomes = {}
    if 'NM_VOTAVEL' in names:
        nn = con.execute(f'SELECT DISTINCT "NR_VOTAVEL", "NM_VOTAVEL" FROM {src} '
                         "WHERE TRY_CAST(\"CD_TIPO_VOTAVEL\" AS INTEGER) = 1").fetchall()
        nomes = {str(a): str(b) for a, b in nn}
    con.close()
    libera_arrow()
    return d, nomes


BWEB_COLS = ['SG_UF', 'CD_MUNICIPIO', 'NR_ZONA', 'NR_SECAO', 'NR_LOCAL_VOTACAO', 'QT_APTOS', 'QT_COMPARECIMENTO',
             'CD_TIPO_VOTAVEL', 'NR_VOTAVEL', 'NM_VOTAVEL', 'QT_VOTOS', 'DS_TIPO_URNA', 'DS_AGREGADAS',
             'DS_SECOES_AGREGADAS']
KEYB = ['CD_MUNICIPIO', 'NR_ZONA', 'NR_SECAO']


def _cat(x):
    """Coluna de texto curta como categoria de strings (barata em memória)."""
    if isinstance(x.dtype, pd.CategoricalDtype):
        return x.cat.rename_categories([str(c) for c in x.cat.categories])
    return x.astype(str).astype('category')


def bweb_para_secoes(d, uf, pleito, cargo, checagem='C5-02', ja_deduplicado=False):
    """BWEB longo (uma linha por seção e votável) -> uma linha por seção com v<NR_VOTAVEL>, branco, nulo,
    outros_tipo, validos, aptos, comp, voting_place, tipo_urna, agregada e status ('OK' ou 'QUARENTENA: motivo').
    Linhas que falham invariante vão para a quarentena com os valores originais. Devolve (secoes, nomes)."""
    ctx = {'pleito': pleito, 'cargo': cargo, 'uf': uf}
    if not ja_deduplicado:
        exatas = d.duplicated(keep='first')
        if exatas.any():
            # linha idêntica em TODAS as colunas (repetição do arquivo publicado): uma cópia é mantida; o registro de
            # quarentena guarda a contagem e a primeira linha repetida (valores originais)
            ex = d[exatas].head(1).assign(**ctx, linhas_identicas_removidas=int(exatas.sum()), linhas_no_arquivo=len(d))
            quarentena(checagem, ex, 'linhas idênticas repetidas no arquivo (todas as colunas); cópia removida')
            d = d[~exatas]
    agcol = 'DS_AGREGADAS' if 'DS_AGREGADAS' in d else ('DS_SECOES_AGREGADAS' if 'DS_SECOES_AGREGADAS' in d else None)
    numc = ['CD_MUNICIPIO', 'NR_ZONA', 'NR_SECAO', 'QT_APTOS', 'QT_COMPARECIMENTO', 'QT_VOTOS', 'CD_TIPO_VOTAVEL']
    x = pd.DataFrame(index=d.index)
    for c in numc:
        x[c] = d[c] if pd.api.types.is_integer_dtype(d[c]) else pd.to_numeric(d[c], errors='coerce')
    ruim = x.isna().any(axis=1)
    if ruim.any():
        quarentena(checagem, d[ruim].assign(**ctx), 'valor não numérico em chave/contagem')
        x = x[~ruim].copy()
    for c in numc:
        x[c] = x[c].astype('int32')
    x['NR_VOTAVEL'] = _cat(d.loc[x.index, 'NR_VOTAVEL'])
    x['_lv'] = (pd.to_numeric(d.loc[x.index, 'NR_LOCAL_VOTACAO'], errors='coerce').astype('float64')
                if 'NR_LOCAL_VOTACAO' in d else np.nan)
    if 'DS_TIPO_URNA' in d:
        x['_tipo'] = _cat(d.loc[x.index, 'DS_TIPO_URNA'])
    if agcol:
        x['_ag'] = _cat(d.loc[x.index, agcol])
    nomes = {}
    if 'NM_VOTAVEL' in d:
        nn = d.loc[x.index[x.CD_TIPO_VOTAVEL == 1], ['NR_VOTAVEL', 'NM_VOTAVEL']].drop_duplicates('NR_VOTAVEL')
        nomes = dict(zip(nn.NR_VOTAVEL.astype(str), nn.NM_VOTAVEL.astype(str)))
    d = x
    del x
    secoes_quar = {}
    dup = d.duplicated(KEYB + ['CD_TIPO_VOTAVEL', 'NR_VOTAVEL'], keep=False)
    if dup.any():
        quarentena(checagem, d[dup].drop(columns=['_lv']).assign(**ctx), 'votável repetido na mesma seção')
        for k in d.loc[dup, KEYB].drop_duplicates().itertuples(index=False):
            secoes_quar[tuple(k)] = 'votável repetido na mesma seção'
    chaves = [d[k] for k in KEYB]
    g = d.groupby(KEYB, sort=False)
    s = g.agg(aptos=('QT_APTOS', 'min'), aptos_max=('QT_APTOS', 'max'), comp=('QT_COMPARECIMENTO', 'min'),
              comp_max=('QT_COMPARECIMENTO', 'max'), voting_place=('_lv', 'min'), lv_max=('_lv', 'max'))
    if '_tipo' in d:
        gt = d['_tipo'].cat.codes.groupby(chaves, sort=False)
        cmin = gt.min().reindex(s.index)
        s['n_tipo'] = np.where(gt.max().reindex(s.index).values != cmin.values, 2, 1)
        s['tipo_urna'] = d['_tipo'].cat.categories.values[cmin.values]
    if '_ag' in d:
        amin = d['_ag'].cat.codes.groupby(chaves, sort=False).min().reindex(s.index)
        s['agregadas'] = d['_ag'].cat.categories.values[amin.values]
    nom = d[d.CD_TIPO_VOTAVEL == 1]
    piv = nom.groupby(KEYB + ['NR_VOTAVEL'], sort=False, observed=True).QT_VOTOS.sum().unstack(fill_value=0)
    del nom
    piv.columns = [f'v{c}' for c in piv.columns]
    s = s.join(piv)
    vcols = list(piv.columns)
    del piv
    s[vcols] = s[vcols].fillna(0).astype('int32')
    for nome, cod in (('branco', 2), ('nulo', 3)):
        s[nome] = d[d.CD_TIPO_VOTAVEL == cod].groupby(KEYB).QT_VOTOS.sum().reindex(s.index).fillna(0).astype('int32')
    s['outros_tipo'] = d[~d.CD_TIPO_VOTAVEL.isin([1, 2, 3])].groupby(KEYB).QT_VOTOS.sum().reindex(s.index).fillna(0)
    s['outros_tipo'] = s.outros_tipo.astype('int32')
    s['validos'] = s[vcols].sum(axis=1).astype('int32') if vcols else 0
    s = s.reset_index().rename(columns={'CD_MUNICIPIO': 'municipality', 'NR_ZONA': 'zone', 'NR_SECAO': 'section'})
    s.insert(0, 'uf', uf)
    s['agregada'] = False
    if agcol:
        a = s.agregadas.astype(str).str.strip()
        s['agregada'] = ~a.isin(['', '#NULO#', 'nan', 'None', '#NE#', '-1'])
    s['status'] = 'OK'
    motivos = []
    if 'n_tipo' in s:
        motivos.append((s.n_tipo > 1, 'mais de um tipo de urna na mesma seção'))
    motivos += [(s.aptos != s.aptos_max, 'aptos diferentes entre linhas da mesma seção'),
                (s.comp != s.comp_max, 'comparecimento diferente entre linhas da mesma seção'),
                (s.voting_place.fillna(-1) != s.lv_max.fillna(-1),
                 'local de votação diferente entre linhas da mesma seção'),
                (s.validos + s.branco + s.nulo + s.outros_tipo != s.comp, 'soma dos votos difere do comparecimento'),
                (s.comp > s.aptos, 'comparecimento maior que aptos')]
    for m, mot in motivos:
        m = m & s.status.eq('OK')
        if m.any():
            quarentena(checagem, s.loc[m, ['uf', 'municipality', 'zone', 'section', 'aptos', 'comp', 'validos', 'branco',
                                           'nulo', 'outros_tipo']].assign(pleito=pleito, cargo=cargo), mot)
            s.loc[m, 'status'] = 'QUARENTENA: ' + mot
    if secoes_quar:
        ks = pd.Series(list(zip(s.municipality, s.zone, s.section)))
        m = ks.isin(secoes_quar.keys()).values & s.status.eq('OK').values
        s.loc[m, 'status'] = 'QUARENTENA: votável repetido na mesma seção'
    s = s.drop(columns=[c for c in ['aptos_max', 'comp_max', 'lv_max', 'n_tipo', 'agregadas'] if c in s])
    return s, nomes


def carrega_bweb(pleito, uf, cargo, checagem='C5-02'):
    f = BWEB / pleito / f'{uf}_{cargo}.parquet'
    if not f.exists():
        return None, {}
    d, nomes = le_bweb_duckdb(f, uf, pleito, cargo, checagem)
    if len(d) == 0:
        return None, {}
    s, nm = bweb_para_secoes(d, uf, pleito, cargo, checagem, ja_deduplicado=True)
    del d
    gc.collect()
    return compacta(s), nomes or nm


def secoes_2026_para_formato(t, turno):
    """secoes_t1_t2.parquet -> formato de bweb_para_secoes (sem tipo de urna nem agregadas)."""
    p = f't{turno}_'
    vcols = [c for c in t if re.fullmatch(p + r'v\d+', c)]
    s = pd.DataFrame({'uf': t.uf.astype(str), 'municipality': t.municipality.astype('int64'),
                      'zone': t.zone.astype('int64'), 'section': t.section.astype('int64'),
                      'voting_place': pd.to_numeric(t[p + 'voting_place'], errors='coerce'),
                      'aptos': t[p + 'aptos'], 'comp': t[p + 'comparecimento']})
    for c in vcols:
        s['v' + c[len(p) + 1:]] = t[c]
    s['branco'] = t[p + 'branco']
    s['nulo'] = t[p + 'nulo']
    s['outros_tipo'] = 0
    falta = s[['aptos', 'comp', 'branco', 'nulo'] + ['v' + c[len(p) + 1:] for c in vcols]].isna().any(axis=1)
    num = [c for c in s if c not in ('uf', 'voting_place')]
    s[num] = s[num].fillna(0).astype('int64')
    vv = [c for c in s if re.fullmatch(r'v\d+', c)]
    s['validos'] = s[vv].sum(axis=1)
    s['tipo_urna'] = 'BU de urna (2026)'
    s['agregada'] = False
    s['status'] = 'OK'
    s.loc[falta.values, 'status'] = f'NOT_COMPARABLE: sem BU no {turno}º turno'
    m = s.status.eq('OK') & (s.validos + s.branco + s.nulo != s.comp)
    s.loc[m, 'status'] = 'QUARENTENA: soma dos votos difere do comparecimento'
    m2 = s.status.eq('OK') & (s.comp > s.aptos)
    s.loc[m2, 'status'] = 'QUARENTENA: comparecimento maior que aptos'
    return s, m, m2


def carrega_2026(turno, checagem='C5-02'):
    cols = ['uf', 'municipality', 'zone', 'section', f't{turno}_voting_place', f't{turno}_aptos',
            f't{turno}_comparecimento', f't{turno}_branco', f't{turno}_nulo']
    cols += [f't{turno}_v{n}' for n in (13, 14, 22, 55, 70, 27, 16, 30, 80, 29, 35, 21, 28)]
    t, _ = le_parquet(SECOES_2026, cols)
    s, m, m2 = secoes_2026_para_formato(t, turno)
    for mask, mot in ((m, 'soma dos votos difere do comparecimento'), (m2, 'comparecimento maior que aptos')):
        if mask.any():
            quarentena(checagem, t[mask.values].assign(pleito=f'2026-t{turno}', cargo='PRESIDENTE'), mot)
    del t
    return s


def carrega_pleito_pres(pleito):
    """Uma tabela por seção (27 UFs + ZZ) do pleito presidencial, mais o dicionário de nomes."""
    if pleito.startswith('2026'):
        return compacta(carrega_2026(int(pleito[-1]))), {LADO_A: 'LULA', '22': 'FLAVIO BOLSONARO'}
    partes, nomes = [], {}
    for uf in UFS + [EXTERIOR]:
        s, nm = carrega_bweb(pleito, uf, 'PRESIDENTE')
        if s is not None:
            partes.append(s)
            nomes.update(nm)
    s = pd.concat(partes, ignore_index=True)
    del partes
    vv = [c for c in s if re.fullmatch(r'v\d+', c)]
    s[vv] = s[vv].fillna(0).astype('int32')
    return compacta(s), nomes


def compacta(s):
    """Contagens em int32 (todas < 2^31) para caber no limite de memória por processo."""
    for c in s:
        if s[c].dtype == 'int64':
            s[c] = s[c].astype('int32')
    return s


def status_referencia(s):
    """Status de comparabilidade de cada seção para o modelo do prédio (antes do teste por categoria)."""
    st = s.status.copy()
    ok = st.eq('OK')
    st[ok & s.voting_place.isna()] = 'NOT_COMPARABLE: sem local de votação'
    ok = st.eq('OK')
    st[ok & (s.aptos < MIN_APTOS)] = f'NOT_COMPARABLE: menos de {MIN_APTOS} aptos'
    ok = st.eq('OK')
    if 'tipo_urna' in s:
        tu = s.tipo_urna.astype(str).str.upper()
        st[ok & ~tu.isin(['APURADA', 'BU DE URNA (2026)'])] = 'NOT_COMPARABLE: tipo de urna ' + s.tipo_urna.astype(str)
    ok = st.eq('OK')
    st[ok & (s.comp <= 0)] = 'NOT_COMPARABLE: comparecimento zero'
    return st


# ------------------------------------------------------------------------------------------------- modelo do prédio
def estima_rho(r2, a, b, alvo=CHI2_MED, it=60):
    """rho >= 0 tal que mediana(r2 / (a + b rho)) = mediana do qui-quadrado(1). Se já houver subdispersão em rho = 0,
    rho = 0 e phi = mediana/alvo (< 1); se nem rho = 1 bastar, rho = 1 e phi > 1. Devolve (rho, phi)."""
    r2, a, b = (np.asarray(v, dtype=float) for v in (r2, a, b))
    if len(r2) < MIN_SECOES_RHO:
        return np.nan, np.nan

    def f(rho):
        return float(np.median(r2 / (a + b * rho)))
    f0 = f(0.0)
    if f0 <= alvo:
        return 0.0, f0 / alvo
    f1 = f(1.0)
    if f1 > alvo:
        return 1.0, f1 / alvo
    lo, hi = 0.0, 1.0
    for _ in range(it):
        mid = (lo + hi) / 2
        if f(mid) > alvo:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2, 1.0


def residuo_predio(x, n, place, ok, y=None, rho_phi=None):
    """Resíduo padronizado de cada seção contra as OUTRAS seções elegíveis do mesmo prédio (deixa-uma-de-fora).
    x: votos da categoria (ou do lado A, com y = votos do lado B, para a margem A-B); n: denominador da seção;
    place: código inteiro do prédio; ok: seção elegível (entra como par e pode ser testada).
    Devolve dict com mu (fatia ou margem esperada), k_pares, testavel, z, excesso (votos), rho e phi."""
    x = np.asarray(x, dtype=float)
    n = np.asarray(n, dtype=float)
    place = np.asarray(place, dtype=np.int64)
    w = np.asarray(ok, dtype=float)
    ng = int(place.max()) + 1 if len(place) else 1

    def loo(v):
        return np.bincount(place, weights=v * w, minlength=ng)[place] - v * w
    kp = np.bincount(place, weights=w, minlength=ng)[place] - w
    Pn = loo(n)
    Px = loo(x)
    with np.errstate(invalid='ignore', divide='ignore'):
        if y is None:
            mu = (Px + .5) / (Pn + 1)
            v = mu * (1 - mu)
            conta = x
            cond = n * np.minimum(mu, 1 - mu) >= MIN_ESPERADO
        else:
            y = np.asarray(y, dtype=float)
            Py = loo(y)
            mu = (Px - Py) / (Pn + 1)
            s = (Px + Py + .5) / (Pn + 1)
            v = np.maximum(s - mu ** 2, 1 / (Pn + 1))
            conta = x - y
            cond = n * v >= MIN_ESPERADO
        nbar = Pn / np.maximum(kp, 1)
        a = 1 + n / Pn
        b = (n - 1) + n * (nbar - 1) / Pn
        r = conta - n * mu
        test = (w > 0) & (kp >= MIN_PARES) & (n > 0) & (Pn > 0) & cond
        r2 = np.where(test, r ** 2 / (n * v), np.nan)
    if rho_phi is None:
        rho, phi = estima_rho(r2[test], a[test], b[test])
    else:
        rho, phi = rho_phi
    with np.errstate(invalid='ignore', divide='ignore'):
        z = np.where(test, r / np.sqrt(n * v * phi * (a + b * rho)), np.nan)
    if not np.isfinite(rho):
        test = np.zeros_like(test)
        z = np.full(len(x), np.nan)
    return dict(mu=mu, k_pares=kp, testavel=test, z=z, excesso=np.where(test, r, np.nan), rho=rho, phi=phi)


def _beta_mix(p, rho, rng):
    if rho is None or not np.isfinite(rho) or rho <= 0:
        return p
    c = 1 / rho - 1
    return rng.beta(np.maximum(p * c, 1e-9), np.maximum((1 - p) * c, 1e-9))


def simula_nulo(x, n, place, ok, rho, rng, y=None):
    """Sorteia votos sob o nulo: todas as seções elegíveis do prédio com a mesma fatia (a do prédio inteiro) e
    dispersão beta-binomial rho. Para a margem, sorteia A e B em cadeia (Dirichlet aproximada). Devolve (x*, y*)."""
    x = np.asarray(x, dtype=float)
    n = np.asarray(n, dtype=np.int64)
    place = np.asarray(place, dtype=np.int64)
    w = np.asarray(ok, dtype=float)
    ng = int(place.max()) + 1
    Sn = np.bincount(place, weights=n * w, minlength=ng)[place]
    pa = np.clip((np.bincount(place, weights=x * w, minlength=ng)[place] + .5) / (Sn + 1), 1e-6, 1 - 1e-6)
    if y is None:
        q = _beta_mix(pa, rho, rng)
        return rng.binomial(n, np.clip(q, 0, 1)).astype(float), None
    y = np.asarray(y, dtype=float)
    pb = np.clip((np.bincount(place, weights=y * w, minlength=ng)[place] + .5) / (Sn + 1), 1e-6, 1 - 1e-6)
    pb = np.minimum(pb, 1 - pa - 1e-6).clip(1e-6, None)
    if rho is None or not np.isfinite(rho) or rho <= 0:
        qa, qb = pa, pb
    else:
        c = 1 / rho - 1
        ga = rng.gamma(np.maximum(pa * c, 1e-9))
        gb = rng.gamma(np.maximum(pb * c, 1e-9))
        gr = rng.gamma(np.maximum((1 - pa - pb) * c, 1e-9))
        tot = ga + gb + gr
        qa, qb = ga / tot, gb / tot
    xa = rng.binomial(n, np.clip(qa, 0, 1))
    cond = np.clip(qb / np.maximum(1 - qa, 1e-12), 0, 1)
    xb = rng.binomial(n - xa, cond)
    return xa.astype(float), xb.astype(float)


def caudas(z):
    z = np.asarray(z, dtype=float)
    z = z[np.isfinite(z)]
    return dict(n=len(z), pos4=int((z >= Z_LIM).sum()), neg4=int((z <= -Z_LIM).sum()),
                gt3=int((np.abs(z) >= Z3).sum()), var=float(np.var(z)) if len(z) else np.nan)


def categorias(s, ano):
    """Categorias testadas: cada candidato (fatia dos válidos), branco e nulo (fatia do comparecimento), margem A-B."""
    vv = sorted((c for c in s if re.fullmatch(r'v\d+', c)), key=lambda c: -s[c].sum())
    cats = [(c[1:], c, 'validos', None) for c in vv if s[c].sum() > 0]
    cats += [('BRANCO', 'branco', 'comp', None), ('NULO', 'nulo', 'comp', None)]
    b = LADO_B[ano]
    if f'v{LADO_A}' in s and f'v{b}' in s:
        cats.append(('MARGEM_A-B', f'v{LADO_A}', 'validos', f'v{b}'))
    return cats


def rotulo(cat, ano):
    if cat == LADO_A:
        return 'A (PT)'
    if cat == LADO_B[ano]:
        return 'B (adversário 2º turno)'
    if cat in ('BRANCO', 'NULO'):
        return cat.lower()
    if cat.startswith('MARGEM'):
        return 'margem A-B'
    return 'outro candidato'


def modelo_uf(s, ano, rng, n_sim=N_SIM):
    """Roda o modelo do prédio em uma UF (todas as categorias). Devolve (familias, colunas z/mu/excesso por seção)."""
    s = s.reset_index(drop=True)
    ok = s.ref_status.eq('OK').values
    place = s.groupby(LOC, sort=False, dropna=False).ngroup().values
    linhas, cols = [], {}
    for cat, col, den, ycol in categorias(s, ano):
        x = s[col].values
        n = s[den].values
        y = s[ycol].values if ycol else None
        res = residuo_predio(x, n, place, ok & (n > 0), y=y)
        c = caudas(res['z'])
        sims = []
        if np.isfinite(res['rho']) and c['n'] > 0:
            for _ in range(n_sim):
                xs, ys = simula_nulo(x, n, place, ok & (n > 0), res['rho'], rng, y=y)
                rs = residuo_predio(xs, n, place, ok & (n > 0), y=ys)
                sims.append(caudas(rs['z']))
        sp = np.mean([q['pos4'] for q in sims]) if sims else np.nan
        sn = np.mean([q['neg4'] for q in sims]) if sims else np.nan
        sv = np.mean([q['var'] for q in sims]) if sims else np.nan
        s3 = np.mean([q['gt3'] for q in sims]) if sims else np.nan
        linhas.append(dict(categoria=cat, rotulo=rotulo(cat, ano), denominador=den,
                           secoes_ref=int((ok & (n > 0)).sum()), testadas=c['n'], rho=res['rho'], phi=res['phi'],
                           var_z=c['var'], var_z_sim=sv, abs_z_ge3=c['gt3'], abs_z_ge3_sim=s3,
                           z_ge4_acima=c['pos4'], z_ge4_abaixo=c['neg4'], sim_z_ge4_acima=sp, sim_z_ge4_abaixo=sn,
                           votos_categoria=float(np.nansum(x)) if y is None else float(np.nansum(x) - np.nansum(y))))
        cols[f'z_{cat}'] = res['z'].astype('float32')
        cols[f'mu_{cat}'] = res['mu'].astype('float32')
        cols[f'k_{cat}'] = res['k_pares'].astype('float32')
    return pd.DataFrame(linhas), pd.DataFrame(cols, index=s.index)


def pares_controle(s, idx, col, den, ycol=None):
    """Para as seções listadas: fatia mínima e máxima entre as outras seções elegíveis do mesmo prédio (controle)."""
    ok = s.ref_status.eq('OK') & (s[den] > 0)
    with np.errstate(invalid='ignore', divide='ignore'):
        val = ((s[col] - (s[ycol] if ycol else 0)) / s[den]).where(ok)
    g = s[LOC].assign(_v=val).groupby(LOC, sort=False, dropna=False)._v
    mins, maxs = [], []
    grupos = s.loc[idx, LOC]
    for i, key in zip(idx, grupos.itertuples(index=False)):
        try:
            vv = g.get_group(tuple(key)).drop(index=i, errors='ignore').dropna()
        except KeyError:
            vv = pd.Series(dtype=float)
        mins.append(100 * vv.min() if len(vv) else np.nan)
        maxs.append(100 * vv.max() if len(vv) else np.nan)
    return mins, maxs


def c5_02_pleito(pleito, s, nomes, rng):
    """Modelo do prédio em todas as UFs de um pleito presidencial. Devolve (familias por UF, destoantes, status, z)."""
    ano = pleito[:4]
    s['ref_status'] = status_referencia(s)
    fams, zs = [], []
    for uf, su in s.groupby('uf', sort=True):
        f, zc = modelo_uf(su, ano, rng)
        f.insert(0, 'uf', uf)
        fams.append(f)
        zs.append(pd.concat([su[KEY + ['voting_place']].reset_index(drop=True), zc.reset_index(drop=True)], axis=1)
                  .set_index(su.index))
    fam = pd.concat(fams, ignore_index=True)
    fam.insert(0, 'pleito', pleito)
    Z = pd.concat(zs).loc[s.index]
    # BH por família: país (sem exterior) e exterior separados
    dest = []
    for cat, col, den, ycol in categorias(s, ano):
        zc = Z[f'z_{cat}'].values.astype(float)
        p = p_bilateral(zc)
        rej = np.zeros(len(zc), dtype=bool)
        ext = s.uf.eq(EXTERIOR).values
        rej[~ext] = bh(p[~ext])
        rej[ext] = bh(p[ext])
        Z[f'bh_{cat}'] = rej
        for grupo, m in (('BR', ~ext), (EXTERIOR, ext)):
            fam.loc[(fam.categoria == cat) & (fam.uf.eq(EXTERIOR) if grupo == EXTERIOR else fam.uf.ne(EXTERIOR)),
                    'familia_bh'] = f'{pleito}|{cat}|{grupo}'
        sel = np.nonzero(rej & (np.abs(np.nan_to_num(zc)) >= Z_LIM))[0]
        for uf in fam.uf.unique():
            m = (s.uf.values == uf)
            fam.loc[(fam.uf == uf) & (fam.categoria == cat), 'bh_acima'] = int((rej & m & (zc > 0)).sum())
            fam.loc[(fam.uf == uf) & (fam.categoria == cat), 'bh_abaixo'] = int((rej & m & (zc < 0)).sum())
            fam.loc[(fam.uf == uf) & (fam.categoria == cat), 'listadas_acima'] = int(
                (rej & m & (zc >= Z_LIM)).sum())
            fam.loc[(fam.uf == uf) & (fam.categoria == cat), 'listadas_abaixo'] = int(
                (rej & m & (zc <= -Z_LIM)).sum())
        if len(sel) == 0:
            continue
        idx = s.index[sel]
        sub = s.loc[idx]
        mu = Z.loc[idx, f'mu_{cat}'].values.astype(float)
        nn = sub[den].values.astype(float)
        conta = sub[col].values - (sub[ycol].values if ycol else 0)
        mins, maxs = pares_controle(s, idx, col, den, ycol)
        dest.append(pd.DataFrame({
            'pleito': pleito, 'uf': sub.uf.values, 'municipality': sub.municipality.values, 'zone': sub.zone.values,
            'section': sub.section.values, 'voting_place': sub.voting_place.values, 'categoria': cat,
            'nome': nomes.get(cat, '') if cat not in ('BRANCO', 'NULO') and not cat.startswith('MARGEM') else '',
            'rotulo': rotulo(cat, ano), 'lado': np.where(zc[sel] > 0, 'acima do prédio', 'abaixo do prédio'),
            'votos': conta, 'denominador': den, 'n': nn, 'fatia_secao_pct': 100 * conta / nn,
            'fatia_pares_pct': 100 * mu, 'diferenca_pp': 100 * (conta / nn - mu), 'excesso_votos': conta - nn * mu,
            'z': zc[sel], 'p': p[sel], 'bh_5pct': True, 'k_pares': Z.loc[idx, f'k_{cat}'].values,
            'pares_min_pct': mins, 'pares_max_pct': maxs, 'aptos': sub.aptos.values, 'comp': sub.comp.values,
            'validos': sub.validos.values, 'agregada': sub.agregada.values,
            'tipo_urna': sub.tipo_urna.values if 'tipo_urna' in sub else '',
            'familia_bh': f'{pleito}|{cat}|' + np.where(sub.uf.values == EXTERIOR, EXTERIOR, 'BR')}))
    dest = pd.concat(dest, ignore_index=True) if dest else pd.DataFrame()
    st = s.groupby(['uf', 'ref_status']).size().rename('secoes').reset_index()
    st.insert(0, 'pleito', pleito)
    zcols = KEY + ['voting_place'] + [c for c in Z if c.startswith('z_')]
    Zout = Z[zcols].copy()
    Zout['ref_status'] = s.ref_status.values
    return fam, dest, st, Zout


def resumo_nacional(fam):
    """Soma as UFs (sem exterior) por pleito e categoria; o exterior fica em linha própria."""
    f = fam.copy()
    f['grupo'] = np.where(f.uf.eq(EXTERIOR), 'exterior', 'país (27 UFs)')
    soma = ['secoes_ref', 'testadas', 'abs_z_ge3', 'abs_z_ge3_sim', 'z_ge4_acima', 'z_ge4_abaixo', 'sim_z_ge4_acima',
            'sim_z_ge4_abaixo', 'bh_acima', 'bh_abaixo', 'listadas_acima', 'listadas_abaixo', 'votos_categoria']
    g = f.groupby(['pleito', 'grupo', 'categoria', 'rotulo'], sort=False)
    r = g[soma].sum().reset_index()
    r['ufs'] = g.size().values
    r['rho_mediana_ufs'] = g.rho.median().values
    r['phi_mediana_ufs'] = g.phi.median().values
    with np.errstate(invalid='ignore', divide='ignore'):
        r['razao_obs_sim_acima'] = r.z_ge4_acima / r.sim_z_ge4_acima
        r['razao_obs_sim_abaixo'] = r.z_ge4_abaixo / r.sim_z_ge4_abaixo
        r['z4_por_10mil'] = 1e4 * (r.z_ge4_acima + r.z_ge4_abaixo) / r.testadas
        r['sim_z4_por_10mil'] = 1e4 * (r.sim_z_ge4_acima + r.sim_z_ge4_abaixo) / r.testadas
        r['pct_acima_entre_z4'] = 100 * r.z_ge4_acima / (r.z_ge4_acima + r.z_ge4_abaixo)
    return r


def comparacao_pleitos(nac):
    """Lado a lado por rótulo (A, B, margem, branco, nulo): taxa de |z| >= 4 por 10 mil seções observada e simulada."""
    n = nac[nac.grupo.eq('país (27 UFs)') & nac.rotulo.isin(['A (PT)', 'B (adversário 2º turno)', 'margem A-B',
                                                            'branco', 'nulo'])].copy()
    n['turno'] = n.pleito.str[-2:]
    n['ano'] = n.pleito.str[:4]
    out = n.pivot_table(index=['turno', 'rotulo'], columns='ano',
                        values=['z4_por_10mil', 'sim_z4_por_10mil', 'listadas_acima', 'listadas_abaixo'],
                        aggfunc='first')
    out.columns = [f'{a}_{b}' for a, b in out.columns]
    return out.reset_index()


# ------------------------------------------------------------------------------------------------ C5-11 (vizinhas)
def _loo(group, clean, x, w):
    """Média ponderada, média simples e variância de x entre as seções `clean` do grupo, sem a própria linha
    (mesma conta de make_varredura_locais.loo)."""
    c = np.asarray(clean, dtype=float)
    x = np.asarray(x, dtype=float)
    w = np.asarray(w, dtype=float)
    g = np.asarray(group, dtype=np.int64)
    ng = int(g.max()) + 1

    def s(v):
        return np.bincount(g, weights=v, minlength=ng)[g]
    npeer = s(c) - c
    s1 = s(x * c) - x * c
    s2 = s(x * x * c) - x * x * c
    sw = s(w * c) - w * c
    swx = s(w * x * c) - w * x * c
    with np.errstate(invalid='ignore', divide='ignore'):
        mean_w = np.where(sw > 0, swx / sw, np.nan)
        mean_u = np.where(npeer > 0, s1 / npeer, np.nan)
        var = np.where(npeer > 1, (s2 - npeer * mean_u ** 2) / (npeer - 1), np.nan)
    return npeer, mean_w, np.clip(var, 0, None)


def compara_vizinhas(d, beh=None):
    """Teste da varredura (|diferença| >= 5 p.p. e |z| >= 2) para share_a E share_b, contra as seções sem
    comportamento do mesmo prédio (>= 3 pares para usar a dispersão do prédio; senão, a do município).
    d: share_a, share_b (0-100), valid_votes, place, mun. beh: máscara de comportamento (None = nenhuma)."""
    d = d.copy()
    beh = np.zeros(len(d), dtype=bool) if beh is None else np.asarray(beh, dtype=bool)
    clean = ~beh
    for lado in ('a', 'b'):
        x = d[f'share_{lado}'].values
        n_pl, m_pl, v_pl = _loo(d.place.values, clean, x, d.valid_votes.values)
        n_mu, m_mu, v_mu = _loo(d.mun.values, clean, x, d.valid_votes.values)
        use_pl = n_pl >= 1
        cmp_ = np.where(use_pl, m_pl, m_mu)
        var = np.where(n_pl >= MIN_PARES, v_pl, v_mu)
        p = np.clip(x / 100, .005, .995)
        se = 100 * np.sqrt(p * (1 - p) / d.valid_votes.values)
        diff = x - cmp_
        with np.errstate(invalid='ignore', divide='ignore'):
            z = diff / np.sqrt(var + se ** 2)
        d[f'diff_{lado}'] = diff
        d[f'z_{lado}'] = z
        d[f'real_{lado}'] = (np.abs(diff) >= MIN_PP) & (np.abs(z) >= ZMIN)
        if lado == 'a':
            d['nivel'] = np.select([n_pl >= MIN_PARES, n_pl >= 1], ['local', 'local (poucos pares)'], 'município')
    d['beh'] = beh
    return d


def resume_vizinhas(d, chaves):
    g = d.groupby(chaves + ['nivel'], sort=False, observed=True)
    r = g.size().rename('secoes').to_frame()
    for lado in ('a', 'b'):
        r[f'real_{lado}_acima'] = g.apply(lambda t, lado=lado: int((t[f'real_{lado}'] & (t[f'diff_{lado}'] > 0)).sum()),
                                          include_groups=False)
        r[f'real_{lado}_abaixo'] = g.apply(lambda t, lado=lado: int((t[f'real_{lado}'] & (t[f'diff_{lado}'] < 0)).sum()),
                                           include_groups=False)
    r = r.reset_index()
    with np.errstate(invalid='ignore', divide='ignore'):
        r['pct_real_a'] = 100 * (r.real_a_acima + r.real_a_abaixo) / r.secoes
        r['pct_a_favor_entre_reais_a'] = 100 * r.real_a_acima / (r.real_a_acima + r.real_a_abaixo)
        r['pct_real_b'] = 100 * (r.real_b_acima + r.real_b_abaixo) / r.secoes
        r['pct_b_favor_entre_reais_b'] = 100 * r.real_b_acima / (r.real_b_acima + r.real_b_abaixo)
    return r


def carrega_manual(pleito):
    ano, t = pleito[:4], pleito[-2:]
    f = BASE / f'base_{ano}.parquet'
    if ano == '2014' or not f.exists():
        return None
    b, names = le_parquet(f, KEY + [f'{t}_manual'])
    if f'{t}_manual' not in names:
        return None
    return b.rename(columns={f'{t}_manual': 'manual'})


def c5_11_pleito(pleito, s, manual):
    """Varredura das vizinhas nas 27 UFs, dois lados, com todas as seções como comuns e com o comportamento 'manual'
    aproximado (fração manual > P99 da UF); exterior fora."""
    ano = pleito[:4]
    b = LADO_B[ano]
    d = s[s.uf.ne(EXTERIOR) & s.ref_status.eq('OK') & (s.validos > 0)].copy()
    d['share_a'] = 100 * d[f'v{LADO_A}'] / d.validos
    d['share_b'] = 100 * d[f'v{b}'] / d.validos
    d['valid_votes'] = d.validos
    d['place'] = d.groupby(LOC, sort=False).ngroup()
    d['mun'] = d.groupby(['uf', 'municipality'], sort=False).ngroup()
    d['fiscalizacao'] = d.uf.isin(UFS_FISCALIZACAO)
    saidas = []
    todos = compara_vizinhas(d)
    todos['variante'] = 'todas como comuns'
    todos['grupo'] = 'comuns'
    saidas.append(resume_vizinhas(todos, ['variante', 'grupo', 'uf', 'fiscalizacao']))
    n_beh = 0
    if manual is not None:
        d = d.merge(manual, on=KEY, how='left')
        d['frac_manual'] = d.manual / d.comp
        p99 = d.groupby('uf').frac_manual.transform(lambda v: v.quantile(P_MANUAL))
        beh = (d.frac_manual > p99).fillna(False).values
        n_beh = int(beh.sum())
        m = compara_vizinhas(d, beh)
        m['variante'] = 'manual aproximado (fração > P99 da UF)'
        m['grupo'] = np.where(m.beh, 'com comportamento', 'comuns')
        saidas.append(resume_vizinhas(m, ['variante', 'grupo', 'uf', 'fiscalizacao']))
    r = pd.concat(saidas, ignore_index=True)
    r.insert(0, 'pleito', pleito)
    return r, n_beh


def agrega_vizinhas(r):
    """Agrega por pleito, variante, grupo, nível e recorte (11 UFs da fiscalização / 16 restantes / 27)."""
    cols = ['secoes', 'real_a_acima', 'real_a_abaixo', 'real_b_acima', 'real_b_abaixo']
    partes = []
    for nome, m in (('11 UFs fiscalização', r.fiscalizacao), ('16 UFs restantes', ~r.fiscalizacao),
                    ('27 UFs', r.fiscalizacao | ~r.fiscalizacao)):
        a = r[m].groupby(['pleito', 'variante', 'grupo', 'nivel'], sort=False)[cols].sum().reset_index()
        a.insert(1, 'recorte', nome)
        partes.append(a)
    a = pd.concat(partes, ignore_index=True)
    with np.errstate(invalid='ignore', divide='ignore'):
        a['pct_real_a'] = 100 * (a.real_a_acima + a.real_a_abaixo) / a.secoes
        a['pct_a_favor_entre_reais_a'] = 100 * a.real_a_acima / (a.real_a_acima + a.real_a_abaixo)
        a['pct_b_favor_entre_reais_b'] = 100 * a.real_b_acima / (a.real_b_acima + a.real_b_abaixo)
    return a


# -------------------------------------------------------------------------------------------- C5-07 (extremos BWEB)
def marca_extremos(s):
    """100% para um candidato (válidos > 0 e um candidato com todos), >= 99%, comparecimento = aptos e >= 99% dos aptos;
    com o local (outras seções, fatia do mesmo candidato e comparecimento das outras) e nº de candidatos no município."""
    s = s.reset_index(drop=True).copy()
    vv = [c for c in s if re.fullmatch(r'v\d+', c)]
    m = s[vv].to_numpy(dtype=float) if vv else np.zeros((len(s), 1))
    top = m.max(axis=1)
    s['cand'] = np.array([c[1:] for c in vv])[m.argmax(axis=1)] if vv else ''
    with np.errstate(invalid='ignore', divide='ignore'):
        s['pct_cand'] = np.where(s.validos > 0, 100 * top / s.validos, np.nan)
        s['pct_comp'] = np.where(s.aptos > 0, 100 * s.comp / s.aptos, np.nan)
    s['cem'] = (s.validos > 0) & (top == s.validos)
    s['ge99'] = s.pct_cand >= 99
    s['comp_eq_aptos'] = (s.aptos > 0) & (s.comp == s.aptos)
    s['comp_ge99'] = s.pct_comp >= 99
    place = s.groupby(LOC, sort=False, dropna=False).ngroup().values
    ng = place.max() + 1
    k = np.bincount(place, minlength=ng)[place]
    s['local_outras_secoes'] = k - 1
    idx = {c[1:]: i for i, c in enumerate(vv)}
    cand_votos = m[np.arange(len(s)), [idx.get(c, 0) for c in s.cand]] if vv else np.zeros(len(s))
    # votos do mesmo candidato nas outras seções do local
    outras_cand = np.zeros(len(s))
    for c, i in idx.items():
        sel = s.cand.values == c
        if sel.any():
            tot = np.bincount(place, weights=m[:, i], minlength=ng)[place]
            outras_cand[sel] = (tot - m[:, i])[sel]
    outras_val = np.bincount(place, weights=s.validos.values.astype(float), minlength=ng)[place] - s.validos.values
    outras_comp = np.bincount(place, weights=s.comp.values.astype(float), minlength=ng)[place] - s.comp.values
    outras_apt = np.bincount(place, weights=s.aptos.values.astype(float), minlength=ng)[place] - s.aptos.values
    with np.errstate(invalid='ignore', divide='ignore'):
        s['local_outras_pct_cand'] = np.where(outras_val > 0, 100 * outras_cand / outras_val, np.nan)
        s['local_outras_pct_comp'] = np.where(outras_apt > 0, 100 * outras_comp / outras_apt, np.nan)
    s['votos_cand'] = cand_votos
    mun = s.groupby(['uf', 'municipality'], sort=False)
    s['candidatos_com_voto_no_municipio'] = mun[vv].transform('sum').gt(0).sum(axis=1).values if vv else 0
    return s


def resume_extremos(s, pleito, cargo):
    s = s.assign(grupo=np.where(s.uf.eq(EXTERIOR), 'exterior', 'país'))
    g = s.groupby(['uf'], sort=True)
    r = pd.DataFrame({
        'secoes': g.size(), 'cem_pct': g.cem.sum(), 'cem_pct_aptos50': g.apply(
            lambda t: int((t.cem & (t.aptos >= MIN_APTOS)).sum()), include_groups=False),
        'cem_pct_secao_unica_local': g.apply(lambda t: int((t.cem & (t.local_outras_secoes == 0)).sum()),
                                             include_groups=False),
        'cem_pct_candidato_unico_mun': g.apply(lambda t: int((t.cem & (t.candidatos_com_voto_no_municipio <= 1)).sum()),
                                               include_groups=False),
        'ge99_pct': g.ge99.sum(), 'comp_igual_aptos': g.comp_eq_aptos.sum(),
        'comp_igual_aptos_aptos50': g.apply(lambda t: int((t.comp_eq_aptos & (t.aptos >= MIN_APTOS)).sum()),
                                            include_groups=False),
        'comp_ge99_aptos': g.comp_ge99.sum(),
        'comp_maior_aptos': g.apply(lambda t: int((t.comp > t.aptos).sum()), include_groups=False)}).reset_index()
    r.insert(0, 'cargo', cargo)
    r.insert(0, 'pleito', pleito)
    return r


# ------------------------------------------------------------------------------------- C5-10 (presidente x governador)
def classifica_pres_gov(p, g):
    """Junta presidente (p) e governador (g) por seção (municipality, zone, section) e classifica a diferença.
    dc = comparecimento pres - gov; da = aptos pres - gov. Eleitor em trânsito de outra UF está apto e vota só para
    presidente, então 0 < dc <= da é compatível com trânsito; dc > da, dc < 0 ou da < 0 não são."""
    k = ['municipality', 'zone', 'section']
    cp = ['aptos', 'comp', 'branco', 'nulo', 'validos', 'status', 'voting_place']
    j = p[['uf'] + k + cp].merge(g[k + cp], on=k, how='outer', suffixes=('_p', '_g'), indicator=True)
    j['uf'] = j.uf.fillna(g.uf.iloc[0] if len(g) else '')
    dc = j.comp_p - j.comp_g
    da = j.aptos_p - j.aptos_g
    j['dc'] = dc
    j['da'] = da
    cls = np.select(
        [j._merge.eq('left_only'), j._merge.eq('right_only'),
         j.status_p.ne('OK') | j.status_g.ne('OK'),
         (dc == 0) & (da == 0), (dc == 0) & (da > 0), (dc > 0) & (dc <= da), (dc > 0) & (dc > da),
         dc < 0, da < 0],
        ['NOT_COMPARABLE: sem BU de governador', 'NOT_COMPARABLE: sem BU de presidente',
         'NOT_COMPARABLE: quarentena ou sem BU num dos cargos',
         'igual', 'aptos só-presidente sem comparecimento', 'presidente maior, dentro dos aptos só-presidente',
         'presidente maior que os aptos só-presidente explicam', 'governador maior', 'aptos governador maior'],
        'outro')
    j['classe'] = cls
    with np.errstate(invalid='ignore', divide='ignore'):
        j['bn_p_pct'] = 100 * (j.branco_p + j.nulo_p) / j.comp_p
        j['bn_g_pct'] = 100 * (j.branco_g + j.nulo_g) / j.comp_g
    j['gap_bn_pp'] = j.bn_g_pct - j.bn_p_pct
    return j.drop(columns=['_merge'])


def gap_bn_predio(j):
    """z do gap branco+nulo (governador - presidente) contra as outras seções do prédio (>= 3 pares; desvio dos pares)."""
    ok = (j.classe.isin(['igual', 'aptos só-presidente sem comparecimento',
                         'presidente maior, dentro dos aptos só-presidente']) & (j.aptos_p >= MIN_APTOS)
          & j.gap_bn_pp.notna() & j.voting_place_p.notna()).values
    place = j.groupby(['uf', 'municipality', 'zone', 'voting_place_p'], sort=False, dropna=False).ngroup().values
    x = j.gap_bn_pp.fillna(0).values
    npeer, _, var = _loo(place, ok, x, np.ones(len(j)))
    c = ok.astype(float)
    ng = place.max() + 1
    s1 = np.bincount(place, weights=x * c, minlength=ng)[place] - x * c
    with np.errstate(invalid='ignore', divide='ignore'):
        mean_u = np.where(npeer > 0, s1 / npeer, np.nan)
        z = (x - mean_u) / np.sqrt(var)
    z = np.where(ok & (npeer >= MIN_PARES) & (var > 0), z, np.nan)
    return z, mean_u


# -------------------------------------------------------------------------------------------------------- execução
def rss_mb():
    try:
        import psutil
        return round(psutil.Process().memory_info().rss / 1e6)
    except Exception:  # noqa: BLE001
        return None


def pico_mb():
    try:
        import psutil
        mi = psutil.Process().memory_info()
        return round(getattr(mi, 'peak_wset', mi.rss) / 1e6)
    except Exception:  # noqa: BLE001
        return None


def lista_extremos(e, pleito, cargo):
    cols = ['uf', 'municipality', 'zone', 'section', 'voting_place', 'aptos', 'comp', 'pct_comp', 'validos', 'branco',
            'nulo', 'cand', 'votos_cand', 'pct_cand', 'cem', 'comp_eq_aptos', 'local_outras_secoes',
            'local_outras_pct_cand', 'local_outras_pct_comp', 'candidatos_com_voto_no_municipio', 'status']
    cols = [c for c in cols if c in e] + [c for c in ('agregada', 'tipo_urna') if c in e]
    lst = e.loc[e.cem | e.comp_eq_aptos, cols].copy()
    lst.insert(0, 'cargo', cargo)
    lst.insert(0, 'pleito', pleito)
    lst['explicacao_candidata'] = np.select(
        [lst.cem & (lst.candidatos_com_voto_no_municipio <= 1), lst.cem & (lst.local_outras_secoes == 0),
         lst.cem & (lst.local_outras_pct_cand >= 95), lst.comp_eq_aptos & (lst.aptos < MIN_APTOS)],
        ['candidato único com voto no município', 'seção única no local', 'outras seções do local >= 95% para o mesmo',
         'seção com menos de 50 aptos'], '')
    return lst


def roda_extremos_outros(cargo):
    """C5-07 em governador ou prefeito (BWEB), um arquivo por vez."""
    res, lst, arqs = [], [], []
    for cargo, pleitos in [(cargo, PLEITOS_GOV if cargo == 'GOVERNADOR' else PLEITOS_PREF)]:
        for pleito in pleitos:
            for uf in UFS:
                if not (BWEB / pleito / f'{uf}_{cargo}.parquet').exists():
                    continue
                s, _ = carrega_bweb(pleito, uf, cargo, checagem='C5-07')
                if s is None:
                    continue
                e = marca_extremos(s)
                res.append(resume_extremos(e, pleito, cargo))
                lst.append(lista_extremos(e, pleito, cargo))
                arqs.append(f'{pleito}/{uf}_{cargo}')
                del s, e
            gc.collect()
            print('C5-07', cargo, pleito, flush=True)
    return res, lst, arqs


def roda_pres_gov():
    """C5-10: presidente x governador na mesma seção, todos os pleitos com governador no BWEB."""
    tabs, nexp, gaps = [], [], []
    cache26 = None
    for pleito in PLEITOS_GOV:
        for uf in UFS:
            fg = BWEB / pleito / f'{uf}_GOVERNADOR.parquet'
            if not fg.exists():
                continue
            g, _ = carrega_bweb(pleito, uf, 'GOVERNADOR', checagem='C5-10')
            if g is None:
                continue
            if pleito.startswith('2026'):
                if cache26 is None:
                    cache26 = carrega_2026(1, checagem='C5-10')
                p = cache26[cache26.uf.eq(uf)].copy()
            else:
                p, _ = carrega_bweb(pleito, uf, 'PRESIDENTE', checagem='C5-10')
            j = classifica_pres_gov(p, g)
            j['z_gap_bn'], j['gap_bn_pares'] = gap_bn_predio(j)
            j.insert(0, 'pleito', pleito)
            tabs.append(resumo_pres_gov(j))
            m = j.classe.isin(['presidente maior que os aptos só-presidente explicam', 'governador maior',
                               'aptos governador maior', 'outro']) | j.classe.str.startswith('NOT_COMPARABLE')
            nexp.append(j[m])
            gaps.append(j[np.abs(j.z_gap_bn.fillna(0)) >= Z_LIM])
            del g, p, j
            gc.collect()
        print('C5-10', pleito, flush=True)
    return tabs, nexp, gaps


def resumo_pres_gov(j):
    g = j.groupby(['pleito', 'uf'])
    r = g.size().rename('secoes').to_frame()
    for c in ['igual', 'aptos só-presidente sem comparecimento', 'presidente maior, dentro dos aptos só-presidente',
              'presidente maior que os aptos só-presidente explicam', 'governador maior', 'aptos governador maior',
              'NOT_COMPARABLE: sem BU de governador', 'NOT_COMPARABLE: sem BU de presidente',
              'NOT_COMPARABLE: quarentena ou sem BU num dos cargos', 'outro']:
        r[c] = g.classe.apply(lambda s, c=c: int((s == c).sum()))
    ok = j.classe.isin(['igual', 'aptos só-presidente sem comparecimento',
                        'presidente maior, dentro dos aptos só-presidente',
                        'presidente maior que os aptos só-presidente explicam', 'governador maior',
                        'aptos governador maior'])
    jj = j[ok]
    gg = jj.groupby(['pleito', 'uf'])
    r['pct_comp_igual'] = 100 * gg.apply(lambda t: (t.dc == 0).mean(), include_groups=False)
    r['soma_dc'] = gg.dc.sum()
    r['soma_da'] = gg.da.sum()
    r['comparecimento_dos_aptos_so_presidente_pct'] = 100 * r.soma_dc / r.soma_da
    r['comparecimento_geral_pct'] = 100 * gg.comp_p.sum() / gg.aptos_p.sum()
    r['max_dc'] = gg.dc.max()
    r['secoes_dc_ge_20'] = gg.apply(lambda t: int((t.dc >= 20).sum()), include_groups=False)
    r['bn_presidente_pct'] = 100 * gg.apply(lambda t: (t.branco_p + t.nulo_p).sum() / t.comp_p.sum(),
                                            include_groups=False)
    r['bn_governador_pct'] = 100 * gg.apply(lambda t: (t.branco_g + t.nulo_g).sum() / t.comp_g.sum(),
                                            include_groups=False)
    r['gap_bn_testadas'] = gg.z_gap_bn.apply(lambda s: int(s.notna().sum()))
    r['gap_bn_z_ge4'] = gg.z_gap_bn.apply(lambda s: int((s.abs() >= Z_LIM).sum()))
    return r.reset_index()


def grava_resumo(resumo):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'C5b_resumo.json').write_text(json.dumps(resumo, ensure_ascii=False, indent=1, default=str),
                                         encoding='utf-8')
    p = OUT / 'C5_resumo.json'
    old = {}
    if p.exists():
        try:
            old = json.loads(p.read_text(encoding='utf-8'))
        except ValueError:
            old = {}
    chk = old.get('checagens', {}) if isinstance(old.get('checagens'), dict) else {}
    chk.update(resumo['checagens'])
    old.update({'camada': 'C5', 'checagens': chk, 'atualizado_parte_B': resumo['at']})
    p.write_text(json.dumps(old, ensure_ascii=False, indent=1, default=str), encoding='utf-8')


PARCIAL = CACHE / 'parcial'
PLEITOS_PREF = ['2012-t1', '2012-t2', '2016-t1', '2016-t2', '2020-t1', '2020-t2', '2024-t1', '2024-t2']


def roda_presidente(checks, pleitos=PLEITOS_PRES):
    """Uma passada por pleito presidencial: C5-02 (modelo do prédio), C5-11 (vizinhas) e C5-07 (extremos).
    Semente por pleito (independe da ordem e de qual processo roda o pleito)."""
    fams, dests, sts, viz, ext_r, ext_l, info = [], [], [], [], [], [], {}
    for pleito in pleitos:
        rng = np.random.default_rng([SEED, PLEITOS_PRES.index(pleito)])
        t0 = time.time()
        s, nomes = carrega_pleito_pres(pleito)
        s['ref_status'] = status_referencia(s)
        info[pleito] = {'secoes': int(len(s)), 'quarentena': int(s.status.str.startswith('QUARENTENA').sum()),
                        'agregadas': int(s.agregada.sum()), 'rss_mb_apos_leitura': rss_mb()}
        if 'C5-02' in checks:
            fam, dest, st, Z = c5_02_pleito(pleito, s, nomes, rng)
            fams.append(fam)
            if len(dest):
                dests.append(dest)
            sts.append(st)
            inp = {k: v for k, v in _INPUTS.items() if pleito in k or (pleito.startswith('2026') and 'secoes_t1_t2' in k)}
            grava_parquet(Z, CACHE / f'z_predio_{pleito}.parquet', inp)
            del Z
            gc.collect()
        info[pleito]['rss_mb_apos_C5-02'] = rss_mb()
        if 'C5-11' in checks:
            man = carrega_manual(pleito)
            n_beh = 0
            for uf, su in s.groupby('uf', sort=True):
                if uf == EXTERIOR:
                    continue
                mu = None if man is None else man[man.uf.eq(uf)]
                r, nb = c5_11_pleito(pleito, su, mu)
                viz.append(r)
                n_beh += nb
            del man
            info[pleito]['secoes_manual_aproximado'] = n_beh
        if 'C5-07' in checks:
            for uf, su in s.groupby('uf', sort=True):
                e = marca_extremos(su)
                ext_r.append(resume_extremos(e, pleito, 'PRESIDENTE'))
                ext_l.append(lista_extremos(e, pleito, 'PRESIDENTE'))
                del e
        info[pleito]['segundos'] = round(time.time() - t0, 1)
        info[pleito]['rss_mb_fim'] = rss_mb()
        info[pleito]['rss_mb_pico'] = pico_mb()
        print(pleito, info[pleito], flush=True)
        del s
        gc.collect()
    return fams, dests, sts, viz, ext_r, ext_l, info


def _concat(lst):
    lst = [x for x in lst if x is not None and len(x)]
    return pd.concat(lst, ignore_index=True) if lst else pd.DataFrame()


def salva_parcial(etapa, tabelas, info):
    """Resultado de uma etapa (um processo) em research/varredura_forense/C5b/parcial/<etapa>.pkl."""
    PARCIAL.mkdir(parents=True, exist_ok=True)
    nome = etapa.replace(':', '_')
    pd.to_pickle({'tabelas': {k: _concat(v) for k, v in tabelas.items()}, 'info': info,
                  'quarentena': list(_QUARENTENA), 'inputs': dict(_INPUTS)}, PARCIAL / f'{nome}.pkl')


def roda_etapa(etapa, checks):
    """Executa uma etapa isolada (chamada em subprocesso, um de cada vez)."""
    tipo, _, arg = etapa.partition(':')
    if tipo == 'pres':
        fams, dests, sts, viz, ext_r, ext_l, info = roda_presidente(checks, [arg])
        salva_parcial(etapa, {'fam': fams, 'dest': dests, 'st': sts, 'viz': viz, 'ext_r': ext_r, 'ext_l': ext_l},
                      info)
    elif tipo == 'outros':
        res, lst, arqs = roda_extremos_outros(arg)
        salva_parcial(etapa, {'ext_r': res, 'ext_l': lst}, {'arquivos_bweb_lidos': arqs, 'rss_mb_pico': pico_mb()})
    elif tipo == 'presgov':
        tabs, nexp, gaps = roda_pres_gov()
        salva_parcial(etapa, {'pg': tabs, 'pg_nexp': nexp, 'pg_gap': gaps}, {'rss_mb_pico': pico_mb()})
    else:
        raise ValueError(etapa)


def etapas(checks):
    e = []
    if checks & {'C5-02', 'C5-11', 'C5-07'}:
        e += [f'pres:{p}' for p in PLEITOS_PRES]
    if 'C5-07' in checks:
        e += ['outros:GOVERNADOR', 'outros:PREFEITO']
    if 'C5-10' in checks:
        e.append('presgov')
    return e


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == 'etapa':
        roda_etapa(argv[1], set(argv[2:]) or {'C5-02', 'C5-10', 'C5-11', 'C5-07'})
        return None
    agregar_so = bool(argv) and argv[0] == 'agrega'
    if agregar_so:
        argv = argv[1:]
    checks = set(argv) if argv else {'C5-02', 'C5-10', 'C5-11', 'C5-07'}
    import subprocess
    lista = etapas(checks)
    if not agregar_so:
        for et in lista:
            # um processo por etapa, em série: a memória de cada pleito é devolvida ao sistema ao fim do processo
            subprocess.run([sys.executable, str(Path(__file__).resolve()), 'etapa', et, *sorted(checks)], check=True)
    return agrega(lista, checks)


def agrega(lista, checks):
    resumo = {'at': agora(), 'protocolo': 'PROTOCOLO.md v1.0', 'parser_version': PARSER_VERSION, 'checagens': {},
              'etapas': {}}
    T = {}
    for et in lista:
        d = pd.read_pickle(PARCIAL / f"{et.replace(':', '_')}.pkl")
        resumo['etapas'][et] = d['info']
        _QUARENTENA.extend(d['quarentena'])
        _INPUTS.update(d['inputs'])
        for k, v in d['tabelas'].items():
            T.setdefault(k, []).append(v)
    T = {k: _concat(v) for k, v in T.items()}
    if 'C5-02' in checks:
        fam = T['fam']
        nac = resumo_nacional(fam)
        resumo['checagens']['C5-02'] = {
            'arquivos': [csv_out('C5-02_familias_por_uf.csv', fam), csv_out('C5-02_resumo_nacional.csv', nac),
                         csv_out('C5-02_comparacao_pleitos.csv', comparacao_pleitos(nac)),
                         csv_out('C5-02_secoes_destoantes.csv', T['dest']),
                         csv_out('C5-02_status_comparabilidade.csv', T['st'])],
            'linhas_destoantes': int(len(T['dest']))}
    if 'C5-11' in checks:
        resumo['checagens']['C5-11'] = {'arquivos': [csv_out('C5-11_vizinhas_por_uf.csv', T['viz']),
                                                     csv_out('C5-11_vizinhas_agregado.csv', agrega_vizinhas(T['viz']))]}
    if 'C5-07' in checks:
        resumo['checagens']['C5-07'] = {'arquivos': [csv_out('C5-07_extremos_por_uf.csv', T['ext_r']),
                                                     csv_out('C5-07_extremos_secoes.csv', T['ext_l'])]}
    if 'C5-10' in checks:
        resumo['checagens']['C5-10'] = {'arquivos': [csv_out('C5-10_pres_gov_por_uf.csv', T['pg']),
                                                     csv_out('C5-10_secoes_nao_explicadas.csv', T['pg_nexp']),
                                                     csv_out('C5-10_gap_branco_nulo_destoantes.csv', T['pg_gap'])]}
    resumo['quarentena'] = grava_quarentena()
    resumo['entradas_sha256'] = _INPUTS
    grava_resumo(resumo)
    return resumo


if __name__ == '__main__':
    main()
