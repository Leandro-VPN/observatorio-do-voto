"""Per-UF presidential pipeline (same method as the Bahia study): BU capture, Range log collection, log parsing, analysis.

Usage: python scripts/uf_pipeline.py --uf SP [--elections 2022-1,2022-2,2026-1]
Layout: research/estados/<UF>/<year>-t<turn>/{bu.parquet,remote-inventory.json,logs/,operational-logs/,analysis/}
"""
import argparse
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as csv
import pyarrow.parquet as pq

import analyze_pilot_operations as engine
from auditabr.acquisition import RemoteZipReader
from auditabr.catalog import Catalog
from auditabr.logs import read_log
from auditabr.utils import read_json, sha256, utcnow, write_json
from pilot_log_count import parse_count

VERSION = 'uf-document-log-1'
CATALOG_ROOT = Path('research/bahia-presidente-2022-2026')
DAYS = {(2022, 1): '02/10/2022 ', (2022, 2): '30/10/2022 ', (2026, 1): '04/10/2026 ', (2024, 1): '06/10/2024 ', (2024, 2): '27/10/2024 '}
SCRIPTS = Path(__file__).resolve().parent
ROOT = None
YEAR = TURN = None


def folder_for(uf, year, turn):
    return Path('research/estados') / uf / f'{year}-t{turn}'


# ---------------------------------------------------------------- prepare
def prepare(uf, year, turn, folder):
    folder.mkdir(parents=True, exist_ok=True)
    resources = Catalog(CATALOG_ROOT).resources(year)
    log = next(r for r in resources if '/arqurnatot/' in r['url'] and r['url'].endswith(f'_{year}_{turn}t_{uf}.zip'))
    inv_path = folder / 'remote-inventory.json'
    if not inv_path.exists():
        with RemoteZipReader(log['url'], budget=64 * 1024 ** 2) as remote, zipfile.ZipFile(remote) as archive:
            write_json(inv_path, [{'resource': log, 'container_bytes': remote.size, 'members': [
                {'name': m.filename, 'bytes': m.file_size, 'compressed': m.compress_size}
                for m in archive.infolist() if not m.is_dir()]}])
    bu = next(r for r in resources if f'/buweb/bweb_{turn}t_{uf}_' in r['url'] and r['url'].endswith('.zip'))
    out = folder / 'bu.parquet'
    receipt = out.with_suffix('.json')
    if receipt.exists() and out.exists() and sha256(out) == read_json(receipt)['sha256']:
        return
    with RemoteZipReader(bu['url'], budget=4 * 1024 ** 3) as remote, zipfile.ZipFile(remote) as archive:
        names = [i.filename for i in archive.infolist() if i.filename.endswith('.csv')]
        if len(names) != 1:
            raise ValueError(('Expected one BU CSV', names))
        name = names[0]
        with archive.open(name) as member, io.BufferedReader(member, 8 * 1024 ** 2) as stream:
            header = stream.peek(65536).split(b'\n', 1)[0].decode('latin1').strip().replace('"', '').split(';')
            reader = csv.open_csv(stream, read_options=csv.ReadOptions(encoding='latin1', block_size=8 * 1024 ** 2),
                                  parse_options=csv.ParseOptions(delimiter=';'),
                                  convert_options=csv.ConvertOptions(column_types={c: pa.string() for c in header}))
            writer, count = None, 0
            try:
                for batch in reader:
                    table = pa.Table.from_batches([batch])
                    table = table.filter(pc.equal(pc.utf8_upper(table['DS_CARGO_PERGUNTA']), 'PRESIDENTE'))
                    table = table.filter(pc.equal(table['SG_UF'], uf))
                    if writer is None:
                        writer = pq.ParquetWriter(out, table.schema, compression='zstd')
                    writer.write_table(table)
                    count += len(table)
            finally:
                if writer:
                    writer.close()
        write_json(receipt, {'at': utcnow(), 'resource': bu, 'member': name, 'member_crc32': archive.getinfo(name).CRC,
                             'sha256': sha256(out), 'rows': count, 'bytes': out.stat().st_size,
                             'scope': f'{uf} PRESIDENTE'})


# ---------------------------------------------------------------- logs
def initialize(root, year, turn):
    global ROOT, YEAR, TURN
    ROOT, YEAR, TURN = Path(root), year, turn
    engine.DAY = DAYS[(year, turn)]


def process(name):
    path = ROOT / 'logs' / name
    dest = ROOT / 'operational-logs' / (name + '.json')
    if dest.exists():
        try:
            saved = read_json(dest)
            if saved.get('parser_version') == VERSION and saved.get('status') == 'PARSED':
                return 'REUSED'
        except ValueError:
            pass  # truncated by a crash; reparse
    try:
        receipt = read_json(path.with_suffix(path.suffix + '.json'))
        assert sha256(path) == receipt['sha256']
        data = read_log(path)
        identities = parse_count(data)
        try:
            text = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = data.decode('latin1')
        independent = sum(1 for line in text.splitlines() if line.startswith(engine.DAY)
                          and len(f := line.split('\t', 5)) >= 5 and f[3] == 'VOTA' and f[4] == 'O voto do eleitor foi computado')
        metrics = engine.parse(data, day=engine.DAY, allow_named_authorization=YEAR in (2024, 2026), allow_unattributed=YEAR in (2024, 2026))
        assert metrics['vote_events'] == independent
        metrics['worker_authorization_markers'] = metrics.pop('worker_fingerprint_captures')
        write_json(dest, {'status': 'PARSED', 'parser_version': VERSION, 'year': YEAR, 'round': TURN, 'member': name,
                          'source_sha256': receipt['sha256'], 'identity_status': identities['status'],
                          **{k: identities.get(k) for k in ('municipality', 'zone', 'section')}, **metrics})
        return 'PARSED'
    except Exception as exc:
        write_json(dest, {'status': 'FAILED', 'member': name, 'error': str(exc), 'parser_version': VERSION})
        return 'FAILED'


def process_logs(folder, year, turn, workers):
    (folder / 'operational-logs').mkdir(exist_ok=True)
    names = [m['name'] for m in read_json(folder / 'remote-inventory.json')[0]['members']
             if m['name'].lower().endswith(('.logjez', '-log.jez'))]
    done, failures, start = set(), 0, time.monotonic()
    with ProcessPoolExecutor(max_workers=workers, initializer=initialize, initargs=(str(folder), year, turn)) as pool:
        while len(done) < len(names):
            available = [n for n in names if n not in done and (folder / 'logs' / (n + '.json')).exists()]
            if not available:
                if (folder / 'collect.finished').exists():
                    break
                time.sleep(3)
                continue
            for name, status in zip(available, pool.map(process, available, chunksize=8)):
                done.add(name)
                failures += int(status == 'FAILED')
            print({'folder': str(folder), 'processed': len(done), 'expected': len(names), 'failures': failures,
                   'seconds': round(time.monotonic() - start)}, flush=True)
    with (folder / 'operations.jsonl').open('w', encoding='utf-8') as stream, ThreadPoolExecutor(max_workers=8) as pool:
        for record in pool.map(lambda n: read_json(folder / 'operational-logs' / (n + '.json')), names):
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')
    write_json(folder / 'processing-run.json', {'at': utcnow(), 'expected': len(names), 'processed': len(done), 'failures': failures,
                                                'complete_scope': len(done) == len(names) and failures == 0, 'parser_version': VERSION})


# ---------------------------------------------------------------- analysis
def analyze(uf, year, turn, folder):
    out = folder / 'analysis'
    out.mkdir(parents=True, exist_ok=True)
    bu, log = folder / 'bu.parquet', folder / 'operations.jsonl'
    assert read_json(folder / 'processing-run.json')['complete_scope']
    assert read_json(folder / 'log-collection-run.json')['complete_scope']
    d = duckdb.connect()
    d.execute("SET memory_limit='3GB'")
    d.read_parquet(str(bu)).create_view('raw_bu')
    d.execute("CREATE VIEW b AS SELECT * FROM raw_bu WHERE upper(DS_CARGO_PERGUNTA)='PRESIDENTE'")
    assert d.execute('SELECT DISTINCT ANO_ELEICAO,NR_TURNO,SG_UF FROM b').fetchall() == [(str(year), str(turn), uf)]
    nh = 'QT_ELEITORES_BIOMETRIA_NH' if year == 2022 else 'QT_ELEI_BIOM_SEM_HABILITACAO'
    agg = 'DS_AGREGADAS' if year == 2022 else 'DS_SECOES_AGREGADAS'
    d.execute(f'''CREATE TABLE units AS SELECT cast(CD_MUNICIPIO AS INT) municipality,NM_MUNICIPIO municipality_name,
        cast(NR_ZONA AS INT) AS zone,cast(NR_SECAO AS INT) section,max(NR_LOCAL_VOTACAO) voting_place,
        max(cast(QT_APTOS AS BIGINT)) eligible,max(cast(QT_COMPARECIMENTO AS BIGINT)) attendance,
        max(cast(QT_ABSTENCOES AS BIGINT)) absent,max(cast({nh} AS BIGINT)) manual_bu,
        max({agg}) aggregation_raw,max(DT_ABERTURA) opening_bu,max(DT_ENCERRAMENTO) closure_bu,
        count(distinct QT_APTOS)=1 AND count(distinct QT_COMPARECIMENTO)=1 AND count(distinct {nh})=1 consistent_denominators,
        sum(CASE WHEN CD_TIPO_VOTAVEL='1' THEN cast(QT_VOTOS AS BIGINT) ELSE 0 END) valid_votes,
        sum(cast(QT_VOTOS AS BIGINT)) total_votes FROM b GROUP BY ALL''')
    bad = d.execute('SELECT count(*) FROM units WHERE NOT consistent_denominators OR eligible!=attendance+absent OR total_votes!=attendance').fetchone()[0]
    assert bad == 0, f'{bad} units with inconsistent BU totals'
    d.execute('''CREATE TABLE candidate_section AS SELECT cast(CD_MUNICIPIO AS INT) municipality,cast(NR_ZONA AS INT) AS zone,
        cast(NR_SECAO AS INT) section,NR_VOTAVEL candidate_number,NM_VOTAVEL candidate,SG_PARTIDO party,sum(cast(QT_VOTOS AS BIGINT)) votes
        FROM b WHERE CD_TIPO_VOTAVEL='1' GROUP BY ALL''')

    def rows(sql):
        cur = d.execute(sql)
        return [dict(zip([c[0] for c in cur.description], row)) for row in cur.fetchall()]
    totals = rows('''SELECT count(*) bu_units,count(distinct municipality) municipalities,count(distinct zone) zones,
        sum(eligible) eligible,sum(attendance) attendance,sum(absent) absent,sum(valid_votes) valid_votes,
        sum(total_votes-valid_votes) blank_null_votes,sum(manual_bu) manual_bu,100.0*sum(attendance)/sum(eligible) turnout_pct FROM units''')[0]
    candidates = rows('SELECT candidate_number,candidate,party,sum(votes) votes FROM candidate_section GROUP BY ALL ORDER BY votes DESC,candidate_number')
    for row in candidates:
        row['share_pct'] = 100 * row['votes'] / totals['valid_votes']
    totals.update(winner=candidates[0]['candidate'], winner_party=candidates[0]['party'], winner_pct=candidates[0]['share_pct'],
                  margin_pp=candidates[0]['share_pct'] - candidates[1]['share_pct'])
    d.execute('''CREATE TABLE turnout_baseline AS WITH base AS (SELECT *,attendance*1.0/nullif(eligible,0) turnout FROM units),
        median_state AS (SELECT median(turnout) state_median FROM base WHERE eligible>=50),
        mad_state AS (SELECT median(abs(turnout-state_median)) state_mad FROM base CROSS JOIN median_state WHERE eligible>=50),
        municipal AS (SELECT municipality,median(turnout) municipal_median FROM base WHERE eligible>=50 GROUP BY municipality)
        SELECT base.*,state_median,state_mad,municipal_median,
        CASE WHEN eligible>=50 AND state_mad>0 THEN (turnout-state_median)/state_mad>3 AND turnout-municipal_median>=0.1 ELSE NULL END raw_high_turnout
        FROM base CROSS JOIN median_state CROSS JOIN mad_state LEFT JOIN municipal USING(municipality)''')
    d.execute('''CREATE TABLE winners AS WITH ranked AS (SELECT *,row_number() OVER(PARTITION BY municipality,zone,section ORDER BY votes DESC,candidate_number) rank,
        sum(votes) OVER(PARTITION BY municipality,zone,section) AS valid_total,
        lead(votes) OVER(PARTITION BY municipality,zone,section ORDER BY votes DESC,candidate_number) runner_up FROM candidate_section)
        SELECT municipality,zone,section,CASE WHEN votes=runner_up THEN 'EMPATE' ELSE candidate END winner,
        CASE WHEN votes=runner_up THEN 'EMPATE' ELSE party END winner_party,100.0*votes/nullif(valid_total,0) winner_pct,
        100.0*(votes-runner_up)/nullif(valid_total,0) margin_pp FROM ranked WHERE rank=1''')
    result = {'at': utcnow(), 'year': year, 'round': turn, 'uf': uf, 'office': 'PRESIDENTE', 'status': 'DESCRITIVO_EXPLORATORIO_COMPLETO_NO_RECORTE',
              'totals': totals, 'candidates': candidates, 'sources': {'bu': {'path': str(bu), 'sha256': sha256(bu)}},
              'rule_A': 'Raw MAD z>3 AND >=10pp above municipal median, >=50 eligible; exclusions pending',
              'rule_B': 'Recorded-clock late fraction>P99 AND late count>=20; unique identity and reconciled attendance',
              'rule_C': 'No adjusted excess C without mandatory controls; show observed manual quantities only'}
    d.read_json(str(log), format='newline_delimited').create_view('logs')
    d.execute('''CREATE TABLE joined AS SELECT t.*,w.* EXCLUDE(municipality,zone,section),
        l.member,l.identity_status identity_source,l.vote_events,l.after_17_recorded,l.manual_sequence_votes,l.after_17_manual_sequence,l.first_vote,l.last_vote,
        l.clock_reversals,l.malformed_timestamps,l.unclassified_votes,l.conflicting_votes,l.late_interval_median_seconds,
        l.late_interval_sd_seconds,l.votes_1630_1700,
        coalesce(l.identity_status IN ('PARSED','PARSED_FILENAME') AND l.vote_events=t.attendance AND l.vote_events>0 AND l.clock_reversals=0
            AND l.malformed_timestamps=0 AND t.eligible>=50,FALSE) operational_eligible,
        l.after_17_recorded*1.0/nullif(l.vote_events,0) late_share
        FROM turnout_baseline t JOIN winners w USING(municipality,zone,section)
        LEFT JOIN logs l ON t.municipality=l.municipality AND t.zone=l.zone AND t.section=l.section AND l.identity_status IN ('PARSED','PARSED_FILENAME') ''')
    assert d.execute('SELECT count(*) FROM joined').fetchone()[0] == totals['bu_units']
    p99 = d.execute('SELECT quantile_cont(late_share,.99) FROM joined WHERE operational_eligible').fetchone()[0]
    d.execute('CREATE TABLE analysis AS SELECT *,CASE WHEN operational_eligible THEN late_share>? AND after_17_recorded>=20 ELSE NULL END raw_high_late FROM joined', [p99])
    result['late_p99'] = p99
    result['sources']['logs'] = {'path': str(log), 'sha256': sha256(log)}
    result['log_counts'] = rows('''SELECT count(*) files,sum(vote_events) vote_events,sum(after_17_recorded) late_votes,
        sum(manual_sequence_votes) manual_votes,sum(after_17_manual_sequence) late_manual_votes,sum(unclassified_votes) unclassified_votes,
        sum(conflicting_votes) conflicting_votes,count(*) FILTER(WHERE identity_status!='PARSED') ambiguous_files FROM logs''')[0]
    result['coverage'] = rows('''SELECT count(*) units,count(*) FILTER(WHERE member IS NOT NULL) linked,
        count(*) FILTER(WHERE vote_events=attendance) reconciled,
        count(*) FILTER(WHERE member IS NOT NULL AND vote_events!=attendance) log_bu_differences,
        count(*) FILTER(WHERE operational_eligible) operational_eligible,count(*) FILTER(WHERE raw_high_turnout) raw_high_turnout,
        count(*) FILTER(WHERE raw_high_late) raw_high_late,count(*) FILTER(WHERE raw_high_turnout AND raw_high_late) overlap_Araw_Braw,
        count(*) FILTER(WHERE member IS NOT NULL AND manual_sequence_votes=manual_bu) manual_equal_bu,
        count(*) FILTER(WHERE member IS NOT NULL AND manual_sequence_votes!=manual_bu) manual_different_bu FROM analysis''')[0]
    if year == 2026:
        result['unattributed_manual'] = rows('SELECT sum(manual_unattributed_votes) votes,sum(after_17_manual_unattributed) late_votes FROM logs')[0]
    d.execute(f"COPY (SELECT * FROM analysis ORDER BY municipality,zone,section) TO '{(out / 'sections.parquet').as_posix()}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    d.execute(f"COPY (SELECT * FROM candidate_section ORDER BY municipality,zone,section,candidate_number) TO '{(out / 'candidate_sections.parquet').as_posix()}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    result['outputs'] = {p.name: sha256(p) for p in out.iterdir() if p.suffix == '.parquet'}
    write_json(out / 'summary.json', result)
    print(json.dumps({'uf': uf, 'year': year, 'round': turn, 'totals': totals, 'coverage': result['coverage']}, ensure_ascii=True), flush=True)
    d.close()


# ---------------------------------------------------------------- driver
def run_election(uf, year, turn, workers, connections):
    folder = folder_for(uf, year, turn)
    if (folder / 'analysis' / 'summary.json').exists():
        print('SKIP (done)', folder, flush=True)
        return
    prepare(uf, year, turn, folder)
    (folder / 'collect.finished').unlink(missing_ok=True)
    complete = folder / 'log-collection-run.json'
    py = sys.executable
    collector = None
    for attempt in range(4):
        if complete.exists() and read_json(complete).get('complete_scope'):
            break
        complete.unlink(missing_ok=True)
        collector = subprocess.Popen([py, str(SCRIPTS / 'collect_bahia_log_blocks.py'), '--root', str(folder), '--connections', str(connections)],
                                     env={**__import__('os').environ, 'PYTHONPATH': 'src'})
        if attempt == 0:
            # process concurrently with the first collection pass
            watcher = ThreadPoolExecutor(max_workers=1)
            future = watcher.submit(lambda: (collector.wait(), (folder / 'collect.finished').write_text('x')))
            process_logs(folder, year, turn, workers)
            future.result()
        else:
            collector.wait()
        if not (complete.exists() and read_json(complete).get('complete_scope')):
            print('collection incomplete; retrying', folder, flush=True)
    assert read_json(complete)['complete_scope'], 'collection did not complete'
    (folder / 'collect.finished').write_text('x')
    process_logs(folder, year, turn, workers)  # reuse parsed files, pick up stragglers
    analyze(uf, year, turn, folder)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--uf', required=True)
    parser.add_argument('--elections', default='2022-1,2022-2,2026-1')
    parser.add_argument('--workers', type=int, default=5)
    parser.add_argument('--connections', type=int, default=6)
    a = parser.parse_args()
    failed = []
    for e in a.elections.split(','):
        y, t = map(int, e.split('-'))
        try:
            run_election(a.uf.upper(), y, t, a.workers, a.connections)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            failed.append((e, repr(exc)))
    print('UF DONE', a.uf, 'FAILED:', failed, flush=True)
    sys.exit(1 if failed else 0)
