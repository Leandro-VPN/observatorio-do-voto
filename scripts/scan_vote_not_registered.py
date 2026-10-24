"""Scan every urn log of given folders for 'O voto do eleitor NÃO foi registrado' (and any ERRO during voting), all logs (not only contingency)."""
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

from auditabr.logs import read_log

PAT = re.compile(r'foi registrado', re.I)


def scan(path):
    try:
        data = read_log(path)
        txt = data.decode('utf-8-sig', 'ignore') if isinstance(data, bytes) else data
    except Exception as exc:
        return dict(member=path.name, error=repr(exc)[:80])
    hits = [l for l in txt.splitlines() if PAT.search(l)]
    if not hits:
        return None
    codes = sorted({m for l in hits for m in re.findall(r'\((\d{4})\)', l)})
    return dict(member=path.name, hits=len(hits), codes=','.join(codes), first=hits[0][:19], msgs=' | '.join(sorted({re.sub(r'\d+', 'N', l.split('\t', 5)[4])[:90] for l in hits if l.count('\t') >= 4})))


if __name__ == '__main__':
    out = []
    for folder in sys.argv[1:]:
        folder = Path(folder)
        files = [p for p in (folder / 'logs').iterdir() if p.suffix.lower() in ('.jez', '.logjez')]
        with ProcessPoolExecutor(max_workers=5) as pool:
            for r in pool.map(scan, files, chunksize=32):
                if r:
                    r['folder'] = folder.as_posix()
                    out.append(r)
        print(folder, 'scanned', len(files), 'hits so far', len(out), flush=True)
    pd.DataFrame(out).to_csv('research/contingencia/_scan_voto_nao_registrado.csv', index=False)
    print('SCAN DONE', len(out), flush=True)
