"""Full log operational description, with explicit limits; no causal attribution."""
import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
import json
import re
from pathlib import Path
from statistics import median, stdev
import time

from auditabr.logs import read_log
from auditabr.utils import sha256, utcnow, write_json

ROOT = Path('research/piloto-ba-2022-t2')
VERSION = 'observed-sequence-2022-1'
DAY = '30/10/2022 '


def parse(data, *, day=DAY, allow_unattributed=False, allow_named_authorization=False):
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = data.decode('latin1')
    state = defaultdict(lambda: {'stage': 0, 'bio': False, 'no_bio': False, 'enabled': False, 'unattributed': False})
    times = {}
    late_times = []
    result = dict(vote_events=0, after_17_recorded=0, manual_sequence_votes=0,
                  after_17_manual_sequence=0, biometric_votes=0, no_enrollment_votes=0,
                  unclassified_votes=0, conflicting_votes=0, clock_reversals=0,
                  malformed_timestamps=0, votes_1630_1700=0, manual_requests=0,
                  worker_fingerprint_captures=0, cancellations=0,
                  first_vote=None, last_vote=None, manual_unattributed_votes=0, after_17_manual_unattributed=0)
    for line in text.splitlines():
        fields = line.split('\t', 5)
        if len(fields) < 5 or not fields[0].startswith(day) or fields[3] != 'VOTA':
            continue
        stamp, device, message = fields[0][11:], fields[2], fields[4]
        try:
            h, m, s = map(int, stamp.split(':'))
            if not (0 <= h <= 23 and 0 <= m <= 59 and 0 <= s <= 59):
                raise ValueError('time')
            seconds = h * 3600 + m * 60 + s
        except ValueError:
            result['malformed_timestamps'] += 1
            state.pop(device, None)
            continue
        if device in times and seconds < times[device]:
            result['clock_reversals'] += 1
            state.pop(device, None)
        times[device] = seconds
        if message in ('Aguardando digitação do título', 'Aguardando digitação do identificador do eleitor'):
            state.pop(device, None)
            continue
        if (message.startswith('Habilitação cancelada') or
                message in ('Habilitação do eleitor cancelada', 'Eleitor foi suspenso pelo mesário')):
            result['cancellations'] += 1
            state.pop(device, None)
            continue
        current = state[device]
        if message == 'Solicitação de dado pessoal do eleitor para habilitação manual':
            result['manual_requests'] += 1
            current['stage'] = 1
        elif (message == 'Capturada a digital do mesário' or
              (allow_named_authorization and re.fullmatch(r'Mesário \d+ habilitou o eleitor',message))):
            result['worker_fingerprint_captures'] += 1
            if current['stage'] == 1:
                current['stage'] = 2
        elif allow_unattributed and message == 'Digital coletada bate com uma digital gravada após o registro inicial de mesário. Não é possível associar a habilitação a um mesário.':
            if current['stage'] == 1:
                current['stage'] = 2
            current['unattributed'] = True
        elif message == 'Eleitor foi habilitado':
            current['enabled'] = True
            if current['stage'] == 2:
                current['stage'] = 3
        elif message == 'Tipo de habilitação do eleitor [biométrica]':
            current['bio'] = True
        elif message == 'O eleitor não possui biometria':
            current['no_bio'] = True
        elif message == 'O voto do eleitor foi computado':
            result['vote_events'] += 1
            late = seconds > 17 * 3600
            result['after_17_recorded'] += int(late)
            result['votes_1630_1700'] += int(59400 <= seconds <= 61200)
            result['first_vote'] = stamp if result['first_vote'] is None else min(result['first_vote'], stamp)
            result['last_vote'] = stamp if result['last_vote'] is None else max(result['last_vote'], stamp)
            if late:
                late_times.append(seconds)
            manual = current['stage'] == 3
            labels = int(manual) + int(current['bio']) + int(current['no_bio'])
            if labels > 1:
                result['conflicting_votes'] += 1
            elif manual:
                result['manual_sequence_votes'] += 1
                result['after_17_manual_sequence'] += int(late)
                result['manual_unattributed_votes'] += int(current['unattributed'])
                result['after_17_manual_unattributed'] += int(late and current['unattributed'])
            elif current['bio'] and current['enabled']:
                result['biometric_votes'] += 1
            elif current['no_bio'] and current['enabled']:
                result['no_enrollment_votes'] += 1
            else:
                result['unclassified_votes'] += 1
            state.pop(device, None)
    intervals = [b-a for a, b in zip(late_times, late_times[1:])]
    result['late_interval_median_seconds'] = median(intervals) if intervals and min(intervals) >= 0 else None
    result['late_interval_sd_seconds'] = stdev(intervals) if len(intervals) >= 2 and min(intervals) >= 0 else None
    assert sum(result[k] for k in ('manual_sequence_votes', 'biometric_votes', 'no_enrollment_votes',
                                   'unclassified_votes', 'conflicting_votes')) == result['vote_events']
    return result


def process(record):
    path = ROOT / 'logs' / record['member']
    out = ROOT / 'operational-logs' / (path.name + '.json')
    if out.exists():
        saved = json.loads(out.read_text(encoding='utf-8'))
        if saved.get('parser_version') == VERSION and saved.get('source_sha256') == record['sha256']:
            return saved['status']
    try:
        assert sha256(path) == record['sha256']
        metrics = parse(read_log(path))
        assert metrics['vote_events'] == record['vote_events'], 'Count differs from previous independent parser'
        result = {'status': 'PARSED', 'parser_version': VERSION, 'source_sha256': record['sha256'],
                  **{k: record.get(k) for k in ('member', 'municipality', 'zone', 'section')},
                  'identity_status': record['status'], **metrics}
    except Exception as exc:
        result = {'status': 'FAILED', 'member': record['member'], 'error': str(exc)}
    write_json(out, result)
    return result['status']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    (ROOT / 'operational-logs').mkdir(exist_ok=True)
    records = [json.loads(line) for line in (ROOT / 'parsed-log-index.jsonl').read_text(encoding='utf-8').splitlines()]
    if args.limit:
        records = records[:args.limit]
    start = time.monotonic()
    counts = defaultdict(int)
    with ProcessPoolExecutor(max_workers=4) as pool:
        for i, status in enumerate(pool.map(process, records, chunksize=16), 1):
            counts[status] += 1
            if i % 1000 == 0 or i == len(records):
                print(json.dumps({'processed': i, 'total': len(records), 'seconds': round(time.monotonic()-start),
                                  'counts': dict(counts)}), flush=True)
    write_json(ROOT / 'operational-run.json', {'at': utcnow(), 'selected': len(records),
               'counts': dict(counts), 'parser_version': VERSION, 'script_sha256': sha256(Path(__file__)),
               'status': 'RECORDED_CLOCK_DESCRIPTIVE_NOT_CONFIRMED_A_B_C_D'})


if __name__ == '__main__':
    main()
