-- name: report_stale_quotes
-- description: Open quotes (submitted or draft) that have not been acted on in 30+ days, potential stalled deals.
-- created_at: 2026-03-20T20:55:16Z
DROP VIEW IF EXISTS report_stale_quotes;
CREATE VIEW report_stale_quotes AS
SELECT
  c.name AS customer,
  l.name AS location,
  l.address_city AS city,
  q.name AS quote_name,
  q.status,
  q.substatus,
  ROUND(q.total_price, 2) AS quote_value,
  date(q.latest_submission, 'unixepoch') AS last_submitted,
  date(q.created_at, 'unixepoch') AS created_on,
  CAST((strftime('%s','now') - COALESCE(q.latest_submission, q.created_at)) / 86400 AS INTEGER) AS days_stale,
  date(q.expires_on, 'unixepoch') AS expires_on
FROM quote q
JOIN company c ON q.customer_id = c.id
LEFT JOIN location l ON q.location_id = l.id
WHERE q.status IN ('submitted', 'draft', 'new')
  AND CAST((strftime('%s','now') - COALESCE(q.latest_submission, q.created_at)) / 86400 AS INTEGER) >= 30
ORDER BY days_stale DESC;
