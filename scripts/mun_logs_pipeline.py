"""2024 municipal urn logs (same method): inventory, Range collection, parsing. BU (PREFEITO) comes from bu_capture_all.py.

Usage: python scripts/mun_logs_pipeline.py --uf SP [--turns 1,2]
Layout: research/municipais/<UF>/2024-t<turn>/{remote-inventory.json,logs/,operational-logs/,operations.jsonl}
"""
import argparse
import subprocess
import sys
import zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import uf_pipeline as U
from auditabr.acquisition import RemoteZipReader
from auditabr.catalog import Catalog
from auditabr.utils import read_json, utcnow, write_json

YEAR = 2024
MUN = Path('research/catalogo-municipais')


def folder_for(uf, turn):
    return Path('research/municipais') / uf / f'{YEAR}-t{turn}'


def prepare(uf, turn, folder):
    folder.mkdir(parents=True, exist_ok=True)
    inv = folder / 'remote-inventory.json'
    if inv.exists():
        return
    res = Catalog(MUN).resources(YEAR)
    log = next(r for r in res if '/arqurnatot/' in r['url'] and r['url'].endswith(f'_{YEAR}_{turn}t_{uf}.zip'))
    with RemoteZipReader(log['url'], budget=64 * 1024 ** 2) as remote, zipfile.ZipFile(remote) as archive:
        write_json(inv, [{'resource': log, 'container_bytes': remote.size, 'members': [
            {'name': m.filename, 'bytes': m.file_size, 'compressed': m.compress_size} for m in archive.infolist() if not m.is_dir()]}])


def run(uf, turn, workers, connections):
    folder = folder_for(uf, turn)
    if (folder / 'processing-run.json').exists() and read_json(folder / 'processing-run.json').get('complete_scope') \
            and (folder / 'log-collection-run.json').exists() and read_json(folder / 'log-collection-run.json').get('complete_scope'):
        print('SKIP (done)', folder, flush=True)
        return
    prepare(uf, turn, folder)
    (folder / 'collect.finished').unlink(missing_ok=True)
    complete = folder / 'log-collection-run.json'
    import os
    for attempt in range(4):
        if complete.exists() and read_json(complete).get('complete_scope'):
            break
        complete.unlink(missing_ok=True)
        collector = subprocess.Popen([sys.executable, str(Path(__file__).parent / 'collect_bahia_log_blocks.py'), '--root', str(folder), '--connections', str(connections)],
                                     env={**os.environ, 'PYTHONPATH': 'src'})
        if attempt == 0:
            pool = ThreadPoolExecutor(max_workers=1)
            fut = pool.submit(lambda: (collector.wait(), (folder / 'collect.finished').write_text('x')))
            U.process_logs(folder, YEAR, turn, workers)
            fut.result()
        else:
            collector.wait()
    assert read_json(complete)['complete_scope'], 'collection did not complete'
    (folder / 'collect.finished').write_text('x')
    U.process_logs(folder, YEAR, turn, workers)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--uf', required=True)
    p.add_argument('--turns', default='1,2')
    p.add_argument('--workers', type=int, default=3)
    p.add_argument('--connections', type=int, default=6)
    a = p.parse_args()
    failed = []
    for t in [int(x) for x in a.turns.split(',')]:
        try:
            run(a.uf.upper(), t, a.workers, a.connections)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            failed.append((t, repr(exc)))
    print('UF DONE', a.uf, 'FAILED:', failed, flush=True)
    sys.exit(1 if failed else 0)
