-- AUDITA-BR | DDL inicial canônico para DuckDB.
-- Versão de especificação 1.0.0 | Um migrador deve gerir versões de esquema.
-- DuckDB para consultas analíticas; parquet para fatos grandes de eventos.

CREATE TABLE IF NOT EXISTS schema_migration (
  version VARCHAR PRIMARY KEY, applied_at TIMESTAMP NOT NULL,
  migration_sha256 VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS election (
  election_id VARCHAR PRIMARY KEY,
  election_year INTEGER NOT NULL,
  election_kind VARCHAR NOT NULL,                -- GERAL | MUNICIPAL
  reference_as_of DATE NOT NULL,
  publication_status VARCHAR NOT NULL,
  created_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS election_round (
  round_id VARCHAR PRIMARY KEY,
  election_id VARCHAR NOT NULL,
  round_number INTEGER NOT NULL,
  election_date DATE,
  scheduled_open_brt TIMESTAMP,
  scheduled_cutoff_brt TIMESTAMP,
  timing_rule_id VARCHAR,
  publication_status VARCHAR NOT NULL,
  UNIQUE(election_id, round_number)
);
CREATE TABLE IF NOT EXISTS office (
  office_code VARCHAR PRIMARY KEY,               -- PRESIDENTE, GOVERNADOR, SENADOR, PREFEITO
  office_name VARCHAR NOT NULL,
  seat_count_rule VARCHAR,
  runoff_allowed BOOLEAN NOT NULL
);
CREATE TABLE IF NOT EXISTS contest (
  contest_id VARCHAR PRIMARY KEY,
  round_id VARCHAR NOT NULL,
  office_code VARCHAR NOT NULL,
  district_scope VARCHAR NOT NULL,               -- BR, UF, MUNICIPIO
  district_code VARCHAR NOT NULL,
  senate_seats INTEGER,
  status VARCHAR NOT NULL,
  UNIQUE(round_id, office_code, district_scope, district_code)
);
CREATE TABLE IF NOT EXISTS locality (
  locality_id VARCHAR PRIMARY KEY,
  election_id VARCHAR NOT NULL,
  uf VARCHAR NOT NULL,
  tse_municipality_code VARCHAR,
  municipality_name VARCHAR,
  ibge_municipality_code VARCHAR,
  is_foreign BOOLEAN DEFAULT FALSE,
  code_map_status VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS polling_place (
  polling_place_id VARCHAR PRIMARY KEY,
  round_id VARCHAR NOT NULL,
  locality_id VARCHAR NOT NULL,
  electoral_zone VARCHAR NOT NULL,
  place_code VARCHAR,
  place_name VARCHAR,
  address_normalized VARCHAR,
  latitude DOUBLE,
  longitude DOUBLE,
  geocode_source VARCHAR,
  location_confidence DOUBLE,
  is_provisional BOOLEAN DEFAULT FALSE
);
CREATE TABLE IF NOT EXISTS section_instance (
  section_instance_id VARCHAR PRIMARY KEY,
  round_id VARCHAR NOT NULL,
  locality_id VARCHAR NOT NULL,
  uf VARCHAR NOT NULL,
  municipality_tse VARCHAR,
  electoral_zone VARCHAR NOT NULL,
  electoral_section VARCHAR NOT NULL,
  polling_place_id VARCHAR,
  section_aggregation_status VARCHAR,
  section_type VARCHAR,
  source_asset_id VARCHAR,
  UNIQUE(round_id, uf, municipality_tse, electoral_zone, electoral_section)
);
CREATE TABLE IF NOT EXISTS historical_section_link (
  link_id VARCHAR PRIMARY KEY,
  section_instance_a VARCHAR NOT NULL,
  section_instance_b VARCHAR NOT NULL,
  linkage_method VARCHAR NOT NULL,
  confidence VARCHAR NOT NULL,                  -- HIGH, MEDIUM, LOW
  evidence JSON,
  reviewed_by VARCHAR,
  reviewed_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS candidate (
  candidate_instance_id VARCHAR PRIMARY KEY,
  election_id VARCHAR NOT NULL,
  office_code VARCHAR NOT NULL,
  tse_candidate_code VARCHAR,
  ballot_number VARCHAR,
  ballot_name VARCHAR,
  full_name VARCHAR,
  party_acronym VARCHAR,
  ticket_id VARCHAR,
  original_status VARCHAR,
  status_snapshot_id VARCHAR,
  source_asset_id VARCHAR
);
CREATE TABLE IF NOT EXISTS source_dataset (
  source_dataset_id VARCHAR PRIMARY KEY,
  ckan_package_id VARCHAR,
  ckan_slug VARCHAR,
  title VARCHAR,
  source_page_url VARCHAR NOT NULL,
  license_label VARCHAR,
  source_updated_at TIMESTAMP,
  catalog_retrieved_at TIMESTAMP NOT NULL,
  metadata_json JSON
);
CREATE TABLE IF NOT EXISTS source_resource (
  source_resource_id VARCHAR PRIMARY KEY,
  source_dataset_id VARCHAR NOT NULL,
  ckan_resource_id VARCHAR,
  resource_url VARCHAR NOT NULL,
  resource_name VARCHAR,
  reported_format VARCHAR,
  observed_format VARCHAR,
  expected_size BIGINT,
  last_modified VARCHAR,
  etag VARCHAR,
  resource_metadata JSON
);
CREATE TABLE IF NOT EXISTS source_asset (
  source_asset_id VARCHAR PRIMARY KEY,
  source_resource_id VARCHAR NOT NULL,
  raw_sha256 VARCHAR NOT NULL,
  raw_size_bytes BIGINT NOT NULL,
  storage_uri VARCHAR NOT NULL,
  downloaded_at TIMESTAMP NOT NULL,
  source_http_metadata JSON,
  archive_members_manifest_uri VARCHAR,
  verification_status VARCHAR NOT NULL,
  retained BOOLEAN NOT NULL DEFAULT TRUE,
  UNIQUE(source_resource_id, raw_sha256)
);
CREATE TABLE IF NOT EXISTS pipeline_run (
  pipeline_run_id VARCHAR PRIMARY KEY,
  run_type VARCHAR NOT NULL,
  code_commit VARCHAR,
  parser_version VARCHAR,
  taxonomy_version VARCHAR,
  config_sha256 VARCHAR,
  input_manifest_sha256 VARCHAR,
  started_at TIMESTAMP NOT NULL,
  finished_at TIMESTAMP,
  status VARCHAR NOT NULL,
  warnings JSON
);
CREATE TABLE IF NOT EXISTS lineage (
  lineage_id VARCHAR PRIMARY KEY,
  pipeline_run_id VARCHAR NOT NULL,
  source_asset_id VARCHAR NOT NULL,
  derived_table VARCHAR NOT NULL,
  partition_uri VARCHAR,
  derived_sha256 VARCHAR,
  row_count BIGINT,
  rejected_count BIGINT
);
CREATE TABLE IF NOT EXISTS dataset_coverage (
  coverage_id VARCHAR PRIMARY KEY,
  round_id VARCHAR NOT NULL,
  uf VARCHAR NOT NULL,
  source_family VARCHAR NOT NULL,
  snapshot_id VARCHAR,
  discovery_status VARCHAR NOT NULL,
  processing_status VARCHAR NOT NULL,
  expected_sections BIGINT,
  parsed_sections BIGINT,
  eligible_voters_in_scope BIGINT,
  event_classified_count BIGINT,
  event_unknown_count BIGINT,
  completeness_ratio DOUBLE,
  limitations JSON,
  source_asset_ids JSON,
  updated_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS section_turnout (
  section_instance_id VARCHAR NOT NULL,
  snapshot_id VARCHAR NOT NULL,
  voters_eligible BIGINT,
  voters_present BIGINT,
  voters_absent BIGINT,
  is_provisional BOOLEAN NOT NULL DEFAULT FALSE,
  source_asset_id VARCHAR NOT NULL,
  validation_status VARCHAR NOT NULL,
  PRIMARY KEY(section_instance_id, snapshot_id)
);
CREATE TABLE IF NOT EXISTS candidate_vote (
  section_instance_id VARCHAR NOT NULL,
  contest_id VARCHAR NOT NULL,
  candidate_instance_id VARCHAR NOT NULL,
  snapshot_id VARCHAR NOT NULL,
  vote_count BIGINT NOT NULL,
  vote_status VARCHAR NOT NULL,
  source_asset_id VARCHAR NOT NULL,
  PRIMARY KEY(section_instance_id, contest_id, candidate_instance_id, snapshot_id, vote_status)
);
CREATE TABLE IF NOT EXISTS contest_vote_summary (
  section_instance_id VARCHAR NOT NULL,
  contest_id VARCHAR NOT NULL,
  snapshot_id VARCHAR NOT NULL,
  vote_nominal_total BIGINT,
  vote_blank BIGINT,
  vote_null BIGINT,
  vote_other_count BIGINT,
  ballot_slots_per_voter INTEGER NOT NULL,
  reconciliation_status VARCHAR NOT NULL,
  source_asset_id VARCHAR NOT NULL,
  PRIMARY KEY(section_instance_id, contest_id, snapshot_id)
);
CREATE TABLE IF NOT EXISTS operational_log (
  operational_log_id VARCHAR PRIMARY KEY,
  section_instance_id VARCHAR,
  round_id VARCHAR NOT NULL,
  source_asset_id VARCHAR NOT NULL,
  source_member_name VARCHAR NOT NULL,
  parser_id VARCHAR NOT NULL,
  parser_version VARCHAR NOT NULL,
  raw_event_count BIGINT,
  classified_event_count BIGINT,
  invalid_event_count BIGINT,
  urn_device_count INTEGER,
  clock_confidence VARCHAR,
  parse_status VARCHAR NOT NULL,
  warnings JSON
);
-- Para eventos de alta cardinalidade, a tabela abaixo é a interface *lógica*.
-- Persistir fisicamente em Parquet particionado por ano/turno/UF/tipo quando volumoso.
CREATE TABLE IF NOT EXISTS operational_event_example_schema (
  event_id VARCHAR,
  operational_log_id VARCHAR,
  section_instance_id VARCHAR,
  device_id_hash VARCHAR,
  raw_line_number BIGINT,
  local_civil_ts TIMESTAMP,
  timezone_id VARCHAR,
  normalized_ts_utc TIMESTAMP,
  normalized_ts_brt TIMESTAMP,
  event_kind VARCHAR,
  event_subtype VARCHAR,
  parser_confidence VARCHAR,
  clock_quality VARCHAR,
  is_election_day BOOLEAN,
  linkage_group_id VARCHAR,
  source_asset_id VARCHAR
);
CREATE TABLE IF NOT EXISTS operational_section_metrics (
  section_instance_id VARCHAR NOT NULL,
  snapshot_id VARCHAR NOT NULL,
  event_votes_count BIGINT,
  earliest_vote_local TIMESTAMP,
  last_vote_local TIMESTAMP,
  nominal_end_local TIMESTAMP,
  closure_event_local TIMESTAMP,
  issued_bu_local TIMESTAMP,
  after_cutoff_events BIGINT,
  after_cutoff_share DOUBLE,
  biometric_confirmed BIGINT,
  manual_confirmed BIGINT,
  no_enrollment_evidence BIGINT,
  other_confirmed BIGINT,
  unknown_habilitation BIGINT,
  multi_device BOOLEAN,
  clock_confidence VARCHAR,
  event_match_status VARCHAR,
  classification_coverage DOUBLE,
  operational_log_ids JSON,
  PRIMARY KEY(section_instance_id, snapshot_id)
);
CREATE TABLE IF NOT EXISTS quality_issue (
  issue_id VARCHAR PRIMARY KEY,
  snapshot_id VARCHAR,
  source_asset_id VARCHAR,
  section_instance_id VARCHAR,
  issue_category VARCHAR NOT NULL,
  issue_code VARCHAR NOT NULL,
  severity VARCHAR NOT NULL,
  raw_value VARCHAR,
  expected_value VARCHAR,
  evidence JSON,
  resolution_status VARCHAR NOT NULL,
  created_at TIMESTAMP NOT NULL
);
CREATE TABLE IF NOT EXISTS analysis_run (
  analysis_run_id VARCHAR PRIMARY KEY,
  snapshot_id VARCHAR NOT NULL,
  analysis_code VARCHAR NOT NULL,
  analysis_version VARCHAR NOT NULL,
  filters JSON NOT NULL,
  baselines JSON,
  thresholds JSON,
  coverage_constraints JSON,
  multiple_testing_method VARCHAR,
  created_at TIMESTAMP NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_finding (
  finding_id VARCHAR PRIMARY KEY,
  analysis_run_id VARCHAR NOT NULL,
  section_instance_id VARCHAR,
  aggregation_scope VARCHAR,
  finding_type VARCHAR NOT NULL,
  evidence_strength VARCHAR NOT NULL,
  review_status VARCHAR NOT NULL,
  measured_value DOUBLE,
  expected_value DOUBLE,
  effect_size DOUBLE,
  p_value DOUBLE,
  adjusted_q_value DOUBLE,
  sample_size BIGINT,
  coverage_pct DOUBLE,
  alternative_explanations JSON,
  notes VARCHAR,
  source_asset_ids JSON,
  created_at TIMESTAMP NOT NULL
);
CREATE TABLE IF NOT EXISTS report_manifest (
  report_id VARCHAR PRIMARY KEY,
  snapshot_id VARCHAR NOT NULL,
  analysis_run_id VARCHAR,
  report_uri VARCHAR NOT NULL,
  report_sha256 VARCHAR NOT NULL,
  produced_at TIMESTAMP NOT NULL,
  source_asset_ids JSON,
  filters JSON NOT NULL,
  code_version VARCHAR,
  bibliography JSON
);
CREATE TABLE IF NOT EXISTS published_snapshot (
  snapshot_id VARCHAR PRIMARY KEY,
  published_at TIMESTAMP NOT NULL,
  as_of_date DATE NOT NULL,
  source_manifest_sha256 VARCHAR NOT NULL,
  transformation_version VARCHAR NOT NULL,
  quality_summary JSON,
  status VARCHAR NOT NULL
);

INSERT INTO office VALUES
  ('PRESIDENTE','Presidente da República','1',TRUE),
  ('GOVERNADOR','Governador de Estado/DF','1',TRUE),
  ('SENADOR','Senador','depends_on_year:1_or_2',FALSE),
  ('PREFEITO','Prefeito','1',TRUE)
ON CONFLICT DO NOTHING;
