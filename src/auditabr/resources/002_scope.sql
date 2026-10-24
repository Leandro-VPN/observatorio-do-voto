-- User-directed narrowing: presidential turnout in general elections, mayor in municipal elections.
DELETE FROM candidate_vote WHERE office NOT IN ('PRESIDENTE','PREFEITO');
DELETE FROM contest_vote_summary WHERE office NOT IN ('PRESIDENTE','PREFEITO');
DELETE FROM section_turnout WHERE year % 4 = 2 AND asset_id NOT IN (
 SELECT asset_id FROM source_asset WHERE json_extract_string(receipt,'$.member') LIKE '%_BR.csv'
);
DELETE FROM partition_registry WHERE family IN ('turnout','votes');
CREATE TABLE IF NOT EXISTS scope_policy(office VARCHAR PRIMARY KEY CHECK(office IN ('PRESIDENTE','PREFEITO')));
INSERT INTO scope_policy VALUES ('PRESIDENTE'),('PREFEITO') ON CONFLICT DO NOTHING;
