"""Varredura forense — passada única sobre os BUs binários de urna (protocolo v1.0: C2-10 invariantes estruturais,
C6-04 identificação de urna e carga, C5-05 todos os cargos, C4-06 canais do 2º turno de 2026).

Entrada: research/bu_urna/<pleito>/<UF>/part-*.parquet (stem, arquivo, bu_raw = bytes do .bu / -bu.dat), um part por vez.
Cada BU é decodificado por um parser BER próprio que segue a especificação ASN.1 do TSE em
research/integridade/tse_doc/formato/spec/bu.asn1 (versão de 2022: EntidadeEnvelopeGenerico{cabecalho, fase, identificacao,
tipoEnvelope, conteudo} e EntidadeBoletimUrna{cabecalho, fase, urna{tipoUrna, versaoVotacao, correspondenciaResultado
{identificacao, carga{numeroInternoUrna, numeroSerieFC, dataHoraCarga, codigoCarga}}, tipoArquivo, numeroSerieFV,
motivoUtilizacaoSA}, identificacaoSecao, dataHoraEmissao, dadosSecaoSA, [1] qtdEleitoresLibCodigo, [2] qtdEleitoresCompBiometrico,
[3] resultadosVotacaoPorEleicao, [4] historicoCorrespondencias, [5] historicoVotoImpresso, chaveAssinaturaVotosVotavel}) e
tolera as variantes observadas nos BUs de 2024 e 2026, que essa versão da especificação não documenta; os campos sem nome na
spec recebem nome neutro:
  - Carga ganha uma SEQUENCE de três GeneralString entre numeroSerieFC e dataHoraCarga -> carga_extra (JSON; o primeiro
    elemento parece identificar o modelo/lote da urna, p.ex. 'ZAC001STD29', 'RACWCSC01');
  - depois de dadosSecaoSA vem um INTEGER (comparecimento_bu) e [1] passa a ser uma SEQUENCE de três inteiros -> hab_0,
    hab_1, hab_2 (mesma convenção de research/padroes_2t/hab_2026_*; nenhum dos três é nomeado aqui);
  - ResultadoVotacaoPorEleicao traz dois inteiros a mais depois de qtdEleitoresAptos -> aptos_int2, aptos_int3 (observado
    aptos = aptos_int2 + aptos_int3) e dois OCTET STRING finais (64 e 132 bytes) -> e<id>_trailer;
  - cada TotalVotosVotavel ganha um INTEGER sequencial antes da assinatura;
  - o último campo passa a ser uma SEQUENCE de GeneralString com os códigos de carga (o da urna por último; nas urnas
    reservaSecao vêm também os das urnas anteriores) -> trailer_cargas, no lugar de chaveAssinaturaVotosVotavel.
Qualquer campo fora disso vai para a coluna extras (e inv_sem_extras = False): nada é descartado em silêncio.

Saída: research/varredura_forense/bu/<pleito>/<UF>/part-NNNNN.parquet (um por part de entrada, com recibo .json ao lado;
retomável: parts completos com recibo íntegro são pulados). Uma linha por BU: identificação pelo stem E pelo conteúdo
(divergências marcadas), urna/carga, horários, habilitação, por eleição e cargo os totais (nominal/branco/nulo/legenda), a
lista {número: votos} de todos os votáveis (JSON por cargo), nº de cargos, e os invariantes (inv_*: True/False/None=não
aplicável, com a diferença ao lado). Linhas com erro de decodificação ficam com a coluna erro preenchida.

Subcomandos:
  passada <pleito> [--ufs AC,AL] [--limite N] [--workers 1]   decodifica os parts (ProcessPool só se --workers > 1)
  canais 2026-t2 [--ufs BA] [--limite N]     BU do sistema de resultados (research/segundo_turno_2026/bu/<UF>.parquet) × BU
                                             dos dados abertos, byte a byte (sha256) pelo stem -> canais_2026t2.csv e
                                             canais_2026t2_diferentes.csv (campos decodificados que mudaram)
  consolida <pleito>                         secoes_<pleito>.parquet (sem as colunas JSON de votáveis), quarentena dos
                                             invariantes falhos (research/varredura_forense/quarentena/rows-C2-bu_<pleito>_
                                             <checagem>.json + quarentena_C2.csv), cargos esperados por UF (conjunto mais
                                             frequente), resumo_<pleito>.csv por UF
  confere <pleito> [--ufs AC]                presidente/prefeito por seção × referência já existente (secoes_t1_t2 2026,
                                             base_2022, BWEB 2024 onde houver); seção sem par = NOT_COMPARABLE + motivo

Chaves: seção = (uf, municipality, zone, section); urna = stem. Nulos ficam nulos, com motivo. Descritivo: sinalização não é
acusação e nada aqui indica irregularidade por si só.
"""
import argparse
import ctypes
import gc
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from auditabr.utils import read_json, write_json  # noqa: E402
from auditabr.utils import sha256 as sha256_arquivo  # noqa: E402

PARSER_VERSION = 'varredura_forense_bu/1.0'
R = ROOT / 'research'
ENTRADA = R / 'bu_urna'
SAIDA = R / 'varredura_forense' / 'bu'
QUARENTENA = R / 'varredura_forense' / 'quarentena'
SISTEMA_2026T2 = R / 'segundo_turno_2026' / 'bu'
SECOES_2026 = ROOT / 'relatorios' / 'verificacoes' / 'virada_1t_2t_2026' / 'secoes_t1_t2.parquet'
BASE_2022 = R / 'padroes_2t' / 'base_2022.parquet'
CSV = dict(index=False, sep=';', decimal=',', encoding='utf-8-sig')
CHAVE = ['uf', 'municipality', 'zone', 'section']

# enumerações da especificação bu.asn1 (2022)
FASE = {1: 'simulado', 2: 'oficial', 3: 'treinamento'}
TIPO_URNA = {1: 'secao', 3: 'contingencia', 4: 'reservaSecao', 6: 'reservaEncerrandoSecao'}
TIPO_ARQUIVO = {1: 'votacaoUE', 2: 'votacaoRED', 3: 'saMistaMRParcialCedula', 4: 'saMistaBUImpressoCedula',
                5: 'saManual', 6: 'saEletronica'}
TIPO_CARGO = {1: 'majoritario', 2: 'proporcional', 3: 'consulta'}
TIPO_VOTO = {1: 'nominal', 2: 'branco', 3: 'nulo', 4: 'legenda', 5: 'cargoSemCandidato'}
CARGO_BWEB = {'PRESIDENTE': 1, 'GOVERNADOR': 3, 'PREFEITO': 11}

# BER: classes e tags universais usadas
UNIVERSAL, CONTEXTO = 0, 2
INT, OCTET, ENUM, SEQ, GS = 2, 4, 10, 16, 27
DATA_RE = re.compile(r'^\d{8}T\d{6}$')
STEM_RE = re.compile(r'^([so])(\d{5})(?:-|([a-z]{2}))(\d{5})(\d{4})(\d{4})$')
SUFIXOS_JSON = ('_votaveis', '_legenda_partidos', '_fora_lista', '_repetidos', '_partido_incoerente', '_outros_tipos',
                '_trailer', '_lista')

MOTIVOS = {
    'inv_id_env_bu': 'identificação da seção no envelope difere da identificação no conteúdo do BU',
    'inv_id_stem_bu': 'município/zona/seção do nome do arquivo (stem) diferem do conteúdo do BU',
    'inv_corresp_secao': 'município/zona/seção da correspondência (urna/carga) diferem da seção do BU',
    'inv_aptos_comp': 'comparecimento de algum cargo maior que os aptos da eleição (faltas calculadas negativas)',
    'inv_hab_soma_comp': 'soma dos contadores de habilitação (hab_0+hab_1+hab_2) difere do comparecimento do BU',
    'inv_comp_bu_cargo': 'comparecimento do BU difere do maior comparecimento por cargo',
    'inv_cargos_soma': 'nominal+branco+nulo+legenda(+outros) difere do comparecimento do cargo',
    'inv_lista': 'número de votável nominal fora da lista oficial do cargo/UF',
    'inv_aptos_int': 'aptos difere da soma dos dois inteiros seguintes da eleição (relação observada em 2024/2026)',
    'inv_trailer_carga': 'último código de carga do bloco final difere do código de carga da urna (2024/2026)',
    'inv_cronologia': 'ordem carga <= abertura <= encerramento <= emissão <= geração do BU não respeitada',
    'inv_cargos_unicos': 'cargo repetido no mesmo BU',
    'inv_numeros_unicos': 'número de votável repetido no mesmo cargo',
    'inv_partido_numero': 'partido do votável difere dos dois primeiros dígitos do número',
    'inv_fase_oficial': 'fase diferente de oficial no envelope ou no BU',
    'inv_tipo_envelope': 'tipo de envelope diferente de boletim de urna',
    'inv_sem_extras': 'campos não reconhecidos pelo parser (estrutura fora do esperado)',
    'inv_cargos_esperados': 'conjunto de cargos difere do mais frequente na UF (cargos faltando ou a mais)',
    'erro': 'erro de decodificação do BU',
}
# colunas cujo valor original acompanha a linha em quarentena (padrões de regex por invariante)
VALORES_INV = {
    'inv_id_env_bu': [r'^env_(municipio|zona|local|secao)$', r'^(municipality|zone|voting_place|section)$'],
    'inv_id_stem_bu': [r'^stem_(municipio|zona|secao)$', r'^(municipality|zone|section)$'],
    'inv_corresp_secao': [r'^corresp_', r'^(municipality|zone|voting_place|section)$', r'^tipo_urna(_ds)?$'],
    'inv_aptos_comp': [r'^e\d+_aptos$', r'_comparecimento$', r'^aptos_comp_dif_min$'],
    'inv_hab_soma_comp': [r'^hab_', r'^comparecimento_bu$', r'^hab_soma$', r'^hab_comp_dif$'],
    'inv_comp_bu_cargo': [r'^comparecimento_bu$', r'_comparecimento$', r'^comp_bu_cargo_dif$'],
    'inv_cargos_soma': [r'_comparecimento$', r'_(nominal|branco|nulo|legenda|outros)$', r'^cargos_soma_dif$'],
    'inv_lista': [r'^numeros_fora_lista$', r'^lista_status$'],
    'inv_aptos_int': [r'^e\d+_aptos(_int2|_int3)?$'],
    'inv_trailer_carga': [r'^trailer_cargas$', r'^codigo_carga$'],
    'inv_cronologia': [r'^data_hora_', r'^bu_data_geracao$', r'^cronologia_dif$'],
    'inv_cargos_unicos': [r'^cargos$', r'^cargos_duplicados_lista$'],
    'inv_numeros_unicos': [r'_repetidos$'],
    'inv_partido_numero': [r'_partido_incoerente$'],
    'inv_fase_oficial': [r'^(env|bu)_fase$'],
    'inv_tipo_envelope': [r'^env_tipo_envelope$'],
    'inv_sem_extras': [r'^extras$'],
    'inv_cargos_esperados': [r'^cargos_set$', r'^cargos_(esperados|faltando|extras)$'],
    'erro': [r'^erro$', r'^bu_bytes$'],
}
INVARIANTES = [k for k in MOTIVOS if k != 'erro']


# ------------------------------------------------------------------ BER
def ber_tlv(b, i):
    """Cabeçalho TLV em b[i:] -> (classe, construído, tag, início do valor, comprimento)."""
    t = b[i]
    i += 1
    cls, cons, tag = t >> 6, bool(t & 0x20), t & 0x1f
    if tag == 0x1f:
        tag = 0
        while True:
            x = b[i]
            i += 1
            tag = (tag << 7) | (x & 0x7f)
            if not x & 0x80:
                break
    ln = b[i]
    i += 1
    if ln == 0x80:
        raise ValueError(f'comprimento indefinido em {i - 1}')
    if ln & 0x80:
        k = ln & 0x7f
        ln = int.from_bytes(b[i:i + k], 'big')
        i += k
    return cls, cons, tag, i, ln


def ber_tree(b, i=0, end=None):
    """Árvore BER: lista de (classe, tag, filhos | bytes). OCTET STRING não é aberto automaticamente."""
    end = len(b) if end is None else end
    out = []
    while i < end:
        cls, cons, tag, s, ln = ber_tlv(b, i)
        if s + ln > end:
            raise ValueError(f'TLV em {i} ultrapassa o pai ({s + ln} > {end})')
        out.append((cls, tag, ber_tree(b, s, s + ln) if cons else b[s:s + ln]))
        i = s + ln
    return out


def _e(n, cls, tag, construido=None):
    return n[0] == cls and n[1] == tag and (construido is None or isinstance(n[2], list) == construido)


def _int(n):
    return int.from_bytes(n[2], 'big', signed=True)


def _str(n):
    return n[2].decode('latin1')


def _hex(n):
    return n[2].hex()


def _sig(n):
    """Assinatura curta de um nó não reconhecido (classe+tag, se construído, tamanho e primeiros bytes)."""
    c = {0: 'U', 1: 'A', 2: 'C', 3: 'P'}[n[0]]
    if isinstance(n[2], list):
        return f'{c}{n[1]}[{len(n[2])}]'
    return f'{c}{n[1]}:{len(n[2])}:{n[2][:12].hex()}'


# ------------------------------------------------------------------ decodificação tipada (bu.asn1)
def _cabecalho(n, pref):
    """CabecalhoEntidade{dataGeracao GeneralString, idEleitoral CHOICE [1] processo | [2] pleito | [3] eleição}."""
    k = n[2]
    gs = [c for c in k if _e(c, UNIVERSAL, GS, False)]
    ch = [c for c in k if c[0] == CONTEXTO and not isinstance(c[2], list)]
    return {pref + 'data_geracao': _str(gs[0]) if gs else None,
            pref + 'id_tipo': ({1: 'processo', 2: 'pleito', 3: 'eleicao'}.get(ch[0][1], f'c{ch[0][1]}') if ch else None),
            pref + 'id': _int(ch[0]) if ch else None}


def _identificacao(n):
    """IdentificacaoUrna CHOICE: [0] seção {municipioZona{municipio, zona}, local, secao} | [1] contingência {municipioZona}."""
    k = n[2]
    mz = k[0][2] if k and isinstance(k[0][2], list) else []
    out = {'tipo': 'secao' if n[1] == 0 else ('contingencia' if n[1] == 1 else f'c{n[1]}'),
           'municipio': _int(mz[0]) if len(mz) > 0 else None, 'zona': _int(mz[1]) if len(mz) > 1 else None,
           'local': None, 'secao': None}
    ints = [c for c in k[1:] if _e(c, UNIVERSAL, INT, False)]
    if n[1] == 0 and len(ints) >= 2:
        out['local'], out['secao'] = _int(ints[0]), _int(ints[1])
    return out


def _carga(n):
    """Carga{numeroInternoUrna, numeroSerieFC OCTET(4), [SEQ de GeneralString: 2024+], dataHoraCarga, codigoCarga}."""
    out = {'numero_interno_urna': None, 'numero_serie_fc': None, 'carga_extra': None, 'data_hora_carga': None,
           'codigo_carga': None}
    extras, gs = [], []
    for c in n[2]:
        if _e(c, UNIVERSAL, INT, False) and out['numero_interno_urna'] is None:
            out['numero_interno_urna'] = _int(c)
        elif _e(c, UNIVERSAL, OCTET, False) and out['numero_serie_fc'] is None:
            out['numero_serie_fc'] = _hex(c)
        elif _e(c, UNIVERSAL, SEQ, True) and out['carga_extra'] is None:
            out['carga_extra'] = [_str(x) if _e(x, UNIVERSAL, GS, False) else _sig(x) for x in c[2]]
        elif _e(c, UNIVERSAL, GS, False):
            gs.append(_str(c))
        else:
            extras.append('carga:' + _sig(c))
    for s in gs:
        if DATA_RE.match(s) and out['data_hora_carga'] is None:
            out['data_hora_carga'] = s
        elif out['codigo_carga'] is None:
            out['codigo_carga'] = s
        else:
            extras.append('carga:GS:' + s[:30])
    return out, extras


def _urna(n):
    """Urna{tipoUrna, versaoVotacao, correspondenciaResultado{identificacao, carga}, tipoArquivo, numeroSerieFV,
    motivoUtilizacaoSA CHOICE [0..3]{tipoApuracao, motivo} OPTIONAL}."""
    k = n[2]
    out, extras = {}, []
    enums = [c for c in k if _e(c, UNIVERSAL, ENUM, False)]
    gs = [c for c in k if _e(c, UNIVERSAL, GS, False)]
    seqs = [c for c in k if _e(c, UNIVERSAL, SEQ, True)]
    octs = [c for c in k if _e(c, UNIVERSAL, OCTET, False)]
    sa = [c for c in k if c[0] == CONTEXTO and isinstance(c[2], list)]
    out['tipo_urna'] = _int(enums[0]) if enums else None
    out['tipo_arquivo'] = _int(enums[1]) if len(enums) > 1 else None
    out['versao_votacao'] = _str(gs[0]) if gs else None
    ident = {'tipo': None, 'municipio': None, 'zona': None, 'local': None, 'secao': None}
    carga = {'numero_interno_urna': None, 'numero_serie_fc': None, 'carga_extra': None, 'data_hora_carga': None,
             'codigo_carga': None}
    if seqs:
        corr = seqs[0][2]
        idn = next((c for c in corr if c[0] == CONTEXTO and isinstance(c[2], list)), None)
        if idn:
            ident = _identificacao(idn)
        cg = next((c for c in corr if _e(c, UNIVERSAL, SEQ, True)), None)
        if cg:
            carga, ex = _carga(cg)
            extras += ex
    out.update({'corresp_' + a: b for a, b in ident.items()})
    out.update(carga)
    out['numero_serie_fv'] = _hex(octs[0]) if octs else None
    out['sa_motivo_choice'] = out['sa_tipo_apuracao'] = out['sa_motivo'] = None
    if sa:
        ints = [_int(c) for c in sa[0][2] if _e(c, UNIVERSAL, ENUM, False) or _e(c, UNIVERSAL, INT, False)]
        out['sa_motivo_choice'] = sa[0][1]
        out['sa_tipo_apuracao'] = ints[0] if ints else None
        out['sa_motivo'] = ints[1] if len(ints) > 1 else None
    if len(enums) > 2 or len(gs) > 1 or len(seqs) > 1 or len(octs) > 1 or len(sa) > 1:
        extras.append('urna:campos_a_mais')
    for c in k:
        if not (_e(c, UNIVERSAL, ENUM, False) or _e(c, UNIVERSAL, GS, False) or _e(c, UNIVERSAL, SEQ, True)
                or _e(c, UNIVERSAL, OCTET, False) or (c[0] == CONTEXTO and isinstance(c[2], list))):
            extras.append('urna:' + _sig(c))
    return out, extras


def _votavel(vt):
    """TotalVotosVotavel{[1] tipoVoto, [2] quantidade, [3] {partido, codigo} OPTIONAL, [INTEGER 2024+], assinatura}."""
    tipo = qtd = partido = numero = None
    assin = []
    for c in vt[2]:
        if c[0] == CONTEXTO and c[1] == 1 and not isinstance(c[2], list):
            tipo = _int(c)
        elif c[0] == CONTEXTO and c[1] == 2 and not isinstance(c[2], list):
            qtd = _int(c)
        elif c[0] == CONTEXTO and c[1] == 3 and isinstance(c[2], list):
            ii = [_int(x) for x in c[2] if _e(x, UNIVERSAL, INT, False)]
            partido, numero = (ii + [None, None])[:2]
        elif _e(c, UNIVERSAL, OCTET, False):
            assin.append(len(c[2]))
    return tipo, (qtd or 0), partido, numero, assin


def _cargo(tc, tipo_cargo, comp):
    """TotalVotosCargo{codigoCargo CHOICE [1] constitucional | [2] livre, ordemImpressao, votosVotaveis SEQ OF}."""
    k = tc[2]
    cod = next((c for c in k if c[0] == CONTEXTO and not isinstance(c[2], list)), None)
    out = {'cargo': _int(cod) if cod else None, 'cargo_livre': bool(cod is not None and cod[1] == 2),
           'tipo_cargo': tipo_cargo, 'comparecimento': comp,
           'ordem': next((_int(c) for c in k if _e(c, UNIVERSAL, INT, False)), None),
           'nominal': 0, 'branco': 0, 'nulo': 0, 'legenda': 0, 'outros': 0, 'outros_tipos': {}, 'votaveis': {},
           'legenda_partidos': {}, 'n_votaveis': 0, 'numeros_repetidos': [], 'partido_incoerente': [],
           'assinatura_len': set()}
    lst = next((c for c in k if _e(c, UNIVERSAL, SEQ, True)), None)
    for vt in (lst[2] if lst else []):
        tipo, qtd, partido, numero, assin = _votavel(vt)
        out['n_votaveis'] += 1
        out['assinatura_len'].update(assin)
        if tipo == 1:
            out['nominal'] += qtd
            if numero in out['votaveis']:
                out['numeros_repetidos'].append(numero)
            out['votaveis'][numero] = out['votaveis'].get(numero, 0) + qtd
            if (tipo_cargo != 3 and numero is not None and partido is not None
                    and str(numero)[:2] != str(partido).zfill(2)):
                out['partido_incoerente'].append([numero, partido])
        elif tipo == 2:
            out['branco'] += qtd
        elif tipo == 3:
            out['nulo'] += qtd
        elif tipo == 4:
            out['legenda'] += qtd
            key = partido if partido is not None else numero
            out['legenda_partidos'][key] = out['legenda_partidos'].get(key, 0) + qtd
        else:
            out['outros'] += qtd
            out['outros_tipos'][tipo] = out['outros_tipos'].get(tipo, 0) + qtd
    out['soma'] = out['nominal'] + out['branco'] + out['nulo'] + out['legenda'] + out['outros']
    out['dif_soma'] = out['soma'] - comp if comp is not None else None
    return out


def _eleicao(n):
    """ResultadoVotacaoPorEleicao{idEleicao, qtdEleitoresAptos, [INT, INT: 2024+], resultadosVotacao SEQ OF
    ResultadoVotacao{tipoCargo, qtdComparecimento, totaisVotosCargo SEQ OF}, [OCTET, OCTET: 2024+]}."""
    k = n[2]
    ints = [_int(c) for c in k if _e(c, UNIVERSAL, INT, False)]
    seqs = [c for c in k if _e(c, UNIVERSAL, SEQ, True)]
    octs = [len(c[2]) for c in k if _e(c, UNIVERSAL, OCTET, False)]
    e = {'id': ints[0] if ints else None, 'aptos': ints[1] if len(ints) > 1 else None,
         'aptos_int2': ints[2] if len(ints) > 2 else None, 'aptos_int3': ints[3] if len(ints) > 3 else None,
         'ints_extra': ints[4:], 'trailer_octets': octs, 'cargos': []}
    for rv in (seqs[0][2] if seqs else []):
        kk = rv[2]
        tipo_cargo = next((_int(c) for c in kk if _e(c, UNIVERSAL, ENUM, False)), None)
        comp = next((_int(c) for c in kk if _e(c, UNIVERSAL, INT, False)), None)
        tot = next((c for c in kk if _e(c, UNIVERSAL, SEQ, True)), None)
        for tc in (tot[2] if tot else []):
            e['cargos'].append(_cargo(tc, tipo_cargo, comp))
    return e


def _parece_eleicoes(n):
    return bool(n[2]) and all(isinstance(c[2], list) and c[2] and _e(c[2][0], UNIVERSAL, INT, False)
                              and any(_e(x, UNIVERSAL, SEQ, True) for x in c[2]) for c in n[2])


def decodifica_bu(raw):
    """Decodifica um BU (bytes BER) -> dict com os campos do envelope e do boletim, 'eleicoes' (lista aninhada) e
    'extras' (campos não reconhecidos). Levanta ValueError se a estrutura não for a de um BU."""
    t = ber_tree(raw)
    if len(t) != 1 or not _e(t[0], UNIVERSAL, SEQ, True):
        raise ValueError('envelope: esperada uma única SEQUENCE')
    env = t[0][2]
    rec, extras = {}, []
    seqs = [c for c in env if _e(c, UNIVERSAL, SEQ, True)]
    enums = [c for c in env if _e(c, UNIVERSAL, ENUM, False)]
    rec.update(_cabecalho(seqs[0], 'env_') if seqs else {'env_data_geracao': None, 'env_id_tipo': None, 'env_id': None})
    rec['env_fase'] = _int(enums[0]) if enums else None
    rec['env_tipo_envelope'] = _int(enums[1]) if len(enums) > 1 else None
    idn = next((c for c in env if c[0] == CONTEXTO and isinstance(c[2], list)), None)
    ident = _identificacao(idn) if idn else {'tipo': None, 'municipio': None, 'zona': None, 'local': None, 'secao': None}
    rec.update({'env_' + a: b for a, b in ident.items()})
    rec['env_seq_extra'] = len(seqs) > 1   # Urna ou Seguranca no envelope: não esperado no BU
    cont = [c for c in env if _e(c, UNIVERSAL, OCTET, False)]
    if not cont:
        raise ValueError('envelope sem conteudo (OCTET STRING)')
    bt = ber_tree(cont[-1][2])
    if len(bt) != 1 or not _e(bt[0], UNIVERSAL, SEQ, True):
        raise ValueError('conteudo: esperada uma única SEQUENCE (EntidadeBoletimUrna)')
    bu = bt[0][2]
    rec['bu_n_campos'] = len(bu)
    base = {'bu_data_geracao': None, 'bu_id_tipo': None, 'bu_id': None, 'bu_fase': None, 'data_hora_emissao': None,
            'dados_tipo': None, 'data_hora_abertura': None, 'data_hora_encerramento': None,
            'data_hora_desligamento_voto_impresso': None, 'sa_junta': None, 'sa_turma': None, 'sa_urna_origem': None,
            'comparecimento_bu': None, 'hab_lista': None, 'hab_lib_codigo': None, 'hab_comp_biometrico': None,
            'eleicoes_tag': None, 'historico_correspondencias': None, 'historico_voto_impresso': None,
            'chave_assinatura': None, 'trailer_cargas': None}
    rec.update(base)
    urna, _ = _urna((UNIVERSAL, SEQ, []))
    rec.update(urna)
    rec.update({'municipality': None, 'zone': None, 'voting_place': None, 'section': None})
    eleicoes, seq_i = [], 0
    for c in bu:
        if _e(c, UNIVERSAL, SEQ, True):
            if seq_i == 0:
                rec.update(_cabecalho(c, 'bu_'))
            elif seq_i == 1:
                u, ex = _urna(c)
                rec.update(u)
                extras += ex
            elif seq_i == 2:
                i = _identificacao((CONTEXTO, 0, c[2]))
                rec.update({'municipality': i['municipio'], 'zone': i['zona'], 'voting_place': i['local'],
                            'section': i['secao']})
            elif _parece_eleicoes(c) and not eleicoes:
                eleicoes = [_eleicao(x) for x in c[2]]
                rec['eleicoes_tag'] = 'U16'
            elif c[2] and all(_e(x, UNIVERSAL, GS, False) for x in c[2]) and rec['trailer_cargas'] is None:
                rec['trailer_cargas'] = [_str(x) for x in c[2]]
            else:
                extras.append(_sig(c))
            seq_i += 1
        elif _e(c, UNIVERSAL, ENUM, False) and rec['bu_fase'] is None:
            rec['bu_fase'] = _int(c)
        elif _e(c, UNIVERSAL, GS, False) and rec['data_hora_emissao'] is None:
            rec['data_hora_emissao'] = _str(c)
        elif c[0] == CONTEXTO and c[1] == 0 and isinstance(c[2], list) and rec['dados_tipo'] is None:
            gs = [_str(x) for x in c[2] if _e(x, UNIVERSAL, GS, False)]
            rec['dados_tipo'] = 'secao'
            rec['data_hora_abertura'] = gs[0] if gs else None
            rec['data_hora_encerramento'] = gs[1] if len(gs) > 1 else None
            rec['data_hora_desligamento_voto_impresso'] = gs[2] if len(gs) > 2 else None
        elif c[0] == CONTEXTO and c[1] == 1 and isinstance(c[2], list) and rec['dados_tipo'] is None:
            ii = [_int(x) for x in c[2] if _e(x, UNIVERSAL, INT, False)]
            rec['dados_tipo'] = 'sa'
            rec['sa_junta'], rec['sa_turma'] = (ii + [None, None])[:2]
            rec['sa_urna_origem'] = ii[2] if len(ii) > 2 else None
        elif c[0] == CONTEXTO and c[1] == 1 and isinstance(c[2], list) and rec['hab_lista'] is None:
            rec['hab_lista'] = [_int(x) for x in c[2] if _e(x, UNIVERSAL, INT, False)]
        elif c[0] == CONTEXTO and c[1] == 1 and not isinstance(c[2], list) and rec['hab_lib_codigo'] is None:
            rec['hab_lib_codigo'] = _int(c)
        elif c[0] == CONTEXTO and c[1] == 2 and not isinstance(c[2], list) and rec['hab_comp_biometrico'] is None:
            rec['hab_comp_biometrico'] = _int(c)
        elif c[0] == CONTEXTO and c[1] == 3 and isinstance(c[2], list) and not eleicoes:
            eleicoes = [_eleicao(x) for x in c[2]]
            rec['eleicoes_tag'] = 'C3'
        elif c[0] == CONTEXTO and c[1] == 4 and isinstance(c[2], list) and rec['historico_correspondencias'] is None:
            hist = []
            for h in c[2]:
                idn = next((x for x in h[2] if x[0] == CONTEXTO and isinstance(x[2], list)), None)
                cg = next((x for x in h[2] if _e(x, UNIVERSAL, SEQ, True)), None)
                item = {'identificacao': _identificacao(idn) if idn else None}
                if cg:
                    carga, ex = _carga(cg)
                    item.update(carga)
                    extras += ['historico:' + e for e in ex]
                hist.append(item)
            rec['historico_correspondencias'] = hist
        elif c[0] == CONTEXTO and c[1] == 5 and isinstance(c[2], list) and rec['historico_voto_impresso'] is None:
            rec['historico_voto_impresso'] = [[(_int(x) if _e(x, UNIVERSAL, INT, False) else _str(x)) for x in h[2]]
                                              for h in c[2]]
        elif _e(c, UNIVERSAL, INT, False) and rec['comparecimento_bu'] is None:
            rec['comparecimento_bu'] = _int(c)
        elif _e(c, UNIVERSAL, OCTET, False) and rec['chave_assinatura'] is None:
            rec['chave_assinatura'] = _hex(c)
        else:
            extras.append(_sig(c))
    rec['eleicoes'] = eleicoes
    rec['extras'] = extras
    return rec


# ------------------------------------------------------------------ linha achatada + invariantes
def _js(o):
    return json.dumps(o, ensure_ascii=False, separators=(',', ':'), default=str)


def analisa_stem(stem):
    m = STEM_RE.match(stem or '')
    if not m:
        return {'stem_fase': None, 'stem_pleito': None, 'stem_uf': None, 'stem_municipio': None, 'stem_zona': None,
                'stem_secao': None}
    return {'stem_fase': m.group(1), 'stem_pleito': int(m.group(2)), 'stem_uf': (m.group(3) or '').upper() or None,
            'stem_municipio': int(m.group(4)), 'stem_zona': int(m.group(5)), 'stem_secao': int(m.group(6))}


def chave_cargo(e, c):
    return f'e{e["id"]}_' + ('q' if c['cargo_livre'] else 'c') + str(c['cargo'])


def achata(dec, stem, uf, arquivo, listas=None, raw=None):
    """dict de decodifica_bu -> uma linha plana (identificação, urna, horários, habilitação, por eleição/cargo, invariantes)."""
    listas = listas or {}
    r = {'stem': stem, 'uf': uf, 'arquivo': arquivo, 'bu_bytes': len(raw) if raw is not None else None,
         'bu_sha256': hashlib.sha256(raw).hexdigest() if raw is not None else None, 'erro': None}
    r.update(analisa_stem(stem))
    for k, v in dec.items():
        if k in ('eleicoes', 'extras', 'hab_lista'):
            continue
        r[k] = _js(v) if isinstance(v, (list, dict)) else v
    r['tipo_urna_ds'] = TIPO_URNA.get(dec.get('tipo_urna'))
    r['tipo_arquivo_ds'] = TIPO_ARQUIVO.get(dec.get('tipo_arquivo'))
    r['env_fase_ds'] = FASE.get(dec.get('env_fase'))
    r['modelo_carga'] = (dec.get('carga_extra') or [None])[0]
    hab = dec.get('hab_lista') or []
    for i, v in enumerate(hab):
        r[f'hab_{i}'] = v
    r['hab_soma'] = sum(hab) if hab else None
    r['n_correspondencias'] = len(dec.get('historico_correspondencias') or [])
    r['n_trailer_cargas'] = len(dec.get('trailer_cargas') or [])
    r['extras'] = _js(dec['extras']) if dec.get('extras') else None
    r['n_extras'] = len(dec.get('extras') or [])

    # por eleição e cargo
    chaves, comps, difs, fora, lista_st, repetidos, incoerentes = [], [], {}, {}, [], {}, {}
    aptos_dif, aptos_int_ok = [], []
    for e in dec.get('eleicoes', []):
        eid = e['id']
        r[f'e{eid}_aptos'] = e['aptos']
        r[f'e{eid}_aptos_int2'] = e['aptos_int2']
        r[f'e{eid}_aptos_int3'] = e['aptos_int3']
        r[f'e{eid}_n_cargos'] = len(e['cargos'])
        r[f'e{eid}_trailer'] = _js(e['trailer_octets'] + (['ints:'] + e['ints_extra'] if e['ints_extra'] else [])) \
            if (e['trailer_octets'] or e['ints_extra']) else None
        if e['aptos_int2'] is not None and e['aptos_int3'] is not None and e['aptos'] is not None:
            aptos_int_ok.append(e['aptos'] == e['aptos_int2'] + e['aptos_int3'])
        comps_e = [c['comparecimento'] for c in e['cargos'] if c['comparecimento'] is not None]
        r[f'e{eid}_faltas_calc'] = (e['aptos'] - max(comps_e)) if comps_e and e['aptos'] is not None else None
        for c in e['cargos']:
            k = chave_cargo(e, c)
            chaves.append(k)
            r[f'{k}_tipo_cargo'] = c['tipo_cargo']
            r[f'{k}_ordem'] = c['ordem']
            r[f'{k}_comparecimento'] = c['comparecimento']
            for f in ('nominal', 'branco', 'nulo', 'legenda', 'outros', 'n_votaveis', 'soma', 'dif_soma'):
                r[f'{k}_{f}'] = c[f]
            r[f'{k}_votaveis'] = _js(c['votaveis'])
            r[f'{k}_legenda_partidos'] = _js(c['legenda_partidos']) if c['legenda_partidos'] else None
            r[f'{k}_outros_tipos'] = _js(c['outros_tipos']) if c['outros_tipos'] else None
            r[f'{k}_repetidos'] = _js(c['numeros_repetidos']) if c['numeros_repetidos'] else None
            r[f'{k}_partido_incoerente'] = _js(c['partido_incoerente']) if c['partido_incoerente'] else None
            r[f'{k}_assinatura_len'] = ','.join(str(x) for x in sorted(c['assinatura_len'])) or None
            if c['comparecimento'] is not None:
                comps.append(c['comparecimento'])
                if e['aptos'] is not None:
                    aptos_dif.append(e['aptos'] - c['comparecimento'])
            if c['dif_soma'] not in (0, None):
                difs[k] = c['dif_soma']
            if c['numeros_repetidos']:
                repetidos[k] = c['numeros_repetidos']
            if c['partido_incoerente']:
                incoerentes[k] = c['partido_incoerente']
            lista = listas.get(c['cargo']) if not c['cargo_livre'] else None
            if lista is None:
                r[f'{k}_lista'] = 'sem lista'
                lista_st.append('sem lista')
            else:
                fl = sorted(n for n in c['votaveis'] if n not in lista)
                r[f'{k}_lista'] = 'ok' if not fl else 'fora'
                r[f'{k}_fora_lista'] = _js(fl) if fl else None
                lista_st.append('ok' if not fl else 'fora')
                if fl:
                    fora[k] = fl
    r['n_eleicoes'] = len(dec.get('eleicoes', []))
    r['n_cargos'] = len(chaves)
    r['cargos'] = ','.join(chaves)
    r['cargos_set'] = ','.join(sorted(set(chaves)))
    dup = sorted(k for k, n in Counter(chaves).items() if n > 1)
    r['cargos_duplicados'] = bool(dup)
    r['cargos_duplicados_lista'] = ','.join(dup) or None
    r['comp_cargos_min'] = min(comps) if comps else None
    r['comp_cargos_max'] = max(comps) if comps else None
    r['comp_cargos_iguais'] = (len(set(comps)) == 1) if comps else None

    # invariantes (True / False / None = não aplicável)
    ids_env = (dec.get('env_municipio'), dec.get('env_zona'), dec.get('env_local'), dec.get('env_secao'))
    ids_bu = (dec.get('municipality'), dec.get('zone'), dec.get('voting_place'), dec.get('section'))
    r['inv_id_env_bu'] = (ids_env == ids_bu) if dec.get('env_tipo') == 'secao' else None
    r['id_env_bu_dif'] = None if r['inv_id_env_bu'] in (True, None) else f'{ids_env} != {ids_bu}'
    st = (r['stem_municipio'], r['stem_zona'], r['stem_secao'])
    r['inv_id_stem_bu'] = (st == (ids_bu[0], ids_bu[1], ids_bu[3])) if r['stem_municipio'] is not None else None
    r['id_stem_bu_dif'] = None if r['inv_id_stem_bu'] in (True, None) else f'{st} != {(ids_bu[0], ids_bu[1], ids_bu[3])}'
    ct = dec.get('corresp_tipo')
    if ct == 'secao':   # o campo local da correspondência vale 1 em todos os pleitos observados: não entra na comparação
        r['inv_corresp_secao'] = (dec.get('corresp_municipio'), dec.get('corresp_zona'),
                                  dec.get('corresp_secao')) == (ids_bu[0], ids_bu[1], ids_bu[3])
    elif ct == 'contingencia':
        r['inv_corresp_secao'] = (dec.get('corresp_municipio'), dec.get('corresp_zona')) == ids_bu[:2]
    else:
        r['inv_corresp_secao'] = None
    r['inv_aptos_comp'] = all(d >= 0 for d in aptos_dif) if aptos_dif else None
    r['aptos_comp_dif_min'] = min(aptos_dif) if aptos_dif else None
    cb = dec.get('comparecimento_bu')
    r['inv_hab_soma_comp'] = (r['hab_soma'] == cb) if (hab and cb is not None) else None
    r['hab_comp_dif'] = (r['hab_soma'] - cb) if (hab and cb is not None) else None
    r['inv_comp_bu_cargo'] = (cb == max(comps)) if (cb is not None and comps) else None
    r['comp_bu_cargo_dif'] = (cb - max(comps)) if (cb is not None and comps) else None
    r['inv_cargos_soma'] = (not difs) if chaves else None
    r['cargos_soma_dif'] = _js(difs) if difs else None
    com_lista = [s for s in lista_st if s != 'sem lista']
    r['inv_lista'] = (all(s == 'ok' for s in com_lista)) if com_lista else None
    r['lista_status'] = ('sem lista' if not com_lista else ('parcial' if len(com_lista) < len(lista_st) else 'completa')
                         + (': fora' if fora else ': ok')) if chaves else None
    r['numeros_fora_lista'] = _js(fora) if fora else None
    r['inv_aptos_int'] = all(aptos_int_ok) if aptos_int_ok else None
    tr = dec.get('trailer_cargas')
    r['inv_trailer_carga'] = (tr[-1] == dec.get('codigo_carga')) if tr else None
    datas = [dec.get('data_hora_carga'), dec.get('data_hora_abertura'), dec.get('data_hora_encerramento'),
             dec.get('data_hora_emissao'), dec.get('bu_data_geracao')]
    nomes = ['carga', 'abertura', 'encerramento', 'emissao', 'geracao']
    if all(d and DATA_RE.match(d) for d in datas):
        quebras = [f'{nomes[i]}>{nomes[i + 1]}' for i in range(4) if datas[i] > datas[i + 1]]
        r['inv_cronologia'] = not quebras
        r['cronologia_dif'] = ','.join(quebras) or None
    else:
        r['inv_cronologia'], r['cronologia_dif'] = None, None
    r['inv_cargos_unicos'] = not dup
    r['inv_numeros_unicos'] = (not repetidos) if chaves else None
    r['inv_partido_numero'] = (not incoerentes) if chaves else None
    r['inv_fase_oficial'] = (dec.get('env_fase') == 2 and dec.get('bu_fase') == 2)
    r['inv_tipo_envelope'] = (dec.get('env_tipo_envelope') == 1)
    r['inv_sem_extras'] = not dec.get('extras')
    return r


def linha_bu(stem, arquivo, raw, uf, listas=None):
    """Uma linha por BU; exceções viram a coluna erro (com a identificação pelo stem preservada)."""
    try:
        return achata(decodifica_bu(raw), stem, uf, arquivo, listas, raw)
    except Exception as exc:  # noqa: BLE001 - qualquer falha de estrutura vira linha de erro
        r = {'stem': stem, 'uf': uf, 'arquivo': arquivo, 'bu_bytes': len(raw) if raw is not None else None,
             'bu_sha256': hashlib.sha256(raw).hexdigest() if raw else None, 'erro': f'{type(exc).__name__}: {exc}'[:200]}
        r.update(analisa_stem(stem))
        return r


COLUNAS_BASE = {
    'stem': 'string', 'uf': 'string', 'arquivo': 'string', 'bu_bytes': 'Int64', 'bu_sha256': 'string', 'erro': 'string',
    'stem_fase': 'string', 'stem_pleito': 'Int64', 'stem_uf': 'string', 'stem_municipio': 'Int64', 'stem_zona': 'Int64',
    'stem_secao': 'Int64', 'env_data_geracao': 'string', 'env_id_tipo': 'string', 'env_id': 'Int64', 'env_fase': 'Int64',
    'env_fase_ds': 'string', 'env_tipo_envelope': 'Int64', 'env_tipo': 'string', 'env_municipio': 'Int64',
    'env_zona': 'Int64', 'env_local': 'Int64', 'env_secao': 'Int64', 'env_seq_extra': 'boolean', 'bu_n_campos': 'Int64',
    'bu_data_geracao': 'string', 'bu_id_tipo': 'string', 'bu_id': 'Int64', 'bu_fase': 'Int64',
    'municipality': 'Int64', 'zone': 'Int64', 'voting_place': 'Int64', 'section': 'Int64',
    'tipo_urna': 'Int64', 'tipo_urna_ds': 'string', 'versao_votacao': 'string', 'tipo_arquivo': 'Int64',
    'tipo_arquivo_ds': 'string', 'corresp_tipo': 'string', 'corresp_municipio': 'Int64', 'corresp_zona': 'Int64',
    'corresp_local': 'Int64', 'corresp_secao': 'Int64', 'numero_interno_urna': 'Int64', 'numero_serie_fc': 'string',
    'carga_extra': 'string', 'modelo_carga': 'string', 'data_hora_carga': 'string', 'codigo_carga': 'string',
    'numero_serie_fv': 'string', 'sa_motivo_choice': 'Int64', 'sa_tipo_apuracao': 'Int64', 'sa_motivo': 'Int64',
    'data_hora_emissao': 'string', 'dados_tipo': 'string', 'data_hora_abertura': 'string',
    'data_hora_encerramento': 'string', 'data_hora_desligamento_voto_impresso': 'string', 'sa_junta': 'Int64',
    'sa_turma': 'Int64', 'sa_urna_origem': 'Int64', 'comparecimento_bu': 'Int64', 'hab_0': 'Int64', 'hab_1': 'Int64',
    'hab_2': 'Int64', 'hab_soma': 'Int64', 'hab_lib_codigo': 'Int64', 'hab_comp_biometrico': 'Int64',
    'eleicoes_tag': 'string', 'historico_correspondencias': 'string', 'n_correspondencias': 'Int64',
    'historico_voto_impresso': 'string', 'chave_assinatura': 'string', 'trailer_cargas': 'string',
    'n_trailer_cargas': 'Int64', 'extras': 'string', 'n_extras': 'Int64', 'n_eleicoes': 'Int64', 'n_cargos': 'Int64',
    'cargos': 'string', 'cargos_set': 'string', 'cargos_duplicados': 'boolean', 'cargos_duplicados_lista': 'string',
    'comp_cargos_min': 'Int64', 'comp_cargos_max': 'Int64', 'comp_cargos_iguais': 'boolean',
    'inv_id_env_bu': 'boolean', 'id_env_bu_dif': 'string', 'inv_id_stem_bu': 'boolean', 'id_stem_bu_dif': 'string',
    'inv_corresp_secao': 'boolean', 'inv_aptos_comp': 'boolean', 'aptos_comp_dif_min': 'Int64',
    'inv_hab_soma_comp': 'boolean', 'hab_comp_dif': 'Int64', 'inv_comp_bu_cargo': 'boolean', 'comp_bu_cargo_dif': 'Int64',
    'inv_cargos_soma': 'boolean', 'cargos_soma_dif': 'string', 'inv_lista': 'boolean', 'lista_status': 'string',
    'numeros_fora_lista': 'string', 'inv_aptos_int': 'boolean', 'inv_trailer_carga': 'boolean',
    'inv_cronologia': 'boolean', 'cronologia_dif': 'string', 'inv_cargos_unicos': 'boolean',
    'inv_numeros_unicos': 'boolean', 'inv_partido_numero': 'boolean', 'inv_fase_oficial': 'boolean',
    'inv_tipo_envelope': 'boolean', 'inv_sem_extras': 'boolean',
}


def tabela(linhas):
    """Lista de linhas -> DataFrame tipado (colunas base sempre presentes; por eleição/cargo inferidas pelo nome)."""
    df = pd.DataFrame(linhas)
    for c in COLUNAS_BASE:
        if c not in df:
            df[c] = None
    dyn = [c for c in df.columns if c not in COLUNAS_BASE]
    df = df[list(COLUNAS_BASE) + sorted(dyn)]
    for c in df.columns:
        if c in COLUNAS_BASE:
            df[c] = df[c].astype(COLUNAS_BASE[c])
        elif c.endswith(SUFIXOS_JSON) or c.endswith('_assinatura_len'):
            df[c] = df[c].astype('string')
        else:
            df[c] = df[c].astype('Int64')
    return df


# ------------------------------------------------------------------ listas oficiais de votáveis
def listas_oficiais(pleito, uf):
    """{código do cargo: conjunto de números nominais} a partir do BWEB research/bu/<pleito>/<UF>_<CARGO>.parquet e, para o
    presidente de 2026, dos nomes das colunas t<n>_v* de secoes_t1_t2.parquet. Cargo ausente = sem lista."""
    out = {}
    pasta = R / 'bu' / pleito
    for nome in CARGO_BWEB:
        p = pasta / f'{uf}_{nome}.parquet'
        if not p.exists():
            continue
        t = pq.read_table(p, columns=['CD_CARGO_PERGUNTA', 'CD_TIPO_VOTAVEL', 'NR_VOTAVEL'])
        t = t.group_by(['CD_CARGO_PERGUNTA', 'CD_TIPO_VOTAVEL', 'NR_VOTAVEL']).aggregate([]).to_pandas()
        t = t[t.CD_TIPO_VOTAVEL.astype(str).str.strip() == '1']
        for cp, g in t.groupby(t.CD_CARGO_PERGUNTA.astype(int)):
            out.setdefault(int(cp), set()).update(int(x) for x in g.NR_VOTAVEL)
        del t
    if pleito.startswith('2026') and SECOES_2026.exists():
        tag = 't1' if pleito.endswith('t1') else 't2'
        nums = {int(c[len(tag) + 2:]) for c in pq.read_schema(SECOES_2026).names if re.fullmatch(tag + r'_v\d+', c)}
        if nums:
            out.setdefault(1, set()).update(nums)
    return out


# ------------------------------------------------------------------ passada
def prioridade_baixa():
    if hasattr(ctypes, 'windll'):
        try:  # BELOW_NORMAL_PRIORITY_CLASS
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
        except Exception:  # noqa: BLE001
            pass


class _PMC(ctypes.Structure):
    _fields_ = [('cb', ctypes.c_ulong), ('PageFaultCount', ctypes.c_ulong), ('PeakWorkingSetSize', ctypes.c_size_t),
                ('WorkingSetSize', ctypes.c_size_t), ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
                ('QuotaPagedPoolUsage', ctypes.c_size_t), ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                ('QuotaNonPagedPoolUsage', ctypes.c_size_t), ('PagefileUsage', ctypes.c_size_t),
                ('PeakPagefileUsage', ctypes.c_size_t)]


def pico_memoria_mb():
    """Pico de working set deste processo em MB (Windows); None fora do Windows."""
    if not hasattr(ctypes, 'windll'):
        return None
    try:
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = ctypes.c_void_p
        f = k.K32GetProcessMemoryInfo
        f.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PMC), ctypes.c_ulong]
        f.restype = ctypes.c_int
        m = _PMC()
        m.cb = ctypes.sizeof(_PMC)
        if not f(k.GetCurrentProcess(), ctypes.byref(m), m.cb):
            return None
        return round(m.PeakWorkingSetSize / 2 ** 20, 1)
    except Exception:  # noqa: BLE001
        return None


def _scandir(pasta, dirs=False, prefixo='', sufixo=''):
    """Lista UMA pasta (sem recursão)."""
    with os.scandir(pasta) as it:
        return sorted(e.name for e in it if (e.is_dir() if dirs else e.is_file())
                      and e.name.startswith(prefixo) and e.name.endswith(sufixo))


def tarefas_pleito(pleito, ufs=None, base=ENTRADA):
    raiz = base / pleito
    if not raiz.exists():
        raise SystemExit(f'sem pasta {raiz}')
    disco = _scandir(raiz, dirs=True)
    ufs = [u for u in (ufs or disco) if u in disco]
    return [(pleito, uf, raiz / uf / p) for uf in ufs for p in _scandir(raiz / uf, prefixo='part-', sufixo='.parquet')]


def ja_feito(dest):
    rec = dest.with_suffix('.json')
    if not dest.exists() or not rec.exists():
        return False
    try:
        j = read_json(rec)
    except Exception:  # noqa: BLE001
        return False
    return (j.get('parser_version') == PARSER_VERSION and j.get('completo') is True
            and j.get('sha256') == sha256_arquivo(dest))


def processa_parte(args):
    pleito, uf, part, limite, listas = args
    dest = SAIDA / pleito / uf / part.name
    t0 = time.time()
    tb = pq.read_table(part, columns=['stem', 'arquivo', 'bu_raw'])
    n_in = tb.num_rows
    linhas = []
    for i, (stem, arq, raw) in enumerate(zip(tb.column('stem').to_pylist(), tb.column('arquivo').to_pylist(),
                                             tb.column('bu_raw').to_pylist())):
        if limite and i >= limite:
            break
        linhas.append(linha_bu(stem, arq, raw, uf, listas))
    del tb
    df = tabela(linhas)
    del linhas
    dest.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(dest, index=False)
    seg = time.time() - t0
    recibo = {'at': datetime.now(timezone.utc).isoformat(), 'inputs': {str(part): sha256_arquivo(part)},
              'sha256': sha256_arquivo(dest), 'rows': int(len(df)), 'bytes': dest.stat().st_size,
              'parser_version': PARSER_VERSION, 'rows_entrada': int(n_in), 'completo': bool(len(df) == n_in),
              'limite': limite, 'erros': int(df.erro.notna().sum()), 'segundos': round(seg, 2),
              'ms_por_bu': round(1000 * seg / max(1, len(df)), 3), 'pleito': pleito, 'uf': uf,
              'pico_memoria_mb': pico_memoria_mb()}
    write_json(dest.with_suffix('.json'), recibo)
    del df
    gc.collect()
    return recibo


def passada(pleito, ufs=None, limite=None, workers=1):
    tarefas = tarefas_pleito(pleito, ufs)
    listas = {uf: listas_oficiais(pleito, uf) for uf in sorted({t[1] for t in tarefas})}
    pend = [(p, uf, part, limite, listas[uf]) for p, uf, part in tarefas if not ja_feito(SAIDA / p / uf / part.name)]
    print(f'{pleito}: {len(tarefas)} parts, {len(tarefas) - len(pend)} já feitos, {len(pend)} a processar; '
          f'listas (cargos com lista oficial): ' + ', '.join(f'{u}:{sorted(ls)}' for u, ls in listas.items()), flush=True)
    tot_bus = tot_seg = 0
    t0 = time.time()
    if workers > 1:
        ex = ProcessPoolExecutor(workers, initializer=prioridade_baixa)
        it = ex.map(processa_parte, pend)
    else:
        prioridade_baixa()
        it = map(processa_parte, pend)
    for k, rec in enumerate(it, 1):
        tot_bus += rec['rows']
        tot_seg += rec['segundos']
        print(f"{k}/{len(pend)} {rec['uf']} {Path(list(rec['inputs'])[0]).name}: {rec['rows']} BUs, "
              f"{rec['erros']} erros, {rec['segundos']} s ({rec['ms_por_bu']} ms/BU)", flush=True)
    if workers > 1:
        ex.shutdown()
    rel = time.time() - t0
    print(f'{pleito}: {tot_bus} BUs em {rel:.1f} s de relógio ({tot_seg:.1f} s de CPU); '
          f'{1000 * tot_seg / max(1, tot_bus):.2f} ms/BU; pico de memória do processo principal '
          f'{pico_memoria_mb()} MB', flush=True)
    return tot_bus, tot_seg, rel


# ------------------------------------------------------------------ consolidação, quarentena e resumo
def _colunas_valores(colunas, inv):
    pats = [re.compile(p) for p in VALORES_INV.get(inv, [])]
    return [c for c in colunas if any(p.search(c) for p in pats)]


def linhas_quarentena(df, inv, pleito, colunas_valores):
    """Linhas de df em que inv == False (ou erro preenchido) -> registros de quarentena com os valores originais em texto."""
    mask = df['erro'].notna() if inv == 'erro' else (df[inv].astype('boolean') == False).fillna(False)  # noqa: E712
    out = []
    for d in df[mask.astype(bool)].to_dict('records'):
        vals = {c: (None if pd.isna(d[c]) else str(d[c])) for c in colunas_valores if c in d}
        out.append({'pleito': pleito, 'uf': d.get('uf'), 'stem': d.get('stem'),
                    'municipality': None if pd.isna(d.get('municipality')) else int(d['municipality']),
                    'zone': None if pd.isna(d.get('zone')) else int(d['zone']),
                    'section': None if pd.isna(d.get('section')) else int(d['section']),
                    'checagem': inv, 'reason': MOTIVOS[inv], 'valores': vals})
    return out


def cargos_esperados(df):
    """Conjunto de cargos mais frequente por UF (linhas sem erro) e, por linha, o que falta/sobra em relação a ele."""
    ok = df[df['erro'].isna() & df['cargos_set'].notna()]
    moda = ok.groupby('uf')['cargos_set'].agg(lambda s: s.value_counts().idxmax()).to_dict()
    esp = df['uf'].map(moda)

    def dif(a, b):
        sa = set(a.split(',')) - {''} if isinstance(a, str) else set()
        sb = set(b.split(',')) - {''} if isinstance(b, str) else set()
        return ','.join(sorted(sa - sb)) or None

    out = pd.DataFrame({'uf': df['uf'], 'stem': df['stem'], 'cargos_esperados': esp})
    out['cargos_faltando'] = [dif(e, c) for e, c in zip(esp, df['cargos_set'])]
    out['cargos_extras'] = [dif(c, e) for e, c in zip(esp, df['cargos_set'])]
    out['inv_cargos_esperados'] = [(None if (pd.isna(e) or pd.isna(c)) else bool(pd.isna(f) and pd.isna(x)))
                                   for e, c, f, x in zip(esp, df['cargos_set'], out.cargos_faltando, out.cargos_extras)]
    out['inv_cargos_esperados'] = out['inv_cargos_esperados'].astype('boolean')
    return out


def consolida(pleito):
    import duckdb
    parts = [pth for _, _, pth in tarefas_pleito(pleito, base=SAIDA)]
    if not parts:
        raise SystemExit(f'nenhum part em {SAIDA / pleito}')
    cols = {}
    for p in parts:
        for f in pq.read_schema(p):
            cols.setdefault(f.name, str(f.type))
    excl = {c for c in cols if c.endswith(('_votaveis', '_legenda_partidos', '_outros_tipos'))
            or c in ('historico_correspondencias', 'historico_voto_impresso')}
    keep = [c for c in cols if c not in excl]
    dest = SAIDA / f'secoes_{pleito}.parquet'
    tmp = SAIDA / f'secoes_{pleito}.tmp.parquet'
    files = [str(p).replace('\\', '/') for p in parts]
    con = duckdb.connect()
    con.execute("SET memory_limit='400MB'")
    con.execute('SET threads=1')
    # tabelas largas (centenas de colunas): sem preservar a ordem e com derramamento em disco, o COPY cabe nos 400 MB
    con.execute('SET preserve_insertion_order=false')
    spill = SAIDA / '_duckdb_tmp'
    spill.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET temp_directory='{spill.as_posix()}'")
    sel = ', '.join(f'"{c}"' for c in keep)
    con.execute(f"COPY (SELECT {sel} FROM read_parquet({files!r}, union_by_name=true)) TO '{tmp.as_posix()}' "
                "(FORMAT PARQUET)")
    ids = con.execute(f"SELECT uf, stem, cargos_set, erro FROM read_parquet('{tmp.as_posix()}')").df()
    esp = cargos_esperados(ids)
    dup = esp.duplicated(['uf', 'stem'], keep='first')
    n_dup = int(dup.sum())
    esp = esp[~dup].copy()
    esp['inv_cargos_esperados'] = esp['inv_cargos_esperados'].astype(object).where(esp['inv_cargos_esperados'].notna(), None)
    # junção em lotes com pyarrow (a junção larga no DuckDB estourava os 400 MB nas tabelas de 1º turno)
    esp = esp.set_index(['uf', 'stem'])[['cargos_esperados', 'cargos_faltando', 'cargos_extras', 'inv_cargos_esperados']]
    pf = pq.ParquetFile(tmp)
    schema = pf.schema_arrow
    for c in ['cargos_esperados', 'cargos_faltando', 'cargos_extras']:
        schema = schema.append(pa.field(c, pa.string()))
    schema = schema.append(pa.field('inv_cargos_esperados', pa.bool_()))
    writer = pq.ParquetWriter(dest, schema)
    try:
        for batch in pf.iter_batches(batch_size=20_000):
            extra = esp.reindex(pd.MultiIndex.from_arrays([batch.column('uf').to_pandas(), batch.column('stem').to_pandas()]))
            cols = batch.columns + [pa.array(extra[c].astype(object).where(extra[c].notna(), None).tolist(), type=pa.string())
                                    for c in ['cargos_esperados', 'cargos_faltando', 'cargos_extras']]
            inv = extra['inv_cargos_esperados'].astype(object).where(extra['inv_cargos_esperados'].notna(), None).tolist()
            cols.append(pa.array([None if v is None else bool(v) for v in inv], type=pa.bool_()))
            writer.write_table(pa.Table.from_arrays(cols, schema=schema))
            del extra, cols, inv
    finally:
        writer.close()
        pf.close()
    del ids, esp
    gc.collect()
    tmp.unlink()
    inputs = {}
    for p in parts:
        rj = p.with_suffix('.json')
        inputs[str(p)] = read_json(rj).get('sha256') if rj.exists() else sha256_arquivo(p)
    n_rows = pq.read_metadata(dest).num_rows
    write_json(dest.with_suffix('.json'), {'at': datetime.now(timezone.utc).isoformat(), 'inputs': inputs,
                                           'sha256': sha256_arquivo(dest), 'rows': int(n_rows),
                                           'bytes': dest.stat().st_size, 'parser_version': PARSER_VERSION,
                                           'stems_duplicados': n_dup, 'colunas_excluidas': sorted(excl)})
    print(f'{dest}: {n_rows} linhas, {len(keep) + 4} colunas, {n_dup} stems duplicados', flush=True)

    # quarentena e resumo (leitura projetada)
    colunas = pq.read_schema(dest).names
    invs = [c for c in colunas if c.startswith('inv_')]
    leves = ['uf', 'stem', 'municipality', 'zone', 'section', 'erro', 'tipo_urna', 'tipo_arquivo', 'versao_votacao',
             'modelo_carga', 'n_cargos', 'cargos_set', 'cargos_esperados', 'lista_status', 'comp_cargos_iguais',
             'dados_tipo', 'n_correspondencias', 'n_extras', 'env_fase']
    df = pq.read_table(dest, columns=[c for c in leves + invs if c in colunas]).to_pandas()
    QUARENTENA.mkdir(parents=True, exist_ok=True)
    quar = []
    for inv in invs + ['erro']:
        cv = _colunas_valores(colunas, inv)
        mask = df['erro'].notna() if inv == 'erro' else (df[inv].astype('boolean') == False).fillna(False)  # noqa: E712
        if not mask.any():
            continue
        cols_q = list(dict.fromkeys(['uf', 'stem', 'municipality', 'zone', 'section', 'erro']
                                    + ([inv] if inv != 'erro' else []) + cv))
        cond = 'erro IS NOT NULL' if inv == 'erro' else f'"{inv}" = false'
        sel_q = ', '.join(f'"{c}"' for c in cols_q)
        sub = con.execute(f"SELECT {sel_q} FROM read_parquet('{dest.as_posix()}') WHERE {cond}").df()
        rows = linhas_quarentena(sub, inv, pleito, cv)
        write_json(QUARENTENA / f'rows-C2-bu_{pleito}_{inv}.json', rows)
        quar += rows
        del sub
    con.close()
    qcsv = QUARENTENA / 'quarentena_C2.csv'
    novo = pd.DataFrame([{**{k: v for k, v in r.items() if k != 'valores'}, 'valores': _js(r['valores'])} for r in quar],
                        columns=['pleito', 'uf', 'stem', 'municipality', 'zone', 'section', 'checagem', 'reason', 'valores'])
    novo.insert(0, 'camada', 'C2')
    novo.insert(1, 'fonte', 'varredura_forense_bu')
    if qcsv.exists():
        antigo = pd.read_csv(qcsv, sep=';', decimal=',', encoding='utf-8-sig', dtype=str)
        antigo = antigo[~((antigo.fonte == 'varredura_forense_bu') & (antigo.pleito == pleito))]
        novo = pd.concat([antigo, novo.astype(str)], ignore_index=True)
    novo.to_csv(qcsv, **CSV)
    print(f'quarentena: {len(quar)} linhas ({Counter(r["checagem"] for r in quar)})', flush=True)

    # resumo por UF
    linhas = []
    for uf, g in list(df.groupby('uf')) + [('TOTAL', df)]:
        ok = g[g.erro.isna()]
        r = {'uf': uf, 'bus': len(g), 'erros': int(g.erro.notna().sum()),
             'secoes_distintas': int(ok[['municipality', 'zone', 'section']].drop_duplicates().shape[0]),
             'stems_duplicados': int(g.duplicated('stem').sum())}
        for t, ds in TIPO_URNA.items():
            r[f'tipo_urna_{t}_{ds}'] = int((ok.tipo_urna == t).sum())
        r['tipo_arquivo_ne_1'] = int((ok.tipo_arquivo != 1).sum())
        r['bu_de_sa'] = int((ok.dados_tipo == 'sa').sum())
        r['com_historico_correspondencias'] = int((ok.n_correspondencias > 0).sum())
        r['n_versoes'] = int(ok.versao_votacao.nunique())
        r['versoes'] = ' | '.join(sorted(ok.versao_votacao.dropna().unique()))
        r['n_modelos_carga'] = int(ok.modelo_carga.nunique())
        r['modelos_carga'] = ' | '.join(sorted(ok.modelo_carga.dropna().unique())[:30])
        r['n_cargos_moda'] = int(ok.n_cargos.mode().iloc[0]) if len(ok) else None
        r['cargos_esperados'] = ' | '.join(sorted(ok.cargos_esperados.dropna().unique()))
        r['comp_cargos_diferentes'] = int((ok.comp_cargos_iguais.astype('boolean') == False).sum())  # noqa: E712
        r['sem_lista'] = int((ok.lista_status == 'sem lista').sum())
        r['lista_parcial'] = int(ok.lista_status.astype(str).str.startswith('parcial').sum())
        r['com_extras'] = int((ok.n_extras > 0).sum())
        for inv in invs:
            s = ok[inv].astype('boolean')
            r[f'falhas_{inv[4:]}'] = int((s == False).sum())  # noqa: E712
            r[f'na_{inv[4:]}'] = int(s.isna().sum())
        linhas.append(r)
    res = pd.DataFrame(linhas)
    res.to_csv(SAIDA / f'resumo_{pleito}.csv', **CSV)
    pd.set_option('display.width', 250)
    print(res[['uf', 'bus', 'erros', 'secoes_distintas', 'n_versoes', 'cargos_esperados', 'comp_cargos_diferentes', 'sem_lista']
              + [f'falhas_{i[4:]}' for i in invs if res[f'falhas_{i[4:]}'].sum() > 0]].to_string(index=False))
    return res


# ------------------------------------------------------------------ canais (2026-t2: sistema de resultados × dados abertos)
def compara_decodificados(raw_a, raw_b, uf='', stem=''):
    """Campos decodificados que diferem entre dois BUs -> {campo: [a, b]} (strings)."""
    try:
        a = achata(decodifica_bu(raw_a), stem, uf, '', None, raw_a)
    except Exception as exc:  # noqa: BLE001
        a = {'erro': repr(exc)[:120]}
    try:
        b = achata(decodifica_bu(raw_b), stem, uf, '', None, raw_b)
    except Exception as exc:  # noqa: BLE001
        b = {'erro': repr(exc)[:120]}
    return {k: [None if a.get(k) is None else str(a.get(k)), None if b.get(k) is None else str(b.get(k))]
            for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k) and k not in ('arquivo', 'bu_sha256', 'bu_bytes')}


def stem_2026t2(uf, mun, zona, secao):
    return f'o03221{uf.lower()}{str(mun).zfill(5)}{str(zona).zfill(4)}{str(secao).zfill(4)}'


def canais(ufs=None, limite=None):
    sufixo = '_parcial' if (ufs or limite) else ''
    ufs = ufs or [n[:-8] for n in _scandir(SISTEMA_2026T2, sufixo='.parquet')]
    SAIDA.mkdir(parents=True, exist_ok=True)
    resumo, difs = [], []
    cols = ['mun_cd', 'zone_cd', 'section_cd', 'aux_status', 'hash_status', 'status', 'bu_raw']
    for uf in ufs:
        t0 = time.time()
        pf = pq.ParquetFile(SISTEMA_2026T2 / f'{uf}.parquet')
        sis, n = {}, 0
        for b in pf.iter_batches(batch_size=1000, columns=cols):
            for r in b.to_pylist():
                if limite and n >= limite:
                    break
                n += 1
                raw = r['bu_raw']
                sis[stem_2026t2(uf, r['mun_cd'], r['zone_cd'], r['section_cd'])] = (
                    hashlib.sha256(raw).hexdigest() if raw else None, r['aux_status'], r['hash_status'], r['status'])
            del b
            if limite and n >= limite:
                break
        gc.collect()
        ab, raw_dif = {}, {}
        for part in _scandir(ENTRADA / '2026-t2' / uf, prefixo='part-', sufixo='.parquet'):
            tb = pq.read_table(ENTRADA / '2026-t2' / uf / part, columns=['stem', 'bu_raw'])
            for stem, raw in zip(tb.column('stem').to_pylist(), tb.column('bu_raw').to_pylist()):
                sha = hashlib.sha256(raw).hexdigest()
                ab[stem] = sha
                s = sis.get(stem)
                if s and s[0] is not None and s[0] != sha:
                    raw_dif[stem] = raw
            del tb
            gc.collect()
            if limite and set(sis) <= set(ab):
                break
        iguais = [s for s, v in sis.items() if v[0] is not None and ab.get(s) == v[0]]
        diferentes = [s for s, v in sis.items() if v[0] is not None and s in ab and ab[s] != v[0]]
        sem_raw = [s for s, v in sis.items() if v[0] is None]
        so_sis = [s for s, v in sis.items() if v[0] is not None and s not in ab]
        so_ab = [s for s in ab if s not in sis] if not limite else []
        if diferentes:
            want = set(diferentes)
            for b in pf.iter_batches(batch_size=1000, columns=cols):
                for r in b.to_pylist():
                    stem = stem_2026t2(uf, r['mun_cd'], r['zone_cd'], r['section_cd'])
                    if stem in want:
                        campos = compara_decodificados(r['bu_raw'], raw_dif[stem], uf, stem)
                        v = sis[stem]
                        difs.append({'uf': uf, 'stem': stem, 'aux_status': v[1], 'hash_status': v[2], 'status': v[3],
                                     'sha256_sistema': v[0], 'sha256_dados_abertos': ab[stem],
                                     'bytes_sistema': len(r['bu_raw']), 'bytes_dados_abertos': len(raw_dif[stem]),
                                     'n_campos_alterados': len(campos), 'campos_alterados': _js(campos)})
        for s in so_sis:
            v = sis[s]
            difs.append({'uf': uf, 'stem': s, 'aux_status': v[1], 'hash_status': v[2], 'status': v[3],
                         'sha256_sistema': v[0], 'sha256_dados_abertos': None, 'bytes_sistema': None,
                         'bytes_dados_abertos': None, 'n_campos_alterados': None,
                         'campos_alterados': 'NOT_COMPARABLE: só no sistema de resultados'
                         + (' (parts dos dados abertos lidos até o --limite)' if limite else '')})
        for s in so_ab:
            difs.append({'uf': uf, 'stem': s, 'aux_status': None, 'hash_status': None, 'status': None, 'sha256_sistema': None,
                         'sha256_dados_abertos': ab[s], 'bytes_sistema': None, 'bytes_dados_abertos': None,
                         'n_campos_alterados': None, 'campos_alterados': 'NOT_COMPARABLE: só nos dados abertos'})
        for s in sem_raw:
            v = sis[s]
            difs.append({'uf': uf, 'stem': s, 'aux_status': v[1], 'hash_status': v[2], 'status': v[3], 'sha256_sistema': None,
                         'sha256_dados_abertos': ab.get(s), 'bytes_sistema': None, 'bytes_dados_abertos': None,
                         'n_campos_alterados': None,
                         'campos_alterados': f'NOT_COMPARABLE: sem BU capturado no sistema de resultados (status={v[3]}); '
                         + ('presente' if s in ab else 'ausente') + ' nos dados abertos'})
        st = Counter(sis[s][1] for s in diferentes)
        resumo.append({'uf': uf, 'n_sistema': len(sis), 'n_sistema_com_bu': len(sis) - len(sem_raw),
                       'n_dados_abertos': len(ab), 'iguais': len(iguais), 'diferentes': len(diferentes),
                       'diferentes_recebida': st.get('Recebida', 0), 'diferentes_totalizada': st.get('Totalizada', 0),
                       'so_sistema': len(so_sis), 'so_dados_abertos': len(so_ab), 'sem_bu_no_sistema': len(sem_raw),
                       'sem_bu_no_sistema_e_ausente_nos_abertos': sum(1 for s in sem_raw if s not in ab),
                       'recebida_no_sistema': sum(1 for v in sis.values() if v[1] == 'Recebida'), 'limite': limite,
                       'segundos': round(time.time() - t0, 1)})
        print(resumo[-1], flush=True)
        del sis, ab, raw_dif
        gc.collect()
    pd.DataFrame(resumo).to_csv(SAIDA / f'canais_2026t2{sufixo}.csv', **CSV)
    pd.DataFrame(difs, columns=['uf', 'stem', 'aux_status', 'hash_status', 'status', 'sha256_sistema', 'sha256_dados_abertos',
                                'bytes_sistema', 'bytes_dados_abertos', 'n_campos_alterados', 'campos_alterados']
                 ).to_csv(SAIDA / f'canais_2026t2_diferentes{sufixo}.csv', **CSV)
    return pd.DataFrame(resumo), pd.DataFrame(difs)


# ------------------------------------------------------------------ conferência contra referências já existentes
def _bu_presidente(pleito, uf):
    """Linhas da UF (parts da passada) com aptos/comparecimento/votáveis do cargo majoritário principal (1 ou 11)."""
    parts = [SAIDA / p / u / pth.name for p, u, pth in tarefas_pleito(pleito, [uf], base=SAIDA)]
    if not parts:
        raise SystemExit(f'sem parts da passada em {SAIDA / pleito / uf}')
    cargo = '11' if pleito.startswith('2024') else '1'
    dfs = []
    for p in parts:
        nomes = pq.read_schema(p).names
        kc = sorted({re.match(rf'^(e\d+_c{cargo})_votaveis$', c).group(1) for c in nomes
                     if re.match(rf'^(e\d+_c{cargo})_votaveis$', c)})
        if not kc:
            continue
        k = kc[0]
        eid = k.split('_')[0]
        cols = ['stem', 'uf', 'municipality', 'zone', 'section', 'erro', f'{eid}_aptos', f'{k}_comparecimento',
                f'{k}_votaveis', f'{k}_branco', f'{k}_nulo']
        d = pq.read_table(p, columns=[c for c in cols if c in nomes]).to_pandas()
        d = d.rename(columns={f'{eid}_aptos': 'bu_aptos', f'{k}_comparecimento': 'bu_comp', f'{k}_votaveis': 'bu_votaveis',
                              f'{k}_branco': 'bu_branco', f'{k}_nulo': 'bu_nulo'})
        dfs.append(d)
    if not dfs:
        raise SystemExit(f'nenhum cargo {cargo} nos parts de {uf}')
    return pd.concat(dfs, ignore_index=True)


def _referencia(pleito, uf):
    """DataFrame com CHAVE + ref_aptos, ref_comp, ref_branco, ref_nulo, ref_v<n>...; None quando não há referência."""
    tag = 't1' if pleito.endswith('t1') else 't2'
    if pleito.startswith('2026') and SECOES_2026.exists():
        nomes = pq.read_schema(SECOES_2026).names
        cols = CHAVE + [c for c in nomes if c.startswith(tag + '_') and (c[3:] in ('aptos', 'comparecimento', 'branco', 'nulo')
                                                                       or re.fullmatch(r'v\d+', c[3:]))]
        d = pq.read_table(SECOES_2026, columns=cols, filters=[('uf', '=', uf)]).to_pandas()
        d = d.rename(columns={c: 'ref_' + c[3:].replace('comparecimento', 'comp') for c in cols if c not in CHAVE})
        return d
    if pleito.startswith('2022') and BASE_2022.exists():
        nomes = pq.read_schema(BASE_2022).names
        cols = CHAVE + [c for c in nomes if c.startswith(tag + '_') and (c[3:] in ('aptos', 'comp', 'branco', 'nulo', 'A', 'B')
                                                                       or re.fullmatch(r'v\d+', c[3:]))]
        d = pq.read_table(BASE_2022, columns=cols, filters=[('uf', '=', uf)]).to_pandas()
        d = d.rename(columns={c: 'ref_' + {'A': 'v13', 'B': 'v22'}.get(c[3:], c[3:]) for c in cols if c not in CHAVE})
        return d
    if pleito.startswith('2024'):
        p = R / 'bu' / pleito / f'{uf}_PREFEITO.parquet'
        if not p.exists():
            return None
        t = pq.read_table(p, columns=['CD_MUNICIPIO', 'NR_ZONA', 'NR_SECAO', 'QT_APTOS', 'QT_COMPARECIMENTO', 'CD_TIPO_VOTAVEL',
                                      'NR_VOTAVEL', 'QT_VOTOS']).to_pandas()
        for c in t.columns:
            t[c] = pd.to_numeric(t[c], errors='coerce')
        t = t.rename(columns={'CD_MUNICIPIO': 'municipality', 'NR_ZONA': 'zone', 'NR_SECAO': 'section'})
        base = t.groupby(['municipality', 'zone', 'section'], as_index=False).agg(ref_aptos=('QT_APTOS', 'first'),
                                                                                  ref_comp=('QT_COMPARECIMENTO', 'first'))
        piv = t.assign(col=['ref_branco' if tp == 2 else ('ref_nulo' if tp == 3 else f'ref_v{int(n)}')
                            for tp, n in zip(t.CD_TIPO_VOTAVEL, t.NR_VOTAVEL)])
        piv = piv.pivot_table(index=['municipality', 'zone', 'section'], columns='col', values='QT_VOTOS', aggfunc='sum')
        d = base.merge(piv.reset_index(), on=['municipality', 'zone', 'section'], how='left')
        d.insert(0, 'uf', uf)
        return d
    return None


def confere(pleito, ufs):
    saida = []
    for uf in ufs:
        bu = _bu_presidente(pleito, uf)
        ref = _referencia(pleito, uf)
        bu = bu.copy()
        if ref is None:
            bu['status'] = 'NOT_COMPARABLE: sem referência por seção para esta UF/pleito no repositório'
            bu['campos_diferentes'] = None
            bu.drop(columns=['bu_votaveis']).to_csv(SAIDA / f'confere_{pleito}_{uf}.csv', **CSV)
            res = {'pleito': pleito, 'uf': uf, 'bus': len(bu), 'referencia': None, 'status': 'NOT_COMPARABLE'}
            print(res, flush=True)
            saida.append(res)
            continue
        for c in ('municipality', 'zone', 'section'):
            bu[c] = bu[c].astype('Int64')
            ref[c] = ref[c].astype('Int64')
        m = bu.merge(ref, on=CHAVE, how='outer', indicator=True)
        vcols = [c for c in ref.columns if re.fullmatch(r'ref_v\d+', c)]
        ref_completa = not pleito.startswith('2022')   # base_2022 agrega os candidatos menores (t1_menores)
        status, campos = [], []
        for d in m.to_dict('records'):
            if d['_merge'] == 'right_only':
                status.append('NOT_COMPARABLE: seção na referência sem BU na passada')
                campos.append(None)
                continue
            if d['_merge'] == 'left_only':
                status.append('NOT_COMPARABLE: BU sem seção correspondente na referência')
                campos.append(None)
                continue
            if pd.notna(d.get('erro')):
                status.append('NOT_COMPARABLE: erro de decodificação')
                campos.append(None)
                continue
            vot = json.loads(d['bu_votaveis']) if d.get('bu_votaveis') else {}
            dif = []
            for a, b in (('bu_aptos', 'ref_aptos'), ('bu_comp', 'ref_comp'), ('bu_branco', 'ref_branco'), ('bu_nulo', 'ref_nulo')):
                if b in d and not (pd.isna(d[a]) and pd.isna(d[b])) and (pd.isna(d[a]) or pd.isna(d[b]) or int(d[a]) != int(d[b])):
                    dif.append(f'{b[4:]}:{d[a]}!={d[b]}')
            for c in vcols:
                n = c[5:]
                rv = 0 if pd.isna(d[c]) else int(d[c])
                if vot.get(n, 0) != rv:
                    dif.append(f'v{n}:{vot.get(n, 0)}!={rv}')
            for n, v in vot.items():
                if ref_completa and f'ref_v{n}' not in d and v:
                    dif.append(f'v{n}:{v}!=ausente')
            status.append('igual' if not dif else 'diferente')
            campos.append(','.join(dif) or None)
        m['status'] = status
        m['campos_diferentes'] = campos
        m = m.drop(columns=['bu_votaveis', '_merge'])
        m.to_csv(SAIDA / f'confere_{pleito}_{uf}.csv', **CSV)
        cnt = Counter(status)
        res = {'pleito': pleito, 'uf': uf, 'bus': len(bu), 'referencia': len(ref), **dict(cnt)}
        print(res, flush=True)
        saida.append(res)
    return saida


# ------------------------------------------------------------------ CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('passada')
    p.add_argument('pleito')
    p.add_argument('--ufs', default=None)
    p.add_argument('--limite', type=int, default=None)
    p.add_argument('--workers', type=int, default=1)
    c = sub.add_parser('canais')
    c.add_argument('pleito')
    c.add_argument('--ufs', default=None)
    c.add_argument('--limite', type=int, default=None)
    k = sub.add_parser('consolida')
    k.add_argument('pleito')
    f = sub.add_parser('confere')
    f.add_argument('pleito')
    f.add_argument('--ufs', default='AC')
    a = ap.parse_args(argv)
    ufs = [u.strip().upper() for u in a.ufs.split(',')] if getattr(a, 'ufs', None) else None
    if a.cmd == 'passada':
        passada(a.pleito, ufs, a.limite, a.workers)
    elif a.cmd == 'canais':
        if a.pleito != '2026-t2':
            raise SystemExit('canais: só 2026-t2 tem os dois canais em disco')
        canais(ufs, a.limite)
    elif a.cmd == 'consolida':
        consolida(a.pleito)
    elif a.cmd == 'confere':
        confere(a.pleito, ufs or ['AC'])


if __name__ == '__main__':
    main()
