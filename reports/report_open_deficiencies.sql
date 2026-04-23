-- name: report_open_deficiencies
-- description: Locations with open deficiencies that have not been resolved or fixed, including severity and days open.
-- created_at: 2026-03-20T20:54:47Z
DROP VIEW IF EXISTS report_open_deficiencies;
CREATE VIEW report_open_deficiencies AS
SELECT
  c.name AS customer,
  l.name AS location,
  l.address_city AS city,
  d.severity,
  d.title,
  d.status AS deficiency_status,
  d.resolution,
  date(d.reported_on, 'unixepoch') AS reported_on,
  CAST((strftime('%s','now') - d.reported_on) / 86400 AS INTEGER) AS days_open,
  d.description
FROM deficiency d
JOIN location l ON d.location_id = l.id
JOIN company c ON l.company_id = c.id
WHERE d.status NOT IN ('fixed', 'invalid')
ORDER BY
  CASE d.severity WHEN 'inoperable' THEN 1 WHEN 'deficient' THEN 2 ELSE 3 END,
  days_open DESC;
