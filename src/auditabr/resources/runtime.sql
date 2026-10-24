-- Migration 001. Revised physical schema; full design retained in reference_schema.sql.
-- One immutable database per snapshot. No cross-snapshot joins or mutable reader database.
CREATE TABLE IF NOT EXISTS schema_migration(version VARCHAR PRIMARY KEY, checksum VARCHAR, applied_at VARCHAR);
CREATE TABLE IF NOT EXISTS section_turnout(
 section_id VARCHAR PRIMARY KEY, year INTEGER NOT NULL, round INTEGER NOT NULL,
 uf VARCHAR NOT NULL, municipality VARCHAR NOT NULL, municipality_name VARCHAR,
 zone VARCHAR NOT NULL, section VARCHAR NOT NULL, place VARCHAR, place_name VARCHAR,
 eligible BIGINT NOT NULL CHECK(eligible >= 0), present BIGINT NOT NULL CHECK(present >= 0),
 absent BIGINT NOT NULL CHECK(absent >= 0), asset_id VARCHAR NOT NULL,
 CHECK(eligible = present + absent)
);
CREATE TABLE IF NOT EXISTS candidate_vote(
 section_id VARCHAR, year INTEGER, round INTEGER, uf VARCHAR, municipality VARCHAR,
 zone VARCHAR, section VARCHAR, place VARCHAR, office VARCHAR NOT NULL,
 candidate_id VARCHAR NOT NULL, candidate_number VARCHAR, candidate_name VARCHAR,
 party VARCHAR, vote_status VARCHAR, vote_class VARCHAR NOT NULL,
 votes BIGINT NOT NULL CHECK(votes >= 0), asset_id VARCHAR NOT NULL,
 CHECK(office IN ('PRESIDENTE','GOVERNADOR','SENADOR','PREFEITO')),
 CHECK(office != 'SENADOR' OR round = 1),
 PRIMARY KEY(section_id,office,candidate_id,vote_status)
);
CREATE TABLE IF NOT EXISTS contest_vote_summary(
 section_id VARCHAR, year INTEGER, round INTEGER, uf VARCHAR, office VARCHAR,
 nominal BIGINT, blank BIGINT, null_votes BIGINT, other BIGINT, total BIGINT,
 slots INTEGER NOT NULL, asset_id VARCHAR NOT NULL,
 PRIMARY KEY(section_id,office)
);
CREATE TABLE IF NOT EXISTS source_asset(
 asset_id VARCHAR PRIMARY KEY, resource_id VARCHAR, dataset_id VARCHAR, source_url VARCHAR,
 sha256 VARCHAR NOT NULL, size_bytes BIGINT, raw_path VARCHAR, receipt JSON NOT NULL
);
CREATE TABLE IF NOT EXISTS partition_registry(
 year INTEGER, round INTEGER, uf VARCHAR, family VARCHAR, run_id VARCHAR,
 assets JSON, rows BIGINT, status VARCHAR, PRIMARY KEY(year,round,uf,family)
);
CREATE TABLE IF NOT EXISTS operational_section_metrics(
 section_id VARCHAR PRIMARY KEY, year INTEGER, round INTEGER, uf VARCHAR, municipality VARCHAR,
 zone VARCHAR, section VARCHAR, place VARCHAR,
 vote_events BIGINT, timed_events BIGINT, after_cutoff BIGINT,
 biometric BIGINT, manual BIGINT, no_enrollment BIGINT, biographic BIGINT,
 unknown BIGINT, conflict BIGINT, first_vote VARCHAR, last_vote VARCHAR, closure VARCHAR, bu VARCHAR,
 clock_quality VARCHAR, taxonomy_status VARCHAR, classification_coverage DOUBLE,
 timezone VARCHAR, cutoff_utc VARCHAR, multi_device BOOLEAN,
 asset_id VARCHAR, warnings JSON, hourly JSON
);
CREATE TABLE IF NOT EXISTS quality_issue(
 issue_id VARCHAR PRIMARY KEY, section_id VARCHAR, family VARCHAR, severity VARCHAR,
 code VARCHAR, detail VARCHAR, asset_id VARCHAR
);
CREATE TABLE IF NOT EXISTS historical_section_link(
 link_id VARCHAR PRIMARY KEY, section_a VARCHAR, section_b VARCHAR, method VARCHAR,
 confidence VARCHAR CHECK(confidence IN ('HIGH','MEDIUM','LOW')), evidence VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS case_review(
 finding_id VARCHAR PRIMARY KEY, snapshot_id VARCHAR, section_id VARCHAR, status VARCHAR,
 note VARCHAR, created_at VARCHAR, configuration JSON
);
