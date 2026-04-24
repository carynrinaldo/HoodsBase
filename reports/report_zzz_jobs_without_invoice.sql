-- name: report_zzz_jobs_without_invoice
-- description: Completed jobs that have no associated invoice — work done but not billed.
-- created_at: 2026-04-24T23:02:00Z
DROP VIEW IF EXISTS report_zzz_jobs_without_invoice;
CREATE VIEW report_zzz_jobs_without_invoice AS
SELECT
  c.name AS customer,
  l.name AS location,
  l.address_city AS city,
  j.number AS job_number,
  j.name AS job_name,
  j.type AS job_type,
  j.service_line,
  date(j.completed_on, 'unixepoch') AS completed_on,
  CAST((strftime('%s','now') - j.completed_on) / 86400 AS INTEGER) AS days_since_completed,
  ROUND(j.estimated_price, 2) AS estimated_price
FROM job j
JOIN company c ON j.customer_id = c.id
LEFT JOIN location l ON j.location_id = l.id
LEFT JOIN invoice i ON i.job_id = j.id AND i.type = 'invoice' AND i.status != 'void'
WHERE j.status = 'completed'
  AND i.id IS NULL
  AND j.completed_on IS NOT NULL
ORDER BY days_since_completed DESC;
