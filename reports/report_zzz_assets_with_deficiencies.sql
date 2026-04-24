-- name: report_zzz_assets_with_deficiencies
-- description: Assets with active (unfixed) deficiencies, showing severity and how long the deficiency has been open.
-- created_at: 2026-04-24T23:00:12Z
DROP VIEW IF EXISTS report_zzz_assets_with_deficiencies;
CREATE VIEW report_zzz_assets_with_deficiencies AS
SELECT
  c.name AS customer,
  l.name AS location,
  l.address_city AS city,
  a.display AS asset_type,
  a.name AS asset_name,
  d.severity,
  d.title AS deficiency_title,
  d.status AS deficiency_status,
  d.resolution,
  date(d.reported_on, 'unixepoch') AS reported_on,
  CAST((strftime('%s','now') - d.reported_on) / 86400 AS INTEGER) AS days_open
FROM deficiency d
JOIN asset a ON d.asset_id = a.id
JOIN location l ON d.location_id = l.id
JOIN company c ON l.company_id = c.id
WHERE d.status NOT IN ('fixed', 'invalid')
ORDER BY
  CASE d.severity WHEN 'inoperable' THEN 1 WHEN 'deficient' THEN 2 ELSE 3 END,
  days_open DESC;
