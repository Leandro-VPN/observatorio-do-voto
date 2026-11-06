"""Varredura forense — camada C2 (consistência interna da urna): checagens leves sobre tabelas já existentes.

Protocolo: relatorios/verificacoes/varredura_forense/PROTOCOLO.md v1.0. Mapa: mapa/mapa_C2.json.
Checagens feitas aqui (ids do mapa):
  C2-01 dossiê das 8 seções de 2026 T2 com log ≠ BU após a releitura aninhada (fatos já apurados + evidência por logd.dat)
  C2-07 habilitação manual do log ≠ habilitação sem biometria do BU (25.450 seções; 11 UFs × 5 pleitos)
  C2-08 (parte leve) relógio do log × relógio do BU por seção (último voto × encerramento, primeiro voto × abertura)
  C2-09 manifesto × logs aninhados (2026 T2: votos que só existem em logs aninhados; amostra de pacotes × manifesto)
  C2-12 urnas sem meio de prova e assimetrias do inventário de zips
  C2-14 hora da assinatura × emissão do BU × encerramento × recebimento
  C2-15 erros 'O voto do eleitor NÃO foi registrado' (8044) e erros durante a votação
Ficam para as passadas pesadas (releitura de logs/BUs) ou exigem rede: C2-02, C2-03, C2-04, C2-05, C2-06, C2-10, C2-11, C2-13.

Saídas: relatorios/verificacoes/varredura_forense/C2/ (CSV com ';' e vírgula decimal; parquet com recibo .json ao lado)
e C2_resumo.json. Quarentena: research/varredura_forense/quarentena/rows-C2-<checagem>.json + quarentena_<checagem>.csv.
Nada aqui indica irregularidade por si só: é descrição de diferenças, ausências e limites ("sinalização não é acusação").
Uso: python scripts/varredura_forense_c2.py [C2-01 C2-07 ...]   (sem argumentos roda todas, em série)
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / 'research'
REL = ROOT / 'relatorios'
OUT = REL / 'verificacoes' / 'varredura_forense' / 'C2'
QUAR = R / 'varredura_forense' / 'quarentena'
PARSER_VERSION = 'varredura-forense-c2-1'
SEED = 20261105
CSV_KW = dict(sep=';', decimal=',', encoding='utf-8-sig', index=False)
MAX_LOG = 32 * 1024 ** 2
MAX_PACOTE = 2 * MAX_LOG

DIA = {'2022-t1': '02/10/2022', '2022-t2': '30/10/2022', '2024-t1': '06/10/2024', '2024-t2': '27/10/2024',
       '2026-t1': '04/10/2026', '2026-t2': '25/10/2026'}
EID_PLEITO = {'P2022': '2022-t1', 'P2022b': '2022-t2', 'M2024': '2024-t1', 'M2024b': '2024-t2', 'P2026': '2026-t1'}
UFS_11 = ['BA', 'CE', 'MA', 'MG', 'PA', 'PE', 'PR', 'RJ', 'RS', 'SC', 'SP']
UFS_T2_RESULTADOS = ['BA', 'CE', 'MG', 'PA', 'PB', 'PE', 'PI', 'PR', 'RJ', 'RN', 'RS', 'SC', 'SE', 'SP']

INDICADORES = REL / 'fiscalizacao'
INTEGRIDADE = REL / 'integridade' / 'integridade_todas_urnas.parquet'
RELOGIO = REL / 'verificacoes' / 'relogio_por_secao.parquet'
BINS_2026 = R / 'janelas_horario' / 'bins_2026.parquet'
LOGS_2026T2 = R / 'segundo_turno_2026' / 'logs'
ASSIN = R / 'assinaturas'
ULTIMO_VOTO = REL / 'verificacoes' / 'ultimo_voto_2026t2' / 'ultimo_voto_por_secao.csv'
CACHE_V2 = R / 'segundo_turno_2026' / 'ultimo_voto_cache'
CACHE_V1 = R / 'segundo_turno_2026' / 'ultimo_voto_cache_leitor_v1'
RECONFERIDO = ROOT / 'build' / 'log_x_bu_reconferido.csv'
HAB_T2 = R / 'padroes_2t' / 'hab_2026_t2.parquet'
BASE_2026 = R / 'padroes_2t' / 'base_2026.parquet'
RDV_T2 = R / 'rdv_gatilho' / '2026-t2'
BU_T2 = R / 'segundo_turno_2026' / 'bu_todos_decodificados.parquet'
INTEG_RES = R / 'integridade' / 'resultado'
INVENTARIO = REL / 'disco' / 'inventario_zips_pais.csv'
FALHAS = REL / 'integridade' / 'falhas.csv'
SEM_PROVA = REL / 'integridade' / 'casos_sem_prova_completa.csv'
SCAN_8044 = R / 'contingencia' / '_scan_voto_nao_registrado.csv'
CONTINGENCIA = R / 'contingencia'
LOGS_SECOES = R / 'anomalias_2t' / 'logs_secoes.parquet'
BWEB = R / 'bu'
CEFT = R / 'ceft'
# única listagem de pasta de logs permitida (pastas pequenas, sem inventário remoto no disco): ZZ e RN 2022 T1
LISTAGEM_PERMITIDA = {('2022-t1', 'ZZ'), ('2022-t1', 'RN')}

# C2-01: as 8 seções de 2026 T2 com log ≠ BU antes do dossiê (build/log_x_bu_reconferido.csv, releitura de 04/11/2026)
CASOS_C2_01 = [('ES', 57932, 9, 85), ('BA', 39870, 133, 184), ('MA', 8893, 47, 609), ('BA', 35653, 173, 235),
               ('PB', 21750, 2, 254), ('BA', 34711, 21, 178), ('PI', 11533, 3, 216), ('SP', 64777, 395, 298)]
# Fatos apurados na sessão de 04-05/11/2026 (leitura manual dos pacotes), gravados como evidência; não refeitos aqui.
FATOS_SESSAO = [
    dict(uf='ES', municipality=57932, zone=9, section=85, pacote='o03221es5793200090085-log.jez', bytes=399475,
         fato='3 logd.dat: externo (depth 0) urna 01758779, 725 linhas, 0 votos, declara "Seção Eleitoral" 0000 '
              '("Urna de contingência") e depois 0112, usada em 25/10 19:39 e 21:24 ("Log interno da urna de contingência '
              'validado"); aninhado urna 01841837 (seção 85, 10.849 linhas, 297 votos em 04/10 e 308 em 25/10 = BU); '
              'aninhado urna 01750820 (seção 112, 304 votos em 04/10 e 304 em 25/10). O filtro por seção declarada não '
              'escolhia (externo declara 2 seções) e somava 308+304 = 612. Corrigido em src/auditabr/logs.py '
              '(section_hint pelo nome do arquivo, 04/11, não commitado): agora 308. O pacote da seção 112 '
              '(…0112-log.jez) tem só a contingência + urna 01750820 = 304 = BU. Releitura do último voto refeita: '
              'ultimo_voto_por_secao.csv já mostra 308.'),
    dict(uf='BA', municipality=35653, zone=173, section=235, pacote='o03221ba3565301730235-log.jez', bytes=None,
         fato='externo = contingência 01656557 com 204 votos em 25/10 (declara 0000 e 0235); aninhados: log de T1 da urna '
              '01833178 (seção 235, 209 votos em 04/10) e um log de 170 linhas da mesma urna 01833178 iniciado 25/10 09:04 '
              'declarando seção 0083, sem votos. BU = 217: faltam 13 votos de uma urna intermediária cujo log não está '
              'no pacote.'),
    dict(uf='MA', municipality=8893, zone=47, section=609, pacote='o03221ma0889300470609-log.jez', bytes=None,
         fato='externo = contingência 01664037 com 188 votos em 25/10 (declara 0000 e 0609); aninhado: log de T1 da urna '
              '01813459 declarando seção 0445 (306 votos em 04/10). BU = 224: faltam 36 votos; o log da urna original '
              'do 2º turno não está no pacote.'),
]

VOTE_LINE = b'\tVOTA\tO voto do eleitor foi computado\t'
SECTION_LINE = re.compile(rb'Se(?:\xe7\xe3|\xc3\xa7\xc3\xa3)o Eleitoral: (\d{4})')
COMPUTADO = 'O voto do eleitor foi computado'
CONFIRMADO = re.compile(r'Voto confirmado para \[([^\]]+)\]')
MASCARA = re.compile(r'\d{8,}')  # números longos (títulos, seriais de 8+ dígitos) mascarados nas linhas publicadas
STEM_2022 = re.compile(r'^o\d{5}-(\d{5})(\d{4})(\d{4})')
STEM_2024 = re.compile(r'^o\d{5}([a-z]{2})(\d{5})(\d{4})(\d{4})', re.I)
SUFIXOS = ('-log.jez', '-vota.vsc', '-bu.dat', '-rdv.dat', '-imgbu.dat', '.logsajez', '.imgbusa', '.vscsa', '.busa',
           '.logjez', '.vscmr', '.imgbu', '.bu', '.rdv')
TIPO_POR_SUFIXO = {'-log.jez': 'log', '.logjez': 'log', '-bu.dat': 'bu', '.bu': 'bu', '-rdv.dat': 'rdv', '.rdv': 'rdv',
                   '-vota.vsc': 'assinatura', '.vscmr': 'assinatura', '-imgbu.dat': 'imgbu', '.imgbu': 'imgbu',
                   '.busa': 'bu_sa', '.logsajez': 'log_sa', '.vscsa': 'assinatura_sa', '.imgbusa': 'imgbu_sa'}
NESTED = ('.jez', '.logjez')


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
    """Linhas que falham invariante: valores originais como string + reason; JSON em research/… e CSV em C2/."""
    if not linhas:
        return None
    QUAR.mkdir(parents=True, exist_ok=True)
    regs = [{k: (None if v is None or (isinstance(v, float) and np.isnan(v)) else str(v)) for k, v in r.items()}
            for r in linhas]
    (QUAR / f'rows-C2-{cx}.json').write_text(json.dumps(regs, indent=1, ensure_ascii=False), encoding='utf-8')
    return grava_csv(pd.DataFrame(regs), f'quarentena_C2-{cx}.csv')


def stem_de(nome: str) -> str:
    """Nome do pacote sem o sufixo de tipo (…logjez, -log.jez, -vota.vsc, .vscmr, .bu, -bu.dat…)."""
    n = PurePosixPath(str(nome).replace('\\', '/')).name
    low = n.lower()
    for suf in SUFIXOS:
        if low.endswith(suf):
            return n[:-len(suf)]
    return n


def tipo_de(nome: str) -> str | None:
    low = PurePosixPath(str(nome).replace('\\', '/')).name.lower()
    for suf in SUFIXOS:
        if low.endswith(suf):
            return TIPO_POR_SUFIXO.get(suf)
    return None


def chave_do_stem(stem: str) -> tuple[str | None, int, int, int]:
    """(uf ou None, município TSE, zona, seção): 2022 'o00406-MMMMMZZZZSSSS'; 2024+ 'o00453ufMMMMMZZZZSSSS'."""
    m = STEM_2024.match(stem)
    if m:
        return m[1].upper(), int(m[2]), int(m[3]), int(m[4])
    m = STEM_2022.match(stem)
    if m:
        return None, int(m[1]), int(m[2]), int(m[3])
    raise ValueError(f'stem não reconhecido: {stem}')


def stem_2026t2(uf: str, mun: int, zona: int, sec: int) -> str:
    return f'o03221{uf.lower()}{int(mun):05d}{int(zona):04d}{int(sec):04d}'


def raiz(pleito: str, uf: str) -> tuple[Path, Path]:
    """(pasta do pleito com logs/remote-inventory, pasta analysis) nas 11 UFs."""
    if pleito.startswith('2024'):
        return R / 'municipais' / uf / pleito, R / 'analysis' / 'PREFEITO' / uf / pleito
    if uf == 'BA':
        if pleito == '2022-t2':
            return R / 'piloto-ba-2022-t2', R / 'piloto-ba-2022-t2' / 'analysis'
        return R / 'bahia-presidente-2022-2026' / pleito, R / 'bahia-presidente-2022-2026' / pleito / 'analysis'
    return R / 'estados' / uf / pleito, R / 'estados' / uf / pleito / 'analysis'


def nome_contingencia(pleito: str, uf: str) -> str:
    if pleito.startswith('2024'):
        return f'municipais_{uf}_{pleito}'
    if uf == 'BA':
        return 'piloto-ba-2022-t2' if pleito == '2022-t2' else f'bahia-presidente-2022-2026_{pleito}'
    return f'estados_{uf}_{pleito}'


def manifesto_local(pleito: str, uf: str, stem: str) -> Path | None:
    for nome in (f'{stem}-vota.vsc', f'{stem}.vscmr'):
        p = ASSIN / pleito / uf / nome
        if p.exists():
            return p
    return None


def parse_dt(s: pd.Series) -> pd.Series:
    """Datas do BU em 'YYYY-MM-DD HH:MM:SS' ou 'DD/MM/YYYY HH:MM:SS' (nulos preservados)."""
    s = s.astype('string')
    a = pd.to_datetime(s, format='%Y-%m-%d %H:%M:%S', errors='coerce')
    b = pd.to_datetime(s, format='%d/%m/%Y %H:%M:%S', errors='coerce')
    return a.fillna(b)


# -------------------------------------------------------------------- manifesto (.vscmr / -vota.vsc) sem assinatura
# Travessia BER copiada de scripts/t2_2026_collect.py (_tlv/tree) e scripts/integridade_lib.py (parse_manifest), que
# dependem de httpx/cryptography; aqui só nomes e hashes SHA-512 dos blocos (a assinatura foi verificada na integridade).
def _tlv(b, i):
    t = b[i]
    i += 1
    cls, cons, num = t >> 6, bool(t & 0x20), t & 0x1f
    if num == 0x1f:
        num = 0
        while True:
            x = b[i]
            i += 1
            num = (num << 7) | (x & 0x7f)
            if not x & 0x80:
                break
    ln = b[i]
    i += 1
    if ln & 0x80:
        k = ln & 0x7f
        ln = int.from_bytes(b[i:i + k], 'big')
        i += k
    return cls, cons, num, i, ln


def _is_der(v):
    try:
        _, _, _, s, ln = _tlv(v, 0)
        if s + ln != len(v):
            return False
        _arvore(v)
        return True
    except Exception:
        return False


def _arvore(b, i=0, end=None):
    end = len(b) if end is None else end
    out = []
    while i < end:
        cls, cons, num, s, ln = _tlv(b, i)
        if s + ln > end:
            raise ValueError('TLV overruns parent')
        v = b[s:s + ln]
        if cons:
            out.append((cls, num, _arvore(b, s, s + ln)))
        elif cls == 0 and num == 4 and ln > 2 and v[0] == 0x30 and _is_der(v):
            out.append((cls, num, _arvore(v)))
        else:
            out.append((cls, num, v))
        i = s + ln
    return out


def _texto(v):
    return v.decode('latin-1') if isinstance(v, (bytes, bytearray)) else None


def blocos_manifesto(raw: bytes) -> list[dict]:
    """[{user, when, entries: {nome: sha512 hex}}] — um bloco por assinante (software 'SEVIN…', hardware 'UEAO…')."""
    top = _arvore(raw)[0][2]
    blocos = []
    for _c, _n, v in top:
        if not isinstance(v, list):
            continue
        user, when, entries = None, None, {}
        for c2, n2, v2 in v:
            if n2 == 27 and isinstance(v2, (bytes, bytearray)) and when is None and len(v2) == 15:
                when = _texto(v2)
            if isinstance(v2, list) and len(v2) == 4 and isinstance(v2[0][2], list) and user is None:
                try:
                    user = _texto(v2[0][2][0][2])
                except Exception:
                    pass
            if c2 == 0 and n2 == 4 and isinstance(v2, list):
                try:
                    for e in v2[0][2][0][2]:
                        nome = _texto(e[2][0][2])
                        entries[nome] = bytes(e[2][1][2][1][2]).hex()
                except Exception:
                    pass
        if user is not None:
            blocos.append({'user': user, 'when': when, 'entries': entries})
    return blocos


def bloco_hardware(blocos: list[dict]) -> dict | None:
    return next((b for b in blocos if (b['user'] or '').upper().startswith('UEAO')), None)


# ------------------------------------------------------------------------------------ pacotes de log e fatos do log
def _is_zip(data: bytes) -> bool:
    return data[:4] == b'PK\x03\x04'


def _is_7z(data: bytes) -> bool:
    return data[:6] == b'7z\xbc\xaf\x27\x1c'


def membros_pacote(data: bytes, depth: int = 0) -> list[tuple[int, str, str, bytes]]:
    """[(profundidade, nome, tipo, bytes)] de um pacote zip (2024/2026) ou 7z (2022): tipo 'logd' para logd.dat,
    'pacote' para .jez/.logjez aninhado (seus membros seguem com profundidade+1), 'outro' para o resto (bytes vazios)."""
    if depth > 3 or len(data) > MAX_PACOTE:
        return []
    out = []
    if _is_zip(data):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for e in z.infolist():
                nome = PurePosixPath(e.filename.replace('\\', '/')).name
                if e.file_size > MAX_LOG or '..' in e.filename:
                    continue
                low = nome.lower()
                if low == 'logd.dat':
                    out.append((depth, nome, 'logd', z.read(e)))
                elif low.endswith(NESTED):
                    blob = z.read(e)
                    out.append((depth, nome, 'pacote', blob))
                    out += membros_pacote(blob, depth + 1)
                else:
                    out.append((depth, nome, 'outro', b''))
    elif _is_7z(data):
        import py7zr
        from py7zr.io import BytesIOFactory
        with py7zr.SevenZipFile(io.BytesIO(data)) as z:
            entradas = z.list()
            if len(entradas) > 100 or sum(e.uncompressed for e in entradas) > MAX_PACOTE:
                raise ValueError('7z excede limite de extração')
            quer = [e.filename for e in entradas if not e.is_directory]
            factory = BytesIOFactory(MAX_PACOTE)
            if quer:
                z.extract(targets=quer, factory=factory)
            for nome_c in quer:
                nome = PurePosixPath(nome_c.replace('\\', '/')).name
                blob = factory.get(nome_c).read()
                low = nome.lower()
                if low == 'logd.dat':
                    out.append((depth, nome, 'logd', blob))
                elif low.endswith(NESTED):
                    out.append((depth, nome, 'pacote', blob))
                    out += membros_pacote(blob, depth + 1)
                else:
                    out.append((depth, nome, 'outro', b''))
    return out


def votos_no_dia(raw: bytes, dia: bytes) -> int:
    n, i = 0, raw.find(VOTE_LINE)
    while i >= 0:
        n += raw.startswith(dia, raw.rfind(b'\n', 0, i) + 1)
        i = raw.find(VOTE_LINE, i + len(VOTE_LINE))
    return n


def fatos_log(raw: bytes, dias: dict[str, str]) -> dict:
    """Primeira linha (instante do logd, serial = 3º campo), seções declaradas na carga, linhas e votos por dia."""
    primeira = raw[:raw.find(b'\n')] if b'\n' in raw else raw[:200]
    f = primeira.decode('latin-1', 'replace').rstrip('\r').split('\t')
    r = {'primeira_linha': f[0], 'serial': f[2] if len(f) > 2 else '', 'linhas': raw.count(b'\n'), 'bytes': len(raw),
         'secoes_declaradas': '|'.join(str(int(s)) for s in sorted({s for s in SECTION_LINE.findall(raw)})),
         'sha512_16': hashlib.sha512(raw).hexdigest()[:16]}
    for rotulo, dia in dias.items():
        r[f'votos_{rotulo}'] = votos_no_dia(raw, dia.encode())
    return r


def sequencia_apos_ultimo_computado(texto: str, dia: str, max_linhas: int = 60) -> list[dict]:
    """Linhas do dia a partir do último 'voto computado' (hora, nível, app, mensagem com números longos mascarados)."""
    linhas = [ln.split('\t') for ln in texto.splitlines() if ln.startswith(dia)]
    idx = [i for i, f in enumerate(linhas) if len(f) > 4 and f[4] == COMPUTADO]
    if not idx:
        return []
    out = []
    for f in linhas[idx[-1]:idx[-1] + 1 + max_linhas]:
        if len(f) > 4:
            out.append({'hora': f[0][11:], 'nivel': f[1], 'app': f[3], 'mensagem': MASCARA.sub('#', f[4])})
    return out


INICIO_ELEITOR = ('Aguardando digitação do título', 'Aguardando digitação do identificador do eleitor',
                  'Eleitor foi habilitado')


def confirmados_sem_computado(texto: str, dia: str, janela: int = 60) -> tuple[int, int, list[list[dict]]]:
    """(nº de 'Voto confirmado', nº de 'computado', janelas) do dia: cada janela é a sequência de linhas, a partir de um
    'Voto confirmado para [cargo]' que não foi seguido de 'O voto do eleitor foi computado' antes do próximo eleitor
    (novo título/habilitação) ou de nova confirmação do mesmo cargo. Números longos mascarados."""
    n_conf = n_comp = 0
    pend: list[dict] | None = None
    cargos: set[str] = set()
    janelas: list[list[dict]] = []

    def fecha():
        nonlocal pend, cargos
        if pend is not None:
            janelas.append(pend)
        pend, cargos = None, set()

    for ln in texto.splitlines():
        if not ln.startswith(dia):
            continue
        f = ln.split('\t')
        if len(f) < 5:
            continue
        msg = f[4]
        reg = {'hora': f[0][11:], 'nivel': f[1], 'app': f[3], 'mensagem': MASCARA.sub('#', msg)}
        m = CONFIRMADO.match(msg)
        if m:
            n_conf += 1
            if pend is not None and m[1] in cargos:
                fecha()
            if pend is None:
                pend, cargos = [reg], {m[1]}
            else:
                cargos.add(m[1])
                pend.append(reg)
        elif msg == COMPUTADO:
            n_comp += 1
            pend, cargos = None, set()
        elif msg in INICIO_ELEITOR:
            fecha()
        elif pend is not None and len(pend) < janela:
            pend.append(reg)
    fecha()
    return n_conf, n_comp, janelas


def classifica_caso_c2_01(bu, votos_releitura, log_antigo, n_logd, contingencia, tem_arquivo, orfaos, duplicados,
                          outra_secao) -> tuple[str, str]:
    """(classificação descritiva, status sugerido) de uma seção log ≠ BU de 2026 T2, a partir dos fatos do pacote:
    nº de logd.dat, urna de contingência, cópias duplicadas do mesmo log, logs de outra seção e 'Voto confirmado' órfãos."""
    if not tem_arquivo:
        return ('log ausente no zip de dados abertos; BU e RDV publicados', 'NAO_TESTAVEL')
    if votos_releitura is None or pd.isna(votos_releitura):
        return ('log não lido na releitura', 'NAO_TESTAVEL')
    dif = int(votos_releitura) - int(bu)
    if dif == 0:
        if log_antigo is not None and not pd.isna(log_antigo) and int(log_antigo) > int(bu):
            if duplicados:
                return ('ARTEFATO do leitor antigo: o pacote traz duas exportações do mesmo log (mesma primeira linha e '
                        'mesmo serial) e o leitor somava as duas; a releitura deduplica pela primeira linha e bate com o BU',
                        'ARTEFATO')
            if outra_secao:
                return ('ARTEFATO do leitor antigo: o pacote traz o log da urna de outra seção (urna de contingência que '
                        'recuperou 2 seções) e o filtro por seção declarada não escolhia; a releitura usa a seção do nome '
                        'do arquivo (section_hint, 04/11/2026) e bate com o BU', 'ARTEFATO')
            return ('ARTEFATO do leitor antigo; a releitura aninhada bate com o BU', 'ARTEFATO')
        return ('log = BU após a releitura aninhada', 'EXPLICADO')
    if dif < 0 and orfaos == -dif:
        return (f'{orfaos} voto(s) com "Voto confirmado" sem a linha "computado" no log (interrupção entre confirmar e '
                'computar); BU e RDV registram o voto', 'EXPLICADO')
    if dif < 0 and ((n_logd or 0) > 1 or bool(contingencia)):
        return (f'pacote publicado sem o log de uma urna intermediária ({-dif} votos sem log; troca de urna)',
                'NAO_TESTAVEL')
    if dif > 0:
        return (f'log com {dif} votos a mais que o BU após a releitura', 'INEXPLICADO')
    return (f'log com {-dif} votos a menos que o BU após a releitura', 'INEXPLICADO')


# ------------------------------------------------------------------------------------ funções puras das checagens
def classifica_manual(df: pd.DataFrame) -> pd.DataFrame:
    """Comparabilidade e diferença d = manual do log − manual do BU por seção, com a classe que pode explicá-la."""
    d = df.copy()
    sem_log = d['member'].isna()
    sem_cont = d['manual_sequence_votes'].isna() | d['manual_bu'].isna()
    d['comparavel'] = np.where(sem_log, 'NOT_COMPARABLE: sem log casado',
                               np.where(sem_cont, 'NOT_COMPARABLE: contagem ausente', 'comparavel'))
    d['d'] = d['manual_sequence_votes'] - d['manual_bu']
    d['dif_votos'] = d['vote_events'] - d['attendance']
    agg = d['aggregation_raw'] if 'aggregation_raw' in d else pd.Series(pd.NA, index=d.index)
    d['agregada'] = agg.notna() & ~agg.astype('string').isin(['', '#NULO#'])
    d['contingencia_nome'] = d['identity_status'].eq('PARSED_FILENAME')
    d['log_incompleto'] = d['dif_votos'].fillna(0).ne(0)
    d['classe'] = np.select(
        [d['comparavel'].ne('comparavel'), d['contingencia_nome'], d['log_incompleto'], d['agregada']],
        ['não comparável', 'contingência (identidade pelo nome)', 'log ≠ BU em votos', 'seção agregada'], 'limpa')
    d['discorda'] = d['comparavel'].eq('comparavel') & d['d'].fillna(0).ne(0)
    d['d_igual_dif_votos'] = d['discorda'] & d['d'].eq(d['dif_votos'])
    return d


def resumo_manual(d: pd.DataFrame, por: list[str]) -> pd.DataFrame:
    comp = d[d['comparavel'].eq('comparavel')]
    limpa = comp[comp['classe'].eq('limpa')]
    disc = comp[comp['discorda']]

    def agg(g, pref):
        return g.groupby(por).size().rename(pref)

    r = pd.concat([d.groupby(por).size().rename('secoes'), agg(comp, 'comparaveis'), agg(disc, 'discordantes'),
                   agg(limpa, 'limpa_n'), agg(limpa[limpa['discorda']], 'limpa_discordantes'),
                   agg(disc[disc['d'] > 0], 'log_maior'), agg(disc[disc['d'] < 0], 'log_menor'),
                   agg(disc[disc['d_igual_dif_votos']], 'd_igual_dif_votos'),
                   disc.groupby(por)['d'].apply(lambda s: float(s.abs().median())).rename('mediana_abs_d'),
                   disc.groupby(por)['d'].sum().rename('soma_d'),
                   comp.groupby(por)['manual_sequence_votes'].sum().rename('manual_log'),
                   comp.groupby(por)['manual_bu'].sum().rename('manual_bu')], axis=1).fillna(0).reset_index()
    for c in ['comparaveis', 'discordantes', 'limpa_n', 'limpa_discordantes', 'log_maior', 'log_menor',
              'd_igual_dif_votos', 'soma_d', 'manual_log', 'manual_bu']:
        r[c] = r[c].astype('int64')
    r['pct_discordantes'] = 100 * r['discordantes'] / r['comparaveis'].replace(0, np.nan)
    r['pct_limpa_discordantes'] = 100 * r['limpa_discordantes'] / r['limpa_n'].replace(0, np.nan)
    r['pct_manual_log_vs_bu'] = 100 * (r['manual_log'] - r['manual_bu']) / r['manual_bu'].replace(0, np.nan)
    return r


def taxa_por_fator(d: pd.DataFrame, fator: str, valores: pd.Series, por: str = 'eid') -> pd.DataFrame:
    """Taxa de discordância (manual log ≠ BU) com e sem o fator, por pleito, com razão de taxas."""
    comp = d[d['comparavel'].eq('comparavel')].assign(_f=valores.loc[d.index[d['comparavel'].eq('comparavel')]])
    g = comp.groupby([por, '_f'])['discorda'].agg(['size', 'sum']).reset_index()
    g.columns = [por, 'com_fator', 'n', 'discordantes']
    g['pct'] = 100 * g['discordantes'] / g['n']
    w = g.pivot(index=por, columns='com_fator', values=['n', 'discordantes', 'pct'])
    out = pd.DataFrame({'fator': fator, por: w.index,
                        'n_sem': w['n'].get(False, pd.Series(0, index=w.index)).values,
                        'disc_sem': w['discordantes'].get(False, pd.Series(0, index=w.index)).values,
                        'pct_sem': w['pct'].get(False, pd.Series(np.nan, index=w.index)).values,
                        'n_com': w['n'].get(True, pd.Series(0, index=w.index)).values,
                        'disc_com': w['discordantes'].get(True, pd.Series(0, index=w.index)).values,
                        'pct_com': w['pct'].get(True, pd.Series(np.nan, index=w.index)).values})
    out['razao_de_taxas'] = out['pct_com'] / out['pct_sem'].replace(0, np.nan)
    return out.reset_index(drop=True)


def histograma_d(d: pd.DataFrame, por: str = 'eid') -> pd.DataFrame:
    disc = d[d['discorda']].copy()
    cortes = [-np.inf, -10.5, -1.5, -0.5, 0.5, 1.5, 10.5, np.inf]
    rotulos = ['≤ −11', '−10 a −2', '−1', '0', '+1', '+2 a +10', '≥ +11']
    disc['faixa_d'] = pd.cut(disc['d'], cortes, labels=rotulos)
    h = disc.groupby([por, 'classe', 'faixa_d'], observed=True).size().rename('secoes').reset_index()
    return h


def relogio_log_x_bu(df: pd.DataFrame, dia: str) -> pd.DataFrame:
    """Minutos entre o último voto do log e o encerramento do BU, e entre a abertura do BU e o primeiro voto."""
    d = df.copy()
    base = pd.Timestamp(datetime.strptime(dia, '%d/%m/%Y'))
    abre = parse_dt(d['opening_bu'])
    fecha = parse_dt(d['closure_bu'])
    pv = pd.to_timedelta(d['first_vote'].astype('string'), errors='coerce')
    uv = pd.to_timedelta(d['last_vote'].astype('string'), errors='coerce')
    d['min_enc_bu_menos_ultimo_voto'] = (fecha - (base + uv)).dt.total_seconds() / 60
    d['min_primeiro_voto_menos_abertura_bu'] = ((base + pv) - abre).dt.total_seconds() / 60
    d['ultimo_voto_apos_encerramento_bu'] = d['min_enc_bu_menos_ultimo_voto'] < 0
    d['primeiro_voto_antes_da_abertura_bu'] = d['min_primeiro_voto_menos_abertura_bu'] < 0
    return d


def assinatura_vs_bu(df: pd.DataFrame, dia: str) -> pd.DataFrame:
    """assinado_em ('YYYYMMDDTHHMMSS', relógio da urna) contra emissão/encerramento do BU e recebimento no TSE."""
    d = df.copy()
    sig = pd.to_datetime(d['assinado_em'].astype('string'), format='%Y%m%dT%H%M%S', errors='coerce')
    d['assinado'] = sig
    dia_dt = datetime.strptime(dia, '%d/%m/%Y').date()
    for col, nome in (('emissao_bu', 'emissao'), ('encerramento', 'encerramento')):
        if col in d:
            d[f'min_assin_apos_{nome}'] = (sig - pd.to_datetime(d[col])).dt.total_seconds() / 60
            d[f'assinou_antes_da_{nome}'] = d[f'min_assin_apos_{nome}'] < 0
    d['min_recebido_apos_assin'] = (pd.to_datetime(d['recebido_tse']) - sig).dt.total_seconds() / 60
    d['assinou_depois_de_recebido'] = d['min_recebido_apos_assin'] < 0
    d['assinou_fora_do_dia'] = sig.notna() & (sig.dt.date != dia_dt)
    d['assinou_antes_17h'] = sig.notna() & (sig.dt.date == dia_dt) & (sig.dt.hour < 17)
    return d


def fase_do_erro(hora_erro, abertura, primeiro_voto, ultimo_voto, encerramento) -> str:
    """Posição do erro no dia: antes da abertura, durante a votação, após o último voto, depois do encerramento."""
    if pd.isna(hora_erro):
        return 'indeterminado'
    if pd.notna(abertura) and hora_erro < abertura:
        return 'antes_da_abertura'
    if pd.notna(primeiro_voto) and hora_erro < primeiro_voto:
        return 'entre_abertura_e_primeiro_voto'
    if pd.notna(ultimo_voto) and hora_erro <= ultimo_voto:
        return 'durante_votacao'
    if pd.notna(encerramento) and hora_erro <= encerramento:
        return 'entre_ultimo_voto_e_encerramento'
    if pd.notna(encerramento):
        return 'depois_do_encerramento'
    return 'indeterminado'


def assimetrias_inventario(inv: pd.DataFrame) -> pd.DataFrame:
    """Zips em que BU, log, RDV ou assinatura não batem entre si ou com o nº de urnas."""
    d = inv.copy()
    cols = ['bu_arquivos', 'log_arquivos', 'rdv_arquivos', 'assinatura_arquivos', 'urnas']
    for c in cols:
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d['log_menos_bu'] = d['log_arquivos'] - d['bu_arquivos']
    d['rdv_menos_bu'] = d['rdv_arquivos'] - d['bu_arquivos']
    d['assinatura_menos_bu'] = d['assinatura_arquivos'] - d['bu_arquivos']
    d['urnas_menos_bu'] = d['urnas'] - d['bu_arquivos']
    m = d[['log_menos_bu', 'rdv_menos_bu', 'assinatura_menos_bu', 'urnas_menos_bu']].fillna(0).ne(0).any(axis=1)
    m |= d['status'].astype('string').ne('ok')
    return d.loc[m, ['eleicao', 'uf', 'status', 'urnas'] + cols[:4] +
                 ['log_menos_bu', 'rdv_menos_bu', 'assinatura_menos_bu', 'urnas_menos_bu']].reset_index(drop=True)


def faltantes_por_tipo(nomes: list[str]) -> dict[str, list[str]]:
    """A partir dos nomes dos membros de um zip: stems que não têm cada tipo (bu, log, rdv, assinatura, imgbu)."""
    por_stem: dict[str, set] = {}
    for n in nomes:
        t = tipo_de(n)
        if t is None:
            continue
        por_stem.setdefault(stem_de(n), set()).add(t)
    out = {}
    for t in ('bu', 'log', 'rdv', 'assinatura', 'imgbu'):
        out[t] = sorted(s for s, ts in por_stem.items() if t not in ts and not (ts <= {'bu_sa', 'log_sa', 'assinatura_sa', 'imgbu_sa'}))
    out['_stems'] = sorted(por_stem)
    return out


def votos_aninhados(v1: pd.DataFrame, v2: pd.DataFrame) -> pd.DataFrame:
    """v1 (leitor antigo, só o logd.dat externo) × v2 (leitor aninhado): votos que só existem em logs aninhados."""
    m = v1.rename(columns={'votos_log': 'votos_externo'}).merge(
        v2.rename(columns={'votos_log': 'votos_todos'}), on='nome', how='outer')
    m['delta'] = m['votos_todos'] - m['votos_externo']
    m['status'] = np.select([m['votos_todos'].isna(), m['votos_externo'].isna(), m['delta'] > 0, m['delta'] < 0],
                            ['NOT_COMPARABLE: sem leitura aninhada', 'NOT_COMPARABLE: sem leitura externa',
                             'votos só em log aninhado', 'leitor externo contava mais'], 'iguais')
    return m


# ------------------------------------------------------------------------------------------------------ C2-01
def _linha_csv_decimal(path: Path, usecols: list[str] | None = None) -> pd.DataFrame:
    return pd.read_csv(path, sep=';', decimal=',', usecols=usecols, encoding='utf-8-sig')


def c2_01() -> dict:
    """Dossiê das 8 seções de 2026 T2 com log ≠ BU: fatos da sessão + evidência por logd.dat, manifesto, RDV e BU."""
    dias = {'t2': DIA['2026-t2'], 't1': DIA['2026-t1']}
    rec = pd.read_csv(RECONFERIDO, sep=';') if RECONFERIDO.exists() else pd.DataFrame()
    uv = _linha_csv_decimal(ULTIMO_VOTO, ['uf', 'municipality', 'zone', 'section', 'encerramento', 'recebimento',
                                           'path', 'votos_log', 'primeiro_voto', 'ultimo_voto', 'erro_log',
                                           'min_enc_menos_ultimo'])
    hab = pd.read_parquet(HAB_T2)
    base = pd.read_parquet(BASE_2026, columns=['uf', 'municipality', 'zone', 'section', 't2_aptos', 't2_comp', 't2_A',
                                                't2_B', 't2_branco', 't2_nulo'])
    bins = pd.read_parquet(BINS_2026, columns=['uf', 'municipality', 'zone', 'section', 'n_logs', 'contingencia'])
    but2 = pd.read_parquet(BU_T2, columns=['uf', 'municipality', 'zone', 'section', 'log_name', 'status', 'log_why',
                                           'hash_status', 'n_hashes', 'receipt_date', 'receipt_time',
                                           'e6258_comparecimento'])
    linhas, pacotes, manifestos, sequencias = [], [], [], []
    for uf, mun, zona, sec in CASOS_C2_01:
        stem = stem_2026t2(uf, mun, zona, sec)
        k = (uf, mun, zona, sec)

        def sel(df, cols=('uf', 'municipality', 'zone', 'section')):
            def inteiro(c):
                return pd.to_numeric(df[c], errors='coerce').fillna(-1).astype('int64')
            m = (df[cols[0]] == k[0]) & (inteiro(cols[1]) == k[1]) & (inteiro(cols[2]) == k[2]) & (inteiro(cols[3]) == k[3])
            return df[m].iloc[0] if m.any() else None

        row = {'uf': uf, 'municipality': mun, 'zone': zona, 'section': sec, 'stem': stem}
        r = sel(rec) if len(rec) else None
        if r is not None:
            row.update(bu=r['bu'], log_leitor_antigo=r['log_antes'], log_releitura_0311=r['log_completo'],
                       n_logs=r['n_logs'], contingencia=r['contingencia'])
        u = sel(uv)
        if u is not None:
            row.update(log_releitura_0411=u['votos_log'], primeiro_voto=u['primeiro_voto'], ultimo_voto=u['ultimo_voto'],
                       encerramento_bu=u['encerramento'], recebimento_tse=u['recebimento'],
                       min_enc_menos_ultimo=u['min_enc_menos_ultimo'], path_log=u['path'])
        else:
            row.update(log_releitura_0411=np.nan, path_log=None)
        h = sel(hab)
        if h is not None:
            row.update(hab_0=h['hab_0'], hab_1=h['hab_1'], hab_2=h['hab_2'], comparecimento_bu=h['comparecimento_bu'],
                       abertura_bu=h['opening'], encerramento_bu_hab=h['closing'])
        b = sel(base)
        if b is not None:
            row.update(t2_aptos=b['t2_aptos'], t2_comp=b['t2_comp'], t2_v13=b['t2_A'], t2_v22=b['t2_B'],
                       t2_branco=b['t2_branco'], t2_nulo=b['t2_nulo'])
        bi = sel(bins)
        if bi is not None:
            row.update(n_logs_bins=bi['n_logs'], contingencia_bins=bi['contingencia'])
        p_rdv = RDV_T2 / f'{uf}.parquet'
        if p_rdv.exists():
            rdv = pd.read_parquet(p_rdv, columns=['municipio', 'zona', 'secao', 'v13', 'v22', 'branco', 'nulo', 'outros'])
            rv = sel(rdv.assign(uf=uf), ('uf', 'municipio', 'zona', 'secao'))
            if rv is not None:
                row.update(rdv_v13=rv['v13'], rdv_v22=rv['v22'], rdv_branco=rv['branco'], rdv_nulo=rv['nulo'],
                           rdv_total=int(rv[['v13', 'v22', 'branco', 'nulo', 'outros']].sum()))
                row['rdv_igual_bu'] = (row['rdv_total'] == row.get('t2_comp')) and (rv['v13'] == row.get('t2_v13')) \
                    and (rv['v22'] == row.get('t2_v22'))
        if uf in UFS_T2_RESULTADOS:
            bt = sel(but2)
            row['sist_resultados'] = 'sem linha' if bt is None else (
                f"BU recebido {bt['receipt_date']} {bt['receipt_time']} ({bt['hash_status']}, n_hashes "
                f"{bt['n_hashes']}); log_name={bt['log_name']}; status={bt['status']}; log_why={bt['log_why']}")
            p_int = INTEG_RES / f'segundo_turno_2026_{uf}.parquet'
            if p_int.exists():
                it = pd.read_parquet(p_int)
                it = it[it['urna'] == stem]
                row['integridade_t2'] = 'não verificada (urna fora das 28.823)' if it.empty else json.dumps(
                    {c: (None if pd.isna(v) else str(v)) for c, v in it.iloc[0].items() if c not in ('uf', 'urna')},
                    ensure_ascii=False)
        else:
            row['sist_resultados'] = 'UF fora das 14 UFs coletadas no sistema de resultados'
        p_man = manifesto_local('2026-t2', uf, stem)
        hashes = set()
        if p_man is not None:
            blocos = blocos_manifesto(p_man.read_bytes())
            hw = bloco_hardware(blocos)
            row['manifesto'] = rel(p_man)
            row['manifesto_assinado_em'] = hw['when'] if hw else None
            row['manifesto_entradas_hw'] = '|'.join(sorted(hw['entries'])) if hw else None
            row['manifesto_lista_log'] = any(tipo_de(n) == 'log' for n in hw['entries']) if hw else None
            for bl in blocos:
                for nome, hx in bl['entries'].items():
                    manifestos.append({'stem': stem, 'bloco': bl['user'], 'assinado_em': bl['when'], 'entrada': nome,
                                       'sha512_16': hx[:16]})
                    hashes.add(hx)
        p_log = LOGS_2026T2 / uf / f'{stem}-log.jez'
        row['log_no_disco'] = p_log.exists()
        orfaos = duplicados = outra_secao = 0
        if p_log.exists():
            data = p_log.read_bytes()
            row['pacote_bytes'] = len(data)
            sha_ext = hashlib.sha512(data).hexdigest()
            row['pacote_externo_hash_no_manifesto'] = sha_ext in hashes if hashes else None
            membros = membros_pacote(data)
            fatos = []
            for dp, nm, tp, raw in membros:
                if tp == 'outro':
                    continue
                pr = {'stem': stem, 'profundidade': dp, 'membro': nm, 'tipo': tp, 'bytes': len(raw),
                      'sha512_no_manifesto': hashlib.sha512(raw).hexdigest() in hashes if hashes else None,
                      'coberto_pelo_hash_do_pacote_externo': row['pacote_externo_hash_no_manifesto']}
                if tp == 'logd':
                    pr.update(fatos_log(raw, dias))
                    fatos.append(pr)
                pacotes.append(pr)
            row['n_logd'] = len(fatos)
            chaves_log = [(f['primeira_linha'], f['serial']) for f in fatos]
            duplicados = len(chaves_log) - len(set(chaves_log))
            outra_secao = sum(1 for f in fatos if f['secoes_declaradas'] and
                              str(sec) not in f['secoes_declaradas'].split('|') and '0' not in f['secoes_declaradas'].split('|'))
            row['logd_duplicados'] = duplicados
            row['logd_de_outra_secao'] = outra_secao
            row['contingencia_pacote'] = any('0' in f['secoes_declaradas'].split('|') for f in fatos if f['secoes_declaradas'])
            # log reconstituído da seção (todas as urnas, deduplicado): 'Voto confirmado' sem 'computado' no dia
            try:
                from auditabr.logs import read_log
                texto = read_log(p_log).decode('utf-8-sig', 'replace')
            except Exception as exc:  # o leitor é do repositório; aqui só se registra a falha
                texto, row['erro_leitor'] = '', repr(exc)[:200]
            n_conf, n_comp, janelas = confirmados_sem_computado(texto, DIA['2026-t2'])
            orfaos = len(janelas)
            row.update(confirmados_dia=n_conf, computados_dia=n_comp, confirmados_sem_computado=orfaos)
            for j, jan in enumerate(janelas):
                for i, s in enumerate(jan):
                    sequencias.append({'stem': stem, 'janela': j, 'ordem': i, **s})
            row['mensagens_energia_nas_janelas'] = sum(
                1 for jan in janelas for s in jan if re.search(r'bateria|energia|desligad|religad', s['mensagem'], re.I))
        row['classificacao'], row['status_sugerido'] = classifica_caso_c2_01(
            row.get('bu', row.get('t2_comp')), row.get('log_releitura_0411'), row.get('log_releitura_0311'),
            row.get('n_logd'), row.get('contingencia_pacote', row.get('contingencia_bins')), row['log_no_disco'],
            orfaos, duplicados, outra_secao)
        linhas.append(row)
    dossie = pd.DataFrame(linhas)
    arqs = [grava_csv(dossie, 'C2-01_dossie_secoes.csv'), grava_csv(pd.DataFrame(pacotes), 'C2-01_logs_por_pacote.csv'),
            grava_csv(pd.DataFrame(manifestos), 'C2-01_manifestos.csv'),
            grava_csv(pd.DataFrame(sequencias), 'C2-01_votos_confirmados_sem_computado.csv'),
            grava_csv(pd.DataFrame(FATOS_SESSAO), 'C2-01_fatos_sessao.csv')]
    st = dossie['status_sugerido'].value_counts().to_dict()
    return {'status': 'feita', 'numeros_chave': {
        'secoes': len(dossie), 'status': st,
        'log_igual_bu_apos_releitura': int((dossie['log_releitura_0411'] == dossie['t2_comp']).sum()),
        'rdv_igual_bu': int(dossie['rdv_igual_bu'].fillna(False).sum()),
        'classificacao': dossie.set_index('stem')['classificacao'].to_dict()}, 'arquivos': arqs}


# ------------------------------------------------------------------------------------------------------ C2-07
COLS_IND = ['uf', 'municipality', 'zone', 'section', 'member', 'identity_status', 'vote_events', 'attendance',
            'manual_sequence_votes', 'manual_bu', 'manual_requests', 'cancellations', 'manual_unattributed_votes',
            'swap', 'red', 'contingency', 'has_log', 'log_complete', 'eligible', 'first_vote', 'last_vote',
            'opening_bu', 'closure_bu']


def carrega_indicadores(eid: str) -> pd.DataFrame:
    """secoes_indicadores_<eid> (derivado de sections.parquet + operations.jsonl das 11 UFs) + aggregation_raw de
    sections.parquet + geração da urna (cert_emissor) da integridade."""
    pleito = EID_PLEITO[eid]
    df = pd.read_parquet(INDICADORES / f'secoes_indicadores_{eid}.parquet', columns=COLS_IND)
    df['eid'], df['pleito'] = eid, pleito
    for c in ('municipality', 'zone', 'section'):
        df[c] = df[c].astype('int64')
    partes = []
    for uf in UFS_11:
        p = raiz(pleito, uf)[1] / 'sections.parquet'
        if not p.exists():
            continue
        if (uf, pleito) == ('BA', '2022-t2'):
            s = pd.read_parquet(p, columns=['municipality', 'zone', 'section', 'office', 'aggregated_raw'])
            s = s[s['office'].str.upper() == 'PRESIDENTE'].drop(columns='office').rename(
                columns={'aggregated_raw': 'aggregation_raw'})
        else:
            s = pd.read_parquet(p, columns=['municipality', 'zone', 'section', 'aggregation_raw'])
        s['uf'] = uf
        partes.append(s)
    agg = pd.concat(partes, ignore_index=True)
    for c in ('municipality', 'zone', 'section'):
        agg[c] = agg[c].astype('int64')
    agg = agg.drop_duplicates(['uf', 'municipality', 'zone', 'section'])
    df = df.merge(agg, on=['uf', 'municipality', 'zone', 'section'], how='left')
    df['stem'] = df['member'].map(lambda m: stem_de(m) if isinstance(m, str) else None)
    c = con()
    emis = c.execute('SELECT urna AS stem, cert_emissor FROM read_parquet(?) WHERE eleicao = ?',
                     [str(INTEGRIDADE), pleito]).df()
    c.close()
    return df.merge(emis.drop_duplicates('stem'), on='stem', how='left')


def c2_07() -> dict:
    """25.450 seções com habilitação manual do log ≠ sem biometria do BU: sinal, tamanho, classe e hipóteses."""
    resumos, hips, hists, disc_all, quar, ger = [], [], [], [], [], []
    por_classe = []
    for eid in EID_PLEITO:
        d = classifica_manual(carrega_indicadores(eid))
        comp = d['comparavel'].eq('comparavel')
        bad = d[comp & ((d['manual_bu'] > d['attendance']) | (d['manual_sequence_votes'] > d['vote_events']))]
        for r in bad.itertuples():
            quar.append({'eid': eid, 'uf': r.uf, 'municipality': r.municipality, 'zone': r.zone, 'section': r.section,
                         'manual_bu': r.manual_bu, 'attendance': r.attendance,
                         'manual_sequence_votes': r.manual_sequence_votes, 'vote_events': r.vote_events,
                         'reason': 'habilitação manual maior que o comparecimento/votos computados'})
        resumos.append(resumo_manual(d, ['eid', 'uf']))
        por_classe.append(resumo_manual(d.assign(classe_=d['classe']), ['eid', 'classe_']))
        fatores = {'contingência (identidade pelo nome)': d['contingencia_nome'],
                   'log ≠ BU em votos': d['log_incompleto'], 'seção agregada': d['agregada'],
                   'troca de urna (CEFT swap)': d['swap'].fillna(False).astype(bool),
                   'BU gerado por RED (CEFT)': d['red'].fillna(False).astype(bool),
                   'cancelamentos > 0': d['cancellations'].fillna(0) > 0,
                   'habilitação manual sem mesário associado > 0': d['manual_unattributed_votes'].fillna(0) > 0,
                   'solicitações manuais sem voto (requests − manual) > 0':
                       (d['manual_requests'].fillna(0) - d['manual_sequence_votes'].fillna(0)) > 0}
        for nome, val in fatores.items():
            hips.append(taxa_por_fator(d, nome, val))
        limpa = d[d['classe'].eq('limpa')]
        for nome, val in list(fatores.items())[5:]:
            hips.append(taxa_por_fator(limpa, nome + ' [só classe limpa]', val.loc[limpa.index]))
        hists.append(histograma_d(d))
        g = limpa.groupby(['eid', 'cert_emissor'], dropna=False)['discorda'].agg(['size', 'sum']).reset_index()
        g.columns = ['eid', 'cert_emissor', 'limpa_n', 'limpa_discordantes']
        g['pct'] = 100 * g['limpa_discordantes'] / g['limpa_n']
        ger.append(g)
        disc = d[d['discorda']][['eid', 'pleito', 'uf', 'municipality', 'zone', 'section', 'member', 'identity_status',
                                 'classe', 'vote_events', 'attendance', 'dif_votos', 'manual_sequence_votes',
                                 'manual_bu', 'd', 'd_igual_dif_votos', 'manual_requests', 'cancellations',
                                 'manual_unattributed_votes', 'swap', 'red', 'agregada', 'cert_emissor']]
        disc_all.append(disc)
        del d, limpa
    resumo = pd.concat(resumos, ignore_index=True)
    classes = pd.concat(por_classe, ignore_index=True)
    hip = pd.concat(hips, ignore_index=True)
    disc = pd.concat(disc_all, ignore_index=True)
    # 2022 T1 × T2 lado a lado por UF e classe
    t = resumo[resumo['eid'].isin(['P2022', 'P2022b'])].pivot(
        index='uf', columns='eid', values=['comparaveis', 'discordantes', 'pct_discordantes', 'limpa_n',
                                           'limpa_discordantes', 'pct_limpa_discordantes'])
    t.columns = [f'{a}_{b}' for a, b in t.columns]
    t = t.reset_index()
    t['razao_pct_t1_t2'] = t['pct_discordantes_P2022'] / t['pct_discordantes_P2022b']
    t['razao_pct_limpa_t1_t2'] = t['pct_limpa_discordantes_P2022'] / t['pct_limpa_discordantes_P2022b']
    arqs = [grava_csv(resumo, 'C2-07_resumo_pleito_uf.csv'), grava_csv(classes, 'C2-07_resumo_por_classe.csv'),
            grava_csv(hip, 'C2-07_hipoteses.csv'), grava_csv(pd.concat(hists, ignore_index=True), 'C2-07_distribuicao_d.csv'),
            grava_csv(pd.concat(ger, ignore_index=True), 'C2-07_por_geracao_urna.csv'),
            grava_csv(disc, 'C2-07_secoes_discordantes.csv'), grava_csv(t, 'C2-07_2022_t1_x_t2.csv')]
    q = quarentena('07', quar)
    if q:
        arqs.append(q)
    tot = resumo.groupby('eid')[['comparaveis', 'discordantes', 'limpa_n', 'limpa_discordantes', 'log_maior',
                                 'log_menor', 'd_igual_dif_votos']].sum()
    tot['pct'] = 100 * tot['discordantes'] / tot['comparaveis']
    tot['pct_limpa'] = 100 * tot['limpa_discordantes'] / tot['limpa_n']
    cl = classes.groupby('classe_')['discordantes'].sum().to_dict()
    return {'status': 'feita', 'numeros_chave': {'total_discordantes': int(tot['discordantes'].sum()),
                                                 'total_comparaveis': int(tot['comparaveis'].sum()),
                                                 'por_pleito': tot.round(3).to_dict('index'),
                                                 'discordantes_por_classe': cl, 'quarentena': len(quar)},
            'arquivos': arqs}


# ------------------------------------------------------------------------------------------------------ C2-08
def c2_08() -> dict:
    """Relógio do log × relógio do BU (parte leve): último voto × encerramento, primeiro voto × abertura, por seção."""
    res, exc = [], []
    for eid, pleito in EID_PLEITO.items():
        d = classifica_manual(carrega_indicadores(eid))
        d = relogio_log_x_bu(d, DIA[pleito])
        comp = d[d['comparavel'].eq('comparavel') & d['min_enc_bu_menos_ultimo_voto'].notna()]
        for classe, g in comp.groupby('classe'):
            for uf, gg in g.groupby('uf'):
                res.append({'eid': eid, 'pleito': pleito, 'uf': uf, 'classe': classe, 'n': len(gg),
                            'mediana_min_enc_menos_ultimo': gg['min_enc_bu_menos_ultimo_voto'].median(),
                            'p01': gg['min_enc_bu_menos_ultimo_voto'].quantile(0.01),
                            'p99': gg['min_enc_bu_menos_ultimo_voto'].quantile(0.99),
                            'ultimo_voto_apos_encerramento': int(gg['ultimo_voto_apos_encerramento_bu'].sum()),
                            'ultimo_voto_apos_enc_mais_2min': int((gg['min_enc_bu_menos_ultimo_voto'] < -2).sum()),
                            'mediana_min_primeiro_menos_abertura': gg['min_primeiro_voto_menos_abertura_bu'].median(),
                            'primeiro_voto_antes_da_abertura': int(gg['primeiro_voto_antes_da_abertura_bu'].sum()),
                            'primeiro_voto_antes_abertura_mais_2min':
                                int((gg['min_primeiro_voto_menos_abertura_bu'] < -2).sum())})
        e = comp[(comp['min_enc_bu_menos_ultimo_voto'] < -2) | (comp['min_primeiro_voto_menos_abertura_bu'] < -2)]
        exc.append(e[['eid', 'pleito', 'uf', 'municipality', 'zone', 'section', 'member', 'classe', 'identity_status',
                      'opening_bu', 'first_vote', 'last_vote', 'closure_bu', 'min_enc_bu_menos_ultimo_voto',
                      'min_primeiro_voto_menos_abertura_bu', 'vote_events', 'attendance']])
        del d, comp
    resumo = pd.DataFrame(res)
    excecoes = pd.concat(exc, ignore_index=True)
    # 2026 T2: último voto (leitor aninhado) × encerramento do BU, nacional (coluna já calculada em ultimo_voto_por_secao)
    c = con()
    t2 = c.execute("""SELECT uf, count(*) n, median(min_enc_menos_ultimo) mediana, quantile_cont(min_enc_menos_ultimo, 0.01) p01,
        quantile_cont(min_enc_menos_ultimo, 0.99) p99, count(*) FILTER (WHERE min_enc_menos_ultimo < 0) ultimo_voto_apos_encerramento,
        count(*) FILTER (WHERE min_enc_menos_ultimo < -2) ultimo_voto_apos_enc_mais_2min
        FROM read_csv(?, delim=';', header=true, decimal_separator=',') GROUP BY uf ORDER BY uf""", [str(ULTIMO_VOTO)]).df()
    t2x = c.execute("""SELECT uf, municipality, zone, section, encerramento, primeiro_voto, ultimo_voto, votos_log, min_enc_menos_ultimo
        FROM read_csv(?, delim=';', header=true, decimal_separator=',') WHERE min_enc_menos_ultimo < -2
        ORDER BY min_enc_menos_ultimo""", [str(ULTIMO_VOTO)]).df()
    # 2026 T2 (14.769 seções marcadas): encerramento do log ('encerrou_min') × encerramento do BU (hab_2026_t2.closing)
    ls = pd.read_parquet(LOGS_SECOES, columns=['uf', 'municipality', 'zone', 'section', 'grupo', 'encerrou_min',
                                               'ultimo_voto', 'min_ultimo_voto_ate_encerrar'])
    hab = pd.read_parquet(HAB_T2, columns=['uf', 'municipality', 'zone', 'section', 'closing'])
    ls = ls.merge(hab, on=['uf', 'municipality', 'zone', 'section'], how='left')
    fecha = pd.to_datetime(ls['closing'].astype('string'), errors='coerce')
    ls['encerramento_bu_min'] = fecha.dt.hour * 60 + fecha.dt.minute + fecha.dt.second / 60
    ls['min_bu_menos_log'] = ls['encerramento_bu_min'] - ls['encerrou_min']
    bins = pd.read_parquet(BINS_2026, columns=['uf', 'municipality', 'zone', 'section', 'n_logs', 'contingencia'])
    ls = ls.merge(bins, on=['uf', 'municipality', 'zone', 'section'], how='left')
    ls['fora_de_2min'] = ls['min_bu_menos_log'].abs() > 2
    enc = ls.groupby('grupo').agg(n=('min_bu_menos_log', 'size'), com_ambos=('min_bu_menos_log', 'count'),
                                  mediana=('min_bu_menos_log', 'median'),
                                  p01=('min_bu_menos_log', lambda s: s.quantile(0.01)),
                                  p99=('min_bu_menos_log', lambda s: s.quantile(0.99)),
                                  fora_de_2min=('fora_de_2min', 'sum'),
                                  fora_de_2min_com_mais_de_um_log=('n_logs', lambda s: int(((s > 1) & ls.loc[s.index, 'fora_de_2min']).sum())),
                                  fora_de_2min_contingencia=('contingencia', lambda s: int((s.fillna(False).astype(bool)
                                                                                           & ls.loc[s.index, 'fora_de_2min']).sum())),
                                  fora_de_2min_bu_antes_do_log=('min_bu_menos_log', lambda s: int((s < -2).sum()))).reset_index()
    fora = ls[ls['fora_de_2min']][['uf', 'municipality', 'zone', 'section', 'grupo', 'n_logs', 'contingencia', 'closing', 'encerrou_min',
                                   'ultimo_voto', 'encerramento_bu_min', 'min_bu_menos_log']].sort_values('min_bu_menos_log')
    arqs = [grava_csv(resumo, 'C2-08_log_x_bu_por_pleito_uf_classe.csv'), grava_csv(excecoes, 'C2-08_excecoes.csv'),
            grava_csv(t2, 'C2-08_2026t2_ultimo_voto_x_encerramento_uf.csv'),
            grava_csv(t2x, 'C2-08_2026t2_excecoes.csv'), grava_csv(enc, 'C2-08_2026t2_encerrou_log_x_bu_grupos.csv'),
            grava_csv(fora, 'C2-08_2026t2_encerrou_fora_de_2min.csv')]
    limpa = resumo[resumo['classe'].eq('limpa')].groupby('eid')[['n', 'ultimo_voto_apos_encerramento',
                                                                 'ultimo_voto_apos_enc_mais_2min',
                                                                 'primeiro_voto_antes_da_abertura']].sum()
    return {'status': 'parcial', 'motivo': 'parte leve: horários do log vêm do leitor antigo (só o logd.dat externo) nas '
            '11 UFs; a parte nacional por tipo de evento depende da passada de logs (C2-02)',
            'numeros_chave': {'limpa_por_pleito': limpa.to_dict('index'),
                              '2026t2_ultimo_voto_apos_encerramento': int(t2['ultimo_voto_apos_encerramento'].sum()),
                              '2026t2_mais_de_2min': int(t2['ultimo_voto_apos_enc_mais_2min'].sum()),
                              '2026t2_secoes': int(t2['n'].sum()),
                              'encerrou_log_x_bu_fora_de_2min': int(enc['fora_de_2min'].sum()),
                              'excecoes_11ufs': int(len(excecoes))}, 'arquivos': arqs}


# ------------------------------------------------------------------------------------------------------ C2-09
def le_cache(pasta: Path) -> pd.DataFrame:
    partes = [pd.read_parquet(p, columns=['nome', 'votos_log']) for p in sorted(pasta.glob('*.parquet'))]
    return pd.concat(partes, ignore_index=True).drop_duplicates('nome') if partes else pd.DataFrame(columns=['nome', 'votos_log'])


def confere_pacote_manifesto(p_pacote: Path, p_manifesto: Path | None, dias: dict[str, str]) -> list[dict]:
    """Cada logd.dat/.jez do pacote com o seu SHA-512 e se algum bloco do manifesto da urna final o lista."""
    data = p_pacote.read_bytes()
    blocos = blocos_manifesto(p_manifesto.read_bytes()) if p_manifesto and p_manifesto.exists() else []
    hashes = {h for b in blocos for h in b['entries'].values()}
    hw = bloco_hardware(blocos)
    sha_ext = hashlib.sha512(data).hexdigest()
    entrada_log = next((h for b in blocos for n, h in b['entries'].items() if tipo_de(n) == 'log'), None)
    base = {'pacote': p_pacote.name, 'manifesto_no_disco': bool(blocos), 'n_entradas_hw': len(hw['entries']) if hw else None,
            'entradas_manifesto': ','.join(sorted({n for b in blocos for n in b['entries']})),
            'assinado_em': hw['when'] if hw else None,
            'pacote_externo_hash_ok': (sha_ext == entrada_log) if entrada_log else None}
    out = []
    for dp, nm, tp, raw in membros_pacote(data):
        if tp == 'outro':
            continue
        r = {**base, 'profundidade': dp, 'membro': nm, 'tipo': tp, 'bytes': len(raw),
             'sha512_no_manifesto': hashlib.sha512(raw).hexdigest() in hashes if hashes else None}
        if tp == 'logd':
            r.update(fatos_log(raw, dias))
        out.append(r)
    return out


def c2_09(amostra_2026: int = 300, amostra_2022: int = 60, limite_min: float = 30.0) -> dict:
    """Manifesto × logs aninhados: votos que só existem em logs aninhados (2026 T2, nacional) e, por amostra, se os
    logd.dat aninhados têm hash em algum bloco do manifesto da urna final (2026 T2) — controle 2022 T2 (pacotes 7z)."""
    t0 = time.time()
    bins = pd.read_parquet(BINS_2026, columns=['uf', 'municipality', 'zone', 'section', 'n_logs', 'contingencia'])
    v1, v2 = le_cache(CACHE_V1), le_cache(CACHE_V2)
    vv = votos_aninhados(v1, v2)
    ch = vv['nome'].map(lambda n: chave_do_stem(stem_de(n)))
    vv[['uf', 'municipality', 'zone', 'section']] = pd.DataFrame(ch.tolist(), index=vv.index)
    vv = vv.merge(bins, on=['uf', 'municipality', 'zone', 'section'], how='outer')
    vv['status'] = vv['status'].fillna('NOT_COMPARABLE: seção sem leitura em cache')
    inputs = [BINS_2026] + sorted(CACHE_V1.glob('*.parquet')) + sorted(CACHE_V2.glob('*.parquet'))
    arqs = [grava_parquet(vv, 'C2-09_votos_por_leitor_2026t2.parquet', inputs)]
    por_uf = vv.groupby('uf').agg(secoes=('nome', 'size'), n_logs_gt1=('n_logs', lambda s: int((s > 1).sum())),
                                  contingencia=('contingencia', lambda s: int(s.fillna(False).sum())),
                                  secoes_com_votos_so_em_aninhado=('delta', lambda s: int((s > 0).sum())),
                                  votos_so_em_aninhado=('delta', lambda s: int(s[s > 0].sum())),
                                  secoes_externo_contava_mais=('delta', lambda s: int((s < 0).sum())),
                                  votos_externo_a_mais=('delta', lambda s: int(-s[s < 0].sum()))).reset_index()
    arqs.append(grava_csv(por_uf, 'C2-09_votos_em_logs_aninhados_por_uf.csv'))
    arqs.append(grava_csv(vv[vv['delta'].fillna(0).ne(0) | (vv['n_logs'] > 1)].sort_values(['uf', 'municipality', 'zone', 'section']),
                          'C2-09_secoes_com_log_aninhado.csv'))
    # amostra de pacotes 2026 T2 × manifesto (todas as seções com ≥ 3 logs + sorteio entre as de 2)
    multi = bins[bins['n_logs'] > 1]
    rng = np.random.default_rng(SEED)
    dois = multi[multi['n_logs'] == 2]
    sel = pd.concat([multi[multi['n_logs'] >= 3], dois.iloc[rng.choice(len(dois), min(amostra_2026, len(dois)), replace=False)]])
    dias = {'t2': DIA['2026-t2'], 't1': DIA['2026-t1']}
    linhas, lidos, falhas = [], 0, []
    for r in sel.itertuples():
        if (time.time() - t0) / 60 > limite_min:
            break
        stem = stem_2026t2(r.uf, r.municipality, r.zone, r.section)
        p = LOGS_2026T2 / r.uf / f'{stem}-log.jez'
        if not p.exists():
            falhas.append({'pleito': '2026-t2', 'stem': stem, 'erro': 'pacote não está no disco'})
            continue
        try:
            for ln in confere_pacote_manifesto(p, manifesto_local('2026-t2', r.uf, stem), dias):
                linhas.append({'pleito': '2026-t2', 'uf': r.uf, 'municipality': r.municipality, 'zone': r.zone,
                               'section': r.section, 'n_logs_bins': r.n_logs, **ln})
            lidos += 1
        except Exception as exc:
            falhas.append({'pleito': '2026-t2', 'stem': stem, 'erro': repr(exc)[:200]})
    # controle 2022 T2: pacotes 7z com urna de contingência (research/contingencia), 10 UFs de research/estados
    cands = []
    for uf in [u for u in UFS_11 if u != 'BA']:
        p = CONTINGENCIA / f'estados_{uf}_2022-t2.parquet'
        if p.exists():
            c = pd.read_parquet(p, columns=['member', 'contingency_start', 'votes'])
            c = c[c['contingency_start'].astype('string').fillna('').ne('')]
            c['uf'] = uf
            cands.append(c)
    cands = pd.concat(cands, ignore_index=True) if cands else pd.DataFrame(columns=['member', 'uf'])
    if len(cands):
        cands = cands.iloc[rng.choice(len(cands), min(amostra_2022, len(cands)), replace=False)]
    dias22 = {'t2': DIA['2022-t2'], 't1': DIA['2022-t1']}
    lidos22 = 0
    for r in cands.itertuples():
        if (time.time() - t0) / 60 > limite_min:
            break
        p = raiz('2022-t2', r.uf)[0] / 'logs' / r.member
        stem = stem_de(r.member)
        if not p.exists():
            falhas.append({'pleito': '2022-t2', 'stem': stem, 'erro': 'pacote não está no disco'})
            continue
        try:
            _, mun, zona, sec = chave_do_stem(stem)
            for ln in confere_pacote_manifesto(p, manifesto_local('2022-t2', r.uf, stem), dias22):
                linhas.append({'pleito': '2022-t2', 'uf': r.uf, 'municipality': mun, 'zone': zona, 'section': sec,
                               'n_logs_bins': None, **ln})
            lidos22 += 1
        except Exception as exc:
            falhas.append({'pleito': '2022-t2', 'stem': stem, 'erro': repr(exc)[:200]})
    am = pd.DataFrame(linhas)
    arqs.append(grava_csv(am, 'C2-09_amostra_pacotes_x_manifesto.csv'))
    if falhas:
        arqs.append(grava_csv(pd.DataFrame(falhas), 'C2-09_amostra_falhas.csv'))
    num = {'secoes_2026t2': int(len(vv)), 'n_logs_gt1': int((vv['n_logs'] > 1).sum()),
           'secoes_com_votos_so_em_aninhado': int((vv['delta'] > 0).sum()),
           'votos_so_em_logs_aninhados': int(vv.loc[vv['delta'] > 0, 'delta'].sum()),
           'secoes_externo_contava_mais': int((vv['delta'] < 0).sum()),
           'status_leitura': vv['status'].value_counts().to_dict(),
           'pacotes_lidos_2026': lidos, 'pacotes_lidos_2022': lidos22, 'falhas': len(falhas),
           'minutos': round((time.time() - t0) / 60, 1)}
    if len(am):
        an = am[am['tipo'].eq('logd')]
        for pl, g in an.groupby('pleito'):
            num[f'{pl}_logd_aninhados'] = int((g['profundidade'] > 0).sum())
            num[f'{pl}_logd_aninhados_com_hash_no_manifesto'] = int(g.loc[g['profundidade'] > 0, 'sha512_no_manifesto'].fillna(False).sum())
            num[f'{pl}_pacotes_externos_hash_ok'] = int(g[g['profundidade'] == 0]['pacote_externo_hash_ok'].fillna(False).sum())
            num[f'{pl}_pacotes_com_manifesto'] = int(g[g['profundidade'] == 0]['manifesto_no_disco'].sum())
            num[f'{pl}_votos_t2_em_aninhados_amostra'] = int(g.loc[g['profundidade'] > 0, 'votos_t2'].sum())
    completo = (time.time() - t0) / 60 <= limite_min and lidos + len([f for f in falhas if f['pleito'] == '2026-t2']) == len(sel)
    return {'status': 'feita' if completo else 'parcial', 'motivo': None if completo else 'tempo limite da amostra atingido',
            'numeros_chave': num, 'arquivos': arqs}


# ------------------------------------------------------------------------------------------------------ C2-12
def membros_inventario_local(pleito: str, uf: str) -> list[str] | None:
    """Nomes dos membros do zip oficial a partir do remote-inventory.json (11 UFs) ou, para ZZ/RN 2022 T1, de uma
    única listagem das pastas pequenas de logs/assinaturas mais os stems dos BUs em research/bu_urna."""
    if uf in UFS_11:
        p = raiz(pleito, uf)[0] / 'remote-inventory.json'
        if p.exists():
            inv = json.loads(p.read_text(encoding='utf-8'))
            return [m['name'] for m in inv[0]['members']]
        return None
    if (pleito, uf) in LISTAGEM_PERMITIDA:
        nomes = []
        for pasta in (R / 'estados' / uf / pleito / 'logs', ASSIN / pleito / uf):
            if pasta.exists():
                with os.scandir(pasta) as it:
                    nomes += [e.name for e in it if e.is_file() and not e.name.endswith('.json')]
        pbu = R / 'bu_urna' / pleito / uf
        if pbu.exists():
            c = con()
            nomes += c.execute("SELECT arquivo FROM read_parquet(?)", [str(pbu / 'part-*.parquet')]).df()['arquivo'].tolist()
            c.close()
        return nomes
    return None


def situacao_bweb(pleito: str, uf: str, mun: int, zona: int, sec: int) -> dict:
    """A seção no BU em CSV (BWEB) do pleito: existe? tipo de urna, urna efetivada, agregadas, aptos/comparecimento."""
    c = con()
    try:
        if pleito in ('2022-t1', '2022-t2'):
            p = BWEB / pleito / f'{uf}_PRESIDENTE.parquet'
            if not p.exists():
                return {'bweb': 'sem arquivo BWEB'}
            q = c.execute(f"""SELECT DS_TIPO_URNA, NR_URNA_EFETIVADA, DS_AGREGADAS, QT_APTOS, QT_COMPARECIMENTO, DT_ABERTURA,
                DT_ENCERRAMENTO FROM read_parquet('{p.as_posix()}') WHERE CAST(CD_MUNICIPIO AS INT)={mun} AND CAST(NR_ZONA AS INT)={zona}
                AND CAST(NR_SECAO AS INT)={sec} AND DS_CARGO_PERGUNTA='Presidente' LIMIT 1""").df()
        elif pleito == '2026-t1' and uf in UFS_11:
            p = raiz(pleito, uf)[0] / 'bu.parquet'
            q = c.execute(f"""SELECT DS_TIPO_URNA, NR_URNA_EFETIVADA, DS_SECOES_AGREGADAS AS DS_AGREGADAS, QT_APTOS, QT_COMPARECIMENTO,
                DT_ABERTURA, DT_ENCERRAMENTO FROM read_parquet('{p.as_posix()}') WHERE CAST(CD_MUNICIPIO AS INT)={mun}
                AND CAST(NR_ZONA AS INT)={zona} AND CAST(NR_SECAO AS INT)={sec} AND DS_CARGO_PERGUNTA='Presidente' LIMIT 1""").df()
        elif pleito.startswith('2024') and uf in UFS_11:
            p = raiz(pleito, uf)[1] / 'sections.parquet'
            if not p.exists():
                return {'bweb': 'sem sections.parquet'}
            q = c.execute(f"""SELECT NULL AS DS_TIPO_URNA, NULL AS NR_URNA_EFETIVADA, aggregation_raw AS DS_AGREGADAS, eligible AS QT_APTOS,
                attendance AS QT_COMPARECIMENTO, opening_bu AS DT_ABERTURA, closure_bu AS DT_ENCERRAMENTO
                FROM read_parquet('{p.as_posix()}') WHERE municipality={mun} AND zone={zona} AND section={sec} LIMIT 1""").df()
        else:
            return {'bweb': 'sem BU em CSV no disco para este pleito/UF'}
    finally:
        c.close()
    if q.empty:
        return {'bweb': 'seção ausente do BU em CSV'}
    r = q.iloc[0]
    return {'bweb': 'presente', 'bweb_tipo_urna': r['DS_TIPO_URNA'], 'bweb_urna_efetivada': r['NR_URNA_EFETIVADA'],
            'bweb_agregadas': r['DS_AGREGADAS'], 'bweb_aptos': r['QT_APTOS'], 'bweb_comparecimento': r['QT_COMPARECIMENTO'],
            'bweb_abertura': r['DT_ABERTURA'], 'bweb_encerramento': r['DT_ENCERRAMENTO']}


def situacao_ceft(pleito: str, uf: str, mun: int, zona: int, sec: int) -> dict:
    p = CEFT / pleito / f'{uf}.parquet'
    if not p.exists():
        return {'ceft': 'sem CEFT no disco'}
    c = con()
    cols = [f.name for f in pq.ParquetFile(p).schema_arrow]
    div = 'DS_DIVERGENCIA' if 'DS_DIVERGENCIA' in cols else 'TP_DIVERGENCIA'
    q = c.execute(f"""SELECT NR_URNA_ESPERADA, NR_URNA_EFETIVADA, {div} AS divergencia, DS_ORIGEM_VOTO
        FROM read_parquet('{p.as_posix()}') WHERE CAST(CD_MUNICIPIO AS INT)={mun} AND CAST(NR_ZONA AS INT)={zona}
        AND CAST(NR_SECAO AS INT)={sec}""").df()
    c.close()
    if q.empty:
        return {'ceft': 'seção ausente da CEFT'}
    r = q.iloc[0]
    return {'ceft': 'presente', 'ceft_urna_esperada': r['NR_URNA_ESPERADA'], 'ceft_urna_efetivada': r['NR_URNA_EFETIVADA'],
            'ceft_divergencia': r['divergencia'], 'ceft_origem_voto': r['DS_ORIGEM_VOTO'], 'ceft_linhas': len(q)}


def situacao_manifesto(pleito: str, uf: str, stem: str) -> dict:
    p = manifesto_local(pleito, uf, stem)
    if p is None:
        return {'manifesto_local': 'não está no disco'}
    try:
        bl = blocos_manifesto(p.read_bytes())
    except Exception as exc:
        return {'manifesto_local': f'ilegível: {exc!r}'[:120]}
    hw = bloco_hardware(bl)
    return {'manifesto_local': 'presente', 'manifesto_assinado_em': hw['when'] if hw else None,
            'manifesto_entradas': ','.join(sorted(hw['entries'])) if hw else None,
            'manifesto_tipos': ','.join(sorted({tipo_de(n) or '?' for n in hw['entries']})) if hw else None}


def situacao_integridade(pleito: str, stem: str) -> dict:
    c = con()
    q = c.execute("""SELECT log_local, log_local_igual_zip, manifest_ok, log_hash_ok, bu_hash_ok, rdv_hash_ok, cadeia_ok, cert_emissor,
        assinado_em, erro FROM read_parquet(?) WHERE eleicao=? AND urna=?""", [str(INTEGRIDADE), pleito, stem]).df()
    c.close()
    if q.empty:
        return {'integridade': 'urna não está na tabela de integridade'}
    r = q.iloc[0]
    return {'integridade': 'presente', **{f'integ_{k}': (None if pd.isna(v) else v) for k, v in r.items()}}


def enriquece_urna(pleito: str, uf: str, stem: str, faltante: str) -> dict:
    row = {'eleicao': pleito, 'uf': uf, 'stem': stem, 'faltante': faltante}
    try:
        _, mun, zona, sec = chave_do_stem(stem)
    except ValueError:
        row['status'] = 'NOT_COMPARABLE: stem sem chave de seção'
        return row
    row.update(municipality=mun, zone=zona, section=sec)
    row.update(situacao_bweb(pleito, uf, mun, zona, sec))
    row.update(situacao_ceft(pleito, uf, mun, zona, sec))
    row.update(situacao_manifesto(pleito, uf, stem))
    row.update(situacao_integridade(pleito, stem))
    return row


def c2_12() -> dict:
    """Assimetrias do inventário (zip com log/rdv/assinatura ≠ BU) e urnas sem meio de prova, uma a uma."""
    inv = pd.read_csv(INVENTARIO, sep=';', encoding='utf-8-sig')
    asym = assimetrias_inventario(inv)
    urnas, nao_test = [], []
    for r in asym.itertuples():
        if r.status != 'ok':
            nao_test.append({'eleicao': r.eleicao, 'uf': r.uf, 'motivo': f'zip com status {r.status} no inventário'})
            continue
        nomes = membros_inventario_local(r.eleicao, r.uf)
        if nomes is None:
            nao_test.append({'eleicao': r.eleicao, 'uf': r.uf, 'motivo': 'sem lista de membros do zip no disco '
                             '(remote-inventory.json só nas 11 UFs; listar o zip exigiria rede)'})
            continue
        falt = faltantes_por_tipo(nomes)
        listagem_local = r.uf not in UFS_11
        for tipo in ('bu', 'log', 'rdv', 'assinatura'):
            if listagem_local and tipo in ('rdv',):
                continue  # RDV não está no disco: só o zip (rede) diria quais urnas o têm
            for stem in falt[tipo]:
                row = enriquece_urna(r.eleicao, r.uf, stem, tipo)
                row['fonte_da_lista'] = 'listagem local (logs, assinaturas, bu_urna)' if listagem_local else 'remote-inventory.json'
                urnas.append(row)
        if listagem_local:
            nao_test.append({'eleicao': r.eleicao, 'uf': r.uf, 'motivo': 'RDV faltante não identificável sem o zip '
                             f'(inventário: rdv {int(r.rdv_arquivos)} × bu {int(r.bu_arquivos)}); stems locais: {len(falt["_stems"])}'})
    # 2026 T2 SP: log ausente identificado em C2-01 (ultimo_voto/cobertura), não pelo inventário de membros
    urnas.append({**enriquece_urna('2026-t2', 'SP', stem_2026t2('SP', 64777, 395, 298), 'log'),
                  'fonte_da_lista': 'C2-01 (cobertura.csv SP 103.655/103.656; pacote não está no disco)'})
    # urnas sem manifesto (falhas.csv) e casos sem prova completa
    fal = pd.read_csv(FALHAS, encoding='utf-8-sig', dtype=str)
    sem = []
    for r in fal.itertuples():
        sem.append({**enriquece_urna(r.eleicao, r.uf, r.urna, 'assinatura'), 'origem': 'falhas.csv', 'erro_integridade': r.erro,
                    'log_no_disco_integridade': r.log_local})
    cp = pd.read_csv(SEM_PROVA, encoding='utf-8-sig', dtype=str)  # vírgula, como falhas.csv
    for r in cp.itertuples():
        tipo = 'log' if 'não traz o log' in r.caso else 'rdv' if 'Sem RDV' in r.caso else \
            'assinatura_lista' if 'não listado' in r.caso else 'assinatura'
        if tipo == 'assinatura':
            continue  # já cobertos por falhas.csv
        for tok in re.findall(r'(o\d{5}-?[a-z]{0,2}\d{13}) \((\w{2})\)', r.exemplos):
            sem.append({**enriquece_urna(r.eleicao, tok[1], tok[0], tipo), 'origem': 'casos_sem_prova_completa.csv',
                        'erro_integridade': r.caso})
    arqs = [grava_csv(asym, 'C2-12_assimetrias_zips.csv'), grava_csv(pd.DataFrame(urnas), 'C2-12_urnas_faltantes.csv'),
            grava_csv(pd.DataFrame(sem), 'C2-12_sem_manifesto_ou_sem_prova.csv'),
            grava_csv(pd.DataFrame(nao_test), 'C2-12_nao_testaveis.csv')]
    u = pd.DataFrame(urnas)
    return {'status': 'parcial', 'motivo': 'zips fora das 11 UFs (exceto ZZ/RN 2022 T1) sem lista de membros local; RDV '
            'nunca baixado; explicação oficial das ausências depende de dado externo (TRE/TSE)',
            'numeros_chave': {'zips_assimetricos': int(len(asym)), 'urnas_faltantes_identificadas': int(len(u)),
                              'por_tipo': u['faltante'].value_counts().to_dict() if len(u) else {},
                              'por_pleito_uf': {f'{k[0]} {k[1]}': int(v) for k, v in u.groupby(['eleicao', 'uf']).size().items()}
                              if len(u) else {},
                              'bweb': u['bweb'].value_counts().to_dict() if len(u) else {},
                              'sem_manifesto_ou_prova': len(sem), 'nao_testaveis': len(nao_test)}, 'arquivos': arqs}


# ------------------------------------------------------------------------------------------------------ C2-14
def c2_14() -> dict:
    """Hora da assinatura do manifesto (relógio da urna) × emissão do BU × encerramento × recebimento no TSE."""
    c = con()
    res, exc, quar, por_uf = [], [], [], []
    for pleito in ['2022-t1', '2022-t2', '2024-t1', '2024-t2', '2026-t1', '2026-t2']:
        it = c.execute('SELECT uf, urna, assinado_em, cert_emissor FROM read_parquet(?) WHERE eleicao = ?',
                       [str(INTEGRIDADE), pleito]).df()
        if it.empty:
            continue
        ch = it['urna'].map(chave_do_stem)
        it[['municipality', 'zone', 'section']] = pd.DataFrame([x[1:] for x in ch], index=it.index)
        rl = c.execute("""SELECT uf, CAST(municipio AS BIGINT) municipality, CAST(zona AS BIGINT) zone, CAST(secao AS BIGINT) section,
            abertura, encerramento, emissao_bu, recebido_tse FROM read_parquet(?) WHERE eleicao = ?""", [str(RELOGIO), pleito]).df()
        if rl.empty:
            res.append({'pleito': pleito, 'urnas_assinadas': len(it), 'status': 'NOT_COMPARABLE: sem relógio do BU para o pleito'})
            continue
        d = it.merge(rl.drop_duplicates(['uf', 'municipality', 'zone', 'section']),
                     on=['uf', 'municipality', 'zone', 'section'], how='left')
        d['comparavel'] = np.where(d['assinado_em'].isna(), 'NOT_COMPARABLE: urna sem assinatura verificável',
                                   np.where(d['recebido_tse'].isna(), 'NOT_COMPARABLE: seção sem linha no relógio do BU',
                                            'comparavel'))
        if 'emissao_bu' in d and d['emissao_bu'].isna().all():
            d = d.drop(columns='emissao_bu')
        d = assinatura_vs_bu(d, DIA[pleito])
        for r in d[d['assinado'].isna() & d['assinado_em'].notna() | (d['assinado'].dt.year < 2020)].itertuples():
            quar.append({'pleito': pleito, 'uf': r.uf, 'urna': r.urna, 'assinado_em': r.assinado_em,
                         'reason': 'assinado_em ilegível ou anterior a 2020 (relógio da urna reiniciado)'})
        comp = d[d['comparavel'].eq('comparavel')]
        col = 'min_assin_apos_emissao' if 'min_assin_apos_emissao' in comp else 'min_assin_apos_encerramento'
        linha = {'pleito': pleito, 'urnas_assinadas': len(it), 'comparaveis': len(comp),
                 'nao_comparaveis': d['comparavel'].ne('comparavel').sum(), 'referencia': col.replace('min_assin_apos_', ''),
                 'mediana_min': comp[col].median(), 'p01_min': comp[col].quantile(0.01), 'p99_min': comp[col].quantile(0.99),
                 'max_min': comp[col].max(), 'min_min': comp[col].min(),
                 'assinou_antes_da_referencia': int((comp[col] < 0).sum()),
                 'assinou_antes_do_encerramento': int(comp['assinou_antes_da_encerramento'].sum()),
                 'assinou_depois_de_recebido': int(comp['assinou_depois_de_recebido'].sum()),
                 'assinou_fora_do_dia': int(comp['assinou_fora_do_dia'].sum()),
                 'assinou_antes_17h': int(comp['assinou_antes_17h'].sum()),
                 'mediana_min_recebido_apos_assin': comp['min_recebido_apos_assin'].median(),
                 'assin_mais_de_60min_apos_referencia': int((comp[col] > 60).sum())}
        res.append(linha)
        g = comp.groupby('uf').agg(comparaveis=(col, 'size'), mediana_min=(col, 'median'),
                                   p99_min=(col, lambda s: s.quantile(0.99)), max_min=(col, 'max'),
                                   antes_da_referencia=(col, lambda s: int((s < 0).sum())),
                                   depois_de_recebido=('assinou_depois_de_recebido', 'sum'),
                                   fora_do_dia=('assinou_fora_do_dia', 'sum')).reset_index()
        g.insert(0, 'pleito', pleito)
        por_uf.append(g)
        m = (comp[col] < 0) | comp['assinou_depois_de_recebido'] | comp['assinou_fora_do_dia'] | (comp[col] > 60) | \
            comp['assinou_antes_da_encerramento']
        cols = ['pleito', 'uf', 'urna', 'municipality', 'zone', 'section', 'cert_emissor', 'assinado_em', 'abertura',
                'encerramento', 'recebido_tse', 'min_assin_apos_encerramento', 'min_recebido_apos_assin',
                'assinou_antes_da_encerramento', 'assinou_depois_de_recebido', 'assinou_fora_do_dia', 'assinou_antes_17h']
        if 'emissao_bu' in comp:
            cols[cols.index('recebido_tse'):cols.index('recebido_tse')] = ['emissao_bu']
            cols.insert(cols.index('min_assin_apos_encerramento'), 'min_assin_apos_emissao')
        exc.append(comp.loc[m].assign(pleito=pleito)[cols])
        del d, comp, it, rl
    c.close()
    excecoes = pd.concat(exc, ignore_index=True)
    # cruzamento das exceções com a CEFT/contingência das 11 UFs (troca de urna, BU gerado por RED, identidade pelo nome)
    flags = []
    for eid, pleito in EID_PLEITO.items():
        p = INDICADORES / f'secoes_indicadores_{eid}.parquet'
        if p.exists() and pleito in set(excecoes['pleito']):
            f = pd.read_parquet(p, columns=['uf', 'municipality', 'zone', 'section', 'swap', 'red', 'identity_status', 'has_log'])
            f['pleito'] = pleito
            flags.append(f)
    if flags:
        f = pd.concat(flags, ignore_index=True)
        for col in ('municipality', 'zone', 'section'):
            f[col] = f[col].astype('int64')
        excecoes = excecoes.merge(f, on=['pleito', 'uf', 'municipality', 'zone', 'section'], how='left')
    excecoes['noronha'] = excecoes['uf'].eq('PE') & excecoes['municipality'].eq(30015)
    tard = excecoes[excecoes[[c for c in ('min_assin_apos_emissao', 'min_assin_apos_encerramento') if c in excecoes][0]] > 60]
    tard_res = tard.groupby('pleito').agg(urnas=('urna', 'size'), swap=('swap', lambda s: int(s.fillna(False).astype(bool).sum())),
                                          red=('red', lambda s: int(s.fillna(False).astype(bool).sum())),
                                          contingencia_nome=('identity_status', lambda s: int(s.eq('PARSED_FILENAME').sum())),
                                          sem_flags_ceft=('swap', lambda s: int(s.isna().sum()))).reset_index()
    arqs = [grava_csv(pd.DataFrame(res), 'C2-14_resumo_por_pleito.csv'), grava_csv(pd.concat(por_uf, ignore_index=True), 'C2-14_por_uf.csv'),
            grava_csv(excecoes, 'C2-14_excecoes.csv'), grava_csv(tard_res, 'C2-14_assinatura_tardia_x_ceft.csv')]
    q = quarentena('14', quar)
    if q:
        arqs.append(q)
    rs = pd.DataFrame(res)
    return {'status': 'feita', 'numeros_chave': {
        'comparaveis': int(rs['comparaveis'].fillna(0).sum()), 'nao_comparaveis': int(rs['nao_comparaveis'].fillna(0).sum()),
        'assinou_antes_da_referencia': int(rs['assinou_antes_da_referencia'].fillna(0).sum()),
        'assinou_antes_do_encerramento': int(rs['assinou_antes_do_encerramento'].fillna(0).sum()),
        'assinou_depois_de_recebido': int(rs['assinou_depois_de_recebido'].fillna(0).sum()),
        'assinou_fora_do_dia': int(rs['assinou_fora_do_dia'].fillna(0).sum()),
        'mediana_min_por_pleito': rs.set_index('pleito')['mediana_min'].round(2).to_dict(),
        'excecoes': int(len(excecoes)), 'quarentena': len(quar)}, 'arquivos': arqs}


# ------------------------------------------------------------------------------------------------------ C2-15
def c2_15() -> dict:
    """Erros 'O voto do eleitor NÃO foi registrado' (8044 e afins) no 2º turno de 2024 (scan de todos os logs das 9 UFs com
    2º turno) e erros do dia nos logs 'ambíguos' de todos os pleitos (research/contingencia), cruzados com log × BU."""
    scan = pd.read_csv(SCAN_8044, encoding='utf-8-sig', dtype=str)
    scan = scan[scan['member'].notna()].copy()
    scan['uf'] = scan['folder'].str.extract(r'municipais/([A-Z]{2})/')[0]
    scan['pleito'] = scan['folder'].str.extract(r'/(\d{4}-t\d)$')[0]
    scan['hora_erro'] = pd.to_datetime(scan['first'], format='%d/%m/%Y %H:%M:%S', errors='coerce')
    scan['hits'] = pd.to_numeric(scan['hits'], errors='coerce')
    partes = []
    for (uf, pleito), g in scan.groupby(['uf', 'pleito']):
        p = raiz(pleito, uf)[1] / 'sections.parquet'
        if not p.exists():
            partes.append(g.assign(comparavel='NOT_COMPARABLE: sem sections.parquet'))
            continue
        s = pd.read_parquet(p, columns=['member', 'municipality', 'zone', 'section', 'vote_events', 'attendance', 'opening_bu',
                                        'closure_bu', 'first_vote', 'last_vote', 'identity_source', 'manual_sequence_votes',
                                        'manual_bu'])
        m = g.merge(s, on='member', how='left')
        m['comparavel'] = np.where(m['attendance'].isna(), 'NOT_COMPARABLE: log sem seção casada no BU', 'comparavel')
        partes.append(m)
    sc = pd.concat(partes, ignore_index=True)
    base = sc['hora_erro'].dt.normalize()
    pv = base + pd.to_timedelta(sc['first_vote'].astype('string'), errors='coerce')
    uv = base + pd.to_timedelta(sc['last_vote'].astype('string'), errors='coerce')
    ab, en = parse_dt(sc['opening_bu']), parse_dt(sc['closure_bu'])
    sc['fase'] = [fase_do_erro(h, a, p, u, e) for h, a, p, u, e in zip(sc['hora_erro'], ab, pv, uv, en)]
    sc['log_igual_bu'] = np.where(sc['comparavel'].eq('comparavel'), sc['vote_events'] == sc['attendance'], None)
    sc['min_erro_antes_abertura'] = (ab - sc['hora_erro']).dt.total_seconds() / 60
    c = con()
    emis = c.execute("SELECT urna AS stem, cert_emissor FROM read_parquet(?) WHERE eleicao='2024-t2'", [str(INTEGRIDADE)]).df()
    c.close()
    sc['stem'] = sc['member'].map(stem_de)
    sc = sc.merge(emis.drop_duplicates('stem'), on='stem', how='left')
    res = sc.groupby(['pleito', 'uf', 'fase', 'codes'], dropna=False).agg(
        logs=('member', 'size'), log_igual_bu=('log_igual_bu', lambda s: int(pd.Series(s).fillna(False).astype(bool).sum())),
        hits=('hits', 'sum'), mediana_min_antes_abertura=('min_erro_antes_abertura', 'median')).reset_index()
    ger = sc.groupby(['cert_emissor'], dropna=False).size().rename('logs_com_erro').reset_index()
    tot = emis.groupby('cert_emissor').size().rename('urnas_2024t2_11ufs').reset_index()
    ger = ger.merge(tot, on='cert_emissor', how='outer')
    ger['por_mil'] = 1000 * ger['logs_com_erro'] / ger['urnas_2024t2_11ufs']
    # contexto (±8 linhas, mascarado) de uma amostra sorteada dos erros ocorridos durante a votação, por código
    ctx = []
    rng = np.random.default_rng(SEED)
    dur = sc[sc['fase'].eq('durante_votacao')]
    for code, g in dur.groupby('codes'):
        for r in g.iloc[rng.choice(len(g), min(4, len(g)), replace=False)].itertuples():
            p = raiz(r.pleito, r.uf)[0] / 'logs' / r.member
            if not p.exists():
                continue
            try:
                from auditabr.logs import read_log
                linhas = read_log(p).decode('utf-8-sig', 'replace').splitlines()
            except Exception as exc:
                ctx.append({'member': r.member, 'codes': code, 'erro': repr(exc)[:120]})
                continue
            idx = [i for i, ln in enumerate(linhas) if 'foi registrado' in ln and ln.startswith(r.first[:10])]
            if not idx:
                continue
            i0 = idx[0]
            for j in range(max(0, i0 - 8), min(len(linhas), i0 + 9)):
                f = linhas[j].split('\t')
                if len(f) > 4:
                    ctx.append({'member': r.member, 'uf': r.uf, 'codes': code, 'ordem': j - i0, 'hora': f[0][11:], 'nivel': f[1],
                                'app': f[3], 'mensagem': MASCARA.sub('#', f[4])[:160]})
    # erros do dia nos logs 'ambíguos' (research/contingencia/<raiz>.parquet) de todos os pleitos/UFs
    cont, msgs = [], []
    for p in sorted(CONTINGENCIA.glob('*.parquet')):
        if p.name.endswith('_messages.parquet'):
            continue
        try:
            d = pd.read_parquet(p, columns=['member', 'votes', 'errors_day', 'error_msgs'])
        except Exception as exc:
            cont.append({'raiz': p.stem, 'erro': repr(exc)[:120]})
            continue
        em = d['error_msgs'].astype('string').fillna('')
        cont.append({'raiz': p.stem, 'logs_ambiguos': len(d), 'com_erro_no_dia': int((d['errors_day'] > 0).sum()),
                     'erros_no_dia': int(d['errors_day'].fillna(0).sum()),
                     'so_desmontar_mr': int(em.str.fullmatch(r'(Problema ao desmontar a MR( \| )?)+').fillna(False).sum()),
                     'voto_nao_registrado': int(em.str.contains('registrado', case=False).fillna(False).sum()),
                     'outros_erros': int(((d['errors_day'] > 0) & ~em.str.fullmatch(r'(Problema ao desmontar a MR( \| )?)+').fillna(False)
                                          & ~em.str.contains('registrado', case=False).fillna(False)).sum())})
        for msg, n in em[em != ''].str.split(r' \| ').explode().value_counts().head(15).items():
            msgs.append({'raiz': p.stem, 'mensagem': msg[:120], 'logs': int(n)})
        del d
    # 2026 T2: catálogo de eventos das 14.769 seções marcadas (anomalias_2t) — 'NÃO foi registrado' e ERRO
    ls = pd.read_parquet(LOGS_SECOES, columns=['uf', 'municipality', 'zone', 'section', 'grupo', 'eventos', 'votos'])
    ev = ls['eventos'].astype('string').fillna('')
    ls['voto_nao_registrado'] = ev.str.contains('NÃO foi registrado|NAO foi registrado', case=False, regex=True)
    ls['tem_erro'] = ev.str.contains('"ERRO', regex=False)
    t2 = ls.groupby('grupo').agg(secoes=('eventos', 'size'), voto_nao_registrado=('voto_nao_registrado', 'sum'),
                                 com_nivel_erro=('tem_erro', 'sum')).reset_index()
    arqs = [grava_csv(sc.drop(columns=['msgs', 'folder']), 'C2-15_erros_8044_2024t2_por_log.csv'),
            grava_csv(res, 'C2-15_erros_8044_2024t2_resumo.csv'), grava_csv(ger, 'C2-15_erros_8044_por_geracao.csv'),
            grava_csv(pd.DataFrame(cont), 'C2-15_erros_do_dia_logs_ambiguos_por_raiz.csv'),
            grava_csv(pd.DataFrame(msgs), 'C2-15_mensagens_de_erro_por_raiz.csv'),
            grava_csv(t2, 'C2-15_2026t2_secoes_marcadas.csv'),
            grava_csv(pd.DataFrame(ctx), 'C2-15_contexto_erros_durante_votacao_amostra.csv')]
    fases = sc['fase'].value_counts().to_dict()
    return {'status': 'parcial', 'motivo': 'scan completo só no 2º turno de 2024 (9 UFs); nos demais pleitos só os logs '
            '"ambíguos" de research/contingencia e as 14.769 seções marcadas de 2026 T2; extensão nacional depende da passada de logs',
            'numeros_chave': {'logs_com_erro_2024t2': int(len(sc)), 'fases': fases,
                              'log_igual_bu': int(pd.Series(sc['log_igual_bu']).fillna(False).astype(bool).sum()),
                              'comparaveis': int(sc['comparavel'].eq('comparavel').sum()),
                              'codigos': sc['codes'].value_counts().to_dict(),
                              '2026t2_marcadas_voto_nao_registrado': int(ls['voto_nao_registrado'].sum()),
                              'logs_ambiguos_voto_nao_registrado': int(sum(x['voto_nao_registrado'] for x in cont))},
            'arquivos': arqs}


# -------------------------------------------------------------------------------------------------------- main
CHECAGENS = {'C2-01': c2_01, 'C2-07': c2_07, 'C2-09': c2_09, 'C2-12': c2_12, 'C2-14': c2_14, 'C2-15': c2_15, 'C2-08': c2_08}
NAO_FEITAS = {
    'C2-02': 'depende da passada pesada de logs (releitura de 2026 T1/T2 com contagem por classe de habilitação e por cargo)',
    'C2-03': 'depende da passada pesada: reler ~40 k logs divergentes/ambíguos das 11 UFs com o leitor aninhado',
    'C2-04': 'depende da passada pesada de BUs/logs (hash de ~1 M urnas) e de RDV por rede',
    'C2-05': 'exige RDV por rede (HTTP Range) ou a passada de BUs',
    'C2-06': 'exige RDV por rede (ordem dos votos não está em disco)',
    'C2-10': 'depende da passada pesada de BUs binários (bu_raw de 2,5 M urnas)',
    'C2-11': 'depende de C2-02 e C2-03',
    'C2-13': 'depende da passada: reler 1.340 logs do piloto BA 2022 T2',
}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('checagens', nargs='*', help='ids (C2-01 …); vazio = todas')
    ap.add_argument('--resumo', default=str(OUT / 'C2_resumo.json'))
    a = ap.parse_args(argv)
    ids = a.checagens or list(CHECAGENS)
    OUT.mkdir(parents=True, exist_ok=True)
    p_res = Path(a.resumo)
    resumo = json.loads(p_res.read_text(encoding='utf-8')) if p_res.exists() else {'camada': 'C2', 'checagens': {}}
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
    for cx, motivo in NAO_FEITAS.items():
        resumo['checagens'].setdefault(cx, {'status': 'nao_feita', 'motivo': motivo})
    resumo['protocolo'] = 'relatorios/verificacoes/varredura_forense/PROTOCOLO.md v1.0'
    resumo['parser_version'] = PARSER_VERSION
    resumo['gerado_em'] = agora()
    p_res.write_text(json.dumps(resumo, indent=1, ensure_ascii=False, default=str), encoding='utf-8')
    print('resumo em', rel(p_res))


if __name__ == '__main__':
    sys.exit(main())
