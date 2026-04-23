-- name: report_jobs_pending_invoice
-- description: Jobs stuck in pending_invoice or sending_invoice status — completed work that hasn't been billed yet.
-- created_at: 2026-03-20T20:54:12Z
DROP VIEW IF EXISTS report_jobs_pending_invoice;
CREATE VIEW report_jobs_pending_invoice AS
SELECT
  c.name AS customer,
  l.name AS location,
  l.address_city AS city,
  j.number AS job_number,
  j.name AS job_name,
  j.type AS job_type,
  j.status,
  j.service_line,
  date(j.completed_on, 'unixepoch') AS completed_on,
  CAST((strftime('%s','now') - j.completed_on) / 86400 AS INTEGER) AS days_since_completed,
  ROUND(j.estimated_price, 2) AS estimated_price
FROM job j
JOIN company c ON j.customer_id = c.id
LEFT JOIN location l ON j.location_id = l.id
WHERE j.status IN ('pending_invoice', 'sending_invoice')
ORDER BY days_since_completed DESC;
