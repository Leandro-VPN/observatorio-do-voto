"""Varredura forense, camada C6 (entre eleicoes: estabilidade, mudancas e regimes): checagens leves sobre parquet/CSV existentes.

Uma funcao por checagem (`roda_c6_XX`). As funcoes puras (`geracao_por_serial`, `parse_dt_br`, `deriva_calendario`, `z_m1`,
`centra`, `fe_ols`, `teste_atributo`, `permuta_dentro`, `classifica_vinculo`, `recorrencia`, `forma_z`, `spearman_matriz`,
`residuo_loo`, `bh`) recebem arrays/DataFrames e devolvem DataFrames/dicionarios; os carregadores leem o disco com projecao de
colunas e DuckDB limitado (400 MB, 2 threads), uma UF por vez quando a tabela nacional e grande. `main()` roda as checagens
pedidas e grava relatorios/verificacoes/varredura_forense/C6/ (CSVs `C6-XX_*.csv`, `C6_resumo.json`, `C6_achados.json`,
`quarentena_C6.csv`); as tabelas por secao (atributos tecnicos e z por eleicao) vao para research/varredura_forense/c6/ com
recibo <arquivo>.json. Importavel sem efeito pesado.

Protocolo: relatorios/verificacoes/varredura_forense/PROTOCOLO.md v1.0. Tudo aqui e descritivo: "diferenca acima do limiar",
"comportamento" e "prioridade de observacao" descrevem medidas, nao indicam irregularidade por si so.

Geracao da urna pelo numero de serie (faixas medidas no certificado da urna, integridade_todas_urnas.parquet):
AC URNA (todos os modelos anteriores a 2020; rotulo AC_URNA_pre2020) 1.000.001-1.850.052; AC UE2020 2.000.009-2.248.576;
AC UE2022 2.250.001-2.474.677 (2024/2026). A faixa AC URNA nao separa UE2004..UE2015 (modelo fino so no log: C6-05/C6-14).

Regras de inferencia: efeito de atributo tecnico medido com efeito fixo de predio (local de votacao) e, em C6-07, de zona;
erro-padrao robusto agrupado por predio (CR1); nulo por permutacao do atributo dentro do predio (N_PERM permutacoes, semente
SEED); BH a 5% por familia (checagem x pleito x desfecho); "regime tecnico" so e sinalizado se sobreviver ao efeito fixo e
aparecer com o mesmo sinal em mais de uma UF.
Uso: python scripts/varredura_forense_c6.py [C6-01 C6-02 ...]   (sem argumentos: todas as checagens leves)
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
from scipy.special import expit, logit

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / 'research'
REL = ROOT / 'relatorios'
OUT = REL / 'verificacoes' / 'varredura_forense' / 'C6'
QUAR = R / 'varredura_forense' / 'quarentena'
INTER = R / 'varredura_forense' / 'c6'
CSV = dict(sep=';', decimal=',', encoding='utf-8-sig', index=False)
PARSER_VERSION = 'varredura-forense-c6-1'
SEED = 20261105
N_PERM = 50
KEY = ['uf', 'municipality', 'zone', 'section']
UFS11 = ['BA', 'CE', 'MA', 'MG', 'PA', 'PE', 'PR', 'RJ', 'RS', 'SC', 'SP']
UFS = ['AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MG', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI', 'PR', 'RJ', 'RN', 'RO',
       'RR', 'RS', 'SC', 'SE', 'SP', 'TO', 'ZZ']
NOT_COMP = 'NOT_COMPARABLE'
MIN_APTOS = 50
MIN_N = 30                     # mesmo corte do modelo do local (padroes_lib.MIN_N)
EPS = .005
ALFA = 0.05
Z_ISOLADA = 4.0
# faixas de serie por geracao (limites inclusivos; arredondados para fora das faixas medidas, sem sobreposicao)
FAIXAS_SERIAL = [('anterior_2009', 1, 999_999), ('AC_URNA_pre2020', 1_000_000, 1_899_999), ('UE2020', 2_000_000, 2_249_999),
                 ('UE2022', 2_250_000, 2_499_999)]
CERT_GERACAO = {'AC URNA': 'AC_URNA_pre2020', 'AC UE2020': 'UE2020', 'AC UE2022': 'UE2022'}
LOTE_SERIAL = 25_000           # bloco de numeros de serie usado como "lote" (proxy de fabricacao/distribuicao)
DATAS = {'2014-t1': '2014-10-05', '2014-t2': '2014-10-26', '2018-t1': '2018-10-07', '2018-t2': '2018-10-28',
         '2022-t1': '2022-10-02', '2022-t2': '2022-10-30', '2024-t1': '2024-10-06', '2024-t2': '2024-10-27',
         '2026-t1': '2026-10-04', '2026-t2': '2026-10-25'}
PLEITOS_BWEB = ['2014-t1', '2014-t2', '2018-t1', '2018-t2', '2022-t1', '2022-t2']
ANOS = [2014, 2018, 2022, 2026]
ROTULOS_IND = {'P2022': '2022-t1', 'P2022b': '2022-t2', 'M2024': '2024-t1', 'M2024b': '2024-t2', 'P2026': '2026-t1'}
# colunas do BWEB por ano (a primeira que existir no arquivo)
COLS_BWEB = {
    'serial': ['NR_URNA_EFETIVADA'], 'carga': ['DT_CARGA_URNA_EFETIVADA', 'DT_CARGA'],
    'flashcard': ['CD_FLASHCARD_URNA_EFETIVADA', 'CD_FLASCARD_URNA_EFETIVADA', 'CD_FLASHCARD'],
    'ds_agregadas': ['DS_SECOES_AGREGADAS', 'DS_AGREGADAS'], 'abertura': ['DT_ABERTURA'], 'encerramento': ['DT_ENCERRAMENTO'],
    'recebido': ['DT_BU_RECEBIDO'], 'emissao': ['DT_EMISSAO_BU'], 'junta': ['NR_JUNTA_APURADORA'], 'tipo_urna': ['DS_TIPO_URNA'],
    'voting_place': ['NR_LOCAL_VOTACAO'], 'aptos': ['QT_APTOS'], 'comp': ['QT_COMPARECIMENTO'],
    'biom_nh': ['QT_ELEI_BIOM_SEM_HABILITACAO', 'QT_ELEITORES_BIOMETRIA_NH']}
NULOS_TXT = {'', '#NULO#', '#NULO', '-1', '-3', 'NAN', 'NONE', '#NE#', '#NE'}
CHECAGENS = ['C6-01', 'C6-02', 'C6-03', 'C6-06', 'C6-07', 'C6-08', 'C6-09', 'C6-10', 'C6-13', 'C6-11', 'C6-12']
PENDENTES = {
    'C6-04': 'nao_feita: depende da passada pesada de BUs. A passada deve extrair do BU binario de cada urna (2022 T1 a 2026 T2, '
             'todas as UFs) a sequencia de identificacao da urna e da carga (conferir nomes na especificacao bu.asn1: numero '
             'interno/serie da urna, tipo/modelo, versao do software de votacao, codigo e data/hora da carga, serie do flashcard) e '
             'gravar research/padroes_2t/urna_<pleito>.parquet por stem; validar serie contra NR_URNA_EFETIVADA do BWEB 2022 e do '
             'CEFT (11 UFs); com isso C6-02/C6-07 passam a cobrir 2026 T2 no pais (hoje: so a amostra de 28.823 urnas da integridade).',
    'C6-05': 'nao_feita: depende da passada pesada de logs. A passada deve ler as ~150 primeiras linhas de cada logd.dat '
             '(read_log merge=True, logs aninhados) e extrair "Identificacao do Modelo de Urna", "Versao da aplicacao", "Versao do '
             'UEFI", "Midia de carga gerada pelo computador", data/hora da geracao da midia, "Codigo de carga", serie da impressora e '
             'o 3o campo (serie em 2024/2026), por stem, para 2022 T1/T2, 2024 T1/T2 e 2026 T1/T2; depois repetir teste_atributo '
             '(este script) com modelo fino (UE2009/2010/2011/2013/2015/2020/2022) e versao.',
}
_QUARENTENA: list[dict] = []
_ACHADOS_N: dict[str, int] = {}


# ----------------------------------------------------------------------------------------------- utilidades
def duck():
    import duckdb
    con = duckdb.connect()
    con.execute("SET memory_limit='300MB'")
    con.execute('SET threads=2')
    return con


def _p(path):
    return str(path).replace('\\', '/')


def quarentena(checagem, df, reason):
    """Linhas que falham invariante: valores originais como string + motivo (JSON por checagem e CSV unico)."""
    if df is None or len(df) == 0:
        return 0
    rows = [{k: ('' if (not isinstance(v, (list, tuple)) and pd.isna(v)) else str(v)) for k, v in r.items()}
            | {'reason': reason, 'checagem': checagem} for r in df.to_dict('records')]
    QUAR.mkdir(parents=True, exist_ok=True)
    p = QUAR / f'rows-C6-{checagem}.json'
    old = json.loads(p.read_text(encoding='utf-8')) if p.exists() else []
    vistos, todas = set(), []
    for r in old + rows:
        k = json.dumps(r, sort_keys=True, ensure_ascii=False)
        if k not in vistos:
            vistos.add(k)
            todas.append(r)
    p.write_text(json.dumps(todas, ensure_ascii=False, indent=1), encoding='utf-8')
    _QUARENTENA.extend(rows)
    return len(rows)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for bloco in iter(lambda: f.read(1 << 20), b''):
            h.update(bloco)
    return h.hexdigest()


def recibo(path, inputs, rows):
    """Recibo <arquivo>.json ao lado do parquet: {at, inputs:{caminho: sha256}, sha256, rows, bytes, parser_version}."""
    path = Path(path)
    rec = {'at': dt.datetime.now(dt.timezone.utc).isoformat(),
           'inputs': {str(i): _sha256(i) for i in inputs if Path(i).exists() and Path(i).is_file()},
           'sha256': _sha256(path), 'rows': int(rows), 'bytes': path.stat().st_size, 'parser_version': PARSER_VERSION}
    Path(str(path) + '.json').write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding='utf-8')
    return rec


def csv_out(nome, df):
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / nome, **CSV)
    return str(OUT / nome)


def ler_csv(nome):
    return pd.read_csv(OUT / nome, sep=';', decimal=',', encoding='utf-8-sig')


def chave_stem(stems):
    """Series de stems -> DataFrame(municipality, zone, section) pelos 13 digitos finais; invalido fica NaN."""
    s = pd.Series(stems, dtype='string').reset_index(drop=True)
    d = s.str[-13:]
    ok = d.str.isdigit().fillna(False) & (s.str.len() >= 13)
    return pd.DataFrame({'municipality': pd.to_numeric(d.str[:5].where(ok), errors='coerce'),
                         'zone': pd.to_numeric(d.str[5:9].where(ok), errors='coerce'),
                         'section': pd.to_numeric(d.str[9:13].where(ok), errors='coerce')})


def predio_id(df):
    """Local de votacao: o numero so e unico dentro da zona -> uf|municipio|zona|local; local nulo -> NaN."""
    vp = pd.to_numeric(df['voting_place'], errors='coerce')
    k = (df['uf'].astype(str) + '|' + df['municipality'].astype('Int64').astype(str) + '|' + df['zone'].astype('Int64').astype(str)
         + '|' + vp.astype('Int64').astype(str))
    return k.where(vp.notna())


def zona_id(df):
    return df['uf'].astype(str) + '|' + df['zone'].astype('Int64').astype(str)


def _int_keys(d):
    for c in ('municipality', 'zone', 'section'):
        d[c] = pd.to_numeric(d[c], errors='coerce').astype('Int64')
    return d


# ----------------------------------------------------------------------------------------------- funcoes puras
def geracao_por_serial(serial):
    """Numero de serie da urna -> geracao pela faixa (FAIXAS_SERIAL). Nulo -> 'sem_serial'; fora das faixas -> 'fora_das_faixas'."""
    s = pd.to_numeric(pd.Series(serial).reset_index(drop=True), errors='coerce')
    out = pd.Series('fora_das_faixas', index=s.index, dtype=object)
    for nome, lo, hi in FAIXAS_SERIAL:
        out[(s >= lo) & (s <= hi)] = nome
    out[s.isna()] = 'sem_serial'
    return out


def parse_dt_br(s):
    """Datas do TSE: 'dd/mm/aaaa hh:mm:ss', 'dd/mm/aaaa hh:mm', 'dd/mm/aaaa', ISO 'aaaa-mm-dd hh:mm:ss' ou 'aaaammddThhmmss'.
    Texto nulo do TSE (#NULO#, -1...) e invalido -> NaT."""
    s = pd.Series(s, dtype='string').str.strip()
    s = s.where(~s.str.upper().isin(NULOS_TXT))
    out = pd.Series(pd.NaT, index=s.index, dtype='datetime64[ns]')
    for fmt in ('%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%d/%m/%Y', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d', '%Y%m%dT%H%M%S'):
        falta = out.isna() & s.notna()
        if not falta.any():
            break
        out[falta] = pd.to_datetime(s[falta], format=fmt, errors='coerce')
    return out


def deriva_calendario(d, data_pleito, col='carga'):
    """Variaveis de calendario da carga: dias antes do pleito (data), dia da semana, hora, carga no proprio dia,
    carga depois do dia (invariante violado) e ordem da carga dentro da zona (posto percentual 0-1; empates = media)."""
    c = pd.to_datetime(d[col])
    dia = pd.Timestamp(data_pleito)
    out = pd.DataFrame(index=d.index)
    out['dias_antes'] = (dia - c.dt.normalize()).dt.days.astype('Int64')
    out['carga_dow'] = c.dt.dayofweek.astype('Int64')
    tem_hora = (c.dt.hour + c.dt.minute) > 0
    out['carga_hora'] = c.dt.hour.where(tem_hora).astype('Int64')
    out['carga_no_dia'] = out['dias_antes'].eq(0)
    out['carga_apos_dia'] = out['dias_antes'].lt(0)
    z = zona_id(d)
    out['ordem_carga_zona'] = c.groupby(z).rank(pct=True, method='average')
    return out


def faixa_dias(dias):
    """Dias antes do pleito -> faixa categorica."""
    x = pd.to_numeric(pd.Series(dias), errors='coerce')
    bins = [-1e9, -1, 0, 3, 6, 10, 20, 1e9]
    lab = ['apos_dia', 'no_dia', '1-3', '4-6', '7-10', '11-20', '21+']
    return pd.cut(x, bins=bins, labels=lab).astype(object).where(x.notna(), 'sem_carga')


def _lg(a, b):
    return logit(np.clip((np.asarray(a, float) + .5) / (np.asarray(b, float) + 1), EPS, 1 - EPS))


def z_m1(d):
    """Residuo do modelo do local (padroes_lib.modelo_local / janelas_horario.res_m1 recalculado), mesma amostra de
    comparacao_eleicoes.prepara: n1, n2 >= MIN_N, predios (uf, municipio, zona, local) com >= 3 secoes. Entrada: uma linha
    por secao com t1_A, t1_B, t2_A, t2_B, uf, municipality, zone, voting_place, section. Devolve copia filtrada com
    n1, n2, place, k, p_loo, res_pp (pontos na fatia de A entre A e B) e z (resíduo de Pearson binomial, sem phi)."""
    e = d.copy()
    e['n1'] = e.t1_A + e.t1_B
    e['n2'] = e.t2_A + e.t2_B
    e = e[(e.n1 >= MIN_N) & (e.n2 >= MIN_N) & e.voting_place.notna()]
    loc = ['uf', 'municipality', 'zone', 'voting_place']
    e = e.sort_values(loc + ['section']).reset_index(drop=True)
    e['place'] = e.groupby(loc, sort=False).ngroup()
    e['k'] = e.groupby('place').section.transform('size')
    e = e[e.k >= 3].reset_index(drop=True)
    g = e.groupby('place')
    S1X, S1N, S2X, S2N = (g[c].transform('sum').to_numpy(float) for c in ('t1_A', 'n1', 't2_A', 'n2'))
    x1, n1, x2, n2 = (e[c].to_numpy(float) for c in ('t1_A', 'n1', 't2_A', 'n2'))
    p = np.clip(expit(_lg(x1, n1) + _lg(S2X - x2, S2N - n2) - _lg(S1X - x1, S1N - n1)), EPS, 1 - EPS)
    e['p_loo'] = p
    e['res_pp'] = 100 * (x2 / n2 - p)
    e['z'] = (x2 / n2 - p) / np.sqrt(p * (1 - p) / np.maximum(n2, 1))
    return e


def codigos(s):
    c, idx = pd.factorize(pd.Series(s).reset_index(drop=True), sort=False)
    return c, idx


def centra(M, codes):
    """M menos a media do seu grupo (efeito fixo); M 1-D ou 2-D; codes inteiros >= 0."""
    M = np.asarray(M, float)
    um = M.ndim == 1
    if um:
        M = M[:, None]
    k = int(codes.max()) + 1 if len(codes) else 0
    n = np.bincount(codes, minlength=k).astype(float)
    out = np.empty_like(M)
    for j in range(M.shape[1]):
        m = np.bincount(codes, weights=M[:, j], minlength=k) / np.where(n > 0, n, 1)
        out[:, j] = M[:, j] - m[codes]
    return out[:, 0] if um else out


def _soma_grupo(M, codes):
    k = int(codes.max()) + 1
    return np.column_stack([np.bincount(codes, weights=M[:, j], minlength=k) for j in range(M.shape[1])])


def fe_ols(y, X, fe_codes, cl_codes, teste=None):
    """OLS de y em X com efeito fixo (centrando y e X no grupo fe_codes) e erro-padrao robusto agrupado (CR1) por cl_codes.
    teste: indices das colunas de X testadas em conjunto (Wald; padrao = todas). Devolve dict com beta, ep, t, wald, gl, p,
    r2_parcial (fracao da variancia de y, depois do efeito fixo e das demais colunas, explicada pelas colunas testadas)."""
    y = np.asarray(y, float)
    X = np.asarray(X, float)
    if X.ndim == 1:
        X = X[:, None]
    yd = centra(y, fe_codes)
    Xd = centra(X, fe_codes)
    viva = Xd.std(axis=0) > 1e-12
    teste = list(range(X.shape[1])) if teste is None else list(teste)
    out = {'n': int(len(y)), 'beta': np.full(X.shape[1], np.nan), 'ep': np.full(X.shape[1], np.nan), 't': np.full(X.shape[1], np.nan),
           'wald': np.nan, 'gl': 0, 'p': np.nan, 'r2_parcial': np.nan}
    if not viva[teste].any() or len(y) < 10:
        return out
    Xv = Xd[:, viva]
    XtX = Xv.T @ Xv
    try:
        inv = np.linalg.inv(XtX)
    except np.linalg.LinAlgError:
        inv = np.linalg.pinv(XtX)
    b = inv @ (Xv.T @ yd)
    u = yd - Xv @ b
    G = _soma_grupo(Xv * u[:, None], cl_codes)
    ng = int((np.bincount(cl_codes) > 0).sum())
    n, kx = Xv.shape
    adj = (ng / max(ng - 1, 1)) * ((n - 1) / max(n - kx, 1))
    V = inv @ (G.T @ G) @ inv * adj
    beta = np.full(X.shape[1], np.nan)
    ep = np.full(X.shape[1], np.nan)
    beta[viva] = b
    ep[viva] = np.sqrt(np.clip(np.diag(V), 0, None))
    pos = {j: i for i, j in enumerate(np.flatnonzero(viva))}
    tt = [pos[j] for j in teste if j in pos]
    bt = b[tt]
    Vt = V[np.ix_(tt, tt)]
    try:
        wald = float(bt @ np.linalg.solve(Vt, bt))
    except np.linalg.LinAlgError:
        wald = float(bt @ np.linalg.pinv(Vt) @ bt)
    # r2 parcial: SSR sem as colunas testadas x com elas
    resto = [i for i in range(kx) if i not in tt]
    if resto:
        Xr = Xv[:, resto]
        br = np.linalg.lstsq(Xr, yd, rcond=None)[0]
        ur = yd - Xr @ br
    else:
        ur = yd
    ssr0, ssr1 = float(ur @ ur), float(u @ u)
    out.update(beta=beta, ep=ep, t=np.where(ep > 0, beta / np.where(ep > 0, ep, 1), np.nan), wald=wald, gl=len(tt),
               p=float(stats.chi2.sf(wald, len(tt))), r2_parcial=(1 - ssr1 / ssr0) if ssr0 > 0 else np.nan,
               var_y_ef=float(yd.var()), clusters=ng)
    return out


def permuta_dentro(valores, grupo, rng):
    """Permuta `valores` entre as linhas do mesmo `grupo` (codigos inteiros). Vetorizado: um lexsort por permutacao."""
    valores = np.asarray(valores)
    grupo = np.asarray(grupo)
    base = np.argsort(grupo, kind='stable')
    ordem = np.lexsort((rng.random(len(grupo)), grupo))
    out = np.empty_like(valores)
    out[ordem] = valores[base]
    return out


def _dummies(a_codes, n_niveis, ref):
    cols = [j for j in range(n_niveis) if j != ref]
    D = np.zeros((len(a_codes), len(cols)))
    for i, j in enumerate(cols):
        D[:, i] = a_codes == j
    return D, cols


def _r2_rapido(yd, a_codes, fe_codes, n_niveis):
    """Fracao da variancia de yd (ja centrado no efeito fixo) explicada pelos niveis do atributo centrados no mesmo efeito fixo."""
    D, _ = _dummies(a_codes, n_niveis, 0)
    Dd = centra(D, fe_codes)
    viva = Dd.std(axis=0) > 1e-12
    if not viva.any():
        return 0.0
    Dd = Dd[:, viva]
    b = np.linalg.lstsq(Dd, yd, rcond=None)[0]
    u = yd - Dd @ b
    return float(1 - (u @ u) / (yd @ yd)) if yd @ yd > 0 else 0.0


def teste_atributo(df, desfecho, atributo, fe='predio', cluster='predio', controles=(), ref=None, n_perm=0, seed=SEED,
                   perm_grupo=None, min_secoes_nivel=30):
    """Efeito de um atributo categorico sobre um desfecho com efeito fixo `fe` (predio/zona), controles continuos opcionais
    (entram em X, nao no teste), erro agrupado por `cluster` e, se n_perm > 0, nulo por permutacao do atributo dentro de
    `perm_grupo` (padrao = fe). Niveis com menos de `min_secoes_nivel` secoes saem (contados em 'secoes_niveis_raros').
    Devolve (resumo dict, tabela por nivel: secoes, media bruta, coef. contra a referencia, ep, t)."""
    cols = [desfecho, atributo, fe, cluster] + list(controles)
    d = df.dropna(subset=list(dict.fromkeys(cols))).reset_index(drop=True)
    vc = d[atributo].value_counts()
    raros = vc[vc < min_secoes_nivel].index
    n_raros = int(d[atributo].isin(raros).sum())
    d = d[~d[atributo].isin(raros)].reset_index(drop=True)
    res = {'desfecho': desfecho, 'atributo': atributo, 'fe': fe, 'controles': '+'.join(controles) or '-', 'n': int(len(d)),
           'secoes_niveis_raros': n_raros}
    if len(d) < 50 or d[atributo].nunique() < 2:
        res.update(status=NOT_COMP, motivo='menos de 2 niveis com >= %d secoes ou < 50 secoes' % min_secoes_nivel)
        return res, pd.DataFrame()
    niveis = list(vc[vc >= min_secoes_nivel].index)
    if ref is not None and ref in niveis:
        niveis.remove(ref)
        niveis = [ref] + niveis
    a_codes = pd.Categorical(d[atributo], categories=niveis).codes.astype(int)
    fe_c, _ = codigos(d[fe])
    cl_c, _ = codigos(d[cluster])
    D, cols_d = _dummies(a_codes, len(niveis), 0)
    C = d[list(controles)].to_numpy(float) if controles else np.zeros((len(d), 0))
    X = np.c_[D, C]
    y = d[desfecho].to_numpy(float)
    r = fe_ols(y, X, fe_c, cl_c, teste=range(D.shape[1]))
    # unidades de efeito fixo com mais de um nivel (so elas informam o efeito)
    pa = pd.DataFrame({'g': fe_c, 'a': a_codes}).drop_duplicates().groupby('g').size()
    mistos = int((pa > 1).sum())
    sec_mistas = int(pa.reindex(fe_c).to_numpy().__gt__(1).sum())
    res.update(status='feita', niveis=len(niveis), referencia=niveis[0], unidades_fe=int(len(pa)), unidades_fe_mistas=mistos,
               secoes_em_unidades_mistas=sec_mistas, wald=r['wald'], gl=r['gl'], p=r['p'], r2_parcial=r['r2_parcial'],
               var_y_ef=r.get('var_y_ef', np.nan), clusters=r.get('clusters', 0))
    if n_perm and mistos > 0:
        pg, _ = codigos(d[perm_grupo or fe])
        rng = np.random.default_rng(seed)
        yd = centra(y, fe_c)
        if controles:
            Cd = centra(C, fe_c)
            yd = yd - Cd @ np.linalg.lstsq(Cd, yd, rcond=None)[0]
        real = _r2_rapido(yd, a_codes, fe_c, len(niveis))
        perms = np.array([_r2_rapido(yd, permuta_dentro(a_codes, pg, rng), fe_c, len(niveis)) for _ in range(n_perm)])
        res.update(r2_perm_real=real, r2_perm_p95=float(np.quantile(perms, .95)), p_perm=float((np.sum(perms >= real) + 1) / (n_perm + 1)),
                   n_perm=n_perm)
    n = np.bincount(a_codes, minlength=len(niveis))
    mb = np.bincount(a_codes, weights=y, minlength=len(niveis)) / np.where(n > 0, n, 1)
    tab = pd.DataFrame({'nivel': niveis, 'secoes': n, 'media_bruta': mb,
                        'coef_vs_ref': np.r_[0.0, r['beta'][:D.shape[1]]], 'ep': np.r_[np.nan, r['ep'][:D.shape[1]]],
                        't': np.r_[np.nan, r['t'][:D.shape[1]]]})
    tab['referencia'] = niveis[0]
    return res, tab


def teste_continuo(df, desfecho, x, fe='predio', cluster='predio', controles=()):
    """Coeficiente de um regressor continuo `x` com efeito fixo e erro agrupado (mesma mecanica de teste_atributo)."""
    cols = [desfecho, x, fe, cluster] + list(controles)
    d = df.dropna(subset=list(dict.fromkeys(cols))).reset_index(drop=True)
    if len(d) < 50:
        return {'desfecho': desfecho, 'x': x, 'fe': fe, 'n': int(len(d)), 'status': NOT_COMP, 'motivo': '< 50 secoes'}
    fe_c, _ = codigos(d[fe])
    cl_c, _ = codigos(d[cluster])
    X = np.c_[d[x].to_numpy(float), d[list(controles)].to_numpy(float)] if controles else d[[x]].to_numpy(float)
    r = fe_ols(d[desfecho].to_numpy(float), X, fe_c, cl_c, teste=[0])
    return {'desfecho': desfecho, 'x': x, 'fe': fe, 'controles': '+'.join(controles) or '-', 'n': int(len(d)), 'status': 'feita',
            'coef': r['beta'][0], 'ep': r['ep'][0], 't': r['t'][0], 'p': r['p'], 'r2_parcial': r['r2_parcial'], 'sd_x': float(d[x].std())}


def bh(p, q=ALFA):
    """Benjamini-Hochberg: vetor booleano dos rejeitados a q (NaN nunca rejeitado)."""
    p = np.asarray(p, float)
    ok = np.isfinite(p)
    out = np.zeros(len(p), bool)
    if ok.sum() == 0:
        return out
    idx = np.flatnonzero(ok)
    order = np.argsort(p[idx])
    ps = p[idx][order]
    m = len(ps)
    below = np.flatnonzero(ps <= q * np.arange(1, m + 1) / m)
    if len(below):
        out[idx[order[:below.max() + 1]]] = True
    return out


def classifica_vinculo(a, b, faixa=(0.7, 1.43), agregadas=None):
    """Classifica cada secao do pleito de origem `a` em relacao ao destino `b` (DataFrames com KEY, voting_place, aptos):
    mantida (mesma chave, mesmo local, razao de aptos na faixa), agregada (mesma chave e local, fora da faixa, e marcada como
    agregada em DS_AGREGADAS de algum dos dois), mesmo_local_porte_diferente, realocada (mesma chave, outro local),
    sem_correspondencia (chave ausente no destino -> NOT_COMPARABLE). Secoes so do destino entram como 'nova_no_destino'."""
    cols = KEY + ['voting_place', 'aptos']
    m = a[cols].merge(b[cols], on=KEY, how='outer', suffixes=('_a', '_b'), indicator=True)
    cls = pd.Series('sem_correspondencia', index=m.index, dtype=object)
    both = m['_merge'] == 'both'
    mesmo_local = both & (m.voting_place_a == m.voting_place_b)
    razao = m.aptos_b / m.aptos_a.where(m.aptos_a > 0)
    na_faixa = razao.between(*faixa)
    cls[both & ~(m.voting_place_a == m.voting_place_b)] = 'realocada'
    cls[mesmo_local & ~na_faixa] = 'mesmo_local_porte_diferente'
    if agregadas is not None and len(agregadas):
        ag = m[KEY].merge(agregadas[KEY].drop_duplicates().assign(_ag=True), on=KEY, how='left')['_ag'].fillna(False).to_numpy(bool)
        cls[mesmo_local & ~na_faixa & ag] = 'agregada'
    cls[mesmo_local & na_faixa] = 'mantida'
    cls[m['_merge'] == 'right_only'] = 'nova_no_destino'
    m['classe'] = cls
    m['status'] = np.where(cls.isin(['sem_correspondencia', 'nova_no_destino']), NOT_COMP, 'COMPARAVEL')
    m['motivo'] = np.where(cls == 'sem_correspondencia', 'chave ausente no destino',
                           np.where(cls == 'nova_no_destino', 'chave ausente na origem', ''))
    m['razao_aptos'] = razao
    return m.drop(columns='_merge')


def recorrencia(df, flag_a, flag_b):
    """pct de secoes com comportamento no destino entre as que tinham comportamento na origem x as que nao tinham."""
    a = df[flag_a].fillna(False).astype(bool)
    b = df[flag_b].fillna(False).astype(bool)
    n_a = int(a.sum())
    rep = 100 * float(b[a].mean()) if n_a else np.nan
    sem = 100 * float(b[~a].mean()) if (~a).sum() else np.nan
    return {'secoes': int(len(df)), 'com_comportamento_origem': n_a, 'pct_repete': rep, 'pct_sem_comportamento_antes': sem,
            'razao': rep / sem if sem and sem > 0 else np.nan}


def forma_z(z):
    """Estatisticas de forma de z: variancia, phi robusto (MAD^2), assimetria e curtose (z cortado em +-10), quantis,
    contagem |z|>3 e |z|>4 observada e esperada sob normal com a variancia robusta."""
    z = np.asarray(z, float)
    z = z[np.isfinite(z)]
    n = len(z)
    if n < 20:
        return {'n': n}
    med = np.median(z)
    sd_r = 1.4826 * np.median(np.abs(z - med))
    zc = np.clip(z, -10, 10)
    q = np.quantile(z, [.001, .01, .05, .25, .5, .75, .95, .99, .999])
    o = {'n': n, 'media': float(z.mean()), 'var': float(z.var()), 'phi_robusto': float(sd_r ** 2), 'assimetria': float(stats.skew(zc)),
         'curtose_excesso': float(stats.kurtosis(zc)), 'razao_var_phi': float(z.var() / sd_r ** 2) if sd_r > 0 else np.nan}
    for nome, v in zip(['q001', 'q01', 'q05', 'q25', 'q50', 'q75', 'q95', 'q99', 'q999'], q):
        o[nome] = float(v)
    for lim in (3, 4):
        o[f'obs_abs_z_maior_{lim}'] = int((np.abs(z) > lim).sum())
        o[f'esp_normal_robusta_{lim}'] = float(n * 2 * stats.norm.sf(lim / sd_r)) if sd_r > 0 else np.nan
        o[f'esp_normal_1_{lim}'] = float(n * 2 * stats.norm.sf(lim))
    return o


def spearman_matriz(df, cols, grupo=None):
    """Matriz de correlacao de Spearman entre `cols`; com `grupo` (codigos), as variaveis sao centradas no grupo antes."""
    M = df[cols].to_numpy(float)
    if grupo is not None:
        M = centra(M, grupo)
    Rk = np.column_stack([stats.rankdata(M[:, j]) for j in range(M.shape[1])])
    return np.corrcoef(Rk, rowvar=False)


def residuo_loo(df, x2, n2, x1, n1, place):
    """Mudanca da fatia (x/n) do 1o para o 2o turno menos a mudanca agregada das OUTRAS secoes do predio (pontos).
    Predios com < 3 secoes -> NaN."""
    d = pd.DataFrame({'x2': df[x2].astype(float), 'n2': df[n2].astype(float), 'x1': df[x1].astype(float), 'n1': df[n1].astype(float),
                      'p': df[place]})
    g = d.groupby('p')
    S = {c: g[c].transform('sum') for c in ('x2', 'n2', 'x1', 'n1')}
    k = g['x2'].transform('size')
    proprio = d.x2 / d.n2.where(d.n2 > 0) - d.x1 / d.n1.where(d.n1 > 0)
    outros = ((S['x2'] - d.x2) / (S['n2'] - d.n2).where((S['n2'] - d.n2) > 0)
              - (S['x1'] - d.x1) / (S['n1'] - d.n1).where((S['n1'] - d.n1) > 0))
    r = 100 * (proprio - outros)
    return r.where(k >= 3)


def _achado(cid, titulo, pleito, cargo, uf, escopo, tipo, efeito, efeito_num, mat_min, mat_max, margem, artefato, controles, hipoteses,
            status, dado_externo, fonte, prioridade):
    _ACHADOS_N[cid] = _ACHADOS_N.get(cid, 0) + 1
    return {'id_sugerido': f'{cid}-A{_ACHADOS_N[cid]}', 'titulo': titulo, 'pleito': pleito, 'cargo': cargo, 'uf': uf,
            'escopo': escopo, 'tipo': tipo, 'efeito': efeito, 'efeito_num': float(efeito_num) if efeito_num is not None else None,
            'materialidade_min': int(mat_min), 'materialidade_max': int(mat_max), 'margem_referencia': margem,
            'artefato_excluido': artefato, 'controles': controles, 'hipoteses': list(hipoteses), 'status_sugerido': status,
            'dados_externos': dado_externo, 'fonte': list(fonte), 'prioridade': int(prioridade)}


def _rec(resumo, cid, status, numeros, arquivos, motivo=''):
    resumo[cid] = {'status': status, 'motivo': motivo, 'numeros_chave': numeros, 'arquivos': arquivos,
                   'at': dt.datetime.now(dt.timezone.utc).isoformat()}


# ----------------------------------------------------------------------------------------------- C6-01 atributos tecnicos
def _primeira(names, cands):
    for c in cands:
        if c in names:
            return c
    return None


def tecnico_bweb(path, con):
    """Uma linha por secao com os atributos tecnicos do BWEB (texto original preservado; n_* = valores distintos na secao)."""
    import pyarrow.parquet as pq
    names = pq.ParquetFile(path).schema_arrow.names
    sel = ["SG_UF as uf", "CD_MUNICIPIO as municipality", "NR_ZONA as zone", "NR_SECAO as section"]
    for k, cands in COLS_BWEB.items():
        c = _primeira(names, cands)
        if c is None:
            sel.append(f"NULL::VARCHAR as {k}")
        elif k in ('aptos', 'comp', 'biom_nh'):
            sel.append(f"max(try_cast({c} as BIGINT)) as {k}")
        else:
            sel.append(f"min(cast({c} as VARCHAR)) as {k}")
            if k in ('serial', 'carga', 'flashcard', 'tipo_urna', 'voting_place'):
                sel.append(f"count(distinct cast({c} as VARCHAR)) as n_{k}")
    q = f"select {', '.join(sel)} from '{_p(path)}' group by 1, 2, 3, 4"
    d = con.execute(q).df()
    for c in d.columns:
        if d[c].dtype == object:
            d[c] = d[c].astype('string[pyarrow]')
    return _int_keys(d)


def ceft_secao(pleito, uf, con):
    """CEFT por secao (11 UFs; 2018 em diante, layout com cabecalho): urna esperada/efetivada, troca, origem do voto, carga,
    flashcard, maquina de geracao da midia (2024+)."""
    import pyarrow.parquet as pq
    p = R / 'ceft' / pleito / f'{uf}.parquet'
    if not p.exists():
        return None
    names = pq.ParquetFile(p).schema_arrow.names
    if 'NR_URNA_EFETIVADA' not in names:
        return None
    quer = {'CD_MUNICIPIO': 'municipality', 'NR_ZONA': 'zone', 'NR_SECAO': 'section', 'NR_LOCAL_VOTACAO': 'voting_place_ceft',
            'NR_URNA_ESPERADA': 'urna_esperada', 'NR_URNA_EFETIVADA': 'urna_efetivada', 'DT_CARGA_URNA_EFETIVADA': 'carga_ceft',
            'CD_FLASHCARD_URNA_EFETIVADA': 'flashcard_ceft', 'DS_ORIGEM_VOTO': 'origem_voto', 'NM_MAQUINA_GERACAO_MIDIA': 'maquina'}
    cols = [f'cast({c} as VARCHAR) as {v}' for c, v in quer.items() if c in names]
    d = con.execute(f"select {', '.join(cols)} from '{_p(p)}'").df()
    d = _int_keys(d)
    d['uf'] = uf
    for c in ('urna_esperada', 'urna_efetivada'):
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d['troca_ceft'] = (d.urna_esperada != d.urna_efetivada) & d.urna_esperada.notna() & d.urna_efetivada.notna()
    return d


def deriva_tecnico(d, pleito):
    """Colunas derivadas do texto original: serial numerico, geracao, lote, datas, calendario, agregada, junta."""
    d = d.copy().reset_index(drop=True)
    for k in COLS_BWEB:
        if k not in d:
            d[k] = pd.Series(pd.NA, index=d.index, dtype='string')
    d['serial'] = pd.to_numeric(d['serial'], errors='coerce').astype('Int64')
    d['geracao'] = geracao_por_serial(d['serial']).to_numpy()
    d['lote_serial'] = (d['serial'] // LOTE_SERIAL).astype('Int64')
    d['carga_dt'] = parse_dt_br(d['carga']).to_numpy()
    cal = deriva_calendario(d[KEY].assign(carga=d['carga_dt']), DATAS[pleito])
    d = pd.concat([d, cal], axis=1)
    d['faixa_dias'] = faixa_dias(d['dias_antes']).to_numpy()
    ag = d['ds_agregadas'].astype('string').str.strip()
    d['agregada'] = (ag.notna() & ~ag.str.upper().isin(NULOS_TXT)).fillna(False).astype(bool)
    jt = d['junta'].astype('string').str.strip()
    d['junta_informada'] = (jt.notna() & ~jt.str.upper().isin(NULOS_TXT)).fillna(False).astype(bool)
    for c in ('abertura', 'encerramento', 'recebido', 'emissao'):
        d[f'{c}_dt'] = parse_dt_br(d[c]).to_numpy()
    d['voting_place'] = pd.to_numeric(d['voting_place'], errors='coerce').astype('Int64')
    d['pleito'] = pleito
    return d


def _quarentena_tecnico(d, pleito):
    n = 0
    q = d[d['n_serial'].fillna(0) > 1]
    n += quarentena('01', q[KEY + ['serial', 'n_serial']].assign(pleito=pleito), 'mais de um numero de serie na mesma secao (BWEB)')
    q = d[d['serial'].isna()]
    n += quarentena('01', q[KEY].assign(pleito=pleito, fonte=q['fonte']), 'secao sem numero de serie numerico')
    q = d[d['carga_apos_dia'].fillna(False)]
    n += quarentena('01', q[KEY + ['serial', 'carga']].assign(pleito=pleito), 'carga posterior ao dia da eleicao')
    q = d[d['carga_dt'].isna() & d['carga'].notna() & ~d['carga'].astype(str).str.upper().isin(NULOS_TXT)]
    n += quarentena('01', q[KEY + ['carga']].assign(pleito=pleito), 'data de carga nao interpretavel')
    return n


def monta_tecnico(pleito, con, ufs=None):
    """Tabela tecnica de um pleito: BWEB presidente (2014-2022, 27 UFs + ZZ) ou governador (2026-t1, 10 UFs) + CEFT MA 2026-t1;
    junta o CEFT por secao (11 UFs, troca/origem/maquina) quando existir."""
    partes, entradas = [], []
    if pleito in PLEITOS_BWEB:
        arqs = [R / 'bu' / pleito / f'{u}_PRESIDENTE.parquet' for u in (ufs or UFS)]
    else:
        arqs = sorted((R / 'bu' / pleito).glob('*_GOVERNADOR.parquet'))
        if ufs:
            arqs = [a for a in arqs if a.name.split('_')[0] in ufs]
    for a in arqs:
        if not a.exists():
            continue
        entradas.append(a)
        c1 = duck()                      # conexao nova por arquivo: o cache do DuckDB nao se acumula entre UFs
        t = tecnico_bweb(a, c1)
        c1.close()
        t['fonte'] = f'BWEB {a.name}'
        partes.append(t)
    d = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=KEY + list(COLS_BWEB) + ['fonte'])
    del partes
    if pleito == '2026-t1' and (ufs is None or 'MA' in ufs) and 'MA' not in set(d.uf):
        c = ceft_secao(pleito, 'MA', con)
        if c is not None:
            entradas.append(R / 'ceft' / pleito / 'MA.parquet')
            m = pd.DataFrame({'uf': 'MA', 'municipality': c.municipality, 'zone': c.zone, 'section': c.section,
                              'serial': c.urna_efetivada.astype('Int64').astype('string'), 'n_serial': 1,
                              'carga': c.carga_ceft, 'n_carga': 1, 'flashcard': c.flashcard_ceft, 'voting_place': c.voting_place_ceft,
                              'fonte': 'CEFT MA.parquet'})
            d = pd.concat([d, m], ignore_index=True) if len(d) else m
    if not len(d):
        return d, entradas
    d = deriva_tecnico(d, pleito)
    cefts = []
    for u in UFS11:
        if ufs and u not in ufs:
            continue
        c = ceft_secao(pleito, u, con)
        if c is not None:
            entradas.append(R / 'ceft' / pleito / f'{u}.parquet')
            cefts.append(c[KEY + ['urna_esperada', 'urna_efetivada', 'troca_ceft', 'origem_voto'] + (['maquina'] if 'maquina' in c else [])])
    if cefts:
        c = pd.concat(cefts, ignore_index=True)
        dup = c.duplicated(KEY, keep=False)
        quarentena('01', c[dup].assign(pleito=pleito), 'secao repetida no CEFT')
        c = c[~dup]
        d = d.merge(c, on=KEY, how='left')
        d['serial_igual_ceft'] = (d['serial'].astype('float') == d['urna_efetivada']).where(d['urna_efetivada'].notna())
        d['geracao_substituta'] = d['geracao'].where(d['troca_ceft'].fillna(False).astype(bool))
    return d, entradas


def grava_parquet(d, path, entradas):
    path.parent.mkdir(parents=True, exist_ok=True)
    d.to_parquet(path, index=False)
    return recibo(path, entradas, len(d))


def _integridade(eleicao, con=None):
    p = REL / 'integridade' / 'integridade_todas_urnas.parquet'
    c1 = duck()
    d = c1.execute(f"select uf, urna, cert_cn, cert_emissor from '{_p(p)}' where eleicao = '{eleicao}'").df()
    c1.close()
    d = pd.concat([d.reset_index(drop=True), chave_stem(d['urna'])], axis=1)
    d = _int_keys(d)
    d['cert_num'] = pd.to_numeric(d['cert_cn'].str.extract(r'(\d+)$', expand=False), errors='coerce')
    d['geracao_cert'] = d['cert_emissor'].map(CERT_GERACAO)
    d['geracao_faixa'] = geracao_por_serial(d['cert_num']).to_numpy()
    return d


def resumo_tecnico(d, pleito):
    g = d.groupby('uf')
    r = pd.DataFrame({'secoes': g.size(), 'com_serial': g['serial'].count(),
                      'mais_de_um_serial': g['n_serial'].apply(lambda s: int((s.fillna(0) > 1).sum())),
                      'carga_min': g['carga_dt'].min(), 'carga_max': g['carga_dt'].max(), 'dias_antes_mediana': g['dias_antes'].median(),
                      'carga_no_dia': g['carga_no_dia'].sum(), 'carga_apos_dia': g['carga_apos_dia'].sum(),
                      'agregadas': g['agregada'].sum(), 'junta_informada': g['junta_informada'].sum(),
                      'flashcards_distintos': g['flashcard'].nunique(), 'lotes_serial': g['lote_serial'].nunique()})
    for ger in ['anterior_2009', 'AC_URNA_pre2020', 'UE2020', 'UE2022', 'fora_das_faixas', 'sem_serial']:
        r[f'pct_{ger}'] = 100 * d.assign(_x=d.geracao.eq(ger)).groupby('uf')['_x'].mean()
    r['tipo_urna'] = d.groupby('uf')['tipo_urna'].apply(
        lambda s: '|'.join(f'{k}:{v}' for k, v in s.astype(str).str.upper().value_counts().items()))
    if 'troca_ceft' in d:
        r['ceft_juntado'] = g['urna_efetivada'].count()
        r['troca_ceft'] = g['troca_ceft'].apply(lambda s: int(s.fillna(False).astype(bool).sum()))
        r['serial_igual_ceft'] = g['serial_igual_ceft'].apply(lambda s: int(s.fillna(False).astype(bool).sum()))
    r = r.reset_index()
    r.insert(0, 'pleito', pleito)
    return r


def calibra_geracao(tec, con):
    """Concordancia entre geracao pela faixa de serie e pelo certificado da urna (integridade), e entre o serial do BWEB/CEFT e o
    serial do certificado, por pleito."""
    linhas = []
    pares = {'2022-t1': '2022-t1', '2022-t2': '2022-t2', '2024-t1': None, '2024-t2': None, '2026-t1': '2026-t1', '2026-t2': '2026-t1'}
    for el, fonte in pares.items():
        it = _integridade(el, con)
        tem = it.cert_num.notna()
        base = {'eleicao': el, 'urnas_integridade': len(it), 'com_certificado': int(tem.sum()),
                'faixa_igual_certificado': int((it.geracao_faixa[tem] == it.geracao_cert[tem]).sum()),
                'faixa_diferente_certificado': int((it.geracao_faixa[tem] != it.geracao_cert[tem]).sum())}
        for ger in ('AC_URNA_pre2020', 'UE2020', 'UE2022'):
            s = it.cert_num[it.geracao_cert == ger]
            base[f'serie_min_{ger}'] = float(s.min()) if len(s) else np.nan
            base[f'serie_max_{ger}'] = float(s.max()) if len(s) else np.nan
        dif = it[tem & (it.geracao_faixa != it.geracao_cert)]
        quarentena('01', dif[['uf', 'urna', 'cert_cn', 'cert_emissor', 'geracao_faixa']].assign(eleicao=el),
                   'geracao pela faixa diferente do certificado')
        if fonte is None:
            ce = []
            for u in UFS11:
                c = ceft_secao(el, u, con)
                if c is not None:
                    ce.append(c[KEY + ['urna_efetivada']].rename(columns={'urna_efetivada': 'serial'}))
            ref = pd.concat(ce, ignore_index=True) if ce else pd.DataFrame(columns=KEY + ['serial'])
            base['fonte_serial'] = 'CEFT NR_URNA_EFETIVADA (11 UFs)'
        else:
            ref = tec[fonte][KEY + ['serial']]
            base['fonte_serial'] = f'tecnico_{fonte}' + (' (1o turno contra o certificado do 2o turno)' if fonte != el else '')
        ref = _int_keys(ref.dropna(subset=['serial']).drop_duplicates(KEY).copy())
        m = it[tem].merge(ref, on=KEY, how='inner')
        base['juntadas'] = len(m)
        base['serial_igual'] = int((m.cert_num == pd.to_numeric(m.serial, errors='coerce')).sum())
        base['pct_serial_igual'] = 100 * base['serial_igual'] / max(len(m), 1)
        g2 = geracao_por_serial(m.serial).to_numpy()
        base['geracao_igual'] = int((g2 == m.geracao_cert.to_numpy()).sum())
        base['pct_geracao_igual'] = 100 * base['geracao_igual'] / max(len(m), 1)
        linhas.append(base)
    return pd.DataFrame(linhas)


def mesma_urna_turnos(t1, t2):
    """Por UF: secoes presentes nos dois turnos com serial, quantas com a mesma urna e com a mesma geracao."""
    m = t1[KEY + ['serial', 'geracao']].merge(t2[KEY + ['serial', 'geracao']], on=KEY, suffixes=('_t1', '_t2'))
    m = m.dropna(subset=['serial_t1', 'serial_t2'])
    m['igual'] = m.serial_t1.astype(float) == m.serial_t2.astype(float)
    m['ger_igual'] = m.geracao_t1.astype(str) == m.geracao_t2.astype(str)
    m['uf'] = m['uf'].astype(str)
    out = m.groupby('uf').agg(secoes=('igual', 'size'), mesma_urna=('igual', 'sum'), mesma_geracao=('ger_igual', 'sum')).reset_index()
    tot = pd.DataFrame([{'uf': 'BR', 'secoes': out.secoes.sum(), 'mesma_urna': out.mesma_urna.sum(), 'mesma_geracao': out.mesma_geracao.sum()}])
    out = pd.concat([out, tot], ignore_index=True)
    out['pct_mesma_urna'] = 100 * out.mesma_urna / out.secoes
    out['pct_mesma_geracao'] = 100 * out.mesma_geracao / out.secoes
    return out


DICIONARIO_TEC = {
    'serial': 'NR_URNA_EFETIVADA (numero de serie da urna que gerou o BU)', 'n_serial': 'valores distintos de serial na secao (>1 = quarentena)',
    'geracao': 'geracao pela faixa de serie (FAIXAS_SERIAL; calibrada contra o certificado em C6-01_calibracao_serial_geracao.csv)',
    'lote_serial': f'serial // {LOTE_SERIAL} (bloco de numeracao, proxy de lote)', 'carga': 'texto original DT_CARGA(_URNA_EFETIVADA)',
    'carga_dt': 'carga interpretada (2014: so data)', 'dias_antes': 'dias entre a data da carga e o dia da eleicao',
    'carga_dow': 'dia da semana da carga (0 = segunda)', 'carga_hora': 'hora da carga (nulo quando o TSE publica so a data)',
    'carga_no_dia': 'carga no proprio dia da eleicao', 'carga_apos_dia': 'carga depois do dia da eleicao (quarentena)',
    'ordem_carga_zona': 'posto percentual da hora da carga entre as secoes da mesma zona (0-1)',
    'faixa_dias': 'faixa de dias antes (apos_dia, no_dia, 1-3, 4-6, 7-10, 11-20, 21+)', 'flashcard': 'CD_FLASHCARD(_URNA_EFETIVADA)',
    'ds_agregadas': 'DS_AGREGADAS / DS_SECOES_AGREGADAS (texto)',
    'agregada': 'secao com secoes agregadas (DS_AGREGADAS nao nulo)', 'junta': 'NR_JUNTA_APURADORA', 'junta_informada': 'junta apuradora nao nula',
    'tipo_urna': 'DS_TIPO_URNA', 'abertura_dt': 'DT_ABERTURA', 'encerramento_dt': 'DT_ENCERRAMENTO', 'recebido_dt': 'DT_BU_RECEBIDO',
    'emissao_dt': 'DT_EMISSAO_BU', 'aptos': 'QT_APTOS', 'comp': 'QT_COMPARECIMENTO',
    'biom_nh': 'QT_ELEITORES_BIOMETRIA_NH / QT_ELEI_BIOM_SEM_HABILITACAO', 'urna_esperada': 'CEFT NR_URNA_ESPERADA (11 UFs)',
    'urna_efetivada': 'CEFT NR_URNA_EFETIVADA', 'troca_ceft': 'urna esperada != efetivada (CEFT)', 'origem_voto': 'CEFT DS_ORIGEM_VOTO',
    'maquina': 'CEFT NM_MAQUINA_GERACAO_MIDIA (2024+)', 'serial_igual_ceft': 'serial BWEB = urna efetivada CEFT',
    'geracao_substituta': 'geracao da urna efetivada quando houve troca', 'fonte': 'arquivo de origem'}


def tecnico_path(pleito):
    return INTER / f'tecnico_{pleito}.parquet'


def carrega_tecnico(pleito, cols=None):
    import pyarrow.parquet as pq
    if cols:
        cols = [c for c in cols if c in pq.ParquetFile(tecnico_path(pleito)).schema_arrow.names]
    d = pd.read_parquet(tecnico_path(pleito), columns=cols)
    return _int_keys(d) if 'section' in d else d


TIPOS_TEC = {
    'uf': 'string', 'municipality': 'Int64', 'zone': 'Int64', 'section': 'Int64', 'serial': 'Int64', 'n_serial': 'Int64', 'carga': 'string',
    'n_carga': 'Int64', 'flashcard': 'string', 'n_flashcard': 'Int64', 'ds_agregadas': 'string', 'junta': 'string', 'tipo_urna': 'string',
    'n_tipo_urna': 'Int64', 'voting_place': 'Int64', 'n_voting_place': 'Int64', 'aptos': 'Int64', 'comp': 'Int64', 'biom_nh': 'Int64',
    'fonte': 'string', 'geracao': 'string', 'lote_serial': 'Int64', 'carga_dt': 'datetime64[ns]', 'dias_antes': 'Int64',
    'carga_dow': 'Int64', 'carga_hora': 'Int64', 'carga_no_dia': 'boolean', 'carga_apos_dia': 'boolean', 'ordem_carga_zona': 'float64',
    'faixa_dias': 'string', 'agregada': 'boolean', 'junta_informada': 'boolean', 'abertura_dt': 'datetime64[ns]',
    'encerramento_dt': 'datetime64[ns]', 'recebido_dt': 'datetime64[ns]', 'emissao_dt': 'datetime64[ns]', 'pleito': 'string',
    'urna_esperada': 'float64', 'urna_efetivada': 'float64', 'troca_ceft': 'boolean', 'origem_voto': 'string', 'maquina': 'string',
    'serial_igual_ceft': 'boolean', 'geracao_substituta': 'string'}


def normaliza_tecnico(d):
    """Mesmas colunas e tipos em todas as partes (UF) de um pleito; coluna ausente vira nula (ex.: CEFT fora das 11 UFs)."""
    out = pd.DataFrame(index=d.index)
    for c, t in TIPOS_TEC.items():
        x = d[c] if c in d else pd.Series(pd.NA, index=d.index)
        if t == 'datetime64[ns]':
            out[c] = pd.to_datetime(x, errors='coerce').astype('datetime64[ns]')
        elif t == 'boolean':
            out[c] = x.astype('object').where(x.notna(), None).astype('boolean')
        elif t == 'Int64':
            out[c] = pd.to_numeric(x, errors='coerce').astype('Int64')
        elif t == 'float64':
            out[c] = pd.to_numeric(x, errors='coerce').astype('float64')
        else:
            out[c] = x.astype('string')
    return out


def compacta(d):
    """Copia com chaves int32/float e textos como categoria (para segurar varios pleitos na memoria)."""
    d = d.copy()
    for c in d.columns:
        if c in ('municipality', 'zone', 'section'):
            d[c] = d[c].astype('float64').astype('float32') if d[c].isna().any() else d[c].astype('int32')
        elif c == 'serial':
            d[c] = d[c].astype('float64')
        elif d[c].dtype == object or str(d[c].dtype).startswith('string'):
            d[c] = d[c].astype('category')
    return d


def flush_quarentena():
    """Acrescenta as linhas de quarentena desta execucao ao quarentena_C6.csv (sem duplicar) e esvazia a lista."""
    if not _QUARENTENA:
        return
    q = pd.DataFrame(_QUARENTENA)
    old = OUT / 'quarentena_C6.csv'
    OUT.mkdir(parents=True, exist_ok=True)
    if old.exists():
        q = pd.concat([pd.read_csv(old, sep=';', encoding='utf-8-sig', dtype=str), q.astype(str)], ignore_index=True).drop_duplicates()
    q.to_csv(old, **CSV)
    _QUARENTENA.clear()


def tecnico_pleito(pleito):
    """Monta e grava research/varredura_forense/c6/tecnico_<pleito>.parquet uma UF por vez (ParquetWriter), com o resumo por UF e
    os numeros-chave em arquivos pequenos ao lado (lidos pelo processo pai)."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    t0 = time.time()
    con = duck()
    ufs = UFS if pleito in PLEITOS_BWEB else sorted({a.name.split('_')[0] for a in (R / 'bu' / pleito).glob('*_GOVERNADOR.parquet')} | {'MA'})
    path = tecnico_path(pleito)
    path.parent.mkdir(parents=True, exist_ok=True)
    writer, schema, entradas_all, res_uf, cont, n = None, None, [], [], {}, 0
    for u in ufs:
        d, entradas = monta_tecnico(pleito, con, ufs=[u])
        if not len(d):
            continue
        entradas_all += entradas
        _quarentena_tecnico(d, pleito)
        d = normaliza_tecnico(d)
        tb = pa.Table.from_pandas(d, preserve_index=False)
        if writer is None:
            schema = tb.schema
            writer = pq.ParquetWriter(path, schema)
        writer.write_table(tb.cast(schema))
        res_uf.append(resumo_tecnico(d, pleito))
        n += len(d)
        for k, v in d.geracao.value_counts().items():
            cont.setdefault('geracao', {})[k] = cont.get('geracao', {}).get(k, 0) + int(v)
        for k, v in (('secoes', len(d)), ('com_serial', int(d.serial.notna().sum())), ('mais_de_um_serial', int((d.n_serial.fillna(0) > 1).sum())),
                     ('carga_no_dia', int(d.carga_no_dia.fillna(False).sum())), ('carga_apos_dia', int(d.carga_apos_dia.fillna(False).sum())),
                     ('agregadas', int(d.agregada.fillna(False).sum())), ('troca_ceft', int(d.troca_ceft.fillna(False).sum()))):
            cont[k] = cont.get(k, 0) + v
        del d, tb
        gc.collect()
    writer.close()
    con.close()
    rec = recibo(path, entradas_all, n)
    cont.update(parquet_sha256=rec['sha256'], segundos=round(time.time() - t0, 1))
    pd.concat(res_uf, ignore_index=True).to_csv(INTER / f'tecnico_{pleito}_resumo_uf.csv', **CSV)
    (INTER / f'tecnico_{pleito}_nums.json').write_text(json.dumps(cont, ensure_ascii=False, default=str), encoding='utf-8')
    flush_quarentena()
    print(pleito, n, cont['segundos'], flush=True)


def calibra_e_turnos():
    """Filho de C6-01: calibracao serie x certificado e mesma urna nos dois turnos (le os tecnicos ja gravados, so 4 colunas)."""
    tec_min = {p: compacta(carrega_tecnico(p, KEY + ['serial', 'geracao'])) for p in PLEITOS_BWEB + ['2026-t1']}
    cal = calibra_geracao(tec_min, duck())
    cal.to_csv(OUT / 'C6-01_calibracao_serial_geracao.csv', **CSV)
    mt = []
    for ano in (2014, 2018, 2022):
        x = mesma_urna_turnos(tec_min[f'{ano}-t1'], tec_min[f'{ano}-t2'])
        x.insert(0, 'ano', str(ano))
        mt.append(x)
    it = _integridade('2026-t2')
    it = it[it.cert_num.notna()]
    it2 = it.assign(serial=it.cert_num, geracao=it.geracao_cert)[KEY + ['serial', 'geracao']].drop_duplicates(KEY)
    x = mesma_urna_turnos(tec_min['2026-t1'], it2)
    x.insert(0, 'ano', '2026 (T2 = amostra da integridade)')
    mt.append(x)
    pd.concat(mt, ignore_index=True).to_csv(OUT / 'C6-01_mesma_urna_1t_2t.csv', **CSV)
    flush_quarentena()


def _filho(*args):
    """Roda uma etapa pesada num processo novo (a memoria do heap do Python/DuckDB volta ao sistema ao fim de cada etapa)."""
    import os
    import subprocess
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONPATH=os.pathsep.join([str(ROOT / 'src'), str(ROOT / 'scripts')]))
    r = subprocess.run([sys.executable, str(Path(__file__).resolve()), *args], env=env, capture_output=True, text=True, encoding='utf-8')
    if r.returncode != 0:
        raise RuntimeError(f'etapa {args} falhou: {r.stderr[-2000:]}')
    return r.stdout


def roda_c6_01(resumo, achados, cache):
    nums, arqs, res_uf = {}, [], []
    for pleito in PLEITOS_BWEB + ['2026-t1']:
        print(_filho('--tecnico', pleito).strip(), flush=True)
        nums[pleito] = json.loads((INTER / f'tecnico_{pleito}_nums.json').read_text(encoding='utf-8'))
        res_uf.append(pd.read_csv(INTER / f'tecnico_{pleito}_resumo_uf.csv', sep=';', decimal=',', encoding='utf-8-sig'))
        arqs.append(str(tecnico_path(pleito)))
    arqs.append(csv_out('C6-01_tecnico_resumo_pleito_uf.csv', pd.concat(res_uf, ignore_index=True)))
    _filho('--calibra')
    cal = ler_csv('C6-01_calibracao_serial_geracao.csv')
    mt = ler_csv('C6-01_mesma_urna_1t_2t.csv')
    arqs += [str(OUT / 'C6-01_calibracao_serial_geracao.csv'), str(OUT / 'C6-01_mesma_urna_1t_2t.csv')]
    arqs.append(csv_out('C6-01_dicionario.csv', pd.DataFrame([{'coluna': k, 'descricao': v} for k, v in DICIONARIO_TEC.items()])))
    nums['calibracao'] = cal[['eleicao', 'com_certificado', 'faixa_igual_certificado', 'juntadas', 'pct_serial_igual',
                              'pct_geracao_igual']].to_dict('records')
    nums['mesma_urna_br'] = mt[mt.uf == 'BR'][['ano', 'secoes', 'pct_mesma_urna', 'pct_mesma_geracao']].to_dict('records')
    _rec(resumo, 'C6-01', 'feita', nums, arqs)


# ----------------------------------------------------------------------------------------------- base por secao (C6-02/06/07/08)
DESFECHOS = ['res_pp', 'z', 'share_A_t2', 'swing_A', 'turnout_t2', 'dturnout', 'bn_t2', 'manual_t2', 'enc_min_t2']


def secoes_path(ano):
    return INTER / f'secoes_{ano}.parquet'


def monta_secoes(ano):
    """Base por secao do 2o turno presidencial (base_<ano>) na amostra do modelo do local (z_m1), com desfechos de resultado e de
    processo, predio/zona, terceiros no 1o turno e os atributos tecnicos do BU (2014-2022: urna do 2o turno, BWEB nacional;
    2026: urna do 1o turno pelo BWEB de governador/CEFT, 11 UFs, como proxy - C6-01 mede ~97-99% de mesma urna entre turnos)."""
    import pyarrow.parquet as pq
    p = R / 'padroes_2t' / f'base_{ano}.parquet'
    names = pq.ParquetFile(p).schema_arrow.names
    quer = KEY + ['voting_place', 't1_A', 't1_B', 't2_A', 't2_B', 't1_comp', 't1_aptos', 't2_comp', 't2_aptos', 't2_branco', 't2_nulo',
                  't1_validos', 't2_manual', 't2_enc_min', 't2_abre_min', 'regiao']
    b = pd.read_parquet(p, columns=[c for c in quer if c in names])
    b = _int_keys(b)
    b['voting_place'] = pd.to_numeric(b['voting_place'], errors='coerce')
    n_base = len(b)
    e = z_m1(b)
    del b
    e['share_A_t2'] = 100 * e.t2_A / e.n2
    e['swing_A'] = 100 * (e.t2_A / e.n2 - e.t1_A / e.n1)
    e['turnout_t2'] = 100 * e.t2_comp / e.t2_aptos.where(e.t2_aptos > 0)
    e['dturnout'] = e.turnout_t2 - 100 * e.t1_comp / e.t1_aptos.where(e.t1_aptos > 0)
    e['bn_t2'] = 100 * (e.t2_branco + e.t2_nulo) / e.t2_comp.where(e.t2_comp > 0)
    e['manual_t2'] = 100 * e.t2_manual / e.t2_comp.where(e.t2_comp > 0) if 't2_manual' in e else np.nan
    e['enc_min_t2'] = e['t2_enc_min'] if 't2_enc_min' in e else np.nan
    e['terceiros_t1'] = 100 * (e.t1_validos - e.n1) / e.t1_validos.where(e.t1_validos > 0)
    e['predio'] = predio_id(e)
    e['zona'] = zona_id(e)
    e['ref_estatistica'] = (e.uf != 'ZZ') & (e.t2_aptos >= MIN_APTOS)
    tp = f'{ano}-t2' if ano < 2026 else '2026-t1'
    t = carrega_tecnico(tp, KEY + ['serial', 'geracao', 'lote_serial', 'faixa_dias', 'dias_antes', 'agregada', 'carga_dt', 'carga_no_dia',
                                   'ordem_carga_zona', 'carga_hora', 'carga_dow', 'flashcard', 'troca_ceft'])
    t = t.drop_duplicates(KEY)
    if ano < 2026:
        t1 = carrega_tecnico(f'{ano}-t1', KEY + ['serial']).drop_duplicates(KEY).rename(columns={'serial': 'serial_t1'})
        t = t.merge(t1, on=KEY, how='left')
        t['mudou_urna'] = (t.serial.astype(float) != t.serial_t1.astype(float)).where(t.serial_t1.notna() & t.serial.notna())
        t = t.drop(columns='serial_t1')
    else:
        t['mudou_urna'] = np.nan
    e = e.merge(t, on=KEY, how='left')
    e['tem_tecnico'] = e.serial.notna()
    e['fonte_tecnico'] = np.where(e.tem_tecnico, tp, NOT_COMP)
    keep = KEY + ['voting_place', 'regiao', 'predio', 'zona', 'k', 'n1', 'n2', 't1_A', 't2_A', 't2_aptos', 'p_loo', 'terceiros_t1',
                  'ref_estatistica', 'tem_tecnico', 'fonte_tecnico', 'serial', 'geracao', 'lote_serial', 'faixa_dias', 'dias_antes', 'agregada',
                  'carga_dt', 'carga_no_dia', 'ordem_carga_zona', 'carga_hora', 'carga_dow', 'flashcard', 'troca_ceft', 'mudou_urna'] + DESFECHOS
    e = e[[c for c in keep if c in e]].copy()
    for c in ('geracao', 'faixa_dias', 'flashcard'):
        e[c] = e[c].astype('string')
    e['mudou_urna'] = e['mudou_urna'].astype('float')
    e['agregada'] = e['agregada'].astype('float')
    e['carga_no_dia'] = e['carga_no_dia'].astype('float')
    e['troca_ceft'] = e['troca_ceft'].astype('float')
    return e, n_base


def carrega_secoes(ano, cols=None):
    return pd.read_parquet(secoes_path(ano), columns=cols)


def garante_secoes(cache):
    if cache.get('secoes_ok'):
        return
    for ano in ANOS:
        if secoes_path(ano).exists():
            continue
        e, _ = monta_secoes(ano)
        tp = f'{ano}-t2' if ano < 2026 else '2026-t1'
        grava_parquet(e, secoes_path(ano), [R / 'padroes_2t' / f'base_{ano}.parquet', tecnico_path(tp)])
        del e
        gc.collect()
    cache['secoes_ok'] = True


def perfil_2022():
    """Perfil 2022 por secao (11 UFs): biometria, 60+ e fundamental incompleto em % dos eleitores."""
    ps = []
    for u in UFS11:
        p = R / 'perfil' / '2022' / f'{u}.parquet'
        if p.exists():
            x = pd.read_parquet(p, columns=['municipality', 'zone', 'section', 'voters', 'biometria', 'age60', 'low_school'])
            x['uf'] = u
            ps.append(x)
    d = _int_keys(pd.concat(ps, ignore_index=True))
    v = d.voters.where(d.voters > 0)
    d['biometria_pct'] = 100 * d.biometria / v
    d['age60_pct'] = 100 * d.age60 / v
    d['low_school_pct'] = 100 * d.low_school / v
    return d[KEY + ['biometria_pct', 'age60_pct', 'low_school_pct']].drop_duplicates(KEY)


CONTROLES_PERFIL = ('biometria_pct', 'age60_pct', 'low_school_pct')


def entre_grupos_perm(y, codes, fe_codes, perm_codes, n_perm=N_PERM, seed=SEED):
    """Atributo de muitos niveis (lote de serie, flashcard): soma de quadrados entre niveis de y centrado no efeito fixo,
    dividida pela variancia (~ qui-quadrado com k-1 gl sob o nulo), contra permutacoes do atributo dentro de perm_codes."""
    yd = centra(y, fe_codes)

    def estat(c):
        k = int(c.max()) + 1
        n = np.bincount(c, minlength=k)
        s = np.bincount(c, weights=yd, minlength=k)
        v = yd.var()
        return float(np.sum(s * s / np.where(n > 0, n, 1)) / v) if v > 0 else 0.0
    real = estat(codes)
    rng = np.random.default_rng(seed)
    perms = np.array([estat(permuta_dentro(codes, perm_codes, rng)) for _ in range(n_perm)])
    k = int(len(np.unique(codes)))
    return {'estat': real, 'gl': k - 1, 'perm_media': float(perms.mean()), 'perm_p95': float(np.quantile(perms, .95)),
            'p_perm': float((np.sum(perms >= real) + 1) / (n_perm + 1)),
            'excesso_sobre_perm': real / perms.mean() if perms.mean() > 0 else np.nan}


def _linha(ano, escopo, res, extra=None):
    r = {'ano': ano, 'escopo': escopo}
    r.update(dict(res))
    if extra:
        r.update(extra)
    return r


def c6_02_particao(e, ano, desfechos, atributos=('geracao', 'faixa_dias', 'agregada', 'mudou_urna', 'carga_no_dia'), n_perm=N_PERM,
                   controles=()):
    """Particao por atributo tecnico depois do efeito fixo de predio (e de zona para geracao): r2 parcial, Wald agrupado por predio,
    permutacao dentro do predio para a geracao; lote de serie por soma de quadrados entre lotes contra permutacao no predio."""
    linhas, niveis = [], []
    for y in desfechos:
        if e[y].notna().sum() < 100:
            continue
        for a in atributos:
            if a not in e or e[a].notna().sum() < 100:
                continue
            for fe in (('predio', 'zona') if a == 'geracao' else ('predio',)):
                res, tab = teste_atributo(e, y, a, fe=fe, cluster='predio', controles=controles,
                                          ref='AC_URNA_pre2020' if a == 'geracao' else None,
                                          n_perm=n_perm if (a == 'geracao' and fe == 'predio') else 0, perm_grupo='predio')
                linhas.append(_linha(ano, 'BR', res))
                if len(tab):
                    niveis.append(tab.assign(ano=ano, escopo='BR', desfecho=y, atributo=a, fe=fe, controles='+'.join(controles) or '-'))
        d = e.dropna(subset=[y, 'lote_serial', 'predio']).reset_index(drop=True)
        if len(d) > 100 and n_perm:
            fe_c, _ = codigos(d.predio)
            lc, _ = codigos(d.lote_serial)
            r = entre_grupos_perm(d[y].to_numpy(float), lc, fe_c, fe_c, n_perm=n_perm)
            linhas.append(_linha(ano, 'BR', {'desfecho': y, 'atributo': 'lote_serial', 'fe': 'predio', 'n': len(d), 'status': 'feita',
                                             'wald': r['estat'], 'gl': r['gl'], 'p_perm': r['p_perm'], 'r2_perm_p95': r['perm_p95'],
                                             'excesso_sobre_perm': r['excesso_sobre_perm'], 'controles': '-'}))
    return pd.DataFrame(linhas), (pd.concat(niveis, ignore_index=True) if niveis else pd.DataFrame())


def c6_02_por_uf(e, ano, desfechos, atributo='geracao', ref='AC_URNA_pre2020'):
    """Atributo dentro do predio por UF: coeficiente de cada nivel contra a referencia, ep agrupado por predio; BH por ano x desfecho."""
    out = []
    for uf, g in e.groupby('uf'):
        for y in desfechos:
            if g[y].notna().sum() < 100:
                continue
            res, tab = teste_atributo(g, y, atributo, fe='predio', cluster='predio', ref=ref)
            if not len(tab):
                out.append({'ano': ano, 'uf': uf, 'desfecho': y, 'nivel': None, 'status': res.get('status'), 'motivo': res.get('motivo')})
                continue
            for r in tab.iloc[1:].itertuples():
                out.append({'ano': ano, 'uf': uf, 'desfecho': y, 'nivel': r.nivel, 'referencia': r.referencia, 'secoes_nivel': r.secoes,
                            'coef_ef_predio': r.coef_vs_ref, 'ep': r.ep, 't': r.t, 'predios_mistos': res['unidades_fe_mistas'],
                            'secoes_em_predios_mistos': res['secoes_em_unidades_mistas'], 'status': 'feita'})
    o = pd.DataFrame(out)
    if len(o) and 't' in o:
        o['p'] = 2 * stats.norm.sf(np.abs(o['t'].astype(float)))
        o['bh_5pct'] = False
        for _, idx in o.groupby(['ano', 'desfecho']).groups.items():
            o.loc[idx, 'bh_5pct'] = bh(o.loc[idx, 'p'].to_numpy(float))
    return o


def plantada_geracao(e, desfecho, nivel, deltas=(0.1, 0.25, 0.5, 1.0)):
    """Poder: soma delta ao desfecho nas secoes do `nivel` de geracao e refaz o teste dentro do predio (BR e por UF)."""
    out = []
    for dlt in deltas:
        x = e[['uf', 'predio', 'geracao', desfecho]].copy()
        x[desfecho] = x[desfecho] + dlt * (x.geracao == nivel)
        res, tab = teste_atributo(x, desfecho, 'geracao', fe='predio', cluster='predio', ref='AC_URNA_pre2020')
        uf = c6_02_por_uf(x, 0, [desfecho])
        sig = uf[uf.nivel == nivel] if len(uf) and 'nivel' in uf else pd.DataFrame()
        t_niv = float(tab.loc[tab.nivel == nivel, 't'].iloc[0]) if len(tab) and (tab.nivel == nivel).any() else np.nan
        out.append({'desfecho': desfecho, 'nivel_plantado': nivel, 'delta': dlt, 'p_wald_br': res.get('p'), 't_nivel_br': t_niv,
                    'ufs_testadas': int(len(sig)),
                    'ufs_bh_5pct_mesmo_sinal': int(((sig.bh_5pct.astype(bool)) & (sig.t > 0)).sum()) if len(sig) else 0})
    return pd.DataFrame(out)


def regime_multiuf(uf):
    reg = []
    if len(uf) and 't' in uf:
        for (ano, y, nivel), g in uf[uf.status == 'feita'].groupby(['ano', 'desfecho', 'nivel']):
            pos = int(((g.bh_5pct.astype(bool)) & (g.t > 0)).sum())
            neg = int(((g.bh_5pct.astype(bool)) & (g.t < 0)).sum())
            reg.append({'ano': ano, 'desfecho': y, 'nivel': nivel, 'ufs_testadas': len(g), 'ufs_bh_positivo': pos, 'ufs_bh_negativo': neg,
                        'regime_multiuf': (pos >= 2) or (neg >= 2), 'mediana_coef': float(g.coef_ef_predio.median()),
                        'secoes_nivel': int(g.secoes_nivel.sum())})
    return pd.DataFrame(reg)


def _bh_tabela(br, chave=('ano', 'desfecho')):
    br = br.copy()
    pcol = br['p'] if 'p' in br else pd.Series(np.nan, index=br.index)
    if 'p_perm' in br:
        pcol = pcol.fillna(br['p_perm'])
    br['p_familia'] = pcol
    br['bh_5pct'] = False
    for _, idx in br.groupby(list(chave)).groups.items():
        br.loc[idx, 'bh_5pct'] = bh(br.loc[idx, 'p_familia'].to_numpy(float))
    return br


def roda_c6_02(resumo, achados, cache):
    garante_secoes(cache)
    tab_br, tab_niv, tab_uf, tab_ctl, tab_pl, nums = [], [], [], [], [], {}
    perf = perfil_2022()
    for ano in ANOS:
        e = carrega_secoes(ano)
        n_tot = len(e)
        e = e[e.ref_estatistica & e.tem_tecnico].reset_index(drop=True)
        des = [y for y in DESFECHOS if e[y].notna().sum() > 100]
        br, niv = c6_02_particao(e, ano, des)
        tab_br.append(br)
        tab_niv.append(niv)
        tab_uf.append(c6_02_por_uf(e, ano, des))
        nums[str(ano)] = {'secoes_modelo': n_tot, 'secoes_com_tecnico_ref': len(e),
                          'geracao': {k: int(v) for k, v in e.geracao.value_counts().items()}}
        if ano in (2022, 2026):
            x = e[e.uf.isin(UFS11)].merge(perf, on=KEY, how='left')
            for y in ('res_pp', 'swing_A', 'turnout_t2', 'manual_t2'):
                for ctl in ((), CONTROLES_PERFIL):
                    res, tab = teste_atributo(x, y, 'geracao', fe='predio', cluster='predio', controles=ctl, ref='AC_URNA_pre2020')
                    tab_ctl.append(_linha(ano, '11 UFs', res))
                    if len(tab):
                        tab_niv.append(tab.assign(ano=ano, escopo='11 UFs', desfecho=y, atributo='geracao', fe='predio',
                                                  controles='+'.join(ctl) or '-'))
            for y in ('res_pp', 'manual_t2'):
                tab_pl.append(plantada_geracao(e, y, 'UE2020').assign(ano=ano))
            del x
        del e
        gc.collect()
        print('C6-02', ano, flush=True)
    br = _bh_tabela(pd.concat(tab_br + [pd.DataFrame(tab_ctl)], ignore_index=True))
    niv = pd.concat(tab_niv, ignore_index=True)
    uf = pd.concat(tab_uf, ignore_index=True)
    pl = pd.concat(tab_pl, ignore_index=True)
    reg = regime_multiuf(uf)
    arqs = [csv_out('C6-02_particao_br.csv', br), csv_out('C6-02_niveis.csv', niv), csv_out('C6-02_geracao_por_uf.csv', uf),
            csv_out('C6-02_plantada_geracao.csv', pl), csv_out('C6-02_regime_multiuf.csv', reg)]
    nums['regimes_multiuf'] = reg[reg.regime_multiuf].to_dict('records') if len(reg) else []
    gbr = br[(br.atributo == 'geracao') & (br.fe == 'predio') & (br.escopo == 'BR')]
    nums['geracao_br'] = gbr[['ano', 'desfecho', 'n', 'unidades_fe_mistas', 'r2_parcial', 'p', 'p_perm', 'bh_5pct']].to_dict('records')
    nums['plantada'] = pl.to_dict('records')
    _rec(resumo, 'C6-02', 'feita', nums, arqs)


# ----------------------------------------------------------------------------------------------- execucao
def roda_pendentes(resumo):
    for cid, motivo in PENDENTES.items():
        _rec(resumo, cid, 'nao_feita', {}, [], motivo=motivo)


def _grava_estado(resumo, achados):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'C6_resumo.json').write_text(json.dumps({'camada': 'C6', 'protocolo': 'PROTOCOLO.md v1.0', 'parser_version': PARSER_VERSION,
                                                     'semente': SEED, 'n_perm': N_PERM, 'checagens': resumo},
                                                    ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    (OUT / 'C6_achados.json').write_text(json.dumps(achados, ensure_ascii=False, indent=1, default=str), encoding='utf-8')


def _runners():
    return {k: globals()['roda_c6_' + k.split('-')[1]] for k in CHECAGENS if ('roda_c6_' + k.split('-')[1]) in globals()}


def main(ids=None):
    ids = ids or CHECAGENS
    OUT.mkdir(parents=True, exist_ok=True)
    resumo, achados, cache = {}, [], {}
    p_res, p_ach = OUT / 'C6_resumo.json', OUT / 'C6_achados.json'
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
    for a in achados:
        cid = '-'.join(a['id_sugerido'].split('-')[:2])
        _ACHADOS_N[cid] = max(_ACHADOS_N.get(cid, 0), int(a['id_sugerido'].split('-A')[-1]))
    run = _runners()
    for cid in ids:
        t0 = time.time()
        try:
            run[cid](resumo, achados, cache)
            print(f'{cid}: {resumo.get(cid, {}).get("status")} em {time.time() - t0:.0f} s', flush=True)
        except Exception as exc:  # noqa: BLE001
            _rec(resumo, cid, 'nao_feita', {}, [], motivo=f'erro: {exc!r}'[:500])
            print(f'{cid}: ERRO {exc!r}', flush=True)
            _grava_estado(resumo, achados)
            raise
        gc.collect()
        _grava_estado(resumo, achados)
    roda_pendentes(resumo)
    _grava_estado(resumo, achados)
    flush_quarentena()
    print(json.dumps({k: v['status'] for k, v in resumo.items()}, ensure_ascii=False))


if __name__ == '__main__':
    if len(sys.argv) > 2 and sys.argv[1] == '--tecnico':
        tecnico_pleito(sys.argv[2])
    elif len(sys.argv) > 1 and sys.argv[1] == '--calibra':
        calibra_e_turnos()
    else:
        main([a for a in sys.argv[1:] if a.startswith('C6-')] or None)
