-- name: report_deficiency_severity_by_customer
-- description: Deficiency severity breakdown by customer — counts of suggested, deficient, and inoperable findings.
-- created_at: 2026-03-20T21:21:23Z
DROP VIEW IF EXISTS report_deficiency_severity_by_customer;
CREATE VIEW report_deficiency_severity_by_customer AS
SELECT
  c.name AS customer,
  CAST(COUNT(d.id) AS INTEGER) AS total_deficiencies,
  CAST(SUM(CASE WHEN d.severity = 'inoperable' THEN 1 ELSE 0 END) AS INTEGER) AS inoperable,
  CAST(SUM(CASE WHEN d.severity = 'deficient' THEN 1 ELSE 0 END) AS INTEGER) AS deficient,
  CAST(SUM(CASE WHEN d.severity = 'suggested' THEN 1 ELSE 0 END) AS INTEGER) AS suggested,
  CAST(SUM(CASE WHEN d.status NOT IN ('fixed','invalid') THEN 1 ELSE 0 END) AS INTEGER) AS still_open,
  CAST(SUM(CASE WHEN d.status = 'fixed' THEN 1 ELSE 0 END) AS INTEGER) AS fixed
FROM deficiency d
JOIN location l ON d.location_id = l.id
JOIN company c ON l.company_id = c.id
GROUP BY c.id, c.name
ORDER BY inoperable DESC, deficient DESC, total_deficiencies DESC;
