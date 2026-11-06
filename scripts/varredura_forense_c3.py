"""Varredura forense — camada C3 (cronologia e processo da seção): checagens leves sobre tabelas já existentes.

Protocolo: relatorios/verificacoes/varredura_forense/PROTOCOLO.md v1.0. Mapa: mapa/mapa_C3.json.
Checagens feitas aqui (ids do mapa):
  C3-01 linha do tempo por seção (carga, abertura, 1º voto, último voto, encerramento, emissão, assinatura, recebimento)
        e ordem esperada; 11 UFs em 2022-T1/T2, 2024-T1/T2, 2026-T1 e país em 2026-T2; ordem só do BU no país (2018, 2022)
  C3-02 assinatura × emissão × encerramento × recebimento por geração de urna e UF (deriva relativa do relógio)
  C3-07 encerramento × último voto e abertura × primeiro voto (gaps, caudas, com/sem troca de urna)
  C3-03 mesma urna em mais de uma seção (BWEB, CEFT, certificado da urna)
  C3-06 mínimo físico derivado dos atendimentos (tempo de cabine e de habilitação): piso empírico e seções com excesso
  C3-09 ligamentos/reinícios nos logs de contingência já extraídos (research/contingencia)
  C3-15 BUs recebidos antes das 19h em 2026-T2 e carimbos do sistema de resultados (recebimento × hash_time)
  C3-08 gap longo último voto → encerramento e primeiro voto tardio em 2026-T2 (só a parte com parquet existente)
  C3-13 controle 2022 para pausas (bins de 15 min) nos grupos das seções destoantes (só a parte com parquet existente)
Ficam para as passadas pesadas (releitura de logs/BUs): C3-04, C3-05, C3-10, C3-11, C3-12, C3-14, C3-16.

Saídas: relatorios/verificacoes/varredura_forense/C3/ (CSV com ';' e vírgula decimal; parquet com recibo .json ao lado)
e C3_resumo.json. Quarentena: research/varredura_forense/quarentena/rows-C3-<checagem>.json + quarentena_C3-<checagem>.csv.
Nada aqui indica irregularidade por si só: é descrição de diferenças, ausências e limites ("sinalização não é acusação").
Uso: python scripts/varredura_forense_c3.py [C3-01 C3-02 ...]   (sem argumentos roda todas, em série, um processo filho por
checagem; C3-01 roda cada pleito num processo filho). Memória: cada processo fica abaixo de 500 MB (DuckDB com limite,
leituras por lote/coluna, textos em 'str' do arrow); --mesmo-processo desliga os processos filhos das checagens.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / 'research'
REL = ROOT / 'relatorios'
OUT = REL / 'verificacoes' / 'varredura_forense' / 'C3'
QUAR = R / 'varredura_forense' / 'quarentena'
PARSER_VERSION = 'varredura-forense-c3-1'
CSV_KW = dict(sep=';', decimal=',', encoding='utf-8-sig', index=False)
CHAVE = ['uf', 'municipality', 'zone', 'section']

DIA = {'2018-t1': '07/10/2018', '2018-t2': '28/10/2018', '2022-t1': '02/10/2022', '2022-t2': '30/10/2022',
       '2024-t1': '06/10/2024', '2024-t2': '27/10/2024', '2026-t1': '04/10/2026', '2026-t2': '25/10/2026'}
EID_PLEITO = {'P2022': '2022-t1', 'P2022b': '2022-t2', 'M2024': '2024-t1', 'M2024b': '2024-t2', 'P2026': '2026-t1'}
PLEITO_EID = {v: k for k, v in EID_PLEITO.items()}
UFS_11 = ['BA', 'CE', 'MA', 'MG', 'PA', 'PE', 'PR', 'RJ', 'RS', 'SC', 'SP']
NORONHA = 30015  # PE, UTC-2: relógio local 1 h à frente de Brasília
MARCOS = ['carga', 'abertura', 'primeiro_voto', 'ultimo_voto', 'encerramento', 'emissao', 'assinatura', 'recebimento']
PARES = list(zip(MARCOS[:-1], MARCOS[1:]))
ESTRITO = {('carga', 'abertura')}  # carga < abertura; os demais pares admitem igualdade
GERACAO = {'AC URNA': 'UE2009-2015 (ECDSA)', 'AC UE2020': 'UE2020', 'AC UE2022': 'UE2022 (Ed521)'}
TIPOS_HAB = {0: 'biometrica', 1: 'manual_identificado', 2: 'manual_nao_associado', 3: 'manual_outro',
             4: 'sem_biometria', 5: 'outro'}
PISO_QUANTIL = 0.001  # piso empírico = p0,1 global (C3-06)
BH_ALFA = 0.05
PERIODICO_S = 1800  # 'Urna ligada' repetido a cada 30 min = mensagem periódica, não reinício (C3-09)

INDICADORES = REL / 'fiscalizacao'
INTEGRIDADE = REL / 'integridade' / 'integridade_todas_urnas.parquet'
RELOGIO = REL / 'verificacoes' / 'relogio_por_secao.parquet'
FECHAMENTO = REL / 'verificacoes' / 'fechamento_2026t2' / 'secoes_fechamento_recebimento.parquet'
ULTIMO_VOTO = REL / 'verificacoes' / 'ultimo_voto_2026t2' / 'ultimo_voto_por_secao.csv'
BINS = {'2022-t2': R / 'janelas_horario' / 'bins_2022.parquet', '2026-t2': R / 'janelas_horario' / 'bins_2026.parquet'}
BWEB = R / 'bu'
CEFT = R / 'ceft'
ATENDIMENTOS = REL / 'verificacoes' / 'cadencia' / 'atendimentos.parquet'
SECOES_CADENCIA = REL / 'verificacoes' / 'cadencia' / 'secoes_cadencia.parquet'
CONTINGENCIA = R / 'contingencia'
FREQ_BASE = REL / 'logs_exemplo' / 'verificacao_frequencia_base.csv'
TROCADAS = REL / 'fechamento_e_trocas' / 'secoes_com_urna_trocada.csv'
BU_T2 = R / 'segundo_turno_2026' / 'bu_todos_decodificados.parquet'
LOGS_SECOES = R / 'anomalias_2t' / 'logs_secoes.parquet'
SECOES_ANOM = {'2022-t2': R / 'anomalias_2t' / 'secoes_2022.parquet', '2026-t2': R / 'anomalias_2t' / 'secoes_2026.parquet'}
CONTROLE_2022 = R / 'anomalias_2t' / 'controle_2022_logs.parquet'
C2_14 = REL / 'verificacoes' / 'varredura_forense' / 'C2' / 'C2-14_resumo_por_pleito.csv'
SECOES_T1T2 = REL / 'verificacoes' / 'virada_1t_2t_2026' / 'secoes_t1_t2.parquet'

STEM_2022 = re.compile(r'^o\d{5}-(\d{5})(\d{4})(\d{4})')
STEM_2024 = re.compile(r'^o\d{5}([a-z]{2})(\d{5})(\d{4})(\d{4})', re.I)
SUFIXOS = ('-log.jez', '.logjez')
BWEB_CARGO = {'2012-t1': 'PREFEITO', '2012-t2': 'PREFEITO', '2014-t1': 'PRESIDENTE', '2014-t2': 'PRESIDENTE',
              '2016-t1': 'PREFEITO', '2016-t2': 'PREFEITO', '2018-t1': 'PRESIDENTE', '2018-t2': 'PRESIDENTE',
              '2020-t1': 'PREFEITO', '2020-t2': 'PREFEITO', '2022-t1': 'PRESIDENTE', '2022-t2': 'PRESIDENTE',
              '2024-t1': 'PREFEITO', '2024-t2': 'PREFEITO'}
# layout do CEFT 2012–2016 (TXT sem cabeçalho, colunas c0..c26) inferido por inspeção: c9 SQ_ESPERADA, c10 NR_URNA_ESPERADA,
# c15 DT_CARGA_ESPERADA, c17 SQ_EFETIVADA, c18 NR_URNA_EFETIVADA, c23 DT_CARGA_EFETIVADA, c25 CD_ORIGEM_VOTO (U)
CEFT_OLD = {'NR_URNA_ESPERADA': 'c10', 'NR_URNA_EFETIVADA': 'c18', 'DT_CARGA_URNA_EFETIVADA': 'c23', 'CD_ORIGEM_VOTO': 'c25',
            'SG_UF': 'c4', 'CD_MUNICIPIO': 'c5', 'NR_ZONA': 'c7', 'NR_SECAO': 'c8'}


# ----------------------------------------------------------------------------------------------- utilidades gerais
def con(memoria: str = '400MB'):
    c = duckdb.connect()
    c.execute(f"SET memory_limit='{memoria}'")
    c.execute('SET threads=2')
    return c


def agora():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for bloco in iter(lambda: f.read(1 << 20), b''):
            h.update(bloco)
    return h.hexdigest()


def rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(ROOT)).replace('\\', '/')
    except ValueError:
        return str(p).replace('\\', '/')


def grava_csv(df: pd.DataFrame, nome: str) -> str:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / nome
    df.to_csv(p, **CSV_KW)
    return rel(p)


def grava_parquet(df: pd.DataFrame, nome: str, inputs: list[Path]) -> str:
    """Parquet derivado com recibo <arquivo>.json ao lado {at, inputs:{caminho: sha256}, sha256, rows, bytes, parser_version}."""
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / nome
    if len(df) <= 100_000:
        df.to_parquet(p, index=False)
    else:  # em blocos de 100 mil linhas: não materializa a tabela arrow inteira (memória)
        esquema = pa.Schema.from_pandas(df.iloc[:1000], preserve_index=False)
        with pq.ParquetWriter(p, esquema) as w:
            for i in range(0, len(df), 100_000):
                w.write_table(pa.Table.from_pandas(df.iloc[i:i + 100_000], schema=esquema, preserve_index=False))
    recibo = {'at': agora(), 'inputs': {rel(i): sha256_file(i) for i in inputs if Path(i).exists()},
              'sha256': sha256_file(p), 'rows': int(len(df)), 'bytes': p.stat().st_size, 'parser_version': PARSER_VERSION}
    (OUT / (nome + '.json')).write_text(json.dumps(recibo, indent=2, ensure_ascii=False), encoding='utf-8')
    return rel(p)


def quarentena(cx: str, linhas: list[dict]) -> str | None:
    """Linhas que falham invariante: valores originais como string + reason; JSON em research/… e CSV em C3/."""
    if not linhas:
        return None
    QUAR.mkdir(parents=True, exist_ok=True)
    regs = [{k: (None if v is None or (isinstance(v, float) and np.isnan(v)) else str(v)) for k, v in r.items()}
            for r in linhas]
    (QUAR / f'rows-C3-{cx}.json').write_text(json.dumps(regs, indent=1, ensure_ascii=False), encoding='utf-8')
    return grava_csv(pd.DataFrame(regs), f'quarentena_C3-{cx}.csv')


def stem_de(nome: str) -> str:
    n = PurePosixPath(str(nome).replace('\\', '/')).name
    for s in SUFIXOS:
        if n.lower().endswith(s):
            return n[:-len(s)]
    return n


def chave_do_stem(stem: str) -> tuple[str | None, int, int, int]:
    """(uf|None, município, zona, seção) a partir do nome do pacote (o00407-<mun><zona><sec> ou o03220<uf><mun><zona><sec>)."""
    m = STEM_2024.match(stem)
    if m:
        return m.group(1).upper(), int(m.group(2)), int(m.group(3)), int(m.group(4))
    m = STEM_2022.match(stem)
    if m:
        return None, int(m.group(1)), int(m.group(2)), int(m.group(3))
    raise ValueError(stem)


def parse_dt(s: pd.Series) -> pd.Series:
    """Datas em 'YYYY-MM-DD HH:MM:SS', 'DD/MM/YYYY HH:MM:SS', 'DD/MM/YYYY HH:MM' ou 'YYYYMMDDTHHMMSS' (nulos preservados)."""
    s = s.astype('string').str.strip()
    out = pd.to_datetime(s, format='%Y-%m-%d %H:%M:%S', errors='coerce')
    for fmt in ('%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%Y%m%dT%H%M%S', '%Y-%m-%d %H:%M'):
        falta = out.isna() & s.notna()
        if not falta.any():
            break
        out = out.fillna(pd.to_datetime(s[falta], format=fmt, errors='coerce'))
    return out


def hora_no_dia(hhmmss: pd.Series, dia: str) -> pd.Series:
    """'HH:MM:SS' (hora do dia no relógio da urna) → timestamp no dia do pleito; nulo se vazio/ilegível."""
    base = pd.Timestamp(datetime.strptime(dia, '%d/%m/%Y'))
    td = pd.to_timedelta(hhmmss.astype('string').str.strip(), errors='coerce')
    return base + td


def desloc_por_municipio(df: pd.DataFrame, col='abertura', hora_ref=8) -> pd.Series:
    """Deslocamento (h) do relógio local da urna até Brasília estimado pela moda da hora de abertura por (uf, municipality):
    desloc_h = hora_ref − moda(hora da abertura). ZZ (exterior) fica nulo."""
    h = pd.to_datetime(df[col]).dt.hour
    g = pd.DataFrame({'uf': df['uf'], 'municipality': df['municipality'], 'h': h}).dropna()
    moda = g.groupby(['uf', 'municipality'])['h'].agg(lambda s: s.mode().iloc[0])
    d = (hora_ref - moda).astype(float).rename('desloc_h')
    d[d.index.get_level_values('uf') == 'ZZ'] = np.nan
    return d


def minutos(a: pd.Series, b: pd.Series) -> pd.Series:
    return (pd.to_datetime(b) - pd.to_datetime(a)).dt.total_seconds() / 60


def ler_ultimo_voto(cols_num: list[str], cols_txt: list[str] = (), extra_sql: list[str] = ()) -> pd.DataFrame:
    """ultimo_voto_por_secao.csv (497.894 linhas) via DuckDB, só as colunas pedidas (o read_csv do pandas passa de 500 MB).
    Números com vírgula decimal viram DOUBLE; chave como BIGINT; demais colunas como texto."""
    c = con('300MB')
    sel = ['uf'] + [f"CAST(CAST(replace({k}, ',', '.') AS DOUBLE) AS BIGINT) {k}" for k in ('municipality', 'zone', 'section')]
    sel += [f"TRY_CAST(replace({k}, ',', '.') AS DOUBLE) {k}" for k in cols_num]
    sel += [f'"{k}"' for k in cols_txt] + list(extra_sql)
    d = c.execute(f"SELECT {', '.join(sel)} FROM read_csv(?, delim=';', header=true, all_varchar=true)", [str(ULTIMO_VOTO)]).df()
    c.close()
    return d


# ----------------------------------------------------------------------------------------------- C3-01: linha do tempo
def ordem_marcos(df: pd.DataFrame) -> pd.DataFrame:
    """Confere carga < abertura ≤ 1º voto ≤ último voto ≤ encerramento ≤ emissão ≤ assinatura ≤ recebimento.
    Colunas de marcos ausentes ou nulas são puladas (o par passa a ser o próximo marco presente). Todos os marcos estão no
    relógio da urna, exceto 'recebimento' (servidor, Brasília): a comparação com ele usa desloc_h (urna + desloc_h = Brasília);
    sem desloc_h, o par com o recebimento fica NOT_COMPARABLE. Devolve dif_<a>_<b> (min, b − a), n_violacoes, violacoes, status.
    Acrescenta as colunas ao próprio DataFrame (sem cópia, por memória) e o devolve; contas em arrays numpy (segundos)."""
    d = df
    n = len(d)
    presentes = [m for m in MARCOS if m in d]
    desloc = d['desloc_h'].to_numpy(dtype=float) if 'desloc_h' in d else np.zeros(n)
    seg = {}
    for m in presentes:
        t = pd.to_datetime(d[m]).to_numpy(dtype='datetime64[s]')
        x = t.astype('int64').astype(float)
        x[np.isnat(t)] = np.nan
        if m == 'recebimento':
            x = x - np.nan_to_num(desloc) * 3600  # recebimento em hora da urna
        seg[m] = x
    i_receb = MARCOS.index('recebimento')
    nviol = np.zeros(n, dtype=np.int16)
    n_pares = np.zeros(n, dtype=np.int16)
    sem_fuso = np.zeros(n, dtype=bool)
    viol_txt: dict[int, list[str]] = {}
    for i, a in enumerate(presentes):
        # próximo marco presente em cada linha: o primeiro marco não nulo depois de 'a' (por linha)
        resto = presentes[i + 1:]
        if not resto:
            break
        tb = np.full(n, np.nan)
        nb = np.full(n, -1, dtype=np.int8)
        for b in resto:
            falta = np.isnan(tb) & ~np.isnan(seg[b])
            tb[falta] = seg[b][falta]
            nb[falta] = MARCOS.index(b)
        ok = ~np.isnan(seg[a]) & ~np.isnan(tb)
        dif = np.where(ok, (tb - seg[a]) / 60, np.nan)
        d[f'dif_apos_{a}'] = dif
        d[f'proximo_de_{a}'] = pd.Series(pd.Categorical.from_codes(np.where(ok, nb, -1), categories=MARCOS),
                                         index=d.index).astype('str')
        with np.errstate(invalid='ignore'):
            v = ok & ((dif <= 0) if a == 'carga' else (dif < 0))
        v_fuso = ok & (nb == i_receb) & np.isnan(desloc)
        sem_fuso |= v_fuso
        v &= ~v_fuso
        n_pares += ok
        nviol += v
        for j in np.flatnonzero(v):
            viol_txt.setdefault(int(j), []).append(f'{a}>{MARCOS[nb[j]]}')
    d['n_pares'] = n_pares.astype(np.int64)
    d['n_violacoes'] = nviol.astype(np.int64)
    vt = np.full(n, '', dtype=object)
    for j, lst in viol_txt.items():
        vt[j] = ';'.join(lst)
    d['violacoes'] = pd.Series(vt, index=d.index).astype('str')
    codigo = np.where(n_pares == 0, 0, np.where(sem_fuso, 1, 2))
    d['status'] = pd.Series(pd.Categorical.from_codes(codigo, categories=[
        'NOT_COMPARABLE: menos de dois marcos presentes', 'PARCIAL: sem fuso para comparar com o recebimento', 'comparavel']),
        index=d.index).astype('str')
    return d


def _secoes_bweb(c, pleito: str, uf: str) -> pd.DataFrame | None:
    """Marcos do BU (BWEB) por seção, projetando só as colunas necessárias (uma linha por seção)."""
    p = BWEB / pleito / f'{uf}_{BWEB_CARGO[pleito]}.parquet'
    if not p.exists():
        return None
    cols = {c_.name for c_ in pq.ParquetFile(p).schema}
    carga = 'DT_CARGA_URNA_EFETIVADA' if 'DT_CARGA_URNA_EFETIVADA' in cols else ('DT_CARGA' if 'DT_CARGA' in cols else None)
    sel = ['SG_UF AS uf', 'CAST(CD_MUNICIPIO AS BIGINT) AS municipality', 'CAST(NR_ZONA AS BIGINT) AS zone',
           'CAST(NR_SECAO AS BIGINT) AS section', 'NR_URNA_EFETIVADA AS urna']
    sel.append(f'{carga} AS carga' if carga else 'NULL AS carga')
    for col, nome in (('DT_ABERTURA', 'abertura'), ('DT_ENCERRAMENTO', 'encerramento'), ('DT_EMISSAO_BU', 'emissao'),
                      ('DT_BU_RECEBIDO', 'recebimento'), ('NR_LOCAL_VOTACAO', 'local'), ('DS_TIPO_URNA', 'tipo_urna')):
        sel.append(f'{col} AS {nome}' if col in cols else f'NULL AS {nome}')
    d = c.execute(f'SELECT DISTINCT {", ".join(sel)} FROM read_parquet(?)', [str(p)]).df()
    d = d.drop_duplicates(CHAVE)
    for col in ('carga', 'abertura', 'encerramento', 'emissao', 'recebimento'):
        d[col] = parse_dt(d[col]) if d[col].notna().any() else pd.NaT
    return d


def _integridade(c, pleito: str) -> pd.DataFrame:
    """Assinatura por urna do pleito; chave da seção tirada do nome do pacote (13 dígitos finais: município, zona, seção,
    como em chave_do_stem) e assinado_em convertido no próprio DuckDB (memória)."""
    ger = ' '.join(f"WHEN '{k}' THEN '{v}'" for k, v in GERACAO.items())
    it = c.execute(f"""SELECT uf, CAST(regexp_extract(urna, '(\\d{{5}})(\\d{{4}})(\\d{{4}})$', 1) AS BIGINT) municipality,
            CAST(regexp_extract(urna, '(\\d{{5}})(\\d{{4}})(\\d{{4}})$', 2) AS BIGINT) zone,
            CAST(regexp_extract(urna, '(\\d{{5}})(\\d{{4}})(\\d{{4}})$', 3) AS BIGINT) section,
            urna, cert_cn, CASE cadeia_ac {ger} ELSE 'sem certificado' END geracao, assinado_em,
            try_strptime(assinado_em, '%Y%m%dT%H%M%S') assinatura
            FROM read_parquet(?) WHERE eleicao = ?""", [str(INTEGRIDADE), pleito]).df()
    return it.drop_duplicates(CHAVE)[CHAVE + ['urna', 'cert_cn', 'geracao', 'assinado_em', 'assinatura']]


def _indicadores(eid: str) -> pd.DataFrame:
    """Indicadores por seção (leitor antigo) lidos em DuckDB: horários do 1º/último voto (HH:MM:SS no relógio da urna) viram
    timestamp no dia do pleito (como hora_no_dia); troca = swap, contingência ou identidade só pelo nome do arquivo."""
    p = INDICADORES / f'secoes_indicadores_{eid}.parquet'
    dia = DIA[EID_PLEITO[eid]]
    c = con('300MB')
    f = c.execute("""SELECT uf, CAST(municipality AS BIGINT) municipality, CAST(zone AS BIGINT) zone, CAST(section AS BIGINT) section,
            member, identity_status, has_log, log_complete, contingency, swap, red, clock_reversals, vote_events, attendance,
            opening_bu, closure_bu, voting_place,
            try_strptime(? || ' ' || trim(first_vote), '%d/%m/%Y %H:%M:%S') primeiro_voto,
            try_strptime(? || ' ' || trim(last_vote), '%d/%m/%Y %H:%M:%S') ultimo_voto,
            (coalesce(swap, false) OR coalesce(contingency, false) OR coalesce(identity_status = 'PARSED_FILENAME', false)) troca_urna
            FROM read_parquet(?)""", [dia, dia, str(p)]).df()
    c.close()
    return f.drop_duplicates(CHAVE)


def linha_do_tempo(pleito: str) -> tuple[pd.DataFrame, list[Path]]:
    """Monta a linha do tempo por seção de um pleito a partir do que já existe (ver cabeçalho do módulo)."""
    c = con()
    inputs = [INTEGRIDADE]
    if pleito == '2026-t2':
        fe = c.execute("""SELECT uf, CAST(municipality AS BIGINT) municipality, CAST(zone AS BIGINT) zone, CAST(section AS BIGINT) section,
            CAST(voting_place AS BIGINT) local, abertura, encerramento_local AS encerramento, recebimento, desloc_h, cenario
            FROM read_parquet(?)""", [str(FECHAMENTO)]).df()
        uv = ler_ultimo_voto(['desloc_h', 'votos_log', 'validos'], ['primeiro_voto', 'ultimo_voto'],
                             extra_sql=["regexp_extract(replace(path, chr(92), '/'), '[^/]+$') log_nome"])
        # primeiro/último voto do CSV estão em hora de Brasília: volta para o relógio da urna (− desloc_h)
        for col in ('primeiro_voto', 'ultimo_voto'):
            uv[col] = pd.to_datetime(uv[col], errors='coerce') - pd.to_timedelta(uv['desloc_h'].fillna(0), unit='h')
        bins = pd.read_parquet(BINS['2026-t2'], columns=CHAVE + ['n_logs', 'contingencia'])
        d = fe.merge(uv.drop(columns=['desloc_h']).drop_duplicates(CHAVE), on=CHAVE, how='left', indicator='tem_log')
        d['tem_log'] = d['tem_log'].eq('both')
        d = d.merge(bins.drop_duplicates(CHAVE), on=CHAVE, how='left')
        d['troca_urna'] = d['contingencia'].fillna(False).astype(bool) | d['n_logs'].fillna(1).gt(1)
        d['leitor'] = 'aninhado (04/11/2026)'
        d['carga'] = pd.NaT
        d['emissao'] = pd.NaT
        inputs += [FECHAMENTO, ULTIMO_VOTO, BINS['2026-t2']]
        del fe, uv, bins
    else:
        eid = PLEITO_EID[pleito]
        if pleito.startswith('2024'):
            partes = [x for x in (_secoes_bweb(c, pleito, uf) for uf in UFS_11) if x is not None]
            bu = pd.concat(partes, ignore_index=True)
            bu['noronha'] = bu['uf'].eq('PE') & bu['municipality'].eq(NORONHA)
            inputs += [BWEB / pleito / f'{uf}_{BWEB_CARGO[pleito]}.parquet' for uf in UFS_11]
            del partes
        else:
            bu = c.execute("""SELECT uf, CAST(municipio AS BIGINT) municipality, CAST(zona AS BIGINT) zone, CAST(secao AS BIGINT) section,
                CAST(local AS BIGINT) local, urna, carga, abertura, encerramento, emissao_bu AS emissao, recebido_tse AS recebimento,
                noronha FROM read_parquet(?) WHERE eleicao = ?""", [str(RELOGIO), pleito]).df()
            inputs.append(RELOGIO)
        bu['desloc_h'] = np.where(bu['noronha'], -1.0, 0.0)
        ind = _indicadores(eid)
        inputs.append(INDICADORES / f'secoes_indicadores_{eid}.parquet')
        d = bu.drop_duplicates(CHAVE).merge(
            ind[CHAVE + ['member', 'identity_status', 'has_log', 'log_complete', 'contingency', 'swap', 'red', 'primeiro_voto',
                         'ultimo_voto', 'clock_reversals', 'vote_events', 'attendance', 'troca_urna']],
            on=CHAVE, how='outer', indicator='fonte')
        d['tem_log'] = d['has_log'].fillna(False).astype(bool)
        d['fonte'] = d['fonte'].map({'both': 'bu+indicadores', 'left_only': 'so_bu', 'right_only': 'so_indicadores'})
        d['leitor'] = 'antigo (só logd.dat externo; em trocas, horários da última urna)'
        d['cenario'] = None
        d = d.rename(columns={'member': 'log_nome'})
        del bu, ind
    it = _integridade(c, pleito)
    d = d.merge(it, on=CHAVE, how='left', suffixes=('', '_integridade'))
    if 'urna' not in d:
        d['urna'] = d['urna_integridade']
    d['pleito'] = pleito
    d = d[[c_ for c_ in COLS_LT if c_ in d]].copy()  # só o que a linha do tempo grava
    for col in ('pleito', 'uf', 'cenario', 'geracao', 'log_nome', 'urna', 'cert_cn'):
        if col in d and d[col].dtype == object:
            d[col] = d[col].astype('str')
    d['leitor'] = d['leitor'].astype('category')  # constante por pleito
    for col in ('troca_urna', 'tem_log'):
        d[col] = d[col].astype('boolean')
    gc.collect()
    pa.default_memory_pool().release_unused()
    d = ordem_marcos(d)
    c.close()
    gc.collect()
    return d, inputs


def _quantis(s: pd.Series) -> dict:
    s = pd.to_numeric(s, errors='coerce').dropna()
    if s.empty:
        return {'n': 0}
    return {'n': int(len(s)), 'min': float(s.min()), 'p01': float(s.quantile(0.01)), 'p50': float(s.median()),
            'p99': float(s.quantile(0.99)), 'max': float(s.max()), 'negativos': int((s < 0).sum())}


def distribuicao_intervalos(d: pd.DataFrame, por: list[str]) -> pd.DataFrame:
    """Quantis de cada intervalo dif_apos_<marco> por grupo (pleito, UF, geração…)."""
    linhas = []
    cols = [c_ for c_ in d.columns if c_.startswith('dif_apos_')]
    for col in cols:  # uma coluna por vez: o groupby não copia o DataFrame inteiro por grupo (memória)
        prox = f'proximo_de_{col[9:]}'
        sub = d[por + [col, prox]]
        for chave, g in sub.groupby(por, dropna=False, observed=True):
            chave = chave if isinstance(chave, tuple) else (chave,)
            q = _quantis(g[col])
            if q['n']:
                linhas.append({**dict(zip(por, chave)), 'intervalo': col.replace('dif_apos_', 'apos_'),
                               'proximo_marco_mais_comum': g[prox].mode().iloc[0] if g[prox].notna().any() else None, **q})
        del sub
    if not linhas:
        return pd.DataFrame()
    ordem = {c_.replace('dif_apos_', 'apos_'): i for i, c_ in enumerate(cols)}
    out = pd.DataFrame(linhas)
    return out.sort_values(por + ['intervalo'], key=lambda s: s.map(ordem) if s.name == 'intervalo' else s,
                           kind='stable').reset_index(drop=True)


COLS_LT = ['pleito', 'uf', 'municipality', 'zone', 'section', 'local', 'urna', 'cert_cn', 'geracao', 'log_nome', 'cenario',
           'tem_log', 'troca_urna', 'leitor', 'carga', 'abertura', 'primeiro_voto', 'ultimo_voto', 'encerramento', 'emissao',
           'assinatura', 'recebimento', 'desloc_h']


PLEITOS_LT = ['2022-t1', '2022-t2', '2026-t1', '2024-t1', '2024-t2', '2026-t2']
TMP_C3_01 = OUT / '_tmp_C3-01'


def _c3_01_pleito(pleito: str) -> None:
    """Uma rodada de C3-01 (um pleito), feita num processo filho para que a memória volte ao sistema entre os pleitos:
    grava a linha do tempo (parquet + recibo) e os parciais em TMP_C3_01 (violações, distribuições, resumo, quarentena)."""
    TMP_C3_01.mkdir(parents=True, exist_ok=True)
    r = _c3_01_um(pleito)
    r['viol'].to_parquet(TMP_C3_01 / f'viol_{pleito}.parquet', index=False)
    r['dist'].to_parquet(TMP_C3_01 / f'dist_{pleito}.parquet', index=False)
    (TMP_C3_01 / f'res_{pleito}.json').write_text(json.dumps({k: r[k] for k in ('linha', 'quar', 'arq')}, ensure_ascii=False,
                                                             default=str), encoding='utf-8')


def c3_01() -> dict:
    """Linha do tempo por seção e ordem esperada dos marcos; ordem só do BU no país (2018 e 2022). Cada pleito roda num
    processo filho, um de cada vez (C3_MESMO_PROCESSO=1 no ambiente faz tudo no processo atual)."""
    import os
    import subprocess
    resumo, viol_all, dist, arqs, quar = [], [], [], [], []
    for pleito in PLEITOS_LT:
        if os.environ.get('C3_MESMO_PROCESSO') == '1':
            _c3_01_pleito(pleito)
        else:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), '--c3-01-pleito', pleito], check=True)
        j = json.loads((TMP_C3_01 / f'res_{pleito}.json').read_text(encoding='utf-8'))
        resumo.append(j['linha'])
        quar += j['quar']
        arqs.append(j['arq'])
        viol_all.append(pd.read_parquet(TMP_C3_01 / f'viol_{pleito}.parquet'))
        dist.append(pd.read_parquet(TMP_C3_01 / f'dist_{pleito}.parquet'))
        print(pleito, j['linha'], flush=True)
    for f in TMP_C3_01.iterdir():
        f.unlink()
    TMP_C3_01.rmdir()
    return _c3_01_fecha(resumo, viol_all, dist, arqs, quar)


def _c3_01_um(pleito: str) -> dict:
    """Corpo de C3-01 para um pleito (ver _c3_01_pleito)."""
    quar = []
    t0 = time.time()
    d, inputs = linha_do_tempo(pleito)
    cols = [c_ for c_ in COLS_LT if c_ in d] + [c_ for c_ in d.columns if c_.startswith(('dif_apos_', 'proximo_de_'))] + \
        ['n_pares', 'n_violacoes', 'violacoes', 'status']
    if list(d.columns) != cols:
        d = d[cols]
    # quarentena: marcos com ano fora do pleito (relógio reiniciado) ficam registrados com o valor original
    ano = int(DIA[pleito][-4:])
    for m in ('carga', 'abertura', 'encerramento', 'emissao', 'assinatura'):
        if m in d:
            t = pd.to_datetime(d[m])
            mask = t.notna() & (t.dt.year != ano)
            for r in d.loc[mask, CHAVE + [m]].itertuples(index=False):
                quar.append({'pleito': pleito, 'uf': r[0], 'municipality': r[1], 'zone': r[2], 'section': r[3], 'marco': m,
                             'valor': str(r[4]), 'reason': f'{m} com ano diferente do pleito (relógio da urna reiniciado?)'})
    arq = grava_parquet(d, f'C3-01_linha_do_tempo_{pleito}.parquet', inputs)
    v = d[d['n_violacoes'] > 0].copy()
    por_viol = v['violacoes'].str.split(';').explode().value_counts()
    linha = {'pleito': pleito, 'secoes': len(d), 'com_log': int(d['tem_log'].fillna(False).sum()),
             'com_assinatura': int(d['assinatura'].notna().sum()), 'com_recebimento': int(d['recebimento'].notna().sum()),
             'troca_urna': int(d['troca_urna'].fillna(False).sum()), 'comparaveis': int(d['status'].eq('comparavel').sum()),
             'parcial_sem_fuso': int(d['status'].str.startswith('PARCIAL').sum()),
             'not_comparable': int(d['status'].str.startswith('NOT_COMPARABLE').sum()),
             'secoes_com_violacao': len(v), 'violacoes_total': int(d['n_violacoes'].sum()),
             'violacoes_em_secoes_com_troca': int(v['troca_urna'].fillna(False).sum()),
             'detalhe_violacoes': json.dumps(por_viol.to_dict(), ensure_ascii=False),
             'minutos_exec': round((time.time() - t0) / 60, 2)}
    d['geracao'] = d['geracao'].fillna('sem assinatura verificada')
    d['classe'] = np.where(d['troca_urna'].fillna(False), 'com troca/contingência', 'sem troca')
    dist = pd.concat([distribuicao_intervalos(d, ['pleito', 'uf']).assign(nivel='uf'),
                      distribuicao_intervalos(d, ['pleito', 'geracao']).assign(nivel='geracao'),
                      distribuicao_intervalos(d, ['pleito', 'classe']).assign(nivel='classe')], ignore_index=True)
    return {'linha': linha, 'viol': v, 'dist': dist, 'quar': quar, 'arq': arq}


def _c3_01_fecha(resumo: list, viol_all: list, dist: list, arqs: list, quar: list) -> dict:
    """Junta os parciais por pleito de C3-01 e faz a ordem só do BU no país."""
    viol = pd.concat(viol_all, ignore_index=True)
    viol['maior_violacao_min'] = viol[[c_ for c_ in viol.columns if c_.startswith('dif_apos_')]].min(axis=1)
    arqs.append(grava_csv(viol, 'C3-01_violacoes_de_ordem.csv'))
    arqs.append(grava_csv(pd.DataFrame(resumo), 'C3-01_resumo_por_pleito.csv'))
    arqs.append(grava_csv(pd.concat(dist, ignore_index=True), 'C3-01_distribuicao_intervalos.csv'))
    q = quarentena('01', quar)
    if q:
        arqs.append(q)
    # ordem só do BU (carga < abertura ≤ encerramento ≤ emissão ≤ recebimento) no país: 2018 e 2022, 28 UFs
    pais_res, pais_viol = [], []
    c = con()
    for pleito in ['2018-t1', '2018-t2', '2022-t1', '2022-t2']:
        ufs = sorted({p.name.split('_')[0] for p in (BWEB / pleito).glob(f'*_{BWEB_CARGO[pleito]}.parquet')})
        for uf in ufs:
            b = _secoes_bweb(c, pleito, uf)
            if b is None or b.empty:
                continue
            b['desloc_h'] = b.set_index(['uf', 'municipality']).index.map(desloc_por_municipio(b).to_dict()).astype(float)
            b['pleito'] = pleito
            b = ordem_marcos(b)
            v = b[b['n_violacoes'] > 0]
            pais_viol.append(v[['pleito'] + CHAVE + ['local', 'urna', 'tipo_urna', 'carga', 'abertura', 'encerramento', 'emissao',
                                                      'recebimento', 'desloc_h', 'violacoes', 'n_violacoes'] +
                               [c_ for c_ in v.columns if c_.startswith('dif_apos_')]])
            pais_res.append({'pleito': pleito, 'uf': uf, 'secoes': len(b), 'desloc_h_moda': b['desloc_h'].mode().iloc[0] if b['desloc_h'].notna().any() else None,
                             'com_carga': int(b['carga'].notna().sum()), 'com_emissao': int(b['emissao'].notna().sum()),
                             'com_recebimento': int(b['recebimento'].notna().sum()), 'comparaveis': int(b['status'].eq('comparavel').sum()),
                             'parcial_sem_fuso': int(b['status'].str.startswith('PARCIAL').sum()),
                             'secoes_com_violacao': len(v), 'detalhe': json.dumps(v['violacoes'].str.split(';').explode().value_counts().to_dict()),
                             'min_urna_ate_recebimento_min': float(b['dif_apos_emissao'].min()) if 'dif_apos_emissao' in b and b['dif_apos_emissao'].notna().any() else None,
                             'p50_encerramento_ate_recebimento_min': float(b['dif_apos_encerramento'].median()) if b['dif_apos_encerramento'].notna().any() else None})
            del b, v
        gc.collect()
        print(pleito, 'país ok', flush=True)
    c.close()
    pv = pd.concat(pais_viol, ignore_index=True) if pais_viol else pd.DataFrame()
    arqs.append(grava_csv(pv, 'C3-01_bu_pais_violacoes.csv'))
    arqs.append(grava_csv(pd.DataFrame(pais_res), 'C3-01_bu_pais_resumo_uf.csv'))
    return {'status': 'feita', 'motivo': 'marcos do log nas 11 UFs vêm do leitor antigo (só logd.dat externo); zerésima/'
            'ligamentos/emissão lidos do log e assinatura das 470 mil urnas restantes de 2026-T2 dependem das passadas (C3-04, integridade 2026-T2)',
            'numeros_chave': {'por_pleito': {r['pleito']: {k: r[k] for k in ('secoes', 'comparaveis', 'secoes_com_violacao',
                                                                                'violacoes_em_secoes_com_troca', 'detalhe_violacoes')}
                                             for r in resumo},
                              'bu_pais_secoes_com_violacao': {p: int(sum(r['secoes_com_violacao'] for r in pais_res if r['pleito'] == p))
                                                              for p in ['2018-t1', '2018-t2', '2022-t1', '2022-t2']},
                              'quarentena': len(quar)},
            'arquivos': arqs}


# ----------------------------------------------------------------------------------------------- C3-02: assinatura
def deriva_relativa(d: pd.DataFrame) -> pd.DataFrame:
    """Por pleito × UF × geração: quantis de (assinatura − emissão|encerramento) e (recebimento − assinatura, em Brasília).
    'p01_rel_uf' = p01 de recebimento−assinatura da geração menos o p01 da UF inteira: gerações com relógio sistematicamente
    adiantado/atrasado em relação às outras da mesma UF (mesma infraestrutura de transmissão) aparecem como desvio."""
    linhas = []
    d = d.copy()
    for (pleito, uf), g in d.groupby(['pleito', 'uf']):
        p01_uf = g['min_receb_apos_assin'].quantile(0.01) if g['min_receb_apos_assin'].notna().any() else np.nan
        p50_uf = g['min_receb_apos_assin'].median() if g['min_receb_apos_assin'].notna().any() else np.nan
        for ger, h in g.groupby('geracao'):
            qa = _quantis(h['min_assin_apos_ref'])
            qr = _quantis(h['min_receb_apos_assin'])
            linhas.append({'pleito': pleito, 'uf': uf, 'geracao': ger, 'urnas': len(h), 'referencia': h['referencia'].mode().iloc[0],
                           'assin_apos_ref_p01': qa.get('p01'), 'assin_apos_ref_p50': qa.get('p50'), 'assin_apos_ref_p99': qa.get('p99'),
                           'assin_apos_ref_max': qa.get('max'), 'assin_antes_ref': qa.get('negativos', 0),
                           'receb_apos_assin_min': qr.get('min'), 'receb_apos_assin_p01': qr.get('p01'), 'receb_apos_assin_p50': qr.get('p50'),
                           'receb_antes_assin': qr.get('negativos', 0),
                           'p01_rel_uf': (qr.get('p01') - p01_uf) if qr.get('p01') is not None and pd.notna(p01_uf) else np.nan,
                           'p50_rel_uf': (qr.get('p50') - p50_uf) if qr.get('p50') is not None and pd.notna(p50_uf) else np.nan})
    return pd.DataFrame(linhas)


def _assinatura_pleito(pleito: str) -> pd.DataFrame:
    """Urnas com assinatura de um pleito (da linha do tempo de C3-01) e os três intervalos de C3-02, com tipos compactos."""
    p = OUT / f'C3-01_linha_do_tempo_{pleito}.parquet'
    cols = ['pleito', 'uf', 'municipality', 'zone', 'section', 'urna', 'geracao', 'encerramento', 'emissao', 'assinatura',
            'recebimento', 'desloc_h']
    d = pd.read_parquet(p, columns=cols) if p.exists() else linha_do_tempo(pleito)[0][cols]
    d = d[d['assinatura'].notna()].reset_index(drop=True)
    tem_emissao = d['emissao'].notna().any()
    ref = d['emissao'] if tem_emissao else d['encerramento']
    d['referencia'] = 'emissao' if tem_emissao else 'encerramento'
    d['min_assin_apos_ref'] = minutos(ref, d['assinatura']).astype('float32')
    d['min_assin_apos_encerramento'] = minutos(d['encerramento'], d['assinatura']).astype('float32')
    rb = minutos(d['assinatura'] + pd.to_timedelta(d['desloc_h'].fillna(0), unit='h'), d['recebimento'])
    d['min_receb_apos_assin'] = rb.where(d['desloc_h'].notna()).astype('float32')
    d['geracao'] = d['geracao'].fillna('sem certificado')
    for col in ('pleito', 'uf', 'geracao', 'referencia'):
        d[col] = d[col].astype('category')
    return d


def c3_02() -> dict:
    """assinado_em (relógio da urna na assinatura) × emissão/encerramento × recebimento por geração e UF; processa um pleito
    por vez (memória) e guarda só os três intervalos para os agregados globais."""
    arqs, dr_l, por_pleito, neg_l, glob = [], [], [], [], []
    for pleito in ['2022-t1', '2022-t2', '2024-t1', '2024-t2', '2026-t1', '2026-t2']:
        d = _assinatura_pleito(pleito)
        dr_l.append(deriva_relativa(d))
        for ger, g in d.groupby('geracao', observed=True):
            qa, qr, qe = _quantis(g['min_assin_apos_ref']), _quantis(g['min_receb_apos_assin']), _quantis(g['min_assin_apos_encerramento'])
            por_pleito.append({'pleito': pleito, 'geracao': ger, 'urnas': len(g), 'referencia': str(g['referencia'].iloc[0]),
                               'assin_apos_ref_p01': qa.get('p01'), 'assin_apos_ref_p50': qa.get('p50'), 'assin_apos_ref_p99': qa.get('p99'),
                               'assin_apos_ref_max': qa.get('max'), 'assin_antes_ref': qa.get('negativos', 0),
                               'assin_apos_encerramento_p50': qe.get('p50'), 'assin_antes_encerramento': qe.get('negativos', 0),
                               'receb_apos_assin_n': qr.get('n', 0), 'receb_apos_assin_min': qr.get('min'),
                               'receb_apos_assin_p01': qr.get('p01'), 'receb_apos_assin_p50': qr.get('p50'),
                               'receb_antes_assin': qr.get('negativos', 0)})
        neg_l.append(d[(d['min_assin_apos_ref'] < 0) | (d['min_receb_apos_assin'] < 0) | (d['min_assin_apos_encerramento'] < 0)])
        glob.append(pd.DataFrame({'pleito': d['pleito'].astype(str), 'geracao': d['geracao'].astype(str),
                                  'min_assin_apos_ref': d['min_assin_apos_ref'], 'min_assin_apos_encerramento': d['min_assin_apos_encerramento'],
                                  'min_receb_apos_assin': d['min_receb_apos_assin']}))
        del d
        gc.collect()
    dr = pd.concat(dr_l, ignore_index=True)
    arqs.append(grava_csv(dr, 'C3-02_por_pleito_uf_geracao.csv'))
    arqs.append(grava_csv(pd.DataFrame(por_pleito), 'C3-02_por_pleito_geracao.csv'))
    neg = pd.concat(neg_l, ignore_index=True)
    arqs.append(grava_csv(neg, 'C3-02_negativos.csv'))
    # gerações com p01 relativo fora de ±2 min dentro da UF (desvio sistemático entre gerações)
    desvio = dr[dr['urnas'] >= 200].copy()
    desvio = desvio[desvio['p01_rel_uf'].abs() >= 2]
    arqs.append(grava_csv(desvio.sort_values('p01_rel_uf'), 'C3-02_geracoes_com_desvio_na_uf.csv'))
    a = pd.concat(glob, ignore_index=True)
    del glob
    c2 = pd.read_csv(C2_14, sep=';', decimal=',', encoding='utf-8-sig') if C2_14.exists() else pd.DataFrame()
    return {'status': 'feita', 'motivo': 'estende C2-14 (que já listou as exceções) com geração/UF e deriva relativa; '
            '2024 agora comparável via BWEB; 2026-T2 só 28.823 urnas assinadas (sem DT_EMISSAO_BU: referência = encerramento)',
            'numeros_chave': {'urnas': int(len(a)), 'assin_antes_ref': int((a['min_assin_apos_ref'] < 0).sum()),
                              'assin_antes_encerramento': int((a['min_assin_apos_encerramento'] < 0).sum()),
                              'receb_antes_assin': int((a['min_receb_apos_assin'] < 0).sum()),
                              'receb_antes_assin_por_pleito': {p: int((g['min_receb_apos_assin'] < 0).sum()) for p, g in a.groupby('pleito')},
                              'por_pleito_p50_assin_apos_ref': {p: float(g['min_assin_apos_ref'].median()) for p, g in a.groupby('pleito')},
                              'por_geracao_p50_assin_apos_ref': {p: float(g['min_assin_apos_ref'].median()) for p, g in a.groupby('geracao')},
                              'geracoes_com_desvio_p01_na_uf': int(len(desvio)),
                              'c2_14_comparaveis': int(c2['comparaveis'].fillna(0).sum()) if 'comparaveis' in c2 else None},
            'arquivos': arqs}


# ----------------------------------------------------------------------------------------------- C3-07: gaps log × BU
def faixas_gap(d: pd.DataFrame, col: str) -> pd.Series:
    bins = [-np.inf, -0.0001, 15, 60, 120, 300, np.inf]
    labels = ['negativo', '0–15', '15–60', '60–120', '120–300', '>300']
    return pd.cut(d[col], bins=bins, labels=labels)


def resumo_gaps(d: pd.DataFrame, por: list[str]) -> pd.DataFrame:
    out = []
    for chave, g in d.groupby(por, dropna=False):
        chave = chave if isinstance(chave, tuple) else (chave,)
        ge, ga = g['gap_enc_ultimo'], g['gap_primeiro_abertura']
        out.append({**dict(zip(por, chave)), 'secoes': len(g), 'gap_enc_ultimo_n': int(ge.notna().sum()),
                    'gap_negativo': int((ge < 0).sum()), 'gap_gt60': int((ge > 60).sum()), 'gap_gt120': int((ge > 120).sum()),
                    'gap_gt300': int((ge > 300).sum()), 'gap_p50': ge.median(), 'gap_p99': ge.quantile(0.99), 'gap_max': ge.max(),
                    'abertura_primeiro_n': int(ga.notna().sum()), 'primeiro_antes_abertura': int((ga < 0).sum()),
                    'primeiro_gt60_apos_abertura': int((ga > 60).sum()), 'primeiro_p50': ga.median(), 'primeiro_p99': ga.quantile(0.99),
                    'primeiro_max': ga.max()})
    return pd.DataFrame(out)


COLS_C3_07 = ['pleito', 'leitor'] + CHAVE + ['voting_place', 'classe', 'has_log', 'vote_events', 'attendance', 'abertura', 'primeiro_voto',
                                            'ultimo_voto', 'encerramento', 'gap_enc_ultimo', 'gap_primeiro_abertura', 'clock_reversals']


def _gaps_pleito(pleito: str) -> pd.DataFrame:
    """Gaps log × BU de um pleito: 11 UFs (indicadores, leitor antigo) ou 2026-T2 país (linha do tempo C3-01, leitor aninhado)."""
    if pleito != '2026-t2':
        f = _indicadores(PLEITO_EID[pleito])
        f['pleito'] = pleito
        f['abertura'] = parse_dt(f['opening_bu'])
        f['encerramento'] = parse_dt(f['closure_bu'])
        f['leitor'] = 'antigo'
    else:
        p = OUT / 'C3-01_linha_do_tempo_2026-t2.parquet'
        f = pd.read_parquet(p, columns=CHAVE + ['local', 'troca_urna', 'tem_log', 'abertura', 'primeiro_voto', 'ultimo_voto',
                                               'encerramento']) if p.exists() else linha_do_tempo('2026-t2')[0]
        f = f.rename(columns={'local': 'voting_place', 'tem_log': 'has_log'})
        f['pleito'] = pleito
        f['leitor'] = 'aninhado'
        for col in ('vote_events', 'attendance', 'clock_reversals'):
            f[col] = np.nan
    f['troca_urna'] = f['troca_urna'].fillna(False).astype(bool)
    f['classe'] = np.where(f['troca_urna'], 'com troca/contingência', 'sem troca')
    f['gap_enc_ultimo'] = minutos(f['ultimo_voto'], f['encerramento'])
    f['gap_primeiro_abertura'] = minutos(f['abertura'], f['primeiro_voto'])
    return f[COLS_C3_07].reset_index(drop=True)


def faixa_encerramento(enc: pd.Series) -> pd.Series:
    """Faixa da hora local de encerramento (relógio da urna): '<18h', '18h–19h', '≥19h' ou 'sem encerramento'."""
    h = pd.to_datetime(enc).dt.hour
    return pd.Series(np.select([h.isna(), h < 18, h < 19], ['sem encerramento', '<18h', '18h–19h'], '≥19h'), index=enc.index)


def c3_07() -> dict:
    arqs, r_cl, r_uf, r_enc, fx_l, caudas_l, rev_l, nk = [], [], [], [], [], [], [], {}
    for pleito in list(EID_PLEITO.values()) + ['2026-t2']:
        a = _gaps_pleito(pleito)
        r_cl.append(resumo_gaps(a, ['pleito', 'classe']))
        r_uf.append(resumo_gaps(a, ['pleito', 'uf']))
        a['faixa_encerramento'] = faixa_encerramento(a['encerramento'])
        a['recorte'] = 'todas as UFs do conjunto'
        r_enc.append(resumo_gaps(a, ['pleito', 'recorte', 'faixa_encerramento']))
        if pleito == '2026-t2':  # mesmo recorte das 11 UFs do controle (2022/2024/2026-T1)
            b = a[a['uf'].isin(UFS_11)].assign(recorte='11 UFs')
            r_enc.append(resumo_gaps(b, ['pleito', 'recorte', 'faixa_encerramento']))
            r_enc.append(resumo_gaps(b.assign(faixa_encerramento='todas'), ['pleito', 'recorte', 'faixa_encerramento']))
            del b
        r_enc.append(resumo_gaps(a.assign(faixa_encerramento='todas'), ['pleito', 'recorte', 'faixa_encerramento']))
        a['faixa_gap'] = faixas_gap(a, 'gap_enc_ultimo')
        fx = a.groupby(['pleito', 'faixa_gap'], observed=False).size().rename('secoes').reset_index()
        fx['pct'] = 100 * fx['secoes'] / fx['secoes'].sum()
        fx_l.append(fx)
        ge, ga = a['gap_enc_ultimo'], a['gap_primeiro_abertura']
        cd = a[(ge < 0) | (ge > 300) | (ga < 0) | (ga > 90) | (a['clock_reversals'].fillna(0) > 0)].copy()
        cd['motivo'] = np.where(cd['gap_enc_ultimo'] < 0, 'último voto depois do encerramento;', '') +             np.where(cd['gap_enc_ultimo'] > 300, 'encerramento > 300 min após o último voto;', '') +             np.where(cd['gap_primeiro_abertura'] < 0, 'primeiro voto antes da abertura;', '') +             np.where(cd['gap_primeiro_abertura'] > 90, 'primeiro voto > 90 min após a abertura;', '') +             np.where(cd['clock_reversals'].fillna(0) > 0, 'reversão de relógio entre votos;', '')
        caudas_l.append(cd)
        rev_l.append(a[a['clock_reversals'].fillna(0) > 0])
        nk[pleito] = {'n': int(ge.notna().sum()), 'negativos': int((ge < 0).sum()), 'gt60': int((ge > 60).sum()),
                      'gt120': int((ge > 120).sum()), 'gt300': int((ge > 300).sum()), 'p50_min': float(ge.median()),
                      'p99_min': float(ge.quantile(0.99)), 'primeiro_antes_abertura': int((ga < 0).sum()),
                      'primeiro_gt60': int((ga > 60).sum()), 'primeiro_gt90': int((ga > 90).sum()),
                      'enc_lt18h_n': int((ge.notna() & a['faixa_encerramento'].eq('<18h')).sum()),
                      'enc_lt18h_gt120': int(((ge > 120) & a['faixa_encerramento'].eq('<18h')).sum()),
                      'enc_ge19h_n': int((ge.notna() & a['faixa_encerramento'].eq('≥19h')).sum()),
                      'enc_ge19h_gt120': int(((ge > 120) & a['faixa_encerramento'].eq('≥19h')).sum()),
                      'primeiro_p50_min': float(ga.median()), 'reversoes': int((a['clock_reversals'].fillna(0) > 0).sum()),
                      'gt120_com_troca': int(((ge > 120) & a['classe'].eq('com troca/contingência')).sum()),
                      'pct_gt120': float(100 * (ge > 120).sum() / max(ge.notna().sum(), 1))}
        print('C3-07', pleito, nk[pleito], flush=True)
        del a, cd
        gc.collect()
    arqs.append(grava_csv(pd.concat(r_cl, ignore_index=True), 'C3-07_resumo_pleito_classe.csv'))
    arqs.append(grava_csv(pd.concat(r_uf, ignore_index=True), 'C3-07_resumo_pleito_uf.csv'))
    arqs.append(grava_csv(pd.concat(r_enc, ignore_index=True), 'C3-07_resumo_por_hora_de_encerramento.csv'))
    arqs.append(grava_csv(pd.concat(fx_l, ignore_index=True), 'C3-07_faixas_gap.csv'))
    caudas = pd.concat(caudas_l, ignore_index=True)
    arqs.append(grava_csv(caudas.sort_values(['pleito', 'gap_enc_ultimo'], ascending=[True, False]), 'C3-07_caudas.csv'))
    rev = pd.concat(rev_l, ignore_index=True)
    arqs.append(grava_csv(rev, 'C3-07_reversoes_relogio_listadas.csv'))
    return {'status': 'feita', 'motivo': '11 UFs com leitor antigo (seções com troca: horários da última urna); 2026-T2 país com leitor aninhado',
            'numeros_chave': {'por_pleito': nk, 'reversoes_listadas': int(len(rev)), 'caudas': int(len(caudas))}, 'arquivos': arqs}


# ----------------------------------------------------------------------------------------------- C3-03: mesma urna
def urnas_repetidas(df: pd.DataFrame, col_urna: str, chave: list[str] | None = None) -> pd.DataFrame:
    """Linhas cujo número de urna aparece em mais de uma seção (chave) no mesmo conjunto; ignora vazios/−1/#NULO#."""
    chave = chave or CHAVE
    d = df.copy()
    d[col_urna] = d[col_urna].astype('string').str.strip()
    d = d[d[col_urna].notna() & ~d[col_urna].isin(['', '-1', '#NULO#', '0', 'nan', '<NA>'])]
    n = d.drop_duplicates(chave).groupby(col_urna)[chave[-1]].transform('size')
    d = d.drop_duplicates(chave)
    d['n_secoes_da_urna'] = n
    return d[d['n_secoes_da_urna'] > 1].sort_values([col_urna] + chave)


URNA_INVALIDA = ('', '-1', '#NULO#', '0', 'nan', '<NA>')


def _sql_repetidas(c, arquivos: list[Path], sel_de, chave_sel: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Em DuckDB, um arquivo por vez (memória). Se chave_sel (só seção + urna) for dado, a tabela distinta usa só essas colunas
    e as demais (sel_de) são buscadas numa segunda leitura filtrada pelas urnas repetidas (para arquivos com uma linha por
    votável, como o BWEB). Devolve (linhas cuja urna aparece em > 1 seção do conjunto, resumo por UF)."""
    for i, f in enumerate(arquivos):
        sel = chave_sel or sel_de({c_.name for c_ in pq.ParquetFile(f).schema})
        q = f"SELECT DISTINCT {sel} FROM read_parquet('{Path(f).as_posix()}')"
        c.execute(f'CREATE OR REPLACE TEMP TABLE s AS {q}' if i == 0 else f'INSERT INTO s {q}')
    inval = ', '.join(f"'{x}'" for x in URNA_INVALIDA)
    rep = c.execute(f"""WITH v AS (SELECT DISTINCT * FROM s WHERE urna IS NOT NULL AND urna NOT IN ({inval})),
        r AS (SELECT urna, count(DISTINCT (uf, municipality, zone, section)) n_secoes_da_urna FROM v GROUP BY urna
              HAVING count(DISTINCT (uf, municipality, zone, section)) > 1)
        SELECT v.*, r.n_secoes_da_urna FROM v JOIN r USING (urna) ORDER BY urna, uf, municipality, zone, section""").df()
    res = c.execute(f"""SELECT uf, count(DISTINCT (municipality, zone, section)) secoes,
        count(DISTINCT CASE WHEN urna IS NOT NULL AND urna NOT IN ({inval}) THEN (municipality, zone, section) END) secoes_com_urna,
        count(*) linhas_distintas FROM s GROUP BY uf ORDER BY uf""").df()
    if chave_sel and not rep.empty:
        lista = ', '.join(f"'{u}'" for u in rep['urna'].unique())
        extra = []
        for f in arquivos:
            sel = sel_de({c_.name for c_ in pq.ParquetFile(f).schema})
            extra.append(c.execute(f"""SELECT DISTINCT {sel} FROM read_parquet('{Path(f).as_posix()}')
                                       WHERE TRIM(CAST(NR_URNA_EFETIVADA AS VARCHAR)) IN ({lista})""").df())
        extra = pd.concat(extra, ignore_index=True)
        rep = rep.merge(extra, on=['uf', 'municipality', 'zone', 'section', 'urna'], how='left')
    return rep, res


def _sel_ceft(cols: set) -> tuple[str, str, str] | None:
    """SELECT padronizado do CEFT (nomeado ou c0..c26), expressão da origem do voto e nome do layout."""
    if 'NR_URNA_EFETIVADA' in cols:
        nulo = 'CAST(NULL AS VARCHAR)'
        div = 'DS_DIVERGENCIA' if 'DS_DIVERGENCIA' in cols else ('TP_DIVERGENCIA' if 'TP_DIVERGENCIA' in cols else nulo)
        ds = 'DS_ORIGEM_VOTO' if 'DS_ORIGEM_VOTO' in cols else nulo
        loc = 'NR_LOCAL_VOTACAO' if 'NR_LOCAL_VOTACAO' in cols else nulo
        sel = ("SG_UF uf, TRY_CAST(CD_MUNICIPIO AS BIGINT) municipality, TRY_CAST(NR_ZONA AS BIGINT) zone, "
               "TRY_CAST(NR_SECAO AS BIGINT) section, TRIM(NR_URNA_EFETIVADA) urna, TRIM(NR_URNA_ESPERADA) urna_esperada, "
               f"DT_CARGA_URNA_EFETIVADA carga, CD_ORIGEM_VOTO cd_origem, {ds} ds_origem, {div} divergencia, {loc} local")
        return sel, 'coalesce(ds_origem, cd_origem)', 'nomeado'
    if 'c18' in cols:
        m = CEFT_OLD
        sel = (f"{m['SG_UF']} uf, TRY_CAST({m['CD_MUNICIPIO']} AS BIGINT) municipality, TRY_CAST({m['NR_ZONA']} AS BIGINT) zone, "
               f"TRY_CAST({m['NR_SECAO']} AS BIGINT) section, TRIM({m['NR_URNA_EFETIVADA']}) urna, "
               f"TRIM({m['NR_URNA_ESPERADA']}) urna_esperada, {m['DT_CARGA_URNA_EFETIVADA']} carga, {m['CD_ORIGEM_VOTO']} cd_origem, "
               "CAST(NULL AS VARCHAR) ds_origem, CAST(NULL AS VARCHAR) divergencia, CAST(NULL AS VARCHAR) local")
        return sel, 'cd_origem', 'inferido (c0..c26)'
    return None


SEL_CHAVE_BWEB = ("SG_UF uf, TRY_CAST(CD_MUNICIPIO AS BIGINT) municipality, TRY_CAST(NR_ZONA AS BIGINT) zone, "
                  "TRY_CAST(NR_SECAO AS BIGINT) section, TRIM(CAST(NR_URNA_EFETIVADA AS VARCHAR)) urna")


def _sel_bweb(cols: set) -> str:
    """SELECT padronizado do BWEB por seção (colunas ausentes no arquivo viram NULL, para o INSERT casar por posição)."""
    opc = []
    for nomes, alias in ((('DT_CARGA_URNA_EFETIVADA', 'DT_CARGA'), 'carga'), (('DT_ABERTURA',), 'abertura'),
                         (('DT_ENCERRAMENTO',), 'encerramento'), (('DS_TIPO_URNA',), 'tipo_urna'),
                         (('DS_AGREGADAS', 'DS_SECOES_AGREGADAS'), 'agregadas'), (('NR_LOCAL_VOTACAO',), 'local')):
        col = next((n for n in nomes if n in cols), None)
        opc.append(f'CAST({col} AS VARCHAR) {alias}' if col else f'CAST(NULL AS VARCHAR) {alias}')
    return ("SG_UF uf, TRY_CAST(CD_MUNICIPIO AS BIGINT) municipality, TRY_CAST(NR_ZONA AS BIGINT) zone, "
            "TRY_CAST(NR_SECAO AS BIGINT) section, TRIM(CAST(NR_URNA_EFETIVADA AS VARCHAR)) urna, " + ', '.join(opc))


def c3_03() -> dict:
    """Mesma urna em mais de uma seção no mesmo pleito: CEFT (NR_URNA_EFETIVADA), BWEB (NR_URNA_EFETIVADA) e certificado
    da urna (cert_cn, assinatura); cada pleito é tratado em DuckDB e só as linhas repetidas voltam para o pandas."""
    c = con('200MB')
    c.execute('SET preserve_insertion_order=false')
    arqs = []
    # (a) CEFT 2012–2026-T1 (11 UFs)
    rep_l, res_l, origem = [], [], []
    for pasta in sorted(x for x in CEFT.iterdir() if x.is_dir()):
        pleito = pasta.name
        fs = sorted(pasta.glob('*.parquet'))
        if not fs:
            continue
        x = _sel_ceft({c_.name for c_ in pq.ParquetFile(fs[0]).schema})
        if x is None:
            continue
        layout = x[2]
        rep, res = _sql_repetidas(c, fs, lambda cols: _sel_ceft(cols)[0])
        og = c.execute("""SELECT uf, coalesce(ds_origem, cd_origem) origem_voto, count(*) secoes,
            sum(CASE WHEN urna <> urna_esperada THEN 1 ELSE 0 END) efetivada_dif_esperada FROM s GROUP BY ALL ORDER BY ALL""").df()
        og.insert(0, 'pleito', pleito)
        origem.append(og)
        rep.insert(0, 'pleito', pleito)
        rep['layout'] = layout
        res.insert(0, 'pleito', pleito)
        res['urnas_repetidas_no_pleito'] = int(rep['urna'].nunique()) if not rep.empty else 0
        rep_l.append(rep)
        res_l.append(res)
        print('C3-03 ceft', pleito, len(rep), flush=True)
    rep_ceft = pd.concat(rep_l, ignore_index=True)
    rep_ceft['origem_nao_urna_ou_divergencia'] = ~rep_ceft['cd_origem'].astype('string').fillna('U').isin(['U']) | \
        ~rep_ceft['divergencia'].astype('string').fillna('#NULO#').isin(['#NULO#', ''])
    rep_ceft['urna_diferente_da_esperada'] = rep_ceft['urna'].astype('string') != rep_ceft['urna_esperada'].astype('string')
    arqs.append(grava_csv(rep_ceft, 'C3-03_urna_repetida_ceft.csv'))
    arqs.append(grava_csv(pd.concat(res_l, ignore_index=True), 'C3-03_ceft_resumo_pleito_uf.csv'))
    arqs.append(grava_csv(pd.concat(origem, ignore_index=True), 'C3-03_origem_voto_ceft_por_pleito_uf.csv'))
    # (b) BWEB (NR_URNA_EFETIVADA por seção) em todos os pleitos/UFs em disco, cargo de referência do pleito
    bw_l, bw_res = [], []
    for pleito, cargo in BWEB_CARGO.items():
        pasta = BWEB / pleito
        fs = sorted(pasta.glob(f'*_{cargo}.parquet')) if pasta.exists() else []
        if not fs:
            continue
        rep, res = _sql_repetidas(c, fs, _sel_bweb, chave_sel=SEL_CHAVE_BWEB)
        rep.insert(0, 'pleito', pleito)
        rep.insert(1, 'cargo', cargo)
        res.insert(0, 'pleito', pleito)
        res['urnas_repetidas_no_pleito'] = int(rep['urna'].nunique()) if not rep.empty else 0
        bw_l.append(rep)
        bw_res.append(res)
        print('C3-03 bweb', pleito, len(rep), flush=True)
    bw = pd.concat(bw_l, ignore_index=True)
    arqs.append(grava_csv(bw, 'C3-03_urna_repetida_bweb.csv'))
    arqs.append(grava_csv(pd.concat(bw_res, ignore_index=True), 'C3-03_bweb_resumo_pleito_uf.csv'))
    # (c) certificado da urna repetido no mesmo pleito (assinatura)
    cert = c.execute("""WITH t AS (SELECT eleicao AS pleito, uf, urna, cert_cn, upper(cert_cn) cert_cn_norm, cadeia_ac, assinado_em
                          FROM read_parquet(?) WHERE cert_cn IS NOT NULL AND cert_cn <> ''),
                        r AS (SELECT pleito, cert_cn_norm FROM t GROUP BY ALL HAVING count(DISTINCT urna) > 1)
                        SELECT t.* FROM t JOIN r USING (pleito, cert_cn_norm) ORDER BY pleito, cert_cn_norm, urna""",
                     [str(INTEGRIDADE)]).df()
    c.close()
    ch = [chave_do_stem(u) for u in cert['urna']]
    cert['municipality'] = [x[1] for x in ch]
    cert['zone'] = [x[2] for x in ch]
    cert['section'] = [x[3] for x in ch]
    cert['n_urnas_do_cert'] = cert.groupby(['pleito', 'cert_cn_norm'])['urna'].transform('nunique')
    if not cert.empty and not bw.empty:
        cert = cert.merge(bw[['pleito', 'uf', 'municipality', 'zone', 'section', 'urna', 'n_secoes_da_urna']]
                          .rename(columns={'urna': 'urna_bweb_repetida', 'n_secoes_da_urna': 'n_secoes_da_urna_bweb'}),
                          on=['pleito', 'uf', 'municipality', 'zone', 'section'], how='left')
    arqs.append(grava_csv(cert, 'C3-03_cert_repetido.csv'))
    # (d) consolidação com os marcos da linha do tempo (C3-01) quando houver
    casos = []
    for src, df_, col in (('CEFT', rep_ceft, 'urna'), ('BWEB', bw, 'urna'), ('certificado', cert, 'cert_cn_norm')):
        if df_.empty:
            continue
        x = df_[['pleito', 'uf', 'municipality', 'zone', 'section', col]].rename(columns={col: 'identificador'}).copy()
        x['fonte'] = src
        casos.append(x)
    casos = pd.concat(casos, ignore_index=True)
    for col in ('municipality', 'zone', 'section'):
        casos[col] = pd.to_numeric(casos[col], errors='coerce').astype('Int64')
    lt = []
    for pleito in casos['pleito'].unique():
        p = OUT / f'C3-01_linha_do_tempo_{pleito}.parquet'
        if p.exists():
            t = pd.read_parquet(p, columns=['pleito'] + CHAVE + ['local', 'urna', 'carga', 'abertura', 'primeiro_voto', 'ultimo_voto',
                                                                 'encerramento', 'emissao', 'troca_urna', 'log_nome'])
            for col in ('municipality', 'zone', 'section'):
                t[col] = t[col].astype('Int64')
            lt.append(t.merge(casos[casos['pleito'] == pleito][CHAVE].drop_duplicates(), on=CHAVE))
            del t
    if lt:
        casos = casos.merge(pd.concat(lt, ignore_index=True).rename(columns={'urna': 'urna_linha_do_tempo'}),
                            on=['pleito'] + CHAVE, how='left')
    casos = casos.sort_values(['pleito', 'fonte', 'identificador'])
    arqs.append(grava_csv(casos, 'C3-03_casos_consolidados.csv'))
    resumo = casos.groupby(['pleito', 'fonte']).agg(identificadores=('identificador', 'nunique'), secoes=('section', 'size')).reset_index()
    arqs.append(grava_csv(resumo, 'C3-03_resumo.csv'))
    return {'status': 'feita', 'motivo': 'CEFT só nas 11 UFs (2012–2026-T1); BWEB presidente país 2014–2022 e prefeito 10–11 UFs '
            '2012–2024; sem CEFT/BWEB 2026-T2; layout 2012–2016 do CEFT inferido (c18 = NR_URNA_EFETIVADA)',
            'numeros_chave': {'ceft_urnas_repetidas_por_pleito': rep_ceft.groupby('pleito')['urna'].nunique().to_dict(),
                              'ceft_secoes_envolvidas_por_pleito': rep_ceft.groupby('pleito').size().to_dict(),
                              'bweb_urnas_repetidas_por_pleito': bw.groupby('pleito')['urna'].nunique().to_dict() if not bw.empty else {},
                              'bweb_secoes_envolvidas_por_pleito': bw.groupby('pleito').size().to_dict() if not bw.empty else {},
                              'cert_repetido_por_pleito': cert.groupby('pleito')['cert_cn_norm'].nunique().to_dict() if not cert.empty else {},
                              'max_secoes_por_urna_ceft': int(rep_ceft['n_secoes_da_urna'].max()) if not rep_ceft.empty else 0,
                              'max_secoes_por_urna_bweb': int(bw['n_secoes_da_urna'].max()) if not bw.empty else 0,
                              'secoes_envolvidas_total': int(len(casos))},
            'arquivos': arqs}


# ----------------------------------------------------------------------------------------------- C3-06: mínimo físico
def bh_rejeita(p: np.ndarray, alfa: float = BH_ALFA) -> np.ndarray:
    """Benjamini–Hochberg: máscara dos testes rejeitados a nível alfa."""
    p = np.asarray(p, dtype=float)
    n = np.isfinite(p).sum()
    ordem = np.argsort(np.where(np.isfinite(p), p, np.inf))
    ps = p[ordem]
    k = np.arange(1, len(p) + 1)
    ok = np.isfinite(ps) & (ps <= alfa * k / max(n, 1))
    limite = ok.nonzero()[0].max() if ok.any() else -1
    rej = np.zeros(len(p), dtype=bool)
    if limite >= 0:
        rej[ordem[:limite + 1]] = True
    return rej


def sid_de(municipality, zone, section) -> np.ndarray:
    """Identificador inteiro da seção (município ≤ 5 dígitos, zona e seção ≤ 4): mun·10⁸ + zona·10⁴ + seção."""
    return (np.asarray(municipality, dtype=np.int64) * 100_000_000 + np.asarray(zone, dtype=np.int64) * 10_000
            + np.asarray(section, dtype=np.int64))


def sid_para_chave(sid: np.ndarray) -> pd.DataFrame:
    sid = np.asarray(sid, dtype=np.int64)
    return pd.DataFrame({'municipality': sid // 100_000_000, 'zone': (sid // 10_000) % 10_000, 'section': sid % 10_000})


def excesso_por_sid(sid: np.ndarray, valores: np.ndarray, piso: float, taxa: float) -> pd.DataFrame:
    """Por seção (sid): n, n abaixo do piso, fração, esperado, p-valor binomial (cauda superior), BH a 5%, mínimo e mediana.
    Usa os blocos contíguos de sid (o arquivo de atendimentos vem agrupado por seção); se não forem contíguos, ordena antes."""
    from scipy.stats import binom
    sid = np.asarray(sid, dtype=np.int64)
    valores = np.asarray(valores)
    quebra = np.flatnonzero(sid[1:] != sid[:-1]) + 1
    ini = np.r_[0, quebra]
    if len(np.unique(sid[ini])) != len(ini):  # seção em mais de um bloco: ordena (estável) por sid
        ordem = np.argsort(sid, kind='stable')
        sid, valores = sid[ordem], valores[ordem]
        del ordem
        ini = np.r_[0, np.flatnonzero(sid[1:] != sid[:-1]) + 1]
    fim = np.r_[ini[1:], len(sid)]
    finito = np.isfinite(valores)
    abaixo = finito & (valores < piso)
    n = np.add.reduceat(finito.astype(np.int64), ini) if len(sid) else np.array([], dtype=np.int64)
    n_ab = np.add.reduceat(abaixo.astype(np.int64), ini) if len(sid) else np.array([], dtype=np.int64)
    mins, meds = np.full(len(ini), np.nan), np.full(len(ini), np.nan)
    for j, (a, b) in enumerate(zip(ini, fim)):
        v = valores[a:b]
        v = v[np.isfinite(v)]
        if len(v):
            mins[j] = v.min()
            meds[j] = np.median(v)
    g = sid_para_chave(sid[ini])
    g['n'] = n
    g['n_abaixo'] = n_ab
    g = g[g['n'] > 0].copy()
    mins, meds = mins[n > 0], meds[n > 0]
    g['frac_abaixo'] = g['n_abaixo'] / g['n']
    g['esperado'] = g['n'] * taxa
    g['p'] = binom.sf(g['n_abaixo'] - 1, g['n'], taxa)
    g['bh_5pct'] = bh_rejeita(g['p'].values)
    g['minimo'] = mins
    g['mediana'] = meds
    return g.reset_index(drop=True)


def excesso_abaixo_do_piso(keys: pd.DataFrame, valores: np.ndarray, piso: float, taxa: float) -> pd.DataFrame:
    """Por seção: n, n abaixo do piso, fração, p-valor binomial (cauda superior) e rejeição BH a 5%."""
    sid = sid_de(keys['municipality'], keys['zone'], keys['section'])
    return excesso_por_sid(sid, np.asarray(valores, dtype=float), piso, taxa).drop(columns=['minimo', 'mediana'])


def c3_06() -> dict:
    """Mínimo físico a partir dos 7,2 M atendimentos (2026-T1, seções da cadência): lidos por grupo de linhas, guardados como
    arrays compactos (sid int64, tempos float32, tipo int8) para caber no limite de memória."""
    arqs = []
    f = pq.ParquetFile(ATENDIMENTOS)
    n_rows = f.metadata.num_rows
    sid = np.empty(n_rows, dtype=np.int64)  # pré-alocados: evita a cópia de um concatenate no fim
    cab = np.empty(n_rows, dtype=np.float32)
    hab = np.empty(n_rows, dtype=np.float32)
    tipo = np.empty(n_rows, dtype=np.int8)
    quar = []
    n_tot = 0
    for i in range(f.metadata.num_row_groups):
        t = f.read_row_group(i, columns=['municipality', 'zone', 'section', 't_id', 't_hab', 't_voto', 'tipo'], use_threads=False)
        k = t.num_rows
        th, ti, tv = (t.column(x).to_numpy() for x in ('t_hab', 't_id', 't_voto'))
        sl = slice(n_tot, n_tot + k)
        cab[sl] = np.where(th >= 0, tv - th, np.nan)
        hab[sl] = np.where((th >= 0) & (ti >= 0), th - ti, np.nan)
        sid[sl] = sid_de(t.column('municipality').to_numpy(), t.column('zone').to_numpy(), t.column('section').to_numpy())
        tipo[sl] = t.column('tipo').to_numpy()
        neg = (cab[sl] < 0) | (hab[sl] < 0)
        if neg.any() and len(quar) < 5000:
            for j in np.flatnonzero(neg)[:2000]:
                m_, z_, s_ = sid_para_chave(sid[sl][j:j + 1]).iloc[0]
                quar.append({'municipality': m_, 'zone': z_, 'section': s_, 't_id': ti[j], 't_hab': th[j], 't_voto': tv[j],
                             'tipo': int(tipo[sl][j]), 'reason': 'voto antes da habilitação ou habilitação antes da identificação'})
        n_tot += k
        del t, th, ti, tv, neg
        pa.default_memory_pool().release_unused()
    gc.collect()
    n_neg = int(np.sum((cab < 0) | (hab < 0)))
    cab[cab < 0] = np.nan  # negativos ficam na quarentena, fora dos quantis
    hab[hab < 0] = np.nan
    # geração da urna por seção (secoes_cadencia → log_nome → integridade 2026-t1)
    sc = pd.read_parquet(SECOES_CADENCIA, columns=CHAVE + ['voting_place', 'log_nome', 'g1', 'g2', 'g3', 'g4', 'local_alta'])
    sc['urna'] = sc['log_nome'].map(stem_de)
    c = con()
    it = c.execute("SELECT urna, cadeia_ac FROM read_parquet(?) WHERE eleicao = '2026-t1'", [str(INTEGRIDADE)]).df()
    c.close()
    sc = sc.merge(it.drop_duplicates('urna'), on='urna', how='left')
    del it
    sc['geracao'] = sc['cadeia_ac'].map(GERACAO).fillna('sem certificado')
    sc['sid'] = sid_de(sc['municipality'], sc['zone'], sc['section'])
    nomes_ger = sorted(sc['geracao'].unique()) + ['sem vínculo']
    cod = pd.Index(sc['sid']).get_indexer(sid)
    ger_sc = pd.Categorical(sc['geracao'], categories=nomes_ger).codes.astype('int8')
    ger = np.where(cod >= 0, ger_sc[np.clip(cod, 0, None)], len(nomes_ger) - 1).astype('int8')
    sem_vinculo = int((cod < 0).sum())
    del cod
    qs = [0.001, 0.01, 0.05, 0.5, 0.95]
    linhas = []

    def q_row(nome, grupo, sel, cab, hab):
        for medida, arr in (('cabine_s (voto − habilitação)', cab), ('habilitacao_s (habilitação − identificação)', hab)):
            v = arr[sel]
            v = v[np.isfinite(v)]
            if len(v):
                qq = np.quantile(v, qs)
                linhas.append({'recorte': nome, 'grupo': grupo, 'medida': medida, 'n': int(len(v)), 'min': float(v.min()),
                               'p0_1': qq[0], 'p1': qq[1], 'p5': qq[2], 'p50': qq[3], 'p95': qq[4], 'max': float(v.max())})
    todos = np.ones(len(cab), dtype=bool)
    q_row('global', 'todos', todos, cab, hab)
    for k, nome in TIPOS_HAB.items():
        q_row('tipo_habilitacao', nome, tipo == k, cab, hab)
    for gi, g_ in enumerate(nomes_ger):
        q_row('geracao_urna', g_, ger == gi, cab, hab)
        for k, nome in TIPOS_HAB.items():
            q_row(f'geracao_x_tipo:{g_}', nome, (ger == gi) & (tipo == k), cab, hab)
    quantis = pd.DataFrame(linhas)
    arqs.append(grava_csv(quantis, 'C3-06_quantis.csv'))
    piso_cab = float(np.nanquantile(cab, PISO_QUANTIL))
    piso_hab = float(np.nanquantile(hab, PISO_QUANTIL))
    # taxa de referência = fração global abaixo do piso (com empates no piso inteiro, não é exatamente 0,1%)
    taxa_cab = float((cab < piso_cab).sum() / np.isfinite(cab).sum())
    taxa_hab = float((hab < piso_hab).sum() / np.isfinite(hab).sum())
    ex = excesso_por_sid(sid, cab, piso_cab, max(taxa_cab, 1e-6)).rename(columns={'minimo': 'cabine_min_s', 'mediana': 'cabine_p50_s'})
    exh = excesso_por_sid(sid, hab, piso_hab, max(taxa_hab, 1e-6)).rename(columns={'minimo': 'habilitacao_min_s', 'mediana': 'habilitacao_p50_s'})
    exh = exh.rename(columns={c_: f'hab_{c_}' for c_ in ('n', 'n_abaixo', 'frac_abaixo', 'esperado', 'p', 'bh_5pct')})
    del sid, cab, hab, tipo, ger
    gc.collect()
    por_sec = ex.merge(exh, on=['municipality', 'zone', 'section'], how='outer')
    por_sec = por_sec.merge(sc[CHAVE + ['voting_place', 'geracao', 'g1', 'g2', 'g3', 'g4', 'local_alta']],
                            on=['municipality', 'zone', 'section'], how='left')
    # comparação com as vizinhas do mesmo prédio (locais com ≥ 3 seções no conjunto)
    pr = por_sec.groupby(['uf', 'municipality', 'zone', 'voting_place'], dropna=False)
    por_sec['n_secoes_predio'] = pr['n'].transform('size')
    soma = pr['frac_abaixo'].transform('sum')
    por_sec['frac_abaixo_vizinhas'] = np.where(por_sec['n_secoes_predio'] >= 3,
                                               (soma - por_sec['frac_abaixo']) / (por_sec['n_secoes_predio'] - 1), np.nan)
    por_sec['dif_vs_vizinhas'] = por_sec['frac_abaixo'] - por_sec['frac_abaixo_vizinhas']
    por_sec['comparabilidade'] = np.where(por_sec['n_secoes_predio'] >= 3, 'prédio',
                                          'NOT_COMPARABLE: menos de 3 seções do prédio no conjunto')
    # hipótese concorrente: cabine muito curta = voto em branco/nulo (poucas teclas); proxy = brancos + nulos de presidente, 1º turno
    bn = pd.read_parquet(SECOES_T1T2, columns=CHAVE + ['t1_comparecimento', 't1_branco', 't1_nulo'])
    for col in ('municipality', 'zone', 'section'):
        bn[col] = bn[col].astype('int64')
    por_sec = por_sec.merge(bn.drop_duplicates(CHAVE), on=CHAVE, how='left')
    por_sec['pct_branco_nulo_pres_t1'] = 100 * (por_sec['t1_branco'] + por_sec['t1_nulo']) / por_sec['t1_comparecimento']
    soma_bn = por_sec.groupby(['uf', 'municipality', 'zone', 'voting_place'], dropna=False)['pct_branco_nulo_pres_t1'].transform('sum')
    por_sec['pct_bn_vizinhas'] = np.where(por_sec['n_secoes_predio'] >= 3, (soma_bn - por_sec['pct_branco_nulo_pres_t1'])
                                          / (por_sec['n_secoes_predio'] - 1), np.nan)
    arqs.append(grava_csv(por_sec, 'C3-06_por_secao.csv'))
    from scipy.stats import spearmanr
    ok_bn = por_sec[['frac_abaixo', 'pct_branco_nulo_pres_t1']].dropna()
    rho = spearmanr(ok_bn['frac_abaixo'], ok_bn['pct_branco_nulo_pres_t1']) if len(ok_bn) > 10 else None
    bhm = por_sec['bh_5pct'].fillna(False).astype(bool)
    controle_bn = {'spearman_frac_abaixo_x_pct_bn': float(rho.statistic) if rho is not None else None,
                   'spearman_p': float(rho.pvalue) if rho is not None else None,
                   'pct_bn_media_secoes_bh': float(por_sec.loc[bhm, 'pct_branco_nulo_pres_t1'].mean()),
                   'pct_bn_media_demais': float(por_sec.loc[~bhm, 'pct_branco_nulo_pres_t1'].mean()),
                   'dif_pct_bn_vs_vizinhas_secoes_bh': float((por_sec.loc[bhm, 'pct_branco_nulo_pres_t1']
                                                              - por_sec.loc[bhm, 'pct_bn_vizinhas']).mean())}
    acima = por_sec[por_sec['bh_5pct'].fillna(False).astype(bool) | por_sec['hab_bh_5pct'].fillna(False).astype(bool)]
    arqs.append(grava_csv(acima.sort_values('p'), 'C3-06_secoes_acima_bh.csv'))
    grupos = []
    for g_ in ('g1', 'g2', 'g3', 'g4', 'local_alta'):
        s_ = por_sec[por_sec[g_].fillna(False).astype(bool)]
        grupos.append({'grupo': g_, 'secoes': len(s_), 'frac_abaixo_piso_media': s_['frac_abaixo'].mean(),
                       'frac_abaixo_p90': s_['frac_abaixo'].quantile(0.9), 'secoes_bh_cabine': int(s_['bh_5pct'].fillna(False).sum()),
                       'secoes_bh_habilitacao': int(s_['hab_bh_5pct'].fillna(False).sum()),
                       'cabine_min_mediana_s': s_['cabine_min_s'].median(), 'cabine_p50_mediana_s': s_['cabine_p50_s'].median(),
                       'dif_vs_vizinhas_media': s_['dif_vs_vizinhas'].mean(),
                       'secoes_com_predio': int(s_['comparabilidade'].eq('prédio').sum())})
    arqs.append(grava_csv(pd.DataFrame(grupos), 'C3-06_por_grupo.csv'))
    q = quarentena('06', quar)
    if q:
        arqs.append(q)
    glob_cab = quantis[(quantis['recorte'] == 'global') & quantis['medida'].str.startswith('cabine')].iloc[0]
    return {'status': 'parcial', 'motivo': 'só 2026-T1, 25.813 seções dos grupos da cadência (G1 destoantes, G2, G3 vizinhas, '
            'G4 aleatório); país, 2022 e 2026-T2 dependem da passada C3-04/C3-05 (instantes por voto)',
            'numeros_chave': {'atendimentos': n_tot, 'com_t_hab': int(glob_cab['n']), 'negativos_quarentena': n_neg,
                              'sem_vinculo_de_geracao': sem_vinculo, 'piso_cabine_s_p0_1': piso_cab, 'piso_habilitacao_s_p0_1': piso_hab,
                              'taxa_abaixo_piso_cabine': taxa_cab, 'taxa_abaixo_piso_habilitacao': taxa_hab,
                              'cabine_min_s': float(glob_cab['min']), 'cabine_p1_s': float(glob_cab['p1']),
                              'cabine_p50_s': float(glob_cab['p50']), 'secoes': int(len(por_sec)),
                              'secoes_bh_cabine': int(por_sec['bh_5pct'].fillna(False).sum()),
                              'secoes_bh_habilitacao': int(por_sec['hab_bh_5pct'].fillna(False).sum()),
                              'atendimentos_abaixo_do_piso_nas_secoes_bh': int(por_sec.loc[bhm, 'n_abaixo'].sum()),
                              'controle_branco_nulo': controle_bn,
                              'por_grupo': {g['grupo']: {'secoes': g['secoes'], 'bh_cabine': g['secoes_bh_cabine'],
                                                         'frac_media': g['frac_abaixo_piso_media']} for g in grupos}},
            'arquivos': arqs}


# ----------------------------------------------------------------------------------------------- C3-09: reinícios
def _seg(hhmmss: str) -> float:
    try:
        h, m, s = hhmmss.split(':')
        return int(h) * 3600 + int(m) * 60 + int(s)
    except (ValueError, AttributeError):
        return np.nan


def classifica_ligamentos(power_on: str, first_vote: str, last_vote: str, voting_mode: str = '') -> dict:
    """Conta mensagens 'Urna ligada…' (campo power_on, ';'-separado) e classifica cada instante: antes do primeiro voto,
    durante a votação (entre o primeiro e o último voto) ou depois do último voto; detecta padrão periódico (intervalos
    múltiplos de 30 min, ±5 s), típico de mensagem de monitoramento, não de reinício."""
    ts = [_seg(x) for x in str(power_on or '').split(';') if x]
    ts = [t for t in ts if np.isfinite(t)]
    pv, uv = _seg(first_vote or ''), _seg(last_vote or '')
    antes = durante = depois = 0
    for t in ts:
        if not np.isfinite(pv) or t <= pv:
            antes += 1
        elif np.isfinite(uv) and t >= uv:
            depois += 1
        else:
            durante += 1
    dif = np.diff(sorted(ts)) if len(ts) >= 3 else np.array([])
    n_per = 0
    if len(dif):
        resto = np.mod(dif, PERIODICO_S)
        n_per = int(((resto <= 5) | (resto >= PERIODICO_S - 5)).sum())
    # periódico: ≥ 3 intervalos múltiplos de 30 min e pelo menos metade dos intervalos (há ligamentos reais antes da série)
    periodico = bool(n_per >= 3 and n_per >= 0.5 * len(dif))
    return {'n_ligamentos': len(ts), 'lig_antes_1o_voto': antes, 'lig_durante_votacao': durante, 'lig_apos_ultimo_voto': depois,
            'padrao_periodico_30min': periodico, 'intervalos_de_30min': n_per, 'primeiro_ligamento': ts[0] if ts else np.nan,
            'n_modo_votacao': len([x for x in str(voting_mode or '').split(';') if x])}


def c3_09() -> dict:
    arqs, partes = [], []
    for p in sorted(CONTINGENCIA.glob('*.parquet')):
        if p.name.endswith('_messages.parquet') or p.name.startswith('_'):
            continue
        raiz, pleito = p.stem.rsplit('_', 1)
        d = pd.read_parquet(p, columns=['member', 'municipality', 'zone', 'section', 'days_in_log', 'power_on', 'power_off', 'contingency_start',
                                        'contingency_ok', 'contingency_fail', 'voting_mode', 'votes', 'first_vote', 'last_vote',
                                        'closing_code', 'closing_confirmed', 'closing_start', 'errors_day', 'zeresima', 'locale_zero'])
        d['raiz'] = raiz
        d['pleito'] = pleito
        d['uf'] = raiz.split('_')[1] if '_' in raiz else 'BA'
        cl = pd.DataFrame([classifica_ligamentos(a, b, c_, v) for a, b, c_, v in zip(d['power_on'], d['first_vote'], d['last_vote'], d['voting_mode'])])
        d = pd.concat([d.reset_index(drop=True), cl], axis=1)
        d['n_desligamentos'] = d['power_off'].fillna('').map(lambda s: len([x for x in s.split(';') if x]))
        d['n_cont_start'] = d['contingency_start'].fillna('').map(lambda s: len([x for x in s.split(';') if x]))
        d['n_cont_fail'] = d['contingency_fail'].fillna('').map(lambda s: len([x for x in s.split(';') if x]))
        d['n_encerramento_digitado'] = d['closing_code'].fillna('').map(lambda s: len([x for x in s.split(';') if x]))
        d['n_dias_no_log'] = d['days_in_log'].fillna('').map(lambda s: len([x for x in s.split(',') if x]))
        d['tem_zeresima'] = d['zeresima'].fillna('').ne('')
        partes.append(d.drop(columns=['power_on', 'power_off', 'contingency_ok', 'closing_confirmed', 'days_in_log']))
        del d, cl
    a = pd.concat(partes, ignore_index=True)
    del partes
    gc.collect()
    for col in ('municipality', 'zone', 'section'):
        a[col] = pd.to_numeric(a[col], errors='coerce').astype('Int64')
    arqs.append(grava_parquet(a, 'C3-09_ligamentos_por_log.parquet', sorted(p for p in CONTINGENCIA.glob('*.parquet') if not p.name.startswith('_'))))
    res = a.groupby(['pleito', 'raiz']).agg(
        logs=('member', 'size'), com_cont_start=('n_cont_start', lambda s: int((s > 0).sum())), cont_fail=('n_cont_fail', lambda s: int((s > 0).sum())),
        lig_mediana=('n_ligamentos', 'median'), lig_max=('n_ligamentos', 'max'), logs_lig_ge2=('n_ligamentos', lambda s: int((s >= 2).sum())),
        logs_lig_durante=('lig_durante_votacao', lambda s: int((s > 0).sum())), logs_periodico=('padrao_periodico_30min', 'sum'),
        logs_lig_durante_nao_periodico=('lig_durante_votacao', lambda s: int(((s > 0) & ~a.loc[s.index, 'padrao_periodico_30min']).sum())),
        logs_com_desligamento=('n_desligamentos', lambda s: int((s > 0).sum())), logs_com_erro_no_dia=('errors_day', lambda s: int((s > 0).sum())),
        logs_encerramento_digitado_ge2=('n_encerramento_digitado', lambda s: int((s >= 2).sum())),
        logs_com_zeresima=('tem_zeresima', 'sum'), logs_votes_zero=('votes', lambda s: int((s == 0).sum()))).reset_index()
    arqs.append(grava_csv(res, 'C3-09_resumo_por_pleito_raiz.csv'))
    durante = a[(a['lig_durante_votacao'] > 0) & ~a['padrao_periodico_30min']]
    arqs.append(grava_csv(durante, 'C3-09_ligamentos_durante_votacao.csv'))
    per = a[a['padrao_periodico_30min']]
    arqs.append(grava_csv(per, 'C3-09_padrao_periodico_30min.csv'))
    # cruzamento com as trocas (CEFT) já consolidadas
    if TROCADAS.exists():
        tr = pd.read_csv(TROCADAS, sep=';', decimal=',', encoding='utf-8-sig', usecols=['eid', 'uf', 'municipality', 'zone', 'section', 'cont_start', 'cont_errors'])
        tr['pleito'] = tr['eid'].map(EID_PLEITO)
        tr = tr.dropna(subset=['pleito'])
        for col in ('municipality', 'zone', 'section'):
            tr[col] = pd.to_numeric(tr[col], errors='coerce').astype('Int64')
        x = a.merge(tr[['pleito'] + CHAVE + ['cont_start']], on=['pleito'] + CHAVE, how='left', indicator=True)
        cruz = x.groupby('pleito')['_merge'].value_counts().unstack(fill_value=0).reset_index()
        cruz.columns.name = None
        arqs.append(grava_csv(cruz, 'C3-09_logs_x_trocas_ceft.csv'))
    fb = pd.read_csv(FREQ_BASE, sep=';', decimal=',', encoding='utf-8-sig') if FREQ_BASE.exists() else pd.DataFrame()
    nk = {'logs': int(len(a)), 'com_contingencia_iniciada': int((a['n_cont_start'] > 0).sum()), 'cont_fail': int((a['n_cont_fail'] > 0).sum()),
          'logs_ligamentos_ge2': int((a['n_ligamentos'] >= 2).sum()), 'logs_ligamento_durante_votacao_nao_periodico': int(len(durante)),
          'logs_padrao_periodico_30min': int(len(per)), 'logs_encerramento_digitado_ge2': int((a['n_encerramento_digitado'] >= 2).sum()),
          'logs_com_zeresima_detectada': int(a['tem_zeresima'].sum()), 'logs_com_erro_no_dia': int((a['errors_day'] > 0).sum()),
          'por_pleito_logs': a.groupby('pleito').size().to_dict(),
          'frequencia_base_1800_urnas_reinicio_pct': (fb.set_index('eleicao')[[c_ for c_ in fb.columns if 'reinicio' in c_][0]].to_dict()
                                                        if not fb.empty else None)}
    return {'status': 'parcial', 'motivo': 'só os 28.777 logs ambíguos/de contingência já extraídos (11 UFs, 2022–2026-T1) e a amostra de 1.800; '
            "'Urna ligada' inclui mensagens de bateria (padrão periódico marcado); sem instante por voto, logo 'votos entre reinícios' "
            'e a frequência de base nas urnas normais dependem de C3-04', 'numeros_chave': nk, 'arquivos': arqs}


# ----------------------------------------------------------------------------------------------- C3-15: recebimento
def dif_hash_recebimento(receipt_date: pd.Series, receipt_time: pd.Series, hash_time: pd.Series) -> pd.Series:
    """Minutos entre o carimbo hash_time (só hora) e o recebimento (data+hora) do sistema de resultados, no mesmo dia."""
    r = pd.to_datetime(receipt_date.astype('string') + ' ' + receipt_time.astype('string'), format='%d/%m/%Y %H:%M:%S', errors='coerce')
    h = pd.to_datetime(receipt_date.astype('string') + ' ' + hash_time.astype('string'), format='%d/%m/%Y %H:%M:%S', errors='coerce')
    return (h - r).dt.total_seconds() / 60


def c3_15() -> dict:
    arqs = []
    c = con()
    fe = c.execute("""SELECT uf, CAST(municipality AS BIGINT) municipality, CAST(zone AS BIGINT) zone, CAST(section AS BIGINT) section,
        abertura, encerramento_local, desloc_h, encerramento, recebimento, cenario, min_enc_apos_17h, min_rec_apos_enc, validos
        FROM read_parquet(?)""", [str(FECHAMENTO)]).df()
    fe['recebido_antes_19h'] = fe['recebimento'].dt.hour < 19
    fe['recebido_antes_do_encerramento'] = fe['min_rec_apos_enc'] < 0
    por_uf = fe.groupby('uf').agg(secoes=('section', 'size'), primeiro_recebimento=('recebimento', 'min'),
                                  recebidos_antes_19h=('recebido_antes_19h', 'sum'), recebidos_antes_do_encerramento=('recebido_antes_do_encerramento', 'sum'),
                                  min_rec_apos_enc_min=('min_rec_apos_enc', 'min'), p01_rec_apos_enc=('min_rec_apos_enc', lambda s: s.quantile(0.01)),
                                  mediana_rec_apos_enc=('min_rec_apos_enc', 'median'), cenario_A=('cenario', lambda s: int(s.eq('A').sum())),
                                  cenario_C=('cenario', lambda s: int(s.eq('C').sum())), sem_fuso=('desloc_h', lambda s: int(s.isna().sum()))).reset_index()
    por_uf['pct_antes_19h'] = 100 * por_uf['recebidos_antes_19h'] / por_uf['secoes']
    rec15 = fe[fe['recebido_antes_19h']].copy()
    rec15['faixa_recebimento'] = rec15['recebimento'].dt.floor('15min').dt.strftime('%H:%M')
    arqs.append(grava_csv(por_uf.sort_values('primeiro_recebimento'), 'C3-15_recebimento_por_uf.csv'))
    arqs.append(grava_csv(rec15.sort_values('recebimento'), 'C3-15_recebidos_antes_19h.csv'))
    arqs.append(grava_csv(rec15.groupby(['uf', 'faixa_recebimento']).size().rename('secoes').reset_index(), 'C3-15_antes_19h_por_uf_faixa.csv'))
    # hash_time × recebimento (14 UFs do sistema de resultados)
    bu = c.execute("""SELECT uf, CAST(municipality AS BIGINT) municipality, CAST(zone AS BIGINT) zone, CAST(section AS BIGINT) section,
        receipt_date, receipt_time, hash_time, aux_status, hash_status, n_hashes, closing FROM read_parquet(?)""", [str(BU_T2)]).df()
    c.close()
    bu['dif_hash_menos_recebimento_min'] = dif_hash_recebimento(bu['receipt_date'], bu['receipt_time'], bu['hash_time'])
    bu['encerramento_local'] = parse_dt(bu['closing'])
    bu = bu.merge(fe[CHAVE + ['desloc_h', 'encerramento', 'recebimento']], on=CHAVE, how='left')
    bu['hash_dt'] = pd.to_datetime(bu['receipt_date'].astype('string') + ' ' + bu['hash_time'].astype('string'), format='%d/%m/%Y %H:%M:%S', errors='coerce')
    bu['min_hash_apos_enc'] = minutos(bu['encerramento'], bu['hash_dt'])
    h_uf = bu.groupby('uf').agg(urnas=('section', 'size'), dif_min=('dif_hash_menos_recebimento_min', 'min'), dif_p01=('dif_hash_menos_recebimento_min', lambda s: s.quantile(0.01)),
                                dif_p50=('dif_hash_menos_recebimento_min', 'median'), dif_p99=('dif_hash_menos_recebimento_min', lambda s: s.quantile(0.99)),
                                dif_max=('dif_hash_menos_recebimento_min', 'max'), hash_antes_recebimento=('dif_hash_menos_recebimento_min', lambda s: int((s < 0).sum())),
                                hash_mais_de_60min_antes=('dif_hash_menos_recebimento_min', lambda s: int((s < -60).sum())),
                                hash_mais_de_60min_depois=('dif_hash_menos_recebimento_min', lambda s: int((s > 60).sum())),
                                hash_antes_do_encerramento=('min_hash_apos_enc', lambda s: int((s < 0).sum())),
                                aux_recebida=('aux_status', lambda s: int(s.eq('Recebida').sum()))).reset_index()
    arqs.append(grava_csv(h_uf, 'C3-15_hash_time_x_recebimento_uf.csv'))
    exc = bu[(bu['dif_hash_menos_recebimento_min'].abs() > 60) | (bu['min_hash_apos_enc'] < 0) | (bu['recebimento'] < bu['encerramento'])]
    arqs.append(grava_csv(exc, 'C3-15_hash_time_excecoes.csv'))
    jac = fe[fe['recebido_antes_do_encerramento']]
    arqs.append(grava_csv(jac, 'C3-15_recebido_antes_do_encerramento.csv'))
    # hash_time anterior ao encerramento (carimbo do sistema de resultados de outro evento?) com votos envolvidos
    ha = bu[bu['min_hash_apos_enc'] < 0].merge(fe[CHAVE + ['validos', 'cenario']], on=CHAVE, how='left')
    arqs.append(grava_csv(ha.sort_values(['uf', 'municipality', 'zone', 'section']), 'C3-15_hash_antes_do_encerramento.csv'))
    status_uf = bu.groupby(['uf', 'aux_status', 'hash_status'], dropna=False).agg(
        urnas=('section', 'size'), dif_p50=('dif_hash_menos_recebimento_min', 'median'),
        hash_antes_do_encerramento=('min_hash_apos_enc', lambda s: int((s < 0).sum()))).reset_index()
    arqs.append(grava_csv(status_uf, 'C3-15_status_hash_por_uf.csv'))
    br = fe['uf'].ne('ZZ')
    return {'status': 'feita', 'motivo': 'carimbos do sistema de resultados (ha/da e hash_time), não o DT_BU_RECEBIDO do BWEB (2026-T2 sem BWEB em disco); '
            'significado oficial de hash_time não documentado',
            'numeros_chave': {'recebidos_antes_19h': int(fe['recebido_antes_19h'].sum()),
                              'recebidos_antes_19h_sem_ZZ': int((fe['recebido_antes_19h'] & br).sum()),
                              'recebidos_antes_19h_ZZ_exterior': int((fe['recebido_antes_19h'] & ~br).sum()),
                              'ufs_primeiro_recebimento_apos_21h': sorted(por_uf.loc[por_uf['primeiro_recebimento'].dt.hour >= 21, 'uf'].tolist()),
                              'hash_antes_do_encerramento_por_uf_status': {f'{k[0]}|{k[1]}': int(v) for k, v in
                                                                           ha.groupby(['uf', 'aux_status']).size().items()},
                              'hash_antes_do_encerramento_validos': int(ha['validos'].fillna(0).sum()),
                              'aux_status_recebida_por_uf': {u: int(v) for u, v in bu[bu['aux_status'].eq('Recebida')].groupby('uf').size().items()},
                              'recebidos_antes_do_encerramento': int(len(jac)),
                              'ufs_com_recebimento_antes_19h': int((por_uf['recebidos_antes_19h'] > 0).sum()),
                              'primeiro_recebimento_por_uf': {r.uf: str(r.primeiro_recebimento) for r in por_uf.itertuples()},
                              'hash_time_urnas': int(len(bu)), 'hash_antes_recebimento': int((bu['dif_hash_menos_recebimento_min'] < 0).sum()),
                              'hash_abs_gt60min': int((bu['dif_hash_menos_recebimento_min'].abs() > 60).sum()),
                              'hash_antes_do_encerramento': int((bu['min_hash_apos_enc'] < 0).sum()),
                              'hash_dif_p50_por_uf': h_uf.set_index('uf')['dif_p50'].round(2).to_dict()},
            'arquivos': arqs}


# ----------------------------------------------------------------------------------------------- C3-08: gaps 2026-T2
def conta_eventos(eventos_json: str, padroes: tuple[str, ...]) -> dict:
    try:
        ev = json.loads(eventos_json) if isinstance(eventos_json, str) else {}
    except ValueError:
        ev = {}
    out = {}
    for p in padroes:
        out[p] = int(sum(v for k, v in ev.items() if p.lower() in k.lower()))
    return out


EVENTOS_C3_08 = ('cancelou o encerramento', 'Encerramento só pode ser solicitado', 'Procedimento de encerramento abortado',
                 'Votação suspensa', 'Urna de contingência', 'Urna ligada')


def c3_08() -> dict:
    arqs = []
    p = OUT / 'C3-01_linha_do_tempo_2026-t2.parquet'
    d = pd.read_parquet(p, columns=CHAVE + ['local', 'cenario', 'tem_log', 'troca_urna', 'abertura', 'primeiro_voto', 'ultimo_voto',
                                           'encerramento', 'recebimento']) if p.exists() else linha_do_tempo('2026-t2')[0]
    uv = ler_ultimo_voto(['votos_log', 'validos', 'votos_apos_17h', 'votos_apos_19h'])
    d = d.merge(uv.drop_duplicates(CHAVE), on=CHAVE, how='left')
    del uv
    for col in ('votos_log', 'validos', 'votos_apos_17h', 'votos_apos_19h'):
        d[col] = d[col].astype('float32')
    d['gap_enc_ultimo'] = minutos(d['ultimo_voto'], d['encerramento'])
    d['primeiro_voto_local_h'] = pd.to_datetime(d['primeiro_voto']).dt.hour + pd.to_datetime(d['primeiro_voto']).dt.minute / 60
    d['min_primeiro_apos_abertura'] = minutos(d['abertura'], d['primeiro_voto'])
    bins = pd.read_parquet(BINS['2026-t2'], columns=CHAVE + ['n_logs', 'contingencia'])
    d = d.merge(bins.drop_duplicates(CHAVE), on=CHAVE, how='left')
    an = pd.read_parquet(SECOES_ANOM['2026-t2'], columns=CHAVE + ['z', 'res_pp', 'n2', 'p_loo'])
    d = d.merge(an.drop_duplicates(CHAVE), on=CHAVE, how='left')
    ls = pd.read_parquet(LOGS_SECOES, columns=CHAVE + ['grupo', 'encerrou_min', 'min_ultimo_voto_ate_encerrar',
                                                       'eventos_entre_ultimo_voto_e_encerrar', 'pausa_max_min', 'manual', 'alertas'])
    ev = []  # a coluna 'eventos' (JSON de ~7 kB por seção) é lida em lotes para não passar do limite de memória
    for lote in pq.ParquetFile(LOGS_SECOES).iter_batches(batch_size=2000, columns=['eventos']):
        ev += [conta_eventos(e, EVENTOS_C3_08) for e in lote.column('eventos').to_pylist()]
    ev = pd.DataFrame(ev)
    ev.columns = ['ev_' + re.sub(r'\W+', '_', c_.lower()).strip('_') for c_ in ev.columns]
    ls = pd.concat([ls.reset_index(drop=True), ev], axis=1)
    d = d.merge(ls.drop_duplicates(CHAVE), on=CHAVE, how='left', indicator='nos_grupos')
    d['nos_grupos'] = d['nos_grupos'].eq('both')
    del ls, ev, an, bins
    gc.collect()
    pa.default_memory_pool().release_unused()
    d['faixa_gap'] = faixas_gap(d, 'gap_enc_ultimo')
    d['faixa_tamanho'] = pd.cut(d['votos_log'], [-1, 30, 100, 200, 300, 10000], labels=['≤30', '31–100', '101–200', '201–300', '>300'])
    d['faixa_encerramento'] = faixa_encerramento(d['encerramento'])
    fe_uf = d.groupby(['uf', 'faixa_encerramento']).agg(secoes=('section', 'size'),
                                                       gap_gt120=('gap_enc_ultimo', lambda s: int((s > 120).sum())),
                                                       gap_p50=('gap_enc_ultimo', 'median')).reset_index()
    arqs.append(grava_csv(fe_uf, 'C3-08_hora_encerramento_por_uf.csv'))
    longo = d[d['gap_enc_ultimo'] > 120].copy()
    tardio = d[d['primeiro_voto_local_h'] >= 9].copy()
    res = d.groupby('faixa_gap', observed=False).agg(
        secoes=('section', 'size'), contingencia_pct=('contingencia', lambda s: 100 * s.fillna(False).mean()),
        n_logs_gt1_pct=('n_logs', lambda s: 100 * (s.fillna(1) > 1).mean()), votos_log_mediana=('votos_log', 'median'),
        votos_log_p10=('votos_log', lambda s: s.quantile(0.1)), cenario_A=('cenario', lambda s: int(s.eq('A').sum())),
        cenario_B=('cenario', lambda s: int(s.eq('B').sum())), cenario_C=('cenario', lambda s: int(s.eq('C').sum())),
        res_pp_media=('res_pp', 'mean'), z_abs_ge4=('z', lambda s: int((s.abs() >= 4).sum())), nos_grupos=('nos_grupos', 'sum'),
        cancelou_encerramento_nos_grupos=('ev_cancelou_o_encerramento', lambda s: int((s.fillna(0) > 0).sum())),
        encerramento_cedo_demais_nos_grupos=('ev_encerramento_só_pode_ser_solicitado', lambda s: int((s.fillna(0) > 0).sum())),
        pausa_max_mediana_nos_grupos=('pausa_max_min', 'median')).reset_index()
    arqs.append(grava_csv(res, 'C3-08_resumo_por_faixa_gap.csv'))
    tam = longo.groupby(['faixa_tamanho', 'cenario'], observed=False).size().rename('secoes').reset_index()
    arqs.append(grava_csv(tam, 'C3-08_gap_longo_por_tamanho_cenario.csv'))
    arqs.append(grava_csv(longo.sort_values('gap_enc_ultimo', ascending=False), 'C3-08_gap_longo_gt120.csv'))
    arqs.append(grava_csv(tardio.sort_values('primeiro_voto_local_h', ascending=False), 'C3-08_primeiro_voto_apos_9h_local.csv'))
    dossie = d[(d['gap_enc_ultimo'] > 300) | (d['primeiro_voto_local_h'] >= 10)].sort_values('gap_enc_ultimo', ascending=False)
    arqs.append(grava_csv(dossie, 'C3-08_caudas_para_dossie.csv'))
    # controle: vizinhas do mesmo prédio das seções com gap > 120 (resultado)
    pr = d.groupby(['uf', 'municipality', 'zone', 'local'])
    d['res_pp_vizinhas'] = (pr['res_pp'].transform('sum') - d['res_pp'].fillna(0)) / (pr['res_pp'].transform('count') - d['res_pp'].notna().astype(int)).replace(0, np.nan)
    lg = d[d['gap_enc_ultimo'] > 120]
    ctrl = {'secoes_gap_gt120': int(len(lg)), 'com_res_pp': int(lg['res_pp'].notna().sum()), 'res_pp_media': float(lg['res_pp'].mean()),
            'res_pp_vizinhas_media': float(lg['res_pp_vizinhas'].mean()), 'dif_media_pp': float((lg['res_pp'] - lg['res_pp_vizinhas']).mean()),
            'dif_ep_pp': float((lg['res_pp'] - lg['res_pp_vizinhas']).std() / np.sqrt(max((lg['res_pp'] - lg['res_pp_vizinhas']).notna().sum(), 1)))}
    return {'status': 'parcial', 'motivo': 'cruzamento com parquets existentes; a leitura dos logs das seções de cauda fora dos grupos '
            '(eventos entre o último voto e o encerramento) fica para a passada C3-04',
            'numeros_chave': {'gap_gt120': int(len(longo)), 'gap_gt300': int((d['gap_enc_ultimo'] > 300).sum()),
                              'gap_gt120_cenario_B': int(longo['cenario'].eq('B').sum()), 'gap_gt120_contingencia': int(longo['contingencia'].fillna(False).sum()),
                              'gap_gt120_votos_log_mediana': float(longo['votos_log'].median()), 'gap_gt120_nos_grupos': int(longo['nos_grupos'].sum()),
                              'gap_gt120_cancelou_encerramento_nos_grupos': int((longo['ev_cancelou_o_encerramento'].fillna(0) > 0).sum()),
                              'primeiro_voto_ge9h_local': int(len(tardio)), 'primeiro_voto_ge9h_por_uf': tardio['uf'].value_counts().head(10).to_dict(),
                              'primeiro_voto_ge9h_contingencia': int(tardio['contingencia'].fillna(False).sum()),
                              'primeiro_voto_ge9h_abertura_apos_9h': int((pd.to_datetime(tardio['abertura']).dt.hour >= 9).sum()),
                              'controle_predio_gap_gt120': ctrl, 'dossie': int(len(dossie)),
                              'gap_gt120_por_faixa_encerramento': longo['faixa_encerramento'].value_counts().to_dict(),
                              'encerramento_ge19h_por_uf': d.loc[d['faixa_encerramento'].eq('≥19h'), 'uf'].value_counts().to_dict()},
            'arquivos': arqs}


# ----------------------------------------------------------------------------------------------- C3-13: pausas (bins)
def pausas_nos_bins(m: np.ndarray) -> pd.DataFrame:
    """Por linha (seção) de uma matriz de contagens por bin de 15 min (8h–17h local): nº de bins vazios entre o primeiro e o último
    bin com voto, maior sequência de bins vazios (min) e nº de bins com voto."""
    m = np.asarray(m)
    n = m.shape[0]
    tem = m > 0
    out = np.zeros((n, 3), dtype=float)
    for i in range(n):
        idx = np.flatnonzero(tem[i])
        if len(idx) == 0:
            out[i] = (np.nan, np.nan, 0)
            continue
        seg = tem[i, idx[0]:idx[-1] + 1]
        vazios = (~seg).astype(int)
        maior = 0
        atual = 0
        for v in vazios:
            atual = atual + 1 if v else 0
            maior = max(maior, atual)
        out[i] = (vazios.sum(), maior * 15, len(idx))
    return pd.DataFrame(out, columns=['pausas_15min_bins', 'pausa_max_min_bins', 'bins_com_voto'])


def _grupos_ano(ano: str) -> pd.DataFrame:
    from scipy.stats import chi2
    s = pd.read_parquet(SECOES_ANOM[ano], columns=CHAVE + ['voting_place', 'z', 'z_m2', 'd2_m3', 'iso_m3', 't2_enc_bsb', 'res_pp', 'n2'])
    s['g_modelo'] = (s['z'].abs() > 4) | (s['z_m2'].abs() > 4) | (chi2.sf(s['d2_m3'], 5) < 1e-6) | (s['iso_m3'] >= s['iso_m3'].quantile(.9999))
    s['g_tarde'] = s['t2_enc_bsb'] >= 1140
    if ano == '2026-t2':
        ls = pd.read_parquet(LOGS_SECOES, columns=CHAVE + ['grupo'])
        s = s.merge(ls.drop_duplicates(CHAVE), on=CHAVE, how='left')
    else:
        ct = pd.read_parquet(CONTROLE_2022, columns=CHAVE + ['votos_apos_17h'])
        s = s.merge(ct.drop_duplicates(CHAVE), on=CHAVE, how='left')
        s['g_tarde'] |= s['votos_apos_17h'].fillna(0) >= 5
        s['marcada'] = s['g_modelo'] | s['g_tarde']
        loc = s.groupby(['uf', 'municipality', 'zone', 'voting_place'])
        s['local_marcado'] = loc['marcada'].transform('any')
        s['grupo'] = np.where(s['marcada'], np.where(s['g_modelo'], 'modelo', 'tarde'), np.where(s['local_marcado'], 'vizinhas', None))
    return s[s['grupo'].notna()][CHAVE + ['voting_place', 'grupo', 'res_pp', 'n2']]


def c3_13() -> dict:
    arqs, res, por_uf = [], [], []
    cols_bins = [f'b{h:02d}h{m:02d}' for h in range(8, 17) for m in (0, 15, 30, 45)]
    for ano in ('2022-t2', '2026-t2'):
        g = _grupos_ano(ano)
        partes = []  # lotes de 50 mil seções: a matriz inteira de bins (int64) passaria do limite de memória
        for lote in pq.ParquetFile(BINS[ano]).iter_batches(batch_size=50_000, columns=CHAVE + ['n_logs', 'contingencia', 'erro'] + cols_bins):
            t = lote.to_pandas()
            m = t[cols_bins].to_numpy(dtype=np.int16)
            partes.append(pd.concat([t.drop(columns=cols_bins).reset_index(drop=True), pausas_nos_bins(m)], axis=1))
            del t, m
        b = pd.concat(partes, ignore_index=True)
        del partes
        p = None
        pa.default_memory_pool().release_unused()
        b['ano'] = ano
        b['total_bins_8_17'] = b['bins_com_voto'] + b['pausas_15min_bins']
        por_uf.append(b.groupby(['ano', 'uf']).agg(secoes=('section', 'size'), pausas_media=('pausas_15min_bins', 'mean'),
                                                   pausa_max_p50=('pausa_max_min_bins', 'median'), pausa_max_p99=('pausa_max_min_bins', lambda s: s.quantile(0.99)),
                                                   pausa_max_ge60_pct=('pausa_max_min_bins', lambda s: 100 * (s >= 60).mean())).reset_index())
        x = g.merge(b, on=CHAVE, how='left')
        x['ano'] = ano
        for grupo, h in x.groupby('grupo'):
            viz = x[x['grupo'] == 'vizinhas']
            from scipy.stats import mannwhitneyu
            try:
                pu = mannwhitneyu(h['pausa_max_min_bins'].dropna(), viz['pausa_max_min_bins'].dropna(), alternative='two-sided').pvalue if grupo != 'vizinhas' else np.nan
            except ValueError:
                pu = np.nan
            res.append({'ano': ano, 'grupo': grupo, 'secoes': len(h), 'com_bins': int(h['pausas_15min_bins'].notna().sum()),
                        'contingencia_pct': 100 * h['contingencia'].fillna(False).mean(), 'pausas_15min_media': h['pausas_15min_bins'].mean(),
                        'pausa_max_min_p50': h['pausa_max_min_bins'].median(), 'pausa_max_min_p90': h['pausa_max_min_bins'].quantile(0.9),
                        'pausa_max_ge60_pct': 100 * (h['pausa_max_min_bins'] >= 60).mean(),
                        'dif_pausa_max_p50_vs_vizinhas': h['pausa_max_min_bins'].median() - viz['pausa_max_min_bins'].median(),
                        'dif_pausas_media_vs_vizinhas': h['pausas_15min_bins'].mean() - viz['pausas_15min_bins'].mean(),
                        'p_mannwhitney_pausa_max_vs_vizinhas': pu})
        arqs.append(grava_parquet(x, f'C3-13_pausas_bins_grupos_{ano}.parquet', [BINS[ano], SECOES_ANOM[ano], LOGS_SECOES if ano == '2026-t2' else CONTROLE_2022]))
        del b, x, g, p
        gc.collect()
    r = pd.DataFrame(res)
    arqs.append(grava_csv(r, 'C3-13_pausas_bins_grupos_2022_x_2026.csv'))
    arqs.append(grava_csv(pd.concat(por_uf, ignore_index=True), 'C3-13_pausas_bins_por_uf.csv'))
    return {'status': 'parcial', 'motivo': 'controle 2022 só para pausas medidas nos bins de 15 min (mesma régua nos dois anos); ritmo (LLR), eventos e '
            'alertas de 2022 exigem reler ~15–20 mil logs 7z (passada)',
            'numeros_chave': {f"{row['ano']}|{row['grupo']}": {k: row[k] for k in ('secoes', 'pausa_max_min_p50', 'pausa_max_ge60_pct',
                                                                                     'dif_pausa_max_p50_vs_vizinhas', 'p_mannwhitney_pausa_max_vs_vizinhas')}
                              for row in r.to_dict('records')},
            'arquivos': arqs}


# ----------------------------------------------------------------------------------------------- main
CHECAGENS = {'C3-01': c3_01, 'C3-02': c3_02, 'C3-07': c3_07, 'C3-03': c3_03, 'C3-06': c3_06, 'C3-09': c3_09, 'C3-15': c3_15,
             'C3-08': c3_08, 'C3-13': c3_13}
NAO_FEITAS = {
    'C3-04': 'depende da passada pesada: extrair por log (2026-T2, 2022-T2, depois T1/2024) carga, zerésima, "Urna ligada"/desligada, modo de votação, '
             'instante de cada voto (ou histograma fino de intervalos), "Encerrar votação", BU gerado/assinado, reversões em todas as linhas/apps, linhas '
             'de outro dia após a abertura, nº de dispositivos, linhas não INFO por app, reinícios, marcas de contingência; um parquet por seção e um de eventos raros',
    'C3-05': 'depende de C3-04 (instantes de voto): intervalo mínimo, P5, mediana, CV, intervalos < 30 s e < piso físico (C3-06: p0,1 da cabine), maior sequência rápida, LLR',
    'C3-10': 'depende de C3-04: monotonicidade em todas as linhas (todos os apps), saltos > 1 h, data ≠ dia após a abertura, dispositivos por log',
    'C3-11': 'exige decodificar bu_raw das 13 UFs de 2026-T2 (research/bu_urna) — passada de BUs; aplicar desloc_h de fechamento_2026t2 e repetir ordem/urna→TSE',
    'C3-12': 'exige ler o cabeçalho de cada logd.dat (modelo da urna) — incorporar à passada C3-04',
    'C3-14': 'exige reprocessar operations.jsonl das 11 UFs com o leitor aninhado (≈ 8–13 mil seções por pleito) — passada',
    'C3-16': 'depende de C3-04: linhas por nível (ALERTA/ERRO) e app, mensagens de erro durante a votação, frequência de base e CMH no prédio',
}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('checagens', nargs='*', help='ids (C3-01 …); vazio = todas')
    ap.add_argument('--resumo', default=str(OUT / 'C3_resumo.json'))
    ap.add_argument('--c3-01-pleito', help='uso interno: uma rodada de C3-01 (processo filho)')
    ap.add_argument('--mesmo-processo', action='store_true',
                    help='com várias checagens, roda todas neste processo (padrão: um processo filho por checagem, em série)')
    a = ap.parse_args(argv)
    if a.c3_01_pleito:
        _c3_01_pleito(a.c3_01_pleito)
        return 0
    ids = a.checagens or list(CHECAGENS)
    OUT.mkdir(parents=True, exist_ok=True)
    p_res = Path(a.resumo)
    if len(ids) > 1 and not a.mesmo_processo:
        # um processo por checagem, um de cada vez: a memória de uma checagem volta ao sistema antes da próxima
        import subprocess
        for cx in ids:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), cx, '--resumo', str(p_res)], check=False)
        ids = []
    resumo = json.loads(p_res.read_text(encoding='utf-8')) if p_res.exists() else {'camada': 'C3', 'checagens': {}}
    for cx in ids:
        t0 = time.time()
        print(f'== {cx}', flush=True)
        try:
            r = CHECAGENS[cx]()
        except Exception as exc:
            import traceback
            r = {'status': 'nao_feita', 'motivo': f'erro: {exc!r}', 'traceback': traceback.format_exc()[-2000:]}
        r['minutos'] = round((time.time() - t0) / 60, 2)
        r['gerado_em'] = agora()
        resumo['checagens'][cx] = r
        print(json.dumps({k: v for k, v in r.items() if k != 'traceback'}, ensure_ascii=False, default=str)[:3000], flush=True)
        p_res.write_text(json.dumps(resumo, indent=1, ensure_ascii=False, default=str), encoding='utf-8')
        gc.collect()
    for cx, motivo in NAO_FEITAS.items():
        resumo['checagens'].setdefault(cx, {'status': 'nao_feita', 'motivo': motivo})
    resumo['protocolo'] = 'relatorios/verificacoes/varredura_forense/PROTOCOLO.md v1.0'
    resumo['parser_version'] = PARSER_VERSION
    resumo['gerado_em'] = agora()
    p_res.write_text(json.dumps(resumo, indent=1, ensure_ascii=False, default=str), encoding='utf-8')
    print('resumo em', rel(p_res))


if __name__ == '__main__':
    sys.exit(main())
