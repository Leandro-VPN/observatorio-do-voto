"""Reproducible descriptive baseline, not the gated anomaly/association tests."""
import json
from pathlib import Path

import duckdb

from auditabr.utils import sha256, utcnow, write_json

ROOT = Path('research/piloto-ba-2022-t2')
OUT = ROOT / 'baseline'


def main():
    OUT.mkdir(exist_ok=True)
    plan = Path('research/PLANO_ANALISE_A_PRIORI.md')
    register = Path('research/plano-v1-registro.json')
    if register.exists():
        assert json.loads(register.read_text(encoding='utf-8'))['sha256'] == sha256(plan)
    else:
        write_json(register, {
            'registered_at_utc': utcnow(), 'file': str(plan), 'sha256': sha256(plan),
            'status': 'LOCAL_FREEZE_BEFORE_NEW_ASSOCIATION_TESTS_NOT_EXTERNAL_PREREGISTRATION',
            'prior_exposure': 'BA2022T2 candidate totals and log-BU reconciliation; exploratory pilot',
        })
    db = duckdb.connect()
    db.execute("SET memory_limit='512MB'")
    source = ROOT / 'captures/bweb_2t_BA_311020221535.parquet'
    db.read_parquet(str(source)).create_view('bu')
    db.execute('''CREATE TEMP TABLE sections AS
        SELECT SG_UF uf, CD_MUNICIPIO municipio, NM_MUNICIPIO nome_municipio,
          NR_ZONA zona, NR_SECAO secao, DS_CARGO_PERGUNTA cargo,
          max(cast(QT_APTOS AS BIGINT)) aptos,
          max(cast(QT_COMPARECIMENTO AS BIGINT)) comparecimento,
          max(cast(QT_ABSTENCOES AS BIGINT)) abstencoes,
          count(distinct QT_APTOS)=1 AND count(distinct QT_COMPARECIMENTO)=1
            AND count(distinct QT_ABSTENCOES)=1 denominadores_consistentes,
          max(DS_AGREGADAS) agregadas_original,
          max(NR_LOCAL_VOTACAO) local_votacao
        FROM bu GROUP BY ALL''')
    assert db.execute('SELECT count(*) FROM sections WHERE NOT denominadores_consistentes').fetchone()[0] == 0
    assert db.execute('SELECT count(*) FROM sections WHERE aptos != comparecimento+abstencoes').fetchone()[0] == 0
    reports = {}
    for level, keys in [
        ('estado', ['uf']),
        ('municipio', ['uf', 'municipio', 'nome_municipio']),
        ('zona', ['uf', 'zona']),
        ('municipio_zona', ['uf', 'municipio', 'nome_municipio', 'zona']),
        ('secao', ['uf', 'municipio', 'nome_municipio', 'zona', 'secao']),
    ]:
        columns = ','.join(keys + ['cargo'])
        base = ','.join(keys)
        db.execute(f'''CREATE OR REPLACE TEMP VIEW denominators AS
          SELECT {columns},sum(aptos) aptos,sum(comparecimento) comparecimento,
            sum(abstencoes) abstencoes,count(*) unidades_bu,
            100.0*sum(comparecimento)/nullif(sum(aptos),0) comparecimento_pct,
            100.0*sum(abstencoes)/nullif(sum(aptos),0) abstencao_pct
          FROM sections GROUP BY ALL''')
        # Alias raw geography once; group only valid nominal votes.
        db.execute(f'''CREATE OR REPLACE TEMP VIEW candidate_totals AS
          WITH v AS (SELECT SG_UF uf,CD_MUNICIPIO municipio,NM_MUNICIPIO nome_municipio,
            NR_ZONA zona,NR_SECAO secao,DS_CARGO_PERGUNTA cargo,
            NR_VOTAVEL numero,NM_VOTAVEL candidato,SG_PARTIDO partido,
            cast(QT_VOTOS AS BIGINT) votos FROM bu WHERE CD_TIPO_VOTAVEL='1')
          SELECT {columns},numero,candidato,partido,sum(votos) votos FROM v GROUP BY ALL''')
        db.execute(f'''CREATE OR REPLACE TEMP VIEW results AS
          WITH ranked AS (SELECT *,sum(votos) OVER(PARTITION BY {columns}) votos_validos,
            row_number() OVER(PARTITION BY {columns} ORDER BY votos DESC,numero) ordem,
            lead(votos) OVER(PARTITION BY {columns} ORDER BY votos DESC,numero) segundo_votos
            FROM candidate_totals)
          SELECT {','.join('r.'+x for x in keys)},2022 ano,2 turno,r.cargo,
            CASE WHEN r.votos=r.segundo_votos THEN 'EMPATE' ELSE r.candidato END vencedor,
            CASE WHEN r.votos=r.segundo_votos THEN 'EMPATE' ELSE r.partido END partido_vencedor,
            r.votos votos_vencedor,
            r.votos_validos,100.0*r.votos/nullif(r.votos_validos,0) vencedor_pct,
            100.0*(r.votos-r.segundo_votos)/nullif(r.votos_validos,0) margem_pp,
            r.votos=r.segundo_votos empate,
            d.aptos,d.comparecimento,d.abstencoes,d.unidades_bu,
            d.comparecimento_pct,d.abstencao_pct,
            'DESCRITIVO_TODO_BU_SEM_EXCLUSOES' status,
            NULL::BOOLEAN flag_a,NULL::BOOLEAN flag_b,NULL::BOOLEAN flag_c,
            NULL::BIGINT votos_pos_horario,NULL::BIGINT votos_pos_manual,
            'A: exclusoes; B: relogio; C: taxonomia e controles; nao sao zeros' lacuna
          FROM ranked r JOIN denominators d USING({columns}) WHERE ordem=1''')
        output = OUT / f'{level}.csv'
        db.execute(f"COPY (SELECT * FROM results ORDER BY {base},cargo) TO '{output.as_posix()}' (HEADER,DELIMITER ';')")
        # Full candidate distributions make winner/margin computation auditable.
        candidates = OUT / f'{level}-candidatos.parquet'
        db.execute(f"COPY candidate_totals TO '{candidates.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        reports[level] = db.execute('SELECT count(*) FROM results').fetchone()[0]
        if level == 'estado':
            cur = db.execute('SELECT * FROM results ORDER BY cargo')
            state = [dict(zip([c[0] for c in cur.description], row)) for row in cur.fetchall()]
        # Every partition must preserve the official totals, independently of granularity.
        assert db.execute('SELECT sum(votos) FROM candidate_totals').fetchone()[0] == 16942330
    write_json(OUT / 'manifest.json', {
        'at': utcnow(), 'plan_sha256': sha256(plan), 'script_sha256': sha256(Path(__file__)),
        'source': str(source), 'source_sha256': sha256(source),
        'status': 'DESCRIPTIVE_ONLY_NO_ANOMALY_FLAGS_OR_INFERENTIAL_TESTS',
        'rows': reports, 'state_results': state,
        'checks': ['BU denominators internally consistent', 'attendance+abstention=eligible',
                   '16942330 nominal votes preserved at every geographic level'],
        'files': {p.name: sha256(p) for p in OUT.iterdir() if p.suffix in ('.csv', '.parquet')},
    })
    print(json.dumps({'rows': reports, 'state': state}, ensure_ascii=False))


if __name__ == '__main__':
    main()
