-- name: report_zzz_quote_acceptance
-- description: Quote acceptance rate by customer — submitted quotes versus accepted, rejected, and still pending.
-- created_at: 2026-04-24T23:04:40Z
DROP VIEW IF EXISTS report_zzz_quote_acceptance;
CREATE VIEW report_zzz_quote_acceptance AS
SELECT
  c.name AS customer,
  CAST(COUNT(q.id) AS INTEGER) AS total_quotes,
  CAST(SUM(CASE WHEN q.status = 'accepted' THEN 1 ELSE 0 END) AS INTEGER) AS accepted,
  CAST(SUM(CASE WHEN q.status = 'rejected' THEN 1 ELSE 0 END) AS INTEGER) AS rejected,
  CAST(SUM(CASE WHEN q.status = 'submitted' THEN 1 ELSE 0 END) AS INTEGER) AS pending,
  CAST(SUM(CASE WHEN q.status IN ('draft','new') THEN 1 ELSE 0 END) AS INTEGER) AS draft,
  CAST(SUM(CASE WHEN q.status = 'canceled' THEN 1 ELSE 0 END) AS INTEGER) AS canceled,
  CAST(ROUND(100.0 * SUM(CASE WHEN q.status = 'accepted' THEN 1 ELSE 0 END) /
    NULLIF(SUM(CASE WHEN q.status IN ('accepted','rejected') THEN 1 ELSE 0 END), 0), 1) AS REAL) AS acceptance_rate_pct,
  CAST(ROUND(SUM(CASE WHEN q.status = 'accepted' THEN q.total_price ELSE 0 END), 2) AS REAL) AS accepted_value
FROM quote q
JOIN company c ON q.customer_id = c.id
GROUP BY c.id, c.name
ORDER BY total_quotes DESC;
