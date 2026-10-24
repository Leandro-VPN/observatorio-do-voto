"""Independent pandas checks of the DuckDB operational aggregation."""
import json
from pathlib import Path

import pandas as pd

from auditabr.logs import read_log
from auditabr.utils import read_json, sha256, utcnow, write_json

root = Path('research/piloto-ba-2022-t2')
out = root / 'analysis'
summary = read_json(out/'summary.json')
for filename, expected in summary['outputs'].items():
    assert sha256(out/filename) == expected
plan = read_json(Path('research/plano-v1-registro.json'))
assert sha256(Path('research/PLANO_ANALISE_A_PRIORI.md')) == plan['sha256'] == summary['plan_sha256']
sections = pd.read_parquet(out/'sections.parquet')
assert len(sections) == 68848
assert not sections.duplicated(['municipality','zone','section','office']).any()
president = sections[sections.office=='Presidente']
eligible = president[president.raw_operational_eligible]
threshold = eligible.late_share_recorded.quantile(.99, interpolation='linear')
assert abs(threshold-summary['raw_late_p99']) < 1e-12
selected = eligible[(eligible.late_share_recorded>threshold)&(eligible.after_17_recorded>=20)]
assert set(selected.member) == set(president[president.raw_high_late.fillna(False)].member)
previous_events = sum(json.loads(line)['vote_events'] for line in (root/'parsed-log-index.jsonl').read_text(encoding='utf-8').splitlines())
assert previous_events == summary['log_totals']['vote_events']
case_checks = []
for row in selected.itertuples():
    data = read_log(root/'logs'/row.member)
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = data.decode('latin1')
    count = 0
    for line in text.splitlines():
        fields = line.split('\t')
        if len(fields)>=5 and fields[0].startswith('30/10/2022 ') and fields[3]=='VOTA':
            count += int(fields[4]=='O voto do eleitor foi computado' and fields[0][11:]>'17:00:00')
    assert count == row.after_17_recorded
    case_checks.append({'member':row.member,'independent_late_events':count,
                        'manual_equals_bu':bool(row.manual_sequence_votes==row.biometric_nh_bu)})
write_json(out/'validation.json', {
    'at':utcnow(),'status':'PASS','script_sha256':sha256(Path(__file__)),
    'checks':['Output hashes','Frozen plan unchanged','Unique 68848 section-office rows',
              'Independent pandas quantile and group membership','Vote counts equal prior parser',
              'Independent raw vote timestamps in highlighted cases'],
    'cases':case_checks,'limits':'These checks validate implementation, not missing controls, clock accuracy or electoral regularity.'})
readiness = read_json(root/'readiness.json')
readiness['at'] = utcnow()
readiness['observed'].update({'operational_logs_processed':34424,'log_sections':33084,'governor_rows':34424})
readiness['operational_results'] = 'analysis/summary.json'
readiness['operational_status'] = 'EXPLORATORY_COMPLETE_BA2022T2; historical/adjusted study incomplete'
readiness['manual_bu_reconciliation'] = summary['manual_bu_validation']
readiness['indicators_status']['C'] = 'OBSERVED_SEQUENCE_IMPLEMENTED; ACTIVE_BIOMETRY_AND_CONTROLS_PENDING'
write_json(root/'readiness.json', readiness)
print('PASS: hashes, frozen plan, rows, threshold, cohort, total events and highlighted raw timestamps')
