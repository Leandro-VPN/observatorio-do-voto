"""Presidential BA 2022/2026 document datasets; no UI or causal claims."""
import argparse
import json
from pathlib import Path
import shutil

import duckdb

from auditabr.utils import read_json, sha256, utcnow, write_json

ROOT=Path('research/bahia-presidente-2022-2026')
PILOT=Path('research/piloto-ba-2022-t2')


def analyze(year,turn,apuration_only=False):
    folder=ROOT/f'{year}-t{turn}';out=folder/'analysis';out.mkdir(parents=True,exist_ok=True)
    bu=PILOT/'captures/bweb_2t_BA_311020221535.parquet' if (year,turn)==(2022,2) else folder/'bu.parquet'
    log=PILOT/'analysis/operations.jsonl' if (year,turn)==(2022,2) else folder/'operations.jsonl'
    if not apuration_only and turn==1:
        assert read_json(folder/'processing-run.json')['complete_scope']
        assert read_json(folder/'log-collection-run.json')['complete_scope']
    d=duckdb.connect();d.execute("SET memory_limit='768MB'")
    d.read_parquet(str(bu)).create_view('raw_bu')
    d.execute("CREATE VIEW b AS SELECT * FROM raw_bu WHERE upper(DS_CARGO_PERGUNTA)='PRESIDENTE'")
    assert d.execute('SELECT DISTINCT ANO_ELEICAO,NR_TURNO,SG_UF FROM b').fetchall()==[(str(year),str(turn),'BA')]
    nh='QT_ELEITORES_BIOMETRIA_NH' if year==2022 else 'QT_ELEI_BIOM_SEM_HABILITACAO'
    agg='DS_AGREGADAS' if year==2022 else 'DS_SECOES_AGREGADAS'
    d.execute(f'''CREATE TABLE units AS SELECT cast(CD_MUNICIPIO AS INT) municipality,NM_MUNICIPIO municipality_name,
        cast(NR_ZONA AS INT) AS zone,cast(NR_SECAO AS INT) section,max(NR_LOCAL_VOTACAO) voting_place,
        max(cast(QT_APTOS AS BIGINT)) eligible,max(cast(QT_COMPARECIMENTO AS BIGINT)) attendance,
        max(cast(QT_ABSTENCOES AS BIGINT)) absent,max(cast({nh} AS BIGINT)) manual_bu,
        max({agg}) aggregation_raw,max(DT_ABERTURA) opening_bu,max(DT_ENCERRAMENTO) closure_bu,
        count(distinct QT_APTOS)=1 AND count(distinct QT_COMPARECIMENTO)=1
          AND count(distinct {nh})=1 consistent_denominators,
        sum(CASE WHEN CD_TIPO_VOTAVEL='1' THEN cast(QT_VOTOS AS BIGINT) ELSE 0 END) valid_votes,
        sum(cast(QT_VOTOS AS BIGINT)) total_votes
        FROM b GROUP BY ALL''')
    assert d.execute('SELECT count(*) FROM units WHERE NOT consistent_denominators OR eligible!=attendance+absent OR total_votes!=attendance').fetchone()[0]==0
    d.execute('''CREATE TABLE candidate_section AS SELECT cast(CD_MUNICIPIO AS INT) municipality,
        cast(NR_ZONA AS INT) AS zone,cast(NR_SECAO AS INT) section,NR_VOTAVEL candidate_number,
        NM_VOTAVEL candidate,SG_PARTIDO party,sum(cast(QT_VOTOS AS BIGINT)) votes
        FROM b WHERE CD_TIPO_VOTAVEL='1' GROUP BY ALL''')
    def rows(sql):
        cur=d.execute(sql);return [dict(zip([c[0] for c in cur.description],row)) for row in cur.fetchall()]
    totals=rows('''SELECT count(*) bu_units,count(distinct municipality) municipalities,count(distinct zone) zones,
        sum(eligible) eligible,sum(attendance) attendance,sum(absent) absent,sum(valid_votes) valid_votes,
        sum(total_votes-valid_votes) blank_null_votes,sum(manual_bu) manual_bu,
        100.0*sum(attendance)/sum(eligible) turnout_pct FROM units''')[0]
    candidates=rows('SELECT candidate_number,candidate,party,sum(votes) votes FROM candidate_section GROUP BY ALL ORDER BY votes DESC,candidate_number')
    for row in candidates:row['share_pct']=100*row['votes']/totals['valid_votes']
    totals['winner']=candidates[0]['candidate'];totals['winner_party']=candidates[0]['party']
    totals['winner_pct']=candidates[0]['share_pct'];totals['margin_pp']=candidates[0]['share_pct']-candidates[1]['share_pct']
    d.execute('''CREATE TABLE turnout_baseline AS WITH base AS (
        SELECT *,attendance*1.0/nullif(eligible,0) turnout FROM units),
        median_state AS (SELECT median(turnout) state_median FROM base WHERE eligible>=50),
        mad_state AS (SELECT median(abs(turnout-state_median)) state_mad FROM base CROSS JOIN median_state WHERE eligible>=50),
        municipal AS (SELECT municipality,median(turnout) municipal_median FROM base WHERE eligible>=50 GROUP BY municipality)
        SELECT base.*,state_median,state_mad,municipal_median,
        CASE WHEN eligible>=50 AND state_mad>0 THEN (turnout-state_median)/state_mad>3
            AND turnout-municipal_median>=0.1 ELSE NULL END raw_high_turnout
        FROM base CROSS JOIN median_state CROSS JOIN mad_state LEFT JOIN municipal USING(municipality)''')
    d.execute('''CREATE TABLE winners AS WITH ranked AS (
        SELECT *,row_number() OVER(PARTITION BY municipality,zone,section ORDER BY votes DESC,candidate_number) rank,
        sum(votes) OVER(PARTITION BY municipality,zone,section) AS valid_total,
        lead(votes) OVER(PARTITION BY municipality,zone,section ORDER BY votes DESC,candidate_number) runner_up
        FROM candidate_section)
        SELECT municipality,zone,section,CASE WHEN votes=runner_up THEN 'EMPATE' ELSE candidate END winner,
        CASE WHEN votes=runner_up THEN 'EMPATE' ELSE party END winner_party,
        100.0*votes/nullif(valid_total,0) winner_pct,100.0*(votes-runner_up)/nullif(valid_total,0) margin_pp
        FROM ranked WHERE rank=1''')
    result={'at':utcnow(),'year':year,'round':turn,'uf':'BA','office':'PRESIDENTE',
        'status':'APURACAO_COMPLETA_LOGS_PENDENTES' if apuration_only else 'DESCRITIVO_EXPLORATORIO_COMPLETO_NO_RECORTE',
        'totals':totals,'candidates':candidates,'sources':{'bu':{'path':str(bu),'sha256':sha256(bu)}},
        'rule_A':'Raw MAD z>3 AND >=10pp above municipal median, >=50 eligible; exclusions pending',
        'rule_B':'Recorded-clock late fraction>P99 AND late count>=20; unique identity and reconciled attendance; exclusions/clock certification pending',
        'rule_C':'No adjusted excess C without mandatory controls; show observed manual quantities only',
        'manual_definition':'Voters with enrolled biometrics who were not habilitated by them (BU); complete observed manual session (log), not all worker authorizations',
        'limits':['No individual vote linked to a log session','No confirmed A/B/C/D or causal/party-favouring claim',
                  'Same geography key across years does not establish stable physical section','Clock values are recorded, not independently calibrated',
                  'Special/transit/aggregate exclusions and full demographic/operational controls remain pending']}
    if not apuration_only:
        d.read_json(str(log),format='newline_delimited').create_view('logs')
        d.execute('''CREATE TABLE joined AS SELECT t.*,w.* EXCLUDE(municipality,zone,section),
            l.member,l.identity_status identity_source,l.vote_events,l.after_17_recorded,l.manual_sequence_votes,l.after_17_manual_sequence,
            l.first_vote,l.last_vote,l.clock_reversals,l.malformed_timestamps,l.unclassified_votes,l.conflicting_votes,
            l.late_interval_median_seconds,l.late_interval_sd_seconds,l.votes_1630_1700,
            coalesce(l.identity_status IN ('PARSED','PARSED_FILENAME') AND l.vote_events=t.attendance AND l.vote_events>0
                AND l.clock_reversals=0 AND l.malformed_timestamps=0 AND t.eligible>=50,FALSE) operational_eligible,
            l.after_17_recorded*1.0/nullif(l.vote_events,0) late_share
            FROM turnout_baseline t JOIN winners w USING(municipality,zone,section)
            LEFT JOIN logs l ON t.municipality=l.municipality AND t.zone=l.zone AND t.section=l.section
                AND l.identity_status IN ('PARSED','PARSED_FILENAME') ''')
        assert d.execute('SELECT count(*) FROM joined').fetchone()[0]==totals['bu_units']
        p99=d.execute('SELECT quantile_cont(late_share,.99) FROM joined WHERE operational_eligible').fetchone()[0]
        d.execute('CREATE TABLE analysis AS SELECT *,CASE WHEN operational_eligible THEN late_share>? AND after_17_recorded>=20 ELSE NULL END raw_high_late FROM joined',[p99])
        result['late_p99']=p99
        result['sources']['logs']={'path':str(log),'sha256':sha256(log)}
        result['log_counts']=rows('''SELECT count(*) files,sum(vote_events) vote_events,sum(after_17_recorded) late_votes,
            sum(manual_sequence_votes) manual_votes,sum(after_17_manual_sequence) late_manual_votes,
            sum(unclassified_votes) unclassified_votes,sum(conflicting_votes) conflicting_votes,
            count(*) FILTER(WHERE identity_status!='PARSED') ambiguous_files FROM logs''')[0]
        result['coverage']=rows('''SELECT count(*) units,count(*) FILTER(WHERE member IS NOT NULL) linked,
            count(*) FILTER(WHERE vote_events=attendance) reconciled,
            count(*) FILTER(WHERE member IS NOT NULL AND vote_events!=attendance) log_bu_differences,
            count(*) FILTER(WHERE operational_eligible) operational_eligible,
            count(*) FILTER(WHERE raw_high_turnout) raw_high_turnout,
            count(*) FILTER(WHERE raw_high_late) raw_high_late,
            count(*) FILTER(WHERE raw_high_turnout AND raw_high_late) overlap_Araw_Braw,
            count(*) FILTER(WHERE member IS NOT NULL AND manual_sequence_votes=manual_bu) manual_equal_bu,
            count(*) FILTER(WHERE member IS NOT NULL AND manual_sequence_votes!=manual_bu) manual_different_bu
            FROM analysis''')[0]
        for label,condition in [('high_late','raw_high_late'),('high_turnout','raw_high_turnout')]:
            result[label]=rows(f'''SELECT count(*) sections,count(distinct municipality) municipalities,count(distinct zone) zones,
                sum(after_17_recorded) late_votes,sum(after_17_manual_sequence) late_manual_votes,
                count(*) FILTER(WHERE after_17_manual_sequence>0) sections_with_late_manual,
                sum(valid_votes) valid_votes,sum(eligible) eligible,sum(attendance) attendance
                FROM analysis WHERE {condition}''')[0]
            result[label+'_candidates']=rows(f'''SELECT candidate,party,sum(votes) votes FROM candidate_section
                JOIN analysis USING(municipality,zone,section) WHERE {condition} GROUP BY ALL ORDER BY votes DESC,candidate''')
            for row in result[label+'_candidates']:
                row['share_pct']=100*row['votes']/result[label]['valid_votes'] if result[label]['valid_votes'] else None
            d.execute(f"COPY (SELECT * FROM analysis WHERE {condition} ORDER BY municipality,zone,section) TO '{(out/(label+'_sections.csv')).as_posix()}' (HEADER,DELIMITER ';')")
        result['high_late_examples']=rows('''SELECT municipality_name,zone,section,eligible,attendance,after_17_recorded,
            after_17_manual_sequence,manual_sequence_votes,manual_bu,cast(last_vote AS VARCHAR) last_vote,
            late_interval_median_seconds,late_interval_sd_seconds,winner,winner_party,winner_pct,margin_pp
            FROM analysis WHERE raw_high_late ORDER BY after_17_recorded DESC,municipality,zone,section LIMIT 12''')
        result['low_abstention_examples']=rows('''SELECT municipality_name,zone,section,eligible,attendance,
            100*turnout turnout_pct,100*municipal_median municipal_median_pct,winner,winner_party
            FROM analysis WHERE raw_high_turnout ORDER BY turnout DESC,municipality,zone,section LIMIT 10''')
        if year==2026:
            result['unattributed_manual']=rows('SELECT sum(manual_unattributed_votes) votes,sum(after_17_manual_unattributed) late_votes FROM logs')[0]
        for level,keys in [('cities','municipality,municipality_name'),('zones','zone'),('city_zones','municipality,municipality_name,zone')]:
            query=f'''SELECT {keys},count(*) sections,sum(eligible) eligible,sum(attendance) attendance,
                100.0*sum(attendance)/sum(eligible) turnout_pct,sum(manual_bu) manual_bu,
                count(*) FILTER(WHERE raw_high_turnout) raw_high_turnout,
                count(*) FILTER(WHERE raw_high_late) raw_high_late,
                sum(after_17_recorded) linked_late_votes,sum(after_17_manual_sequence) linked_late_manual_votes,
                sum(after_17_recorded) FILTER(WHERE raw_high_late) high_late_votes,
                sum(after_17_manual_sequence) FILTER(WHERE raw_high_late) high_late_manual_votes
                FROM analysis GROUP BY ALL ORDER BY raw_high_late DESC,high_late_votes DESC,{keys}'''
            d.execute(f"COPY ({query}) TO '{(out/(level+'.csv')).as_posix()}' (HEADER,DELIMITER ';')")
            if level=='cities':result['top_cities']=rows(f'SELECT * FROM ({query}) WHERE raw_high_late>0 LIMIT 12')
    else:
        d.execute('CREATE TABLE analysis AS SELECT t.*,w.* EXCLUDE(municipality,zone,section) FROM turnout_baseline t JOIN winners w USING(municipality,zone,section)')
    d.execute(f"COPY (SELECT * FROM analysis ORDER BY municipality,zone,section) TO '{(out/'sections.parquet').as_posix()}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    d.execute(f"COPY (SELECT * FROM candidate_section ORDER BY municipality,zone,section,candidate_number) TO '{(out/'candidate_sections.parquet').as_posix()}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    result['outputs']={p.name:sha256(p) for p in out.iterdir() if p.suffix in ('.parquet','.csv')}
    result['script_sha256']=sha256(Path(__file__))
    write_json(out/'summary.json',result)
    print(json.dumps({'year':year,'round':turn,'totals':totals,'coverage':result.get('coverage')},ensure_ascii=True),flush=True)
    d.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apuration-only',action='store_true');args=parser.parse_args()
    for year,turn in [(2022,1),(2022,2),(2026,1)]:analyze(year,turn,args.apuration_only)
