"""Amostra ~2.000 urnas (presidencial 2022, 2o turno, varias UFs) e confere RDV x BU por cargo.

Para cada urna sorteada: le do zip oficial do TSE (dados abertos, HTTP Range) o .bu e o .rdv,
decodifica os dois e verifica se a soma dos votos do RDV, por cargo e por candidato, e igual ao BU.
O RDV e a lista embaralhada de votos individuais; o BU e o total. Se batem exatamente, o total
publicado corresponde, voto a voto, ao registro individual da mesma urna. (Nao e testemunha externa
a urna - ambos saem do mesmo encerramento - mas fecha a consistencia interna entre os dois artefatos.)

Saida: relatorios/verificacoes/rdv_bu/<UF>.parquet e, ao final, rdv_bu_resumo.csv
"""
import random
import re
import struct
import sys
import time
import zipfile
import zlib
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
from auditabr.acquisition import RemoteZipReader  # noqa: E402
from rdv_lib import compara  # noqa: E402

OUT = ROOT / 'relatorios' / 'verificacoes' / 'rdv_bu'
BASE = 'https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2022/arqurnatot/bu_imgbu_logjez_rdv_vscmr_2022_2t_{}.zip'
UFS = ['SP', 'MG', 'RS', 'RJ', 'PE', 'PA', 'CE']
POR_UF = 290
SEED = 20261027
MEMBER = re.compile(r'^(?P<stem>.+?)(?:\.(?P<a>bu|rdv)|-(?P<b>bu|rdv)\.dat)$')


def _member_bytes(block, begin, m):
    off = m['offset'] - begin
    if block[off:off + 4] != b'PK\x03\x04':
        raise ValueError('cabecalho local invalido')
    n, x = struct.unpack('<HH', block[off + 26:off + 30])
    s = off + 30 + n + x
    comp = block[s:s + m['csize']]
    data = zlib.decompress(comp, -15) if m['method'] == zipfile.ZIP_DEFLATED else comp
    if len(data) != m['size'] or zlib.crc32(data) & 0xffffffff != m['crc']:
        raise ValueError('CRC/tamanho divergente')
    return data


def indice(rz):
    with zipfile.ZipFile(rz) as z:
        urns = {}
        for i in z.infolist():
            if Path(i.filename).name != i.filename:
                continue
            m = MEMBER.match(i.filename)
            if not m:
                continue
            typ = m.group('a') or m.group('b')
            u = urns.setdefault(m.group('stem'), {})
            u[typ] = {'offset': i.header_offset, 'csize': i.compress_size, 'size': i.file_size,
                      'crc': i.CRC, 'method': i.compress_type}
    return {k: v for k, v in urns.items() if 'bu' in v and 'rdv' in v}


def uf_job(uf):
    dest = OUT / f'{uf}.parquet'
    if dest.exists():
        print(uf, 'JA FEITO', flush=True)
        return pd.read_parquet(dest)
    url = BASE.format(uf)
    rows = []
    with RemoteZipReader(url, budget=8 * 1024 ** 3) as rz:
        idx = indice(rz)
        stems = sorted(idx)
        random.Random(SEED).shuffle(stems)
        amostra = stems[:POR_UF]
        size = rz.size
        for k, stem in enumerate(amostra, 1):
            u = idx[stem]
            begin = min(u['bu']['offset'], u['rdv']['offset'])
            end = min(size, max(u['bu']['offset'] + u['bu']['csize'], u['rdv']['offset'] + u['rdv']['csize']) + 4096)
            row = {'uf': uf, 'stem': stem}
            block = None
            for attempt in range(4):           # retry so em falha de rede
                try:
                    rz.seek(begin)
                    block = rz.read(end - begin)
                    break
                except Exception as exc:
                    if attempt == 3:
                        row['erro'] = 'rede: ' + repr(exc)[:150]
                    else:
                        time.sleep(2 * 2 ** attempt)
            if block is not None:
                try:
                    bu = _member_bytes(block, begin, u['bu'])
                    rdv = _member_bytes(block, begin, u['rdv'])
                    ok, difs, tb, tr = compara(bu, rdv)
                    row.update(confere=ok, total_bu=tb, total_rdv=tr, n_difs=len(difs),
                               difs=str(difs[:8]) if difs else '')
                except Exception as exc:
                    row['erro'] = 'decode: ' + repr(exc)[:150]
            rows.append(row)
            if k % 50 == 0:
                print(uf, k, POR_UF, 'conferem', sum(r.get('confere', False) for r in rows), flush=True)
    d = pd.DataFrame(rows)
    dest.parent.mkdir(parents=True, exist_ok=True)
    d.to_parquet(dest, index=False)
    print(uf, 'CONCLUIDO', len(d), 'conferem', int(d.confere.sum()) if 'confere' in d else 0, flush=True)
    return d


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    partes = [uf_job(uf) for uf in UFS]
    d = pd.concat(partes, ignore_index=True)
    res = d.groupby('uf').apply(lambda g: pd.Series({
        'urnas': len(g),
        'conferem': int(g.confere.sum()) if 'confere' in g else 0,
        'divergentes': int((~g.confere.fillna(False)).sum()) - int(g.get('erro', pd.Series([None] * len(g))).notna().sum()),
        'erros_leitura': int(g['erro'].notna().sum()) if 'erro' in g else 0,
    })).reset_index()
    res.loc['TOTAL'] = ['TOTAL', res.urnas.sum(), res.conferem.sum(), res.divergentes.sum(), res.erros_leitura.sum()]
    res.to_csv(ROOT / 'relatorios/verificacoes/rdv_bu_resumo.csv', index=False, sep=';', encoding='utf-8-sig')
    pd.set_option('display.width', 200)
    print(res.to_string(index=False))
    if 'confere' in d:
        bad = d[d.confere.eq(False) & d.get('erro', pd.Series([None] * len(d))).isna()]
        if len(bad):
            print('\nDIVERGENCIAS:')
            print(bad[['uf', 'stem', 'total_bu', 'total_rdv', 'difs']].to_string(index=False))


if __name__ == '__main__':
    main()
