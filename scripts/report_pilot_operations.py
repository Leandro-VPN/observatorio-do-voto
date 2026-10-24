"""Territorial operational results. Raw-clock cohorts are explicitly exploratory."""
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import duckdb
import pandas as pd
import numpy as np

from auditabr.utils import sha256, utcnow, write_json

ROOT = Path('research/piloto-ba-2022-t2')
OUT = ROOT / 'analysis'


def compact_record(path):
    return json.dumps(json.loads(path.read_text(encoding='utf-8')), ensure_ascii=False) + '\n'


def main():
    OUT.mkdir(exist_ok=True)
    run = json.loads((ROOT / 'operational-run.json').read_text(encoding='utf-8'))
    assert run['selected'] == 34424 and run['counts'] == {'PARSED': 34424}, run
    compact = OUT / 'operations.jsonl'
    with compact.open('w', encoding='utf-8') as stream, ThreadPoolExecutor(max_workers=8) as pool:
        for i, line in enumerate(pool.map(compact_record, sorted((ROOT / 'operational-logs').glob('*.json'))), 1):
            stream.write(line)
            if i % 5000 == 0:
                print(f'Consolidated {i}/34424 logs', flush=True)
    db = duckdb.connect()
    db.execute("SET memory_limit='512MB'")
    db.read_json(str(compact), format='newline_delimited').create_view('logs')
    assert db.execute('SELECT count(*),sum(vote_events) FROM logs').fetchone() == (34424, 8941487)
    assert db.execute('''SELECT count(*) FROM logs WHERE after_17_manual_sequence>after_17_recorded
      OR after_17_manual_sequence>manual_sequence_votes OR after_17_recorded>vote_events''').fetchone()[0] == 0
    db.read_parquet(str(ROOT / 'captures/bweb_2t_BA_311020221535.parquet')).create_view('bu')
    correspondence = pd.read_csv(ROOT / 'support/ceft_2t_BA_311020221100.csv', sep=';', encoding='latin1', dtype=str)
    db.register('correspondence', correspondence)

    def rows(sql):
        cur = db.execute(sql)
        return [dict(zip([x[0] for x in cur.description], row)) for row in cur.fetchall()]

    db.execute('''CREATE TEMP TABLE sections AS
      WITH b AS (SELECT cast(CD_MUNICIPIO AS INTEGER) municipality,NM_MUNICIPIO municipality_name,
          cast(NR_ZONA AS INTEGER) AS zone,cast(NR_SECAO AS INTEGER) section,
          DS_CARGO_PERGUNTA office,max(cast(QT_APTOS AS BIGINT)) eligible,
          max(cast(QT_COMPARECIMENTO AS BIGINT)) attendance,
          max(cast(QT_ABSTENCOES AS BIGINT)) absent,max(DS_AGREGADAS) aggregated_raw,
          max(cast(QT_ELEITORES_BIOMETRIA_NH AS BIGINT)) biometric_nh_bu,
          max(DT_ABERTURA) opening_bu,max(DT_ENCERRAMENTO) closure_bu,
          sum(CASE WHEN CD_TIPO_VOTAVEL='1' THEN cast(QT_VOTOS AS BIGINT) ELSE 0 END) valid_votes,
          sum(CASE WHEN CD_TIPO_VOTAVEL='1' AND SG_PARTIDO='PT' THEN cast(QT_VOTOS AS BIGINT) ELSE 0 END) pt_votes,
          sum(CASE WHEN CD_TIPO_VOTAVEL='1' AND SG_PARTIDO!='PT' THEN cast(QT_VOTOS AS BIGINT) ELSE 0 END) other_votes
        FROM bu GROUP BY ALL)
      SELECT b.*,l.* EXCLUDE(municipality,zone,section),
        b.attendance*1.0/nullif(b.eligible,0) turnout,
        l.vote_events=b.attendance reconciled_this_office,
        l.after_17_recorded*1.0/nullif(l.vote_events,0) late_share_recorded,
        l.manual_sequence_votes*1.0/nullif(l.vote_events,0) manual_share_observed
      FROM b LEFT JOIN logs l ON b.municipality=l.municipality AND b.zone=l.zone
        AND b.section=l.section AND l.identity_status='PARSED' ''')
    assert db.execute('SELECT count(*) FROM sections').fetchone()[0] == 68848
    db.execute('''CREATE TEMP TABLE operations_context AS
      SELECT cast(CD_MUNICIPIO AS INTEGER) municipality,cast(NR_ZONA AS INTEGER) AS zone,
        cast(NR_SECAO AS INTEGER) section,max(DS_DIVERGENCIA) divergence_raw,
        bool_or(NR_URNA_ESPERADA!=NR_URNA_EFETIVADA) expected_actual_urn_differ,
        bool_or(DS_DIVERGENCIA='**') contingency_documented,
        max(DS_ORIGEM_VOTO) vote_origin
      FROM correspondence GROUP BY ALL''')
    # Operational eligibility is based on the full voting session (presidential attendance),
    # not the governor denominator, which can legitimately differ.
    db.execute('''CREATE TEMP TABLE pres_quality AS
      SELECT municipality,zone,section,
        coalesce(reconciled_this_office AND clock_reversals=0 AND malformed_timestamps=0
                 AND vote_events>0 AND eligible>=50,FALSE) raw_operational_eligible
      FROM sections WHERE office='Presidente' ''')
    db.execute('''CREATE TEMP TABLE thresholds AS
      SELECT quantile_cont(late_share_recorded,0.99) late_p99
      FROM sections JOIN pres_quality USING(municipality,zone,section)
      WHERE office='Presidente' AND raw_operational_eligible''')
    db.execute('''CREATE TEMP TABLE turnout_reference AS
      WITH m AS (SELECT office,median(turnout) state_median FROM sections WHERE eligible>=50 GROUP BY office)
      SELECT office,state_median,median(abs(turnout-state_median)) state_mad
      FROM sections JOIN m USING(office) WHERE eligible>=50 GROUP BY ALL''')
    db.execute('''CREATE TEMP TABLE analysis AS
      WITH municipal AS (SELECT office,municipality,median(turnout) municipal_median
        FROM sections WHERE eligible>=50 GROUP BY ALL)
      SELECT s.*,o.* EXCLUDE(municipality,zone,section),
        q.raw_operational_eligible,t.late_p99,r.state_median,r.state_mad,m.municipal_median,
        CASE WHEN eligible>=50 AND state_mad>0 THEN
          (turnout-state_median)/state_mad>3 AND turnout-municipal_median>=0.1 ELSE NULL END
          raw_high_turnout,
        CASE WHEN raw_operational_eligible THEN late_share_recorded>late_p99 AND after_17_recorded>=20
          ELSE NULL END raw_high_late,
        'EXPLORATORIO_RELOGIO_REGISTRADO_EXCLUSOES_PENDENTES' analysis_status
      FROM sections s JOIN pres_quality q USING(municipality,zone,section)
      JOIN turnout_reference r USING(office) JOIN municipal m USING(office,municipality)
      LEFT JOIN operations_context o USING(municipality,zone,section)
      CROSS JOIN thresholds t''')
    summary = {'at': utcnow(), 'status': 'EXPLORATORY_NOT_CONFIRMATORY_A_B_C_D',
               'scope': 'BA/2022/T2; president and governor',
               'plan_sha256': sha256(Path('research/PLANO_ANALISE_A_PRIORI.md')),
               'script_sha256': sha256(Path(__file__)), 'parser': run,
               'raw_late_p99': rows('SELECT * FROM thresholds')[0]['late_p99'],
               'log_totals': rows('''SELECT count(*) files,sum(vote_events) vote_events,
                 sum(after_17_recorded) after_17_recorded,sum(manual_sequence_votes) manual_sequence_votes,
                 sum(after_17_manual_sequence) after_17_manual_sequence,
                 sum(biometric_votes) biometric_votes,sum(no_enrollment_votes) no_enrollment_votes,
                 sum(unclassified_votes) unclassified_votes,sum(conflicting_votes) conflicting_votes,
                 count(*) FILTER(WHERE clock_reversals>0) files_with_clock_reversal,
                 count(*) FILTER(WHERE identity_status!='PARSED') ambiguous_identity_files FROM logs''')[0],
               'turnout_reference': rows('SELECT * FROM turnout_reference'),
               'full_state_results': json.loads((ROOT/'baseline/manifest.json').read_text(encoding='utf-8'))['state_results'],
               'national_reference': json.loads((ROOT/'national-reference.json').read_text(encoding='utf-8')),
               'sources': {str(p.relative_to(ROOT)):sha256(p) for p in [
                   ROOT/'captures/bweb_2t_BA_311020221535.parquet',
                   ROOT/'support/ceft_2t_BA_311020221100.csv',
                   ROOT/'support/leiame-boletimurnaweb.pdf',ROOT/'support/leiame-corresp-efetivada.pdf']},
               'manual_bu_validation': rows('''SELECT office,count(*) compared,
                 count(*) FILTER(WHERE manual_sequence_votes=biometric_nh_bu) equal,
                 count(*) FILTER(WHERE manual_sequence_votes!=biometric_nh_bu) different,
                 sum(manual_sequence_votes) log_manual,sum(biometric_nh_bu) bu_biometric_nh,
                 sum(manual_sequence_votes-biometric_nh_bu) difference
                 FROM analysis WHERE member IS NOT NULL GROUP BY office'''),
               'operational_context': rows('''SELECT office,
                 count(*) FILTER(WHERE vote_origin IS NOT NULL) correspondence_covered,
                 count(*) FILTER(WHERE expected_actual_urn_differ) urn_numbers_differ,
                 count(*) FILTER(WHERE contingency_documented) contingency_documented
                 FROM analysis GROUP BY office'''),
               'high_late_context': rows('''SELECT office,count(*) sections,
                 count(*) FILTER(WHERE expected_actual_urn_differ) urn_numbers_differ,
                 count(*) FILTER(WHERE contingency_documented) contingency_documented,
                 count(*) FILTER(WHERE raw_high_turnout) also_raw_high_turnout,
                 sum(votes_1630_1700) votes_1630_1700,
                 count(*) FILTER(WHERE late_interval_median_seconds<40 AND late_interval_sd_seconds<10) short_regular_intervals
                 FROM analysis WHERE raw_high_late GROUP BY office'''),
               'coverage': rows('''SELECT office,count(*) bu_sections,
                 count(*) FILTER(WHERE member IS NOT NULL) linked_logs,
                 count(*) FILTER(WHERE raw_operational_eligible) raw_operational_eligible,
                 count(*) FILTER(WHERE raw_high_turnout) raw_high_turnout,
                 count(*) FILTER(WHERE raw_high_late) raw_high_late FROM analysis GROUP BY office'''),
               'high_late_sections': rows('''SELECT municipality_name,municipality,zone,section,office,
                 eligible,attendance,after_17_recorded,after_17_manual_sequence,manual_sequence_votes,
                 biometric_nh_bu,cast(first_vote AS VARCHAR) first_vote,cast(last_vote AS VARCHAR) last_vote,
                 opening_bu,closure_bu,late_interval_median_seconds,late_interval_sd_seconds,
                 contingency_documented,aggregated_raw,raw_high_turnout,member
                 FROM analysis WHERE raw_high_late'''),
               'limits': [
                   'Recorded 17h, no independent clock certification; not confirmed B.',
                   'Special/transit/aggregate exclusions pending; raw turnout is not confirmed A.',
                   'Manual sequence is observed, not C residual: active biometry and mandatory controls pending.',
                   'No B+C/ABC inference, matching, adjusted p-values or four-election persistence computed.',
                   'No individual vote/candidate linkage; candidate results refer to whole sections.',
                   'Governor uses same operational cohort as president; its own turnout/vote denominators remain separate.',
               ]}
    for name, condition in [('all_linked', 'member IS NOT NULL'),
                            ('raw_high_late', 'raw_high_late'),
                            ('raw_high_turnout', 'raw_high_turnout')]:
        summary[name] = rows(f'''SELECT office,count(*) sections,count(distinct zone) zones,
            count(distinct municipality) municipalities,sum(eligible) eligible,sum(attendance) attendance,
            sum(valid_votes) valid_votes,sum(pt_votes) pt_votes,sum(other_votes) other_votes,
            100.0*sum(pt_votes)/nullif(sum(valid_votes),0) pt_share_pct,
            100.0*(sum(pt_votes)-sum(other_votes))/nullif(sum(valid_votes),0) pt_minus_other_pp,
            sum(after_17_recorded) after_17_recorded,sum(manual_sequence_votes) manual_sequence_votes,
            sum(after_17_manual_sequence) after_17_manual_sequence,
            count(*) FILTER(WHERE after_17_manual_sequence>0) sections_with_late_manual
            FROM analysis WHERE {condition} GROUP BY office''')
    # An explicitly secondary, unadjusted contrast; not the registered adjusted model.
    summary['unadjusted_exploratory_contrast'] = []
    for office in ('Presidente', 'Governador'):
        frame = db.execute('''SELECT zone,raw_high_late,eligible,pt_votes*1.0/valid_votes y
          FROM analysis WHERE office=? AND raw_operational_eligible AND valid_votes>0''', [office]).df()
        zones = sorted(frame.zone.unique())
        aggregates = np.zeros((len(zones), 4))
        for i, zone in enumerate(zones):
            local = frame[frame.zone == zone]
            for group in (0, 1):
                subset = local[local.raw_high_late == bool(group)]
                aggregates[i, 2*group] = (subset.eligible*subset.y).sum()
                aggregates[i, 2*group+1] = subset.eligible.sum()
        def contrast(totals):
            if totals[1] == 0 or totals[3] == 0:
                return np.nan
            return 100*(totals[2]/totals[3]-totals[0]/totals[1])
        effect = contrast(aggregates.sum(axis=0))
        rng = np.random.default_rng(20261016)
        draws = np.array([contrast(aggregates[rng.integers(0,len(zones),len(zones))].sum(axis=0)) for _ in range(2000)])
        valid = draws[np.isfinite(draws)]
        interval = np.quantile(valid,[.025,.975]).tolist() if len(valid)>=1900 and len(zones)>=30 else None
        summary['unadjusted_exploratory_contrast'].append({
            'office':office,'estimand':'Difference in PT section vote shares, weighted by eligible voters: raw high-late minus others',
            'effect_pp':float(effect) if np.isfinite(effect) else None,'ci95_zone_bootstrap':interval,
            'zones':len(zones),'replicates':2000,'valid_replicates':len(valid),'seed':20261016,
            'ci_unavailable_reason':None if interval is not None else 'Fewer than 95% valid bootstrap replicates or fewer than 30 zones; a group present in only one zone cannot support this interval.',
            'adjusted':False,'matched':False,'p_value':None,'bh_q_value':None,
            'interpretation':'Exploratory unadjusted territorial association; not a test of fraud or confirmed H1'})
    for level, keys in [('municipalities', 'municipality,municipality_name'),
                        ('zones', 'zone'), ('municipality_zones', 'municipality,municipality_name,zone')]:
        query = f'''SELECT {keys},office,count(*) sections,
          count(*) FILTER(WHERE raw_operational_eligible) raw_operational_eligible_sections,
          count(*) FILTER(WHERE raw_high_turnout) raw_high_turnout_sections,
          count(*) FILTER(WHERE raw_high_late) raw_high_late_sections,
          count(*) FILTER(WHERE raw_high_late AND after_17_manual_sequence>0) high_late_sections_with_manual,
          sum(after_17_recorded) after_17_recorded,
          sum(after_17_manual_sequence) after_17_manual_sequence,
          sum(after_17_recorded) FILTER(WHERE raw_high_late) high_late_recorded_votes,
          sum(after_17_manual_sequence) FILTER(WHERE raw_high_late) high_late_manual_votes,
          sum(valid_votes) FILTER(WHERE raw_high_late) high_late_valid_votes,
          sum(pt_votes) FILTER(WHERE raw_high_late) high_late_pt_votes,
          sum(other_votes) FILTER(WHERE raw_high_late) high_late_other_votes,
          100.0*sum(pt_votes) FILTER(WHERE raw_high_late)/
            nullif(sum(valid_votes) FILTER(WHERE raw_high_late),0) high_late_pt_pct,
          100.0*(sum(pt_votes) FILTER(WHERE raw_high_late)-sum(other_votes) FILTER(WHERE raw_high_late))/
            nullif(sum(valid_votes) FILTER(WHERE raw_high_late),0) high_late_pt_margin_pp
          FROM analysis GROUP BY ALL ORDER BY raw_high_late_sections DESC,high_late_manual_votes DESC,{keys},office'''
        db.execute(f"COPY ({query}) TO '{(OUT / (level+'.csv')).as_posix()}' (HEADER,DELIMITER ';')")
        summary['top_'+level] = rows(f'SELECT * FROM ({query}) WHERE office=\'Presidente\' AND raw_high_late_sections>0 ORDER BY raw_high_late_sections DESC,high_late_manual_votes DESC,{keys} LIMIT 10')
    db.execute(f"COPY (SELECT * FROM analysis ORDER BY municipality,zone,section,office) TO '{(OUT/'sections.parquet').as_posix()}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    db.execute(f"COPY (SELECT * FROM analysis ORDER BY municipality,zone,section,office) TO '{(OUT/'sections.csv').as_posix()}' (HEADER,DELIMITER ';')")
    for flag in ('raw_high_late', 'raw_high_turnout'):
        db.execute(f"COPY (SELECT * FROM analysis WHERE {flag} ORDER BY municipality,zone,section,office) TO '{(OUT/(flag+'_sections.csv')).as_posix()}' (HEADER,DELIMITER ';')")
    summary['outputs'] = {path.name: sha256(path) for path in OUT.iterdir() if path.suffix in ('.csv', '.parquet')}
    write_json(OUT / 'summary.json', summary)
    lines = [
        '# Análise executada — Bahia, 2022, segundo turno',
        '', 'Resultado exploratório com logs completos coletados. Não representa ainda a análise histórica das quatro eleições nem os testes confirmatórios ajustados A/B/C/D.',
        '', '## Cobertura e leitura dos logs',
        f"Foram processados {summary['log_totals']['files']:,} logs. Eventos de voto computado: {summary['log_totals']['vote_events']:,}. Após as 17h registradas: {summary['log_totals']['after_17_recorded']:,}. Destes, {summary['log_totals']['after_17_manual_sequence']:,} tiveram a sequência manual completa observada.",
        'Esses totais incluem arquivos de identidade ambígua. Para cruzar com candidatos, usamos apenas identidades inequívocas; para o grupo de horário elevado, exigimos também conciliação com o comparecimento presidencial e ausência de reversões temporais detectadas.',
        '', '## Critério fixado e resultado por cargo',
        f"Grupo exploratório de horário elevado: proporção de votos após 17h superior ao P99 ({100*summary['raw_late_p99']:.4f}%) e quantidade de pelo menos 20. A fórmula numérica é a prevista, mas relógios não certificados e exclusões pendentes impedem chamar este grupo de B confirmado.",
    ]
    for record in summary['raw_high_late']:
        office = record['office']
        state = next(r for r in summary['full_state_results'] if r['cargo']==office)
        other = 'PL/Bolsonaro' if office=='Presidente' else 'UNIÃO/ACM Neto'
        pt = 'PT/Lula' if office=='Presidente' else 'PT/Jerônimo'
        winner = pt if record['pt_votes']>record['other_votes'] else other if record['pt_votes']<record['other_votes'] else 'Empate'
        contrast = next(r for r in summary['unadjusted_exploratory_contrast'] if r['office']==office)
        lines += ['', f'### {office}',
            f"- Grupo de horário elevado: {record['sections']} seções em {record['zones']} zonas e {record['municipalities']} municípios.",
            f"- Votos tardios registrados no grupo: {record['after_17_recorded']:,}; tardios com sequência manual: {record['after_17_manual_sequence']:,}, presentes em {record['sections_with_late_manual']} seções. Presença de sequência manual não significa excesso C.",
            f"- Vencedor nas seções inteiras desse grupo: {winner}. {pt}: {record['pt_share_pct']:.4f}% dos válidos; {other}: {100-record['pt_share_pct']:.4f}%. Margem entre candidatos: {abs(record['pt_minus_other_pp']):.4f} p.p.",
            f"- No estado inteiro: {state['vencedor']} ({state['partido_vencedor']}), {state['vencedor_pct']:.4f}% dos válidos, margem de {state['margem_pp']:.4f} p.p. Comparecimento: {state['comparecimento_pct']:.4f}%.",
            f"- Contraste exploratório PT (horário elevado menos demais elegíveis), ponderado por aptos: {contrast['effect_pp']:.4f} p.p. Sem ajustes ou pareamento; sem q-valor confirmatório.",
            (f"- IC95% por zona: {contrast['ci95_zone_bootstrap']}." if contrast['ci95_zone_bootstrap'] is not None else
             f"- IC95% indisponível: apenas {contrast['valid_replicates']} de 2.000 réplicas válidas, abaixo do mínimo de 95% fixado. O grupo elevado está em apenas uma zona. Não há base para declarar significância a partir deste contraste."),
        ]
    lines += ['', '## Seções encontradas pelo critério de horário elevado']
    for record in summary['high_late_sections']:
        if record['office']!='Presidente':
            continue
        lines += [f"{record['municipality_name']}, zona {record['zone']}, seção {record['section']}: {record['attendance']} comparecimentos de {record['eligible']} aptos. Último voto às {record['last_vote']}; encerramento no BU: {record['closure_bu']}. Mediana dos intervalos tardios: {record['late_interval_median_seconds']} s; desvio-padrão: {record['late_interval_sd_seconds']:.2f} s. Não satisfaz o diagnóstico de intervalos medianos<40 s e desvio<10 s. A ordem de grandeza é compatível com fila, sem comprová-la.",
                  f"Habilitações manuais observadas no dia: {record['manual_sequence_votes']}; campo correspondente do BU: {record['biometric_nh_bu']}. A seção não atende ao critério bruto de comparecimento elevado. Origem: {record['member']}."]
    lines += ['', '## Municípios com maior número de seções no grupo de horário elevado — presidente']
    for record in summary['top_municipalities']:
        if not record['raw_high_late_sections']:
            continue
        lines += [f"- {record['municipality_name']}: {record['raw_high_late_sections']} seções; {record['high_late_recorded_votes']} votos tardios registrados; {record['high_late_manual_votes']} tardios com sequência manual. Nas seções inteiras: PT {record['high_late_pt_pct']:.2f}% dos válidos; diferença PT−PL {record['high_late_pt_margin_pp']:.2f} p.p."]
    lines += ['', '## Comparecimento e conferência manual']
    for record in summary['coverage']:
        lines += [f"- {record['office']}: {record['raw_high_turnout']} unidades atendem à fórmula bruta de comparecimento elevado (z MAD>3 e diferença municipal≥10 p.p.). Ainda requer exclusões antes de confirmar A."]
    lines += ['Referência nacional publicada pelo TSE: comparecimento 79,41%, incluindo exterior e seções especiais. É referência descritiva geral, não a referência nacional filtrada do protocolo.']
    for record in summary['manual_bu_validation']:
        lines += [f"- {record['office']}, log manual versus QT_ELEITORES_BIOMETRIA_NH do BU: {record['equal']} iguais e {record['different']} diferentes em {record['compared']} unidades comparadas. Diferença total: {record['difference']}."]
    lines += ['', '## Conclusões que os dados permitem',
        'O relatório identifica onde há concentração de horários registrados e habilitações manuais, e mostra o resultado partidário das seções correspondentes. Não identifica o candidato votado pelos eleitores tardios ou habilitados manualmente.',
        'Não foi testada a persistência em quatro eleições. Também não foi estimado excesso manual C, pois faltam os controles completos e a confirmação territorial de biometria ativa. Não há contagem confirmada de B+C, nem conclusão de favorecimento partidário ou fraude.',
        'A votação de quem estava na fila pode continuar após o horário. Falha biométrica, composição do eleitorado, contingência, agregação e relógio são explicações que exigem avaliação. O intervalo exploratório não elimina essas explicações.',
        '', '## Arquivos e reprodução',
        '`sections.csv` e `sections.parquet`: detalhes por seção/cargo, inclusive controles operacionais adquiridos, contagens e votos. `municipalities.csv`, `zones.csv`, `municipality_zones.csv`: agregados. `summary.json`: parâmetros, fontes, hashes, cobertura, efeitos e limitações.',
        'Executar a partir de F:\\votos: `.venv\\Scripts\\python.exe scripts/analyze_pilot_operations.py`, depois `.venv\\Scripts\\python.exe scripts/report_pilot_operations.py`.',
        f"Plano SHA-256: {summary['plan_sha256']}. Registro local antes dos novos cálculos; piloto já explorado anteriormente, não pré-registro independente.",
        '', 'Fonte nacional: '+summary['national_reference']['source'],
    ]
    (OUT/'RELATORIO.md').write_text('\n\n'.join(line for line in lines if line), encoding='utf-8')
    print(json.dumps({k: summary[k] for k in ('log_totals','raw_late_p99','coverage','raw_high_late','top_municipalities')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
