"""Office-level section analysis (same method as the presidential study) for any year/turn/office, with or without urn logs.

Output: research/analysis/<OFFICE>/<UF>/<year>-t<turn>/{sections.parquet,candidate_sections.parquet,summary.json}
Section columns match the presidential `analysis/sections.parquet`; log-derived columns are NULL when no log exists (2014, 2018).
"""
import argparse
import json
import sys
from pathlib import Path

import duckdb

from auditabr.utils import read_json, sha256, utcnow, write_json

UFS = ['BA', 'SP', 'MG', 'RJ', 'PR', 'RS', 'PE', 'CE', 'PA', 'SC']
ELECTIONS = [(2014, 1), (2014, 2), (2018, 1), (2018, 2), (2022, 1), (2022, 2), (2026, 1)]
MUN_ELECTIONS = [(2012, 1), (2012, 2), (2016, 1), (2016, 2), (2020, 1), (2020, 2), (2024, 1), (2024, 2)]


def bu_path(uf, year, turn, office):
    return Path('research/bu') / f'{year}-t{turn}' / f'{uf}_{office}.parquet'


def ops_path(uf, year, turn):
    if year == 2024:
        return Path('research/municipais') / uf / f'{year}-t{turn}' / 'operations.jsonl'
    if year not in (2022, 2026):
        return None
    if uf == 'BA':
        if (year, turn) == (2022, 2):
            return Path('research/piloto-ba-2022-t2/analysis/operations.jsonl')
        return Path('research/bahia-presidente-2022-2026') / f'{year}-t{turn}' / 'operations.jsonl'
    return Path('research/estados') / uf / f'{year}-t{turn}' / 'operations.jsonl'


def out_dir(uf, year, turn, office):
    return Path('research/analysis') / office / uf / f'{year}-t{turn}'


def analyze(uf, year, turn, office):
    bu = bu_path(uf, year, turn, office)
    if not bu.exists():
        return 'NO_BU'
    out = out_dir(uf, year, turn, office)
    if (out / 'summary.json').exists():
        return 'SKIP'
    out.mkdir(parents=True, exist_ok=True)
    log = ops_path(uf, year, turn)
    d = duckdb.connect()
    d.execute("SET memory_limit='3GB'")
    if (year, turn) == (2012, 2):   # this BU file lists every votable row twice; drop exact duplicates
        d.read_parquet(str(bu)).create_view('b_raw')
        d.execute('CREATE TABLE b AS SELECT DISTINCT * FROM b_raw')
    else:
        d.read_parquet(str(bu)).create_view('b')
    cols = {r[0] for r in d.execute('DESCRIBE b').fetchall()}
    nh = next((c for c in ('QT_ELEITORES_BIOMETRIA_NH', 'QT_ELEI_BIOM_SEM_HABILITACAO') if c in cols), None)
    agg = next((c for c in ('DS_AGREGADAS', 'DS_SECOES_AGREGADAS') if c in cols), None)
    sel_nh = f'max(try_cast({nh} AS BIGINT))' if nh else 'CAST(NULL AS BIGINT)'
    sel_agg = f'max({agg})' if agg else 'CAST(NULL AS VARCHAR)'
    sel_open = 'max(DT_ABERTURA)' if 'DT_ABERTURA' in cols else 'CAST(NULL AS VARCHAR)'
    sel_close = 'max(DT_ENCERRAMENTO)' if 'DT_ENCERRAMENTO' in cols else 'CAST(NULL AS VARCHAR)'
    chk = [r for r in d.execute(f'SELECT DISTINCT ANO_ELEICAO,NR_TURNO,SG_UF FROM b').fetchall()] if 'ANO_ELEICAO' in cols else [(str(year), str(turn), uf)]
    assert chk == [(str(year), str(turn), uf)], chk
    d.execute(f'''CREATE TABLE units AS SELECT cast(CD_MUNICIPIO AS INT) municipality,NM_MUNICIPIO municipality_name,
        cast(NR_ZONA AS INT) AS zone,cast(NR_SECAO AS INT) section,max(NR_LOCAL_VOTACAO) voting_place,
        max(cast(QT_APTOS AS BIGINT)) eligible,max(cast(QT_COMPARECIMENTO AS BIGINT)) attendance,
        max(cast(QT_ABSTENCOES AS BIGINT)) absent,{sel_nh} manual_bu,{sel_agg} aggregation_raw,{sel_open} opening_bu,{sel_close} closure_bu,
        count(distinct QT_APTOS)=1 AND count(distinct QT_COMPARECIMENTO)=1 consistent_denominators,
        sum(CASE WHEN CD_TIPO_VOTAVEL='1' THEN cast(QT_VOTOS AS BIGINT) ELSE 0 END) valid_votes,
        sum(cast(QT_VOTOS AS BIGINT)) total_votes FROM b GROUP BY ALL''')
    d.execute('''CREATE TABLE units2 AS SELECT *,eligible=attendance+absent AND total_votes=attendance AND consistent_denominators bu_consistent,
        coalesce(try_strptime(closure_bu,'%d/%m/%Y %H:%M:%S'),try_strptime(closure_bu,'%Y-%m-%d %H:%M:%S')) closure_ts,
        coalesce(try_strptime(opening_bu,'%d/%m/%Y %H:%M:%S'),try_strptime(opening_bu,'%Y-%m-%d %H:%M:%S')) opening_ts FROM units''')
    d.execute('''CREATE TABLE units3 AS SELECT * EXCLUDE(closure_ts,opening_ts),
        date_part('hour',closure_ts)*60+date_part('minute',closure_ts)+date_part('second',closure_ts)/60.0-1020 closing_min_after17,
        date_part('hour',opening_ts)*60+date_part('minute',opening_ts)+date_part('second',opening_ts)/60.0-480 opening_min_after8 FROM units2''')
    d.execute('''CREATE TABLE candidate_section AS SELECT cast(CD_MUNICIPIO AS INT) municipality,cast(NR_ZONA AS INT) AS zone,
        cast(NR_SECAO AS INT) section,NR_VOTAVEL candidate_number,NM_VOTAVEL candidate,SG_PARTIDO party,sum(cast(QT_VOTOS AS BIGINT)) votes
        FROM b WHERE CD_TIPO_VOTAVEL='1' GROUP BY ALL''')

    def rows(sql):
        cur = d.execute(sql)
        return [dict(zip([c[0] for c in cur.description], row)) for row in cur.fetchall()]
    totals = rows('''SELECT count(*) bu_units,count(distinct municipality) municipalities,count(distinct zone) zones,sum(eligible) eligible,
        sum(attendance) attendance,sum(absent) absent,sum(valid_votes) valid_votes,sum(total_votes-valid_votes) blank_null_votes,
        sum(manual_bu) manual_bu,100.0*sum(attendance)/sum(eligible) turnout_pct,count(*) FILTER(WHERE NOT bu_consistent) inconsistent_units FROM units3''')[0]
    candidates = rows('SELECT candidate_number,candidate,party,sum(votes) votes FROM candidate_section GROUP BY ALL ORDER BY votes DESC,candidate_number')
    for r in candidates:
        r['share_pct'] = 100 * r['votes'] / totals['valid_votes']
    totals.update(winner=candidates[0]['candidate'], winner_party=candidates[0]['party'], winner_pct=candidates[0]['share_pct'],
                  margin_pp=candidates[0]['share_pct'] - candidates[1]['share_pct'] if len(candidates) > 1 else None)
    d.execute('''CREATE TABLE turnout_baseline AS WITH base AS (SELECT *,attendance*1.0/nullif(eligible,0) turnout FROM units3),
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
    result = {'at': utcnow(), 'year': year, 'round': turn, 'uf': uf, 'office': office, 'has_logs': bool(log and log.exists()),
              'totals': totals, 'candidates': candidates, 'sources': {'bu': {'path': str(bu), 'sha256': sha256(bu)}}}
    if log and log.exists():
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
    else:
        d.execute('''CREATE TABLE analysis AS SELECT t.*,w.* EXCLUDE(municipality,zone,section),
            CAST(NULL AS VARCHAR) member,CAST(NULL AS BIGINT) vote_events,CAST(NULL AS BIGINT) after_17_recorded,CAST(NULL AS BIGINT) manual_sequence_votes,
            CAST(NULL AS BIGINT) after_17_manual_sequence,CAST(NULL AS VARCHAR) first_vote,CAST(NULL AS VARCHAR) last_vote,
            FALSE operational_eligible,CAST(NULL AS DOUBLE) late_share,CAST(NULL AS BOOLEAN) raw_high_late
            FROM turnout_baseline t JOIN winners w USING(municipality,zone,section)''')
        result['coverage'] = rows('SELECT count(*) units,count(*) FILTER(WHERE raw_high_turnout) raw_high_turnout FROM analysis')[0]
    d.execute(f"COPY (SELECT * FROM analysis ORDER BY municipality,zone,section) TO '{(out / 'sections.parquet').as_posix()}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    d.execute(f"COPY (SELECT * FROM candidate_section ORDER BY municipality,zone,section,candidate_number) TO '{(out / 'candidate_sections.parquet').as_posix()}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    write_json(out / 'summary.json', result)
    d.close()
    return f"OK units={totals['bu_units']} inconsistent={totals['inconsistent_units']} winner={totals['winner_party']} {totals['winner_pct']:.1f}%"


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--offices', default='GOVERNADOR,PRESIDENTE')
    p.add_argument('--only-missing', action='store_true')
    p.add_argument('--years', default='')
    a = p.parse_args()
    for office in a.offices.split(','):
        for year, turn in (MUN_ELECTIONS if office == 'PREFEITO' else ELECTIONS):
            if office == 'PRESIDENTE' and year in (2022, 2026):
                continue   # existing presidential analyses
            if a.years and str(year) not in a.years.split(','):
                continue
            for uf in UFS:
                try:
                    print(office, year, turn, uf, analyze(uf, year, turn, office), flush=True)
                except Exception as exc:
                    import traceback
                    traceback.print_exc()
                    print(office, year, turn, uf, 'FAILED', repr(exc), flush=True)
