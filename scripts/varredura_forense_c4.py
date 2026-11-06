"""Varredura forense, camada C4 (totalizacao): checagens leves sobre os parquet/CSV ja existentes no repositorio.

Uma funcao por checagem: as funcoes `c4_XX_*` sao puras (recebem DataFrames e devolvem DataFrames/dicionarios) e os
carregadores (`carrega_*`, `tabela_secoes_bweb`, `stems_bu_urna`...) leem o disco com projecao de colunas e DuckDB
limitado (400 MB, 2 threads). `main()` roda as checagens pedidas e grava relatorios/verificacoes/varredura_forense/C4/
(CSVs `C4-XX_*.csv`, `C4_resumo.json`, `C4_achados.json`, `quarentena_C4.csv`); cache por pleito em
research/varredura_forense/C4/ (parquet + recibo .json). Importavel sem efeito pesado.

Protocolo: relatorios/verificacoes/varredura_forense/PROTOCOLO.md v1.0. Tudo aqui e descritivo: "diferenca" e
diferenca de reconciliacao entre publicacoes oficiais e nao indica irregularidade por si so.
Uso: python scripts/varredura_forense_c4.py [C4-01 C4-02 ...]   (sem argumentos: todas as checagens leves)
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
OUT = REL / 'verificacoes' / 'varredura_forense' / 'C4'
CACHE = R / 'varredura_forense' / 'C4'
QUAR = R / 'varredura_forense' / 'quarentena'
CSV = dict(sep=';', decimal=',', encoding='utf-8-sig', index=False)
PARSER_VERSION = 'varredura-forense-c4-1'
KEY = ['uf', 'municipality', 'zone', 'section']
UFS27 = ['AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MG', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI', 'PR',
         'RJ', 'RN', 'RO', 'RR', 'RS', 'SC', 'SE', 'SP', 'TO']
UFS = UFS27 + ['ZZ']
UFS11 = ['BA', 'CE', 'MA', 'MG', 'PA', 'PE', 'PR', 'RJ', 'RS', 'SC', 'SP']
PLEITOS_PRES = ['2014-t1', '2014-t2', '2018-t1', '2018-t2', '2022-t1', '2022-t2']
PLEITOS_PREF = ['2024-t1', '2024-t2']
PLEITOS_URNA = ['2022-t1', '2022-t2', '2024-t1', '2024-t2', '2026-t1', '2026-t2']
DIA_ELEICAO = {'2014-t1': '2014-10-05', '2014-t2': '2014-10-26', '2018-t1': '2018-10-07', '2018-t2': '2018-10-28',
               '2022-t1': '2022-10-02', '2022-t2': '2022-10-30', '2024-t1': '2024-10-06', '2024-t2': '2024-10-27',
               '2026-t1': '2026-10-04', '2026-t2': '2026-10-25'}
BRANCO, NULO = '95', '96'
APURADA = 1
NOT_COMP = 'NOT_COMPARABLE'
SEM_BU = 'BWEB sem .bu no zip de urna'
SEM_BWEB = '.bu no zip sem secao no BWEB'
# nomes possiveis de cada campo do BWEB (o layout muda entre 2014, 2018, 2022 e 2024)
BWEB_COLS = {
    'voting_place': ['NR_LOCAL_VOTACAO'], 'aptos': ['QT_APTOS'], 'comp': ['QT_COMPARECIMENTO'],
    'abst': ['QT_ABSTENCOES'], 'urna': ['NR_URNA_EFETIVADA'], 'cd_tipo_urna': ['CD_TIPO_URNA'],
    'ds_tipo_urna': ['DS_TIPO_URNA'], 'agregadas': ['DS_AGREGADAS', 'DS_SECOES_AGREGADAS'],
    'junta': ['NR_JUNTA_APURADORA'], 'turma': ['NR_TURMA_APURADORA'], 'dt_bu_recebido': ['DT_BU_RECEBIDO'],
    'dt_emissao_bu': ['DT_EMISSAO_BU'], 'dt_abertura': ['DT_ABERTURA'], 'dt_encerramento': ['DT_ENCERRAMENTO'],
    'dt_carga': ['DT_CARGA_URNA_EFETIVADA', 'DT_CARGA'],
    'biometria_nh': ['QT_ELEITORES_BIOMETRIA_NH', 'QT_ELEI_BIOM_SEM_HABILITACAO'],
}
BWEB_INT = {'aptos', 'comp', 'abst', 'urna', 'cd_tipo_urna', 'junta', 'turma', 'biometria_nh', 'voting_place'}
BWEB_DT = {'dt_bu_recebido', 'dt_emissao_bu', 'dt_abertura', 'dt_encerramento', 'dt_carga'}
RE_MEMBRO = re.compile(r'^(o\d{5}(?:[a-z]{2}\d{13}|-\d{13}))[-.](.+)$')
TIPOS_APURACAO_SEPARADA = ('busa.dat', 'logsa.jez', 'sa.vsc', 'imgbusa.dat')
_QUARENTENA: list[dict] = []


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
    """SHA-256 de uma entrada: reutiliza o recibo <arquivo>.json ja existente ao lado (hash do parquet gravado)."""
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


def recibo_ok(path):
    rec = Path(path).with_suffix('.json')
    if not Path(path).exists() or not rec.exists():
        return False
    try:
        return json.loads(rec.read_text(encoding='utf-8')).get('parser_version') == PARSER_VERSION
    except (ValueError, OSError):
        return False


def quarentena(checagem, df, reason):
    """Linhas que falham invariante: valores originais como string + motivo (JSON por checagem e CSV unico)."""
    if df is None or len(df) == 0:
        return 0
    rows = [{k: ('' if pd.isna(v) else str(v)) for k, v in r.items()} | {'reason': reason, 'checagem': checagem}
            for r in df.to_dict('records')]
    QUAR.mkdir(parents=True, exist_ok=True)
    p = QUAR / f'rows-C4-{checagem}.json'
    old = json.loads(p.read_text(encoding='utf-8')) if p.exists() else []
    p.write_text(json.dumps(old + rows, ensure_ascii=False, indent=1), encoding='utf-8')
    _QUARENTENA.extend(rows)
    return len(rows)


def csv_out(nome, df):
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / nome, **CSV)
    return str(OUT / nome)


def csv_in(nome):
    p = OUT / nome
    return pd.read_csv(p, sep=';', decimal=',', encoding='utf-8-sig') if p.exists() else None


def stem_chave(stem):
    """Os 13 digitos finais do stem sao municipio (5) + zona (4) + secao (4)."""
    if not isinstance(stem, str) or len(stem) < 13 or not stem[-13:].isdigit():
        return None
    d = stem[-13:]
    return int(d[:5]), int(d[5:9]), int(d[9:13])


def chaves_de_stems(stems, uf):
    """Series de stems -> DataFrame(uf, stem, municipality, zone, section); chave invalida fica NaN."""
    s = pd.Series(stems, dtype='string').reset_index(drop=True)
    d = s.str[-13:]
    ok = d.str.isdigit().fillna(False) & (s.str.len() >= 13)
    out = pd.DataFrame({'uf': uf, 'stem': s.astype(object)})
    out['municipality'] = pd.to_numeric(d.str[:5].where(ok), errors='coerce')
    out['zone'] = pd.to_numeric(d.str[5:9].where(ok), errors='coerce')
    out['section'] = pd.to_numeric(d.str[9:13].where(ok), errors='coerce')
    return out


def chave_int(df):
    """Remove linhas com chave nula e converte municipio/zona/secao para int."""
    d = df.dropna(subset=['municipality', 'zone', 'section']).copy()
    for c in ('municipality', 'zone', 'section'):
        d[c] = d[c].astype(int)
    return d


def membro_stem_tipo(nome):
    """'o03220mg4123800390168-bu.dat' -> ('o03220mg4123800390168', 'bu.dat'); 'o00407-...0104.bu' -> (stem, 'bu')."""
    m = RE_MEMBRO.match(nome)
    return (m.group(1), m.group(2)) if m else (None, nome)


def membros_por_stem(nomes):
    """Lista de membros de um zip -> uma linha por stem com os tipos presentes e flags (bu, rdv, log, assinatura, SA)."""
    rows = [membro_stem_tipo(n) for n in nomes]
    df = pd.DataFrame(rows, columns=['stem', 'tipo']).dropna(subset=['stem'])
    df = df.drop_duplicates().sort_values(['stem', 'tipo'])
    g = df.groupby('stem', sort=False)['tipo'].agg(';'.join).rename('tipos').reset_index()
    tipos = g.tipos.str.split(';')
    g['tem_bu'] = tipos.apply(lambda t: any(x in ('bu', 'bu.dat') for x in t))
    g['tem_rdv'] = tipos.apply(lambda t: any(x in ('rdv', 'rdv.dat') for x in t))
    g['tem_log'] = tipos.apply(lambda t: any(x in ('logjez', 'log.jez') for x in t))
    g['tem_assinatura'] = tipos.apply(lambda t: any(x in ('vscmr', 'vota.vsc') for x in t))
    g['apuracao_separada'] = tipos.apply(lambda t: any(x in TIPOS_APURACAO_SEPARADA for x in t))
    return g


def raiz_inventario(uf, pleito):
    """Raiz com remote-inventory.json (lista de membros do zip) para uma UF/pleito, ou None."""
    cands = [R / 'estados' / uf / pleito]
    if uf == 'BA':
        cands = [R / 'bahia-presidente-2022-2026' / pleito] + cands
    for c in cands:
        if (c / 'remote-inventory.json').exists():
            return c
    return None


def membros_inventario(raiz):
    j = json.loads((raiz / 'remote-inventory.json').read_text(encoding='utf-8'))
    ent = j[0] if isinstance(j, list) else j
    nomes = [m['name'] if isinstance(m, dict) else str(m) for m in ent.get('members', [])]
    del j
    return nomes


def ler_cs_json(path, uf=None):
    """Config do sistema de resultados (lista oficial de secoes do 2o turno 2026 com data/hora de recebimento)."""
    j = json.loads(Path(path).read_text(encoding='utf-8'))
    rows = []
    for ab in j.get('abr', []):
        uf_ = (uf or ab.get('cd', '')).upper()
        for mu in ab.get('mu', []):
            for zn in mu.get('zon', []):
                for se in zn.get('sec', []):
                    rows.append({'uf': uf_, 'municipality': int(mu['cd']), 'municipio': mu.get('nm', ''),
                                 'zone': int(zn['cd']), 'section': int(se['ns']),
                                 'recebido_em': f"{se.get('da', '')} {se.get('ha', '')}".strip(),
                                 'secao_principal': pd.to_numeric(se.get('nsp'), errors='coerce'),
                                 'secoes_agregadas': se.get('nsa', '')})
    out = pd.DataFrame(rows, columns=['uf', 'municipality', 'municipio', 'zone', 'section', 'recebido_em',
                                      'secao_principal', 'secoes_agregadas'])
    out['recebido_em'] = pd.to_datetime(out.recebido_em, format='%d/%m/%Y %H:%M:%S', errors='coerce')
    out['agregada'] = out.secao_principal.notna()
    return out


def stems_bu_urna(pleito):
    """Coluna stem de todos os part-*.parquet de um pleito (so a chave; nunca bu_raw)."""
    con = duck()
    pat = (R / 'bu_urna' / pleito).as_posix() + '/*/part-*.parquet'
    df = con.execute(f"select stem, filename from read_parquet('{pat}', filename=true)").df()
    con.close()
    df['uf'] = df.filename.str.replace('\\', '/', regex=False).str.split('/').str[-2]
    parts = [chaves_de_stems(g.stem, uf) for uf, g in df.groupby('uf', sort=True)]
    out = pd.concat(parts, ignore_index=True) if parts else chaves_de_stems([], 'XX')
    out['pleito'] = pleito
    return out


def _expr(canon, names):
    for n in BWEB_COLS[canon]:
        if n in names:
            if canon in BWEB_INT:
                return f'max(try_cast({n} as bigint))'
            if canon in BWEB_DT:
                return f"max(coalesce(try_strptime({n}, '%d/%m/%Y %H:%M:%S'), try_strptime({n}, '%d/%m/%Y')))"
            if canon == 'agregadas':
                return f"max(nullif({n}, '#NULO#'))"
            return f'max({n})'
    typ = 'BIGINT' if canon in BWEB_INT else 'TIMESTAMP' if canon in BWEB_DT else 'VARCHAR'
    return f'cast(NULL as {typ})'


def secoes_bweb_uf(con, path, uf):
    """BWEB (uma linha por votavel x secao) -> uma linha por secao com campos de totalizacao e somas de votos."""
    names = pq_names(path)
    cols = ',\n '.join(f'{_expr(c, names)} {c}' for c in BWEB_COLS)
    q = f"""select '{uf}' uf, try_cast(CD_MUNICIPIO as integer) municipality, try_cast(NR_ZONA as integer) zone,
 try_cast(NR_SECAO as integer) section, {cols},
 min(try_cast(QT_APTOS as bigint)) aptos_min, min(try_cast(QT_COMPARECIMENTO as bigint)) comp_min,
 min(try_cast(QT_ABSTENCOES as bigint)) abst_min, count(distinct NR_URNA_EFETIVADA) n_urna,
 sum(try_cast(QT_VOTOS as bigint)) votos_total,
 sum(case when NR_VOTAVEL not in ('{BRANCO}','{NULO}') then try_cast(QT_VOTOS as bigint) else 0 end) votos_nominais,
 sum(case when NR_VOTAVEL='{BRANCO}' then try_cast(QT_VOTOS as bigint) else 0 end) branco,
 sum(case when NR_VOTAVEL='{NULO}' then try_cast(QT_VOTOS as bigint) else 0 end) nulo,
 count(*) n_linhas, count(distinct CD_CARGO_PERGUNTA) n_cargos
 from read_parquet('{Path(path).as_posix()}') group by 1, 2, 3, 4"""
    return con.execute(q).df()


def totais_candidatos_uf(con, path, uf):
    q = f"""select '{uf}' uf, NR_VOTAVEL numero, max(NM_VOTAVEL) nome, sum(try_cast(QT_VOTOS as bigint)) votos
 from read_parquet('{Path(path).as_posix()}') group by 1, 2"""
    return con.execute(q).df()


def arquivos_bweb(pleito, cargo):
    return sorted((R / 'bu' / pleito).glob(f'*_{cargo}.parquet'))


def tabela_secoes_bweb(pleito, cargo='PRESIDENTE', con=None, cols=None):
    """Tabela por secao do BWEB de um pleito/cargo (todas as UFs), em cache com recibo; tambem os totais por candidato."""
    CACHE.mkdir(parents=True, exist_ok=True)
    p_sec = CACHE / f'secoes_bweb_{pleito}_{cargo}.parquet'
    p_cand = CACHE / f'candidatos_bweb_{pleito}_{cargo}.parquet'
    if recibo_ok(p_sec) and recibo_ok(p_cand):
        return pd.read_parquet(p_sec, columns=cols), pd.read_parquet(p_cand)
    own = con is None
    con = con or duck()
    secs, cands, inputs = [], [], {}
    for path in arquivos_bweb(pleito, cargo):
        uf = path.name.split('_')[0]
        s = secoes_bweb_uf(con, path, uf)
        s['pleito'] = pleito
        secs.append(s)
        c = totais_candidatos_uf(con, path, uf)
        c['pleito'] = pleito
        cands.append(c)
        inputs[path] = sha_entrada(path)
        del s, c
    if own:
        con.close()
    sec = pd.concat(secs, ignore_index=True) if secs else pd.DataFrame()
    cand = pd.concat(cands, ignore_index=True) if cands else pd.DataFrame()
    grava_parquet(sec, p_sec, inputs)
    grava_parquet(cand, p_cand, inputs)
    del secs, cands
    gc.collect()
    return (sec[cols] if cols else sec), cand


def carrega_munzona(ano):
    p = R / 'segundo_turno_2026' / 'ref' / f'munzona_{ano}_presidente.parquet'
    df = pd.read_parquet(p)
    df['municipality'] = pd.to_numeric(df.CD_MUNICIPIO, errors='coerce').astype('Int64')
    df['turno'] = pd.to_numeric(df.NR_TURNO, errors='coerce').astype('Int64')
    return df.rename(columns={'SG_UF': 'uf', 'NM_MUNICIPIO': 'municipio', 'QT_APTOS': 'aptos_of',
                              'QT_COMPARECIMENTO': 'comp_of', 'QT_ABSTENCOES': 'abst_of'})[
        ['turno', 'uf', 'municipality', 'municipio', 'aptos_of', 'comp_of', 'abst_of']]


def carrega_desloc():
    """Deslocamento de fuso (h) por municipio, como usado em fechamento_2026t2 (AC +2, AM +1/+2, MT/MS/RO/RR +1, Noronha -1)."""
    p = REL / 'verificacoes' / 'fechamento_2026t2' / 'secoes_fechamento_recebimento.parquet'
    d = pd.read_parquet(p, columns=['uf', 'municipality', 'desloc_h']).dropna().drop_duplicates(['uf', 'municipality'])
    d['municipality'] = d.municipality.astype(int)
    return d


def carrega_secoes_2026():
    p = REL / 'verificacoes' / 'virada_1t_2t_2026' / 'secoes_t1_t2.parquet'
    s = pd.read_parquet(p)
    s['_merge'] = s['_merge'].astype(str)
    return s


def carrega_mun_todos():
    m = pd.read_parquet(R / 'segundo_turno_2026' / 'mun_todos.parquet')
    m['municipality'] = pd.to_numeric(m.mun_cd, errors='coerce').astype(int)
    return m.drop(columns=[c for c in ('abs_t1', 'abs_t2', 'mun5', 'abs22_t2') if c in m])


def carrega_c4_04_municipios(cache):
    """Resultado de C4-04 (por municipio, todos os pleitos) da memoria ou dos CSVs ja gravados."""
    if 'c4_04_municipios' in cache:
        return cache['c4_04_municipios']
    parts = [csv_in(f'C4-04_{p}_municipios.csv') for p in PLEITOS_PRES]
    parts = [p for p in parts if p is not None]
    if not parts:
        return None
    m = pd.concat(parts, ignore_index=True)
    cache['c4_04_municipios'] = m
    return m


# ----------------------------------------------------------------------------------------------- C4-01
def c4_01_reconciliar_2026(sec, mun):
    """Soma dos BUs por municipio x totais oficiais (mun_todos) em todos os campos, T1 e T2, sem excluir as secoes
    'right_only' (so no T2). Devolve (por municipio, por UF, resumo)."""
    sec = sec.copy()
    merge = sec['_merge'].astype(str)
    sec['t1_presente'] = (merge != 'right_only').astype(int)
    sec['t2_presente'] = (merge != 'left_only').astype(int)
    sec['so_t2'] = (merge == 'right_only').astype(int)
    sec['so_t1'] = (merge == 'left_only').astype(int)
    t1c = sorted(c for c in sec if re.fullmatch(r't1_v\d+', c))
    t2c = sorted(c for c in sec if re.fullmatch(r't2_v\d+', c))
    sec['t1_validos'] = sec[t1c].sum(axis=1, min_count=1)
    sec['t2_validos'] = sec[t2c].sum(axis=1, min_count=1)
    sec['t1_bn'] = sec.t1_branco + sec.t1_nulo
    sec['t2_bn'] = sec.t2_branco + sec.t2_nulo
    num = ['t1_aptos', 't1_comparecimento', 't1_validos', 't1_bn'] + t1c + \
          ['t2_aptos', 't2_comparecimento', 't2_validos', 't2_bn'] + t2c
    g = sec.groupby(['uf', 'municipality'])[num].sum(min_count=1)
    g[['t1_secoes', 't2_secoes', 'secoes_so_t2', 'secoes_so_t1']] = \
        sec.groupby(['uf', 'municipality'])[['t1_presente', 't2_presente', 'so_t2', 'so_t1']].sum()
    g = g.reset_index()
    of = mun.rename(columns={c: c + '_of' for c in mun if c.startswith('t1_') or c.startswith('t2_')})
    m = g.merge(of, on=['uf', 'municipality'], how='outer', indicator='fonte')
    m['fonte'] = m.fonte.astype(str)
    pares, sem_oficial = [], {}
    for t in ('t1', 't2'):
        m[f'{t}_abstencao'] = m[f'{t}_aptos'] - m[f'{t}_comparecimento']
        m[f'{t}_bn_of'] = m[f'{t}_comparecimento_of'] - m[f'{t}_validos_of']
        bu_c = set(t1c if t == 't1' else t2c)
        of_c = {c[:-3] for c in of if re.fullmatch(rf'{t}_v\d+_of', c)}
        # candidato com votos no BU mas sem linha no resultado oficial (registro indeferido): a totalizacao soma esses
        # votos aos nulos, logo saem dos validos e entram em brancos+nulos na comparacao, e ficam listados a parte
        so_bu = sorted(bu_c - of_c)
        m[f'{t}_v_sem_linha_oficial'] = m[so_bu].sum(axis=1, min_count=1).fillna(0) if so_bu else 0.0
        sem_oficial[t] = so_bu
        m[f'{t}_validos'] = m[f'{t}_validos'] - m[f'{t}_v_sem_linha_oficial']
        m[f'{t}_bn'] = m[f'{t}_bn'] + m[f'{t}_v_sem_linha_oficial']
        pares += [(f'{t}_aptos', f'{t}_eleitorado_of'), (f'{t}_comparecimento', f'{t}_comparecimento_of'),
                  (f'{t}_abstencao', f'{t}_abstencao_of'), (f'{t}_secoes', f'{t}_secoes_of'),
                  (f'{t}_validos', f'{t}_validos_of'), (f'{t}_bn', f'{t}_bn_of')]
        for c in sorted(bu_c | of_c):
            if c not in m:
                m[c] = 0.0
            if f'{c}_of' not in m:
                m[f'{c}_of'] = 0
            if c not in so_bu:
                pares.append((c, f'{c}_of'))
    for bu, ofc in pares:
        m[f'dif_{bu}'] = m[bu] - m[ofc]
    d1 = [f'dif_{b}' for b, _ in pares if b.startswith('t1_')]
    d2 = [f'dif_{b}' for b, _ in pares if b.startswith('t2_')]
    m['bate_t1'] = (m[d1].fillna(0).abs().sum(axis=1) == 0) & (m.fonte == 'both')
    m['bate_t2'] = (m[d2].fillna(0).abs().sum(axis=1) == 0) & (m.fonte == 'both')
    m['status'] = np.select(
        [m.fonte == 'left_only', m.fonte == 'right_only', m.bate_t1 & m.bate_t2],
        [f'{NOT_COMP}: sem referencia oficial no HD (mun_todos nao tem exterior)',
         f'{NOT_COMP}: municipio sem secao na base de BUs', 'OK'], 'diferenca acima do limiar (0)')
    m['origem'] = np.select(
        [m.fonte != 'both', m.bate_t1 & m.bate_t2, (~m.bate_t1) & (m.secoes_so_t2 > 0) & m.bate_t2,
         (~m.bate_t1) & (m.secoes_so_t2 == 0)],
        ['', '', 'T1: secao presente so no T2 (sem bu.dat no zip do T1); a diferenca de T1 e o que a totalizacao '
                 'contabilizou para essa secao sem BU publicado; T2 fecha com a secao incluida',
         'T1: diferenca sem secao faltante conhecida'], 'T2: diferenca nao explicada pela agregacao')
    m = m.sort_values(['uf', 'municipality']).reset_index(drop=True)
    comp = m[m.fonte == 'both']
    cols_uf = [c for p in pares for c in p]
    uf = comp.groupby('uf')[cols_uf + d1 + d2].sum().reset_index()
    br = uf[cols_uf + d1 + d2].sum().to_frame().T
    br.insert(0, 'uf', 'BR (sem exterior)')
    uf = pd.concat([uf, br], ignore_index=True)
    uf['bate_t1'] = uf[d1].abs().sum(axis=1) == 0
    uf['bate_t2'] = uf[d2].abs().sum(axis=1) == 0
    resumo = {'municipios_na_base': int((m.fonte != 'right_only').sum()), 'municipios_comparaveis': int(len(comp)),
              'municipios_batem_t1': int(comp.bate_t1.sum()), 'municipios_batem_t2': int(comp.bate_t2.sum()),
              'municipios_nao_comparaveis': int((m.fonte != 'both').sum()),
              'nao_batem_t1': comp.loc[~comp.bate_t1, ['uf', 'municipality', 'municipality_name']].to_dict('records'),
              'nao_batem_t2': comp.loc[~comp.bate_t2, ['uf', 'municipality', 'municipality_name']].to_dict('records'),
              'ufs_batem_t1': int(uf.bate_t1.sum()), 'ufs_batem_t2': int(uf.bate_t2.sum()),
              'campos_comparados': [b for b, _ in pares],
              'candidatos_sem_linha_oficial': {c: int(comp[c].sum()) for t in sem_oficial for c in sem_oficial[t]},
              'votos_sem_linha_oficial_t1': int(comp.t1_v_sem_linha_oficial.sum()),
              'votos_sem_linha_oficial_t2': int(comp.t2_v_sem_linha_oficial.sum())}
    return m, uf, resumo


def c4_01_invariante_secao(sec):
    """Invariante do BU: soma de todos os votaveis (nominais + branco + nulo) = comparecimento, e comparecimento <= aptos."""
    s = sec.copy()
    t1c = [c for c in s if re.fullmatch(r't1_v\d+', c)]
    s['t1_soma'] = s[t1c].sum(axis=1, min_count=1) + s.t1_branco + s.t1_nulo
    s['t2_soma'] = s.t2_v13 + s.t2_v22 + s.t2_branco + s.t2_nulo
    f1 = s[s.t1_soma.notna() & (s.t1_soma != s.t1_comparecimento)]
    f2 = s[s.t2_soma.notna() & (s.t2_soma != s.t2_comparecimento)]
    f3 = s[(s.t2_comparecimento > s.t2_aptos) | (s.t1_comparecimento > s.t1_aptos)]
    return f1, f2, f3


def c4_01_canais_2026_t2(sec, canal):
    """BU decodificado do sistema de resultados (noite de 25/10, 14 UFs) x BU decodificado do zip de dados abertos."""
    pares = [('t2_aptos', 'e6258_aptos'), ('t2_comparecimento', 'e6258_comparecimento'), ('t2_v13', 'e6258_c1_v13'),
             ('t2_v22', 'e6258_c1_v22'), ('t2_branco', 'e6258_c1_branco'), ('t2_nulo', 'e6258_c1_nulo')]
    m = sec[KEY + [a for a, _ in pares]].merge(canal, on=KEY, how='outer', indicator='fonte')
    m['fonte'] = m.fonte.astype(str)
    both = m.fonte == 'both'
    # o decodificador do sistema de resultados omite votaveis com zero votos (branco/nulo/candidato ficam NaN): NaN = 0
    m['campos_nulos_no_canal2'] = m[[b for _, b in pares]].isna().sum(axis=1).where(both, 0)
    for _, b in pares:
        m[b] = m[b].fillna(0)
    m['igual'] = both & np.all([(m[a] == m[b]).values for a, b in pares], axis=0)
    m['status'] = np.select([m.fonte == 'left_only', m.fonte == 'right_only', m.igual],
                            ['so dados abertos', f'{NOT_COMP}: so no sistema de resultados', 'igual'], 'diferente')
    r = m[both].groupby(['uf', 'aux_status']).agg(secoes=('igual', 'size'), iguais=('igual', 'sum'),
                                                   secoes_com_campo_nulo_no_canal2=('campos_nulos_no_canal2', lambda s: int((s > 0).sum()))
                                                   ).reset_index()
    r['diferentes'] = r.secoes - r.iguais
    return m[m.status == 'diferente'], r, int(both.sum()), int(m[both].igual.sum())


# ----------------------------------------------------------------------------------------------- C4-02
def c4_02_esperadas_x_recebidas(esperadas, recebidas):
    """Lista oficial de secoes (cs.json) x stems com BU no zip -> status por secao."""
    e = esperadas[KEY].drop_duplicates().assign(esperada=1)
    r = chave_int(recebidas[KEY + ['stem']])
    m = e.merge(r, on=KEY, how='outer', indicator='fonte')
    m['fonte'] = m.fonte.astype(str)
    m['status'] = np.select([m.fonte == 'left_only', m.fonte == 'right_only'],
                            ['esperada sem BU no zip', 'BU no zip sem secao na lista oficial'], 'OK')
    return m


def c4_02_contagem_municipio(sec, mun):
    """Numero de BUs por municipio (T1 e T2) x t1_secoes / t2_secoes oficiais."""
    merge = sec['_merge'].astype(str)
    g = sec.assign(t1=(merge != 'right_only').astype(int), t2=(merge != 'left_only').astype(int)) \
        .groupby(['uf', 'municipality'])[['t1', 't2']].sum().reset_index()
    m = g.merge(mun[['uf', 'municipality', 'municipality_name', 't1_secoes', 't2_secoes']],
                on=['uf', 'municipality'], how='outer', indicator='fonte')
    m['fonte'] = m.fonte.astype(str)
    m['dif_t1'] = m.t1 - m.t1_secoes
    m['dif_t2'] = m.t2 - m.t2_secoes
    m['status'] = np.select([m.fonte != 'both', (m.dif_t1 == 0) & (m.dif_t2 == 0)],
                            [f'{NOT_COMP}: sem referencia (exterior) ou sem BU', 'OK'], 'diferenca acima do limiar (0)')
    return m


# ----------------------------------------------------------------------------------------------- C4-03 / C4-15
def c4_03_bweb_x_bu(sec_bweb, stems):
    """Secoes do BWEB (BU em CSV) x stems com .bu no zip de urna, mesmo pleito: anti-join nos dois sentidos."""
    b = chave_int(sec_bweb)
    s = chave_int(stems)
    m = b.merge(s[KEY + ['stem']], on=KEY, how='outer', indicator='fonte')
    m['fonte'] = m.fonte.astype(str)
    m['status'] = np.select([m.fonte == 'left_only', m.fonte == 'right_only'], [SEM_BU, SEM_BWEB], 'OK')
    por_uf = m.groupby('uf').agg(bweb=('fonte', lambda f: int((f != 'right_only').sum())),
                                 bu_zip=('fonte', lambda f: int((f != 'left_only').sum())),
                                 bweb_sem_bu=('fonte', lambda f: int((f == 'left_only').sum())),
                                 bu_sem_bweb=('fonte', lambda f: int((f == 'right_only').sum()))).reset_index()
    return m[m.status != 'OK'].copy(), por_uf


def prefixo_stems(stems_uf):
    """Prefixo mais comum dos stems de uma UF (tudo antes dos 13 digitos), para montar o stem esperado de uma secao."""
    s = stems_uf.stem.dropna().astype(str)
    if s.empty:
        return None
    return s.str[:-13].mode().iloc[0]


def stem_esperado(prefixo, municipality, zone, section):
    return None if prefixo is None else f'{prefixo}{int(municipality):05d}{int(zone):04d}{int(section):04d}'


def carrega_ceft(pleito, uf, con=None):
    """CEFT (correspondencia esperada x efetivada) por secao; None se nao houver ou se o layout for sem cabecalho."""
    p = R / 'ceft' / pleito / f'{uf}.parquet'
    if not p.exists():
        return None
    names = pq_names(p)
    if 'DS_ORIGEM_VOTO' not in names:
        return None
    div = 'DS_DIVERGENCIA' if 'DS_DIVERGENCIA' in names else 'TP_DIVERGENCIA' if 'TP_DIVERGENCIA' in names else 'NULL'
    own = con is None
    con = con or duck()
    q = f"""select '{uf}' uf, try_cast(CD_MUNICIPIO as integer) municipality, try_cast(NR_ZONA as integer) zone,
 try_cast(NR_SECAO as integer) section, NR_URNA_ESPERADA urna_esperada, NR_URNA_EFETIVADA urna_efetivada,
 DS_ORIGEM_VOTO origem_voto, {div} divergencia from read_parquet('{p.as_posix()}')"""
    df = con.execute(q).df()
    if own:
        con.close()
    df['troca_urna'] = (df.urna_esperada != df.urna_efetivada) & df.urna_esperada.notna() & df.urna_efetivada.notna()
    df['pleito'] = pleito
    return df


def votos_candidatos_secoes(pleito, cargo, uf, chaves, con=None):
    """Votos por candidato das secoes listadas (materialidade de uma lista pequena de secoes)."""
    paths = [p for p in arquivos_bweb(pleito, cargo) if p.name.startswith(f'{uf}_')]
    if not paths or chaves.empty:
        return pd.DataFrame(columns=['uf', 'municipality', 'zone', 'section', 'numero', 'nome', 'votos'])
    own = con is None
    con = con or duck()
    con.register('chaves', chaves[['municipality', 'zone', 'section']].astype(int))
    q = f"""select '{uf}' uf, try_cast(CD_MUNICIPIO as integer) municipality, try_cast(NR_ZONA as integer) zone,
 try_cast(NR_SECAO as integer) section, NR_VOTAVEL numero, max(NM_VOTAVEL) nome, sum(try_cast(QT_VOTOS as bigint)) votos
 from read_parquet('{paths[0].as_posix()}') b
 where exists (select 1 from chaves c where c.municipality = try_cast(b.CD_MUNICIPIO as integer)
   and c.zone = try_cast(b.NR_ZONA as integer) and c.section = try_cast(b.NR_SECAO as integer))
 group by 1, 2, 3, 4, 5"""
    df = con.execute(q).df()
    con.unregister('chaves')
    if own:
        con.close()
    return df


# ----------------------------------------------------------------------------------------------- C4-04
def c4_04_municipios(sec, ref):
    """Soma por municipio de aptos/comparecimento/abstencoes (uma linha por secao) x referencia oficial do turno.
    sec: uf, municipality, aptos, comp, abst, cd_tipo_urna, agregadas; ref: uf, municipality, municipio, *_of."""
    s = sec.dropna(subset=['municipality']).copy()
    s['municipality'] = s.municipality.astype(int)
    s['anulada'] = (s.cd_tipo_urna.fillna(APURADA) != APURADA).astype(int)
    s['agregada'] = s.agregadas.notna().astype(int) if 'agregadas' in s else 0
    g = s.groupby(['uf', 'municipality']).agg(secoes=('aptos', 'size'), aptos_bu=('aptos', 'sum'),
                                              comp_bu=('comp', 'sum'), abst_bu=('abst', 'sum'),
                                              anuladas=('anulada', 'sum'), agregadas=('agregada', 'sum')).reset_index()
    r = ref.dropna(subset=['municipality']).copy()
    r['municipality'] = r.municipality.astype(int)
    m = g.merge(r, on=['uf', 'municipality'], how='outer', indicator='fonte')
    m['fonte'] = m.fonte.astype(str)
    for c in ('aptos', 'comp', 'abst'):
        m[f'dif_{c}'] = m[f'{c}_bu'] - m[f'{c}_of']
    difs = m[['dif_aptos', 'dif_comp', 'dif_abst']].fillna(0).abs().sum(axis=1)
    m['status'] = np.select([m.fonte == 'left_only', m.fonte == 'right_only', difs == 0],
                            [f'{NOT_COMP}: municipio sem referencia oficial', f'{NOT_COMP}: referencia sem secao no BWEB',
                             'OK'], 'diferenca acima do limiar (0)')
    return m.sort_values(['uf', 'municipality']).reset_index(drop=True)


def c4_04_por_uf(m):
    comp = m[m.fonte == 'both']
    cols = ['secoes', 'anuladas', 'agregadas', 'aptos_bu', 'comp_bu', 'abst_bu', 'aptos_of', 'comp_of', 'abst_of',
            'dif_aptos', 'dif_comp', 'dif_abst']
    uf = comp.groupby('uf')[cols].sum().reset_index()
    uf['municipios'] = comp.groupby('uf').size().values
    uf['municipios_batem'] = comp.groupby('uf').status.apply(lambda s: int((s == 'OK').sum())).values
    tot = uf[cols + ['municipios', 'municipios_batem']].sum().to_frame().T
    tot.insert(0, 'uf', 'TOTAL (com exterior)')
    sem = uf[uf.uf != 'ZZ'][cols + ['municipios', 'municipios_batem']].sum().to_frame().T
    sem.insert(0, 'uf', 'BR (sem exterior)')
    return pd.concat([uf, sem, tot], ignore_index=True)


# ----------------------------------------------------------------------------------------------- C4-05
def c4_05_stems_duplicados(stems):
    """Chaves municipio-zona-secao repetidas entre stems (mesmo pleito) e stems com chave invalida."""
    s = stems.copy()
    inval = s[s[['municipality', 'zone', 'section']].isna().any(axis=1)]
    v = s.dropna(subset=['municipality', 'zone', 'section'])
    dup = v[v.duplicated(['pleito'] + KEY, keep=False)].sort_values(['pleito'] + KEY)
    return dup, inval


def c4_05_bweb_inconsistencias(sec):
    """Secoes do BWEB com mais de uma urna efetivada, QT_* nao constantes entre linhas, ou invariantes quebrados."""
    s = sec.copy()
    s['n_urna_gt1'] = s.n_urna > 1
    s['aptos_var'] = s.aptos != s.aptos_min
    s['comp_var'] = s.comp != s.comp_min
    s['abst_var'] = s.abst != s.abst_min
    s['aptos_ne_comp_abst'] = (s.aptos - s.comp - s.abst).fillna(0) != 0
    s['votos_ne_comp'] = (s.votos_total - s.comp).fillna(0) != 0
    s['chave_nula'] = s[['municipality', 'zone', 'section']].isna().any(axis=1)
    s['multi_cargo'] = s.n_cargos > 1
    s['dup_chave'] = s.duplicated(['pleito'] + KEY, keep=False) & ~s.chave_nula
    flags = ['n_urna_gt1', 'aptos_var', 'comp_var', 'abst_var', 'aptos_ne_comp_abst', 'votos_ne_comp', 'chave_nula',
             'multi_cargo', 'dup_chave']
    casos = s[s[flags].any(axis=1)]
    resumo = s.groupby(['pleito', 'uf'])[flags].sum().reset_index()
    resumo['secoes'] = s.groupby(['pleito', 'uf']).size().values
    return casos, resumo, flags


# ----------------------------------------------------------------------------------------------- C4-07
def c4_07_anuladas(sec, mun_conf, stems=None):
    """Secoes com DS_TIPO_URNA diferente de APURADA: o total oficial do municipio inclui ou exclui a secao?"""
    a = sec[sec.cd_tipo_urna.fillna(APURADA) != APURADA].copy()
    if a.empty:
        return a
    m = a.merge(mun_conf[['pleito', 'uf', 'municipality', 'municipio', 'dif_aptos', 'dif_comp', 'status']],
                on=['pleito', 'uf', 'municipality'], how='left', suffixes=('', '_mun'))

    def classe(dif, valor):
        if pd.isna(dif):
            return f'{NOT_COMP}: municipio sem referencia oficial'
        if valor == 0:
            return 'valor 0 na secao: inclusao indistinguivel'
        if dif == 0:
            return 'total oficial inclui a secao (soma com a secao bate)'
        if dif == valor:
            return 'total oficial exclui a secao (soma sem a secao bate)'
        return 'diferenca de outra origem no municipio'
    m['comp_no_oficial'] = [classe(d, v) for d, v in zip(m.dif_comp, m.comp)]
    m['aptos_no_oficial'] = [classe(d, v) for d, v in zip(m.dif_aptos, m.aptos)]
    if stems is not None and len(stems):
        st = chave_int(stems[['pleito'] + KEY + ['stem']])
        m = m.merge(st, on=['pleito'] + KEY, how='left')
    else:
        m['stem'] = None
    m['tem_bu_no_zip'] = np.where(m.pleito.isin(PLEITOS_URNA), np.where(m.stem.notna(), 'sim', 'nao'),
                                  'sem zip de urna no pleito')
    return m


# ----------------------------------------------------------------------------------------------- C4-08
def explodir_agregadas(sec):
    """DS_AGREGADAS ('628 / 629') -> uma linha por secao agregada: (pleito, uf, municipality, zone, section, agregada)."""
    a = sec[sec.agregadas.notna()][['pleito'] + KEY + ['agregadas', 'aptos', 'comp']].copy()
    if a.empty:
        return pd.DataFrame(columns=['pleito'] + KEY + ['agregada', 'aptos', 'comp'])
    a['agregada'] = a.agregadas.astype(str).str.split('/')
    a = a.explode('agregada')
    a['agregada'] = pd.to_numeric(a.agregada.str.strip(), errors='coerce')
    return a.drop(columns='agregadas')


def c4_08_agregadas_com_bu_proprio(agr, sec):
    """Secao listada como agregada que tambem aparece com BU proprio no mesmo pleito (esperado: nenhuma)."""
    chaves = chave_int(sec[['pleito'] + KEY]).drop_duplicates().rename(columns={'section': 'agregada'}).assign(bu_proprio=1)
    m = chave_int(agr.dropna(subset=['agregada'])).astype({'agregada': int}).merge(
        chaves, on=['pleito', 'uf', 'municipality', 'zone', 'agregada'], how='left')
    m['bu_proprio'] = m.bu_proprio.fillna(0).astype(int)
    return m


def c4_08_aptos_vs_perfil(agr, sec, perfil):
    """Aptos da secao principal x eleitores do perfil (principal + agregadas) e x principal sozinha (2022)."""
    p = chave_int(perfil[['uf', 'municipality', 'zone', 'section', 'voters']])
    ag = chave_int(agr.dropna(subset=['agregada'])).astype({'agregada': int})
    ag = ag.merge(p.rename(columns={'section': 'agregada', 'voters': 'voters_agregada'}),
                  on=['uf', 'municipality', 'zone', 'agregada'], how='left')
    g = ag.groupby(['pleito'] + KEY).agg(n_agregadas=('agregada', 'size'),
                                         voters_agregadas=('voters_agregada', 'sum'),
                                         agregadas_sem_perfil=('voters_agregada', lambda v: int(v.isna().sum()))).reset_index()
    g = g.merge(chave_int(sec[['pleito'] + KEY + ['aptos']]), on=['pleito'] + KEY, how='left')
    g = g.merge(p.rename(columns={'voters': 'voters_principal'}), on=KEY, how='left')
    g['dif_aptos_vs_principal_mais_agregadas'] = g.aptos - (g.voters_principal + g.voters_agregadas)
    g['dif_aptos_vs_principal'] = g.aptos - g.voters_principal
    g['leitura'] = np.select(
        [g.voters_principal.isna(), g.dif_aptos_vs_principal_mais_agregadas == 0, g.dif_aptos_vs_principal == 0],
        [f'{NOT_COMP}: principal sem perfil', 'aptos = principal + agregadas', 'aptos = so a principal'],
        'aptos difere das duas somas')
    return g


# ----------------------------------------------------------------------------------------------- C4-10
def c4_10_recebimento_antes(fech):
    """2026 T2: secoes com recebimento pelo TSE antes do encerramento registrado pela urna (min_rec_apos_enc < 0)."""
    f = fech[fech.min_rec_apos_enc < 0].copy()
    f['min_antes'] = -f.min_rec_apos_enc
    return f.sort_values('min_rec_apos_enc')


def c4_10_relogio_excecoes(rel):
    """relogio_por_secao: urna emitiu o BU depois de o TSE receber (ok_tse_depois_da_urna False) e demais flags."""
    ex = rel[(~rel.ok_tse_depois_da_urna.astype(bool)) & (~rel.sem_datas.astype(bool))].copy()
    res = rel.groupby(['eleicao', 'uf']).agg(
        secoes=('ok_tse_depois_da_urna', 'size'),
        tse_antes_da_urna=('ok_tse_depois_da_urna', lambda s: int((~s.astype(bool)).sum())),
        carga_nao_anterior=('ok_carga_antes', lambda s: int((~s.astype(bool)).sum())),
        fora_da_data=('ok_data_eleicao', lambda s: int((~s.astype(bool)).sum())),
        ordem_interna_invertida=('ok_ordem_urna', lambda s: int((~s.astype(bool)).sum())),
        sem_datas=('sem_datas', lambda s: int(s.astype(bool).sum()))).reset_index()
    return ex, res


# ----------------------------------------------------------------------------------------------- C4-11
def c4_11_consolidar(fontes):
    """Uniao por chave (pleito, uf, municipality, zone, section) das fontes de 'apuracao fora da urna'.
    fontes: dict nome -> DataFrame com a chave e colunas extras; devolve uma linha por secao com uma flag por fonte."""
    chave = ['pleito'] + KEY
    partes = []
    for nome, df in fontes.items():
        if df is None or df.empty:
            continue
        d = chave_int(df).drop_duplicates(chave)
        d[f'f_{nome}'] = 1
        partes.append(d)
    if not partes:
        return pd.DataFrame(columns=chave)
    out = partes[0]
    for d in partes[1:]:
        comuns = [c for c in d.columns if c in out.columns and c not in chave]
        out = out.merge(d.drop(columns=comuns), on=chave, how='outer')
    flags = [c for c in out if c.startswith('f_')]
    out[flags] = out[flags].fillna(0).astype(int)
    out['fontes'] = out[flags].apply(lambda r: ';'.join(c[2:] for c in flags if r[c] == 1), axis=1)
    return out.sort_values(chave).reset_index(drop=True)


# ----------------------------------------------------------------------------------------------- C4-12
def c4_12_proxy_trocas(logs, rotulo):
    """Secoes com mais de um log no pacote (urna intermediaria/contingencia) por UF: proxy de troca de urna."""
    d = logs.copy()
    d['n_logs'] = pd.to_numeric(d.n_logs, errors='coerce')
    d['cont'] = d.contingencia.astype(str).str.lower().isin(['true', '1']) | (d.n_logs > 1)
    g = d.groupby('uf').agg(secoes=('cont', 'size'), com_contingencia=('cont', 'sum'),
                            n_logs_2=('n_logs', lambda s: int((s == 2).sum())),
                            n_logs_3mais=('n_logs', lambda s: int((s >= 3).sum()))).reset_index()
    g['pct_contingencia'] = 100 * g.com_contingencia / g.secoes
    g['pleito'] = rotulo
    return g


def c4_12_comparar(p2022, p2026, ceft_uf):
    """Proxy 2022-t2 x 2026-t2 por UF, com a taxa CEFT (troca esperada != efetivada) de 2022-t2 e 2026-t1 nas 11 UFs."""
    a = p2022.rename(columns={c: f'{c}_2022t2' for c in p2022 if c not in ('uf', 'pleito')}).drop(columns='pleito')
    b = p2026.rename(columns={c: f'{c}_2026t2' for c in p2026 if c not in ('uf', 'pleito')}).drop(columns='pleito')
    m = a.merge(b, on='uf', how='outer')
    for eid, suf in (('P2022b', 'ceft_2022t2'), ('P2026', 'ceft_2026t1')):
        c = ceft_uf[ceft_uf.eid == eid][['uf', 'swaps', 'swap_pct']].rename(
            columns={'swaps': f'swaps_{suf}', 'swap_pct': f'swap_pct_{suf}'})
        m = m.merge(c, on='uf', how='left')
    m['razao_2026_2022'] = m.pct_contingencia_2026t2 / m.pct_contingencia_2022t2
    m['proxy_menos_ceft_2022t2_pp'] = m.pct_contingencia_2022t2 - m.swap_pct_ceft_2022t2
    return m.sort_values('uf').reset_index(drop=True)


# ----------------------------------------------------------------------------------------------- C4-13
def _quantis(d, col, flags):
    r = d.groupby('uf').agg(secoes=(col, 'size'), com_datas=(col, 'count'),
                            p01=(col, lambda s: s.quantile(0.01)), p50=(col, 'median'),
                            p90=(col, lambda s: s.quantile(0.9)), p99=(col, lambda s: s.quantile(0.99)),
                            maximo=(col, 'max'), minimo=(col, 'min'),
                            **{f: (f, 'sum') for f in flags}).reset_index()
    tot = {'uf': 'TOTAL', 'secoes': len(d), 'com_datas': int(d[col].notna().sum()), 'p01': d[col].quantile(0.01),
           'p50': d[col].median(), 'p90': d[col].quantile(0.9), 'p99': d[col].quantile(0.99), 'maximo': d[col].max(),
           'minimo': d[col].min()} | {f: int(d[f].sum()) for f in flags}
    return pd.concat([r, pd.DataFrame([tot])], ignore_index=True)


def c4_13_atrasos(df, dia):
    """Minutos entre emissao do BU (ou encerramento) na urna e recebimento no TSE, corrigindo o fuso do municipio.
    df: uf, municipality, dt_emissao_bu, dt_encerramento, dt_bu_recebido, desloc_h. Devolve (por UF, extremos)."""
    d = df.copy()
    d['desloc_h'] = d.desloc_h.fillna(0)
    off = pd.to_timedelta(d.desloc_h, unit='h')
    d['min_emissao_rec'] = (d.dt_bu_recebido - (d.dt_emissao_bu + off)).dt.total_seconds() / 60
    d['min_enc_rec'] = (d.dt_bu_recebido - (d.dt_encerramento + off)).dt.total_seconds() / 60
    dia = pd.Timestamp(dia)
    d['recebido_dia_seguinte'] = d.dt_bu_recebido.notna() & (d.dt_bu_recebido.dt.normalize() > dia)
    d['recebido_antes_emissao'] = d.min_emissao_rec < 0
    d['recebido_antes_encerramento'] = d.min_enc_rec < 0
    d['min_base'] = d.min_emissao_rec.where(d.min_emissao_rec.notna(), d.min_enc_rec)
    d['medida'] = np.where(d.min_emissao_rec.notna(), 'emissao->recebimento', 'encerramento->recebimento')
    flags = ['recebido_dia_seguinte', 'recebido_antes_emissao', 'recebido_antes_encerramento']
    res = _quantis(d, 'min_base', flags)
    p99 = d.min_base.quantile(0.99)
    ext = d[d[flags].any(axis=1) | (d.min_base >= max(p99, 600))].copy()
    return res, ext.sort_values('min_base', ascending=False)


# ----------------------------------------------------------------------------------------------- C4-14
def c4_14_exterior_2026(sec, nomes):
    """Exterior 2026: soma dos BUs por pais (municipality = codigo do pais) sem referencia oficial no HD."""
    z = sec[sec.uf == 'ZZ'].copy()
    merge = z['_merge'].astype(str)
    z['t1_presente'] = (merge != 'right_only').astype(int)
    t1c = [c for c in z if re.fullmatch(r't1_v\d+', c)]
    z['t1_validos'] = z[t1c].sum(axis=1, min_count=1)
    z['t2_validos'] = z.t2_v13 + z.t2_v22
    g = z.groupby(['uf', 'municipality']).agg(
        secoes_t1=('t1_presente', 'sum'), secoes_t2=('t2_aptos', 'size'), t1_aptos=('t1_aptos', 'sum'),
        t1_comparecimento=('t1_comparecimento', 'sum'), t1_validos=('t1_validos', 'sum'), t1_v13=('t1_v13', 'sum'),
        t1_v22=('t1_v22', 'sum'), t2_aptos=('t2_aptos', 'sum'), t2_comparecimento=('t2_comparecimento', 'sum'),
        t2_validos=('t2_validos', 'sum'), t2_v13=('t2_v13', 'sum'), t2_v22=('t2_v22', 'sum'),
        t2_branco=('t2_branco', 'sum'), t2_nulo=('t2_nulo', 'sum')).reset_index()
    g = g.merge(nomes, on=['uf', 'municipality'], how='left')
    g['status'] = f'{NOT_COMP}: sem resultado oficial do exterior no HD (-u.json de ZZ nao capturado)'
    return g


# ----------------------------------------------------------------------------------------------- orquestracao
def _t():
    return time.perf_counter()


def _rec(resumo, cid, status, numeros, arquivos, motivo=''):
    resumo[cid] = {'status': status, 'motivo': motivo, 'numeros_chave': numeros, 'arquivos': arquivos}


def roda_c4_01(resumo, achados, cache):
    sec = carrega_secoes_2026()
    mun = carrega_mun_todos()
    m, uf, res = c4_01_reconciliar_2026(sec, mun)
    cols_m = ['uf', 'municipality', 'municipality_name', 'status', 'origem', 'fonte', 't1_secoes', 't1_secoes_of',
              'secoes_so_t2', 't2_secoes', 't2_secoes_of', 'bate_t1', 'bate_t2'] + \
             [c for c in m if c.startswith('dif_')] + \
             [c for c in m if (c.startswith('t1_') or c.startswith('t2_')) and c not in
              ('t1_secoes', 't1_secoes_of', 't2_secoes', 't2_secoes_of')]
    a1 = csv_out('C4-01_conferencia_municipios_completa.csv', m[cols_m])
    a2 = csv_out('C4-01_conferencia_uf.csv', uf)
    a3 = csv_out('C4-01_municipios_com_diferenca.csv', m[(m.status != 'OK') & (m.fonte == 'both')][cols_m])
    f1, f2, f3 = c4_01_invariante_secao(sec)
    nq = quarentena('C4-01', f1[KEY + ['t1_comparecimento', 't1_branco', 't1_nulo']],
                    'T1: soma dos votaveis != comparecimento')
    nq += quarentena('C4-01', f2[KEY + ['t2_comparecimento', 't2_v13', 't2_v22', 't2_branco', 't2_nulo']],
                     'T2: v13+v22+branco+nulo != comparecimento')
    nq += quarentena('C4-01', f3[KEY + ['t1_aptos', 't1_comparecimento', 't2_aptos', 't2_comparecimento']],
                     'comparecimento > aptos')
    canal = pd.read_parquet(R / 'segundo_turno_2026' / 'bu_todos_decodificados.parquet',
                            columns=KEY + ['aux_status', 'e6258_aptos', 'e6258_comparecimento', 'e6258_c1_v13',
                                           'e6258_c1_v22', 'e6258_c1_branco', 'e6258_c1_nulo'])
    dif, rc, n_both, n_igual = c4_01_canais_2026_t2(sec, chave_int(canal))
    a4 = csv_out('C4-01_canal_sistema_resultados_x_dados_abertos_uf.csv', rc)
    a5 = csv_out('C4-01_canal_sistema_resultados_x_dados_abertos_diferentes.csv', dif)
    del canal
    nums = res | {'invariante_t1_falhas': int(len(f1)), 'invariante_t2_falhas': int(len(f2)),
                  'comp_gt_aptos': int(len(f3)), 'quarentena_linhas': nq, 'canal2_secoes_comparadas': n_both,
                  'canal2_iguais': n_igual, 'canal2_diferentes': n_both - n_igual}
    _rec(resumo, 'C4-01', 'feita', nums, [a1, a2, a3, a4, a5])
    nb = m[(~m.bate_t1) & (m.fonte == 'both')]
    for r in nb.itertuples():
        d1 = {c: int(getattr(r, c)) for c in m.columns if c.startswith('dif_t1_') and getattr(r, c) != 0}
        achados.append({
            'id_sugerido': f'C4-01-{r.uf}-{r.municipality}',
            'titulo': f'{r.municipality_name} ({r.uf}) 2026 T1: soma dos BUs publicados difere do total oficial; '
                      f'{int(r.secoes_so_t2)} secao(oes) do municipio sem bu.dat no zip do T1',
            'pleito': '2026-t1', 'cargo': 'presidente', 'uf': r.uf,
            'escopo': f'1 municipio, {int(r.secoes_so_t2)} secao(oes) de {int(r.t1_secoes_of)}',
            'tipo': 'reconciliacao soma dos BUs x total oficial (campo a campo)',
            'efeito': f'diferencas T1 (BU - oficial): {d1}; T2 fecha em todos os campos com a secao incluida',
            'efeito_num': float(r.dif_t1_comparecimento),
            'materialidade_min': int(abs(r.dif_t1_comparecimento)), 'materialidade_max': int(abs(r.dif_t1_comparecimento)),
            'margem_referencia': 'margem nacional do 1o turno (milhoes de votos); a diferenca e local',
            'artefato_excluido': 'as 2 secoes right_only entraram na agregacao de T2 (que fecha em todos os municipios); '
                                 'a diferenca de T1 persiste e coincide com a ausencia do bu.dat no zip '
                                 '(casos_sem_prova_completa.csv) e com os 2 imgbusa.dat republicados',
            'controles': 'os demais municipios fecham em todos os campos em T1 e T2; 2022/2018/2014 em C4-04',
            'hipoteses': ['secao apurada em separado (SA) pela junta: totalizada sem BU de urna publicado',
                          'BU publicado em outro membro do zip (imgbusa.dat), nao decodificado'],
            'status_sugerido': 'PLAUSIVEL-EXPLICAVEL',
            'dados_externos': 'ata da junta / decisao do TRE-MG sobre as secoes e o conteudo do imgbusa.dat',
            'fonte': [a1, a3], 'prioridade': 2})
    nb2 = m[(~m.bate_t2) & (m.fonte == 'both')]
    if len(nb2):
        achados.append({'id_sugerido': 'C4-01-T2', 'titulo': f'2026 T2: {len(nb2)} municipio(s) nao fecham mesmo com as '
                        'secoes so-T2 incluidas', 'pleito': '2026-t2', 'cargo': 'presidente',
                        'uf': ';'.join(sorted(set(nb2.uf))), 'escopo': f'{len(nb2)} municipios', 'tipo': 'reconciliacao',
                        'efeito': 'ver CSV', 'materialidade_min': 0,
                        'materialidade_max': int(nb2.dif_t2_comparecimento.abs().sum()), 'status_sugerido': 'INEXPLICADO',
                        'fonte': [a3], 'prioridade': 1})
    del sec, mun, m
    gc.collect()


def roda_c4_02(resumo, achados, cache):
    cfg = R / 'segundo_turno_2026' / 'config'
    esp = pd.concat([ler_cs_json(cfg / f'{uf}-cs.json', uf) for uf in UFS if (cfg / f'{uf}-cs.json').exists()],
                    ignore_index=True)
    out_files, nums = [], {'cs_json_secoes': int(len(esp)), 'cs_json_ufs': int(esp.uf.nunique())}
    stems_t1 = stems_bu_urna('2026-t1')
    for pleito in ('2026-t1', '2026-t2'):
        st = stems_t1 if pleito == '2026-t1' else stems_bu_urna('2026-t2')
        inv = st[st[['municipality', 'zone', 'section']].isna().any(axis=1)]
        quarentena('C4-02', inv, f'{pleito}: stem sem 13 digitos finais numericos')
        m = c4_02_esperadas_x_recebidas(esp, st)
        por_uf = m.groupby('uf').agg(esperadas=('fonte', lambda f: int((f != 'right_only').sum())),
                                     bu=('fonte', lambda f: int((f != 'left_only').sum())),
                                     esperada_sem_bu=('fonte', lambda f: int((f == 'left_only').sum())),
                                     bu_sem_esperada=('fonte', lambda f: int((f == 'right_only').sum()))).reset_index()
        m = m.merge(esp[KEY + ['municipio', 'recebido_em', 'agregada', 'secao_principal']], on=KEY, how='left')
        # a lista oficial inclui secoes agregadas em outra urna (campo 'nsp' = secao principal, sem hora de recebimento):
        # essas nao geram BU proprio; o que sobra e 'esperada, com recebimento registrado, sem BU no zip'
        m['classe'] = np.select([m.status == 'OK', m.agregada.fillna(False).astype(bool), m.recebido_em.notna()],
                                ['OK', 'agregada em outra secao (nsp): sem BU proprio',
                                 'esperada com recebimento registrado e sem BU no zip'],
                                'esperada sem recebimento e sem BU no zip')
        m.loc[m.status == 'BU no zip sem secao na lista oficial', 'classe'] = 'BU no zip sem secao na lista oficial'
        agreg = m[m.agregada.fillna(False).astype(bool)]
        por_uf_cls = m[m.status != 'OK'].groupby(['uf', 'classe']).size().unstack(fill_value=0).reset_index()
        por_uf = por_uf.merge(por_uf_cls, on='uf', how='left')
        out_files.append(csv_out(f'C4-02_{pleito}_esperadas_x_bu_por_uf.csv', por_uf))
        out_files.append(csv_out(f'C4-02_{pleito}_secoes_fora.csv', m[(m.status != 'OK') & ~m.agregada.fillna(False).astype(bool)]))
        out_files.append(csv_out(f'C4-02_{pleito}_secoes_agregadas_cs_json.csv', agreg[KEY + ['municipio', 'secao_principal']]))
        reais = m[m.classe.str.startswith('esperada')]
        com_rec = reais[reais.classe.str.startswith('esperada com recebimento')]
        nums[pleito] = {'bu_stems': int(len(st)), 'stems_chave_invalida': int(len(inv)),
                        'esperada_sem_bu': int((m.status == 'esperada sem BU no zip').sum()),
                        'bu_sem_esperada': int((m.status == 'BU no zip sem secao na lista oficial').sum()),
                        'classes': m[m.status != 'OK'].classe.value_counts().to_dict(),
                        'agregadas_na_lista': int(len(agreg)), 'agregadas_com_bu_proprio': int((agreg.status == 'OK').sum()),
                        'esperadas_com_recebimento_sem_bu_por_uf': {k: int(v) for k, v in com_rec.groupby('uf').size().items()},
                        'esperadas_sem_recebimento_sem_bu_por_uf': {k: int(v) for k, v in reais[~reais.index.isin(com_rec.index)]
                                                                    .groupby('uf').size().items()},
                        'fora': reais[KEY + ['municipio', 'recebido_em', 'classe']].astype(str).to_dict('records')}
        if pleito == '2026-t2':
            del st
    sec = carrega_secoes_2026()
    mun = carrega_mun_todos()
    cm = c4_02_contagem_municipio(sec, mun)
    out_files.append(csv_out('C4-02_contagem_secoes_municipio_x_oficial.csv', cm[cm.status != 'OK']))
    nums['municipios_contagem_difere'] = cm[(cm.status != 'OK') & (cm.fonte == 'both')][
        ['uf', 'municipality', 'municipality_name', 't1', 't1_secoes', 't2', 't2_secoes']].to_dict('records')
    nums['municipios_contagem_ok'] = int((cm.status == 'OK').sum())
    del sec, mun
    # membros dos zips 2026-t1 (remote-inventory.json): stems sem bu.dat e o que tem
    sem_bu, inv_nums = [], {}
    for uf in UFS:
        raiz = raiz_inventario(uf, '2026-t1')
        if raiz is None:
            inv_nums[uf] = 'sem remote-inventory.json'
            continue
        g = membros_por_stem(membros_inventario(raiz))
        s = g[~g.tem_bu].copy()
        s['uf'] = uf
        inv_nums[uf] = {'stems': int(len(g)), 'sem_bu': int(len(s)), 'apuracao_separada': int(g.apuracao_separada.sum())}
        sem_bu.append(s)
        del g
        gc.collect()
    sb = pd.concat(sem_bu, ignore_index=True) if sem_bu else pd.DataFrame(columns=['uf', 'stem', 'tipos', 'apuracao_separada'])
    if len(sb):
        ch = chaves_de_stems(sb.stem, 'x')[['municipality', 'zone', 'section']]
        sb = pd.concat([sb.reset_index(drop=True), ch], axis=1)
        sb = sb.merge(esp[KEY + ['municipio']], on=KEY, how='left')
        t1 = chave_int(stems_t1[KEY]).assign(secao_tem_bu_em_outro_stem=1)
        sb = sb.merge(t1, on=KEY, how='left')
        sb['secao_tem_bu_em_outro_stem'] = sb.secao_tem_bu_em_outro_stem.fillna(0).astype(int)
    else:
        sb['secao_tem_bu_em_outro_stem'] = 0
    out_files.append(csv_out('C4-02_2026-t1_stems_sem_bu_no_zip.csv', sb))
    nums['2026-t1_inventario'] = {
        'ufs_com_inventario': sum(1 for v in inv_nums.values() if isinstance(v, dict)),
        'stems_sem_bu_total': int(len(sb)),
        'stems_sem_bu_com_apuracao_separada': int(sb.apuracao_separada.astype(bool).sum()) if len(sb) else 0,
        'stems_sem_bu_cuja_secao_tem_bu_em_outro_stem': int(sb.secao_tem_bu_em_outro_stem.sum()) if len(sb) else 0,
        'tipos_presentes': sb.tipos.value_counts().to_dict() if len(sb) else {}, 'por_uf': inv_nums}
    nums['2026-t2_inventario'] = ('nao ha remote-inventory.json para 2026-t2 (download por blocos sem indice gravado); os '
                                  '29 stems com RDV e sem BU do inventario de contagem nao podem ser nomeados sem o '
                                  'indice do zip')
    inv = pd.read_csv(REL / 'disco' / 'inventario_zips_pais.csv', sep=';', encoding='utf-8-sig')
    inv = inv[inv.eleicao.isin(['2026-t1', '2026-t2'])].copy()
    inv['stems_sem_bu'] = inv.urnas - inv.bu_arquivos
    inv = inv[inv.stems_sem_bu > 0][['eleicao', 'uf', 'urnas', 'bu_arquivos', 'rdv_arquivos', 'log_arquivos', 'assinatura_arquivos',
                                    'stems_sem_bu']]
    out_files.append(csv_out('C4-02_inventario_stems_sem_bu_por_uf.csv', inv))
    nums['inventario_stems_sem_bu_por_uf'] = inv.astype(str).to_dict('records')
    _rec(resumo, 'C4-02', 'parcial', nums, out_files,
         motivo='lista oficial (cs.json, com agregadas) x BU feita nos dois turnos; os stems extras (RDV sem BU) so sao nomeados onde ha '
                'remote-inventory.json (11 UFs de 2026-t1); nas outras UFs ficam contados por UF pelo inventario dos zips')
    for pleito in ('2026-t1', '2026-t2'):
        reais = nums[pleito]['esperadas_com_recebimento_sem_bu_por_uf']
        sem_rec = nums[pleito]['esperadas_sem_recebimento_sem_bu_por_uf']
        if reais:
            n = sum(reais.values())
            achados.append({
                'id_sugerido': f'C4-02-{pleito}-esperada-sem-bu',
                'titulo': f'{pleito}: {n} secoes da lista oficial com hora de recebimento registrada e sem BU no zip de dados abertos '
                          f'(por UF: {reais}); outras {sum(sem_rec.values())} listadas sem recebimento e sem BU ({sem_rec})',
                'pleito': pleito, 'cargo': 'presidente', 'uf': ';'.join(sorted(reais)), 'escopo': f'{n} secoes',
                'tipo': 'BU esperado x recebido (lista oficial do sistema de resultados x zip de urna)',
                'efeito': 'a totalizacao registra recebimento da secao, mas o zip publicado nao traz bu.dat (inventario: ZZ tem 29 stems '
                          'com rdv.dat e sem bu/log/assinatura nos dois turnos; MG 2026-t1 tem 2 stems de apuracao em separado)',
                'efeito_num': float(n), 'materialidade_min': 0, 'materialidade_max': int(n * 500),
                'margem_referencia': 'teto de 500 eleitores por secao; o resultado oficial dessas secoes nao esta no HD (exterior) '
                                     'ou esta so no total municipal (MG)',
                'artefato_excluido': 'secoes agregadas (nsp) separadas; chave int; cs.json e o indice oficial do 2o turno; inventario '
                                     'de contagem por UF dos zips confere (ZZ 1.310 urnas x 1.281 BUs)',
                'controles': '2022-t1: ZZ 99 stems extras / 103 secoes do BWEB sem .bu; 2022-t2: ZZ 33 / 34 (C4-03)',
                'hipoteses': ['secoes do exterior apuradas por sistema de apuracao / BU digitado (sem arquivo de urna), com RDV publicado',
                              'urna sem transmissao de arquivos de resultado (so o RDV chegou ao zip)'],
                'status_sugerido': 'PLAUSIVEL-EXPLICAVEL', 'dados_externos': 'resultado oficial do exterior por secao (-u.json ZZ) e CEFT '
                'de ZZ 2026; atas das juntas',
                'fonte': [str(OUT / f'C4-02_{pleito}_secoes_fora.csv')], 'prioridade': 2})
    if len(sb):
        n_sa = int(sb.apuracao_separada.astype(bool).sum())
        achados.append({
            'id_sugerido': 'C4-02-stems-sem-bu-2026t1',
            'titulo': f'2026 T1: {len(sb)} stems nos zips de urna sem bu.dat ({n_sa} com membros de apuracao em separado)',
            'pleito': '2026-t1', 'cargo': 'presidente', 'uf': ';'.join(sorted(set(sb.uf))), 'escopo': f'{len(sb)} stems',
            'tipo': 'BU esperado x recebido (membros do zip)',
            'efeito': f'tipos de membros presentes nesses stems: {nums["2026-t1_inventario"]["tipos_presentes"]}',
            'efeito_num': float(len(sb)), 'materialidade_min': 0, 'materialidade_max': 0,
            'margem_referencia': 'nenhuma: sao arquivos, nao votos',
            'artefato_excluido': 'nomes lidos do remote-inventory.json (indice do zip), nao de pastas; chave = 13 digitos finais',
            'controles': '2022-t1: 116 stems sem BU no inventario de contagem (nao nomeados nas 17 UFs sem indice); 2026-t2: 29',
            'hipoteses': ['secao apurada em separado pela junta (busa/logsa/sa.vsc)',
                          'urna de contingencia que nao concluiu, com RDV/log publicados'],
            'status_sugerido': 'PLAUSIVEL-EXPLICAVEL',
            'dados_externos': 'indice (central directory) dos zips 2026-t2 e 2022 das 17 UFs; CEFT 2026-t2',
            'fonte': [out_files[-1]], 'prioridade': 2})


def roda_c4_03(resumo, achados, cache):
    con = duck()
    out_files, nums = [], {}
    cols = KEY + ['aptos', 'comp', 'votos_nominais', 'branco', 'nulo', 'cd_tipo_urna', 'ds_tipo_urna', 'agregadas', 'urna',
                  'dt_bu_recebido', 'junta']
    for pleito in ('2022-t1', '2022-t2'):
        sec, _ = tabela_secoes_bweb(pleito, 'PRESIDENTE', con, cols=cols)
        stems = stems_bu_urna(pleito)
        fora, por_uf = c4_03_bweb_x_bu(sec, stems)
        pref = {uf: prefixo_stems(g) for uf, g in stems.groupby('uf')}
        del sec, stems
        gc.collect()
        fora['stem_esperado'] = [stem_esperado(pref.get(r.uf), r.municipality, r.zone, r.section) for r in fora.itertuples()]
        ufs_fora = sorted(set(fora.uf))
        cefts = [carrega_ceft(pleito, uf, con) for uf in ufs_fora if uf in UFS11]
        cefts = [c for c in cefts if c is not None]
        if cefts:
            fora = fora.merge(pd.concat(cefts, ignore_index=True).drop(columns='pleito'), on=KEY, how='left')
        else:
            fora['origem_voto'] = np.nan
        fora['ceft'] = np.where(fora.uf.isin(UFS11), np.where(fora.origem_voto.notna(), 'secao no CEFT', 'secao ausente do CEFT'),
                                f'{NOT_COMP}: UF sem CEFT no HD')
        ufs_inv = [uf for uf in ufs_fora if raiz_inventario(uf, pleito) is not None]
        membros = []
        for uf in ufs_inv:
            g = membros_por_stem(membros_inventario(raiz_inventario(uf, pleito)))
            alvo = set(fora.loc[fora.uf == uf, 'stem_esperado'].dropna())
            membros.append(g[g.stem.isin(alvo)].assign(uf=uf))
            del g
            gc.collect()
        mb = pd.concat(membros, ignore_index=True) if membros else \
            pd.DataFrame(columns=['uf', 'stem', 'tipos', 'tem_rdv', 'tem_log', 'tem_assinatura', 'apuracao_separada'])
        mb = mb.rename(columns={'stem': 'stem_esperado', 'tipos': 'membros_no_zip'})
        fora = fora.merge(mb[['uf', 'stem_esperado', 'membros_no_zip', 'tem_rdv', 'tem_log', 'tem_assinatura', 'apuracao_separada']],
                          on=['uf', 'stem_esperado'], how='left')
        fora['membros_no_zip'] = np.where(fora.uf.isin(ufs_inv), fora.membros_no_zip.fillna('nenhum membro com esse stem'),
                                          f'{NOT_COMP}: UF sem remote-inventory.json')
        pz = R / 'assinaturas' / pleito / 'ZZ'
        if pz.exists() and (fora.uf == 'ZZ').any():
            vs = {membro_stem_tipo(e.name)[0] for e in pz.iterdir() if e.is_file()}
            fora['assinatura_zz_no_hd'] = np.where(fora.uf == 'ZZ', fora.stem_esperado.isin(vs).map({True: 'sim', False: 'nao'}), '')
        falhas = pd.read_csv(REL / 'integridade' / 'falhas.csv', encoding='utf-8-sig')
        falhas = falhas[falhas.eleicao == pleito][['urna', 'tipo']].rename(columns={'urna': 'stem_esperado', 'tipo': 'integridade_falha'})
        # stem_esperado pode vir todo vazio (float NaN) quando nenhuma seção faltou: junta como texto
        fora['stem_esperado'] = fora['stem_esperado'].astype(object).where(fora['stem_esperado'].notna(), None).astype('string')
        falhas['stem_esperado'] = falhas['stem_esperado'].astype('string')
        fora = fora.merge(falhas.drop_duplicates('stem_esperado'), on='stem_esperado', how='left')
        vc = [votos_candidatos_secoes(pleito, 'PRESIDENTE', uf, g[['municipality', 'zone', 'section']], con)
              for uf, g in fora[fora.status == SEM_BU].groupby('uf')]
        vc = pd.concat(vc, ignore_index=True) if vc else pd.DataFrame()
        if len(vc):
            piv = vc.pivot_table(index=KEY, columns='numero', values='votos', aggfunc='sum').reset_index()
            piv.columns = [c if c in KEY else f'v{c}' for c in piv.columns]
            fora = fora.merge(piv, on=KEY, how='left')
        out_files.append(csv_out(f'C4-03_{pleito}_bweb_x_bu_por_uf.csv', por_uf))
        out_files.append(csv_out(f'C4-03_{pleito}_secoes_sem_par.csv', fora.sort_values(['status'] + KEY)))
        sem = fora[fora.status == SEM_BU]
        nums[pleito] = {'bweb_secoes': int(por_uf.bweb.sum()), 'bu_zip': int(por_uf.bu_zip.sum()),
                        'bweb_sem_bu': int(len(sem)), 'bu_sem_bweb': int((fora.status == SEM_BWEB).sum()),
                        'bweb_sem_bu_por_uf': sem.groupby('uf').size().to_dict(),
                        'comparecimento_sem_bu': int(sem.comp.sum()), 'aptos_sem_bu': int(sem.aptos.sum()),
                        'anuladas_entre_sem_bu': int((sem.cd_tipo_urna.fillna(1) != 1).sum()),
                        'agregadas_entre_sem_bu': int(sem.agregadas.notna().sum()),
                        'ceft_origem': sem.origem_voto.value_counts(dropna=False).to_dict(),
                        'ceft': sem.ceft.value_counts().to_dict(),
                        'membros_no_zip': sem.membros_no_zip.value_counts(dropna=False).to_dict(),
                        'assinatura_zz_no_hd': sem.assinatura_zz_no_hd.value_counts().to_dict() if 'assinatura_zz_no_hd' in sem else {},
                        'votos_13': int(sem.v13.sum()) if 'v13' in sem else None,
                        'votos_22': int(sem.v22.sum()) if 'v22' in sem else None,
                        'bu_sem_bweb_lista': fora[fora.status == SEM_BWEB][KEY + ['stem']].to_dict('records')}
        achados.append({
            'id_sugerido': f'C4-03-{pleito}',
            'titulo': f'{pleito}: {len(sem)} secoes do BWEB sem arquivo .bu no zip de urna ({int(sem.comp.sum())} '
                      f'comparecimentos); {nums[pleito]["bu_sem_bweb"]} .bu sem BWEB',
            'pleito': pleito, 'cargo': 'presidente',
            'uf': ';'.join(f'{k}:{v}' for k, v in sorted(nums[pleito]['bweb_sem_bu_por_uf'].items())),
            'escopo': f'{len(sem)} secoes', 'tipo': 'duas publicacoes oficiais do mesmo pleito com conjuntos de secoes diferentes',
            'efeito': f'comparecimento das secoes sem .bu: {int(sem.comp.sum())}; votos 13: {nums[pleito]["votos_13"]}, '
                      f'22: {nums[pleito]["votos_22"]}; CEFT (11 UFs): {nums[pleito]["ceft_origem"]}; membros no zip: '
                      f'{nums[pleito]["membros_no_zip"]}; anuladas: {nums[pleito]["anuladas_entre_sem_bu"]}',
            'efeito_num': float(sem.comp.sum()), 'materialidade_min': 0, 'materialidade_max': int(sem.comp.sum()),
            'margem_referencia': 'margem nacional do turno (milhoes de votos); as secoes estao totalizadas no BWEB, '
                                 'falta so o arquivo de urna',
            'artefato_excluido': 'chave municipio/zona/secao (int) nos dois lados; stem esperado montado com o prefixo real '
                                 'da UF; membros conferidos no indice do zip (UFs com inventario) e assinaturas do exterior no HD',
            'controles': '2026-t1: 2 secoes (MG) sem BU; 2026-t2: 0',
            'hipoteses': ['secao apurada em separado / sistema de apuracao (sem BU de urna)',
                          'urna RED/contingencia sem arquivo proprio', 'exterior: secoes sem arquivos de urna publicados'],
            'status_sugerido': 'PLAUSIVEL-EXPLICAVEL',
            'dados_externos': 'atas das juntas / TREs e indice dos zips das 17 UFs sem inventario',
            'fonte': out_files[-2:], 'prioridade': 2})
        del fora
        gc.collect()
    con.close()
    _rec(resumo, 'C4-03', 'feita', nums, out_files)


def roda_c4_04(resumo, achados, cache):
    con = duck()
    out_files, nums, todos_mun, todos_cand = [], {}, [], []
    for pleito in PLEITOS_PRES:
        ano, turno = pleito.split('-t')
        sec, cand = tabela_secoes_bweb(pleito, 'PRESIDENTE', con, cols=['uf', 'municipality', 'aptos', 'comp', 'abst',
                                                                        'cd_tipo_urna', 'agregadas'])
        ref = carrega_munzona(ano)
        ref = ref[ref.turno == int(turno)].drop(columns='turno')
        m = c4_04_municipios(sec, ref)
        m.insert(0, 'pleito', pleito)
        uf = c4_04_por_uf(m)
        uf.insert(0, 'pleito', pleito)
        todos_mun.append(m)
        cand = cand.copy()
        cand['numero'] = cand.numero.astype(str)
        nac = cand.groupby(['pleito', 'numero']).agg(nome=('nome', 'max'), votos=('votos', 'sum')).reset_index()
        nac['uf'] = 'BR (com exterior)'
        todos_cand.append(pd.concat([cand, nac], ignore_index=True))
        out_files.append(csv_out(f'C4-04_{pleito}_municipios.csv', m))
        out_files.append(csv_out(f'C4-04_{pleito}_uf.csv', uf))
        comp = m[m.fonte == 'both']
        dif = comp[comp.status != 'OK']
        tot = uf[uf.uf == 'TOTAL (com exterior)'].iloc[0]
        nums[pleito] = {'municipios_comparaveis': int(len(comp)), 'batem': int((comp.status == 'OK').sum()),
                        'nao_comparaveis': int((m.fonte != 'both').sum()),
                        'nao_comparaveis_lista': m[m.fonte != 'both'][['uf', 'municipality', 'municipio', 'fonte', 'secoes']].to_dict('records'),
                        'municipios_com_diferenca': dif[['uf', 'municipality', 'municipio', 'dif_aptos', 'dif_comp', 'dif_abst',
                                                         'anuladas', 'agregadas']].to_dict('records'),
                        'total_aptos_bu': int(tot.aptos_bu), 'total_aptos_oficial': int(tot.aptos_of),
                        'total_comp_bu': int(tot.comp_bu), 'total_comp_oficial': int(tot.comp_of),
                        'total_abst_bu': int(tot.abst_bu), 'total_abst_oficial': int(tot.abst_of),
                        'votos_nacionais': {f'{r.numero} {r.nome}': int(r.votos) for r in nac.itertuples()}}
        for r in dif.itertuples():
            achados.append({
                'id_sugerido': f'C4-04-{pleito}-{r.uf}-{r.municipality}',
                'titulo': f'{pleito} {r.municipio} ({r.uf}): soma do BWEB difere da referencia oficial (aptos {int(r.dif_aptos)}, '
                          f'comparecimento {int(r.dif_comp)}, abstencoes {int(r.dif_abst)})',
                'pleito': pleito, 'cargo': 'presidente', 'uf': r.uf,
                'escopo': f'1 municipio, {int(r.secoes)} secoes ({int(r.anuladas)} anuladas, {int(r.agregadas)} agregadas)',
                'tipo': 'reconciliacao soma dos BUs (BWEB) x referencia oficial por municipio',
                'efeito': f'BU - oficial: aptos {int(r.dif_aptos)}, comparecimento {int(r.dif_comp)}, abstencoes {int(r.dif_abst)}',
                'efeito_num': float(r.dif_comp), 'materialidade_min': int(abs(r.dif_comp)), 'materialidade_max': int(abs(r.dif_comp)),
                'margem_referencia': 'margem nacional do turno; diferenca local',
                'artefato_excluido': 'uma linha por secao (max dos campos); chave int; referencia munzona do mesmo turno',
                'controles': 'demais municipios do pleito fecham; ver C4-07 (anuladas) para a origem',
                'hipoteses': ['secao anulada incluida/excluida do total oficial', 'secao agregada contada duas vezes',
                              'referencia munzona com outra regra de consolidacao'],
                'status_sugerido': 'PLAUSIVEL-EXPLICAVEL' if (r.anuladas or r.agregadas) else 'INEXPLICADO',
                'dados_externos': 'detalhe_votacao_munzona oficial do pleito e ata da junta', 'fonte': [out_files[-2]],
                'prioridade': 2})
        del sec, ref, m
        gc.collect()
    con.close()
    cache['c4_04_municipios'] = pd.concat(todos_mun, ignore_index=True)
    cand_all = pd.concat(todos_cand, ignore_index=True)
    out_files.append(csv_out('C4-04_totais_candidatos_uf_e_nacional.csv', cand_all.sort_values(['pleito', 'uf', 'numero'])))
    nums['nota'] = ('votos por candidato nacionais/UF gravados como referencia; o resultado oficial de votos por municipio '
                    '(votacao_candidato_munzona) nao esta no HD, so aptos/comparecimento/abstencoes (ref/munzona)')
    _rec(resumo, 'C4-04', 'feita', nums, out_files)


def roda_c4_05(resumo, achados, cache):
    out_files, nums = [], {}
    dups, invs = [], []
    for pleito in PLEITOS_URNA:
        st = stems_bu_urna(pleito)
        dup, inv = c4_05_stems_duplicados(st)
        dups.append(dup)
        invs.append(inv)
        nums[f'stems_{pleito}'] = {'stems': int(len(st)), 'chaves_duplicadas': int(len(dup)), 'chave_invalida': int(len(inv))}
        quarentena('C4-05', inv, f'{pleito}: stem com chave invalida')
        del st
        gc.collect()
    out_files.append(csv_out('C4-05_stems_chave_duplicada.csv', pd.concat(dups, ignore_index=True)))
    out_files.append(csv_out('C4-05_stems_chave_invalida.csv', pd.concat(invs, ignore_index=True)))
    casos, resumos = [], []
    con = duck()
    cols = ['pleito'] + KEY + ['n_urna', 'urna', 'aptos', 'aptos_min', 'comp', 'comp_min', 'abst', 'abst_min', 'votos_total',
                               'n_cargos']
    for pleito, cargo in [(p, 'PRESIDENTE') for p in PLEITOS_PRES] + [(p, 'PREFEITO') for p in PLEITOS_PREF]:
        sec, _ = tabela_secoes_bweb(pleito, cargo, con, cols=cols)
        c, r, flags = c4_05_bweb_inconsistencias(sec)
        c = c.assign(cargo=cargo)
        r = r.assign(cargo=cargo)
        casos.append(c[['pleito', 'cargo'] + KEY + cols[5:] + flags])
        resumos.append(r)
        nums[f'bweb_{pleito}_{cargo}'] = {f: int(r[f].sum()) for f in flags} | {'secoes': int(r.secoes.sum())}
        quarentena('C4-05', c[c.chave_nula][['pleito'] + KEY + ['aptos', 'comp']],
                   f'{pleito} {cargo}: chave municipio/zona/secao nula')
        quarentena('C4-05', c[c.aptos_var | c.comp_var | c.abst_var][['pleito'] + KEY + ['aptos', 'aptos_min', 'comp', 'comp_min',
                                                                                        'abst', 'abst_min']],
                   f'{pleito} {cargo}: QT_* nao constante entre as linhas da secao')
        del sec
        gc.collect()
    con.close()
    casos_all = pd.concat(casos, ignore_index=True)
    out_files.append(csv_out('C4-05_bweb_inconsistencias_casos.csv', casos_all))
    out_files.append(csv_out('C4-05_bweb_inconsistencias_por_uf.csv', pd.concat(resumos, ignore_index=True)))
    _rec(resumo, 'C4-05', 'feita', nums, out_files)
    tot_votos_ne = sum(v.get('votos_ne_comp', 0) for k, v in nums.items() if k.startswith('bweb_'))
    if tot_votos_ne:
        achados.append({'id_sugerido': 'C4-05-votos-ne-comp',
                        'titulo': f'BWEB: {tot_votos_ne} secoes com soma de votos do cargo != comparecimento',
                        'pleito': ';'.join(sorted(set(casos_all[casos_all.votos_ne_comp].pleito))), 'cargo': 'presidente/prefeito',
                        'uf': ';'.join(sorted(set(casos_all[casos_all.votos_ne_comp].uf))), 'escopo': f'{tot_votos_ne} secoes',
                        'tipo': 'invariante do BU', 'efeito': 'soma QT_VOTOS (nominais+branco+nulo) difere de QT_COMPARECIMENTO',
                        'materialidade_min': 0, 'materialidade_max': int((casos_all[casos_all.votos_ne_comp].votos_total -
                                                                          casos_all[casos_all.votos_ne_comp].comp).abs().sum()),
                        'status_sugerido': 'INEXPLICADO', 'fonte': [out_files[-2]], 'prioridade': 2})


def roda_c4_07(resumo, achados, cache):
    con = duck()
    secs = []
    cols = ['pleito'] + KEY + ['voting_place', 'aptos', 'comp', 'abst', 'cd_tipo_urna', 'ds_tipo_urna', 'urna', 'agregadas',
                               'junta', 'votos_nominais', 'branco', 'nulo', 'dt_bu_recebido']
    for pleito, cargo in [(p, 'PRESIDENTE') for p in PLEITOS_PRES] + [(p, 'PREFEITO') for p in PLEITOS_PREF]:
        sec, _ = tabela_secoes_bweb(pleito, cargo, con, cols=cols)
        secs.append(sec[sec.cd_tipo_urna.fillna(APURADA) != APURADA].assign(cargo=cargo))
        del sec
    con.close()
    anul = pd.concat(secs, ignore_index=True)
    mun_conf = carrega_c4_04_municipios(cache)
    if mun_conf is None:
        mun_conf = pd.DataFrame(columns=['pleito', 'uf', 'municipality', 'municipio', 'dif_aptos', 'dif_comp', 'status'])
    stems = []
    for p in sorted(set(anul.pleito) & set(PLEITOS_URNA)):
        st = stems_bu_urna(p)
        stems.append(st.merge(chave_int(anul[anul.pleito == p][KEY]), on=KEY, how='inner'))
        del st
        gc.collect()
    stems = pd.concat(stems, ignore_index=True) if stems else None
    out = c4_07_anuladas(anul, mun_conf, stems)
    a = csv_out('C4-07_secoes_anuladas.csv', out)
    nums = {'secoes_nao_apuradas': int(len(out)),
            'por_pleito': {f'{k[0]} {k[1]}': int(v) for k, v in out.groupby(['pleito', 'ds_tipo_urna']).size().items()} if len(out) else {},
            'comp_no_oficial': out.comp_no_oficial.value_counts().to_dict() if len(out) else {},
            'aptos_no_oficial': out.aptos_no_oficial.value_counts().to_dict() if len(out) else {},
            'comparecimento_total': int(out.comp.sum()) if len(out) else 0,
            'casos': out[['pleito', 'uf', 'municipality', 'municipio', 'zone', 'section', 'ds_tipo_urna', 'aptos', 'comp', 'votos_nominais',
                          'branco', 'nulo', 'comp_no_oficial', 'aptos_no_oficial', 'tem_bu_no_zip']].astype(str).to_dict('records') if len(out) else []}
    _rec(resumo, 'C4-07', 'feita', nums, [a], motivo='2026 sem campo equivalente (BU binario); prefeito 2024 incluido')
    if len(out):
        achados.append({
            'id_sugerido': 'C4-07-anuladas',
            'titulo': f'{len(out)} secoes ANULADA / ANULADA E APURADA EM SEPARADO no BWEB (2014-2024); comparecimento no total '
                      f'oficial: {nums["comp_no_oficial"]}',
            'pleito': ';'.join(sorted(set(out.pleito))), 'cargo': 'presidente/prefeito', 'uf': ';'.join(sorted(set(out.uf))),
            'escopo': f'{len(out)} secoes', 'tipo': 'secoes anuladas x totais oficiais',
            'efeito': f'comparecimento somado das secoes: {nums["comparecimento_total"]}; classificacao por secao no CSV',
            'efeito_num': float(nums['comparecimento_total']), 'materialidade_min': 0,
            'materialidade_max': int(nums['comparecimento_total']),
            'margem_referencia': 'margem nacional/estadual do pleito; volume de centenas de votos',
            'artefato_excluido': 'campo lido do BWEB oficial; soma com/sem a secao x munzona',
            'controles': 'mesma regra aplicada a todos os pleitos 2014-2024',
            'hipoteses': ['anulacao por decisao da junta/TRE com votos mantidos no comparecimento',
                          'apuracao em separado com BU substituto'],
            'status_sugerido': 'PLAUSIVEL-EXPLICAVEL', 'dados_externos': 'decisoes de anulacao (TREs) das secoes listadas',
            'fonte': [a], 'prioridade': 2})


def roda_c4_08(resumo, achados, cache):
    con = duck()
    out_files, nums = [], {}
    agrs, bus = [], []
    cols = ['pleito'] + KEY + ['agregadas', 'aptos', 'comp']
    pleitos = [(p, 'PRESIDENTE') for p in ('2018-t1', '2018-t2', '2022-t1', '2022-t2')] + [(p, 'PREFEITO') for p in PLEITOS_PREF]
    for pleito, cargo in pleitos:
        sec, _ = tabela_secoes_bweb(pleito, cargo, con, cols=cols)
        agr = explodir_agregadas(sec)
        bp = c4_08_agregadas_com_bu_proprio(agr, sec)
        bp['cargo'] = cargo
        bus.append(bp)
        agrs.append(agr.assign(cargo=cargo))
        nums[f'{pleito}_{cargo}'] = {'secoes_principais_com_agregadas': int(sec.agregadas.notna().sum()),
                                     'secoes_agregadas': int(len(agr)), 'agregadas_com_bu_proprio': int(bp.bu_proprio.sum()),
                                     'agregada_nao_numerica': int(agr.agregada.isna().sum())}
        quarentena('C4-08', agr[agr.agregada.isna()], f'{pleito} {cargo}: DS_AGREGADAS nao numerica')
        del sec
    con.close()
    bp_all = pd.concat(bus, ignore_index=True)
    out_files.append(csv_out('C4-08_agregadas_com_bu_proprio.csv', bp_all[bp_all.bu_proprio == 1]))
    out_files.append(csv_out('C4-08_agregadas_por_pleito_uf.csv', pd.concat(agrs, ignore_index=True).groupby(
        ['pleito', 'cargo', 'uf']).agg(principais=('section', 'nunique'), agregadas=('agregada', 'size')).reset_index()))
    perf = [pd.read_parquet(R / 'perfil' / '2022' / f'{uf}.parquet', columns=['municipality', 'zone', 'section', 'voters']).assign(uf=uf)
            for uf in UFS11 if (R / 'perfil' / '2022' / f'{uf}.parquet').exists()]
    if perf:
        perfil = pd.concat(perf, ignore_index=True)
        del perf
        res = []
        for pleito in ('2022-t1', '2022-t2'):
            sec, _ = tabela_secoes_bweb(pleito, 'PRESIDENTE', cols=cols)
            sec = sec[sec.uf.isin(UFS11)]
            res.append(c4_08_aptos_vs_perfil(explodir_agregadas(sec), sec, perfil))
            del sec
        res = pd.concat(res, ignore_index=True)
        out_files.append(csv_out('C4-08_2022_aptos_principal_x_perfil.csv', res))
        nums['2022_aptos_x_perfil'] = {'principais': int(len(res)), 'leitura': res.leitura.value_counts().to_dict(),
                                       'dif_mediana_principal_mais_agregadas': float(res.dif_aptos_vs_principal_mais_agregadas.median()),
                                       'dif_mediana_so_principal': float(res.dif_aptos_vs_principal.median()),
                                       'agregadas_sem_perfil': int(res.agregadas_sem_perfil.sum())}
        del perfil
    _rec(resumo, 'C4-08', 'feita', nums, out_files)
    n_bp = int(bp_all.bu_proprio.sum())
    if n_bp:
        sel = bp_all[bp_all.bu_proprio == 1]
        achados.append({'id_sugerido': 'C4-08-agregada-com-bu', 'titulo': f'{n_bp} secoes agregadas tambem aparecem com BU proprio',
                        'pleito': ';'.join(sorted(set(sel.pleito))), 'cargo': 'presidente/prefeito', 'uf': ';'.join(sorted(set(sel.uf))),
                        'escopo': f'{n_bp} secoes', 'tipo': 'dupla contagem potencial',
                        'efeito': 'secao listada em DS_AGREGADAS de outra secao e com linha propria no BWEB', 'materialidade_min': 0,
                        'materialidade_max': int(sel.comp.sum()), 'status_sugerido': 'INEXPLICADO', 'fonte': [out_files[0]], 'prioridade': 1})


def roda_c4_10(resumo, achados, cache):
    out_files = []
    fech = pd.read_parquet(REL / 'verificacoes' / 'fechamento_2026t2' / 'secoes_fechamento_recebimento.parquet',
                           columns=KEY + ['voting_place', 'receipt_date', 'receipt_time', 'abertura', 'encerramento_local',
                                          'recebimento', 'desloc_h', 'encerramento', 'cenario', 'v13', 'v22', 'min_rec_apos_enc'])
    antes = c4_10_recebimento_antes(chave_int(fech))
    del fech
    uv = pd.read_csv(REL / 'verificacoes' / 'ultimo_voto_2026t2' / 'ultimo_voto_por_secao.csv', sep=';', decimal=',',
                     encoding='utf-8-sig', usecols=['uf', 'municipality', 'zone', 'section', 'path', 'votos_log', 'erro_log',
                                                    'primeiro_voto', 'ultimo_voto', 'log_why'])
    antes = antes.merge(chave_int(uv), on=KEY, how='left')
    del uv
    hab = pd.read_parquet(R / 'padroes_2t' / 'hab_2026_t2.parquet', columns=KEY + ['stem', 'opening', 'closing', 'comparecimento_bu'])
    antes = antes.merge(hab, on=KEY, how='left')
    del hab
    canal = pd.read_parquet(R / 'segundo_turno_2026' / 'bu_todos_decodificados.parquet',
                            columns=KEY + ['aux_status', 'hash_time', 'receipt_time', 'n_hashes', 'log_name'])
    antes = antes.merge(chave_int(canal).rename(columns={'receipt_time': 'receipt_time_canal2'}), on=KEY, how='left')
    del canal
    antes.insert(0, 'eleicao', '2026-t2')
    out_files.append(csv_out('C4-10_2026-t2_recebido_antes_do_encerramento.csv', antes))
    con = duck()
    p = (REL / 'verificacoes' / 'relogio_por_secao.parquet').as_posix()
    ex = con.execute(f"""select eleicao, uf, municipio municipality, nome_municipio, zona zone, secao section, local, urna, carga,
 abertura, encerramento, emissao_bu, recebido_tse, noronha, min_urna_ate_tse, ok_data_eleicao, ok_carga_antes, ok_ordem_urna
 from read_parquet('{p}') where ok_tse_depois_da_urna = false and sem_datas = false""").df()
    res = con.execute(f"""select eleicao, uf, count(*) secoes,
 sum(case when ok_tse_depois_da_urna = false then 1 else 0 end) tse_antes_da_urna,
 sum(case when ok_carga_antes = false then 1 else 0 end) carga_nao_anterior,
 sum(case when ok_data_eleicao = false then 1 else 0 end) fora_da_data,
 sum(case when ok_ordem_urna = false then 1 else 0 end) ordem_interna_invertida,
 sum(case when sem_datas then 1 else 0 end) sem_datas
 from read_parquet('{p}') group by 1, 2 order by 1, 2""").df()
    con.close()
    ex = chave_int(ex)
    extras = []
    for (ele, uf), g in ex.groupby(['eleicao', 'uf']):
        raiz = raiz_inventario(uf, ele) or (R / 'estados' / uf / ele)
        ps = raiz / 'analysis' / 'sections.parquet'
        if ps.exists():
            s = pd.read_parquet(ps, columns=['municipality', 'zone', 'section', 'member', 'vote_events', 'attendance', 'closure_bu',
                                             'first_vote', 'last_vote', 'manual_sequence_votes'])
            s = s.merge(g[['municipality', 'zone', 'section']], on=['municipality', 'zone', 'section'])
            extras.append(s.assign(eleicao=ele, uf=uf))
    if extras:
        ex = ex.merge(pd.concat(extras, ignore_index=True), on=['eleicao', 'uf', 'municipality', 'zone', 'section'], how='left')
    else:
        ex['last_vote'] = None
    integ = pd.read_parquet(REL / 'integridade' / 'integridade_todas_urnas.parquet',
                            columns=['eleicao', 'uf', 'urna', 'log_nome', 'assinado_em', 'bu_assinatura_ok', 'log_hash_ok', 'cert_cn'])
    integ = integ[integ.eleicao.isin(set(ex.eleicao))].copy()
    integ['chave13'] = integ.urna.str[-13:]
    ex['chave13'] = [f'{m:05d}{z:04d}{s:04d}' for m, z, s in zip(ex.municipality, ex.zone, ex.section)]
    ex = ex.merge(integ.drop(columns='urna').rename(columns={'log_nome': 'log_nome_integridade'}).drop_duplicates(['eleicao', 'uf', 'chave13']),
                  on=['eleicao', 'uf', 'chave13'], how='left')
    del integ
    out_files.append(csv_out('C4-10_relogio_tse_antes_da_urna_dossie.csv', ex.sort_values(['eleicao', 'uf', 'municipality', 'zone', 'section'])))
    out_files.append(csv_out('C4-10_relogio_excecoes_por_uf.csv', res))
    nums = {'2026-t2_recebido_antes_encerramento': int(len(antes)),
            '2026-t2_casos': antes[KEY + ['encerramento', 'recebimento', 'min_rec_apos_enc', 'ultimo_voto', 'votos_log', 'comparecimento_bu',
                                        'aux_status', 'hash_time']].astype(str).to_dict('records'),
            'relogio_tse_antes_da_urna': int(len(ex)), 'relogio_por_eleicao': {k: int(v) for k, v in ex.groupby('eleicao').size().items()},
            'relogio_casos': ex[['eleicao', 'uf', 'nome_municipio', 'municipality', 'zone', 'section', 'emissao_bu', 'recebido_tse',
                                 'min_urna_ate_tse', 'encerramento', 'last_vote', 'assinado_em', 'noronha']].astype(str).to_dict('records'),
            'carga_nao_anterior_total': int(res.carga_nao_anterior.sum()), 'fora_da_data_total': int(res.fora_da_data.sum()),
            'ordem_interna_invertida_total': int(res.ordem_interna_invertida.sum())}
    _rec(resumo, 'C4-10', 'parcial', nums, out_files,
         motivo='dossie tabular (recebimento, encerramento, ultimo voto do log ja parseado, assinatura, canal 2) feito; a leitura dos '
                'logs dessas urnas (eventos de transmissao/retransmissao, hora de emissao do BU no log) fica para a passada de logs')
    achados.append({
        'id_sugerido': 'C4-10-tse-antes-urna',
        'titulo': f'BU recebido pelo TSE antes do encerramento/emissao registrado pela urna: {len(antes)} secoes (2026-t2, cs.json) + '
                  f'{len(ex)} (relogio BWEB/sistema de resultados 2022-t2, 2026-t1, 2026-t2)',
        'pleito': '2022-t2;2026-t1;2026-t2', 'cargo': 'presidente', 'uf': ';'.join(sorted(set(antes.uf) | set(ex.uf))),
        'escopo': f'{len(antes) + len(ex)} secoes (com repeticao entre fontes)', 'tipo': 'inconsistencia temporal urna x totalizacao',
        'efeito': f'min_rec_apos_enc minimo {antes.min_rec_apos_enc.min():.2f} min (2026-t2); relogio: min_urna_ate_tse minimo '
                  f'{ex.min_urna_ate_tse.min():.1f} min', 'efeito_num': float(antes.min_rec_apos_enc.min()) if len(antes) else 0.0,
        'materialidade_min': 0, 'materialidade_max': int(antes.v13.sum() + antes.v22.sum()) if len(antes) else 0,
        'margem_referencia': 'nenhum voto em disputa: a diferenca e de minutos entre relogios',
        'artefato_excluido': 'fuso corrigido (desloc_h por municipio; Noronha marcado); recebimento do cs.json e do BWEB; encerramento do BU',
        'controles': '2022-t2, 2026-t1 e 2026-t2 com a mesma ordem de grandeza (unidades de secoes, minutos)',
        'hipoteses': ['relogio da urna adiantado/atrasado em minutos', 'retransmissao: hora de recebimento da primeira transmissao'],
        'status_sugerido': 'PLAUSIVEL-EXPLICAVEL', 'dados_externos': 'log de cada urna (passada) e historico de recebimentos do TSE',
        'fonte': out_files[:2], 'prioridade': 3})


def roda_c4_11(resumo, achados, cache):
    con = duck()
    out_files = []
    ce_rows, ce_res = [], []
    for pdir in sorted((R / 'ceft').iterdir()):
        for uf in UFS11:
            c = carrega_ceft(pdir.name, uf, con)
            if c is None:
                continue
            ce_res.append(c.groupby(['pleito', 'uf', 'origem_voto']).agg(secoes=('section', 'size'), trocas=('troca_urna', 'sum')).reset_index())
            ce_rows.append(c[c.origem_voto != 'Urna Eletrônica'])
            del c
    ce_res = pd.concat(ce_res, ignore_index=True) if ce_res else pd.DataFrame()
    ce = pd.concat(ce_rows, ignore_index=True) if ce_rows else pd.DataFrame(columns=['pleito'] + KEY + ['origem_voto'])
    out_files.append(csv_out('C4-11_ceft_origem_voto_por_pleito_uf.csv', ce_res))
    juntas = []
    cols = ['pleito'] + KEY + ['junta', 'turma', 'comp', 'aptos', 'ds_tipo_urna']
    for pleito, cargo in [(p, 'PRESIDENTE') for p in ('2018-t1', '2018-t2', '2022-t1', '2022-t2')] + [(p, 'PREFEITO') for p in PLEITOS_PREF]:
        sec, _ = tabela_secoes_bweb(pleito, cargo, con, cols=cols)
        juntas.append(sec[sec.junta.notna() & (sec.junta != -1)])
        del sec
    con.close()
    junta = pd.concat(juntas, ignore_index=True)
    sa = pd.DataFrame(columns=['pleito'] + KEY)
    s = csv_in('C4-02_2026-t1_stems_sem_bu_no_zip.csv')
    if s is not None and len(s):
        sa = s[s.apuracao_separada.astype(str).str.lower() == 'true'][KEY + ['stem', 'tipos']].assign(pleito='2026-t1')
        sem_bu = [s[KEY + ['stem']].assign(pleito='2026-t1')]
    else:
        sem_bu = [sa]
    for pleito in ('2022-t1', '2022-t2'):
        s = csv_in(f'C4-03_{pleito}_secoes_sem_par.csv')
        if s is not None:
            s = s[s.status == SEM_BU]
            sem_bu.append(s[KEY + [c for c in ['comp', 'aptos', 'origem_voto', 'membros_no_zip', 'ds_tipo_urna'] if c in s]].assign(pleito=pleito))
    sem_bu = pd.concat(sem_bu, ignore_index=True)
    anul = csv_in('C4-07_secoes_anuladas.csv')
    anul = anul[['pleito'] + KEY + ['ds_tipo_urna', 'comp']] if anul is not None else pd.DataFrame(columns=['pleito'] + KEY)
    fontes = {'ceft_origem_nao_urna': ce[['pleito'] + KEY + ['origem_voto', 'urna_esperada', 'urna_efetivada', 'divergencia']],
              'bweb_junta_apuradora': junta, 'zip_apuracao_separada': sa, 'secao_sem_bu_no_zip': sem_bu, 'bweb_anulada': anul}
    cons = c4_11_consolidar(fontes)
    out_files.append(csv_out('C4-11_secoes_apuradas_fora_da_urna.csv', cons))
    flags = [c for c in cons if c.startswith('f_')]
    por = cons.groupby(['pleito', 'uf']).agg(secoes=('section', 'size'), **{f: (f, 'sum') for f in flags}).reset_index() if len(cons) else pd.DataFrame()
    out_files.append(csv_out('C4-11_por_pleito_uf.csv', por))
    nums = {'secoes_consolidadas': int(len(cons)), 'por_fonte': {c[2:]: int(cons[c].sum()) for c in flags},
            'ceft_origem_nao_urna_por_pleito': {f'{k[0]} | {k[1]}': int(v) for k, v in ce.groupby(['pleito', 'origem_voto']).size().items()},
            'sistema_apuracao_secoes': ce[ce.origem_voto.str.contains('apura', case=False, na=False)][['pleito'] + KEY].to_dict('records'),
            'junta_apuradora_secoes': int(len(junta)), 'junta_por_pleito': {k: int(v) for k, v in junta.groupby('pleito').size().items()},
            'ceft_2012_2016': 'sem cabecalho (c0..c26): nao lido', 'combinacoes_de_fontes': cons.fontes.value_counts().to_dict() if len(cons) else {}}
    _rec(resumo, 'C4-11', 'feita', nums, out_files, motivo='11 UFs para CEFT/junta; 2026-t2 sem CEFT; CEFT 2012-2016 sem cabecalho nao lido')
    achados.append({
        'id_sugerido': 'C4-11-fora-da-urna',
        'titulo': f'{len(cons)} secoes com indicio de apuracao fora da urna ou sem BU de urna (2014-2026), por fonte: {nums["por_fonte"]}',
        'pleito': ';'.join(sorted(set(cons.pleito))) if len(cons) else '', 'cargo': 'presidente/prefeito',
        'uf': ';'.join(sorted(set(cons.uf))) if len(cons) else '', 'escopo': f'{len(cons)} secoes',
        'tipo': 'lista consolidada de secoes recontadas/apuradas fora da urna', 'efeito': f'combinacoes de fontes: {nums["combinacoes_de_fontes"]}',
        'efeito_num': float(len(cons)), 'materialidade_min': 0, 'materialidade_max': int(pd.to_numeric(cons.get('comp'), errors='coerce').fillna(0).sum()) if 'comp' in cons else 0,
        'margem_referencia': 'margens nacionais/estaduais dos pleitos; volume de centenas a milhares de votos por pleito',
        'artefato_excluido': 'chave int unica; fontes marcadas separadamente (CEFT, junta, membros SA, sem .bu, anulada)',
        'controles': 'todos os pleitos com a mesma regra; 2026-t2 so a fonte sem-BU (0 secoes)',
        'hipoteses': ['apuracao pela junta por defeito de urna/midia', 'RED/contingencia'], 'status_sugerido': 'PLAUSIVEL-EXPLICAVEL',
        'dados_externos': 'atas das juntas apuradoras e CEFT das 16 UFs restantes + 2026-t2', 'fonte': out_files[1:3], 'prioridade': 2})


def roda_c4_12(resumo, achados, cache):
    out_files = []
    lx = pd.read_csv(ROOT / 'build' / 'log_x_bu_reconferido.csv', sep=';', encoding='utf-8-sig')
    p26 = c4_12_proxy_trocas(lx[['uf', 'n_logs', 'contingencia']], '2026-t2 (log_x_bu_reconferido)')
    b22 = pd.read_parquet(R / 'janelas_horario' / 'bins_2022.parquet', columns=['uf', 'n_logs', 'contingencia'])
    p22 = c4_12_proxy_trocas(b22, '2022-t2 (bins_2022)')
    del b22
    b26 = pd.read_parquet(R / 'janelas_horario' / 'bins_2026.parquet', columns=['uf', 'n_logs', 'contingencia'])
    p26b = c4_12_proxy_trocas(b26, '2026-t2 (bins_2026)')
    del b26
    ceft_uf = pd.read_csv(REL / 'fechamento_e_trocas' / 'trocas_por_estado.csv', sep=';', decimal=',', encoding='utf-8-sig')
    comp = c4_12_comparar(p22, p26, ceft_uf)

    def linha(nome, a, b):
        return {'uf': nome, 'secoes_2022t2': int(a.secoes.sum()), 'com_contingencia_2022t2': int(a.com_contingencia.sum()),
                'pct_contingencia_2022t2': 100 * a.com_contingencia.sum() / a.secoes.sum(), 'secoes_2026t2': int(b.secoes.sum()),
                'com_contingencia_2026t2': int(b.com_contingencia.sum()), 'pct_contingencia_2026t2': 100 * b.com_contingencia.sum() / b.secoes.sum()}
    tot = pd.DataFrame([linha('BR', p22, p26), linha('11 UFs CEFT', p22[p22.uf.isin(UFS11)], p26[p26.uf.isin(UFS11)]) |
                        {'swaps_ceft_2022t2': comp.swaps_ceft_2022t2.sum(), 'swaps_ceft_2026t1': comp.swaps_ceft_2026t1.sum()}])
    comp = pd.concat([comp, tot], ignore_index=True)
    comp['razao_2026_2022'] = comp.pct_contingencia_2026t2 / comp.pct_contingencia_2022t2
    out_files.append(csv_out('C4-12_proxy_trocas_por_uf_2022t2_x_2026t2.csv', comp))
    out_files.append(csv_out('C4-12_proxy_bins_2026_x_log_x_bu.csv', p26b.merge(p26, on='uf', suffixes=('_bins', '_logxbu'))))
    lx['dif'] = pd.to_numeric(lx.log_completo, errors='coerce') - pd.to_numeric(lx.bu, errors='coerce')
    inc = lx[(lx.dif != 0) | lx.dif.isna()]
    out_files.append(csv_out('C4-12_2026-t2_log_diferente_do_bu.csv', inc))
    nums = {'2026-t2_secoes': int(p26.secoes.sum()), '2026-t2_com_contingencia': int(p26.com_contingencia.sum()),
            '2026-t2_pct': float(100 * p26.com_contingencia.sum() / p26.secoes.sum()),
            '2022-t2_secoes': int(p22.secoes.sum()), '2022-t2_com_contingencia': int(p22.com_contingencia.sum()),
            '2022-t2_pct': float(100 * p22.com_contingencia.sum() / p22.secoes.sum()),
            'ceft_2022t2_swaps_11ufs': int(comp.swaps_ceft_2022t2.sum()), 'ceft_2026t1_swaps_11ufs': int(comp.swaps_ceft_2026t1.sum()),
            'proxy_2022t2_11ufs': int(tot.iloc[1].com_contingencia_2022t2), 'proxy_2026t2_11ufs': int(tot.iloc[1].com_contingencia_2026t2),
            'log_diferente_do_bu_2026t2': int(len(inc)),
            'casos': inc[KEY + ['bu', 'log_antes', 'log_completo', 'n_logs', 'contingencia', 'erro']].astype(str).to_dict('records'),
            'bins_2026_x_log_x_bu_contingencia': {'bins': int(p26b.com_contingencia.sum()), 'logxbu': int(p26.com_contingencia.sum())}}
    _rec(resumo, 'C4-12', 'feita', nums, out_files, motivo='proxy pelos logs aninhados; CEFT 2026-t2 inexistente')
    r = nums['2026-t2_pct'] / nums['2022-t2_pct'] if nums['2022-t2_pct'] else float('nan')
    achados.append({
        'id_sugerido': 'C4-12-trocas-proxy',
        'titulo': f'Secoes com urna de contingencia (mais de um log no pacote): {nums["2026-t2_pct"]:.2f}% em 2026-t2 x '
                  f'{nums["2022-t2_pct"]:.2f}% em 2022-t2 (razao {r:.2f}); CEFT 2022-t2 nas 11 UFs: {nums["ceft_2022t2_swaps_11ufs"]} '
                  f'trocas x proxy {nums["proxy_2022t2_11ufs"]}',
        'pleito': '2022-t2;2026-t2', 'cargo': 'presidente', 'uf': 'todas', 'escopo': f'{nums["2026-t2_secoes"]} + {nums["2022-t2_secoes"]} secoes',
        'tipo': 'BU substituido (troca de urna) por proxy de logs',
        'efeito': 'queda da taxa de contingencia entre 2022 e 2026 (ja vista no CEFT 2022-t1 2,18% -> 2026-t1 0,61%)', 'efeito_num': float(r),
        'materialidade_min': 0, 'materialidade_max': 0, 'margem_referencia': 'nenhum voto: contagem de urnas substituidas',
        'artefato_excluido': 'mesma definicao (n_logs > 1 ou contingencia) nos dois anos; bins_2026 e log_x_bu conferidos entre si',
        'controles': '2022-t2 nacional e CEFT nas 11 UFs',
        'hipoteses': ['menos falhas de urna em 2026 (parque mais novo)', 'mudanca de procedimento (menos substituicoes)'],
        'status_sugerido': 'PLAUSIVEL-EXPLICAVEL', 'dados_externos': 'CEFT 2026-t2 e relatorio de ocorrencias de urna do TSE',
        'fonte': out_files[:1], 'prioridade': 3})


def roda_c4_13(resumo, achados, cache):
    con = duck()
    desloc = carrega_desloc()
    out_files, nums, res_all, ext_all = [], {}, [], []
    pleitos = [(p, 'PRESIDENTE') for p in ('2014-t1', '2014-t2', '2018-t1', '2022-t1', '2022-t2')] + [(p, 'PREFEITO') for p in PLEITOS_PREF]
    for pleito, cargo in pleitos:
        sec, _ = tabela_secoes_bweb(pleito, cargo, con, cols=KEY + ['dt_emissao_bu', 'dt_encerramento', 'dt_bu_recebido'])
        d = chave_int(sec).merge(desloc, on=['uf', 'municipality'], how='left')
        del sec
        if d.dt_bu_recebido.notna().sum() == 0:
            nums[pleito] = 'sem DT_BU_RECEBIDO no BWEB'
            continue
        if d.dt_emissao_bu.isna().all() and d.dt_encerramento.isna().all():
            dia = pd.Timestamp(DIA_ELEICAO[pleito])
            d['recebido_dia_seguinte'] = d.dt_bu_recebido.dt.normalize() > dia
            d['recebido_antes_do_dia'] = d.dt_bu_recebido.dt.normalize() < dia
            r = d.groupby('uf').agg(secoes=('dt_bu_recebido', 'size'), com_datas=('dt_bu_recebido', 'count'),
                                    dia_seguinte=('recebido_dia_seguinte', 'sum'), antes_do_dia=('recebido_antes_do_dia', 'sum')).reset_index()
            r.insert(0, 'pleito', pleito)
            r['medida'] = 'so data de recebimento (BWEB 2014 sem hora)'
            res_all.append(r)
            ext_all.append(d[d.recebido_dia_seguinte | d.recebido_antes_do_dia].assign(pleito=pleito, medida='data'))
            nums[pleito] = {'secoes': int(len(d)), 'dia_seguinte': int(d.recebido_dia_seguinte.sum()),
                            'antes_do_dia': int(d.recebido_antes_do_dia.sum()), 'nota': 'DT_BU_RECEBIDO so com data em 2014'}
            continue
        r, ext = c4_13_atrasos(d, DIA_ELEICAO[pleito])
        r.insert(0, 'pleito', pleito)
        r['medida'] = 'emissao->recebimento (BWEB)'
        res_all.append(r)
        ext_all.append(ext.assign(pleito=pleito))
        t = r[r.uf == 'TOTAL'].iloc[0]
        nums[pleito] = {'secoes': int(t.secoes), 'com_datas': int(t.com_datas), 'p01': float(t.p01), 'p50': float(t.p50), 'p90': float(t.p90),
                        'p99': float(t.p99), 'max': float(t.maximo), 'min': float(t.minimo), 'dia_seguinte': int(t.recebido_dia_seguinte),
                        'antes_emissao': int(t.recebido_antes_emissao), 'antes_encerramento': int(t.recebido_antes_encerramento)}
        del d
        gc.collect()
    con.close()
    f = pd.read_parquet(REL / 'verificacoes' / 'fechamento_2026t2' / 'secoes_fechamento_recebimento.parquet',
                        columns=KEY + ['encerramento', 'recebimento', 'min_rec_apos_enc', 'cenario']).rename(columns={'min_rec_apos_enc': 'min_base'})
    f['recebido_dia_seguinte'] = f.recebimento.dt.normalize() > pd.Timestamp(DIA_ELEICAO['2026-t2'])
    f['recebido_antes_encerramento'] = f.min_base < 0
    r = _quantis(f, 'min_base', ['recebido_dia_seguinte', 'recebido_antes_encerramento'])
    r.insert(0, 'pleito', '2026-t2')
    r['medida'] = 'encerramento->recebimento (cs.json)'
    res_all.append(r)
    nums['2026-t2'] = {'secoes': int(len(f)), 'p01': float(f.min_base.quantile(0.01)), 'p50': float(f.min_base.median()),
                       'p90': float(f.min_base.quantile(0.9)), 'p99': float(f.min_base.quantile(0.99)), 'max': float(f.min_base.max()),
                       'dia_seguinte': int(f.recebido_dia_seguinte.sum()), 'antes_encerramento': int((f.min_base < 0).sum()),
                       'medida': 'encerramento->recebimento'}
    ext_all.append(f[f.recebido_dia_seguinte | (f.min_base < 0) | (f.min_base >= max(f.min_base.quantile(0.99), 600))].assign(pleito='2026-t2'))
    out_files.append(csv_out('C4-13_atraso_emissao_recebimento_por_uf.csv', pd.concat(res_all, ignore_index=True)))
    out_files.append(csv_out('C4-13_secoes_extremas.csv', pd.concat(ext_all, ignore_index=True)))
    nums['nota'] = ('2022/2024: emissao do BU -> DT_BU_RECEBIDO (fuso do municipio corrigido com desloc_h de fechamento_2026t2); 2026-t2: '
                    'encerramento -> recebimento do cs.json (a emissao do BU ocorre poucos minutos apos o encerramento); 2018: BWEB sem '
                    'DT_BU_RECEBIDO; 2014: so a data')
    _rec(resumo, 'C4-13', 'feita', nums, out_files)
    n22 = nums.get('2022-t2', {}) if isinstance(nums.get('2022-t2'), dict) else {}
    p26 = nums['2026-t2']['p50']
    achados.append({
        'id_sugerido': 'C4-13-atraso-recebimento',
        'titulo': f'Mediana entre a urna encerrar/emitir o BU e o TSE receber: 2026-t2 {p26:.1f} min (encerramento->recebimento) x '
                  f'2022-t2 {n22.get("p50", float("nan")):.1f} min (emissao->recebimento)',
        'pleito': '2022-t2;2026-t2', 'cargo': 'presidente', 'uf': 'todas',
        'escopo': f'{nums["2026-t2"]["secoes"]} + {n22.get("secoes", 0)} secoes', 'tipo': 'funil de recebimento (contexto)',
        'efeito': f'p99 2026-t2 {nums["2026-t2"]["p99"]:.0f} min x 2022-t2 {n22.get("p99", float("nan")):.0f} min; recebidos no dia seguinte: '
                  f'2026-t2 {nums["2026-t2"]["dia_seguinte"]}, 2022-t2 {n22.get("dia_seguinte", 0)}',
        'efeito_num': float(p26 - n22.get('p50', 0)), 'materialidade_min': 0, 'materialidade_max': 0,
        'margem_referencia': 'nenhum voto: tempo de transmissao',
        'artefato_excluido': 'fuso por municipio; medidas diferentes (emissao x encerramento) explicitadas; 2014 so data',
        'controles': '2022-t1/t2, 2024-t1/t2', 'hipoteses': ['prorrogacao e fila de transmissao em 2026-t2', 'transmissao em lote por local'],
        'status_sugerido': 'EXPLICADO', 'dados_externos': 'historico de recebimentos por secao do TSE (detalhe_votacao_secao)',
        'fonte': out_files[:1], 'prioridade': 3})


def roda_c4_14(resumo, achados, cache):
    out_files = []
    sec = carrega_secoes_2026()
    cfg = R / 'segundo_turno_2026' / 'config' / 'ZZ-cs.json'
    nomes = ler_cs_json(cfg, 'ZZ')[['uf', 'municipality', 'municipio']].drop_duplicates() if cfg.exists() else \
        pd.DataFrame(columns=['uf', 'municipality', 'municipio'])
    g = c4_14_exterior_2026(sec, nomes)
    out_files.append(csv_out('C4-14_exterior_2026_por_pais.csv', g))
    tot = g[['secoes_t1', 'secoes_t2', 't1_aptos', 't1_comparecimento', 't1_v13', 't1_v22', 't2_aptos', 't2_comparecimento', 't2_v13', 't2_v22']].sum()
    nums = {'2026_paises': int(len(g)), '2026_totais': {k: int(v) for k, v in tot.items()}}
    del sec
    m = carrega_c4_04_municipios(cache)
    if m is not None:
        zz = m[m.uf == 'ZZ']
        out_files.append(csv_out('C4-14_exterior_2022_2018_2014_por_pais.csv', zz))
        nums['2014_2018_2022_zz'] = {p: {'paises_comparaveis': int(((zz.pleito == p) & (zz.fonte == 'both')).sum()),
                                        'batem': int(((zz.pleito == p) & (zz.status == 'OK')).sum()),
                                        'nao_comparaveis': int(((zz.pleito == p) & (zz.fonte != 'both')).sum()),
                                        'dif_comp_total': int(zz[(zz.pleito == p) & (zz.fonte == 'both')].dif_comp.sum()),
                                        'dif_aptos_total': int(zz[(zz.pleito == p) & (zz.fonte == 'both')].dif_aptos.sum())}
                                    for p in sorted(set(zz.pleito))}
    for pleito in ('2022-t1', '2022-t2'):
        s = csv_in(f'C4-03_{pleito}_secoes_sem_par.csv')
        if s is not None:
            s = s[(s.uf == 'ZZ') & (s.status == SEM_BU)]
            nums[f'{pleito}_zz_sem_bu'] = {'secoes': int(len(s)), 'comparecimento': int(s.comp.sum()), 'aptos': int(s.aptos.sum()),
                                           'anuladas': int((s.cd_tipo_urna.fillna(1) != 1).sum()),
                                           'assinatura_no_hd': s.assinatura_zz_no_hd.value_counts().to_dict() if 'assinatura_zz_no_hd' in s else {},
                                           'comparecimento_zero': int((s.comp == 0).sum()),
                                           'paises': s.municipality.nunique()}
    _rec(resumo, 'C4-14', 'parcial', nums, out_files,
         motivo='2026: sem resultado oficial do exterior no HD (NOT_COMPARABLE, contagens documentadas); 2014/2018/2022: aptos/comparecimento '
                'por pais conferidos com munzona (ver C4-04)')


def roda_c4_15(resumo, achados, cache):
    con = duck()
    out_files, nums = [], {}
    for pleito in PLEITOS_PREF:
        sec, cand = tabela_secoes_bweb(pleito, 'PREFEITO', con, cols=['pleito'] + KEY + ['aptos', 'comp', 'abst', 'cd_tipo_urna', 'ds_tipo_urna',
                                                                                        'agregadas', 'urna', 'dt_bu_recebido', 'votos_nominais',
                                                                                        'branco', 'nulo'])
        stems = stems_bu_urna(pleito)
        ufs_bweb = sorted(set(sec.uf))
        fora, por_uf = c4_03_bweb_x_bu(sec.drop(columns=['pleito', 'votos_nominais', 'branco', 'nulo', 'abst']), stems[stems.uf.isin(ufs_bweb)])
        pref = {uf: prefixo_stems(g) for uf, g in stems.groupby('uf')}
        fora['stem_esperado'] = [stem_esperado(pref.get(r.uf), r.municipality, r.zone, r.section) for r in fora.itertuples()]
        n_stems = int(len(stems))
        del stems
        cefts = [carrega_ceft(pleito, uf, con) for uf in ufs_bweb]
        cefts = [c for c in cefts if c is not None]
        if cefts:
            ce = pd.concat(cefts, ignore_index=True)
            fora = fora.merge(ce.drop(columns='pleito'), on=KEY, how='left')
            ce_res = ce.groupby(['uf', 'origem_voto']).agg(secoes=('section', 'size'), trocas=('troca_urna', 'sum')).reset_index()
            ce_res.insert(0, 'pleito', pleito)
            out_files.append(csv_out(f'C4-15_{pleito}_ceft_origem_trocas.csv', ce_res))
            nums[f'{pleito}_ceft'] = {'secoes': int(len(ce)), 'trocas': int(ce.troca_urna.sum()), 'origem': ce.origem_voto.value_counts().to_dict()}
            del ce
        falhas = pd.read_csv(REL / 'integridade' / 'falhas.csv', encoding='utf-8-sig')
        falhas = falhas[falhas.eleicao == pleito][['urna', 'tipo']].rename(columns={'urna': 'stem_esperado', 'tipo': 'integridade_falha'})
        # stem_esperado pode vir todo vazio (float NaN) quando nenhuma seção faltou: junta como texto
        fora['stem_esperado'] = fora['stem_esperado'].astype(object).where(fora['stem_esperado'].notna(), None).astype('string')
        falhas['stem_esperado'] = falhas['stem_esperado'].astype('string')
        fora = fora.merge(falhas.drop_duplicates('stem_esperado'), on='stem_esperado', how='left')
        g = chave_int(sec).groupby(['uf', 'municipality']).agg(
            secoes=('aptos', 'size'), aptos=('aptos', 'sum'), comp=('comp', 'sum'), abst=('abst', 'sum'),
            votos_nominais=('votos_nominais', 'sum'), branco=('branco', 'sum'), nulo=('nulo', 'sum'),
            anuladas=('cd_tipo_urna', lambda s: int((s.fillna(1) != 1).sum()))).reset_index()
        g['status'] = f'{NOT_COMP}: resultado oficial por municipio de 2024 nao esta no HD'
        out_files.append(csv_out(f'C4-15_{pleito}_totais_municipio_bweb.csv', g))
        out_files.append(csv_out(f'C4-15_{pleito}_bweb_x_bu_por_uf.csv', por_uf))
        out_files.append(csv_out(f'C4-15_{pleito}_secoes_sem_par.csv', fora))
        nums[pleito] = {'ufs_bweb': ufs_bweb, 'bweb_secoes': int(por_uf.bweb.sum()), 'bu_zip_nas_ufs_bweb': int(por_uf.bu_zip.sum()),
                        'bweb_sem_bu': int((fora.status == SEM_BU).sum()), 'bu_sem_bweb': int((fora.status == SEM_BWEB).sum()),
                        'secoes_sem_par': fora[KEY + ['status', 'comp', 'ds_tipo_urna']].astype(str).to_dict('records'),
                        'stems_total_pleito': n_stems, 'municipios_bweb': int(len(g)),
                        'votos_candidatos_uf': int(len(cand))}
        del sec, fora
        gc.collect()
    con.close()
    _rec(resumo, 'C4-15', 'parcial', nums, out_files, motivo='soma por municipio gravada mas sem referencia oficial 2024 no HD (NOT_COMPARABLE)')


def roda_pendentes(resumo):
    _rec(resumo, 'C4-06', 'nao_feita', {}, [], motivo='depende da passada pesada de BUs: ler bu_raw de research/segundo_turno_2026/bu/<UF>.parquet '
         '(14 UFs) e de research/bu_urna/2026-t2/<UF>/part-*.parquet, calcular SHA-256 por secao nos dois canais, comparar com o campo hash '
         'do aux.json, listar diferencas e cruzar com aux_status Recebida (16.015) e com contingencia (n_logs > 1)')
    _rec(resumo, 'C4-09', 'nao_feita', {}, [], motivo='depende da passada pesada de logs: reler com auditabr.logs.read_log(merge=True) os ~3.400 '
         'logs de 2022-t2 das secoes com vote_events != attendance em research/estados/<UF>/2022-t2/analysis/sections.parquet (771 log maior, '
         '2.643 log menor), dedupe por primeira linha, classificar (urna trocada, log duplicado, evento nao classificado, diferenca real) e '
         'repetir em 2024')


CHECAGENS = ['C4-01', 'C4-02', 'C4-03', 'C4-04', 'C4-05', 'C4-07', 'C4-08', 'C4-10', 'C4-11', 'C4-12', 'C4-13', 'C4-14', 'C4-15']
RUNNERS = {'C4-01': roda_c4_01, 'C4-02': roda_c4_02, 'C4-03': roda_c4_03, 'C4-04': roda_c4_04, 'C4-05': roda_c4_05,
           'C4-07': roda_c4_07, 'C4-08': roda_c4_08, 'C4-10': roda_c4_10, 'C4-11': roda_c4_11, 'C4-12': roda_c4_12,
           'C4-13': roda_c4_13, 'C4-14': roda_c4_14, 'C4-15': roda_c4_15}


def _grava_estado(resumo, achados):
    (OUT / 'C4_resumo.json').write_text(json.dumps({'camada': 'C4', 'protocolo': 'v1.0', 'parser_version': PARSER_VERSION,
                                                    'checagens': resumo}, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    (OUT / 'C4_achados.json').write_text(json.dumps(achados, ensure_ascii=False, indent=1, default=str), encoding='utf-8')


def main(ids=None):
    ids = ids or CHECAGENS
    OUT.mkdir(parents=True, exist_ok=True)
    resumo, achados, cache = {}, [], {}
    p_res, p_ach = OUT / 'C4_resumo.json', OUT / 'C4_achados.json'
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
        old = OUT / 'quarentena_C4.csv'
        if old.exists():
            q = pd.concat([pd.read_csv(old, sep=';', encoding='utf-8-sig', dtype=str), q], ignore_index=True).drop_duplicates()
        q.to_csv(old, **CSV)
    print(json.dumps({k: v['status'] for k, v in resumo.items()}, ensure_ascii=False))


if __name__ == '__main__':
    main([a for a in sys.argv[1:] if a.startswith('C4-')] or None)
