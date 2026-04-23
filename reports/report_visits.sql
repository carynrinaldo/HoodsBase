-- name: report_visits
-- description: All completed jobs by customer for 2024 and 2025, showing individual visit records with job number, customer, location, and completed date.
-- created_at: 2026-03-20T05:34:14Z
DROP VIEW IF EXISTS report_visits;
CREATE VIEW report_visits AS
SELECT
  j.id AS job_id,
  j.number AS job_number,
  c.name AS customer_name,
  l.name AS location_name,
  l.address_city AS city,
  j.type AS job_type,
  strftime('%Y', j.completed_on, 'unixepoch') AS year,
  date(j.completed_on, 'unixepoch') AS completed_on
FROM job j
JOIN company c ON j.customer_id = c.id
LEFT JOIN location l ON j.location_id = l.id
WHERE j.status = 'completed'
  AND strftime('%Y', j.completed_on, 'unixepoch') IN ('2024', '2025')
ORDER BY c.name, j.completed_on;
