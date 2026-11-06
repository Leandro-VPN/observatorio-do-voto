"""Varredura forense, camada C8 (clusters espaciais, tecnicos e de processo): checagens leves sobre parquet/CSV existentes.

Uma funcao por checagem. As funcoes `c8_XX_*`, `scan_hierarquico`, `efeito_dentro_predio`, `estat_entre_grupos`,
`autocorrelacao_serie` sao puras (recebem DataFrames/arrays e devolvem DataFrames/dicionarios); os carregadores
(`carrega_*`) leem o disco com projecao de colunas e DuckDB limitado (400 MB, 2 threads). `main()` roda as checagens
pedidas e grava relatorios/verificacoes/varredura_forense/C8/ (CSVs `C8-XX_*.csv`, `C8_resumo.json`, `C8_achados.json`,
`quarentena_C8.csv`). Importavel sem efeito pesado.

Protocolo: relatorios/verificacoes/varredura_forense/PROTOCOLO.md v1.0. Tudo aqui e descritivo: "diferenca acima do
limiar" e "comportamento" descrevem agrupamentos e limites de deteccao, nao indicam irregularidade por si so.

Nulos por permutacao (semente 20261105, 200 permutacoes): C8-01 permuta rotulos de municipio dentro da UF (M5) e
secoes/predios dentro da UF (M1); C8-02/C8-03/C8-09 permutam o atributo tecnico dentro da zona (quebra o atributo,
mantem a geografia); C8-04/C8-10 permutam secoes dentro da UF.
Uso: python scripts/varredura_forense_c8.py [C8-01 C8-02 ...]   (sem argumentos: todas as checagens leves)
"""
import datetime as dt
import gc
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / 'research'
REL = ROOT / 'relatorios'
OUT = REL / 'verificacoes' / 'varredura_forense' / 'C8'
QUAR = R / 'varredura_forense' / 'quarentena'
INTER = R / 'varredura_forense' / 'c8'
CSV = dict(sep=';', decimal=',', encoding='utf-8-sig', index=False)
PARSER_VERSION = 'varredura-forense-c8-1'
SEED = 20261105
N_PERM = 200
KEY = ['uf', 'municipality', 'zone', 'section']
UFS11 = ['BA', 'CE', 'MA', 'MG', 'PA', 'PE', 'PR', 'RJ', 'RS', 'SC', 'SP']
NIVEIS_IBGE = ['micro', 'meso', 'imediata', 'intermediaria']
NOT_COMP = 'NOT_COMPARABLE'
MIN_APTOS = 50
BLOCO_SERIE = 1000
JANELA_SERIE = 20
CHECAGENS = ['C8-01', 'C8-02', 'C8-03', 'C8-04', 'C8-08', 'C8-09', 'C8-11', 'C8-12', 'C8-10']
PENDENTES = {
    'C8-05': 'depende da passada pesada / nova versao do PROTOCOLO de janelas: estender NIVEIS de janelas_horario.py a '
             'micro/meso exige rodar A.melhor e a permutacao (~7 h) do estudo existente, o que este prompt veda; a passada '
             'deve acrescentar os niveis micro/meso/imediata (codigos de C8-01_geografia.csv) a Agrupamentos e repetir '
             'clusters + permutacao nas janelas 10:45-18:45, 08:00-10:45, 12:00-17:00 e 10:30-17:15.',
    'C8-06': 'parte pesada depende da passada de logs: a passada deve contar por secao as linhas "Solicita digital. '
             'Tentativa [n]", "Falha na captura da digital", "ERROR opening the biometric reader" e as habilitacoes '
             'manuais nao associadas (A-002), nas 27 UFs do 2T 2026 e nas 11 de 2022 T2, gravando por secao: '
             'n_atendimentos, n_com_2+_tentativas, n_manual_nao_associado, n_erros_leitor.',
    'C8-07': 'depende da passada de logs: ler as ~100 primeiras linhas de cada logd.dat e extrair "Identificacao do '
             'Modelo de Urna", "Versao da aplicacao", "Versao do UEFI" e o 3o campo (serie em 2026) por secao; depois '
             'repetir efeito_dentro_predio por modelo/versao (mesma funcao deste script).',
}
_QUARENTENA: list[dict] = []


# ----------------------------------------------------------------------------------------------- utilidades
def duck():
    import duckdb
    con = duckdb.connect()
    con.execute("SET memory_limit='400MB'")
    con.execute('SET threads=2')
    return con


def quarentena(checagem, df, reason):
    """Linhas que falham invariante: valores originais como string + motivo (JSON por checagem e CSV unico)."""
    if df is None or len(df) == 0:
        return 0
    rows = [{k: ('' if pd.isna(v) else str(v)) for k, v in r.items()} | {'reason': reason, 'checagem': checagem}
            for r in df.to_dict('records')]
    QUAR.mkdir(parents=True, exist_ok=True)
    p = QUAR / f'rows-C8-{checagem}.json'
    old = json.loads(p.read_text(encoding='utf-8')) if p.exists() else []
    vistos, todas = set(), []
    for r in old + rows:                      # reexecucoes nao duplicam linhas
        k = json.dumps(r, sort_keys=True, ensure_ascii=False)
        if k not in vistos:
            vistos.add(k)
            todas.append(r)
    p.write_text(json.dumps(todas, ensure_ascii=False, indent=1), encoding='utf-8')
    _QUARENTENA.extend(rows)
    return len(rows)


def _sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for bloco in iter(lambda: f.read(1 << 20), b''):
            h.update(bloco)
    return h.hexdigest()


def recibo(path, inputs, rows):
    """Recibo <arquivo>.json ao lado do parquet: {at, inputs:{caminho: sha256}, sha256, rows, bytes, parser_version}."""
    path = Path(path)
    rec = {'at': dt.datetime.now(dt.timezone.utc).isoformat(), 'inputs': {str(i): _sha256(i) for i in inputs if Path(i).exists()},
           'sha256': _sha256(path), 'rows': int(rows), 'bytes': path.stat().st_size, 'parser_version': PARSER_VERSION}
    Path(str(path) + '.json').write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding='utf-8')
    return rec


ENTRADAS_C8_04 = [R / 'padroes_2t' / f'base_{a}.parquet' for a in (2026, 2022)] + [R / 'janelas_horario' / f'bins_{a}.parquet' for a in (2026, 2022)] +     [R / 'anomalias_2t' / f'secoes_{a}.parquet' for a in (2026, 2022)] + [R / 'ibge' / 'municipios.json',
                                                                         REL / 'verificacoes' / 'eleitorado_populacao' / 'municipios.csv']


def csv_out(nome, df):
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / nome, **CSV)
    return str(OUT / nome)


def chave_stem(stems):
    """Series de stems -> DataFrame(municipality, zone, section) pelos 13 digitos finais; invalido fica NaN."""
    s = pd.Series(stems, dtype='string').reset_index(drop=True)
    d = s.str[-13:]
    ok = d.str.isdigit().fillna(False) & (s.str.len() >= 13)
    out = pd.DataFrame({
        'municipality': pd.to_numeric(d.str[:5].where(ok), errors='coerce'),
        'zone': pd.to_numeric(d.str[5:9].where(ok), errors='coerce'),
        'section': pd.to_numeric(d.str[9:13].where(ok), errors='coerce')})
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


def padroniza_por_uf(r, w, uf_code):
    """(r - media ponderada da UF) / desvio ponderado da UF; UF com desvio 0 ou pesos nulos -> 0."""
    r = np.asarray(r, float)
    w = np.asarray(w, float)
    k = int(uf_code.max()) + 1 if len(uf_code) else 0
    sw = np.bincount(uf_code, weights=w, minlength=k)
    m = np.bincount(uf_code, weights=w * r, minlength=k) / np.where(sw > 0, sw, 1)
    d = r - m[uf_code]
    v = np.bincount(uf_code, weights=w * d * d, minlength=k) / np.where(sw > 0, sw, 1)
    sd = np.sqrt(v)
    out = np.where(sd[uf_code] > 0, d / np.where(sd[uf_code] > 0, sd[uf_code], 1), 0.0)
    return out


def t_grupos(r_std, w, codes, n_grupos):
    """t_g = sum(w r_std) / sqrt(sum(w^2)) por grupo (media ponderada padronizada; ~N(0,1) sob permutacao na UF)."""
    s = np.bincount(codes, weights=w * r_std, minlength=n_grupos)
    w2 = np.bincount(codes, weights=w * w, minlength=n_grupos)
    return np.where(w2 > 0, s / np.sqrt(np.where(w2 > 0, w2, 1)), 0.0)


def scan_hierarquico(df, valor, peso, niveis, bloco, n_perm=N_PERM, seed=SEED, min_unidades=2):
    """Scan discreto na hierarquia: por nivel, t de cada grupo (media ponderada do valor padronizado na UF) e limite =
    p95 do maximo de |t| em `n_perm` permutacoes dos rotulos dos blocos (`bloco`: secao, predio ou municipio) dentro da UF.
    Grupos sao `uf` + coluna do nivel; linhas com nivel nulo ficam fora do nivel (contadas em `sem_rotulo`).
    Devolve (tabela de grupos, tabela de limites por nivel)."""
    d = df.reset_index(drop=True)
    uf_code, ufs = pd.factorize(d['uf'])
    w = d[peso].to_numpy(float)
    r_std = padroniza_por_uf(d[valor].to_numpy(float), w, uf_code)
    bl_code, _ = pd.factorize(d[bloco])
    rng = np.random.default_rng(seed)
    grupos, limites = [], []
    # rotulos por bloco (um bloco pertence a um unico grupo em cada nivel)
    for nivel in niveis:
        lab = d[nivel]
        ok = lab.notna().to_numpy()
        g_code, g_idx = pd.factorize(pd.Series(np.where(ok, d['uf'].astype(str) + '|' + lab.astype(str), None)))
        n_g = len(g_idx)
        valid = g_code >= 0
        unid = np.bincount(g_code[valid], minlength=n_g)
        t_real = t_grupos(r_std[valid], w[valid], g_code[valid], n_g)
        media = np.bincount(g_code[valid], weights=(w * d[valor].to_numpy(float))[valid], minlength=n_g)
        sw = np.bincount(g_code[valid], weights=w[valid], minlength=n_g)
        media = media / np.where(sw > 0, sw, 1)
        # rotulo do grupo por bloco: tabela bloco -> (uf, grupo)
        bt = pd.DataFrame({'b': bl_code, 'u': uf_code, 'g': g_code}).drop_duplicates('b').sort_values('b')
        bt = bt.set_index('b').reindex(range(bl_code.max() + 1))
        bg = bt['g'].to_numpy()
        bu = bt['u'].to_numpy()
        maxs = np.empty(n_perm)
        elegivel = unid >= min_unidades
        for i in range(n_perm):
            gp = permuta_dentro(bg, bu, rng)[bl_code]
            v = gp >= 0
            tp = t_grupos(r_std[v], w[v], gp[v], n_g)
            maxs[i] = np.abs(tp[elegivel]).max() if elegivel.any() else 0.0
        lim = float(np.quantile(maxs, 0.95)) if n_perm else np.nan
        p_max = np.array([(np.sum(maxs >= abs(t)) + 1) / (n_perm + 1) for t in t_real]) if n_perm else np.full(n_g, np.nan)
        tab = pd.DataFrame({'nivel': nivel, 'grupo': [g.split('|', 1)[1] for g in g_idx], 'uf': [g.split('|', 1)[0] for g in g_idx],
                            'unidades': unid, 'peso_total': sw, 'media_ponderada': media, 't': t_real, 'p_max_perm': p_max,
                            'limite_p95': lim, 'acima_limite': (np.abs(t_real) >= lim) & elegivel})
        grupos.append(tab)
        limites.append({'nivel': nivel, 'grupos': int(n_g), 'grupos_elegiveis': int(elegivel.sum()), 'sem_rotulo': int((~ok).sum()),
                        'limite_p95_max_abs_t': lim, 'max_abs_t_real': float(np.abs(t_real[elegivel]).max()) if elegivel.any() else np.nan,
                        'mediana_max_perm': float(np.median(maxs)) if n_perm else np.nan, 'acima_limite': int(tab['acima_limite'].sum()),
                        'n_perm': int(n_perm), 'semente': seed})
    return pd.concat(grupos, ignore_index=True), pd.DataFrame(limites)


def dispersao_dentro(df, valor, peso, nivel_interno, nivel_externo, n_perm=N_PERM, seed=SEED):
    """Excesso de dispersao: dentro de cada grupo externo (ex.: microrregiao), soma dos t^2 dos grupos internos (ex.:
    municipios) dividida pelo numero deles; limite = p95 do maximo sob permutacao das linhas dentro da UF."""
    d = df.dropna(subset=[nivel_interno, nivel_externo]).reset_index(drop=True)
    uf_code, _ = pd.factorize(d['uf'])
    w = d[peso].to_numpy(float)
    r_std = padroniza_por_uf(d[valor].to_numpy(float), w, uf_code)
    gi, _ = pd.factorize(d['uf'].astype(str) + '|' + d[nivel_interno].astype(str))
    ge, ge_idx = pd.factorize(d['uf'].astype(str) + '|' + d[nivel_externo].astype(str))
    ext_of_int = pd.Series(ge).groupby(gi).first().to_numpy()
    k = np.bincount(ext_of_int, minlength=len(ge_idx))
    rng = np.random.default_rng(seed)

    def estat(rs):
        t = t_grupos(rs, w, gi, len(ext_of_int))
        return np.bincount(ext_of_int, weights=t * t, minlength=len(ge_idx)) / np.where(k > 0, k, 1)

    real = estat(r_std)
    maxs = np.array([estat(permuta_dentro(r_std, uf_code, rng))[k >= 2].max() if (k >= 2).any() else 0 for _ in range(n_perm)])
    lim = float(np.quantile(maxs, 0.95))
    return pd.DataFrame({'grupo_externo': [g.split('|', 1)[1] for g in ge_idx], 'uf': [g.split('|', 1)[0] for g in ge_idx],
                         'unidades_internas': k, 'chi2_medio': real, 'limite_p95': lim, 'acima_limite': (real >= lim) & (k >= 2)})


def demean_por(y, codes):
    """y menos a media do seu grupo (efeito fixo)."""
    y = np.asarray(y, float)
    k = int(codes.max()) + 1
    n = np.bincount(codes, minlength=k)
    m = np.bincount(codes, weights=y, minlength=k) / np.where(n > 0, n, 1)
    return y - m[codes]


def estat_entre_grupos(y, codes):
    """Soma de quadrados entre grupos / variancia total: sum_g n_g * (media_g - media)^2 / var(y) (~ qui-quadrado com
    k-1 graus sob o nulo). Grupo com 1 linha conta."""
    y = np.asarray(y, float)
    y = y - y.mean()
    k = int(codes.max()) + 1
    n = np.bincount(codes, minlength=k)
    s = np.bincount(codes, weights=y, minlength=k)
    v = y.var()
    if v <= 0:
        return 0.0
    return float(np.sum(s * s / np.where(n > 0, n, 1)) / v)


def efeito_dentro_predio(df, desfecho, atributo, predio='voting_place', zona='zona_id', n_perm=N_PERM, seed=SEED, min_niveis=2):
    """Efeito de um atributo tecnico (ex.: geracao da urna, maquina de carga) sobre um desfecho, tres vezes: bruto, com
    efeito fixo de zona e com efeito fixo de predio. A estatistica entre niveis do atributo e comparada a `n_perm`
    permutacoes do atributo entre secoes da mesma zona (quebra o atributo, mantem a geografia). Devolve
    (resumo dict, tabela por nivel do atributo com medias demeaned por predio)."""
    d = df.dropna(subset=[desfecho, atributo, predio, zona]).reset_index(drop=True)
    if len(d) < 10 or d[atributo].nunique() < min_niveis:
        return {'n': int(len(d)), 'status': NOT_COMP, 'motivo': 'menos de 2 niveis do atributo ou <10 secoes'}, pd.DataFrame()
    y = d[desfecho].to_numpy(float)
    a_code, a_idx = pd.factorize(d[atributo])
    z_code, _ = pd.factorize(d[zona])
    p_code, _ = pd.factorize(d[predio])
    y_z = demean_por(y, z_code)
    y_p = demean_por(y, p_code)
    # predios com mais de um nivel do atributo (so eles informam o efeito com efeito fixo de predio)
    pa = pd.DataFrame({'p': p_code, 'a': a_code}).drop_duplicates().groupby('p').size()
    predios_mistos = int((pa > 1).sum())
    secoes_mistas = int(pa.reindex(p_code).to_numpy().__gt__(1).sum())
    rng = np.random.default_rng(seed)
    real = {'bruto': estat_entre_grupos(y, a_code), 'ef_zona': estat_entre_grupos(y_z, a_code), 'ef_predio': estat_entre_grupos(y_p, a_code)}
    perms = {k: np.empty(n_perm) for k in real}
    for i in range(n_perm):
        ap = permuta_dentro(a_code, z_code, rng)
        perms['bruto'][i] = estat_entre_grupos(y, ap)
        perms['ef_zona'][i] = estat_entre_grupos(y_z, ap)
        perms['ef_predio'][i] = estat_entre_grupos(y_p, ap)
    res = {'n': int(len(d)), 'niveis': int(len(a_idx)), 'graus': int(len(a_idx)) - 1, 'predios': int(len(pa)), 'predios_mistos': predios_mistos,
           'secoes_em_predios_mistos': secoes_mistas, 'status': 'feita'}
    for k in real:
        res[f'estat_{k}'] = real[k]
        res[f'p_perm_{k}'] = float((np.sum(perms[k] >= real[k]) + 1) / (n_perm + 1))
        res[f'perm_p95_{k}'] = float(np.quantile(perms[k], 0.95))
    # tabela por nivel: media do desfecho demeaned por predio, erro-padrao, t
    n = np.bincount(a_code, minlength=len(a_idx))
    m_p = np.bincount(a_code, weights=y_p, minlength=len(a_idx)) / np.where(n > 0, n, 1)
    m_z = np.bincount(a_code, weights=y_z, minlength=len(a_idx)) / np.where(n > 0, n, 1)
    m_b = np.bincount(a_code, weights=y, minlength=len(a_idx)) / np.where(n > 0, n, 1)
    s2 = np.bincount(a_code, weights=(y_p - m_p[a_code]) ** 2, minlength=len(a_idx)) / np.where(n > 1, n - 1, 1)
    se = np.sqrt(s2 / np.where(n > 0, n, 1))
    tab = pd.DataFrame({atributo: a_idx, 'secoes': n, 'media_bruta': m_b, 'media_ef_zona': m_z, 'media_ef_predio': m_p,
                        'ep_ef_predio': se, 't_ef_predio': np.where(se > 0, m_p / np.where(se > 0, se, 1), 0.0)})
    return res, tab


def autocorrelacao_serie(df, desfecho, serie, zona='zona_id', predio='voting_place', n_perm=N_PERM, seed=SEED, janela=JANELA_SERIE):
    """Dentro de cada zona, ordena as secoes pelo numero de serie e mede (a) correlacao de 1a ordem do desfecho
    (demeaned por predio) entre vizinhas de serie em predios DIFERENTES e (b) variancia das medias de janelas de
    `janela` series consecutivas; nulo = embaralhar a ordem das series dentro da zona."""
    d = df.dropna(subset=[desfecho, serie, zona, predio]).copy()
    d = d.sort_values([zona, serie]).reset_index(drop=True)
    p_code, _ = pd.factorize(d[predio])
    z_code, _ = pd.factorize(d[zona])
    y = demean_por(d[desfecho].to_numpy(float), p_code)
    rng = np.random.default_rng(seed)

    def estat(yy):
        a, b = yy[:-1], yy[1:]
        mesma_zona = z_code[:-1] == z_code[1:]
        outro_predio = p_code[:-1] != p_code[1:]
        m = mesma_zona & outro_predio
        if m.sum() < 10:
            return np.nan, np.nan
        rho = float(np.corrcoef(a[m], b[m])[0, 1])
        # janelas de `janela` series consecutivas dentro da zona
        pos = np.arange(len(yy))
        inicio = np.r_[0, np.flatnonzero(np.diff(z_code)) + 1]
        rel = pos - np.repeat(inicio, np.diff(np.r_[inicio, len(yy)]))
        jan = z_code * 100000 + rel // janela
        jc, _ = pd.factorize(jan)
        n = np.bincount(jc)
        s = np.bincount(jc, weights=yy)
        cheia = n == janela
        var_jan = float(np.var(s[cheia] / janela)) if cheia.sum() > 5 else np.nan
        return rho, var_jan

    rho, vj = estat(y)
    rhos, vjs = np.empty(n_perm), np.empty(n_perm)
    for i in range(n_perm):
        yp = permuta_dentro(y, z_code, rng)
        rhos[i], vjs[i] = estat(yp)
    return {'n': int(len(d)), 'rho_lag1_outro_predio': rho, 'rho_perm_media': float(np.nanmean(rhos)),
            'rho_perm_p975': float(np.nanquantile(rhos, 0.975)), 'rho_perm_p025': float(np.nanquantile(rhos, 0.025)),
            'p_perm_rho': float((np.sum(np.abs(rhos) >= abs(rho)) + 1) / (n_perm + 1)) if np.isfinite(rho) else np.nan,
            'var_janelas': vj, 'var_janelas_perm_p95': float(np.nanquantile(vjs, 0.95)),
            'p_perm_var_janelas': float((np.sum(vjs >= vj) + 1) / (n_perm + 1)) if np.isfinite(vj) else np.nan,
            'janela': janela, 'n_perm': n_perm}


def bh(p, q=0.05):
    """Benjamini-Hochberg: devolve vetor booleano dos rejeitados a q."""
    p = np.asarray(p, float)
    ok = np.isfinite(p)
    out = np.zeros(len(p), bool)
    if ok.sum() == 0:
        return out
    idx = np.flatnonzero(ok)
    order = np.argsort(p[idx])
    ps = p[idx][order]
    m = len(ps)
    thr = q * np.arange(1, m + 1) / m
    below = np.flatnonzero(ps <= thr)
    if len(below):
        kmax = below.max()
        out[idx[order[:kmax + 1]]] = True
    return out


# ----------------------------------------------------------------------------------------------- carregadores
def carrega_geografia():
    """municipality (TSE) -> codigos IBGE de micro, meso, regiao imediata e intermediaria (+ nomes)."""
    m = pd.read_csv(REL / 'verificacoes' / 'eleitorado_populacao' / 'municipios.csv', sep=';', decimal=',', encoding='utf-8-sig',
                    usecols=['uf', 'municipality', 'municipio', 'ibge'])
    j = json.loads((R / 'ibge' / 'municipios.json').read_text(encoding='utf-8'))
    ib = pd.DataFrame([{'ibge': x['municipio-id'], 'micro': x['microrregiao-id'], 'micro_nome': x['microrregiao-nome'],
                        'meso': x['mesorregiao-id'], 'meso_nome': x['mesorregiao-nome'], 'imediata': x['regiao-imediata-id'],
                        'imediata_nome': x['regiao-imediata-nome'], 'intermediaria': x['regiao-intermediaria-id'],
                        'intermediaria_nome': x['regiao-intermediaria-nome']} for x in j])
    g = m.merge(ib, on='ibge', how='left')
    g['municipality'] = g['municipality'].astype(int)
    for c in NIVEIS_IBGE:
        g[c] = g[c].astype('Int64')
    return g


def carrega_secoes(ano, cols=None):
    cols = cols or KEY + ['voting_place', 'n2', 'z', 'res_pp']
    return pd.read_parquet(R / 'anomalias_2t' / f'secoes_{ano}.parquet', columns=cols)


def carrega_m5(ano):
    m = pd.read_csv(REL / 'verificacoes' / 'anomalias_2t' / f'm5_municipios_{ano}.csv', sep=';', decimal=',', encoding='utf-8-sig',
                    usecols=['uf', 'municipality', 'n2', 'previsto_pt_pct', 'observado_pt_pct', 'residuo_pp', 't1_comp', 't1_aptos'])
    m['municipality'] = m['municipality'].astype(int)
    return m


def carrega_integridade(eleicao, ufs=None, con=None):
    """Por urna: chave da secao (13 digitos finais do stem), numero de serie (cert_cn), geracao (cert_emissor)."""
    con = con or duck()
    p = str(REL / 'integridade' / 'integridade_todas_urnas.parquet').replace('\\', '/')
    w = f"eleicao = '{eleicao}'" + (f" and uf in ({','.join(repr(u) for u in ufs)})" if ufs else '')
    d = con.execute(f"select uf, urna, cert_cn, cert_emissor, assinado_em from '{p}' where {w}").df()
    k = chave_stem(d['urna'])
    d = pd.concat([d, k], axis=1)
    d['cert_num'] = pd.to_numeric(d['cert_cn'].str.extract(r'(\d+)$', expand=False), errors='coerce')
    return d


def carrega_ceft(pleito, uf, con=None):
    """CEFT com chave inteira, urna esperada/efetivada, data da carga, maquina de geracao de midia (2024+)."""
    con = con or duck()
    p = R / 'ceft' / pleito / f'{uf}.parquet'
    if not p.exists():
        return None
    import pyarrow.parquet as pq
    names = pq.ParquetFile(p).schema_arrow.names
    quer = ['CD_MUNICIPIO', 'NR_ZONA', 'NR_SECAO', 'NR_LOCAL_VOTACAO', 'NR_URNA_ESPERADA', 'NR_URNA_EFETIVADA',
            'DT_CARGA_URNA_ESPERADA', 'DT_CARGA_URNA_EFETIVADA', 'CD_CARGA_URNA_EFETIVADA', 'DS_ORIGEM_VOTO', 'TP_DIVERGENCIA',
            'DS_DIVERGENCIA', 'NM_MAQUINA_GERACAO_MIDIA', 'NM_MAQUINA_TRANSM_CORRESP']
    cols = [c for c in quer if c in names]
    d = con.execute(f"select {', '.join(cols)} from '{str(p).replace(chr(92), '/')}'").df()
    d = d.rename(columns={'CD_MUNICIPIO': 'municipality', 'NR_ZONA': 'zone', 'NR_SECAO': 'section', 'NR_LOCAL_VOTACAO': 'voting_place',
                          'NR_URNA_ESPERADA': 'urna_esperada', 'NR_URNA_EFETIVADA': 'urna_efetivada',
                          'DT_CARGA_URNA_ESPERADA': 'dt_carga_esperada', 'DT_CARGA_URNA_EFETIVADA': 'dt_carga',
                          'CD_CARGA_URNA_EFETIVADA': 'cd_carga', 'DS_ORIGEM_VOTO': 'origem_voto', 'NM_MAQUINA_GERACAO_MIDIA': 'maquina',
                          'NM_MAQUINA_TRANSM_CORRESP': 'maquina_transm'})
    d['divergencia'] = d['TP_DIVERGENCIA'] if 'TP_DIVERGENCIA' in d else d.get('DS_DIVERGENCIA')
    d = d.drop(columns=[c for c in ('TP_DIVERGENCIA', 'DS_DIVERGENCIA') if c in d])
    for c in ('municipality', 'zone', 'section', 'voting_place', 'urna_esperada', 'urna_efetivada'):
        if c in d:
            d[c] = pd.to_numeric(d[c], errors='coerce')
    for c in ('dt_carga', 'dt_carga_esperada'):
        s = d[c].astype('string')
        barra = s.str.contains('/', na=False)
        d[c] = pd.to_datetime(s.where(~barra), errors='coerce', format='%Y-%m-%d %H:%M:%S')
        d.loc[barra, c] = pd.to_datetime(s[barra], errors='coerce', format='%d/%m/%Y %H:%M')
    d['uf'] = uf
    d['troca'] = d['urna_esperada'] != d['urna_efetivada']
    return d


def carrega_indicadores(rotulo, cols=None):
    cols = cols or KEY + ['voting_place', 'eligible', 'attendance', 'share_a', 'manual_share', 'late_share', 'close_min', 'contingency', 'has_log']
    d = pd.read_parquet(REL / 'fiscalizacao' / f'secoes_indicadores_{rotulo}.parquet', columns=cols)
    for c in ('municipality', 'zone', 'section'):
        d[c] = d[c].astype(int)
    if 'voting_place' in d:
        d['voting_place'] = pd.to_numeric(d['voting_place'], errors='coerce')
    return d


def carrega_bins(ano):
    return pd.read_parquet(R / 'janelas_horario' / f'bins_{ano}.parquet', columns=KEY + ['n_logs', 'contingencia'])


def carrega_base(ano, cols):
    return pd.read_parquet(R / 'padroes_2t' / f'base_{ano}.parquet', columns=cols)


def zona_id(df):
    return df['uf'].astype(str) + '|' + df['zone'].astype(int).astype(str)


def predio_id(df):
    """Local de votacao: o numero (NR_LOCAL_VOTACAO) so e unico dentro da zona, entao a chave e uf|municipio|zona|local.
    Local nulo -> NaN (a secao fica fora dos testes com efeito fixo de predio)."""
    vp = pd.to_numeric(df['voting_place'], errors='coerce')
    k = (df['uf'].astype(str) + '|' + df['municipality'].astype('Int64').astype(str) + '|' + df['zone'].astype('Int64').astype(str)
         + '|' + vp.astype('Int64').astype(str))
    return k.where(vp.notna())


def junta_geografia(df, geo):
    return df.merge(geo[['uf', 'municipality'] + NIVEIS_IBGE], on=['uf', 'municipality'], how='left')


# ----------------------------------------------------------------------------------------------- C8-01
def c8_01_scan_m5(m5, geo, n_perm=N_PERM, seed=SEED):
    """Scan do residuo M5 (municipio previsto pelas outras UFs) agregado a micro/meso/imediata/intermediaria;
    nulo = permutacao dos rotulos de municipio dentro da UF. Devolve (grupos, limites, municipios com |r_std| >= 4)."""
    d = junta_geografia(m5, geo)
    d = d[d['n2'] > 0].copy()
    d['municipio_bloco'] = d['uf'].astype(str) + '|' + d['municipality'].astype(str)
    grupos, limites = scan_hierarquico(d, 'residuo_pp', 'n2', NIVEIS_IBGE, 'municipio_bloco', n_perm=n_perm, seed=seed)
    uf_code, _ = pd.factorize(d['uf'])
    d['r_std'] = padroniza_por_uf(d['residuo_pp'].to_numpy(float), d['n2'].to_numpy(float), uf_code)
    isolados = d[np.abs(d['r_std']) >= 4][['uf', 'municipality', 'n2', 'residuo_pp', 'r_std'] + NIVEIS_IBGE]
    return grupos, limites, isolados


def c8_01_scan_m1(sec, geo, bloco='secao', n_perm=N_PERM, seed=SEED):
    """Scan do residuo M1 (res_pp, relativo ao predio) por zona/municipio/micro/meso; nulo = permutacao de secoes
    (bloco='secao') ou de predios inteiros (bloco='predio') dentro da UF."""
    d = junta_geografia(sec, geo)
    d = d[d['n2'] > 0].copy()
    d['zona'] = d['zone']
    d['municipio'] = d['municipality']
    d['bloco'] = np.arange(len(d)) if bloco == 'secao' else predio_id(d).fillna('secao|' + pd.Series(np.arange(len(d)), index=d.index).astype(str))
    niveis = ['zona', 'municipio'] + NIVEIS_IBGE
    return scan_hierarquico(d, 'res_pp', 'n2', niveis, 'bloco', n_perm=n_perm, seed=seed)


def roda_c8_01(resumo, achados, cache):
    geo = carrega_geografia()
    cache['geo'] = geo
    csv_out('C8-01_geografia.csv', geo)
    arqs, nums = [], {}
    # (a) M5 por hierarquia, 2026 e 2022
    tabs, lims = [], []
    for ano in (2026, 2022):
        m5 = carrega_m5(ano)
        g, lim, iso = c8_01_scan_m5(m5, geo)
        g['ano'] = ano
        lim['ano'] = ano
        iso['ano'] = ano
        tabs.append(g)
        lims.append(lim)
        if len(iso):
            arqs.append(csv_out(f'C8-01_m5_municipios_isolados_{ano}.csv', iso))
        nums[f'm5_{ano}'] = {r['nivel']: {'limite_p95': round(r['limite_p95_max_abs_t'], 3), 'max_abs_t': round(r['max_abs_t_real'], 3),
                                          'acima': int(r['acima_limite']), 'grupos': int(r['grupos'])} for _, r in lim.iterrows()}
        nums[f'm5_{ano}']['municipios_abs_rstd_ge_4'] = int(len(iso))
        nums[f'm5_{ano}']['municipios_sem_geografia'] = int(lim['sem_rotulo'].max())
    g = pd.concat(tabs, ignore_index=True)
    geo_nomes = geo.drop_duplicates('micro').set_index('micro')['micro_nome'].to_dict()
    geo_nomes.update(geo.drop_duplicates('meso').set_index('meso')['meso_nome'].to_dict())
    geo_nomes.update(geo.drop_duplicates('imediata').set_index('imediata')['imediata_nome'].to_dict())
    geo_nomes.update(geo.drop_duplicates('intermediaria').set_index('intermediaria')['intermediaria_nome'].to_dict())
    g['nome'] = pd.to_numeric(g['grupo'], errors='coerce').map(geo_nomes)
    # lado a lado: 2026 x 2022 no mesmo grupo
    lado = g[g.ano == 2026].merge(g[g.ano == 2022][['nivel', 'grupo', 't', 'media_ponderada', 'acima_limite', 'limite_p95']], on=['nivel', 'grupo'],
                                  how='left', suffixes=('_2026', '_2022'))
    lado = lado.sort_values('t_2026', key=np.abs, ascending=False)
    p_scan = csv_out('C8-01_m5_scan_grupos.csv', lado)
    p_lim = csv_out('C8-01_m5_scan_limites.csv', pd.concat(lims, ignore_index=True))
    arqs += [p_scan, p_lim]
    acima = lado[lado['acima_limite_2026'] | lado['acima_limite_2022'].fillna(False)]
    nums['m5_grupos_acima_2026'] = int(lado['acima_limite_2026'].sum())
    nums['m5_grupos_acima_2022'] = int(lado['acima_limite_2022'].fillna(False).sum())
    nums['m5_top_2026'] = [f"{r.nivel} {r.uf} {r.grupo} {r.nome}: t {r.t_2026:.2f} ({r.media_ponderada_2026:+.2f} pp; 2022 t {r.t_2022:.2f})"
                           for r in lado.head(8).itertuples()]
    del m5
    gc.collect()
    # (b) M1 por hierarquia (secoes e predios como bloco), 2026 e 2022, e dispersao entre municipios da mesma micro
    tabs, lims, disp = [], [], []
    for ano in (2026, 2022):
        sec = carrega_secoes(ano)
        for bloco in ('secao', 'predio'):
            gg, lim = c8_01_scan_m1(sec, geo, bloco=bloco)
            gg['ano'] = ano
            gg['bloco'] = bloco
            lim['ano'] = ano
            lim['bloco'] = bloco
            tabs.append(gg[gg['acima_limite'] | (gg['t'].abs() >= 4)])
            lims.append(lim)
            nums[f'm1_{ano}_{bloco}'] = {r['nivel']: {'limite_p95': round(r['limite_p95_max_abs_t'], 3), 'max_abs_t': round(r['max_abs_t_real'], 3),
                                                      'acima': int(r['acima_limite'])} for _, r in lim.iterrows()}
        dd = junta_geografia(sec, geo)
        dd = dd[dd['n2'] > 0]
        di = dispersao_dentro(dd, 'res_pp', 'n2', 'municipality', 'micro')
        di['ano'] = ano
        di['nome'] = pd.to_numeric(di['grupo_externo'], errors='coerce').map(geo_nomes)
        disp.append(di)
        nums[f'm1_dispersao_micro_{ano}'] = {'limite_p95': round(float(di['limite_p95'].iloc[0]), 3), 'max': round(float(di['chi2_medio'].max()), 3),
                                             'acima': int(di['acima_limite'].sum())}
        # media municipal do M1: desvio-padrao entre municipios (mostra que o M1 e relativo ao predio)
        mm = dd.groupby(['uf', 'municipality']).apply(lambda x: np.average(x['res_pp'], weights=x['n2'])) if len(dd) else pd.Series(dtype=float)
        nums[f'm1_sd_media_municipal_{ano}'] = round(float(mm.std()), 4)
        nums[f'm1_sd_secao_{ano}'] = round(float(dd['res_pp'].std()), 4)
        del sec, dd
        gc.collect()
    m1acima = pd.concat(tabs, ignore_index=True)
    m1acima['nome'] = pd.to_numeric(m1acima['grupo'], errors='coerce').map(geo_nomes).where(m1acima['nivel'].isin(NIVEIS_IBGE))
    p_m1 = csv_out('C8-01_m1_scan_grupos_acima.csv', m1acima)
    arqs.append(p_m1)
    sa = m1acima[(m1acima['bloco'] == 'secao') & m1acima['acima_limite']]
    if len(sa):
        desc = '; '.join(f'{r.ano} {r.nivel} {r.uf} {r.grupo} {r.nome if isinstance(r.nome, str) else ""}: t {r.t:+.2f} (lim {r.limite_p95:.2f}; '
                         f'{r.media_ponderada:+.3f} pp; {int(r.unidades)} secoes)' for r in sa.sort_values(['ano', 'nivel']).itertuples())
        n26, n22 = int((sa.ano == 2026).sum()), int((sa.ano == 2022).sum())
        achados.append(_achado(
            'C8-01', f'Residuo M1 (relativo ao predio) agregado por regiao: {n26} grupos acima do limite em 2026 e {n22} em 2022 (nulo de secoes)',
            '2026-t2 / 2022-t2', 'PRESIDENTE', ', '.join(sorted(sa.uf.unique())), f'{len(sa)} grupos-nivel', 'cluster territorial (M1)', desc,
            float(sa.loc[sa.ano == 2026, 't'].abs().max()) if n26 else 0.0, 0,
            int((sa['media_ponderada'].abs() / 100 * sa['peso_total']).max()), 'margem nacional 2026 T2; efeito em pp do residuo dentro do predio',
            'M1 ja e relativo ao predio (media municipal do residuo com dp ~0,10 pp); nulo por permutacao de secoes dentro da UF; mesma especificacao em 2022',
            f'2022 com a mesma especificacao: {n22} grupos acima (mesma ordem de grandeza que 2026: {n26})',
            ['acaso de familia (6 niveis x 2 anos; grupos aninhados contam o mesmo sinal varias vezes)', 'heterogeneidade do modelo de predio por regiao'],
            'PLAUSIVEL-EXPLICAVEL', 'nenhum (teste interno); malha de vizinhanca IBGE para scan contiguo', [p_m1], 3))
    arqs.append(csv_out('C8-01_m1_scan_limites.csv', pd.concat(lims, ignore_index=True)))
    arqs.append(csv_out('C8-01_m1_dispersao_municipios_na_micro.csv', pd.concat(disp, ignore_index=True).sort_values('chi2_medio', ascending=False)))
    nums['nota_nulo_predio'] = ('M1 e centrado no predio (soma ponderada do residuo padronizado por predio = 1% da soma por secao); permutar predios '
                                'inteiros quase zera os grupos e o limite cai para 0,3-1,4, entao os 86-215 grupos acima por nivel com bloco=predio medem so '
                                'a parte nao centrada do modelo (|media| <= 0,25 pp, 2022 igual a 2026) - ARTEFATO do nulo; a referencia e o nulo de secoes')
    _rec(resumo, 'C8-01', 'feita', nums, arqs)
    for r in acima.itertuples():
        quando = ' e '.join(a for a, f in (('2026', r.acima_limite_2026), ('2022 (controle)', bool(r.acima_limite_2022) if pd.notna(r.acima_limite_2022) else False)) if f)
        achados.append(_achado(
            'C8-01', f'Grupo {r.nivel} {r.uf} {r.grupo} ({r.nome}): media do residuo M5 acima do limite de permutacao em {quando}', '2026-t2 / 2022-t2',
            'PRESIDENTE', r.uf, f'{int(r.unidades)} municipios; {int(r.peso_total):,} votos', 'cluster territorial (M5)',
            f'media ponderada do residuo M5 {r.media_ponderada_2026:+.2f} pp (t {r.t_2026:.2f}, limite p95 {r.limite_p95_2026:.2f}) em 2026; '
            f'2022 {r.media_ponderada_2022:+.2f} pp (t {r.t_2022:.2f}, limite p95 {r.limite_p95_2022:.2f})', float(r.media_ponderada_2026),
            int(abs(r.media_ponderada_2026) / 100 * r.peso_total * 0.5), int(abs(r.media_ponderada_2026) / 100 * r.peso_total),
            'margem nacional 2026 T2 (mun_todos.parquet); o M5 e previsao por composicao do 1o turno, nao margem',
            'M5 e modelo treinado nas outras UFs; residuo por municipio ja publicado; permutacao de rotulos dentro da UF',
            '2022 com a mesma especificacao (lado a lado no CSV)', ['gradiente regional real (composicao nao capturada pelo M5)',
            'heterogeneidade do modelo por UF', 'acaso de familia: 4 niveis x 2 anos com limite p95 do maximo dao ~0,4 grupo esperado'],
            'PLAUSIVEL-EXPLICAVEL', 'perfil do eleitorado 2026 por secao (TSE); malha de vizinhanca IBGE', [p_scan, p_lim], 2 if r.acima_limite_2026 else 3))


# ----------------------------------------------------------------------------------------------- C8-02 / C8-09
def _integ_chave(eleicao, con):
    """Integridade por urna com chave inteira; stem sem chave ou sem certificado -> quarentena (C8-02)."""
    integ = carrega_integridade(eleicao, con=con)
    ruim = integ['municipality'].isna()
    quarentena('C8-02', integ[ruim][['uf', 'urna', 'cert_cn', 'cert_emissor']], f'{eleicao}: stem sem 13 digitos finais')
    d = integ[~ruim].drop(columns=['urna', 'assinado_em']).copy()
    for c in ('municipality', 'zone', 'section'):
        d[c] = d[c].astype(int)
    sem_cert = d['cert_emissor'].isna() | d['cert_num'].isna()
    quarentena('C8-02', d[sem_cert][['uf', 'municipality', 'zone', 'section', 'cert_cn', 'cert_emissor']],
               f'{eleicao}: urna sem certificado (sem arquivo de assinatura) - geracao/serie nulas')
    return d


def _finaliza_tec(d):
    d['zona_id'] = zona_id(d)
    d['predio_id'] = predio_id(d)
    d['geracao'] = d['cert_emissor']
    d['bloco_serie'] = (d['cert_num'] // BLOCO_SERIE).astype('Int64')
    d['vinculo'] = np.where(d['predio_id'].isna(), NOT_COMP + ': sem secao/local no desfecho', 'ok')
    return d.drop(columns=['cert_cn'])


def _montar_2022t2(con):
    d = _integ_chave('2022-t2', con)
    sec = carrega_secoes(2022, KEY + ['n2', 'res_pp'])
    base = carrega_base(2022, KEY + ['voting_place', 't2_manual', 't2_comp', 't2_enc_min'])
    bins = carrega_bins(2022)
    d = d.merge(sec, on=KEY, how='left').merge(base, on=KEY, how='left').merge(bins, on=KEY, how='left')
    d['manual_share'] = d['t2_manual'] / d['t2_comp'].where(d['t2_comp'] > 0)
    d['enc_min'] = d['t2_enc_min']
    d['contingencia'] = d['contingencia'].astype(float)
    del sec, base, bins
    gc.collect()
    return _finaliza_tec(d.drop(columns=['t2_manual', 't2_enc_min', 'n_logs']))


def _montar_2026t1(con):
    d = _integ_chave('2026-t1', con)
    ind = carrega_indicadores('P2026', KEY + ['voting_place', 'share_a', 'manual_share', 'late_share', 'close_min', 'contingency'])
    d = d.merge(ind, on=KEY, how='left')
    d['enc_min'] = d['close_min']
    d['contingencia'] = d['contingency'].astype(float)
    del ind
    gc.collect()
    return _finaliza_tec(d.drop(columns=['close_min', 'contingency']))


def _montar_2026t2(con):
    d = _integ_chave('2026-t2', con)
    sec = carrega_secoes(2026, KEY + ['n2', 'res_pp'])
    base = carrega_base(2026, KEY + ['voting_place', 't2_manual', 't2_comp', 't2_enc_min'])
    bins = carrega_bins(2026)
    d = d.merge(sec, on=KEY, how='left').merge(base, on=KEY, how='left').merge(bins, on=KEY, how='left')
    d['manual_share'] = d['t2_manual'] / d['t2_comp'].where(d['t2_comp'] > 0)
    d['enc_min'] = d['t2_enc_min']
    d['contingencia'] = d['contingencia'].astype(float)
    del sec, base, bins
    gc.collect()
    return _finaliza_tec(d.drop(columns=['t2_manual', 't2_enc_min', 'n_logs']))


def c8_02_geracao(d, desfechos):
    """Efeito da geracao (cert_emissor) e do bloco de 1.000 series sobre cada desfecho, bruto / ef. zona / ef. predio."""
    linhas, tabs = [], []
    sem_cont = d[d['contingencia'] == 0] if 'contingencia' in d else d
    for nome, col in desfechos.items():
        # a urna da secao com contingencia e a substituta (reserva, serie e geracao proprias): o vinculo atributo x desfecho
        # de processo e mecanico nessas secoes; repete-se o teste sem elas (sufixo |sem_contingencia)
        variantes = [(nome, d)] + ([(f'{nome}|sem_contingencia', sem_cont)] if col not in ('res_pp', 'share_a', 'contingencia') else [])
        for nome_v, dv in variantes:
            for atributo in ('geracao', 'bloco_serie'):
                res, tab = efeito_dentro_predio(dv, col, atributo, predio='predio_id')
                res.update({'desfecho': nome_v, 'atributo': atributo})
                linhas.append(res)
                if atributo == 'geracao' and len(tab):
                    tab['desfecho'] = nome_v
                    tabs.append(tab)
    return pd.DataFrame(linhas), (pd.concat(tabs, ignore_index=True) if tabs else pd.DataFrame())


def roda_c8_02(resumo, achados, cache):
    con = duck()
    arqs, nums = [], {}
    resumos, niveis = [], []
    for rotulo, montar, desfechos in (
            ('2022-t2', _montar_2022t2, {'res_pp_M1': 'res_pp', 'manual_share': 'manual_share', 'enc_min': 'enc_min', 'contingencia': 'contingencia'}),
            ('2026-t1', _montar_2026t1, {'share_a': 'share_a', 'manual_share': 'manual_share', 'enc_min': 'enc_min', 'contingencia': 'contingencia', 'late_share': 'late_share'}),
            ('2026-t2_amostra', _montar_2026t2, {'res_pp_M1': 'res_pp', 'manual_share': 'manual_share', 'enc_min': 'enc_min', 'contingencia': 'contingencia'})):
        d = montar(con)
        sem_chave = int((d['vinculo'] != 'ok').sum())
        cache[f'tec_{rotulo}'] = d
        r, tab = c8_02_geracao(d, desfechos)
        r['pleito'] = rotulo
        tab['pleito'] = rotulo
        resumos.append(r)
        niveis.append(tab)
        ger = d['geracao'].value_counts(dropna=False).to_dict()
        nums[rotulo] = {'urnas': int(len(d)), 'sem_vinculo_com_secao': sem_chave, 'geracoes': {str(k): int(v) for k, v in ger.items()},
                        'predios_mistos_geracao': int(r[(r.atributo == 'geracao')]['predios_mistos'].max()),
                        'efeitos': {f"{x.desfecho}/{x.atributo}": {'estat_predio': round(float(x.estat_ef_predio), 2), 'p_perm_predio': round(float(x.p_perm_ef_predio), 4),
                                                                   'estat_zona': round(float(x.estat_ef_zona), 2), 'p_perm_zona': round(float(x.p_perm_ef_zona), 4),
                                                                   'estat_bruto': round(float(x.estat_bruto), 2), 'p_perm_bruto': round(float(x.p_perm_bruto), 4)}
                                    for x in r.itertuples() if x.status == 'feita'}}
        for x in tab[tab.desfecho == list(desfechos)[0]].itertuples():
            nums[rotulo][f'{list(desfechos)[0]}_{x.geracao}_media_ef_predio'] = round(float(x.media_ef_predio), 4)
        print(f'  C8-02 {rotulo}: {len(d)} urnas', flush=True)
    rr = pd.concat(resumos, ignore_index=True)
    arqs.append(csv_out('C8-02_tecnico_vs_geografia_resumo.csv', rr))
    arqs.append(csv_out('C8-02_geracao_por_nivel.csv', pd.concat(niveis, ignore_index=True)))
    rr['bh_5pct'] = bh(rr['p_perm_ef_predio'].to_numpy(float))
    rr.to_csv(arqs[0], **CSV)
    nums['testes'] = int((rr.status == 'feita').sum())
    nums['bh_5pct_rejeicoes_ef_predio'] = int(rr['bh_5pct'].sum())
    nums['p_perm_ef_predio_lt_005'] = int((rr['p_perm_ef_predio'] < 0.05).sum())
    _rec(resumo, 'C8-02', 'feita', nums, arqs)
    t_all = pd.concat(niveis, ignore_index=True)
    fonte = arqs
    # (A) resultado: geracao e bloco de serie dentro do predio
    res = rr[rr.desfecho.isin(['res_pp_M1', 'share_a']) & (rr.status == 'feita')]
    tg = t_all[t_all.desfecho.isin(['res_pp_M1', 'share_a'])]
    achados.append(_achado(
        'C8-02', 'Geracao da urna e faixa de numero de serie x resultado dentro do predio: nenhuma diferenca acima do limiar (refaz o teste de SP 2022 em 11 UFs)',
        '2022-t2 / 2026-t1 / 2026-t2 (amostra)', 'PRESIDENTE', '11 UFs (14 na amostra 2026 T2)',
        '; '.join(f'{x.pleito} {x.desfecho}/{x.atributo}: {x.n} urnas, {x.predios_mistos} predios mistos' for x in res.itertuples()),
        'cluster tecnico (resultado) - negativo',
        '; '.join(f'{x.pleito} {x.desfecho}/{x.atributo}: p perm ef. predio {x.p_perm_ef_predio:.3f}' for x in res.itertuples()) + ' | medias ef. predio (pp): '
        + '; '.join(f'{r.pleito} {r.geracao} {r.media_ef_predio:+.4f} (t {r.t_ef_predio:+.2f})' for r in tg.itertuples()),
        float(res['p_perm_ef_predio'].min()), 0,
        int(tg[tg.desfecho == 'res_pp_M1']['media_ef_predio'].abs().max() / 100 * float(cache['tec_2022-t2']['n2'].sum())),
        'margem nacional; teto = maior |media ef. predio| do residuo M1 x votos validos A+B das urnas de 2022 T2 com residuo',
        'efeito fixo de predio (uf|municipio|zona|local); permutacao do atributo dentro da zona; vinculo pelos 13 digitos do stem (0 stems invalidos)',
        '2022 T2 e 2026 lado a lado; poucos predios mistos (as urnas sao distribuidas por predio), por isso a faixa de serie (blocos de 1.000) tambem foi testada',
        ['geracao distribuida por predio: o teste dentro do predio tem pouca variacao (156 predios mistos em 2022 T2)'], 'EXPLICADO',
        'modelo exato por urna (C8-07) para os predios sem mistura', fonte, 3))
    # (B) processo: geracao dentro da zona e bloco de serie dentro do predio
    pz = t_all[t_all.desfecho.isin(['contingencia', 'manual_share'])]
    zz = rr[rr.desfecho.isin(['contingencia', 'manual_share']) & (rr.atributo == 'geracao') & (rr.status == 'feita')]
    achados.append(_achado(
        'C8-02', 'Urnas da geracao antiga (AC URNA) concentram contingencia e habilitacao manual dentro da mesma zona, em 2022 e 2026',
        '2022-t2 / 2026-t1 / 2026-t2 (amostra)', 'PRESIDENTE', '11 UFs', f'{int(pz.secoes.sum() // max(len(pz.desfecho.unique()), 1)):,} urnas',
        'cluster tecnico (processo)', 'media bruta por geracao: ' + '; '.join(f'{r.pleito} {r.desfecho} {r.geracao} {r.media_bruta:.4f} (ef. zona {r.media_ef_zona:+.4f})'
                                                                          for r in pz.itertuples())
        + ' | ef. zona: ' + '; '.join(f'{x.pleito} {x.desfecho} estat {x.estat_ef_zona:.0f} ({x.graus} gl, p {x.p_perm_ef_zona:.3f}); ef. predio p {x.p_perm_ef_predio:.3f}'
                                      for x in zz.itertuples()),
        float(zz['estat_ef_zona'].max()) if len(zz) else 0.0, 0, 0, 'desfecho de processo: sem materialidade direta em votos',
        'mesmo desenho nos tres pleitos; dentro do predio (poucos predios mistos) a diferenca desaparece, ou seja, segue o predio',
        '2022 T2 e 2026 T1 com o mesmo sinal; persistencia por zona ja documentada (multiano)',
        ['urnas antigas (leitor biometrico antigo) falham mais e pedem mais liberacao manual', 'urnas antigas alocadas a predios com outro perfil de eleitor (rural, idoso)',
         'contingencia: a urna registrada na secao e a substituta (reserva), o que liga geracao e contingencia mecanicamente'],
        'PLAUSIVEL-EXPLICAVEL', 'modelo exato e leitor biometrico por urna (C8-07, C8-06); criterio de alocacao de urnas do TRE', fonte, 2))
    bs = rr[(rr.atributo == 'bloco_serie') & (rr.status == 'feita') & ~rr.desfecho.isin(['res_pp_M1', 'share_a'])]
    rej = bs[bs['bh_5pct']]
    if len(rej):
        achados.append(_achado(
            'C8-02', f'Faixa de numero de serie (blocos de {BLOCO_SERIE}) associada a variaveis de processo dentro do predio ({len(rej)} de {len(bs)} testes, BH 5%)',
            '2022-t2 / 2026-t1 / 2026-t2 (amostra)', 'PRESIDENTE', '11 UFs (14 na amostra)', '; '.join(f'{x.pleito} {x.desfecho}' for x in rej.itertuples()),
            'cluster tecnico (serie x processo)', '; '.join(f'{x.pleito} {x.desfecho}: estat {x.estat_ef_predio:.0f} vs p95 perm {x.perm_p95_ef_predio:.0f} '
                                                          f'({x.graus} gl, p {x.p_perm_ef_predio:.3f})' for x in bs.itertuples()),
            float(rej['estat_ef_predio'].max() / rej['perm_p95_ef_predio'].max()), 0, 0, 'processo; sem materialidade em votos',
            'efeito fixo de predio; permutacao na zona; variante sem as secoes com contingencia (sufixo |sem_contingencia) para retirar a urna substituta',
            'mesmo teste em 2022 T2 e 2026; resultado (res_pp/share_a) sem efeito de serie',
            ['urnas de reserva (series proprias) entram nas secoes com contingencia', 'faixas de serie = modelo (UE2009/10/11/13/15/20/22) com leitor diferente',
             'series contiguas carregadas juntas (mesma data/maquina)'], 'PLAUSIVEL-EXPLICAVEL', 'modelo por urna (C8-07); lote/fornecimento das urnas', fonte, 2))
    del con


def roda_c8_09(resumo, achados, cache):
    arqs, nums, linhas = [], {}, []
    montar = {'2022-t2': _montar_2022t2, '2026-t1': _montar_2026t1, '2026-t2_amostra': _montar_2026t2}
    for rotulo, col in (('2022-t2', 'res_pp'), ('2026-t1', 'share_a'), ('2026-t2_amostra', 'res_pp')):
        d = cache.pop(f'tec_{rotulo}', None)
        if d is None:
            d = montar[rotulo](duck())
        sem_cont = d[d['contingencia'] == 0]
        for desf, dv, rot_d in ((col, d, col), ('manual_share', d, 'manual_share'), ('contingencia', d, 'contingencia'),
                                ('manual_share', sem_cont, 'manual_share|sem_contingencia'), ('enc_min', sem_cont, 'enc_min|sem_contingencia')):
            if desf not in dv:
                continue
            r = autocorrelacao_serie(dv, desf, 'cert_num', predio='predio_id')
            desf = rot_d
            r.update({'pleito': rotulo, 'desfecho': desf})
            linhas.append(r)
            nums[f'{rotulo}/{desf}'] = {'rho_lag1': round(r['rho_lag1_outro_predio'], 4), 'p_perm_rho': r['p_perm_rho'],
                                        'rho_perm_ic95': [round(r['rho_perm_p025'], 4), round(r['rho_perm_p975'], 4)],
                                        'var_janelas20': r['var_janelas'], 'p_perm_var': r['p_perm_var_janelas']}
    rr = pd.DataFrame(linhas)
    rej = bh(np.r_[rr['p_perm_rho'].to_numpy(float), rr['p_perm_var_janelas'].to_numpy(float)])
    rr['bh_rho'], rr['bh_var'] = rej[:len(rr)], rej[len(rr):]
    arqs.append(csv_out('C8-09_autocorrelacao_serie.csv', rr))
    nums['bh_5pct_rejeicoes'] = int(rej.sum())
    nums['testes'] = int(len(rej))
    _rec(resumo, 'C8-09', 'feita', nums, arqs)
    achados_c8_09(rr, arqs, achados)


def achados_c8_09(rr, arqs, achados):
    """Um achado consolidado: autocorrelacao ao longo da serie (processo) com o resultado como contraste."""
    achados[:] = [a for a in achados if not a['id_sugerido'].startswith('C8-09-')]
    _ACHADOS_N['C8-09'] = 0
    rej = rr[rr['bh_rho'] | rr['bh_var']]
    res = rr[rr.desfecho.isin(['res_pp', 'share_a'])]
    achados.append(_achado(
        'C8-09', f'Ordem do numero de serie da urna: {len(rej)} de {len(rr)} desfechos com autocorrelacao acima do limiar (BH 5%), todos de processo; '
                 'resultado sem autocorrelacao',
        '2022-t2 / 2026-t1 / 2026-t2 (amostra)', 'PRESIDENTE', '11 UFs (14 na amostra 2026 T2)', f'{int(rr.n.max()):,} urnas por pleito no maximo',
        'cluster tecnico (serie)',
        'rho lag-1 entre vizinhas de serie em predios diferentes da mesma zona (IC95 perm): '
        + '; '.join(f'{x.pleito} {x.desfecho} {x.rho_lag1_outro_predio:+.4f} ({x.rho_perm_p025:+.4f}..{x.rho_perm_p975:+.4f}; BH {"sim" if x.bh_rho or x.bh_var else "nao"})'
                    for x in rr.itertuples()),
        float(rej['rho_lag1_outro_predio'].abs().max()) if len(rej) else 0.0, 0, 0,
        'processo; resultado (res_pp/share_a) dentro do IC de permutacao nos tres pleitos: ' + '; '.join(
            f'{x.pleito} p {x.p_perm_rho:.3f}' for x in res.itertuples()),
        'demeaned por predio; so pares de predios diferentes; permutacao da ordem dentro da zona; variante sem secoes com contingencia (urna substituta)',
        '2022 T2 e 2026 lado a lado: manual sem contingencia correlaciona ao longo da serie em 2022 (rho +0,034) e nao em 2026 T1 (+0,001); contingencia nos tres',
        ['urnas de reserva (series contiguas) usadas nas trocas da mesma zona', 'faixas de serie = modelo de urna/leitor biometrico (2022: AC URNA com '
         'modelos 2009-2015)', 'series contiguas distribuidas a predios vizinhos com perfil parecido'],
        'PLAUSIVEL-EXPLICAVEL', 'modelo por urna (C8-07); lote/fornecimento das urnas; registro de urnas de reserva por zona', arqs, 3))


def roda_c8_09a(resumo, achados, cache):
    """Refaz so os achados de C8-09 a partir do CSV ja gravado (sem reler dados)."""
    p = OUT / 'C8-09_autocorrelacao_serie.csv'
    rr = pd.read_csv(p, sep=';', decimal=',', encoding='utf-8-sig')
    for c in ('bh_rho', 'bh_var'):
        rr[c] = rr[c].astype(str).str.lower().eq('true')
    achados_c8_09(rr, [str(p)], achados)


# ----------------------------------------------------------------------------------------------- C8-03 / C8-10
def c8_03_maquina(d, desfechos, atributos=('maquina', 'dia_carga', 'turno_carga'), com_troca=('troca_ceft', 'contingencia')):
    """Efeito de maquina de geracao de midia / dia / turno da carga (da urna ESPERADA) sobre cada desfecho, dentro do predio.
    Desfechos de resultado e processo usam so secoes sem troca no CEFT (a urna efetivada e a carregada pelo atributo);
    troca e contingencia usam todas as secoes (atributo da urna esperada, anterior a troca)."""
    linhas, tabs = [], []
    for nome, col in desfechos.items():
        dd = d if nome in com_troca else d[~d['troca'].astype(bool)]
        for atributo in atributos:
            if atributo not in dd or dd[atributo].isna().all():
                continue
            res, tab = efeito_dentro_predio(dd, col, atributo, predio='predio_id')
            res.update({'desfecho': nome, 'atributo': atributo, 'universo': 'todas' if nome in com_troca else 'sem troca no CEFT'})
            linhas.append(res)
            if atributo == 'maquina' and len(tab):
                tab['desfecho'] = nome
                tabs.append(tab)
    return pd.DataFrame(linhas), (pd.concat(tabs, ignore_index=True) if tabs else pd.DataFrame())


def _ceft_com_desfechos(pleito, rotulo_ind, con):
    frames = []
    for uf in UFS11:
        c = carrega_ceft(pleito, uf, con=con)
        if c is None:
            continue
        ruim = c['municipality'].isna() | c['zone'].isna() | c['section'].isna()
        quarentena('C8-03', c[ruim], f'{pleito} {uf}: CEFT sem chave de secao')
        c = c[~ruim].copy()
        for x in ('municipality', 'zone', 'section'):
            c[x] = c[x].astype(int)
        c['dia_carga'] = c['dt_carga_esperada'].dt.strftime('%Y-%m-%d')
        c['turno_carga'] = np.where(c['dt_carga_esperada'].isna(), None, np.where(c['dt_carga_esperada'].dt.hour < 12, 'manha', 'tarde'))
        c['zona_id'] = zona_id(c)
        c['predio_id'] = predio_id(c)
        frames.append(c[['uf', 'municipality', 'zone', 'section', 'voting_place', 'urna_esperada', 'urna_efetivada', 'dt_carga', 'dt_carga_esperada',
                         'dia_carga', 'turno_carga', 'troca', 'divergencia', 'zona_id', 'predio_id'] + [x for x in ('maquina', 'maquina_transm') if x in c]])
    ceft = pd.concat(frames, ignore_index=True)
    ind = carrega_indicadores(rotulo_ind, KEY + ['share_a', 'manual_share', 'late_share', 'close_min', 'contingency'])
    d = ceft.merge(ind, on=KEY, how='left')
    d['contingencia'] = d['contingency'].astype(float)
    d['troca_ceft'] = d['troca'].astype(float)
    d['vinculo'] = np.where(d['share_a'].isna(), NOT_COMP + ': secao do CEFT sem indicadores', 'ok')
    return d.drop(columns=['contingency'])


def roda_c8_03(resumo, achados, cache):
    con = duck()
    arqs, nums, resumos, niveis = [], {}, [], []
    for pleito, rot in (('2026-t1', 'P2026'), ('2022-t2', 'P2022b')):
        d = _ceft_com_desfechos(pleito, rot, con)
        desf = {'share_a': 'share_a', 'manual_share': 'manual_share', 'late_share': 'late_share', 'close_min': 'close_min',
                'contingencia': 'contingencia', 'troca_ceft': 'troca_ceft'}
        por_uf = []
        for uf in UFS11:
            du = d[d.uf == uf]
            r, tab = c8_03_maquina(du, desf)
            r['uf'] = uf
            r['pleito'] = pleito
            tab['uf'] = uf
            tab['pleito'] = pleito
            por_uf.append(r)
            niveis.append(tab)
        rr = pd.concat(por_uf, ignore_index=True)
        resumos.append(rr)
        tem_maq = 'maquina' in d and d['maquina'].notna().any()
        nums[pleito] = {'secoes_ceft': int(len(d)), 'sem_indicadores': int(d['share_a'].isna().sum()),
                        'maquinas': int(d['maquina'].nunique()) if tem_maq else 0,
                        'maquinas_em_mais_de_uma_zona': int((d.groupby('maquina')['zone'].nunique() > 1).sum()) if tem_maq else 0,
                        'predios_com_mais_de_uma_maquina': int(rr[rr.atributo == 'maquina'].groupby('uf')['predios_mistos'].max().sum()) if tem_maq else 0,
                        'trocas_ceft': int(d['troca'].sum()),
                        'testes_p_perm_predio_lt_005': int(((rr.status == 'feita') & (rr.p_perm_ef_predio < 0.05)).sum()),
                        'testes': int((rr.status == 'feita').sum())}
        if tem_maq:
            zn = pd.to_numeric(d['maquina'].astype('string').str.extract(r'^Z[A-Z]{2}(\d{3})', expand=False), errors='coerce')
            nums[pleito]['maquina_nome_com_zona_da_secao_pct'] = round(100 * float((zn == d['zone']).mean()), 2)
            nums[pleito]['maquina_nome_sem_padrao_ZUFnnn'] = int(zn.isna().sum())
        nums[pleito]['sem_vinculo'] = int((d['vinculo'] != 'ok').sum())
        print(f'  C8-03 {pleito}: {len(d)} secoes', flush=True)
        del d
        gc.collect()
    rr = pd.concat(resumos, ignore_index=True)
    rr['bh_predio_5pct'] = bh(rr['p_perm_ef_predio'].to_numpy(float))
    arqs.append(csv_out('C8-03_ceft_maquina_carga_resumo.csv', rr))
    nv = pd.concat([t for t in niveis if len(t)], ignore_index=True) if any(len(t) for t in niveis) else pd.DataFrame()
    if len(nv):
        nv = nv.sort_values('t_ef_predio', key=np.abs, ascending=False)
        arqs.append(csv_out('C8-03_maquinas_t_dentro_predio.csv', nv[nv['secoes'] >= 20].head(500)))
        nums['maquinas_abs_t_ge_4'] = int(((nv['t_ef_predio'].abs() >= 4) & (nv['secoes'] >= 20)).sum())
    nums['bh_predio_5pct_rejeicoes'] = int(rr['bh_predio_5pct'].sum())
    _rec(resumo, 'C8-03', 'feita', nums, arqs)
    roda_c8_03c(resumo, achados, cache)
    del con


def c8_03_turno_controle(d, n_perm=N_PERM, seed=SEED):
    """Turno da carga (manha/tarde, urna esperada) x desfecho `y` dentro do predio, com e sem controle da ordem da secao no
    predio (rank percentual) e do tamanho (log aptos). Coeficiente parcial de 'manha' por MQO sobre variaveis demeaned por
    predio; p por permutacao de 'manha' dentro da zona (o controle e refeito em cada permutacao)."""
    x = d.dropna(subset=['y', 'manha', 'predio_id', 'zona_id']).reset_index(drop=True)
    p_code = pd.factorize(x['predio_id'])[0]
    z_code = pd.factorize(x['zona_id'])[0]
    rank = x.groupby('predio_id')['section'].rank(pct=True).to_numpy(float)
    tam = np.log1p(x['eligible'].to_numpy(float)) if 'eligible' in x else np.zeros(len(x))
    y = demean_por(x['y'].to_numpy(float), p_code)
    ctrl = np.c_[demean_por(rank, p_code), demean_por(np.nan_to_num(tam), p_code)]

    def coefs(m):
        mm = demean_por(m, p_code)
        so = float(mm @ y / (mm @ mm)) if (mm @ mm) > 0 else np.nan
        b = np.linalg.lstsq(np.c_[mm, ctrl], y, rcond=None)[0]
        return so, float(b[0]), float(b[1])

    m0 = x['manha'].to_numpy(float)
    so, parc, b_rank = coefs(m0)
    rng = np.random.default_rng(seed)
    perm = np.array([coefs(permuta_dentro(m0, z_code, rng))[:2] for _ in range(n_perm)])
    return {'n': int(len(x)), 'coef_manha_pp': so, 'coef_manha_controle_ordem_tamanho_pp': parc, 'coef_rank_ordem_pp': b_rank,
            'corr_manha_rank': float(np.corrcoef(demean_por(m0, p_code), ctrl[:, 0])[0, 1]),
            'p_perm_so': float((np.sum(np.abs(perm[:, 0]) >= abs(so)) + 1) / (n_perm + 1)),
            'p_perm_controle': float((np.sum(np.abs(perm[:, 1]) >= abs(parc)) + 1) / (n_perm + 1)), 'n_perm': n_perm}


def roda_c8_03c(resumo, achados, cache):
    """Consolida os achados de C8-03 por familia e refaz turno x fatia A / manual com controle da ordem da secao no predio."""
    rr = pd.read_csv(OUT / 'C8-03_ceft_maquina_carga_resumo.csv', sep=';', decimal=',', encoding='utf-8-sig')
    achados[:] = [a for a in achados if not a['id_sugerido'].startswith('C8-03-')]
    _ACHADOS_N['C8-03'] = 0
    con = duck()
    linhas = []
    alvo = rr[(rr.atributo == 'turno_carga') & (rr.status == 'feita') & rr.desfecho.isin(['share_a', 'manual_share'])]
    ufs_bh = alvo[alvo['bh_predio_5pct']][['pleito', 'uf']].drop_duplicates()
    # controle nas UF-pleitos que rejeitaram em algum dos dois desfechos e, como contraste, na mesma UF no outro pleito
    pares = pd.concat([ufs_bh, ufs_bh.assign(pleito=ufs_bh['pleito'].map({'2026-t1': '2022-t2', '2022-t2': '2026-t1'}))]).drop_duplicates()
    for pleito, uf in pares.itertuples(index=False):
        c = carrega_ceft(pleito, uf, con=con)
        if c is None:
            continue
        c = c.dropna(subset=['municipality', 'zone', 'section'])
        for k in ('municipality', 'zone', 'section'):
            c[k] = c[k].astype(int)
        c = c[~c['troca'].astype(bool)].copy()
        c['predio_id'] = predio_id(c)
        c['zona_id'] = zona_id(c)
        c['manha'] = np.where(c['dt_carga_esperada'].isna(), np.nan, (c['dt_carga_esperada'].dt.hour < 12).astype(float))
        ind = carrega_indicadores({'2026-t1': 'P2026', '2022-t2': 'P2022b'}[pleito], KEY + ['eligible', 'share_a', 'manual_share'])
        d = c.merge(ind, on=KEY, how='inner')
        for desf in ('share_a', 'manual_share'):
            r = c8_03_turno_controle(d.assign(y=d[desf] * (100 if desf == 'manual_share' else 1)))
            orig = alvo[(alvo.pleito == pleito) & (alvo.uf == uf) & (alvo.desfecho == desf)]
            r.update({'pleito': pleito, 'uf': uf, 'desfecho': desf,
                      'p_perm_estat_original': float(orig['p_perm_ef_predio'].iloc[0]) if len(orig) else np.nan,
                      'bh_original': bool(orig['bh_predio_5pct'].iloc[0]) if len(orig) else False})
            linhas.append(r)
        del c, ind, d
        gc.collect()
    tc = pd.DataFrame(linhas).sort_values(['desfecho', 'uf', 'pleito'])
    tc['bh_controle'] = bh(tc['p_perm_controle'].to_numpy(float))
    p_tc = csv_out('C8-03_turno_carga_controle_ordem_secao.csv', tc)
    rec = resumo.get('C8-03', {'status': 'feita', 'motivo': '', 'numeros_chave': {}, 'arquivos': []})
    rec['numeros_chave']['turno_controle_ordem'] = {f'{r.pleito} {r.uf} {r.desfecho}': {
        'coef_pp': round(r.coef_manha_pp, 3), 'coef_controle_pp': round(r.coef_manha_controle_ordem_tamanho_pp, 3),
        'p_controle': round(r.p_perm_controle, 4), 'bh_original': bool(r.bh_original), 'bh_controle': bool(r.bh_controle)} for r in tc.itertuples()}
    if p_tc not in rec['arquivos']:
        rec['arquivos'].append(p_tc)
    resumo['C8-03'] = rec
    fonte = [str(OUT / 'C8-03_ceft_maquina_carga_resumo.csv'), str(OUT / 'C8-03_maquinas_t_dentro_predio.csv')]
    ok = rr[rr.status == 'feita']
    # (1) maquina x contingencia/troca: vinculo mecanico
    g1 = ok[(ok.atributo == 'maquina') & ok.desfecho.isin(['contingencia', 'troca_ceft'])]
    r1 = g1[g1.bh_predio_5pct]
    achados.append(_achado(
        'C8-03', f'Maquina de geracao de midia x troca/contingencia dentro do predio (2026 T1): {len(r1)} de {len(g1)} testes acima do limiar, '
                 'explicados pelo vinculo mecanico do campo',
        '2026-t1', 'PRESIDENTE', ', '.join(sorted(r1.uf.unique())) or '11 UFs',
        '; '.join(f'{x.uf} {x.desfecho}: {x.niveis} maquinas, {x.predios_mistos} predios mistos' for x in r1.itertuples()),
        'cluster tecnico (carga) - artefato de vinculo',
        'as maquinas com |t| >= 4 tem 0% de troca (media bruta 0): a maquina do CEFT e a da urna EFETIVADA, entao a secao com troca recebe a estacao que '
        'carregou a urna de reserva; 99,88% dos nomes ZUFnnn trazem a zona da propria secao; '
        + '; '.join(f'{x.uf} {x.desfecho} estat {x.estat_ef_predio:.0f} vs p95 {x.perm_p95_ef_predio:.0f}' for x in r1.itertuples()),
        float(r1['estat_ef_predio'].max()) if len(r1) else 0.0, 0, 0, 'sem materialidade (processo)',
        'dia/turno usam a carga da urna ESPERADA; maquina so existe para a efetivada (2024+); maquinas x resultado/manual/tardio: 0 rejeicoes',
        '2022 sem campo de maquina no CEFT; 2024 T1 em C8-10', ['vinculo mecanico: a urna de contingencia e carregada por outra estacao'], 'ARTEFATO',
        'maquina de geracao da midia da urna esperada (o CEFT nao publica)', fonte, 3))
    # (2) dia/turno x contingencia/troca
    g2 = ok[ok.atributo.isin(['dia_carga', 'turno_carga']) & ok.desfecho.isin(['contingencia', 'troca_ceft'])]
    r2 = g2[g2.bh_predio_5pct]
    achados.append(_achado(
        'C8-03', f'Data/turno da carga da urna esperada x contingencia no log e troca no CEFT: {len(r2)} de {len(g2)} testes acima do limiar '
                 f'({int((r2.pleito == "2022-t2").sum())} em 2022 T2, {int((r2.pleito == "2026-t1").sum())} em 2026 T1)',
        '2022-t2 / 2026-t1', 'PRESIDENTE', ', '.join(sorted(r2.uf.unique())), f'{len(r2)} testes UF x atributo x desfecho',
        'cluster de processo (carga)',
        'SP 2022 T2: contingencia (log identificado so pelo nome do arquivo = urna substituta ou recarregada) por dia de carga da urna esperada '
        '0,9% (21/09), 2,3% (24/09), 9,8% (27/09), 17,1% (28/09), 60,6% (29/09, 236 secoes), com troca no CEFT de 0,8% a 2,1% no mesmo periodo; maiores: '
        + '; '.join(f'{x.pleito} {x.uf} {x.atributo}/{x.desfecho} {x.estat_ef_predio:.0f} vs p95 {x.perm_p95_ef_predio:.0f}'
                    for x in r2.sort_values('estat_ef_predio', ascending=False).head(6).itertuples()),
        float(r2['estat_ef_predio'].max()) if len(r2) else 0.0, 0, 0, 'processo; sem materialidade em votos',
        'carga da urna esperada (anterior a troca); permutacao na zona; efeito fixo de predio; contingencia = identity_status PARSED_FILENAME',
        '2026 T1 com o mesmo desenho: 0 rejeicoes de dia/turno x contingencia/troca (urnas novas, menos recarga)',
        ['urnas carregadas por ultimo (fim de setembro de 2022) sao recargas cujo log o leitor identifica pelo nome do arquivo',
         'cartorios que carregam tarde tambem trocam mais urnas'], 'PLAUSIVEL-EXPLICAVEL', 'registro de recarga por urna (atas de carga) dos TREs', fonte, 2))
    # (3) turno x fatia A
    t3 = tc[tc.desfecho == 'share_a']
    r3 = t3[t3.bh_controle]
    # 2026 so conta como sem controle se a mesma UF em 2022 nao tiver o mesmo sinal acima do limiar
    c22 = {r.uf: r for r in t3[t3.pleito == '2022-t2'].itertuples()}
    so26 = [r.uf for r in r3[r3.pleito == '2026-t1'].itertuples()
            if not (r.uf in c22 and c22[r.uf].bh_controle and np.sign(c22[r.uf].coef_manha_controle_ordem_tamanho_pp) == np.sign(r.coef_manha_controle_ordem_tamanho_pp))]
    status3 = 'INEXPLICADO' if so26 else 'PLAUSIVEL-EXPLICAVEL'
    rec['numeros_chave']['turno_share_a_2026_sem_par_2022'] = so26
    achados.append(_achado(
        'C8-03', f'Turno da carga x fatia de A dentro do predio: {int(t3.bh_original.sum())} de {len(t3)} UF-pleitos acima do limiar no teste bruto e '
                 f'{len(r3)} de {len(t3)} depois de controlar a ordem da secao e o tamanho',
        '2026-t1 / 2022-t2', 'PRESIDENTE', ', '.join(sorted(t3.uf.unique())),
        '; '.join(f'{r.pleito} {r.uf}: {r.n} secoes' for r in t3.itertuples()), 'cluster tecnico (carga) x resultado',
        '; '.join(f'{r.pleito} {r.uf}: manha - tarde {r.coef_manha_pp:+.2f} pp -> {r.coef_manha_controle_ordem_tamanho_pp:+.2f} pp com controle '
                  f'(p {r.p_perm_controle:.3f}; corr turno x ordem {r.corr_manha_rank:+.2f})' for r in t3.itertuples()),
        float(t3['coef_manha_controle_ordem_tamanho_pp'].abs().max()) if len(t3) else 0.0, 0,
        int((t3['coef_manha_controle_ordem_tamanho_pp'].abs() / 100 * t3['n'] * 150).max()) if len(t3) else 0,
        'margem da UF no 1o turno 2026 / 2o turno 2022; teto = |coef| x secoes x 150 votos (metade das secoes da UF num turno)',
        'urna esperada sem troca; efeito fixo de predio; permutacao do turno dentro da zona; controle da ordem da secao no predio e do numero de aptos',
        f'2026 T1 e 2022 T2 lado a lado na mesma UF (CSV de controle); acima do limiar em 2026 sem par de mesmo sinal em 2022: {", ".join(so26) or "nenhuma"}',
        ['a carga segue a ordem das secoes e a ordem acompanha a idade do eleitorado (secoes novas = eleitores novos)',
         'composicao residual nao capturada pela ordem', 'acaso (11 UFs x 3 atributos x 6 desfechos x 2 pleitos)'],
        status3, 'perfil do eleitorado 2026 por secao (idade/escolaridade)', fonte + [p_tc], 2))
    # (4) dia/turno x manual/tardio/encerramento
    g4 = ok[ok.atributo.isin(['dia_carga', 'turno_carga']) & ok.desfecho.isin(['manual_share', 'late_share', 'close_min'])]
    r4 = g4[g4.bh_predio_5pct]
    if len(r4):
        tm = tc[tc.desfecho == 'manual_share']
        achados.append(_achado(
            'C8-03', f'Data/turno da carga x habilitacao manual, voto tardio e encerramento dentro do predio: {len(r4)} de {len(g4)} testes acima do limiar',
            '2026-t1 / 2022-t2', 'PRESIDENTE', ', '.join(sorted(r4.uf.unique())), '; '.join(f'{x.pleito} {x.uf} {x.atributo}/{x.desfecho}' for x in r4.itertuples()),
            'cluster de processo (carga)',
            '; '.join(f'{x.pleito} {x.uf} {x.atributo}/{x.desfecho}: {x.estat_ef_predio:.1f} vs p95 {x.perm_p95_ef_predio:.1f}' for x in r4.itertuples())
            + ' | manual (pp) com controle de ordem: ' + '; '.join(f'{r.pleito} {r.uf} {r.coef_manha_pp:+.2f} -> {r.coef_manha_controle_ordem_tamanho_pp:+.2f} '
                                                                  f'(p {r.p_perm_controle:.3f})' for r in tm.itertuples()),
            float(r4['estat_ef_predio'].max()), 0, 0, 'processo; sem materialidade em votos', 'urna esperada sem troca; efeito fixo de predio; permutacao na zona',
            '2026 T1 e 2022 T2 com o mesmo desenho', ['ordem da secao (secoes antigas: eleitorado mais idoso, mais falha de digital)',
                                                     'urnas carregadas a tarde = outra leva/modelo'],
            'PLAUSIVEL-EXPLICAVEL', 'modelo por urna (C8-07) e perfil 2026 por secao', fonte, 3))
    del con


def c8_10_excesso_por_zona(df, variaveis, peso_col=None):
    """t por zona de cada variavel (secao como unidade; padronizada na UF). Devolve tabela zona x variavel."""
    d = df.copy()
    d['zona'] = d['zone']
    out = None
    for v in variaveis:
        dd = d.dropna(subset=[v]).copy()
        dd['peso'] = dd[peso_col] if peso_col else 1.0
        dd['bloco'] = np.arange(len(dd))
        g, _ = scan_hierarquico(dd, v, 'peso', ['zona'], 'bloco', n_perm=0)
        g = g[['uf', 'grupo', 'unidades', 't']].rename(columns={'grupo': 'zone', 't': f't_{v}', 'unidades': f'n_{v}'})
        out = g if out is None else out.merge(g, on=['uf', 'zone'], how='outer')
    return out


def roda_c8_10(resumo, achados, cache):
    con = duck()
    arqs, nums = [], {}
    zonas = {}
    for rot in ('P2022b', 'M2024', 'M2024b', 'P2026'):
        ind = carrega_indicadores(rot)
        ind['contingencia'] = ind['contingency'].astype(float)
        z = c8_10_excesso_por_zona(ind, ['contingencia', 'manual_share', 'late_share', 'close_min'])
        z['pleito'] = rot
        zonas[rot] = z
        del ind
        gc.collect()
    z26 = cache.get('zonas_2026t2')
    p04 = OUT / 'C8-04_scan_processo_zonas_2026.csv'
    if z26 is None and p04.exists():
        # 2T 2026 nacional (C8-04, secoes >= 50 aptos, sem ZZ): t por zona; tardio_19h faz o papel de close_min
        x = pd.read_csv(p04, sep=';', decimal=',', encoding='utf-8-sig', usecols=['variavel', 'uf', 'grupo', 'unidades', 't_2026'])
        x['variavel'] = x['variavel'].replace({'tardio_19h': 'close_min'})
        x = x[x['variavel'].isin(['contingencia', 'manual_share', 'close_min'])]
        z26 = None
        for v, g in x.groupby('variavel'):
            g = g.rename(columns={'grupo': 'zone', 't_2026': f't_{v}', 'unidades': f'n_{v}'})[['uf', 'zone', f'n_{v}', f't_{v}']]
            z26 = g if z26 is None else z26.merge(g, on=['uf', 'zone'], how='outer')
        if z26 is not None:
            z26['zone'] = z26['zone'].astype(int)
            z26['pleito'] = 'P2026b_nacional'
    if z26 is not None:
        zonas['P2026b_nacional'] = z26[z26['uf'].isin(UFS11)].copy()
    # 2024 T1: maquina de carga x processo (mesma estatistica de C8-03)
    d24 = _ceft_com_desfechos('2024-t1', 'M2024', con)
    por_uf = []
    for uf in UFS11:
        du = d24[d24.uf == uf]
        r, _ = c8_03_maquina(du, {'manual_share': 'manual_share', 'late_share': 'late_share', 'contingencia': 'contingencia', 'troca_ceft': 'troca_ceft'})
        r['uf'] = uf
        r['pleito'] = '2024-t1'
        por_uf.append(r)
    r24 = pd.concat(por_uf, ignore_index=True)
    r24['bh_predio_5pct'] = bh(r24['p_perm_ef_predio'].to_numpy(float))
    r24['bh_zona_5pct'] = bh(r24['p_perm_ef_zona'].to_numpy(float))
    arqs.append(csv_out('C8-10_ceft_maquina_2024t1_resumo.csv', r24))
    nums['2024-t1_maquina'] = {'secoes': int(len(d24)), 'testes_p_perm_predio_lt_005': int(((r24.status == 'feita') & (r24.p_perm_ef_predio < 0.05)).sum()),
                               'testes': int((r24.status == 'feita').sum()), 'bh_predio_5pct': int(r24['bh_predio_5pct'].sum()),
                               'bh_zona_5pct': int(r24['bh_zona_5pct'].sum()),
                               'rejeicoes_predio': [f'{x.uf} {x.atributo}/{x.desfecho} p {x.p_perm_ef_predio:.4f}' for x in r24[r24['bh_predio_5pct']].itertuples()]}
    del d24
    gc.collect()
    # correlacao por zona entre eleicoes
    tudo = pd.concat(zonas.values(), ignore_index=True)
    arqs.append(csv_out('C8-10_zonas_t_por_eleicao.csv', tudo))
    cors = []
    for v in ('contingencia', 'manual_share', 'late_share', 'close_min'):
        col = f't_{v}'
        wide = None
        for rot, z in zonas.items():
            if col not in z:
                continue
            zz = z[['uf', 'zone', col]].rename(columns={col: rot})
            zz['zone'] = zz['zone'].astype(int)
            wide = zz if wide is None else wide.merge(zz, on=['uf', 'zone'], how='outer')
        if wide is None:
            continue
        pleitos = [c for c in wide.columns if c not in ('uf', 'zone')]
        for i, a in enumerate(pleitos):
            for b in pleitos[i + 1:]:
                m = wide[[a, b]].dropna()
                rho = float(stats.spearmanr(m[a], m[b]).statistic) if len(m) > 10 else np.nan
                top = (m[a] >= m[a].quantile(0.95)) & (m[b] >= m[b].quantile(0.95))
                cors.append({'variavel': v, 'pleito_a': a, 'pleito_b': b, 'zonas': int(len(m)), 'spearman': rho,
                             'zonas_top5pct_em_ambos': int(top.sum()), 'esperado_acaso': round(0.05 * 0.05 * len(m), 1)})
    cc = pd.DataFrame(cors)
    arqs.append(csv_out('C8-10_correlacao_zonas_entre_eleicoes.csv', cc))
    nums['spearman_zonas'] = {f"{r.variavel} {r.pleito_a}x{r.pleito_b}": round(r.spearman, 3) for r in cc.itertuples() if np.isfinite(r.spearman)}
    cc['razao_top5_vs_acaso'] = cc['zonas_top5pct_em_ambos'] / cc['esperado_acaso'].where(cc['esperado_acaso'] > 0)
    cc.to_csv(arqs[-1], **CSV)
    _rec(resumo, 'C8-10', 'feita', nums, arqs)
    mesmo_ano = {('M2024', 'M2024b'), ('P2026', 'P2026b_nacional')}
    cc['mesmo_ano'] = [(a, b) in mesmo_ano for a, b in zip(cc.pleito_a, cc.pleito_b)]
    for v, titulo in (('manual_share', 'Habilitacao manual: as mesmas zonas concentram o excesso em todas as eleicoes (2022 T2, 2024, 2026 T1 e 2T)'),
                      ('contingencia', 'Contingencia: o agrupamento por zona se repete entre 1o e 2o turno do mesmo ano, mas quase nao entre anos'),
                      ('close_min', 'Encerramento tardio por zona: persistencia moderada entre eleicoes')):
        x = cc[cc.variavel == v]
        if len(x) == 0:
            continue
        entre = x[~x['mesmo_ano']]
        dentro = x[x['mesmo_ano']]
        achados.append(_achado(
            'C8-10', titulo, '2022-t2 / 2024-t1 / 2024-t2 / 2026-t1 / 2026-t2', 'PRESIDENTE/PREFEITO', '11 UFs', f'{int(x.zonas.max())} zonas',
            'cluster de processo (persistencia)',
            f'Spearman por zona entre anos: mediana {entre.spearman.median():+.2f} (de {entre.spearman.min():+.2f} a {entre.spearman.max():+.2f}); '
            f'dentro do mesmo ano: ' + '; '.join(f'{r.pleito_a} x {r.pleito_b} {r.spearman:+.2f}' for r in dentro.itertuples())
            + '; top 5% em ambos (obs/esperado): ' + '; '.join(f'{r.pleito_a} x {r.pleito_b} {r.zonas_top5pct_em_ambos}/{r.esperado_acaso}' for r in x.itertuples()),
            float(entre.spearman.median()), 0, 0, 'processo; sem materialidade em votos',
            't por zona padronizado na UF (secao como unidade; 2T 2026 nacional vem de C8-04 com secoes >= 50 aptos); mesmas zonas (uf, zona) entre pleitos',
            'controle estrutural de C8-04: excesso que tambem aparece em 2022 e 2024 e logistico/estrutural; 2024 T1 maquina de carga x processo: '
            f'{nums["2024-t1_maquina"]["bh_predio_5pct"]} rejeicoes BH dentro do predio em {nums["2024-t1_maquina"]["testes"]} testes',
            (['perfil do eleitorado (idade, biometria) e pratica do cartorio estaveis por zona'] if v == 'manual_share' else
             ['urnas e cartorios do mesmo ano (mesma carga para os dois turnos) repetem a troca; entre anos o parque de urnas muda (UE2022)',
              'evento local do ano (falha de lote, energia)']),
            'EXPLICADO' if (v == 'manual_share' and entre.spearman.median() > 0.3) else 'PLAUSIVEL-EXPLICAVEL',
            'registro de ocorrencias e de urnas de contingencia por zona (TREs)', arqs, 3))
    del con


# ----------------------------------------------------------------------------------------------- C8-04
def _processo_2026(geo):
    bins = carrega_bins(2026)
    base = carrega_base(2026, KEY + ['voting_place', 't2_aptos', 't2_comp', 't2_manual', 't2_enc_min'])
    sec = carrega_secoes(2026, KEY + ['n2', 'res_pp', 'votos_log', 'votos_apos_17h'])
    d = base.merge(bins, on=KEY, how='left').merge(sec, on=KEY, how='left')
    d['contingencia'] = d['contingencia'].astype(float)
    d['manual_share'] = d['t2_manual'] / d['t2_comp'].where(d['t2_comp'] > 0)
    d['tardio_19h'] = (d['t2_enc_min'] >= 19 * 60).astype(float).where(d['t2_enc_min'].notna())
    d['apos_17h_share'] = d['votos_apos_17h'] / d['votos_log'].where(d['votos_log'] > 0)
    d['aptos'] = d['t2_aptos']
    d['comp'] = d['t2_comp']
    del bins, base, sec
    return junta_geografia(d, geo)


def _processo_2022(geo):
    bins = carrega_bins(2022)
    base = carrega_base(2022, KEY + ['voting_place', 't2_aptos', 't2_comp', 't2_manual', 't2_enc_min'])
    sec = carrega_secoes(2022, KEY + ['n2', 'res_pp'])
    d = base.merge(bins, on=KEY, how='left').merge(sec, on=KEY, how='left')
    d['contingencia'] = d['contingencia'].astype(float)
    d['manual_share'] = d['t2_manual'] / d['t2_comp'].where(d['t2_comp'] > 0)
    d['tardio_19h'] = (d['t2_enc_min'] >= 19 * 60).astype(float).where(d['t2_enc_min'].notna())
    d['aptos'] = d['t2_aptos']
    d['comp'] = d['t2_comp']
    del bins, base, sec
    return junta_geografia(d, geo)


def c8_04_scan_processo(d, variavel, peso, n_perm=N_PERM, seed=SEED):
    dd = d.dropna(subset=[variavel]).copy()
    dd = dd[(dd['aptos'] >= MIN_APTOS) & (dd['uf'] != 'ZZ')]
    dd['peso'] = dd[peso] if peso else 1.0
    dd = dd[dd['peso'] > 0]
    dd['zona'] = dd['zone']
    dd['municipio'] = dd['municipality']
    dd['bloco'] = np.arange(len(dd))
    return scan_hierarquico(dd, variavel, 'peso', ['zona', 'municipio', 'micro', 'meso'], 'bloco', n_perm=n_perm, seed=seed)


def c8_04_residuo_trocadas(d, zonas_acima):
    """Nas zonas com excesso de contingencia: media do residuo M1 das secoes com contingencia vs sem, na mesma zona."""
    return c8_04_residuo_flag(d, zonas_acima, 'contingencia')


def c8_04_residuo_flag(d, zonas_acima, flag):
    """Nas zonas com excesso de `flag` (0/1): media do residuo M1 das secoes com flag vs sem, na mesma zona."""
    rows = []
    for r in zonas_acima.itertuples():
        z = d[(d.uf == r.uf) & (d.zone == int(r.grupo)) & d['res_pp'].notna()]
        a, b = z[z[flag] == 1], z[z[flag] == 0]
        if len(a) == 0 or len(b) == 0:
            rows.append({'uf': r.uf, 'zone': int(r.grupo), 'status': NOT_COMP, 'motivo': f'sem secoes com e sem {flag} na zona'})
            continue
        dif = a['res_pp'].mean() - b['res_pp'].mean()
        se = np.sqrt(a['res_pp'].var(ddof=1) / len(a) + b['res_pp'].var(ddof=1) / len(b)) if len(a) > 1 else np.nan
        rows.append({'uf': r.uf, 'zone': int(r.grupo), 'status': 'feita', 'secoes_contingencia': len(a), 'secoes_sem': len(b),
                     'res_pp_contingencia': a['res_pp'].mean(), 'res_pp_sem': b['res_pp'].mean(), 'diferenca_pp': dif, 'ep_pp': se,
                     't': dif / se if se and se > 0 else np.nan, 'ano': int(d['ano'].iloc[0]) if 'ano' in d else None})
    return pd.DataFrame(rows)


def roda_c8_04(resumo, achados, cache):
    geo = cache.get('geo')
    if geo is None:
        geo = carrega_geografia()
        cache['geo'] = geo
    nums = {}
    variaveis = {'contingencia': None, 'manual_share': 'comp', 'tardio_19h': None, 'apos_17h_share': 'votos_log'}
    grupos, limites, trocadas = [], [], []
    for ano, montar in ((2026, _processo_2026), (2022, _processo_2022)):
        d = montar(geo)
        d['ano'] = ano
        nums[ano] = {'secoes': int(len(d)), 'contingencia': int(d['contingencia'].sum()), 'sem_bins': int(d['contingencia'].isna().sum()),
                     'tardio_19h': int(d['tardio_19h'].sum()), 'manual_share_media': round(float(d['manual_share'].mean()), 4),
                     'sem_geografia_nao_ZZ': int((d['micro'].isna() & (d.uf != 'ZZ')).sum()), 'ZZ': int((d.uf == 'ZZ').sum())}
        for v, peso in variaveis.items():
            if v not in d or d[v].notna().sum() == 0:
                continue
            g, lim = c8_04_scan_processo(d, v, peso)
            g['ano'] = ano
            g['variavel'] = v
            lim['ano'] = ano
            lim['variavel'] = v
            grupos.append(g)
            limites.append(lim)
            nums[ano][v] = {r['nivel']: {'limite_p95': round(r['limite_p95_max_abs_t'], 2), 'max_abs_t': round(r['max_abs_t_real'], 2), 'acima': int(r['acima_limite'])}
                            for _, r in lim.iterrows()}
            if v in ('contingencia', 'tardio_19h'):
                za = g[(g.nivel == 'zona') & g['acima_limite']]
                tr = c8_04_residuo_flag(d, za, v)
                tr['ano'] = ano
                tr['variavel'] = v
                trocadas.append(tr)
            print(f'  C8-04 {ano} {v}', flush=True)
        if ano == 2026:
            z = pd.concat([x for x in grupos if x['ano'].iloc[0] == 2026], ignore_index=True)
            z = z[z.nivel == 'zona']
            wide = None
            for v in variaveis:
                zz = z[z.variavel == v][['uf', 'grupo', 'unidades', 't']].rename(columns={'grupo': 'zone', 't': f't_{v}', 'unidades': f'n_{v}'})
                wide = zz if wide is None else wide.merge(zz, on=['uf', 'zone'], how='outer')
            if wide is not None:
                wide['zone'] = wide['zone'].astype(int)
                wide['pleito'] = 'P2026b_nacional'
                cache['zonas_2026t2'] = wide
        del d
        gc.collect()
    G = pd.concat(grupos, ignore_index=True)
    L = pd.concat(limites, ignore_index=True)
    tr = pd.concat(trocadas, ignore_index=True) if trocadas else pd.DataFrame()
    # copia intermediaria (para nao perder a permutacao se o pos-processamento falhar; reaproveitada por C8-04p)
    INTER.mkdir(parents=True, exist_ok=True)
    for c in ('variavel', 'nivel', 'grupo', 'uf'):
        G[c] = G[c].astype(str)
    G.to_parquet(INTER / 'c8_04_grupos.parquet', index=False)
    L.to_parquet(INTER / 'c8_04_limites.parquet', index=False)
    tr.to_parquet(INTER / 'c8_04_trocadas.parquet', index=False)
    (INTER / 'c8_04_nums.json').write_text(json.dumps(nums, ensure_ascii=False, default=str), encoding='utf-8')
    for nome, df in (('c8_04_grupos.parquet', G), ('c8_04_limites.parquet', L), ('c8_04_trocadas.parquet', tr)):
        recibo(INTER / nome, ENTRADAS_C8_04, len(df))
    _c8_04_pos(G, L, tr, nums, geo, resumo, achados)


def roda_c8_04p(resumo, achados, cache):
    """Refaz so o pos-processamento de C8-04 a partir das copias intermediarias (sem refazer as permutacoes)."""
    G = pd.read_parquet(INTER / 'c8_04_grupos.parquet')
    L = pd.read_parquet(INTER / 'c8_04_limites.parquet')
    tr = pd.read_parquet(INTER / 'c8_04_trocadas.parquet') if (INTER / 'c8_04_trocadas.parquet').exists() else pd.DataFrame()
    nums = json.loads((INTER / 'c8_04_nums.json').read_text(encoding='utf-8')) if (INTER / 'c8_04_nums.json').exists() else {}
    geo = cache.get('geo')
    if geo is None:
        geo = carrega_geografia()
    _c8_04_pos(G, L, tr, nums, geo, resumo, achados)


def _c8_04_pos(G, L, tr, nums, geo, resumo, achados):
    achados[:] = [a for a in achados if not a['id_sugerido'].startswith('C8-04-')]
    _ACHADOS_N['C8-04'] = 0
    arqs = []
    for c in ('variavel', 'nivel', 'grupo', 'uf'):
        G[c] = G[c].astype(str)
    G['acima_limite'] = G['acima_limite'].astype(bool)
    nomes = {}
    for c in ('micro', 'meso'):
        nomes.update(geo.drop_duplicates(c).set_index(c)[f'{c}_nome'].to_dict())
    G['nome'] = pd.to_numeric(G['grupo'], errors='coerce').map(nomes).where(G['nivel'].isin(['micro', 'meso']))
    chave = ['variavel', 'nivel', 'uf', 'grupo']      # zona so e unica dentro da UF
    lado = G[G.ano == 2026].merge(G[G.ano == 2022][chave + ['t', 'media_ponderada', 'acima_limite', 'limite_p95']],
                                  on=chave, how='left', suffixes=('_2026', '_2022'))
    lado['tem_par_2022'] = lado['t_2022'].notna()
    lado['acima_limite_2022'] = lado['acima_limite_2022'].fillna(False).astype(bool)
    lado['acima_limite_2026'] = lado['acima_limite_2026'].astype(bool)
    acima = lado[lado['acima_limite_2026'] | lado['acima_limite_2022']].copy()
    acima['abs_t'] = acima['t_2026'].abs()
    acima = acima.sort_values(['variavel', 'nivel', 'abs_t'], ascending=[True, True, False]).drop(columns='abs_t')
    so22 = G[(G.ano == 2022)].merge(G[G.ano == 2026][chave], on=chave, how='left', indicator=True)
    so22 = so22[(so22['_merge'] == 'left_only') & so22['acima_limite'].astype(bool)].drop(columns='_merge')
    arqs.append(csv_out('C8-04_scan_processo_acima_limite.csv', pd.concat([acima, so22.rename(columns={'t': 't_2022', 'acima_limite': 'acima_limite_2022'})
                                                                          .assign(status_par=NOT_COMP + ': grupo so existe em 2022')], ignore_index=True)))
    arqs.append(csv_out('C8-04_scan_processo_limites.csv', L))
    zz = lado[lado.nivel == 'zona'].copy()
    zz['status_par'] = np.where(zz['tem_par_2022'], 'comparavel', NOT_COMP + ': zona sem par em 2022 (variavel ou zona ausente)')
    zz['abs_t'] = zz['t_2026'].abs()
    arqs.append(csv_out('C8-04_scan_processo_zonas_2026.csv', zz.sort_values('abs_t', ascending=False).drop(columns='abs_t')))
    if len(tr):
        arqs.append(csv_out('C8-04_residuo_trocadas_zonas_excesso.csv', tr))
        ok = tr[tr.status == 'feita']
        if 'variavel' not in tr:
            tr['variavel'] = 'contingencia'
        nums['residuo_flag_zonas_excesso'] = {
            f'{v}/{int(a)}': {'zonas': int(((tr.ano == a) & (tr.variavel == v)).sum()), 'zonas_comparaveis': int(len(o)),
                              'diferenca_media_pp': round(float(o['diferenca_pp'].mean()), 3) if len(o) else None,
                              'zonas_abs_t_ge_4': int((o['t'].abs() >= 4).sum()) if len(o) else 0}
            for (v, a), o in [((v, a), ok[(ok.ano == a) & (ok.variavel == v)]) for v, a in tr[['variavel', 'ano']].drop_duplicates().itertuples(index=False)]}
    por = lado.groupby(['variavel', 'nivel']).agg(acima_2026=('acima_limite_2026', 'sum'), acima_2022_mesmo_grupo=('acima_limite_2022', 'sum'),
                                                  ambos=('acima_limite_2022', lambda s: int((s & lado.loc[s.index, 'acima_limite_2026']).sum())))
    nums['acima_por_variavel_nivel'] = {f'{v}/{n}': {k: int(x) for k, x in r.items()} for (v, n), r in por.iterrows()}
    nums['grupos_acima_2026'] = int(lado['acima_limite_2026'].sum())
    nums['grupos_acima_2026_e_2022'] = int((lado['acima_limite_2026'] & lado['acima_limite_2022']).sum())
    nums['grupos_acima_so_2026'] = int((lado['acima_limite_2026'] & ~lado['acima_limite_2022']).sum())
    nums['grupos_acima_so_2022'] = int((~lado['acima_limite_2026'] & lado['acima_limite_2022']).sum() + len(so22))
    _rec(resumo, 'C8-04', 'feita', nums, arqs)
    for v in sorted(lado['variavel'].unique()):
        sub = acima[(acima.variavel == v) & acima['acima_limite_2026']]
        n22 = int(((lado.variavel == v) & lado['acima_limite_2022']).sum())
        if len(sub) == 0:
            continue
        so26 = sub[~sub['acima_limite_2022']]
        medido_22 = bool(((G.ano == 2022) & (G.variavel == v)).any())
        top = sub.sort_values('t_2026', key=np.abs, ascending=False).head(6)
        lim = L[(L.variavel == v) & (L.ano == 2026)].set_index('nivel')['limite_p95_max_abs_t'].round(2).to_dict()
        tr_txt = ''
        if len(tr) and 'ano' in tr and 'variavel' in tr:
            okk = tr[(tr.status == 'feita') & (tr.ano == 2026) & (tr.variavel == v)]
            if len(okk):
                tr_txt = (f'; residuo M1 secoes com {v} - sem, nas {len(okk)} zonas com excesso em 2026: media {okk["diferenca_pp"].mean():+.3f} pp, '
                          f'{int((okk["t"].abs() >= 4).sum())} zonas com |t| >= 4')
        achados.append(_achado(
            'C8-04', f'Agrupamento territorial de {v} no 2T 2026 acima do limite de permutacao: {len(sub)} grupos ({len(so26)} sem o mesmo grupo acima em 2022; '
                     f'{n22} grupos acima em 2022)',
            '2026-t2 / 2022-t2', 'PRESIDENTE', ', '.join(sorted(sub.uf.unique()))[:200], f'{len(sub)} grupos (zona/municipio/micro/meso); maiores: ' + '; '.join(
                f'{r.nivel} {r.uf} {r.grupo} {r.nome if isinstance(r.nome, str) else ""} t {r.t_2026:+.1f} (2022 t {r.t_2022:+.1f})' for r in top.itertuples()),
            'cluster de processo', f'limites p95 2026 por nivel {lim}; |t| maximo {sub["t_2026"].abs().max():.1f}' + tr_txt,
            float(sub['t_2026'].abs().max()), 0, 0, 'variavel de processo; sem materialidade direta em votos',
            'bins/BU ja validados; secoes <50 aptos e ZZ fora; permutacao de secoes dentro da UF; chave de zona = uf+zona',
            (f'2022 T2 mesma especificacao: {int(sub["acima_limite_2022"].sum())} dos {len(sub)} grupos tambem acima em 2022; C8-10 mede a persistencia entre eleicoes'
             if medido_22 else f'{NOT_COMP}: 2022 sem votos por hora na base de secoes (secoes_2022.parquet nao tem votos_apos_17h); grupos coincidem com os de tardio_19h'),
            ['logistica do cartorio (as mesmas zonas concentram contingencia/manual eleicao apos eleicao)', 'composicao do eleitorado (biometria, idade)',
             'urnas antigas concentradas por zona (C8-02)'] + (['orientacao por zona/cartorio para cancelar o encerramento e aguardar (2026: 6.342 secoes '
             'encerradas >= 19h contra 20 em 2022)', 'fila real no fim do dia em zonas grandes'] if v in ('tardio_19h', 'apos_17h_share') else []),
            ('NAO_TESTAVEL' if not medido_22 else 'INEXPLICADO' if (n22 <= 1 and v == 'tardio_19h') else 'PLAUSIVEL-EXPLICAVEL'),
            'registro do TRE de urnas de contingencia e ocorrencias por zona; atas das mesas (prorrogacao/fila); perfil 2026 por secao', arqs[:3],
            2 if v in ('tardio_19h', 'apos_17h_share', 'contingencia') else 3))


# ----------------------------------------------------------------------------------------------- C8-08
def c8_08_concentracao(locais, nivel_cols, flag='alta'):
    """Binomial por grupo (zona ou municipio): locais `alta` observados vs esperados pela taxa da UF; BH 5%."""
    L = locais.copy()
    L['alta'] = (L['prioridade_observacao'] == flag).astype(int)
    taxa_uf = L.groupby('uf')['alta'].mean().rename('taxa_uf')
    g = L.groupby(nivel_cols).agg(locais=('alta', 'size'), alta=('alta', 'sum')).reset_index().merge(taxa_uf, on='uf')
    g['esperado'] = g['locais'] * g['taxa_uf']
    g['p_binomial'] = stats.binom.sf(g['alta'] - 1, g['locais'], g['taxa_uf'])
    g['bh_5pct'] = bh(g['p_binomial'].to_numpy())
    g['excesso'] = g['alta'] - g['esperado']
    return g.sort_values('p_binomial')


def c8_08_predios_vs_municipio(pred, marcados, desfechos):
    """Predios marcados (alta) vs os demais do mesmo municipio: diferenca media de cada desfecho e t (secao como peso 1)."""
    p = pred.merge(marcados[['uf', 'municipality', 'zone', 'voting_place']].drop_duplicates().assign(alta=1),
                   on=['uf', 'municipality', 'zone', 'voting_place'], how='left')
    p['alta'] = p['alta'].fillna(0).astype(int)
    rows = []
    for d in desfechos:
        x = p.dropna(subset=[d]).copy()
        x['dm'] = demean_por(x[d].to_numpy(float), pd.factorize(x['uf'].astype(str) + '|' + x['municipality'].astype(str))[0])
        a, b = x[x.alta == 1], x[x.alta == 0]
        se = np.sqrt(a['dm'].var(ddof=1) / len(a) + b['dm'].var(ddof=1) / len(b)) if len(a) > 1 and len(b) > 1 else np.nan
        rows.append({'desfecho': d, 'predios_alta': len(a), 'predios_outros_mesmo_mun': len(b), 'media_alta': a[d].mean(), 'media_outros': b[d].mean(),
                     'diferenca_dentro_mun': a['dm'].mean() - b['dm'].mean(), 'ep': se, 't': (a['dm'].mean() - b['dm'].mean()) / se if se and se > 0 else np.nan})
    return pd.DataFrame(rows)


def roda_c8_08(resumo, achados, cache):
    arqs, nums = [], {}
    L = pd.read_csv(REL / 'fiscalizacao' / 'varredura' / 'locais_risco.csv', sep=';', decimal=',', encoding='utf-8-sig',
                    usecols=['uf', 'municipality', 'municipality_name', 'zone', 'voting_place', 'prioridade_observacao', 'secoes_max', 'secoes_com_comportamento'])
    z = c8_08_concentracao(L, ['uf', 'municipality', 'municipality_name', 'zone'])
    m = c8_08_concentracao(L, ['uf', 'municipality', 'municipality_name'])
    arqs.append(csv_out('C8-08_concentracao_locais_alta_por_zona.csv', z))
    arqs.append(csv_out('C8-08_concentracao_locais_alta_por_municipio.csv', m))
    nums['locais'] = int(len(L))
    nums['locais_alta'] = int((L.prioridade_observacao == 'alta').sum())
    nums['zonas_bh_5pct'] = int(z['bh_5pct'].sum())
    nums['municipios_bh_5pct'] = int(m['bh_5pct'].sum())
    nums['zonas_top'] = [f"{r.uf} {r.municipality_name} z{r.zone}: {int(r.alta)} alta de {int(r.locais)} (esp. {r.esperado:.1f}, p {r.p_binomial:.1e})" for r in z.head(8).itertuples()]
    # manual alto (cadencia) por zona
    C = pd.read_csv(REL / 'verificacoes' / 'cadencia' / 'locais_alta_habilitacao_manual.csv', sep=';', decimal=',', encoding='utf-8-sig',
                    usecols=['uf', 'municipality', 'zone', 'voting_place', 'pct_manual_nao_associado'])
    nums['locais_alta_manual_cadencia'] = int(len(C))
    k4 = ['uf', 'municipality', 'zone', 'voting_place']
    nums['locais_alta_que_sao_alta_manual'] = int(len(L[L.prioridade_observacao == 'alta'].merge(C.drop_duplicates(k4), on=k4)))
    nums['cadencia_linhas_duplicadas_por_chave'] = int(C.duplicated(k4).sum())
    nums['cadencia_locais_unicos'] = int(len(C.drop_duplicates(k4)))
    dup = C[C.duplicated(k4, keep=False)]
    quarentena('C8-08', dup, 'locais_alta_habilitacao_manual.csv: chave (uf, municipio, zona, local) repetida')
    C = C.drop_duplicates(k4)
    # predios alta vs demais do municipio no 2T 2026: variacao da fatia A T1->T2, manual, comparecimento, perfil 2022
    base = carrega_base(2026, KEY + ['voting_place', 't1_A', 't1_validos', 't2_A', 't2_validos', 't2_manual', 't2_comp', 't2_aptos', 't1_comp', 't1_aptos'])
    base = base[base.uf.isin(UFS11)]
    pred = base.groupby(['uf', 'municipality', 'zone', 'voting_place']).agg(
        secoes=('section', 'size'), t1_A=('t1_A', 'sum'), t1_validos=('t1_validos', 'sum'), t2_A=('t2_A', 'sum'), t2_validos=('t2_validos', 'sum'),
        t2_manual=('t2_manual', 'sum'), t2_comp=('t2_comp', 'sum'), t2_aptos=('t2_aptos', 'sum'), t1_comp=('t1_comp', 'sum'), t1_aptos=('t1_aptos', 'sum')).reset_index()
    pred['delta_fatia_A_pp'] = 100 * (pred['t2_A'] / pred['t2_validos'] - pred['t1_A'] / pred['t1_validos'])
    pred['manual_share_t2'] = pred['t2_manual'] / pred['t2_comp']
    pred['comp_t2'] = pred['t2_comp'] / pred['t2_aptos']
    pred['delta_comp_pp'] = 100 * (pred['t2_comp'] / pred['t2_aptos'] - pred['t1_comp'] / pred['t1_aptos'])
    sec26 = carrega_secoes(2026, KEY + ['voting_place', 'n2', 'res_pp'])
    sec26 = sec26[sec26['n2'] > 0].assign(wr=lambda x: x['res_pp'] * x['n2'])
    rp = sec26.groupby(['uf', 'municipality', 'zone', 'voting_place'])[['wr', 'n2']].sum()
    rp = (rp['wr'] / rp['n2']).rename('res_pp_M1_medio').reset_index()
    pred = pred.merge(rp, on=['uf', 'municipality', 'zone', 'voting_place'], how='left')
    del base, sec26
    import pyarrow.parquet as pq
    perf = []
    for uf in UFS11:
        p = R / 'perfil' / '2022' / f'{uf}.parquet'
        if p.exists():
            x = pd.read_parquet(p, columns=['municipality', 'zone', 'voting_place', 'voters', 'age60', 'low_school'] +
                                (['biometria'] if 'biometria' in pq.ParquetFile(p).schema_arrow.names else []))
            x['uf'] = uf
            x['voting_place'] = pd.to_numeric(x['voting_place'], errors='coerce')
            perf.append(x)
    if perf:
        pf = pd.concat(perf, ignore_index=True)
        pf = pf.groupby(['uf', 'municipality', 'zone', 'voting_place']).sum(numeric_only=True).reset_index()
        pf['age60_pct'] = 100 * pf['age60'] / pf['voters']
        pf['low_school_pct'] = 100 * pf['low_school'] / pf['voters']
        if 'biometria' in pf:
            pf['biometria_pct'] = 100 * pf['biometria'] / pf['voters']
        pred = pred.merge(pf[['uf', 'municipality', 'zone', 'voting_place', 'age60_pct', 'low_school_pct'] + (['biometria_pct'] if 'biometria_pct' in pf else [])],
                          on=['uf', 'municipality', 'zone', 'voting_place'], how='left')
    marc = L[L.prioridade_observacao == 'alta']
    desf = ['delta_fatia_A_pp', 'res_pp_M1_medio', 'manual_share_t2', 'comp_t2', 'delta_comp_pp', 'age60_pct', 'low_school_pct'] + (['biometria_pct'] if 'biometria_pct' in pred else [])
    comp = c8_08_predios_vs_municipio(pred, marc, [d for d in desf if d in pred])
    comp['grupo'] = 'locais alta (varredura)'
    comp2 = c8_08_predios_vs_municipio(pred, C, [d for d in desf if d in pred])
    comp2['grupo'] = 'locais alta habilitacao manual (cadencia)'
    cc = pd.concat([comp, comp2], ignore_index=True)
    arqs.append(csv_out('C8-08_predios_alta_vs_mesmo_municipio_2026t2.csv', cc))
    nums['predios_alta_vinculados_base_2026'] = int(comp['predios_alta'].max())
    nums['dif_dentro_municipio'] = {f"{r.grupo}/{r.desfecho}": {'dif': round(float(r.diferenca_dentro_mun), 3), 't': round(float(r.t), 2) if pd.notna(r.t) else None} for r in cc.itertuples()}
    # as 6 zonas citadas
    seis_ref = {('LAURO DE FREITAS', 180), ('FEIRA DE SANTANA', 157), ('RIO DE JANEIRO', 179), ('CAMAÇARI', 171), ('ARARIPINA', 84),
                ('TEIXEIRA DE FREITAS', 183)}
    seis = z[[(str(a).upper(), int(b)) in seis_ref for a, b in zip(z['municipality_name'], z['zone'])]]
    nums['seis_zonas'] = [f"{r.uf} {r.municipality_name} z{r.zone}: {int(r.alta)}/{int(r.locais)} alta (esp. {r.esperado:.2f}; p {r.p_binomial:.1e}; BH {bool(r.bh_5pct)})"
                          for r in seis.itertuples()]
    nums['seis_zonas_bh'] = int(seis['bh_5pct'].sum())
    _rec(resumo, 'C8-08', 'feita', nums, arqs)
    for r in cc[(cc['t'].abs() >= 4) & (cc['grupo'] == 'locais alta (varredura)')].itertuples():
        achados.append(_achado(
            'C8-08', f'Predios "{r.grupo}" diferem dos demais do mesmo municipio em {r.desfecho} (t {r.t:.1f})', '2026-t2', 'PRESIDENTE', '11 UFs',
            f'{r.predios_alta} predios marcados vs {r.predios_outros_mesmo_mun} outros', 'cluster de processo x resultado/composicao',
            f'diferenca dentro do municipio {r.diferenca_dentro_mun:+.3f} ({r.desfecho}); medias {r.media_alta:.3f} vs {r.media_outros:.3f}', float(r.diferenca_dentro_mun),
            0, 0, 'delta_fatia_A_pp e em pontos de fatia por predio; materialidade = dif x validos dos predios marcados (ver CSV)',
            'predio como unidade; efeito fixo de municipio; marcacao vem de 2022 T1-2026 T1 (fora do 2T 2026)',
            'perfil 2022 (idade, escolaridade, biometria) na mesma tabela; M1 medio do predio ~0 por construcao',
            ['composicao do eleitorado (idade/escolaridade) explica manual e comparecimento', 'persistencia logistica dos mesmos predios',
             'selecao dos locais usa o comportamento do 1o turno de 2026 (comparecimento/manual): regressao a media no 2o turno'],
            'PLAUSIVEL-EXPLICAVEL', 'perfil do eleitorado 2026 por secao', arqs[-1:], 2))
    if nums['cadencia_locais_unicos'] == nums['locais_alta_que_sao_alta_manual']:
        achados.append(_achado(
            'C8-08', f"A lista de {len(C) + nums['cadencia_linhas_duplicadas_por_chave']} locais de alta habilitacao manual (cadencia) e o mesmo conjunto dos "
                     f"{nums['locais_alta']} locais de prioridade alta da varredura ({nums['cadencia_linhas_duplicadas_por_chave']} linhas repetidas)",
            '2026-t1', 'PRESIDENTE', '11 UFs', f"{nums['cadencia_locais_unicos']} locais unicos", 'consistencia de dados (derivacao)',
            f"{nums['locais_alta_que_sao_alta_manual']} dos {nums['cadencia_locais_unicos']} locais unicos da cadencia sao 'alta' na varredura; a 'mesma "
            "distribuicao' (BA 159/144, PE 148/143) nao e confirmacao independente, e a mesma lista com linhas repetidas",
            float(nums['cadencia_linhas_duplicadas_por_chave']), 0, 0, 'sem materialidade (lista de locais)', 'cruzamento por (uf, municipio, zona, local); duplicatas em quarentena',
            'nao se aplica', ['a cadencia partiu dos locais alta da varredura e expandiu por secao (G1/G2), repetindo o local'], 'ARTEFATO',
            'nenhum (documentacao do script make_cadencia_report/verifica_cadencia)', [str(REL / 'verificacoes' / 'cadencia' / 'locais_alta_habilitacao_manual.csv')], 3))
    if nums['zonas_bh_5pct']:
        top = z[z['bh_5pct']].head(6)
        achados.append(_achado(
            'C8-08', f'Locais de prioridade alta concentrados em {nums["zonas_bh_5pct"]} zonas acima do acaso (BH 5%)', '2022-t1..2026-t1', 'PRESIDENTE/PREFEITO',
            'BA/PE/RJ/PA/MA/CE', '; '.join(f'{r.uf} {r.municipality_name} z{r.zone} {int(r.alta)}/{int(r.locais)}' for r in top.itertuples()), 'cluster de processo',
            f'binomial contra a taxa da UF; {nums["municipios_bh_5pct"]} municipios tambem', float(nums['zonas_bh_5pct']), 0, 0, 'variavel de processo',
            'contagem de locais ja publicada; teste binomial por zona com BH', 'persistencia 2022->2026 ja documentada (multiano)',
            ['logistica do cartorio', 'composicao (idade/escolaridade/biometria) - ver CSV predios vs municipio'], 'PLAUSIVEL-EXPLICAVEL',
            'registro de ocorrencias do TRE por zona', arqs[:1], 2))


# ----------------------------------------------------------------------------------------------- C8-11
def c8_11_classifica(exc, ceft, integ):
    """Cruza cada excecao de relogio com o CEFT (urna esperada/efetivada, carga, maquina) e a integridade (assinatura)."""
    e = exc.copy()
    for c in ('municipio', 'zona', 'secao'):
        e[c] = pd.to_numeric(e[c], errors='coerce')
    e = e.rename(columns={'municipio': 'municipality', 'zona': 'zone', 'secao': 'section'})
    e['urna'] = pd.to_numeric(e['urna'], errors='coerce')
    out = e.merge(ceft, on=['eleicao', 'uf', 'municipality', 'zone', 'section'], how='left', suffixes=('', '_ceft'))
    out = out.merge(integ, on=['eleicao', 'uf', 'municipality', 'zone', 'section'], how='left')
    out['status'] = np.where(out['urna_efetivada'].isna(), NOT_COMP + ': sem CEFT para o pleito/UF', 'feita')
    out['urna_bate_ceft'] = out['urna'] == out['urna_efetivada']
    dif_carga = (out['carga'] - out['dt_carga']).abs()
    out['carga_bate_ceft_min'] = dif_carga.dt.total_seconds() / 60
    sem = out['urna_efetivada'].isna().to_numpy()
    troca = out['troca'].fillna(False).astype(bool).to_numpy()
    carga_ok = out['ok_carga_antes'].astype(bool).to_numpy()
    bate = out['carga_bate_ceft_min'].fillna(1e9).lt(60).to_numpy()
    ordem_ok = out['ok_ordem_urna'].astype(bool).to_numpy() if 'ok_ordem_urna' in out else np.ones(len(out), bool)
    out['classe'] = np.select(
        [sem, troca, ~carga_ok & bate, ~carga_ok, ~out['ok_data_eleicao'].astype(bool).to_numpy(), ~out['ok_tse_depois_da_urna'].astype(bool).to_numpy(),
         ~ordem_ok],
        ['sem CEFT', 'troca de urna no CEFT (esperada != efetivada)', 'carga original no dia, CEFT confirma a data', 'carga no dia, CEFT com outra data',
         'fora da data da eleicao', 'recebimento TSE antes da urna', 'ordem interna da urna violada (relogio)'], default='outra')
    return out


def roda_c8_11(resumo, achados, cache):
    con = duck()
    arqs, nums = [], {}
    exc = pd.read_csv(REL / 'verificacoes' / 'relogio_excecoes.csv', sep=';', decimal=',', encoding='utf-8-sig')
    for c in ('carga', 'abertura', 'encerramento', 'emissao_bu', 'recebido_tse'):
        exc[c] = pd.to_datetime(exc[c], errors='coerce')
    frames, ints = [], []
    for (ele, uf), _ in exc.groupby(['eleicao', 'uf']):
        c = carrega_ceft(ele, uf, con=con)
        if c is not None:
            c['eleicao'] = ele
            frames.append(c[['eleicao', 'uf', 'municipality', 'zone', 'section', 'urna_esperada', 'urna_efetivada', 'dt_carga', 'dt_carga_esperada', 'troca', 'divergencia', 'origem_voto']
                            + [x for x in ('maquina',) if x in c]])
    ceft = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=['eleicao', 'uf', 'municipality', 'zone', 'section', 'urna_esperada', 'urna_efetivada', 'dt_carga', 'dt_carga_esperada', 'troca', 'divergencia', 'origem_voto'])
    for ele in exc['eleicao'].unique():
        i = carrega_integridade(ele, ufs=sorted(exc[exc.eleicao == ele]['uf'].unique()), con=con)
        i = i.dropna(subset=['municipality'])
        i['eleicao'] = ele
        ints.append(i[['eleicao', 'uf', 'municipality', 'zone', 'section', 'cert_num', 'cert_emissor', 'assinado_em']])
    integ = pd.concat(ints, ignore_index=True)
    out = c8_11_classifica(exc, ceft, integ)
    out['assinatura_fora_do_dia'] = out['assinado_em'].str[:8] != out['eleicao'].map({'2022-t1': '20221002', '2022-t2': '20221030', '2026-t1': '20261004', '2026-t2': '20261025'})
    arqs.append(csv_out('C8-11_relogio_excecoes_x_ceft.csv', out))
    por_zona = out.groupby(['eleicao', 'uf', 'zone']).agg(excecoes=('section', 'size'), classes=('classe', lambda s: '; '.join(sorted(set(s))))).reset_index().sort_values('excecoes', ascending=False)
    arqs.append(csv_out('C8-11_excecoes_por_zona.csv', por_zona))
    if 'maquina' in out:
        por_maq = out.dropna(subset=['maquina']).groupby(['eleicao', 'uf', 'maquina']).size().rename('excecoes').reset_index().sort_values('excecoes', ascending=False)
        arqs.append(csv_out('C8-11_excecoes_por_maquina.csv', por_maq))
        nums['maquinas_com_2_ou_mais'] = int((por_maq['excecoes'] >= 2).sum())
    nums['excecoes'] = int(len(out))
    nums['classes'] = out['classe'].value_counts().to_dict()
    nums['sem_ceft'] = int((out['status'] != 'feita').sum())
    nums['urna_bate_ceft'] = int(out['urna_bate_ceft'].sum())
    nums['zonas_com_2_ou_mais'] = int((por_zona['excecoes'] >= 2).sum())
    nums['zonas_top'] = [f"{r.eleicao} {r.uf} z{int(r.zone)}: {int(r.excecoes)} ({r.classes})" for r in por_zona.head(6).itertuples()]
    nums['assinatura_fora_do_dia'] = int(out['assinatura_fora_do_dia'].fillna(False).sum())
    nums['cargas_no_dia_2022t1_PR_SP_BA'] = {u: int(((out.eleicao == '2022-t1') & (out.uf == u) & ~out.ok_carga_antes.astype(bool)).sum()) for u in ('PR', 'SP', 'BA')}
    nums['cargas_no_dia_2022t1_que_sao_troca'] = int(((out.eleicao == '2022-t1') & ~out.ok_carga_antes.astype(bool) & out.troca.fillna(False)).sum())
    _rec(resumo, 'C8-11', 'feita', nums, arqs)
    nums['classes_por_eleicao'] = {f'{e}/{c}': int(n) for (e, c), n in out.groupby(['eleicao', 'classe']).size().items()}
    arq = arqs[:2]
    cd = out[out['classe'] == 'carga original no dia, CEFT confirma a data']
    if len(cd):
        zc = cd.groupby(['eleicao', 'uf', 'zone']).size().sort_values(ascending=False)
        achados.append(_achado(
            'C8-11', f'{len(cd)} urnas com carga no proprio dia da eleicao sem troca registrada no CEFT (urna esperada = efetivada, mesma data)',
            ', '.join(sorted(cd.eleicao.unique())), 'PRESIDENTE', ', '.join(sorted(cd.uf.unique())), f'{len(cd)} secoes em {len(zc)} zonas',
            'excecao tecnica (carga)', 'carga entre ' + str(cd['carga'].min())[11:16] + ' e ' + str(cd['carga'].max())[11:16] + ' do dia; zonas com mais casos: '
            + '; '.join(f'{e} {u} z{int(z)}: {n}' for (e, u, z), n in zc.head(6).items()) + f'; por pleito {cd.eleicao.value_counts().to_dict()}',
            float(len(cd)), 0, 0, 'sem materialidade em votos (atributo de carga); a urna abriu depois da carga em todos os casos',
            'CEFT e integridade cruzados por chave de secao; numero da urna do log = NR_URNA_EFETIVADA em ' f'{int(out.urna_bate_ceft.sum())} de {len(out)}',
            'mesma regra em 2022 T1/T2 e 2026 T1 (2026 T2 sem CEFT)', ['recarga da mesma urna na manha da eleicao (falha antes da abertura)',
            'urna de contingencia registrada como esperada no CEFT'], 'PLAUSIVEL-EXPLICAVEL', 'atas de carga/recarga dos cartorios; ata da mesa receptora', arq, 3))
    rel = out[out['classe'].isin(['recebimento TSE antes da urna', 'ordem interna da urna violada (relogio)', 'outra'])]
    if len(rel):
        achados.append(_achado(
            'C8-11', f'{len(rel)} urnas com relogio interno incoerente (BU emitido depois do recebimento no TSE ou data reiniciada)',
            ', '.join(sorted(rel.eleicao.unique())), 'PRESIDENTE', ', '.join(sorted(rel.uf.unique())), f'{len(rel)} secoes',
            'excecao tecnica (relogio)', '; '.join(f'{r.eleicao} {r.uf} m{int(r.municipality)} z{int(r.zone)} s{int(r.section)}: {r.classe}, emissao {r.emissao_bu}, '
                                                   f'TSE {r.recebido_tse}' for r in rel.itertuples()),
            float(len(rel)), 0, 0, 'sem materialidade em votos', 'urna e carga conferidas no CEFT (urna esperada = efetivada nesses casos); assinatura do BU no mesmo horario',
            'relogio_resumo.csv: casos isolados em 2022 e 2026', ['relogio da urna adiantado alguns minutos (deriva)', 'bateria do relogio (data 2009-01-01 = relogio reiniciado)'],
            'PLAUSIVEL-EXPLICAVEL', 'log da urna (ajuste de hora) das secoes listadas', arq, 3))
    del con


# ----------------------------------------------------------------------------------------------- C8-12
def c8_12_exterior(m26, m22, base26, base22):
    """Postos do exterior: residuo M5 2026 x 2022, comparecimento e fatias por posto."""
    def agg(b, ano):
        g = b[b.uf == 'ZZ'].groupby(['municipality', 'municipio']).agg(
            secoes=('section', 'size'), t2_aptos=('t2_aptos', 'sum'), t2_comp=('t2_comp', 'sum'), t2_A=('t2_A', 'sum'), t2_B=('t2_B', 'sum'),
            t1_comp=('t1_comp', 'sum'), t1_A=('t1_A', 'sum'), t1_validos=('t1_validos', 'sum'), t2_validos=('t2_validos', 'sum')).reset_index()
        g['comp_t2_pct'] = 100 * g['t2_comp'] / g['t2_aptos']
        g['fatia_A_t2_pct'] = 100 * g['t2_A'] / g['t2_validos']
        g['fatia_A_t1_pct'] = 100 * g['t1_A'] / g['t1_validos']
        g['delta_comp_t1_t2'] = g['t2_comp'] - g['t1_comp']
        return g.add_suffix(f'_{ano}').rename(columns={f'municipality_{ano}': 'municipality', f'municipio_{ano}': 'municipio'})
    z26 = agg(base26, 2026).merge(m26[m26.uf == 'ZZ'][['municipality', 'residuo_pp', 'n2']].rename(columns={'residuo_pp': 'residuo_m5_2026', 'n2': 'n2_2026'}), on='municipality', how='left')
    z22 = agg(base22, 2022).merge(m22[m22.uf == 'ZZ'][['municipality', 'residuo_pp', 'n2']].rename(columns={'residuo_pp': 'residuo_m5_2022', 'n2': 'n2_2022'}),
                                  on='municipality', how='left')
    z = z26.merge(z22.drop(columns=['municipio']), on='municipality', how='outer')
    z['status'] = np.where(z['residuo_m5_2022'].isna() | z['residuo_m5_2026'].isna(), NOT_COMP + ': posto sem par no outro ano', 'comparavel')
    z['peso_std'] = z['residuo_m5_2026'] * np.sqrt(z['n2_2026'].fillna(0))
    return z.sort_values('residuo_m5_2026', key=np.abs, ascending=False)


def roda_c8_12(resumo, achados, cache):
    arqs, nums = [], {}
    m26, m22 = carrega_m5(2026), carrega_m5(2022)
    cols = KEY + ['municipio', 't2_aptos', 't2_comp', 't2_A', 't2_B', 't1_comp', 't1_A', 't1_validos', 't2_validos']
    b26 = carrega_base(2026, cols)
    b22 = carrega_base(2022, cols)
    z = c8_12_exterior(m26, m22, b26[b26.uf == 'ZZ'], b22[b22.uf == 'ZZ'])
    arqs.append(csv_out('C8-12_exterior_postos.csv', z))
    comp = z[z.status == 'comparavel']
    ok26 = z['residuo_m5_2026'].notna() & z['n2_2026'].fillna(0).gt(0)
    w26 = np.average(z.loc[ok26, 'residuo_m5_2026'], weights=z.loc[ok26, 'n2_2026'])
    ok22 = z['residuo_m5_2022'].notna() & z['n2_2022'].fillna(0).gt(0)
    w22 = np.average(z.loc[ok22, 'residuo_m5_2022'], weights=z.loc[ok22, 'n2_2022'])
    contrib = (z.loc[ok26, 'residuo_m5_2026'] * z.loc[ok26, 'n2_2026']).sort_values(key=np.abs, ascending=False)
    top5 = float(contrib.head(5).sum() / contrib.sum())
    so_comp = np.average(comp.loc[comp['n2_2026'].fillna(0) > 0, 'residuo_m5_2026'], weights=comp.loc[comp['n2_2026'].fillna(0) > 0, 'n2_2026'])
    nums = {'postos_2026': int(z['residuo_m5_2026'].notna().sum()), 'postos_2022': int(z['residuo_m5_2022'].notna().sum()), 'comparaveis': int(len(comp)),
            'residuo_m5_2026_ponderado': round(float(w26), 3), 'dp_entre_postos_2026': round(float(z['residuo_m5_2026'].std()), 3),
            'corr_residuo_2022_2026': round(float(comp[['residuo_m5_2022', 'residuo_m5_2026']].corr().iloc[0, 1]), 3) if len(comp) > 3 else None,
            'postos_abs_residuo_ge_5pp': int((z['residuo_m5_2026'].abs() >= 5).sum()),
            'top': [f"{r.municipio} ({int(r.municipality)}): M5 2026 {r.residuo_m5_2026:+.2f} pp, 2022 {r.residuo_m5_2022 if pd.notna(r.residuo_m5_2022) else float('nan'):+.2f}; "
                    f"n2 {int(r.n2_2026) if pd.notna(r.n2_2026) else 0}; comp {r.comp_t2_pct_2026:.1f}%" for r in z.head(10).itertuples()],
            'soma_n2_2026': int(z['n2_2026'].fillna(0).sum()), 'residuo_m5_2022_ponderado': round(float(w22), 3),
            'fracao_do_desvio_nos_5_maiores_postos': round(top5, 3), 'residuo_2026_so_postos_com_par_2022': round(float(so_comp), 3),
            'soma_n2_2022': int(z['n2_2022'].fillna(0).sum())}
    _rec(resumo, 'C8-12', 'feita', nums, arqs)
    achados.append(_achado(
        'C8-12', f"Exterior (ZZ): residuo M5 ponderado {nums['residuo_m5_2026_ponderado']:+.2f} pp em 2026 contra "
                 f"{nums['residuo_m5_2022_ponderado']:+.2f} pp em 2022 (maior desvio de UF em 2026)", '2026-t2 / 2022-t2', 'PRESIDENTE', 'ZZ',
        f"{nums['postos_2026']} postos, {nums['soma_n2_2026']:,} votos", 'cluster territorial (exterior)',
        f"residuo ponderado {nums['residuo_m5_2026_ponderado']:+.2f} pp; dp entre postos {nums['dp_entre_postos_2026']}; corr com 2022 {nums['corr_residuo_2022_2026']}; "
        + '; '.join(nums['top'][:4]), float(nums['residuo_m5_2026_ponderado']), 0, int(abs(w26) / 100 * nums['soma_n2_2026']),
        'margem nacional; o exterior e ~0,1% dos votos', 'M5 por municipio ja publicado; postos sem par marcados NOT_COMPARABLE',
        f"2022 lado a lado por posto: residuo ponderado 2022 {nums['residuo_m5_2022_ponderado']:+.2f} pp; corr por posto {nums['corr_residuo_2022_2026']}; "
        f"5 maiores postos = {100 * nums['fracao_do_desvio_nos_5_maiores_postos']:.0f}% do desvio; so postos com par 2022: {nums['residuo_2026_so_postos_com_par_2022']:+.2f} pp",
        ['composicao do eleitorado no exterior nao representada no treino do M5 (modelo treinado no Brasil)', 'mudanca de comparecimento por posto',
         'postos novos de 2026 sem par em 2022 (Caracas, Ramallah, Paramaribo)'],
        'PLAUSIVEL-EXPLICAVEL', 'perfil do eleitorado no exterior por posto', arqs, 3))


# ----------------------------------------------------------------------------------------------- orquestracao
def _t():
    return time.time()


def _rec(resumo, cid, status, numeros, arquivos, motivo=''):
    resumo[cid] = {'status': status, 'motivo': motivo, 'numeros_chave': numeros, 'arquivos': arquivos,
                   'at': dt.datetime.now(dt.timezone.utc).isoformat()}


_ACHADOS_N: dict[str, int] = {}


def _achado(cid, titulo, pleito, cargo, uf, escopo, tipo, efeito, efeito_num, mat_min, mat_max, margem, artefato, controles, hipoteses,
            status, dado_externo, fonte, prioridade):
    _ACHADOS_N[cid] = _ACHADOS_N.get(cid, 0) + 1
    return {'id_sugerido': f'{cid}-A{_ACHADOS_N[cid]}', 'titulo': titulo, 'pleito': pleito, 'cargo': cargo, 'uf': uf,
            'escopo': escopo, 'tipo': tipo, 'efeito': efeito, 'efeito_num': float(efeito_num) if efeito_num is not None else None,
            'materialidade_min': int(mat_min), 'materialidade_max': int(mat_max), 'margem_referencia': margem, 'artefato_excluido': artefato,
            'controles': controles, 'hipoteses': list(hipoteses), 'status_sugerido': status, 'dados_externos': dado_externo,
            'fonte': list(fonte), 'prioridade': int(prioridade)}


RUNNERS = {'C8-01': roda_c8_01, 'C8-02': roda_c8_02, 'C8-03': roda_c8_03, 'C8-03c': roda_c8_03c, 'C8-09a': roda_c8_09a, 'C8-04p': roda_c8_04p, 'C8-04': roda_c8_04, 'C8-08': roda_c8_08, 'C8-09': roda_c8_09,
           'C8-11': roda_c8_11, 'C8-12': roda_c8_12, 'C8-10': roda_c8_10}


def roda_pendentes(resumo):
    for cid, motivo in PENDENTES.items():
        if cid not in resumo:
            _rec(resumo, cid, 'nao_feita', {}, [], motivo=motivo)


def _grava_estado(resumo, achados):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'C8_resumo.json').write_text(json.dumps({'camada': 'C8', 'protocolo': 'PROTOCOLO.md v1.0', 'parser_version': PARSER_VERSION,
                                                     'semente': SEED, 'n_perm': N_PERM, 'checagens': resumo}, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    (OUT / 'C8_achados.json').write_text(json.dumps(achados, ensure_ascii=False, indent=1, default=str), encoding='utf-8')


def main(ids=None):
    ids = ids or CHECAGENS
    OUT.mkdir(parents=True, exist_ok=True)
    resumo, achados, cache = {}, [], {}
    p_res, p_ach = OUT / 'C8_resumo.json', OUT / 'C8_achados.json'
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
    for cid in ids:
        t0 = _t()
        try:
            RUNNERS[cid](resumo, achados, cache)
            resumo.pop('C8-03c', None)
            resumo.pop('C8-09a', None)
            resumo.pop('C8-04p', None)
            print(f'{cid}: {resumo.get(cid, resumo.get(cid[:5], {})).get("status")} em {_t() - t0:.0f} s', flush=True)
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
        old = OUT / 'quarentena_C8.csv'
        if old.exists():
            q = pd.concat([pd.read_csv(old, sep=';', encoding='utf-8-sig', dtype=str), q], ignore_index=True).drop_duplicates()
        q.to_csv(old, **CSV)
    print(json.dumps({k: v['status'] for k, v in resumo.items()}, ensure_ascii=False))


if __name__ == '__main__':
    main([a for a in sys.argv[1:] if a.startswith('C8-')] or None)
