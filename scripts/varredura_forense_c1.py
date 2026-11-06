"""Varredura forense — camada C1 (aquisição e formato): checagens leves sobre inventários, recibos e tabelas já existentes.

Protocolo: relatorios/verificacoes/varredura_forense/PROTOCOLO.md v1.0. Mapa: mapa/mapa_C1.json.
Checagens feitas aqui (ids do mapa):
  C1-01 tabela única de cobertura família × UF × pleito (seções × stems × BUs no HD × logs usados × assinaturas no HD
        × integridade × CEFT × perfil) com diferenças por seção
  C1-02 dossiê dos membros 'sa' (sistema de apuração) e dos membros fora do padrão nas 11 UFs com remote-inventory.json;
        contagens nacionais pelo inventário dos zips
  C1-03 universo esperado de seções por pleito (BWEB × stems × CEFT × perfil; 2026 T2: cs.json × bu_urna × secoes_t1_t2)
  C1-04 invariante aptos = comparecimento + abstenções nas famílias em disco (BWEB 2012–2026, hab_2026, bu_todos)
  C1-06 matriz de layouts por família × ano (recibos .json + esquemas parquet), formatos de urna e revisão de colunas
        renomeadas nos scripts
  C1-10 membros fora do padrão de 2026 T2 e ZZ 2022 T1 (o que o inventário e as listas locais permitem)
  C1-13 casos de prova incompleta × CEFT × BWEB × contingência
  C1-14 quarentena regional (11 linhas) × BWEB/captura regional; 189 seções MA 2022 T1 aptos presidente ≠ governador
Ficam para as passadas pesadas ou exigem rede/HDD: C1-05, C1-07, C1-08, C1-09, C1-11, C1-12, C1-15.

Saídas: relatorios/verificacoes/varredura_forense/C1/ (CSV com ';' e vírgula decimal; parquet com recibo .json ao lado),
C1_resumo.json (os achados vão no registro da varredura). Quarentena: research/varredura_forense/quarentena/rows-C1-<checagem>.json +
quarentena_C1-<checagem>.csv. Nada aqui indica irregularidade por si só ("sinalização não é acusação").
Uso: python scripts/varredura_forense_c1.py [C1-01 C1-03 ...]   (sem argumentos roda todas, em série)
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import re
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / 'research'
REL = ROOT / 'relatorios'
OUT = REL / 'verificacoes' / 'varredura_forense' / 'C1'
QUAR = R / 'varredura_forense' / 'quarentena'
PARSER_VERSION = 'varredura-forense-c1-1'
CSV_KW = dict(sep=';', decimal=',', encoding='utf-8-sig', index=False)

UFS_11 = ['BA', 'CE', 'MA', 'MG', 'PA', 'PE', 'PR', 'RJ', 'RS', 'SC', 'SP']
UFS_28 = ['AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MG', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI', 'PR',
          'RJ', 'RN', 'RO', 'RR', 'RS', 'SC', 'SE', 'SP', 'TO', 'ZZ']
UFS_T2_RESULTADOS = ['BA', 'CE', 'MG', 'PA', 'PB', 'PE', 'PI', 'PR', 'RJ', 'RN', 'RS', 'SC', 'SE', 'SP']
PLEITOS_URNA = ['2022-t1', '2022-t2', '2024-t1', '2024-t2', '2026-t1', '2026-t2']
PLEITOS_BWEB = ['2012-t1', '2012-t2', '2014-t1', '2014-t2', '2016-t1', '2016-t2', '2018-t1', '2018-t2', '2020-t1',
                '2020-t2', '2022-t1', '2022-t2', '2024-t1', '2024-t2', '2026-t1']
# família BWEB de referência (uma por pleito) para o universo de seções
CARGO_REF = {'2012': 'PREFEITO', '2014': 'PRESIDENTE', '2016': 'PREFEITO', '2018': 'PRESIDENTE', '2020': 'PREFEITO',
             '2022': 'PRESIDENTE', '2024': 'PREFEITO', '2026': 'GOVERNADOR'}
PLEITOS_BINS = {'2022-t2': R / 'janelas_horario' / 'bins_2022.parquet', '2026-t2': R / 'janelas_horario' / 'bins_2026.parquet'}

INVENTARIO = REL / 'disco' / 'inventario_zips_pais.csv'
DOWNLOAD_LOG = REL / 'disco' / 'download.log'
BWEB = R / 'bu'
BU_URNA = R / 'bu_urna'
ASSIN = R / 'assinaturas'
CEFT = R / 'ceft'
PERFIL = R / 'perfil' / '2022'
SECOES_2026 = REL / 'verificacoes' / 'virada_1t_2t_2026' / 'secoes_t1_t2.parquet'
HAB_2026 = {'2026-t1': R / 'padroes_2t' / 'hab_2026_t1.parquet', '2026-t2': R / 'padroes_2t' / 'hab_2026_t2.parquet'}
BU_TODOS_T2 = R / 'segundo_turno_2026' / 'bu_todos_decodificados.parquet'
CONFIG_CS = R / 'segundo_turno_2026' / 'config'
INTEGRIDADE = REL / 'integridade' / 'integridade_todas_urnas.parquet'
FALHAS = REL / 'integridade' / 'falhas.csv'
SEM_PROVA = REL / 'integridade' / 'casos_sem_prova_completa.csv'
COBERTURA_T2 = REL / 'verificacoes' / 'ultimo_voto_2026t2' / 'cobertura.csv'
ULTIMO_VOTO = REL / 'verificacoes' / 'ultimo_voto_2026t2' / 'ultimo_voto_por_secao.csv'
CONTINGENCIA = R / 'contingencia'
QUAR_REGIONAL = ROOT / 'storage-regional' / 'quarantine'
CAPTURAS_REGIONAIS = ROOT / 'storage-regional' / 'captures'
TSE_README = R / 'integridade' / 'tse_doc' / 'formato' / 'README.md'
C4_DIR = REL / 'verificacoes' / 'varredura_forense' / 'C4'
C2_DIR = REL / 'verificacoes' / 'varredura_forense' / 'C2'
# única listagem de pasta de logs permitida (pasta pequena, sem inventário remoto): exterior 2022 T1 (861 arquivos)
LOGS_ZZ_2022T1 = R / 'estados' / 'ZZ' / '2022-t1' / 'logs'

STEM_2022 = re.compile(r'^o\d{5}-(\d{5})(\d{4})(\d{4})$')
STEM_2024 = re.compile(r'^o\d{5}([a-z]{2})(\d{5})(\d{4})(\d{4})$', re.I)
# sufixos conhecidos (TSE, research/integridade/tse_doc/formato/README.md): VOTA/RED geram bu, imgbu, logjez, rdv, vscmr;
# o SA (sistema de apuração) gera busa, imgbusa, logsa, vscsa (e rdv). 2024/2026 usam '-<tipo>.dat/.jez/.vsc'.
SUFIXOS = [('-log.jez', 'log'), ('-vota.vsc', 'assinatura'), ('-bu.dat', 'bu'), ('-rdv.dat', 'rdv'), ('-imgbu.dat', 'imgbu'),
           ('-busa.dat', 'bu_sa'), ('-imgbusa.dat', 'imgbu_sa'), ('-logsa.jez', 'log_sa'), ('-sa.vsc', 'assinatura_sa'),
           ('.logsajez', 'log_sa'), ('.imgbusa', 'imgbu_sa'), ('.vscsa', 'assinatura_sa'), ('.busa', 'bu_sa'),
           ('.logjez', 'log'), ('.vscmr', 'assinatura'), ('.imgbu', 'imgbu'), ('.bu', 'bu'), ('.rdv', 'rdv')]
TIPOS_PADRAO = ('bu', 'imgbu', 'log', 'rdv', 'assinatura')
TIPOS_SA = ('bu_sa', 'imgbu_sa', 'log_sa', 'assinatura_sa')
# no inventário nacional (zips na versão de 28/10/2026) cada stem SA traz 4 membros fora da regex (busa, imgbusa, logsa, vscsa);
# com 4 o resíduo zera em 2022-t1/t2, 2024-t1/t2 e 2026-t1 (o rdv do SA casa com a regex padrão)
MEMBROS_SA_POR_STEM = 4
# colunas renomeadas entre anos (BWEB e CEFT)
RENOMEADAS = {'QT_ELEITORES_BIOMETRIA_NH': 'QT_ELEI_BIOM_SEM_HABILITACAO', 'DS_AGREGADAS': 'DS_SECOES_AGREGADAS',
              'DT_RECO_URNA_ESPERADA': 'DT_RECBTO_URNA_ESPERADA', 'DT_RECO_URNA_EFETIVADA': 'DT_RECBTO_URNA_EFETIVADA',
              'DS_DIVERGENCIA': 'TP_DIVERGENCIA', 'CD_FLASCARD_URNA_EFETIVADA': 'CD_FLASHCARD_URNA_EFETIVADA',
              'ANO_ELEICAO': 'AA_ELEICAO', 'DT_RECO_EFETIVADA': 'DT_RECO_URNA_EFETIVADA'}
# quarentena regional (storage-regional/quarantine): família 'detalhe/turnout'; a referência é docs/RELATORIO_EXECUCAO.md
CASOS_MA_2022 = ('2022-t1', 'MA')


# ----------------------------------------------------------------------------------------------- utilidades gerais
def con():
    c = duckdb.connect()
    c.execute("SET memory_limit='400MB'")
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
    df = df.copy()
    for c in ('municipality', 'zone', 'section'):  # chaves inteiras mesmo com nulos (evita '2011,0')
        if c in df and df[c].dtype.kind == 'f':
            df[c] = df[c].astype('Int64')
    df.to_csv(p, **CSV_KW)
    return rel(p)


def grava_parquet(df: pd.DataFrame, nome: str, inputs: list[Path]) -> str:
    """Parquet derivado com recibo <arquivo>.json ao lado {at, inputs:{caminho: sha256}, sha256, rows, bytes, parser_version}."""
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / nome
    df.to_parquet(p, index=False)
    recibo = {'at': agora(), 'inputs': {rel(i): sha256_file(i) for i in inputs if Path(i).exists()},
              'sha256': sha256_file(p), 'rows': int(len(df)), 'bytes': p.stat().st_size, 'parser_version': PARSER_VERSION}
    (OUT / (nome + '.json')).write_text(json.dumps(recibo, indent=2, ensure_ascii=False), encoding='utf-8')
    return rel(p)


def quarentena(cx: str, linhas: list[dict]) -> str | None:
    """Linhas que falham invariante: valores originais como string + reason; JSON em research/… e CSV em C1/."""
    if not linhas:
        return None
    QUAR.mkdir(parents=True, exist_ok=True)
    regs = [{k: (None if v is None or (isinstance(v, float) and np.isnan(v)) else str(v)) for k, v in r.items()}
            for r in linhas]
    (QUAR / f'rows-C1-{cx}.json').write_text(json.dumps(regs, indent=1, ensure_ascii=False), encoding='utf-8')
    return grava_csv(pd.DataFrame(regs), f'quarentena_C1-{cx}.csv')


def pq_names(p: Path) -> list[str]:
    return [f.name for f in pq.read_schema(p)]


# ----------------------------------------------------------------------------------------- nomes de membros e stems
def tipo_membro(nome: str) -> tuple[str, str]:
    """(stem, tipo) de um membro do zip oficial: tipos padrão (bu, imgbu, log, rdv, assinatura), 'sa' (bu_sa, imgbu_sa,
    log_sa, assinatura_sa), 'leiame', 'pasta' (entrada sem extensão) ou 'outro'."""
    n = PurePosixPath(str(nome).replace('\\', '/')).name
    low = n.lower()
    if low == 'leiame.pdf':
        return n, 'leiame'
    for suf, tipo in SUFIXOS:
        if low.endswith(suf):
            return n[:-len(suf)], tipo
    if '.' not in n:
        return n, 'pasta'
    return n, 'outro'


def chave_do_stem(stem: str) -> tuple[str | None, int, int, int] | None:
    """(uf ou None, município TSE, zona, seção): 2022 'o00406-MMMMMZZZZSSSS'; 2024+ 'o00453ufMMMMMZZZZSSSS'; None se inválido."""
    m = STEM_2024.match(stem)
    if m:
        return m[1].upper(), int(m[2]), int(m[3]), int(m[4])
    m = STEM_2022.match(stem)
    if m:
        return None, int(m[1]), int(m[2]), int(m[3])
    return None


def chaves_de_stems(stems, uf: str) -> pd.DataFrame:
    """DataFrame (uf, stem, municipality, zone, section, chave_ok) para uma lista de stems de uma UF."""
    rows = []
    for s in stems:
        k = chave_do_stem(s)
        if k is None:
            rows.append((uf, s, None, None, None, False))
        else:
            rows.append((k[0] or uf, s, k[1], k[2], k[3], True))
    df = pd.DataFrame(rows, columns=['uf', 'stem', 'municipality', 'zone', 'section', 'chave_ok'])
    for c in ('municipality', 'zone', 'section'):
        df[c] = df[c].astype('Int64')
    return df


def classifica_membros(nomes) -> pd.DataFrame:
    """Uma linha por stem com o conjunto de tipos presentes, flags por tipo padrão/'sa' e a lista de membros."""
    por_stem: dict[str, list[tuple[str, str]]] = {}
    extras = []
    for n in nomes:
        stem, tipo = tipo_membro(n)
        if tipo in ('leiame', 'pasta', 'outro'):
            extras.append((n, tipo))
            continue
        por_stem.setdefault(stem, []).append((n, tipo))
    rows = []
    for stem, lst in por_stem.items():
        tipos = {t for _, t in lst}
        rows.append({'stem': stem, 'n_membros': len(lst), 'tipos': ';'.join(sorted(tipos)),
                     **{f'tem_{t}': t in tipos for t in TIPOS_PADRAO}, **{f'tem_{t}': t in tipos for t in TIPOS_SA},
                     'tem_sa': any(t in tipos for t in TIPOS_SA), 'padrao_completo': all(t in tipos for t in TIPOS_PADRAO),
                     'membros': ';'.join(sorted(n for n, _ in lst))})
    df = pd.DataFrame(rows, columns=['stem', 'n_membros', 'tipos'] + [f'tem_{t}' for t in TIPOS_PADRAO + TIPOS_SA]
                      + ['tem_sa', 'padrao_completo', 'membros'])
    df.attrs['extras'] = extras
    return df


def membros_inventario_local(pleito: str, uf: str) -> list[str] | None:
    """Nomes dos membros do zip oficial (remote-inventory.json, 11 UFs) lidos por regex sobre o texto, sem json.load
    (SP 2022 T2 tem 57 MB)."""
    p = raiz_inventario(pleito, uf)
    if p is None:
        return None
    raw = (p / 'remote-inventory.json').read_text(encoding='utf-8')
    i = raw.find('"members"')
    nomes = re.findall(r'"name":\s*"([^"]+)"', raw[i:] if i >= 0 else raw)
    del raw
    return nomes


def raiz_inventario(pleito: str, uf: str) -> Path | None:
    if uf not in UFS_11:
        return None
    if pleito.startswith('2024'):
        cands = [R / 'municipais' / uf / pleito]
    elif uf == 'BA':
        cands = [R / 'piloto-ba-2022-t2' if pleito == '2022-t2' else R / 'bahia-presidente-2022-2026' / pleito,
                 R / 'estados' / uf / pleito]
    else:
        cands = [R / 'estados' / uf / pleito]
    for c in cands:
        if (c / 'remote-inventory.json').exists():
            return c
    return None


# ------------------------------------------------------------------------------------------ leitores de cada família
def stems_bu_urna(pleito: str) -> pd.DataFrame:
    """Stems de research/bu_urna/<pleito>/<UF>/part-*.parquet (só a coluna stem; nunca bu_raw) com chave de seção."""
    base = BU_URNA / pleito
    partes = []
    c = con()
    for uf in sorted(os.listdir(base)):
        d = base / uf
        if not d.is_dir() or not any(f.endswith('.parquet') for f in os.listdir(d)):
            continue
        st = c.execute("select stem from read_parquet(?)", [(d / 'part-*.parquet').as_posix()]).df()['stem'].tolist()
        partes.append(chaves_de_stems(st, uf))
    c.close()
    df = pd.concat(partes, ignore_index=True) if partes else chaves_de_stems([], 'XX')
    df['pleito'] = pleito
    return df


def secoes_bweb(pleito: str, cargo: str) -> pd.DataFrame | None:
    """Uma linha por seção (uf, municipality, zone, section) da família BWEB <pleito>/<UF>_<CARGO>.parquet, com aptos,
    comparecimento, abstenções, tipo de urna, agregadas, urna efetivada, nº de linhas e de cargos."""
    base = BWEB / pleito
    if not base.exists():
        return None
    partes = []
    c = con()
    for f in sorted(base.glob(f'*_{cargo}.parquet')):
        uf = f.name.split('_')[0]
        names = pq_names(f)
        agg = next((n for n in ('DS_SECOES_AGREGADAS', 'DS_AGREGADAS') if n in names), None)
        agg_expr = f"max(nullif({agg}, '#NULO#'))" if agg else 'cast(NULL as varchar)'
        tipo = 'max(DS_TIPO_URNA)' if 'DS_TIPO_URNA' in names else 'cast(NULL as varchar)'
        urna = 'max(NR_URNA_EFETIVADA)' if 'NR_URNA_EFETIVADA' in names else 'cast(NULL as varchar)'
        q = c.execute(f"""select '{uf}' uf, try_cast(CD_MUNICIPIO as int) municipality, try_cast(NR_ZONA as int) zone,
            try_cast(NR_SECAO as int) section, max(try_cast(QT_APTOS as bigint)) aptos,
            max(try_cast(QT_COMPARECIMENTO as bigint)) comparecimento, max(try_cast(QT_ABSTENCOES as bigint)) abstencoes,
            {tipo} tipo_urna, {agg_expr} agregadas, {urna} urna_efetivada, count(*) linhas,
            count(distinct CD_CARGO_PERGUNTA) cargos, count(*) filter (where CD_MUNICIPIO is null or NR_ZONA is null or
            NR_SECAO is null) chave_nula
            from read_parquet('{f.as_posix()}') group by 1, 2, 3, 4""").df()
        partes.append(q)
    c.close()
    if not partes:
        return None
    df = pd.concat(partes, ignore_index=True)
    df['pleito'] = pleito
    df['cargo'] = cargo
    return df


def invariante_bweb(pleito: str, cargo: str) -> pd.DataFrame | None:
    """Por seção × cargo: aptos ≠ comparecimento + abstenções, variação de aptos/comparecimento entre linhas da mesma
    seção, soma de votos ≠ comparecimento, chave nula; agregado por UF e tipo de urna, mais a lista dos casos."""
    base = BWEB / pleito
    if not base.exists():
        return None
    partes = []
    c = con()
    for f in sorted(base.glob(f'*_{cargo}.parquet')):
        uf = f.name.split('_')[0]
        names = pq_names(f)
        agg = next((n for n in ('DS_SECOES_AGREGADAS', 'DS_AGREGADAS') if n in names), None)
        agg_expr = f"max(nullif({agg}, '#NULO#'))" if agg else 'cast(NULL as varchar)'
        q = c.execute(f"""with s as (select '{uf}' uf, try_cast(CD_MUNICIPIO as int) municipality,
            try_cast(NR_ZONA as int) zone, try_cast(NR_SECAO as int) section, CD_CARGO_PERGUNTA cargo_cd,
            max(DS_CARGO_PERGUNTA) cargo_ds, max(DS_TIPO_URNA) tipo_urna, {agg_expr} agregadas,
            max(try_cast(QT_APTOS as bigint)) aptos, min(try_cast(QT_APTOS as bigint)) aptos_min,
            max(try_cast(QT_COMPARECIMENTO as bigint)) comp, min(try_cast(QT_COMPARECIMENTO as bigint)) comp_min,
            max(try_cast(QT_ABSTENCOES as bigint)) abst, min(try_cast(QT_ABSTENCOES as bigint)) abst_min,
            sum(try_cast(QT_VOTOS as bigint)) votos, count(*) linhas,
            count(*) filter (where try_cast(QT_APTOS as bigint) is null or try_cast(QT_COMPARECIMENTO as bigint) is null
              or try_cast(QT_ABSTENCOES as bigint) is null) nulos_num
            from read_parquet('{f.as_posix()}') group by 1, 2, 3, 4, 5),
            d as (select try_cast(CD_MUNICIPIO as int) municipality, try_cast(NR_ZONA as int) zone,
              try_cast(NR_SECAO as int) section, CD_CARGO_PERGUNTA cargo_cd, sum(try_cast(QT_VOTOS as bigint)) votos_dedup,
              count(*) linhas_distintas from (select distinct * from read_parquet('{f.as_posix()}')) group by 1, 2, 3, 4)
            select s.*, d.votos_dedup, d.linhas_distintas, (aptos <> comp + abst) f_aptos,
            (aptos <> aptos_min or comp <> comp_min or abst <> abst_min) f_var,
            (votos <> comp) f_votos, (d.votos_dedup <> comp) f_votos_dedup, (s.linhas <> d.linhas_distintas) f_dup,
            (s.municipality is null or s.zone is null or s.section is null) f_chave,
            (nulos_num > 0) f_nulo from s left join d on s.municipality is not distinct from d.municipality
            and s.zone is not distinct from d.zone and s.section is not distinct from d.section
            and s.cargo_cd is not distinct from d.cargo_cd""").df()
        partes.append(q)
    c.close()
    if not partes:
        return None
    df = pd.concat(partes, ignore_index=True)
    df['pleito'] = pleito
    df['cargo'] = cargo
    return df


def secoes_2026() -> pd.DataFrame:
    c = con()
    df = c.execute("""select uf, municipality, zone, section, t1_stem, t2_stem, cast(_merge as varchar) _merge, t1_aptos,
        t1_comparecimento, t2_aptos, t2_comparecimento from read_parquet(?)""", [str(SECOES_2026)]).df()
    c.close()
    return df


def secoes_bins(pleito: str) -> pd.DataFrame:
    c = con()
    df = c.execute("select uf, municipality, zone, section, n_logs, contingencia from read_parquet(?)",
                   [str(PLEITOS_BINS[pleito])]).df()
    c.close()
    return df


def integridade_por_pleito(pleito: str) -> pd.DataFrame:
    c = con()
    df = c.execute("""select uf, urna stem, canal, coalesce(log_local, false) log_local, coalesce(manifest_ok, false)
        manifest_ok, coalesce(bu_hash_ok, false) bu_hash_ok, erro from read_parquet(?) where eleicao = ?""",
                   [str(INTEGRIDADE), pleito]).df()
    c.close()
    return df


def secoes_ceft(pleito: str, uf: str) -> pd.DataFrame | None:
    p = CEFT / pleito / f'{uf}.parquet'
    if not p.exists():
        return None
    names = pq_names(p)
    if 'CD_MUNICIPIO' not in names:
        return None  # 2012–2016: colunas sem nome (c0..c26) — layout não resolvido (mapa_dados.json)
    div = next((n for n in ('TP_DIVERGENCIA', 'DS_DIVERGENCIA') if n in names), None)
    div_expr = f'max({div})' if div else 'cast(NULL as varchar)'
    c = con()
    df = c.execute(f"""select '{uf}' uf, try_cast(CD_MUNICIPIO as int) municipality, try_cast(NR_ZONA as int) zone,
        try_cast(NR_SECAO as int) section, max(NR_URNA_ESPERADA) urna_esperada, max(NR_URNA_EFETIVADA) urna_efetivada,
        max(DS_ORIGEM_VOTO) origem_voto, {div_expr} divergencia, count(*) linhas
        from read_parquet('{p.as_posix()}') group by 1, 2, 3, 4""").df()
    c.close()
    return df


def secoes_perfil(uf: str) -> pd.DataFrame | None:
    p = PERFIL / f'{uf}.parquet'
    if not p.exists():
        return None
    c = con()
    df = c.execute(f"""select '{uf}' uf, cast(municipality as int) municipality, cast(zone as int) zone,
        cast(section as int) section, max(voters) voters from read_parquet('{p.as_posix()}') group by 1, 2, 3, 4""").df()
    c.close()
    return df


def assinaturas_disco(pleito: str, uf: str) -> list[str] | None:
    """ls raso de research/assinaturas/<pleito>/<UF> (uma vez); None quando a pasta não existe."""
    d = ASSIN / pleito / uf
    if not d.is_dir():
        return None
    with os.scandir(d) as it:
        return [e.name for e in it if e.is_file()]


def ler_cs_json(path: Path, uf: str | None = None) -> pd.DataFrame:
    """Config do sistema de resultados (lista oficial de seções do 2º turno 2026, com recebimento e agregação)."""
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
    out['agregada'] = out.secao_principal.notna()
    return out


def download_concluido() -> pd.DataFrame:
    """Linhas 'CONCLUIDO' de relatorios/disco/download.log (pleito, uf, modo, erros)."""
    rows = []
    if DOWNLOAD_LOG.exists():
        for ln in DOWNLOAD_LOG.read_text(encoding='utf-8', errors='replace').splitlines():
            m = re.match(r'^(\d{4}-t\d) (\w{2}) (\w+) (JA )?CONCLUIDO(?: erros (\d+))?', ln)
            if m:
                rows.append({'pleito': m[1], 'uf': m[2], 'modo': m[3], 'erros': int(m[5]) if m[5] else None,
                             'ja': bool(m[4])})
    df = pd.DataFrame(rows, columns=['pleito', 'uf', 'modo', 'erros', 'ja'])
    # 'JA CONCLUIDO' (sem contagem de erros) só entra quando não há linha com contagem para o mesmo pleito/UF/modo
    com = df[~df.ja].drop_duplicates(['pleito', 'uf', 'modo'], keep='last')
    so_ja = df[df.ja & ~df.set_index(['pleito', 'uf', 'modo']).index.isin(com.set_index(['pleito', 'uf', 'modo']).index)]
    out = pd.concat([com, so_ja.drop_duplicates(['pleito', 'uf', 'modo'])], ignore_index=True)
    return out.drop(columns='ja')[['pleito', 'uf', 'modo', 'erros']]


# ------------------------------------------------------------------------------------------- funções puras (testáveis)
KEY = ['uf', 'municipality', 'zone', 'section']


def diferencas_chaves(a: pd.DataFrame, b: pd.DataFrame, nome_a: str, nome_b: str, chave=KEY) -> pd.DataFrame:
    """Anti-join nos dois sentidos: linhas só em a ('so_em_<a>') e só em b ('so_em_<b>'), com as chaves."""
    ka = a[chave].dropna().drop_duplicates().copy()
    kb = b[chave].dropna().drop_duplicates().copy()
    for c in chave:
        if c in ('municipality', 'zone', 'section'):
            ka[c] = ka[c].astype('int64')
            kb[c] = kb[c].astype('int64')
    m = ka.merge(kb, how='outer', on=chave, indicator=True)
    m = m[m['_merge'] != 'both'].copy()
    m['lado'] = np.where(m['_merge'] == 'left_only', f'so_em_{nome_a}', f'so_em_{nome_b}')
    m['familia_a'], m['familia_b'] = nome_a, nome_b
    return m.drop(columns='_merge').reset_index(drop=True)


def tabela_cobertura(longa: pd.DataFrame) -> pd.DataFrame:
    """Formato longo (pleito, uf, familia, n) -> largo (uma linha por pleito × uf, uma coluna por família) com razões."""
    w = longa.pivot_table(index=['pleito', 'uf'], columns='familia', values='n', aggfunc='first').reset_index()
    w.columns.name = None

    def razao(num, den):
        if num in w and den in w:
            return (w[num] / w[den]).where(w[den] > 0)
        return pd.Series(np.nan, index=w.index)

    w['r_bu_hd_x_secoes'] = razao('bu_hd', 'secoes_ref')
    w['r_bu_hd_x_bu_zip'] = razao('bu_hd', 'bu_zip')
    w['r_log_usado_x_bu_hd'] = razao('log_usado', 'bu_hd')
    w['r_assinatura_hd_x_bu_zip'] = razao('assinatura_hd', 'bu_zip')
    w['r_integridade_x_bu_hd'] = razao('integridade_manifesto', 'bu_hd')
    return w


def decompoe_outros(outros: float, urnas: float, bu: float, membros_sa_por_stem: int = 4) -> dict:
    """Decomposição do campo 'outros_arquivos' do inventário: 1 leiame + k membros 'sa' por stem sem BU padrão + resíduo
    não identificado (só a releitura do diretório central, por rede, diz o nome)."""
    if pd.isna(outros) or pd.isna(urnas) or pd.isna(bu):
        return {'leiame': np.nan, 'stems_sem_bu': np.nan, 'sa_esperados': np.nan, 'residuo': np.nan}
    stems_sem_bu = max(0, int((urnas or 0) - (bu or 0)))
    sa = membros_sa_por_stem * stems_sem_bu
    return {'leiame': 1, 'stems_sem_bu': stems_sem_bu, 'sa_esperados': sa, 'residuo': int(outros) - 1 - sa}


def diff_layout(anterior: list[str], atual: list[str], renomeadas: dict[str, str] = RENOMEADAS) -> dict:
    """Colunas adicionadas, removidas e renomeadas (pares conhecidos) entre dois layouts consecutivos."""
    a, b = set(anterior), set(atual)
    ren = [(x, y) for x, y in renomeadas.items() if x in a and y in b and x not in b and y not in a]
    ren_x = {x for x, _ in ren}
    ren_y = {y for _, y in ren}
    return {'adicionadas': sorted(b - a - ren_y), 'removidas': sorted(a - b - ren_x),
            'renomeadas': [f'{x}->{y}' for x, y in ren], 'ordem_igual': anterior == atual}


def i0(x):
    """int ou None (nulo fica nulo)."""
    return None if pd.isna(x) else int(x)


def fingerprint(colunas: list[str]) -> str:
    return hashlib.sha1(';'.join(colunas).encode('utf-8')).hexdigest()[:12]


def classifica_uso_coluna(texto: str, antiga: str, nova: str) -> str:
    """Como um script usa um par de colunas renomeadas: 'trata ambos', 'só antiga', 'só nova', 'não usa'."""
    tem_a, tem_n = antiga in texto, nova in texto
    if tem_a and tem_n:
        return 'trata ambos'
    if tem_a:
        return 'só antiga'
    if tem_n:
        return 'só nova'
    return 'não usa'


def secao_em_agregadas(texto: str, secao: int) -> bool:
    """A seção aparece na lista DS_AGREGADAS/DS_SECOES_AGREGADAS ('12', '0012', '12, 15', '#NULO#')?"""
    return any(t.isdigit() and int(t) == int(secao) for t in re.split(r'[^0-9]+', str(texto)))


def compara_cargos(pres: pd.DataFrame, gov: pd.DataFrame) -> pd.DataFrame:
    """Seções com aptos/comparecimento/abstenções diferentes entre dois cargos da mesma seção (join interno)."""
    m = pres.merge(gov, on=KEY, suffixes=('_pres', '_gov'))
    for c in ('aptos', 'comparecimento', 'abstencoes'):
        m[f'dif_{c}'] = m[f'{c}_pres'] - m[f'{c}_gov']
    m['difere'] = (m.dif_aptos != 0) | (m.dif_comparecimento != 0) | (m.dif_abstencoes != 0)
    return m


def classifica_prova(faltante: str, bweb_tipo: str | None, ceft_origem: str | None, ceft_div: str | None,
                     tem_sa: bool | None) -> str:
    """Leitura descritiva de um caso de prova incompleta a partir do que as famílias documentam (sem causa)."""
    if tem_sa:
        return 'membros SA no zip (sistema de apuração); BWEB ' + str(bweb_tipo) + '; CEFT origem ' + str(ceft_origem)
    if ceft_origem and 'apura' in str(ceft_origem).lower():
        return f'CEFT registra origem do voto "{ceft_origem}"; BWEB {bweb_tipo}'
    if ceft_div and str(ceft_div).strip() not in ('', '#NULO#', 'nan', 'None'):
        return f'CEFT registra divergência "{ceft_div}" (urna esperada ≠ efetivada); BWEB {bweb_tipo}'
    if bweb_tipo:
        return f'BWEB {bweb_tipo}; CEFT sem divergência; ausência de {faltante} não explicada pelas famílias em disco'
    return f'sem BWEB/CEFT no disco para o caso; ausência de {faltante} NOT_COMPARABLE'


# --------------------------------------------------------------------------------------------------------- C1-01
def c1_01() -> dict:
    """Tabela única de cobertura família × UF × pleito e diferenças por seção entre famílias."""
    t0 = time.time()
    inv = pd.read_csv(INVENTARIO, sep=';', encoding='utf-8-sig')
    longa, difs, resumo_difs, nao_comp = [], [], [], []

    def add(pleito, uf, familia, n, obs=''):
        longa.append({'pleito': pleito, 'uf': uf, 'familia': familia, 'n': n, 'observacao': obs})

    def registra_dif(pleito, d, nome_a, nome_b, stems_por_chave=None):
        if len(d):
            d = d.copy()
            d['pleito'] = pleito
            difs.append(d)
        for uf, g in d.groupby('uf') if len(d) else []:
            resumo_difs.append({'pleito': pleito, 'uf': uf, 'familia_a': nome_a, 'familia_b': nome_b,
                                f'so_em_{nome_a}': int((g.lado == f'so_em_{nome_a}').sum()),
                                f'so_em_{nome_b}': int((g.lado == f'so_em_{nome_b}').sum())})

    # inventário dos zips (contagens oficiais por família)
    for r in inv.itertuples():
        if r.status != 'ok':
            nao_comp.append({'pleito': r.eleicao, 'uf': r.uf, 'familia': 'zip', 'status': 'NOT_COMPARABLE',
                             'motivo': f'inventário: {str(r.status)[:80]}'})
            continue
        add(r.eleicao, r.uf, 'urnas_zip', r.urnas, 'stems distintos no zip oficial (inventario_zips_pais.csv)')
        for fam, col in (('bu_zip', 'bu_arquivos'), ('log_zip', 'log_arquivos'), ('rdv_zip', 'rdv_arquivos'),
                         ('assinatura_zip', 'assinatura_arquivos'), ('imgbu_zip', 'imgbu_arquivos'),
                         ('outros_zip', 'outros_arquivos')):
            add(r.eleicao, r.uf, fam, getattr(r, col))
    # download concluído (prova de que o HD recebeu o zip inteiro com CRC)
    dl = download_concluido()
    for r in dl.itertuples():
        add(r.pleito, r.uf, 'download_erros', r.erros, f'baixa_pais modo {r.modo} (download.log)')
    # BWEB: seções de referência por pleito (presidente/prefeito/governador conforme o ano) e todos os cargos
    bweb_ref = {}
    for pleito in PLEITOS_BWEB:
        for cargo in ('PRESIDENTE', 'GOVERNADOR', 'PREFEITO'):
            s = secoes_bweb(pleito, cargo)
            if s is None:
                continue
            for uf, g in s.groupby('uf'):
                add(pleito, uf, f'secoes_bweb_{cargo.lower()}', len(g))
            if cargo == CARGO_REF[pleito[:4]] and not pleito.startswith('2026'):
                if pleito in PLEITOS_URNA:  # só os pleitos com arquivos de urna precisam das chaves (memória)
                    bweb_ref[pleito] = s[KEY].copy()
                for uf, g in s.groupby('uf'):
                    add(pleito, uf, 'secoes_ref', len(g), f'BWEB {cargo}')
            del s
            gc.collect()
    # 2026: presidente por seção vem do BU decodificado (secoes_t1_t2) — referência para 2026-t1 e 2026-t2
    s26 = secoes_2026()
    for turno, col in (('2026-t1', 't1_stem'), ('2026-t2', 't2_stem')):
        g = s26[s26[col].notna()]
        for uf, gg in g.groupby('uf'):
            add(turno, uf, 'secoes_ref', len(gg), 'secoes_t1_t2.parquet (BU decodificado)')
        bweb_ref[turno] = g[KEY].copy()
        if turno == '2026-t1':
            # governador BWEB 2026-t1 (10 UFs) × seções do BU decodificado
            gov = secoes_bweb('2026-t1', 'GOVERNADOR')
            if gov is not None:
                d = diferencas_chaves(g[g.uf.isin(gov.uf.unique())], gov, 'secoes_bu_2026t1', 'bweb_governador_2026t1')
                registra_dif('2026-t1', d, 'secoes_bu_2026t1', 'bweb_governador_2026t1')
                del gov
    for turno in ('2026-t1', '2026-t2'):
        c = con()
        h = c.execute("select uf, count(*) n from read_parquet(?) group by 1", [str(HAB_2026[turno])]).df()
        c.close()
        for r in h.itertuples():
            add(turno, r.uf, 'hab_2026', r.n, 'hab_2026_t<turno>.parquet')
    # famílias por pleito de urna
    for pleito in PLEITOS_URNA:
        bu = stems_bu_urna(pleito)
        for uf, g in bu.groupby('uf'):
            add(pleito, uf, 'bu_hd', len(g), 'linhas em research/bu_urna (stems)')
            add(pleito, uf, 'bu_hd_chave_invalida', int((~g.chave_ok).sum()))
        bu_ok = bu[bu.chave_ok]
        # seções de referência × BU no HD
        if pleito in bweb_ref:
            ref = bweb_ref[pleito]
            ufs_ref = set(ref.uf.unique())
            d = diferencas_chaves(ref, bu_ok[bu_ok.uf.isin(ufs_ref)], 'secoes_ref', 'bu_hd')
            d = d.merge(bu_ok[KEY + ['stem']], on=KEY, how='left')
            registra_dif(pleito, d, 'secoes_ref', 'bu_hd')
            for uf in sorted(set(bu_ok.uf.unique()) - ufs_ref):
                nao_comp.append({'pleito': pleito, 'uf': uf, 'familia': 'secoes_ref', 'status': 'NOT_COMPARABLE',
                                 'motivo': 'sem BWEB de referência no disco para esta UF/pleito'})
        # logs usados (bins) × BU no HD
        if pleito in PLEITOS_BINS:
            b = secoes_bins(pleito)
            for uf, g in b.groupby('uf'):
                add(pleito, uf, 'log_usado', len(g), 'seções em bins_<ano>.parquet (log lido, erro = 0)')
                add(pleito, uf, 'log_contingencia', int(g.contingencia.sum()))
                add(pleito, uf, 'logs_lidos', int(g.n_logs.sum()), 'soma de n_logs (inclui aninhados)')
            d = diferencas_chaves(bu_ok, b, 'bu_hd', 'bins')
            registra_dif(pleito, d, 'bu_hd', 'bins')
            del b
        # integridade (11 UFs dados abertos; 2026-t2: 14 UFs canal sistema de resultados)
        it = integridade_por_pleito(pleito)
        if len(it):
            for uf, g in it.groupby('uf'):
                add(pleito, uf, 'integridade_urnas', len(g), f"canal {';'.join(sorted(g.canal.dropna().unique()))}")
                add(pleito, uf, 'integridade_log_local', int(g.log_local.sum()))
                add(pleito, uf, 'integridade_manifesto', int(g.manifest_ok.sum()))
                add(pleito, uf, 'integridade_bu_hash_ok', int(g.bu_hash_ok.sum()))
            if pleito != '2026-t2':
                ufs_it = set(it.uf.unique())
                d = diferencas_chaves(bu_ok[bu_ok.uf.isin(ufs_it)], it, 'bu_hd', 'integridade', chave=['uf', 'stem'])
                registra_dif(pleito, d, 'bu_hd', 'integridade')
            for uf in sorted(set(bu_ok.uf.unique()) - set(it.uf.unique())):
                nao_comp.append({'pleito': pleito, 'uf': uf, 'familia': 'integridade', 'status': 'NOT_COMPARABLE',
                                 'motivo': 'UF fora do escopo da integridade (nunca verificada)'})
            if pleito not in PLEITOS_BINS:
                for uf in sorted(set(bu_ok.uf.unique()) - set(it.uf.unique())):
                    nao_comp.append({'pleito': pleito, 'uf': uf, 'familia': 'log_hd', 'status': 'NOT_COMPARABLE',
                                     'motivo': 'logs no HD não contados (sem índice local; HDD não percorrido); '
                                               'evidência só do download.log (CRC por membro)'})
        del it
        # assinaturas no HD (ls raso) × BU no HD
        for uf in sorted(bu_ok.uf.unique()):
            nomes = assinaturas_disco(pleito, uf)
            if nomes is None:
                nao_comp.append({'pleito': pleito, 'uf': uf, 'familia': 'assinatura_hd', 'status': 'NOT_COMPARABLE',
                                 'motivo': 'sem pasta research/assinaturas/<pleito>/<UF> (UF conferida em streaming '
                                           'pela integridade ou nunca baixada)'})
                continue
            st = [tipo_membro(n) for n in nomes]
            stems = [s for s, t in st if t == 'assinatura']
            add(pleito, uf, 'assinatura_hd', len(stems), 'arquivos .vscmr/-vota.vsc em research/assinaturas (ls raso)')
            outros = [n for n, (s, t) in zip(nomes, st) if t != 'assinatura']
            if outros:
                add(pleito, uf, 'assinatura_hd_outros', len(outros), ';'.join(outros[:5]))
            a = pd.DataFrame({'uf': uf, 'stem': stems})
            d = diferencas_chaves(bu_ok[bu_ok.uf == uf], a, 'bu_hd', 'assinatura_hd', chave=['uf', 'stem'])
            registra_dif(pleito, d, 'bu_hd', 'assinatura_hd')
        # CEFT (11 UFs) × BU no HD
        for uf in UFS_11:
            cf = secoes_ceft(pleito, uf)
            if cf is None:
                continue
            add(pleito, uf, 'ceft', len(cf), 'seções na CEFT (correspondências efetivadas)')
            d = diferencas_chaves(bu_ok[bu_ok.uf == uf], cf, 'bu_hd', 'ceft')
            registra_dif(pleito, d, 'bu_hd', 'ceft')
            del cf
        if pleito == '2022-t2':
            for uf in UFS_11:
                pf = secoes_perfil(uf)
                if pf is None:
                    continue
                add('2022-t1', uf, 'perfil_2022', len(pf), 'perfil_eleitor_secao 2022 (research/perfil/2022)')
                add('2022-t2', uf, 'perfil_2022', len(pf))
                d = diferencas_chaves(bu_ok[bu_ok.uf == uf], pf, 'bu_hd', 'perfil_2022')
                registra_dif(pleito, d, 'bu_hd', 'perfil_2022')
                del pf
        if pleito == '2026-t2':
            cob = pd.read_csv(COBERTURA_T2, sep=';', encoding='utf-8-sig')
            for r in cob.itertuples():
                add(pleito, r.uf, 'log_usado_cobertura_csv', r.com_log_usado, 'ultimo_voto_2026t2/cobertura.csv')
            uv = pd.read_csv(ULTIMO_VOTO, sep=';', decimal=',', encoding='utf-8-sig',
                             usecols=['uf', 'municipality', 'zone', 'section', 'erro_log', 'votos_log'])
            for uf, g in uv.groupby('uf'):
                add(pleito, uf, 'ultimo_voto_secoes', len(g), 'ultimo_voto_por_secao.csv')
                add(pleito, uf, 'ultimo_voto_erro_log', int(g.erro_log.notna().sum()))
            uv2 = uv.dropna(subset=['municipality', 'zone', 'section']).copy()
            for c in ('municipality', 'zone', 'section'):
                uv2[c] = uv2[c].astype('int64')
            d = diferencas_chaves(bu_ok, uv2, 'bu_hd', 'ultimo_voto')
            registra_dif(pleito, d, 'bu_hd', 'ultimo_voto')
            del uv, uv2
            # lista oficial do sistema de resultados (cs.json) por UF
            for f in sorted(CONFIG_CS.glob('*-cs.json')):
                cs = ler_cs_json(f, f.name[:2])
                add(pleito, f.name[:2].upper(), 'cs_json_secoes', len(cs))
                add(pleito, f.name[:2].upper(), 'cs_json_agregadas', int(cs.agregada.sum()))
        del bu, bu_ok
        gc.collect()
    longa_df = pd.DataFrame(longa)
    larga = tabela_cobertura(longa_df)
    nc = pd.DataFrame(nao_comp, columns=['pleito', 'uf', 'familia', 'status', 'motivo'])
    difs_df = pd.concat(difs, ignore_index=True) if difs else pd.DataFrame(columns=KEY + ['lado', 'familia_a', 'familia_b', 'pleito'])
    rd = pd.DataFrame(resumo_difs)
    arqs = [grava_csv(longa_df, 'C1-01_cobertura_longa.csv'), grava_csv(larga, 'C1-01_cobertura_familia_uf_pleito.csv'),
            grava_csv(difs_df, 'C1-01_diferencas_secoes.csv'), grava_csv(rd, 'C1-01_diferencas_resumo.csv'),
            grava_csv(nc, 'C1-01_nao_comparaveis.csv')]
    chave = {'linhas_cobertura_longa': int(len(longa_df)), 'pleito_uf': int(len(larga)),
             'diferencas_secoes': int(len(difs_df)), 'nao_comparaveis': int(len(nc)),
             'diferencas_por_par': {f'{k[0]} {k[1]}×{k[2]}': int(v) for k, v in
                                    difs_df.groupby(['pleito', 'familia_a', 'familia_b']).size().items()} if len(difs_df) else {},
             'bu_hd_total_por_pleito': {p: int(v) for p, v in longa_df[longa_df.familia == 'bu_hd'].groupby('pleito').n.sum().items()},
             'secoes_ref_total_por_pleito': {p: int(v) for p, v in longa_df[longa_df.familia == 'secoes_ref'].groupby('pleito').n.sum().items()},
             'assinatura_hd_por_pleito': {p: int(v) for p, v in longa_df[longa_df.familia == 'assinatura_hd'].groupby('pleito').n.sum().items()},
             'minutos': round((time.time() - t0) / 60, 2)}
    return {'status': 'feita', 'motivo': '', 'numeros_chave': chave, 'arquivos': arqs}


# --------------------------------------------------------------------------------------------------------- C1-02
def situacao_bweb_lote(pleito: str, uf: str, chaves: pd.DataFrame) -> pd.DataFrame:
    """BWEB (cargo de referência do ano) para um lote de seções: tipo de urna, aptos, comparecimento, agregadas."""
    cargo = CARGO_REF[pleito[:4]]
    p = BWEB / pleito / f'{uf}_{cargo}.parquet'
    if not p.exists() or chaves.empty:
        return chaves.assign(bweb='sem BWEB no disco para este pleito/UF')
    s = secoes_bweb_uf_arquivo(p, uf).drop(columns=['cargos', 'chave_nula'])
    s = s.rename(columns={c: f'bweb_{c}' for c in s.columns if c not in KEY}).rename(columns={'bweb_urna_efetivada': 'bweb_urna'})
    m = int_keys(chaves).merge(int_keys(s), on=KEY, how='left')
    m['bweb'] = np.where(m.bweb_linhas.notna(), 'presente', 'seção ausente do BWEB')
    return m.drop(columns=['bweb_linhas'])


def int_keys(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in ('municipality', 'zone', 'section'):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors='coerce').astype('Int64')  # nulo fica nulo (stem fora do padrão)
    return df


def ceft_prefixada(cf: pd.DataFrame) -> pd.DataFrame:
    return int_keys(cf).rename(columns={c: f'ceft_{c}' for c in cf.columns if c not in KEY})


def secoes_bweb_uf_arquivo(p: Path, uf: str) -> pd.DataFrame:
    names = pq_names(p)
    agg = next((n for n in ('DS_SECOES_AGREGADAS', 'DS_AGREGADAS') if n in names), None)
    agg_expr = f"max(nullif({agg}, '#NULO#'))" if agg else 'cast(NULL as varchar)'
    c = con()
    df = c.execute(f"""select '{uf}' uf, try_cast(CD_MUNICIPIO as int) municipality, try_cast(NR_ZONA as int) zone,
        try_cast(NR_SECAO as int) section, max(try_cast(QT_APTOS as bigint)) aptos,
        max(try_cast(QT_COMPARECIMENTO as bigint)) comparecimento, max(try_cast(QT_ABSTENCOES as bigint)) abstencoes,
        max(DS_TIPO_URNA) tipo_urna, {agg_expr} agregadas, max(NR_URNA_EFETIVADA) urna_efetivada, count(*) linhas,
        count(distinct CD_CARGO_PERGUNTA) cargos, 0 chave_nula from read_parquet('{p.as_posix()}') group by 1, 2, 3, 4""").df()
    c.close()
    return df


def c1_02() -> dict:
    """Membros 'sa' e fora do padrão nos remote-inventory.json das 11 UFs; contagens nacionais pelo inventário."""
    t0 = time.time()
    por_uf, stems_sa, extras_rows = [], [], []
    for pleito in PLEITOS_URNA:
        for uf in UFS_11:
            nomes = membros_inventario_local(pleito, uf)
            if nomes is None:
                por_uf.append({'pleito': pleito, 'uf': uf, 'status': 'NOT_COMPARABLE',
                               'motivo': 'sem remote-inventory.json no disco'})
                continue
            m = classifica_membros(nomes)
            extras = m.attrs['extras']
            for n, t in extras:
                extras_rows.append({'pleito': pleito, 'uf': uf, 'membro': n, 'tipo': t})
            # imgbu fica fora do critério: os remote-inventory de 2026-t1 são anteriores à republicação de 22/10/2026,
            # que só acrescentou -imgbu.dat (zips_republicados.csv); a falta de imgbu é contada à parte (stems_sem_imgbu)
            sa = m[m.tem_sa | ~(m.tem_bu & m.tem_log & m.tem_rdv & m.tem_assinatura)]
            por_uf.append({'pleito': pleito, 'uf': uf, 'status': 'ok', 'membros': len(nomes), 'stems': len(m),
                           'stems_padrao_completo': int(m.padrao_completo.sum()), 'stems_com_sa': int(m.tem_sa.sum()),
                           'stems_sem_bu_padrao': int((~m.tem_bu).sum()), 'stems_sem_log_padrao': int((~m.tem_log).sum()),
                           'stems_sem_rdv': int((~m.tem_rdv).sum()), 'stems_sem_assinatura_padrao': int((~m.tem_assinatura).sum()),
                           'stems_sem_imgbu': int((~m.tem_imgbu).sum()), 'extras_leiame': sum(t == 'leiame' for _, t in extras),
                           'extras_pasta': sum(t == 'pasta' for _, t in extras), 'extras_outro': sum(t == 'outro' for _, t in extras)})
            if len(sa):
                k = chaves_de_stems(sa.stem.tolist(), uf)
                k = k.merge(sa, on='stem')
                k['pleito'] = pleito
                stems_sa.append(k)
            del m, nomes
            gc.collect()
    cols = ['pleito', 'uf', 'stem', 'municipality', 'zone', 'section', 'tipos', 'tem_sa', 'padrao_completo', 'membros']
    sa_df = pd.concat(stems_sa, ignore_index=True)[cols] if stems_sa else pd.DataFrame(columns=cols)
    # cruzamento com BWEB, CEFT e integridade (lote por pleito/UF)
    enriq = []
    for (pleito, uf), g in sa_df.groupby(['pleito', 'uf']):
        g = int_keys(g)
        b = situacao_bweb_lote(pleito, uf, g[KEY].drop_duplicates())
        g = g.merge(b, on=KEY, how='left')
        cf = secoes_ceft(pleito, uf)
        if cf is None:
            g['ceft'] = 'sem CEFT no disco'
        else:
            g = g.merge(ceft_prefixada(cf), on=KEY, how='left')
            g['ceft'] = np.where(g.ceft_linhas.notna(), 'presente', 'seção ausente da CEFT')
        it = integridade_por_pleito(pleito)
        it = it[it.uf == uf][['stem', 'log_local', 'manifest_ok', 'erro']].rename(columns={'erro': 'integridade_erro'})
        g = g.merge(it, on='stem', how='left')
        g['integridade'] = np.where(g.manifest_ok.notna(), 'presente', 'urna não está na tabela de integridade')
        enriq.append(g)
    sa_enr = pd.concat(enriq, ignore_index=True) if enriq else sa_df
    # país: inventário (urnas − bu, outros)
    inv = pd.read_csv(INVENTARIO, sep=';', encoding='utf-8-sig')
    pais = []
    for r in inv.itertuples():
        d = decompoe_outros(r.outros_arquivos, r.urnas, r.bu_arquivos,
                            membros_sa_por_stem=MEMBROS_SA_POR_STEM)
        pais.append({'pleito': r.eleicao, 'uf': r.uf, 'status': r.status if r.status == 'ok' else 'NOT_COMPARABLE',
                     'urnas': r.urnas, 'bu': r.bu_arquivos, 'log': r.log_arquivos, 'rdv': r.rdv_arquivos,
                     'assinatura': r.assinatura_arquivos, 'outros': r.outros_arquivos, **d,
                     'tem_remote_inventory': r.uf in UFS_11 and raiz_inventario(r.eleicao, r.uf) is not None})
    pais_df = pd.DataFrame(pais)
    # trecho da documentação TSE sobre o SA (texto, não inferência)
    doc = ''
    if TSE_README.exists():
        txt = TSE_README.read_text(encoding='utf-8', errors='replace')
        i = txt.find('Sistema de apura')
        doc = re.sub(r'\s+', ' ', txt[i:i + 140]) if i >= 0 else ''
    arqs = [grava_csv(pd.DataFrame(por_uf), 'C1-02_membros_por_pleito_uf_11ufs.csv'),
            grava_csv(sa_enr, 'C1-02_stems_sa_ou_incompletos_11ufs.csv'),
            grava_csv(pd.DataFrame(extras_rows, columns=['pleito', 'uf', 'membro', 'tipo']), 'C1-02_membros_extras_11ufs.csv'),
            grava_csv(pais_df, 'C1-02_inventario_pais_decomposicao_outros.csv')]
    chave = {'pastas_com_inventario': int(sum(1 for r in por_uf if r.get('status') == 'ok')),
             'stems_sa_ou_incompletos_11ufs': int(len(sa_df)), 'stems_com_sa_11ufs': int(sa_df.tem_sa.sum()) if len(sa_df) else 0,
             'por_pleito': {p: int(v) for p, v in sa_df.groupby('pleito').size().items()} if len(sa_df) else {},
             'tipos': sa_df.tipos.value_counts().to_dict() if len(sa_df) else {},
             'bweb_tipo_urna': sa_enr.bweb_tipo_urna.value_counts(dropna=False).astype(int).to_dict() if 'bweb_tipo_urna' in sa_enr else {},
             'ceft_origem_voto': sa_enr.ceft_origem_voto.value_counts(dropna=False).astype(int).to_dict() if 'ceft_origem_voto' in sa_enr else {},
             'pais_stems_sem_bu_por_pleito': {p: int(v) for p, v in pais_df.groupby('pleito').stems_sem_bu.sum().items()},
             'pais_residuo_outros_por_pleito': {p: int(v) for p, v in pais_df.groupby('pleito').residuo.sum().items()},
             'documentacao_tse_sa': doc, 'minutos': round((time.time() - t0) / 60, 2)}
    return {'status': 'parcial', 'motivo': 'nomes dos membros só existem no disco para as 11 UFs (remote-inventory.json); '
            'nas demais UFs e em 2026-t2 só as contagens do inventário (nomes exigem releitura do diretório central, rede)',
            'numeros_chave': chave, 'arquivos': arqs}


# --------------------------------------------------------------------------------------------------------- C1-03
DIVERGENCIA_MARCAS = {'**', '*', 'C', 'S', 'SIM'}


def divergencia_marcada(v) -> bool:
    """CEFT: DS_DIVERGENCIA ('**'/'*', 2012–2022) ou TP_DIVERGENCIA ('C', 2024+) marca urna esperada ≠ efetivada;
    '#NULO#'/nulo = sem divergência."""
    return v is not None and not (isinstance(v, float) and np.isnan(v)) and str(v).strip().upper() in DIVERGENCIA_MARCAS


def marca_agregadas(bw: pd.DataFrame, chaves: pd.DataFrame) -> np.ndarray:
    """Para cada linha de `chaves`, True se a seção aparece na lista de agregadas (DS_AGREGADAS) de alguma seção do
    BWEB no mesmo município e zona."""
    lista = set()
    for r in bw[bw.agregadas.notna()].itertuples():
        for tok in re.split(r'[^0-9]+', str(r.agregadas)):
            if tok.isdigit():
                lista.add((int(r.municipality), int(r.zone), int(tok)))
    return np.array([(int(m), int(z), int(s)) in lista for m, z, s in zip(chaves.municipality, chaves.zone, chaves.section)],
                    dtype=bool)


def ceft_origem_divergencia() -> pd.DataFrame:
    """Série de controle 2018–2026 (11 UFs): seções na CEFT, origem do voto (SA, RED) e divergência urna esperada ×
    efetivada."""
    rows = []
    for pleito in sorted(os.listdir(CEFT)):
        for uf in UFS_11:
            cf = secoes_ceft(pleito, uf)
            if cf is None:
                continue
            ov = cf.origem_voto.fillna('')
            rows.append({'pleito': pleito, 'uf': uf, 'secoes': len(cf),
                         'origem_sa': int(ov.str.contains('apura', case=False).sum()),
                         'origem_red': int(ov.str.contains('RED').sum()),
                         'divergencia': int(cf.divergencia.map(divergencia_marcada).sum())})
    df = pd.DataFrame(rows)
    if len(df):
        df['pct_divergencia'] = 100 * df.divergencia / df.secoes
    return df


def c1_03() -> dict:
    """Universo esperado de seções: BWEB × stems × CEFT × perfil; 2026 T2: cs.json × bu_urna × secoes_t1_t2."""
    t0 = time.time()
    resumo, fora, perfil_fora = [], [], []
    sa = None
    p_sa = OUT / 'C1-02_stems_sa_ou_incompletos_11ufs.csv'
    if p_sa.exists():
        sa = pd.read_csv(p_sa, sep=';', decimal=',', encoding='utf-8-sig')

    def classifica(row, pleito):
        if sa is not None and len(sa):
            hit = sa[(sa.pleito == pleito) & (sa.uf == row['uf']) & (sa.municipality == row['municipality'])
                     & (sa.zone == row['zone']) & (sa.section == row['section'])]
            if len(hit):
                return f"membros no zip: {hit.iloc[0]['tipos']}"
        tipo = str(row.get('tipo_urna') or '').upper()
        agreg = pd.notna(row.get('agregadas')) and str(row.get('agregadas')) not in ('', 'nan')
        if tipo or agreg:
            return f"sem stem no zip; BWEB tipo de urna {tipo or '?'}" + ('; seção principal com agregadas' if agreg else '')
        return 'sem classificação pelas famílias em disco'

    for pleito in PLEITOS_URNA:
        bu = stems_bu_urna(pleito)
        bu = bu[bu.chave_ok]
        cargo = CARGO_REF[pleito[:4]]
        bw = secoes_bweb(pleito, cargo) if not pleito.startswith('2026') else None
        if pleito.startswith('2026'):
            s26 = secoes_2026()
            col = 't1_stem' if pleito == '2026-t1' else 't2_stem'
            bw = s26[s26[col].notna()][KEY].copy()
            bw['tipo_urna'] = None
            bw['agregadas'] = None
            del s26
        for uf in sorted(set(bu.uf.unique()) | set(bw.uf.unique() if bw is not None else [])):
            r = {'pleito': pleito, 'uf': uf, 'fonte_ref': f'BWEB {cargo}' if not pleito.startswith('2026') else 'secoes_t1_t2',
                 'n_ref': int((bw.uf == uf).sum()) if bw is not None else None, 'n_bu_hd': int((bu.uf == uf).sum())}
            if bw is not None and (bw.uf == uf).any():
                d = diferencas_chaves(bw[bw.uf == uf], bu[bu.uf == uf], 'ref', 'bu_hd')
                r['ref_sem_bu'] = int((d.lado == 'so_em_ref').sum())
                r['bu_sem_ref'] = int((d.lado == 'so_em_bu_hd').sum())
                if len(d):
                    d = d.merge(bw[KEY + ['tipo_urna', 'agregadas']], on=KEY, how='left')
                    d['pleito'] = pleito
                    d['classe'] = [classifica(x, pleito) for _, x in d.iterrows()]
                    fora.append(d)
            else:
                r['status'] = 'NOT_COMPARABLE: UF sem família de referência no disco'
            cf = secoes_ceft(pleito, uf) if uf in UFS_11 else None
            if cf is not None:
                r['n_ceft'] = len(cf)
                d = diferencas_chaves(bu[bu.uf == uf], cf, 'bu_hd', 'ceft')
                r['bu_sem_ceft'] = int((d.lado == 'so_em_bu_hd').sum())
                r['ceft_sem_bu'] = int((d.lado == 'so_em_ceft').sum())
                if bw is not None and (bw.uf == uf).any():
                    d2 = diferencas_chaves(bw[bw.uf == uf], cf, 'ref', 'ceft')
                    r['ref_sem_ceft'] = int((d2.lado == 'so_em_ref').sum())
                    r['ceft_sem_ref'] = int((d2.lado == 'so_em_ceft').sum())
                    if len(d2):
                        d2['pleito'] = pleito
                        d2['classe'] = 'diferença BWEB × CEFT'
                        fora.append(d2)
                ov = cf.origem_voto.fillna('')
                r['ceft_origem_sa'] = int(ov.str.contains('apura', case=False).sum())
                r['ceft_origem_red'] = int(ov.str.contains('RED', case=True).sum())
                r['ceft_divergencia'] = int(cf.divergencia.map(divergencia_marcada).sum())
            elif uf in UFS_11:
                r['ceft'] = 'sem CEFT no disco (ou layout sem nome 2012–2016)'
            if pleito == '2022-t1' and uf in UFS_11:
                pf = secoes_perfil(uf)
                if pf is not None:
                    r['n_perfil_2022'] = len(pf)
                    d = diferencas_chaves(bw[bw.uf == uf], pf, 'ref', 'perfil')
                    r['ref_sem_perfil'] = int((d.lado == 'so_em_ref').sum())
                    r['perfil_sem_ref'] = int((d.lado == 'so_em_perfil').sum())
                    so_pf = d[d.lado == 'so_em_perfil']
                    ag = marca_agregadas(bw[bw.uf == uf], so_pf)
                    r['perfil_sem_ref_listada_em_agregadas'] = int(ag.sum())
                    so_ref = d[d.lado == 'so_em_ref'].merge(bw[KEY + ['tipo_urna', 'agregadas']], on=KEY, how='left')
                    r['ref_sem_perfil_tipos'] = ';'.join(f'{k}={v}' for k, v in
                                                         so_ref.tipo_urna.fillna('?').value_counts().items())
                    if len(so_pf):
                        perfil_fora.append(so_pf.assign(
                            pleito='2022', classe=np.where(ag, 'perfil: seção listada como agregada no BWEB',
                                                           'perfil: seção sem BU e não listada como agregada')))
                    if len(so_ref):
                        perfil_fora.append(so_ref.assign(pleito='2022', classe='BWEB: seção sem linha no perfil do eleitorado'))
            if pleito == '2026-t2':
                f = CONFIG_CS / f'{uf}-cs.json'
                if f.exists():
                    cs = ler_cs_json(f, uf)
                    r['n_cs_json'] = len(cs)
                    r['cs_agregadas'] = int(cs.agregada.sum())
                    d = diferencas_chaves(cs[~cs.agregada], bu[bu.uf == uf], 'cs_nao_agregada', 'bu_hd')
                    r['cs_nao_agregada_sem_bu'] = int((d.lado == 'so_em_cs_nao_agregada').sum())
                    r['bu_sem_cs'] = int((d.lado == 'so_em_bu_hd').sum())
                    if len(d):
                        d = d.merge(cs[KEY + ['recebido_em', 'municipio']], on=KEY, how='left')
                        d['pleito'] = pleito
                        d['classe'] = np.where(d.recebido_em.fillna('').str.len() > 0,
                                               'esperada com recebimento registrado e sem BU no zip', 'esperada sem recebimento e sem BU')
                        fora.append(d)
            resumo.append(r)
        del bu, bw
        gc.collect()
    # pleitos só com BWEB (2012–2020): o universo é o próprio BWEB; registrar seções com chave nula ou cargos múltiplos
    for pleito in [p for p in PLEITOS_BWEB if p[:4] < '2022']:
        s = secoes_bweb(pleito, CARGO_REF[pleito[:4]])
        if s is None:
            continue
        for uf, g in s.groupby('uf'):
            resumo.append({'pleito': pleito, 'uf': uf, 'fonte_ref': f'BWEB {CARGO_REF[pleito[:4]]}', 'n_ref': len(g),
                           'n_bu_hd': None, 'status': 'NOT_COMPARABLE: TSE não publica arquivos de urna antes de 2022',
                           'chave_nula': int(g.chave_nula.sum()), 'secoes_agregadas_principais': int(g.agregadas.notna().sum())})
        del s
    res = pd.DataFrame(resumo)
    fora_df = pd.concat(fora, ignore_index=True) if fora else pd.DataFrame(columns=KEY + ['lado', 'familia_a', 'familia_b', 'pleito', 'classe'])
    pf_df = pd.concat(perfil_fora, ignore_index=True) if perfil_fora else pd.DataFrame()
    cs_ceft = ceft_origem_divergencia()
    arqs = [grava_csv(res, 'C1-03_universo_por_pleito_uf.csv'), grava_csv(fora_df, 'C1-03_secoes_so_de_um_lado.csv'),
            grava_csv(pf_df, 'C1-03_perfil2022_x_bweb_secoes.csv'),
            grava_csv(cs_ceft, 'C1-03_ceft_origem_divergencia_por_pleito.csv')]
    tot = {}
    for pleito, g in res.groupby('pleito'):
        tot[pleito] = {k: int(g[k].sum()) for k in ('n_ref', 'n_bu_hd', 'ref_sem_bu', 'bu_sem_ref', 'n_ceft', 'bu_sem_ceft',
                                                   'ceft_sem_bu', 'ref_sem_ceft', 'ceft_sem_ref', 'n_cs_json', 'cs_agregadas',
                                                   'cs_nao_agregada_sem_bu', 'bu_sem_cs', 'ceft_origem_sa', 'ceft_origem_red',
                                                   'ceft_divergencia', 'n_perfil_2022', 'ref_sem_perfil', 'perfil_sem_ref',
                                                   'perfil_sem_ref_listada_em_agregadas') if k in g and g[k].notna().any()}
    ceft_tot = cs_ceft.groupby('pleito')[['secoes', 'origem_sa', 'origem_red', 'divergencia']].sum()
    chave = {'por_pleito': tot, 'secoes_so_de_um_lado': int(len(fora_df)),
             'ceft_por_pleito_11ufs': {k: {c: int(v) for c, v in r.items()} for k, r in ceft_tot.iterrows()},
             'perfil_classes': pf_df.classe.value_counts().to_dict() if len(pf_df) else {},
             'classes': fora_df.classe.value_counts().to_dict() if len(fora_df) else {},
             'minutos': round((time.time() - t0) / 60, 2)}
    return {'status': 'feita', 'motivo': 'CEFT só nas 11 UFs (2018+); perfil só 2022/11 UFs; cs.json só 2026 T2',
            'numeros_chave': chave, 'arquivos': arqs}


# --------------------------------------------------------------------------------------------------------- C1-04
def c1_04() -> dict:
    """Invariante aptos = comparecimento + abstenções (e afins) em todos os BWEB em disco, hab_2026 e bu_todos."""
    t0 = time.time()
    por_uf, casos = [], []
    for pleito in PLEITOS_BWEB:
        for cargo in ('PRESIDENTE', 'GOVERNADOR', 'PREFEITO'):
            d = invariante_bweb(pleito, cargo)
            if d is None:
                continue
            flags = ['f_aptos', 'f_var', 'f_votos', 'f_votos_dedup', 'f_dup', 'f_chave', 'f_nulo']
            for (uf, tipo), g in d.groupby(['uf', d.tipo_urna.fillna('(sem DS_TIPO_URNA)')]):
                por_uf.append({'pleito': pleito, 'cargo': cargo, 'uf': uf, 'tipo_urna': tipo, 'secoes': len(g),
                               'agregadas_principais': int(g.agregadas.notna().sum()),
                               **{f: int(g[f].fillna(False).sum()) for f in flags}})
            # quarentena: só o que falha depois de remover linhas duplicadas exatas (a duplicação é registrada por arquivo)
            bad = d[d[['f_aptos', 'f_var', 'f_votos_dedup', 'f_chave', 'f_nulo']].fillna(False).any(axis=1)]
            if len(bad):
                casos.append(bad)
            del d
            gc.collect()
    por_uf_df = pd.DataFrame(por_uf)
    casos_df = pd.concat(casos, ignore_index=True) if casos else pd.DataFrame()
    # 2026 (BU decodificado): hab_0 + hab_1 + hab_2 = comparecimento_bu; comparecimento ≤ aptos; T2 bu_todos (14 UFs)
    c = con()
    h26 = {}
    for turno, p in HAB_2026.items():
        h26[turno] = c.execute("""select count(*) n, count(*) filter (where hab_0 + hab_1 + hab_2 <> comparecimento_bu) f_hab,
            count(*) filter (where hab_0 is null or hab_1 is null or hab_2 is null or comparecimento_bu is null) f_nulo
            from read_parquet(?)""", [str(p)]).df().iloc[0].to_dict()
        h26[turno] = {k: int(v) for k, v in h26[turno].items()}
    s26 = c.execute("""select count(*) n, count(*) filter (where t1_stem is not null and t1_comparecimento > t1_aptos) f_t1_comp_gt_aptos,
        count(*) filter (where t2_comparecimento > t2_aptos) f_t2_comp_gt_aptos,
        count(*) filter (where t1_stem is not null and t1_v13 + t1_v14 + t1_v22 + t1_v55 + t1_v70 + t1_branco + t1_nulo + t1_v27
          + t1_v16 + t1_v30 + t1_v80 + t1_v29 + t1_v35 + t1_v21 + t1_v28 <> t1_comparecimento) f_t1_votos_ne_comp,
        count(*) filter (where t2_v13 + t2_v22 + t2_branco + t2_nulo <> t2_comparecimento) f_t2_votos_ne_comp
        from read_parquet(?)""", [str(SECOES_2026)]).df().iloc[0].to_dict()
    bt = c.execute("""select count(*) n, count(*) filter (where e6258_comparecimento <> comparecimento_bu) f_comp_sistema_ne_bu,
        count(*) filter (where e6258_comparecimento > e6258_aptos) f_comp_gt_aptos,
        count(*) filter (where e6258_c1_v13 + e6258_c1_v22 + e6258_c1_branco + e6258_c1_nulo <> e6258_comparecimento) f_votos_ne_comp,
        count(*) filter (where hab_0 + hab_1 + hab_2 <> comparecimento_bu) f_hab from read_parquet(?)""", [str(BU_TODOS_T2)]).df().iloc[0].to_dict()
    c.close()
    dup = por_uf_df[por_uf_df.f_dup > 0].groupby(['pleito', 'cargo', 'uf'], as_index=False)[['secoes', 'f_dup', 'f_votos']].sum()
    q_rows = [{'pleito': r.pleito, 'cargo': r.cargo, 'uf': r.uf, 'arquivo': f'research/bu/{r.pleito}/{r.uf}_{r.cargo}.parquet',
               'secoes_com_linhas_duplicadas': r.f_dup, 'secoes': r.secoes,
               'reason': 'linhas exatamente duplicadas no arquivo (soma de votos = 2 × comparecimento); após deduplicar, '
                         'votos = comparecimento'} for r in dup.itertuples()]
    q_rows += casos_df.to_dict('records') if len(casos_df) else []
    q = quarentena('04', q_rows)
    arqs = [grava_csv(por_uf_df, 'C1-04_invariante_por_pleito_cargo_uf_tipo_urna.csv'),
            grava_csv(casos_df, 'C1-04_casos.csv')] + ([q] if q else [])
    tot = por_uf_df.groupby(['pleito', 'cargo'])[['secoes', 'f_aptos', 'f_var', 'f_votos', 'f_votos_dedup', 'f_dup', 'f_chave',
                                                  'f_nulo']].sum()
    chave = {'bweb_por_pleito_cargo': {f'{k[0]} {k[1]}': {c: int(v) for c, v in r.items()} for k, r in tot.iterrows()},
             'bweb_arquivos': int(len(por_uf_df.groupby(['pleito', 'cargo', 'uf']))),
             'bweb_casos_total': int(len(casos_df)), 'tipos_urna': sorted(por_uf_df.tipo_urna.unique().tolist()),
             'hab_2026': h26, 'secoes_t1_t2': {k: int(v) for k, v in s26.items()}, 'bu_todos_2026t2': {k: int(v) for k, v in bt.items()},
             'minutos': round((time.time() - t0) / 60, 2)}
    return {'status': 'parcial', 'motivo': 'famílias BWEB (todos os cargos em disco) e BU decodificado 2026 feitas; a família '
            "'detalhe de apuração por seção' não está em research/ (exige captura por rede) — distribuição por TRE = UF",
            'numeros_chave': chave, 'arquivos': arqs}


# --------------------------------------------------------------------------------------------------------- C1-06
def c1_06() -> dict:
    """Matriz de layouts por família × ano × turno a partir dos recibos e esquemas; formatos de urna; revisão de scripts."""
    t0 = time.time()
    layouts = []
    for pleito in PLEITOS_BWEB:
        base = BWEB / pleito
        if not base.exists():
            continue
        for f in sorted(base.glob('*.json')):
            r = json.loads(f.read_text(encoding='utf-8'))
            uf, cargo = f.stem.split('_', 1)
            cols = r.get('columns') or []
            layouts.append({'familia': 'BWEB', 'pleito': pleito, 'ano': int(pleito[:4]), 'turno': int(pleito[-1]), 'cargo': cargo,
                            'uf': uf, 'status': 'no_zip' if r.get('no_zip') else 'no_such_office' if r.get('no_such_office') else 'ok',
                            'formato': (r.get('resource') or {}).get('format'), 'membro': r.get('member'), 'rows': r.get('rows'),
                            'bytes': r.get('bytes'), 'n_colunas': len(cols), 'fingerprint': fingerprint(cols) if cols else '',
                            'colunas': ';'.join(cols)})
    for pleito in sorted(os.listdir(CEFT)):
        for f in sorted((CEFT / pleito).glob('*.json')):
            r = json.loads(f.read_text(encoding='utf-8'))
            cols = r.get('columns') or []
            layouts.append({'familia': 'CEFT', 'pleito': pleito, 'ano': int(pleito[:4]), 'turno': int(pleito[-1]), 'cargo': '',
                            'uf': f.stem, 'status': 'ok' if cols else 'vazio', 'formato': Path(r.get('member', '')).suffix.lstrip('.').upper(),
                            'membro': r.get('member'), 'rows': r.get('rows'), 'bytes': r.get('bytes'), 'n_colunas': len(cols),
                            'fingerprint': fingerprint(cols) if cols else '', 'colunas': ';'.join(cols)})
    for f in sorted(PERFIL.glob('*.parquet')):
        cols = pq_names(f)
        layouts.append({'familia': 'PERFIL_SECAO', 'pleito': '2022', 'ano': 2022, 'turno': 0, 'cargo': '', 'uf': f.stem, 'status': 'ok',
                        'formato': 'parquet derivado', 'membro': f.name, 'rows': pq.read_metadata(f).num_rows, 'bytes': f.stat().st_size,
                        'n_colunas': len(cols), 'fingerprint': fingerprint(cols), 'colunas': ';'.join(cols)})
    lay = pd.DataFrame(layouts)
    # cabeçalho/encoding/delimitador segundo o código de captura (não verificável sem o CSV bruto, que não fica no disco)
    lay['cabecalho'] = np.where((lay.familia == 'BWEB') & (lay.ano <= 2016), 'não (COLS_2012/COLS_2014 fixos em bu_capture_all.py)',
                                np.where((lay.familia == 'CEFT') & (lay.ano <= 2016), 'não (c0..c26; COLS_OLD com 29 nomes não aplicado)',
                                         'sim (lido do arquivo)'))
    lay['encoding_leitura'] = np.where(lay.familia == 'PERFIL_SECAO', '', 'latin-1 (bu_capture_all.py / ceft_capture.py)')
    lay['delimitador'] = np.where(lay.familia == 'PERFIL_SECAO', '', ';')
    # matriz por família × pleito × cargo (um layout por combinação; conferir se todas as UFs têm o mesmo fingerprint)
    grp = lay[lay.status == 'ok'].groupby(['familia', 'pleito', 'cargo'])
    mat = grp.agg(arquivos=('uf', 'count'), fingerprints=('fingerprint', 'nunique'), n_colunas=('n_colunas', 'max'),
                  linhas=('rows', 'sum'), bytes=('bytes', 'sum'), colunas=('colunas', 'first'), fingerprint=('fingerprint', 'first'),
                  cabecalho=('cabecalho', 'first'), encoding_leitura=('encoding_leitura', 'first')).reset_index()
    # diffs entre layouts distintos em ordem de primeira aparição (BWEB e CEFT)
    diffs = []
    for fam in ('BWEB', 'CEFT'):
        sub = mat[mat.familia == fam].sort_values(['pleito', 'cargo'])
        seq = sub.drop_duplicates('fingerprint', keep='first')
        ant = None
        for r in seq.itertuples():
            cols = r.colunas.split(';')
            if ant is not None:
                d = diff_layout(ant[1], cols)
                diffs.append({'familia': fam, 'de': ant[0], 'para': f'{r.pleito} {r.cargo}'.strip(), 'n_de': len(ant[1]),
                              'n_para': len(cols), 'adicionadas': ';'.join(d['adicionadas']), 'removidas': ';'.join(d['removidas']),
                              'renomeadas': ';'.join(d['renomeadas']), 'ordem_igual': d['ordem_igual']})
            ant = (f'{r.pleito} {r.cargo}'.strip(), cols)
    # presença de cada coluna por pleito (BWEB)
    pres = []
    for r in mat[mat.familia == 'BWEB'].itertuples():
        for c in r.colunas.split(';'):
            pres.append({'coluna': c, 'pleito_cargo': f'{r.pleito} {r.cargo}', 'presente': 1})
    pres_df = pd.DataFrame(pres).pivot_table(index='coluna', columns='pleito_cargo', values='presente', fill_value=0).reset_index() \
        if pres else pd.DataFrame()
    # formatos de urna: extensões por pleito (remote-inventory das 11 UFs) + fatos do código
    ext = []
    for pleito in PLEITOS_URNA:
        for uf in UFS_11:
            nomes = membros_inventario_local(pleito, uf)
            if nomes is None:
                continue
            cnt = {}
            for n in nomes:
                s, t = tipo_membro(n)
                suf = n[len(s):] if t not in ('leiame', 'pasta', 'outro') else n
                cnt[(t, suf)] = cnt.get((t, suf), 0) + 1
            for (t, suf), v in cnt.items():
                ext.append({'pleito': pleito, 'uf': uf, 'tipo': t, 'sufixo': suf, 'n': v})
            del nomes
            gc.collect()
            break  # uma UF por pleito basta para documentar o formato dos nomes
    ext_df = pd.DataFrame(ext)
    fatos = [
        {'familia': 'log de urna', 'anos': '2022', 'formato': 'pacote 7z (.logjez) com logd.dat', 'fonte': 'src/auditabr/logs.py (_is_7z, py7zr)'},
        {'familia': 'log de urna', 'anos': '2024, 2026', 'formato': 'pacote zip (-log.jez) com logd.dat; pode aninhar .jez/.logjez da urna anterior (contingência)',
         'fonte': 'src/auditabr/logs.py (read_log_members, NESTED); memória 04/11/2026'},
        {'familia': 'log de urna', 'anos': '2022–2026', 'formato': 'texto tab-separado: data hora\\tnível\\tserial\\tapp\\tmensagem\\tcódigo; latin-1',
         'fonte': 'scripts/varredura_forense_c2.py (fatos_log), src/auditabr/logs.py'},
        {'familia': 'BU binário', 'anos': '2022', 'formato': 'ASN.1/BER (.bu); votável SEQ(C1=tipo, C2=quantidade[, C3=número]); tipo 1 nominal, 2 branco, 3 nulo, 4 legenda',
         'fonte': 'scripts/rdv_lib.py (votos_bu)'},
        {'familia': 'BU binário', 'anos': '2024, 2026', 'formato': 'ASN.1/BER (-bu.dat); mesma estrutura; decodificador próprio para 2026 (decode_bu)',
         'fonte': 'scripts/t2_2026_collect.py (decode_bu); research/integridade/tse_doc/formato/spec/bu.asn1'},
        {'familia': 'RDV', 'anos': '2022', 'formato': 'ASN.1 (.rdv): lista embaralhada de votos SEQ(tipo, valor); tipo 2 nominal, 3 branco, 4 nulo',
         'fonte': 'scripts/rdv_lib.py (votos_rdv)'},
        {'familia': 'RDV', 'anos': '2026', 'formato': 'ASN.1 (-rdv.dat): códigos de tipo diferem de 2022 (memória: rdv-bu-vote-decode); nulo digitado ordenado',
         'fonte': 'scripts/rdv_lib.py; memória do projeto'},
        {'familia': 'assinatura', 'anos': '2022', 'formato': '.vscmr (ASN.1 com blocos por assinante: software SEVIN…, hardware UEAO…; ECDSA-P521 ou Ed521 sobre SHA-512)',
         'fonte': 'scripts/integridade_lib.py, scripts/ed521.py; memória tse-urn-signature-format'},
        {'familia': 'assinatura', 'anos': '2024, 2026', 'formato': '-vota.vsc (mesma estrutura); SA: -sa.vsc', 'fonte': 'scripts/integridade_lib.py; remote-inventory 2026-t1 MG'},
        {'familia': 'membros SA', 'anos': '2022', 'formato': '.busa, .imgbusa, .logsajez, .vscsa (sistema de apuração)', 'fonte': 'research/integridade/tse_doc/formato/README.md; remote-inventory 2022'},
        {'familia': 'membros SA', 'anos': '2024, 2026', 'formato': '-busa.dat, -imgbusa.dat, -logsa.jez, -sa.vsc', 'fonte': 'remote-inventory 2026-t1 MG; zips_republicados.csv'},
        {'familia': 'presidente por seção', 'anos': '2014–2022', 'formato': 'BWEB CSV (research/bu) — QT_ELEITORES_BIOMETRIA_NH, DT_ABERTURA/ENCERRAMENTO desde 2018',
         'fonte': 'research/bu/<pleito>/<UF>_PRESIDENTE.json'},
        {'familia': 'presidente por seção', 'anos': '2026', 'formato': 'BU binário decodificado (secoes_t1_t2, hab_2026): descontinuidade de fonte CSV → ASN.1; hab_2 ≈ habilitação manual',
         'fonte': 'relatorios/verificacoes/virada_1t_2t_2026/secoes_t1_t2.parquet; research/padroes_2t/hab_2026_t*.parquet'},
    ]
    # revisão dos scripts que leem colunas renomeadas
    rev = []
    arquivos_py = sorted((ROOT / 'scripts').glob('*.py')) + sorted((ROOT / 'src').rglob('*.py'))
    for f in arquivos_py:
        if f.name.startswith('varredura_forense_c1'):
            continue
        txt = f.read_text(encoding='utf-8', errors='replace')
        for antiga, nova in RENOMEADAS.items():
            if antiga == 'ANO_ELEICAO':
                continue  # só a CEFT renomeou (AA_ELEICAO); o BWEB mantém ANO_ELEICAO — a busca geraria falsos positivos
            cls = classifica_uso_coluna(txt, antiga, nova)
            if cls != 'não usa':
                linhas = [i + 1 for i, ln in enumerate(txt.splitlines()) if antiga in ln or nova in ln]
                rev.append({'arquivo': rel(f), 'coluna_antiga': antiga, 'coluna_nova': nova, 'classe': cls,
                            'linhas': ';'.join(map(str, linhas[:8]))})
    rev_df = pd.DataFrame(rev)
    arqs = [grava_csv(lay, 'C1-06_layouts_por_arquivo.csv'), grava_csv(mat, 'C1-06_layouts_matriz.csv'),
            grava_csv(pd.DataFrame(diffs), 'C1-06_layouts_diferencas_entre_anos.csv'),
            grava_csv(pres_df, 'C1-06_colunas_bweb_por_pleito.csv'), grava_csv(ext_df, 'C1-06_sufixos_membros_zip.csv'),
            grava_csv(pd.DataFrame(fatos), 'C1-06_formatos_urna.csv'), grava_csv(rev_df, 'C1-06_scripts_colunas_renomeadas.csv')]
    chave = {'recibos_bweb': int((lay.familia == 'BWEB').sum()), 'recibos_bweb_ok': int(((lay.familia == 'BWEB') & (lay.status == 'ok')).sum()),
             'recibos_ceft': int((lay.familia == 'CEFT').sum()), 'layouts_distintos_bweb': int(mat[mat.familia == 'BWEB'].fingerprint.nunique()),
             'layouts_distintos_ceft': int(mat[mat.familia == 'CEFT'].fingerprint.nunique()),
             'pleitos_com_mais_de_um_fingerprint': [f'{r.familia} {r.pleito} {r.cargo}' for r in mat[mat.fingerprints > 1].itertuples()],
             'n_colunas_bweb_por_pleito': {f'{r.pleito} {r.cargo}': int(r.n_colunas) for r in mat[mat.familia == 'BWEB'].itertuples()},
             'scripts_so_coluna_antiga': rev_df[rev_df.classe == 'só antiga'].arquivo.unique().tolist() if len(rev_df) else [],
             'minutos': round((time.time() - t0) / 60, 2)}
    return {'status': 'feita', 'motivo': 'encoding/cabeçalho registrados conforme o código de captura (CSV bruto não fica no disco)',
            'numeros_chave': chave, 'arquivos': arqs}


# --------------------------------------------------------------------------------------------------------- C1-10
def c1_10() -> dict:
    """Membros fora do padrão em 2026 T2 (só contagens) e exterior 2022 T1 (listas locais: BU no HD, logs, assinaturas, BWEB)."""
    t0 = time.time()
    inv = pd.read_csv(INVENTARIO, sep=';', encoding='utf-8-sig')
    rows = []
    for r in inv[inv.status == 'ok'].itertuples():
        k = MEMBROS_SA_POR_STEM
        d = decompoe_outros(r.outros_arquivos, r.urnas, r.bu_arquivos, k)
        rows.append({'pleito': r.eleicao, 'uf': r.uf, 'urnas': i0(r.urnas), 'bu': i0(r.bu_arquivos), 'log': i0(r.log_arquivos),
                     'rdv': i0(r.rdv_arquivos), 'assinatura': i0(r.assinatura_arquivos), 'imgbu': i0(r.imgbu_arquivos),
                     'outros': i0(r.outros_arquivos), 'membros_sa_por_stem_assumido': k, **d,
                     'log_menos_bu': i0(r.log_arquivos - r.bu_arquivos), 'rdv_menos_bu': i0(r.rdv_arquivos - r.bu_arquivos),
                     'nomes_no_disco': 'sim (remote-inventory)' if raiz_inventario(r.eleicao, r.uf) else 'não (rede)'})
    dec = pd.DataFrame(rows)
    t2 = dec[dec.pleito == '2026-t2']
    # exterior 2022 T1: listas locais (única listagem de pasta de logs permitida)
    zz = None
    bu = stems_bu_urna('2022-t1')
    bu = bu[(bu.uf == 'ZZ') & bu.chave_ok]
    logs = []
    if LOGS_ZZ_2022T1.is_dir():
        with os.scandir(LOGS_ZZ_2022T1) as it:
            logs = [e.name for e in it if e.is_file() and not e.name.endswith('.json')]
    ass = assinaturas_disco('2022-t1', 'ZZ') or []
    lg = pd.DataFrame({'stem': [tipo_membro(n)[0] for n in logs if tipo_membro(n)[1] == 'log']})
    asn = pd.DataFrame({'stem': [tipo_membro(n)[0] for n in ass if tipo_membro(n)[1] == 'assinatura']})
    bw = secoes_bweb('2022-t1', 'PRESIDENTE')
    bw = bw[bw.uf == 'ZZ'] if bw is not None else None
    if bw is not None:
        zz = int_keys(bw[KEY + ['aptos', 'comparecimento', 'tipo_urna', 'agregadas', 'urna_efetivada']]).merge(
            int_keys(bu[KEY + ['stem']]), on=KEY, how='outer', indicator='bweb_x_bu')
        zz['stem_esperado'] = ['o00406-%05d%04d%04d' % (m, z, s) for m, z, s in zip(zz.municipality, zz.zone, zz.section)]
        zz['log_no_hd'] = zz.stem_esperado.isin(set(lg.stem))
        zz['assinatura_no_hd'] = zz.stem_esperado.isin(set(asn.stem))
        zz['bu_no_hd'] = zz.stem.notna()
        zz['bweb'] = zz.bweb_x_bu.map({'both': 'presente', 'left_only': 'presente', 'right_only': 'ausente'})
        zz['bweb_x_bu'] = zz.bweb_x_bu.astype(str)
        zz = zz.drop(columns='stem')
    inv_zz = inv[(inv.eleicao == '2022-t1') & (inv.uf == 'ZZ')].iloc[0]
    n_zz = {'inventario': {'urnas': int(inv_zz.urnas), 'bu': int(inv_zz.bu_arquivos), 'log': int(inv_zz.log_arquivos),
                           'rdv': int(inv_zz.rdv_arquivos), 'assinatura': int(inv_zz.assinatura_arquivos), 'outros': int(inv_zz.outros_arquivos)},
            'bu_no_hd': int(len(bu)), 'logs_no_hd': int(len(lg)), 'assinaturas_no_hd': int(len(asn)),
            'bweb_secoes': int(len(bw)) if bw is not None else None}
    if zz is not None:
        n_zz.update({'bweb_sem_bu': int((zz.bweb_x_bu == 'left_only').sum()), 'bu_sem_bweb': int((zz.bweb_x_bu == 'right_only').sum()),
                     'bu_sem_log_no_hd': int((zz.bu_no_hd & ~zz.log_no_hd).sum()), 'log_sem_bu': int(len(set(lg.stem) - set(bu.stem))),
                     'bu_sem_assinatura_no_hd': int((zz.bu_no_hd & ~zz.assinatura_no_hd).sum()),
                     'bweb_sem_bu_tipo_urna': zz[zz.bweb_x_bu == 'left_only'].tipo_urna.value_counts(dropna=False).astype(int).to_dict(),
                     'bweb_sem_bu_comparecimento': int(zz[zz.bweb_x_bu == 'left_only'].comparecimento.sum()),
                     'bu_sem_log_comparecimento': int(zz[zz.bu_no_hd & ~zz.log_no_hd].comparecimento.fillna(0).sum())})
    arqs = [grava_csv(dec, 'C1-10_outros_decomposicao_por_pleito_uf.csv'), grava_csv(t2, 'C1-10_2026t2_outros_por_uf.csv')]
    if zz is not None:
        arqs.append(grava_csv(zz, 'C1-10_zz_2022t1_familias_por_secao.csv'))
    chave = {'2026-t2_outros_total': int(t2.outros.sum()), '2026-t2_leiame': int(t2.leiame.sum()),
             '2026-t2_sa_esperados': int(t2.sa_esperados.sum()), '2026-t2_residuo_nao_identificado': int(t2.residuo.sum()),
             '2026-t2_residuo_por_uf': {r.uf: int(r.residuo) for r in t2.itertuples() if r.residuo != 0},
             'residuo_por_pleito': {p: int(v) for p, v in dec.groupby('pleito').residuo.sum().items()},
             'zz_2022t1': n_zz, 'minutos': round((time.time() - t0) / 60, 2)}
    return {'status': 'parcial', 'motivo': 'os nomes dos 77 membros residuais de 2026 T2 (e dos "sa" fora das 11 UFs) não estão '
            'no disco: exigem releitura do diretório central dos zips (rede); exterior 2022 T1 feito com listas locais',
            'numeros_chave': chave, 'arquivos': arqs}


# --------------------------------------------------------------------------------------------------------- C1-13
def c1_13() -> dict:
    """Casos de prova incompleta (falhas.csv + casos_sem_prova_completa.csv) × BWEB × CEFT × contingência × membros do zip."""
    t0 = time.time()
    fal = pd.read_csv(FALHAS, encoding='utf-8-sig', dtype=str)
    casos = [{'pleito': r.eleicao, 'uf': r.uf, 'stem': r.urna, 'caso': r.tipo, 'origem': 'falhas.csv', 'log_no_hd_integridade': r.log_local}
             for r in fal.itertuples()]
    cp = pd.read_csv(SEM_PROVA, encoding='utf-8-sig', dtype=str)
    for r in cp.itertuples():
        if 'sem arquivo de assinatura' in r.caso.lower():
            continue
        for stem, uf in re.findall(r'(o\d{5}-?[a-z]{0,2}\d{13}) \((\w{2})\)', r.exemplos):
            casos.append({'pleito': r.eleicao, 'uf': uf, 'stem': stem, 'caso': r.caso, 'origem': 'casos_sem_prova_completa.csv',
                          'log_no_hd_integridade': ''})
    # casos_sem_prova_completa.csv só traz até 4 exemplos por caso: completar com a lista integral das 11 UFs (C1-02)
    p_sa = OUT / 'C1-02_stems_sa_ou_incompletos_11ufs.csv'
    if p_sa.exists():
        ja = {c['stem'] for c in casos}
        for r in pd.read_csv(p_sa, sep=';', decimal=',', encoding='utf-8-sig', dtype=str).itertuples():
            if r.stem in ja:
                continue
            tipos = set(str(r.tipos).split(';'))
            falta = [t for t in ('bu', 'log', 'rdv', 'assinatura') if t not in tipos]
            casos.append({'pleito': r.pleito, 'uf': r.uf, 'stem': r.stem, 'caso': 'zip sem ' + '/'.join(falta),
                          'origem': 'C1-02 (remote-inventory)', 'log_no_hd_integridade': r.log_local})
    df = pd.DataFrame(casos)
    k = pd.DataFrame([chave_do_stem(s) or (None, None, None, None) for s in df.stem], columns=['uf_stem', 'municipality', 'zone', 'section'])
    df = pd.concat([df, k.drop(columns='uf_stem')], axis=1)
    out = []
    for (pleito, uf), g in df.groupby(['pleito', 'uf']):
        g = int_keys(g)
        b = situacao_bweb_lote(pleito, uf, g[KEY].drop_duplicates())
        g = g.merge(b, on=KEY, how='left')
        cf = secoes_ceft(pleito, uf)
        if cf is None:
            g['ceft'] = 'sem CEFT no disco'
        else:
            g = g.merge(ceft_prefixada(cf), on=KEY, how='left')
            g['ceft'] = np.where(g.ceft_linhas.notna(), 'presente', 'seção ausente da CEFT')
        nomes = membros_inventario_local(pleito, uf)
        if nomes is None:
            g['membros_zip'] = 'NOT_COMPARABLE: sem remote-inventory.json'
            g['tem_sa'] = None
        else:
            m = classifica_membros(nomes).set_index('stem')
            g['membros_zip'] = [m.tipos.get(s, 'stem ausente do zip') for s in g.stem]
            g['tem_sa'] = [bool(m.tem_sa.get(s, False)) for s in g.stem]
            del m, nomes
            gc.collect()
        # contingência (varredura de logs das 11 UFs): o log desta seção tem marcas de contingência/troca?
        if pleito.startswith('2024'):
            pc = CONTINGENCIA / f'municipais_{uf}_{pleito}.parquet'
        elif uf == 'BA':
            pc = CONTINGENCIA / ('piloto-ba-2022-t2.parquet' if pleito == '2022-t2' else f'bahia-presidente-2022-2026_{pleito}.parquet')
        else:
            pc = CONTINGENCIA / f'estados_{uf}_{pleito}.parquet'
        if pc.exists():
            c = con()
            ct = c.execute("""select cast(municipality as int) municipality, cast(zone as int) zone, cast(section as int) section,
                max(contingency_mode) contingencia_modo, max(votes) contingencia_votos, max(days_in_log) dias_no_log
                from read_parquet(?) group by 1, 2, 3""", [str(pc)]).df()
            c.close()
            ct['uf'] = uf
            g = g.merge(ct, on=KEY, how='left')
            g['contingencia'] = np.where(g.dias_no_log.notna(), 'seção na varredura de contingência', 'seção não marcada')
        else:
            g['contingencia'] = 'sem varredura de contingência para este pleito/UF'
        out.append(g)
    res = pd.concat(out, ignore_index=True)
    res['leitura'] = [classifica_prova(r.caso, r.get('bweb_tipo_urna'), r.get('ceft_origem_voto'), r.get('ceft_divergencia'),
                                       r.get('tem_sa')) for _, r in res.iterrows()]
    arqs = [grava_csv(res, 'C1-13_casos_prova_incompleta_x_familias.csv')]

    def vc(col):
        return res[col].value_counts(dropna=False).astype(int).rename(lambda k: str(k)).to_dict() if col in res else {}

    chave = {'casos': int(len(res)), 'por_caso': res.caso.value_counts().to_dict(),
             'bweb_tipo_urna': vc('bweb_tipo_urna'), 'ceft_origem_voto': vc('ceft_origem_voto'), 'ceft_divergencia': vc('ceft_divergencia'),
             'com_membros_sa': int(res.tem_sa.fillna(False).astype(bool).sum()),
             'leituras': res.leitura.value_counts().to_dict(), 'minutos': round((time.time() - t0) / 60, 2)}
    return {'status': 'feita', 'motivo': 'nacionalização (fora das 11 UFs) depende de nomes dos membros (rede)',
            'numeros_chave': chave, 'arquivos': arqs}


# --------------------------------------------------------------------------------------------------------- C1-14
def c1_14() -> dict:
    """Quarentena regional (11 linhas) × BWEB/captura regional; 189 seções MA 2022 T1 aptos presidente ≠ governador."""
    t0 = time.time()
    linhas = []
    for f in sorted(QUAR_REGIONAL.glob('rows-*.json')):
        for r in json.loads(f.read_text(encoding='utf-8')):
            p = r['parameters']
            sid = r['section_id'].split(':')
            linhas.append({'arquivo': f.name, 'ano': p['year'], 'turno': p['round'], 'uf': p['uf'], 'familia': p['family'],
                           'municipality': int(sid[2]), 'zone': int(sid[3]), 'section': int(sid[4]), 'aptos_q': r['eligible'],
                           'presentes_q': r['present'], 'ausentes_q': r['absent'], 'reason': r['reason']})
    q = pd.DataFrame(linhas)
    out = []
    for r in q.itertuples():
        pleito = f'{r.ano}-t{r.turno}'
        row = r._asdict()
        row.pop('Index', None)
        row['pleito'] = pleito
        cargo = CARGO_REF[str(r.ano)]
        p = BWEB / pleito / f'{r.uf}_{cargo}.parquet'
        if p.exists():
            s = secoes_bweb_uf_arquivo(p, r.uf)
            hit = s[(s.municipality == r.municipality) & (s.zone == r.zone) & (s.section == r.section)]
            row['bweb'] = f'{cargo}: presente' if len(hit) else f'{cargo}: seção ausente do BWEB'
            if len(hit):
                h = hit.iloc[0]
                row.update(bweb_aptos=h.aptos, bweb_comparecimento=h.comparecimento, bweb_abstencoes=h.abstencoes,
                           bweb_tipo_urna=h.tipo_urna, bweb_agregadas=h.agregadas, bweb_urna=h.urna_efetivada)
            # a seção aparece como agregada em outra seção?
            agg = s[s.agregadas.notna()]
            hits_agg = agg[agg.agregadas.astype(str).apply(lambda t, sec=r.section: secao_em_agregadas(t, sec)).astype(bool)
                           & (agg.municipality == r.municipality) & (agg.zone == r.zone)]
            row['bweb_agregada_em'] = ';'.join(f'{a.section}' for a in hits_agg.itertuples()) if len(hits_agg) else ''
            del s
        else:
            row['bweb'] = f'sem BWEB {cargo} no disco para {pleito} {r.uf}'
        # captura regional (família detalhe/turnout) — o parquet bruto projetado
        cap = None
        for f in CAPTURAS_REGIONAIS.glob('*.json'):
            c = json.loads(f.read_text(encoding='utf-8'))
            a = c.get('assets', {}).get(r.uf)
            if a and a.get('year') == r.ano and a.get('family') == 'turnout' and Path(a.get('path', '')).exists():
                cap = Path(a['path'])
                break
        if cap is not None:
            cc = con()
            names = pq_names(cap)
            turno_col = 'NR_TURNO' if 'NR_TURNO' in names else None
            cond = f" and try_cast({turno_col} as int) = {r.turno}" if turno_col else ''
            d = cc.execute(f"""select DS_CARGO, QT_APTOS, QT_COMPARECIMENTO, QT_ABSTENCOES from read_parquet('{cap.as_posix()}')
                where try_cast(CD_MUNICIPIO as int) = {r.municipality} and try_cast(NR_ZONA as int) = {r.zone}
                and try_cast(NR_SECAO as int) = {r.section}{cond}""").df()
            cc.close()
            row['detalhe_regional'] = f'{len(d)} linha(s): ' + '; '.join(f'{x.DS_CARGO} {x.QT_APTOS}/{x.QT_COMPARECIMENTO}/{x.QT_ABSTENCOES}' for x in d.itertuples())
            row['detalhe_regional_arquivo'] = rel(cap)
        else:
            row['detalhe_regional'] = 'captura regional não encontrada'
        out.append(row)
    res = pd.DataFrame(out)
    # 189 seções MA 2022 T1 (DECISOES_E_CORRECOES): aptos/comparecimento presidente ≠ governador. O governador MA 2022 não
    # está em disco (nem BWEB nem detalhe regional, que foi projetado só para Presidente) -> NAO_TESTAVEL; controles abaixo.
    ma_gov = BWEB / '2022-t1' / 'MA_GOVERNADOR.parquet'
    if ma_gov.exists():
        pres = secoes_bweb_uf_arquivo(BWEB / '2022-t1' / 'MA_PRESIDENTE.parquet', 'MA')
        gov = secoes_bweb_uf_arquivo(ma_gov, 'MA')
        cmp_ = compara_cargos(pres[KEY + ['aptos', 'comparecimento', 'abstencoes', 'tipo_urna', 'agregadas']],
                              gov[KEY + ['aptos', 'comparecimento', 'abstencoes']])
        dif = cmp_[cmp_.difere].copy()
        ma_status = 'testado'
    else:
        dif = pd.DataFrame(columns=KEY + ['dif_aptos', 'dif_comparecimento', 'dif_abstencoes'])
        cmp_ = dif
        ma_status = ('NAO_TESTAVEL: governador MA 2022 não está em disco (research/bu/2022-t1 sem MA_GOVERNADOR; '
                     'research/estados/MA/2022-t1/bu.parquet e a captura regional detalhe/turnout MA 2022 só têm Presidente)')
    # controles: presidente × governador na mesma seção, BWEB (2014/2018/2022, UFs com os dois arquivos), 2026 T1
    # (governador BWEB × presidente do BU decodificado) e 2026 T2 (sistema de resultados, eleições estaduais e6xxx × e6258)
    ctrl, exemplos = [], []

    def resume(pleito, uf, fonte, a, b):
        m = compara_cargos(a[KEY + ['aptos', 'comparecimento', 'abstencoes']], b[KEY + ['aptos', 'comparecimento', 'abstencoes']])
        ctrl.append({'pleito': pleito, 'uf': uf, 'fonte': fonte, 'secoes_comparaveis': len(m), 'diferem': int(m.difere.sum()),
                     'dif_aptos_n': int((m.dif_aptos != 0).sum()), 'dif_comparecimento_n': int((m.dif_comparecimento != 0).sum()),
                     'so_presidente': int(len(a) - len(m)), 'so_governador': int(len(b) - len(m)),
                     'dif_aptos_total': int(m.dif_aptos.sum()), 'dif_comparecimento_total': int(m.dif_comparecimento.sum()),
                     'dif_abstencoes_total': int(m.dif_abstencoes.fillna(0).sum()),
                     'aptos_pres_maior': int((m.dif_aptos > 0).sum()), 'aptos_pres_menor': int((m.dif_aptos < 0).sum()),
                     'dif_aptos_igual_dif_comparecimento': int(((m.dif_aptos == m.dif_comparecimento) & m.difere).sum())})
        if m.difere.any():
            e = m[m.difere].head(20).copy()
            e['pleito'], e['fonte'] = pleito, fonte
            exemplos.append(e)

    for pleito in ('2014-t1', '2014-t2', '2018-t1', '2018-t2', '2022-t1', '2022-t2'):
        for pg in sorted((BWEB / pleito).glob('*_GOVERNADOR.parquet')):
            uf = pg.name.split('_')[0]
            pp = BWEB / pleito / f'{uf}_PRESIDENTE.parquet'
            if not pp.exists():
                continue
            resume(pleito, uf, 'BWEB presidente × BWEB governador', secoes_bweb_uf_arquivo(pp, uf), secoes_bweb_uf_arquivo(pg, uf))
            gc.collect()
    s26 = secoes_2026()
    p26 = s26[s26.t1_stem.notna()].rename(columns={'t1_aptos': 'aptos', 't1_comparecimento': 'comparecimento'})
    p26['abstencoes'] = p26.aptos - p26.comparecimento
    for pg in sorted((BWEB / '2026-t1').glob('*_GOVERNADOR.parquet')):
        uf = pg.name.split('_')[0]
        resume('2026-t1', uf, 'BU decodificado presidente × BWEB governador', int_keys(p26[p26.uf == uf]),
               int_keys(secoes_bweb_uf_arquivo(pg, uf)))
    del s26, p26
    c = con()
    cols = pq_names(BU_TODOS_T2)
    est = sorted({x.split('_')[0] for x in cols if re.match(r'^e\d{4}_aptos$', x) and not x.startswith('e6258')})
    bt = c.execute(f"""select uf, municipality, zone, section, e6258_aptos aptos, e6258_comparecimento comparecimento,
        {', '.join(f'{e}_aptos, {e}_comparecimento' for e in est)} from read_parquet(?)""", [str(BU_TODOS_T2)]).df()
    c.close()
    for e in est:
        g = bt[bt[f'{e}_aptos'].notna()]
        if g.empty:
            continue
        a = g[KEY + ['aptos', 'comparecimento']].assign(abstencoes=lambda x: x.aptos - x.comparecimento)
        b = g[KEY].assign(aptos=g[f'{e}_aptos'], comparecimento=g[f'{e}_comparecimento'])
        b['abstencoes'] = b.aptos - b.comparecimento
        for uf in sorted(g.uf.unique()):
            resume('2026-t2', uf, f'sistema de resultados e6258 (presidente) × {e} (governador)', int_keys(a[a.uf == uf]),
                   int_keys(b[b.uf == uf]))
    del bt
    ctrl_df = pd.DataFrame(ctrl)
    ex_df = pd.concat(exemplos, ignore_index=True) if exemplos else pd.DataFrame()
    arqs = [grava_csv(res, 'C1-14_quarentena_regional_x_bweb.csv'), grava_csv(ctrl_df, 'C1-14_presidente_x_governador_por_uf.csv'),
            grava_csv(ex_df, 'C1-14_presidente_x_governador_exemplos.csv')]
    if len(dif):
        arqs.append(grava_csv(dif, 'C1-14_ma_2022t1_presidente_x_governador_secoes.csv'))
    tot = ctrl_df.groupby('pleito')[['secoes_comparaveis', 'diferem', 'dif_aptos_n', 'so_presidente', 'so_governador']].sum()         if len(ctrl_df) else pd.DataFrame()
    chave = {'linhas_quarentena': int(len(res)), 'bweb': res.bweb.value_counts().to_dict(),
             'bweb_comparecimento_zero': int((res.get('bweb_comparecimento', pd.Series(dtype=float)) == 0).sum()),
             'detalhe_regional': res.detalhe_regional.value_counts().to_dict() if 'detalhe_regional' in res else {},
             'ma_2022t1': ma_status, 'ma_2022t1_secoes_diferentes': int(len(dif)), 'ma_2022t1_comparaveis': int(len(cmp_)),
             'controle_presidente_x_governador_por_pleito': {k: {c: int(v) for c, v in r.items()} for k, r in tot.iterrows()},
             'controle_ufs_com_diferenca': [f"{r.pleito} {r.uf}: {r.diferem}" for r in ctrl_df.itertuples() if r.diferem] if len(ctrl_df) else [],
             'minutos': round((time.time() - t0) / 60, 2)}
    return {'status': 'parcial' if not ma_gov.exists() else 'feita',
            'motivo': '' if ma_gov.exists() else 'quarentena regional feita; 189 seções MA 2022 T1 não testáveis (governador MA ausente do disco)',
            'numeros_chave': chave, 'arquivos': arqs}


# ------------------------------------------------------------------------------------------------------------ main
CHECAGENS = {'C1-01': c1_01, 'C1-02': c1_02, 'C1-03': c1_03, 'C1-04': c1_04, 'C1-06': c1_06, 'C1-10': c1_10,
             'C1-13': c1_13, 'C1-14': c1_14}
PENDENTES = {
    'C1-05': 'depende da passada pesada: os.stat/CRC de ~1,6 M arquivos no HDD (tamanho × bytes do remote-inventory; '
             'zlib.crc32 × CRC do diretório central, que exige rede) e consolidação das colunas de erro',
    'C1-07': 'exige rede (~124 GB de zip 2026-t2 lidos por blocos) e HDD: integridade_check.py zips nos 28 zips de 2026-t2',
    'C1-08': 'depende da passada pesada: verificação offline de assinaturas (log × manifesto × BU) das 16 UFs + ZZ',
    'C1-09': 'exige rede: Last-Modified/tamanho/diretório central atual dos zips × remote-inventory/zips_republicados',
    'C1-11': 'exige rede (membros dos 28.823 stems no zip oficial) + passada de BUs (bu_raw dos dois canais); manifestos '
             'dos dois canais são leves e podem ir na passada de BUs',
    'C1-12': 'depende da passada pesada de logs: reler 34.424 .logjez de BA 2022-t2 com o leitor aninhado (1.340 '
             'identidades ambíguas, 771 log > BU) e recomputar log_x_boletim/relogio',
    'C1-15': 'depende de HDD ocioso: índice local (nome, bytes, mtime) das pastas de logs por UF/pleito',
}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('ids', nargs='*', help='ids das checagens (padrão: todas)')
    args = ap.parse_args(argv)
    ids = args.ids or list(CHECAGENS)
    OUT.mkdir(parents=True, exist_ok=True)
    p_res = OUT / 'C1_resumo.json'
    resumo = json.loads(p_res.read_text(encoding='utf-8')) if p_res.exists() else {'camada': 'C1', 'protocolo': 'v1.0',
                                                                                     'parser_version': PARSER_VERSION, 'checagens': {}}
    for cid, motivo in PENDENTES.items():
        resumo['checagens'].setdefault(cid, {'status': 'nao_feita', 'motivo': motivo, 'numeros_chave': {}, 'arquivos': []})
    for cid in ids:
        t0 = time.time()
        print(f'[{agora()}] {cid} ...', flush=True)
        try:
            r = CHECAGENS[cid]()
        except Exception as exc:  # registra e segue
            r = {'status': 'nao_feita', 'motivo': f'erro: {exc!r}'[:400], 'numeros_chave': {}, 'arquivos': []}
            print(f'   ERRO {exc!r}', flush=True)
            traceback.print_exc()
        r['minutos'] = round((time.time() - t0) / 60, 2)
        r['gerado_em'] = agora()
        resumo['checagens'][cid] = r
        p_res.write_text(json.dumps(resumo, indent=1, ensure_ascii=False, default=str), encoding='utf-8')
        print(f'   {r["status"]} em {r["minutos"]} min', flush=True)
        gc.collect()
    return resumo


if __name__ == '__main__':
    main()
