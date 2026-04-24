-- name: report_qual_primary_hood_duplicates
-- description: DATA QUALITY: Detect any active locations that have more than one active Primary Main Hood service recurrence. The main report (report_primary_hood_next_service) assumes one per location. If this report has any rows, those locations need cleanup in ServiceTrade. Part of the report_qual_* data quality suite.
-- created_at: 2026-04-24T22:48:14Z
DROP VIEW IF EXISTS report_qual_primary_hood_duplicates;
CREATE VIEW report_qual_primary_hood_duplicates AS
SELECT 
  c.name AS company_name,
  l.name AS location_name,
  COUNT(*) AS active_primary_hood_count,
  GROUP_CONCAT(sr.id) AS recurrence_ids,
  GROUP_CONCAT(sr.estimated_price) AS prices
FROM service_recurrence sr
JOIN location l ON sr.location_id = l.id
JOIN company c ON l.company_id = c.id
WHERE sr.description LIKE 'PrimaryxxxxMainHoodxxxxxx%'
  AND sr.service_line_id = 10
  AND sr.id = sr.current_service_recurrence_id
  AND sr.ends_on IS NULL
  AND l.status = 'active'
  AND c.status = 'active'
GROUP BY c.name, l.name
HAVING COUNT(*) > 1
ORDER BY c.name, l.name;
