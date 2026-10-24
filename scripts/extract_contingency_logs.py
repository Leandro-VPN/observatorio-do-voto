"""Re-read urn logs whose section identity was ambiguous (contingency / replaced urns) and extract what the published log shows.

Identity comes from the file name (…MMMMMZZZZSSSS.logjez / …MMMMMZZZZSSSS-log.jez). For each log: power-on times, contingency procedure times,
first/last vote, votes in this urn, votes after 17:00, closing events, data-recovery markers, and all non-VOTA message types (counts) for later taxonomy.
Output: research/contingencia/<folder>.parquet (one row per log) + message_counts.parquet.
"""
import json
import re
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

from auditabr.logs import read_log

DAYS = {('2022-t1',): '02/10/2022', ('2022-t2',): '30/10/2022', ('2026-t1',): '04/10/2026', ('2024-t1',): '06/10/2024', ('2024-t2',): '27/10/2024'}
ID_RE = re.compile(r'(\d{5})(\d{4})(\d{4})(?:\.logjez|-log\.jez)$', re.I)
OUT = Path('research/contingencia')
KW = re.compile(r'conting|substitu|RED\b|recupera|mem[oó]ria de resultado|falha|erro|defeito|reinici|Urna ligada|desligada|Carga|lacr|zer[eé]sima|encerramento|Abertura|bateria|rede el|tempo|rel[oó]gio|hor[aá]rio|data e hora', re.I)


def day_for(folder):
    k = folder.name
    return DAYS[(k,)]


def parse(args):
    path, day = args
    m = ID_RE.search(path.name)
    rec = dict(member=path.name, municipality=int(m.group(1)) if m else None, zone=int(m.group(2)) if m else None, section=int(m.group(3)) if m else None)
    try:
        data = read_log(path)
        txt = data.decode('utf-8-sig', 'ignore') if isinstance(data, bytes) else data
    except Exception as exc:
        rec['error'] = repr(exc)[:120]
        return rec, Counter()
    lines = txt.splitlines()
    rec['days_in_log'] = ','.join(sorted({l[:10] for l in lines if len(l) > 10 and l[2] == '/'}))
    el = [l.split('\t', 5) for l in lines if l.startswith(day)]
    el = [f for f in el if len(f) >= 5]
    times = lambda pred: [f[0][11:19] for f in el if pred(f[4])]
    rec['n_events_day'] = len(el)
    rec['power_on'] = ';'.join(times(lambda s: s.startswith('Urna ligada')))
    rec['power_off'] = ';'.join(times(lambda s: 'desligada' in s))
    rec['contingency_mode'] = ';'.join(times(lambda s: 'Urna de conting' in s))
    rec['contingency_start'] = ';'.join(times(lambda s: s.startswith('In') and 'procedimento de conting' in s))
    rec['contingency_ok'] = ';'.join(times(lambda s: 'Conting' in s and 'sucesso' in s))
    rec['contingency_fail'] = ';'.join(times(lambda s: 'onting' in s and re.search(r'falh|erro|n[aã]o', s, re.I)))
    rec['recovery_markers'] = ';'.join(sorted({f[4][:80] for f in el if re.search(r'\bRED\b|recupera|mem[oó]ria de resultado', f[4], re.I)}))[:400]
    rec['voting_mode'] = ';'.join(times(lambda s: s == 'Modo de carga da UE - Votação' or s == 'Modo de carga da UE - Votao'))
    votes = [f[0][11:19] for f in el if f[3] == 'VOTA' and f[4] == 'O voto do eleitor foi computado']
    rec['votes'] = len(votes)
    rec['first_vote'] = votes[0] if votes else None
    rec['last_vote'] = votes[-1] if votes else None
    rec['late_votes'] = sum(1 for t in votes if t > '17:00:00')
    rec['closing_code'] = ';'.join(times(lambda s: 'encerramento digitado' in s))
    rec['closing_confirmed'] = ';'.join(times(lambda s: 'encerramento confirmado' in s))
    rec['closing_start'] = ';'.join(times(lambda s: s.startswith('Inicio do Encerramento') or s.startswith('Início do Encerramento')))
    rec['errors_day'] = sum(1 for f in el if f[1] == 'ERRO')
    rec['error_msgs'] = ';'.join(sorted({re.sub(r'\d+', 'N', f[4])[:70] for f in el if f[1] == 'ERRO'}))[:400]
    rec['zeresima'] = ';'.join(times(lambda s: 'zer' in s.lower() and 'sima' in s.lower() and ('emit' in s.lower() or 'impress' in s.lower())))[:120]
    rec['locale_zero'] = any('Local de Vota' in l and ': 0000' in l for l in lines)
    c = Counter(re.sub(r'\d+', 'N', f[4])[:90] for f in el if f[3] != 'VOTA')
    return rec, c


def main(folder):
    folder = Path(folder)
    f = folder / 'operations.jsonl'
    if not f.exists() or f.stat().st_size == 0:
        print(folder, 'no operations.jsonl; skipped', flush=True)
        return
    ops = pd.read_json(f, lines=True, dtype=False)
    if 'identity_status' not in ops:
        print(folder, 'no identity_status; skipped', flush=True)
        return
    amb = ops[ops.identity_status != 'PARSED'].member.tolist()
    day = day_for(folder)
    jobs = [(folder / 'logs' / m, day) for m in amb]
    rows, total = [], Counter()
    with ProcessPoolExecutor(max_workers=4) as pool:
        for rec, c in pool.map(parse, jobs, chunksize=8):
            rows.append(rec)
            total.update(c)
    tag = folder.as_posix().replace('research/', '').replace('/', '_')
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(OUT / f'{tag}.parquet', index=False)
    pd.DataFrame([{'msg': k, 'count': v} for k, v in total.most_common()]).to_parquet(OUT / f'{tag}_messages.parquet', index=False)
    print(tag, 'ambiguous', len(amb), 'parsed', len(rows), 'with contingency_start', sum(1 for r in rows if r.get('contingency_start')), flush=True)


if __name__ == '__main__':
    for f in sys.argv[1:]:
        main(f)
