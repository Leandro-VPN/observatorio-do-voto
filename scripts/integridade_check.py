"""Teste de integridade de TODAS as urnas com log guardado no HD.

  zips   ROOT...   le cada zip "arquivos transmitidos para totalizacao" (dados abertos) em blocos contiguos
                   (HTTP Range), confere manifesto x log local x BU/RDV/imagem do BU, assinatura de
                   hardware da urna e certificado da urna x AC do TSE. Nada alem do resultado e gravado.
  t2       UF...   2o turno 2026: baixa o -vota.vsc de cada urna com log (sistema de resultados) e confere
                   o log local e o bu.dat ja guardado.
Resultado: research/integridade/resultado/<rotulo>/part-*.parquet (retomavel).
"""
import argparse
import hashlib
import json
import os
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
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
import integridade_lib as I  # noqa: E402

OUT = ROOT / 'research' / 'integridade' / 'resultado'
MEMBER = re.compile(r'^(?P<stem>.+?)(?:\.(?P<a>bu|imgbu|logjez|rdv|vscmr)|-(?P<b>bu|imgbu|log|rdv|vota)\.(?:dat|jez|vsc))$')
TYPE = {'bu': 'bu', 'imgbu': 'imgbu', 'logjez': 'log', 'log': 'log', 'rdv': 'rdv', 'vscmr': 'man', 'vota': 'man'}
CHUNK = 48


def label_of(root):
    p = Path(root).resolve().relative_to(ROOT / 'research')
    return '_'.join(p.parts)


def zip_entry(root):
    inv = json.loads((Path(root) / 'remote-inventory.json').read_text(encoding='utf-8'))
    for e in inv:
        if 'arqurnatot' in e['resource']['url'] or 'logjez' in e['resource']['url']:
            return e
    raise ValueError('sem zip de arquivos de urna em ' + str(root))


# ------------------------------------------------------------------ worker (processo)
_W = {}


def _reader(url):
    from auditabr.acquisition import RemoteZipReader
    r = _W.get(url)
    if r is None:
        r = RemoteZipReader(url, budget=1 << 42)
        _W.clear(); _W[url] = r
    return r


def _member_bytes(block, begin, m):
    off = m['offset'] - begin
    if block[off:off + 4] != b'PK\x03\x04':
        raise ValueError('cabecalho local invalido ' + m['name'])
    n, x = struct.unpack('<HH', block[off + 26:off + 30])
    s = off + 30 + n + x
    comp = block[s:s + m['csize']]
    if m['method'] == zipfile.ZIP_DEFLATED:
        data = zlib.decompress(comp, -15)
    elif m['method'] == zipfile.ZIP_STORED:
        data = comp
    else:
        raise ValueError('compressao nao suportada')
    if len(data) != m['size'] or zlib.crc32(data) & 0xffffffff != m['crc']:
        raise ValueError('CRC/tamanho divergente ' + m['name'])
    return data


SCATTER = 4 * 1024 ** 2


def _span(u):
    return max(m['offset'] + m['csize'] for m in u['members']) - min(m['offset'] for m in u['members'])


def _read(url, begin, end):
    for attempt in range(5):
        try:
            r = _reader(url)
            r.seek(begin)
            return r.read(end - begin)
        except Exception:
            _W.clear()
            if attempt == 4:
                raise
            time.sleep(3 * 2 ** attempt)


def work_chunk(args):
    """Bloco contiguo para as urnas compactas; urnas com arquivos espalhados no zip (span > 4 MB)
    sao lidas arquivo a arquivo, para nao baixar o intervalo inteiro entre eles."""
    url, size, logdir, chunk_id, urns = args
    compact = [m for u in urns if _span(u) <= SCATTER for m in u['members']]
    blocks = {}
    nbytes = 0
    if compact:
        begin = min(m['offset'] for m in compact)
        end = min(size, max(m['offset'] + m['csize'] for m in compact) + 4096)
        block = _read(url, begin, end)
        nbytes += len(block)
        for m in compact:
            blocks[m['name']] = (block, begin)
    for u in urns:
        if _span(u) > SCATTER:
            for m in u['members']:
                b = _read(url, m['offset'], min(size, m['offset'] + m['csize'] + 1024))
                nbytes += len(b)
                blocks[m['name']] = (b, m['offset'])
    rows = []
    for u in urns:
        row = {'chunk': chunk_id, 'urna': u['stem']}
        try:
            files = {}
            man = None
            for m in u['members']:
                t = TYPE[m['type']]
                blk, beg = blocks[m['name']]
                data = _member_bytes(blk, beg, m)
                if t == 'man':
                    man = data
                else:
                    files[t] = data
                    if t == 'log':
                        row['log_nome'] = m['name']
            if 'log' in files:
                lp = Path(logdir) / row['log_nome']
                if lp.exists():
                    local = lp.read_bytes()
                    row['log_local'] = True
                    row['log_local_igual_zip'] = (local == files['log'])
                    files['log'] = local  # o que se testa e o arquivo guardado no HD
                else:
                    row['log_local'] = False
            if man is None:
                row['erro'] = 'sem manifesto no zip'
            else:
                row.update(I.check_urn(man, files))
        except Exception as exc:
            row['erro'] = repr(exc)[:200]
        rows.append(row)
    return chunk_id, rows, nbytes


def run_zip_root(root, workers):
    root = Path(root)
    lab = label_of(root)
    dest = OUT / lab
    dest.mkdir(parents=True, exist_ok=True)
    if (dest / 'DONE').exists():
        print(lab, 'JA CONCLUIDO', flush=True)
        return
    e = zip_entry(root)
    url, size = e['resource']['url'], e['container_bytes']
    from auditabr.acquisition import RemoteZipReader
    with RemoteZipReader(url, budget=256 * 1024 ** 2) as rz, zipfile.ZipFile(rz) as z:
        infos = sorted(z.infolist(), key=lambda i: i.header_offset)
        zip_atual = {'bytes': rz.size, 'cabecalhos': {k: v for k, v in rz.headers.items() if k.lower() in ('etag', 'last-modified', 'content-range')}}
    if zip_atual['bytes'] != size:
        print(lab, 'ATENCAO: zip republicado pelo TSE desde a coleta', size, '->', zip_atual['bytes'], zip_atual['cabecalhos'], flush=True)
        size = zip_atual['bytes']
    urns = {}
    others = 0
    for i in infos:
        m = MEMBER.match(i.filename)
        if not m or Path(i.filename).name != i.filename:
            others += 1
            continue
        typ = m.group('a') or m.group('b')
        if typ == 'imgbu':
            continue  # imagem do BU nao muda a conclusao; poupa CPU
        u = urns.setdefault(m.group('stem'), {'stem': m.group('stem'), 'members': []})
        u['members'].append({'name': i.filename, 'type': typ, 'offset': i.header_offset, 'csize': i.compress_size,
                             'size': i.file_size, 'crc': i.CRC, 'method': i.compress_type})
    ulist = sorted(urns.values(), key=lambda u: min(m['offset'] for m in u['members']))
    chunks = [ulist[k:k + CHUNK] for k in range(0, len(ulist), CHUNK)]
    done = set()
    for p in dest.glob('part-*.parquet'):
        done |= set(pd.read_parquet(p, columns=['chunk']).chunk.unique())
    todo = [(url, size, str(root / 'logs'), cid, ch) for cid, ch in enumerate(chunks) if cid not in done]
    print(lab, 'urnas', len(ulist), 'outros membros', others, 'blocos', len(chunks), 'pendentes', len(todo), flush=True)
    buf = []
    nbytes = 0
    t0 = time.monotonic()
    part = len(list(dest.glob('part-*.parquet')))

    def flush():
        nonlocal buf, part
        if buf:
            pd.DataFrame(buf).to_parquet(dest / f'part-{part:05d}.parquet', index=False)
            part += 1
            buf = []
    with ProcessPoolExecutor(workers) as ex:
        for k, (cid, rows, nb) in enumerate(ex.map(work_chunk, todo, chunksize=1), 1):
            buf.extend(rows)
            nbytes += nb
            if len(buf) >= 20000:
                flush()
            if k % 100 == 0 or k == len(todo):
                el = time.monotonic() - t0
                print(lab, f'{k}/{len(todo)} blocos', f'{nbytes / 1e9:.1f} GB', f'{nbytes / 1e6 / max(el, 1):.1f} MB/s',
                      f'{el / 60:.1f} min', flush=True)
    flush()
    (dest / 'DONE').write_text(json.dumps({'urnas': len(ulist), 'zip': url, 'bytes_zip_coleta': e['container_bytes'], 'zip_atual': zip_atual,
                                           'concluido': time.strftime('%Y-%m-%d %H:%M:%S')}), encoding='utf-8')
    print(lab, 'CONCLUIDO', flush=True)


# ------------------------------------------------------------------ 2o turno 2026 (sistema de resultados)
def run_t2(ufs, threads):
    import t2_2026_collect as T
    base = ROOT / 'research' / 'segundo_turno_2026'
    for uf in ufs:
        dest = OUT / f'segundo_turno_2026_{uf}.parquet'
        if dest.exists():
            print(uf, 'JA CONCLUIDO', flush=True)
            continue
        logdir = base / 'logs' / uf
        if not logdir.exists():
            continue
        names = {p.name for p in logdir.glob('*-log.jez')}
        bu = pd.read_parquet(base / 'bu' / f'{uf}.parquet',
                             columns=['mun_cd', 'zone_cd', 'section_cd', 'hash', 'log_name', 'bu_raw'])
        bu = bu[bu.log_name.isin(names)]
        mandir = base / 'manifestos' / uf
        mandir.mkdir(parents=True, exist_ok=True)

        def job(r):
            row = {'urna': r.log_name.replace('-log.jez', ''), 'log_nome': r.log_name, 'log_local': True}
            vname = r.log_name.replace('-log.jez', '-vota.vsc')
            mp = mandir / vname
            try:
                if mp.exists():
                    man = mp.read_bytes()
                else:
                    man = T.get(f'{T.BASE}/arquivo-urna/{T.PLEITO}/dados/{uf.lower()}/{r.mun_cd}/{r.zone_cd}/'
                                f'{r.section_cd}/{r.hash}/{vname}', kind='bytes')
                    if not man:
                        row['erro'] = 'manifesto indisponivel'
                        return row
                    mp.write_bytes(man)
                files = {'log': (logdir / r.log_name).read_bytes()}
                if r.bu_raw is not None:
                    files['bu'] = bytes(r.bu_raw)
                row.update(I.check_urn(man, files))
            except Exception as exc:
                row['erro'] = repr(exc)[:200]
            return row
        t0 = time.monotonic()
        with ThreadPoolExecutor(threads) as ex:
            rows = list(ex.map(job, bu.itertuples()))
        df = pd.DataFrame(rows)
        df.insert(0, 'uf', uf)
        df.to_parquet(dest, index=False)
        print(uf, 'T2 CONCLUIDO', len(df), f'{(time.monotonic() - t0) / 60:.1f} min',
              df.get('log_assinatura_ok', pd.Series(dtype=object)).value_counts(dropna=False).to_dict(), flush=True)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('zips'); a.add_argument('roots', nargs='+'); a.add_argument('--workers', type=int, default=8)
    b = sub.add_parser('t2'); b.add_argument('ufs', nargs='+'); b.add_argument('--threads', type=int, default=8)
    args = ap.parse_args()
    if args.cmd == 'zips':
        for r in args.roots:
            run_zip_root(r, args.workers)
    else:
        run_t2(args.ufs, args.threads)


if __name__ == '__main__':
    main()
