"""Baixa para o HD os logs e BUs de urna do pais inteiro (dados abertos do TSE), so o que falta.

Fonte: zips oficiais "bu_imgbu_logjez_rdv_vscmr" listados em relatorios/disco/inventario_zips_pais.csv
(scripts/inventario_pais.py). Le o zip por HTTP Range, confere CRC e tamanho de cada arquivo, nada mais.

  completo  UF/pleito sem logs no HD: le blocos continuos de urnas e grava
              log         -> mesma pasta de logs que o projeto ja usa (export_logs_exemplo.pasta_logs)
              assinatura  -> research/assinaturas/<pleito>/<UF>/   (permite verificar o log sem internet)
              bu          -> research/bu_urna/<pleito>/<UF>/part-*.parquet (bytes originais do .bu)
  so_bu     UF/pleito que ja tem os logs: le so o .bu de cada urna
Retomavel: arquivos ja gravados e partes ja concluidas sao pulados.
Uso: python scripts/baixa_pais.py [completo|so_bu|tudo] [--workers N]
"""
import argparse
import json
import re
import struct
import sys
import time
import zipfile
import zlib
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from auditabr.acquisition import RemoteZipReader  # noqa: E402
from export_logs_exemplo import pasta_logs  # noqa: E402

R = ROOT / 'research'
INV = ROOT / 'relatorios' / 'disco' / 'inventario_zips_pais.csv'
MEMBER = re.compile(r'^(?P<stem>.+?)(?:\.(?P<a>bu|imgbu|logjez|rdv|vscmr)|-(?P<b>bu|imgbu|log|rdv|vota)\.(?:dat|jez|vsc))$')
TIPO = {'bu': 'bu', 'imgbu': 'imgbu', 'logjez': 'log', 'log': 'log', 'rdv': 'rdv', 'vscmr': 'assinatura', 'vota': 'assinatura'}
CHUNK = 48
SCATTER = 4 * 1024 ** 2


def member_bytes(block, begin, m):
    off = m['offset'] - begin
    if block[off:off + 4] != b'PK\x03\x04':
        raise ValueError('cabecalho local invalido ' + m['name'])
    n, x = struct.unpack('<HH', block[off + 26:off + 30])
    s = off + 30 + n + x
    comp = block[s:s + m['csize']]
    data = zlib.decompress(comp, -15) if m['method'] == zipfile.ZIP_DEFLATED else comp
    if len(data) != m['size'] or zlib.crc32(data) & 0xffffffff != m['crc']:
        raise ValueError('CRC/tamanho divergente ' + m['name'])
    return data


def indice(url):
    with RemoteZipReader(url, budget=1 << 30) as rz, zipfile.ZipFile(rz) as z:
        size = rz.size
        urns = {}
        for i in z.infolist():
            m = MEMBER.match(i.filename)
            if not m or Path(i.filename).name != i.filename:
                continue
            u = urns.setdefault(m.group('stem'), {'stem': m.group('stem'), 'members': []})
            u['members'].append({'name': i.filename, 'type': TIPO[m.group('a') or m.group('b')], 'offset': i.header_offset,
                                 'csize': i.compress_size, 'size': i.file_size, 'crc': i.CRC, 'method': i.compress_type})
    return size, sorted(urns.values(), key=lambda u: min(m['offset'] for m in u['members']))


_W = {}


def _read(url, begin, end):
    for attempt in range(6):
        try:
            r = _W.get(url)
            if r is None:
                _W.clear()
                r = _W[url] = RemoteZipReader(url, budget=1 << 42)
            r.seek(begin)
            return r.read(end - begin)
        except Exception:
            _W.clear()
            if attempt == 5:
                raise
            time.sleep(3 * 2 ** attempt)


def destinos(el, uf):
    return pasta_logs(el, uf), R / 'assinaturas' / el / uf, R / 'bu_urna' / el / uf


def chunk_completo(args):
    """Grava log e assinatura de cada urna do bloco; devolve os BUs (bytes) para a parte em parquet."""
    url, size, el, uf, cid, urns = args
    logdir, assdir, _ = destinos(el, uf)
    logdir.mkdir(parents=True, exist_ok=True)
    assdir.mkdir(parents=True, exist_ok=True)
    want = [u for u in urns if any(m['type'] in ('log', 'bu', 'assinatura') for m in u['members'])]
    compact = [m for u in want if max(m['offset'] + m['csize'] for m in u['members']) - min(m['offset'] for m in u['members']) <= SCATTER
               for m in u['members']]
    blocks, nbytes = {}, 0
    if compact:
        b0 = min(m['offset'] for m in compact)
        b1 = min(size, max(m['offset'] + m['csize'] for m in compact) + 4096)
        blk = _read(url, b0, b1)
        nbytes += len(blk)
        for m in compact:
            blocks[m['name']] = (blk, b0)
    bus, erros = [], []
    for u in want:
        for m in u['members']:
            if m['type'] not in ('log', 'bu', 'assinatura'):
                continue
            dest = (logdir if m['type'] == 'log' else assdir) / m['name']
            if m['type'] != 'bu' and dest.exists() and dest.stat().st_size == m['size']:
                continue
            try:
                if m['name'] not in blocks:
                    b = _read(url, m['offset'], min(size, m['offset'] + m['csize'] + 1024))
                    nbytes += len(b)
                    blocks[m['name']] = (b, m['offset'])
                data = member_bytes(*blocks[m['name']], m)
            except Exception as exc:  # noqa: BLE001
                erros.append({'stem': u['stem'], 'arquivo': m['name'], 'erro': repr(exc)[:150]})
                continue
            if m['type'] == 'bu':
                bus.append({'stem': u['stem'], 'arquivo': m['name'], 'bu_raw': data})
            else:
                dest.write_bytes(data)
    return cid, bus, erros, nbytes


def bu_um(args):
    url, size, u = args
    m = next(m for m in u['members'] if m['type'] == 'bu')
    try:
        b = _read(url, m['offset'], min(size, m['offset'] + m['csize'] + 1024))
        return {'stem': u['stem'], 'arquivo': m['name'], 'bu_raw': member_bytes(b, m['offset'], m)}, None, len(b)
    except Exception as exc:  # noqa: BLE001
        return None, {'stem': u['stem'], 'arquivo': m['name'], 'erro': repr(exc)[:150]}, 0


def run(el, uf, url, modo, workers):
    _, _, budir = destinos(el, uf)
    budir.mkdir(parents=True, exist_ok=True)
    done_flag = budir / f'DONE_{modo}'
    if done_flag.exists():
        print(el, uf, modo, 'JA CONCLUIDO', flush=True)
        return
    size, ulist = indice(url)
    ulist = [u for u in ulist if any(m['type'] == 'bu' for m in u['members']) or modo == 'completo']
    feitos = set()
    for p in budir.glob('part-*.parquet'):
        feitos |= set(pd.read_parquet(p, columns=['stem']).stem)
    part = len(list(budir.glob('part-*.parquet')))
    erros, buf, nbytes, t0 = [], [], 0, time.monotonic()

    def flush():
        nonlocal buf, part
        if buf:
            pd.DataFrame(buf).to_parquet(budir / f'part-{part:05d}.parquet', index=False)
            part += 1
            buf = []

    if modo == 'completo':
        chunks = [ulist[k:k + CHUNK] for k in range(0, len(ulist), CHUNK)]
        todo = [(url, size, el, uf, cid, ch) for cid, ch in enumerate(chunks) if not all(u['stem'] in feitos for u in ch)]
        print(el, uf, 'completo: urnas', len(ulist), 'blocos pendentes', len(todo), flush=True)
        with ProcessPoolExecutor(workers) as ex:
            for k, (cid, bus, err, nb) in enumerate(ex.map(chunk_completo, todo, chunksize=1), 1):
                buf.extend(b for b in bus if b['stem'] not in feitos)
                erros.extend(err)
                nbytes += nb
                if len(buf) >= 5000:
                    flush()
                if k % 200 == 0 or k == len(todo):
                    el_ = time.monotonic() - t0
                    print(el, uf, f'{k}/{len(todo)} blocos', f'{nbytes / 1e9:.1f} GB', f'{nbytes / 1e6 / max(el_, 1):.1f} MB/s', flush=True)
    else:
        todo = [(url, size, u) for u in ulist if u['stem'] not in feitos]
        print(el, uf, 'so_bu: urnas', len(ulist), 'pendentes', len(todo), flush=True)
        with ThreadPoolExecutor(workers) as ex:
            for k, (rec, err, nb) in enumerate(ex.map(bu_um, todo), 1):
                if rec:
                    buf.append(rec)
                if err:
                    erros.append(err)
                nbytes += nb
                if len(buf) >= 5000:
                    flush()
                if k % 5000 == 0 or k == len(todo):
                    el_ = time.monotonic() - t0
                    print(el, uf, f'{k}/{len(todo)} BUs', f'{k / max(el_, 1):.0f} BU/s', flush=True)
    flush()
    if erros:
        pd.DataFrame(erros).to_csv(budir / f'erros_{modo}.csv', index=False, sep=';', encoding='utf-8-sig')
    done_flag.write_text(json.dumps({'url': url, 'urnas': len(ulist), 'erros': len(erros), 'bytes_lidos': nbytes,
                                     'concluido': time.strftime('%Y-%m-%d %H:%M:%S')}), encoding='utf-8')
    print(el, uf, modo, 'CONCLUIDO', 'erros', len(erros), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('modo', choices=['completo', 'so_bu', 'tudo'])
    ap.add_argument('--workers', type=int, default=4)
    a = ap.parse_args()
    d = pd.read_csv(INV, sep=';', encoding='utf-8-sig')
    d = d[d.status == 'ok'].copy()
    d['falta_log'] = d.logs_no_hd < 0.99 * d.log_arquivos.fillna(0)
    ordem = {'2022-t1': 0, '2022-t2': 1, '2024-t1': 2, '2024-t2': 3, '2026-t1': 4, '2026-t2': 5}
    d = d.sort_values(['falta_log', 'eleicao', 'uf'], key=lambda s: s.map(ordem) if s.name == 'eleicao' else s, ascending=[False, True, True])
    for r in d.itertuples():
        modo = 'completo' if r.falta_log else 'so_bu'
        if a.modo in (modo, 'tudo'):
            run(r.eleicao, r.uf, r.url, modo, a.workers if modo == 'completo' else 2 * a.workers)


if __name__ == '__main__':
    main()
