-- name: report_ar_aging
-- description: Accounts receivable aging report bucketed into current, 1-30, 31-60, 61-90, and 90+ day buckets by customer.
-- created_at: 2026-03-20T21:20:20Z
DROP VIEW IF EXISTS report_ar_aging;
CREATE VIEW report_ar_aging AS
SELECT
  c.name AS customer,
  CAST(COUNT(i.id) AS INTEGER) AS invoice_count,
  CAST(ROUND(SUM(i.total_price - COALESCE(i.total_paid_amount, 0)), 2) AS REAL) AS total_outstanding,
  CAST(ROUND(SUM(CASE WHEN CAST((strftime('%s','now') - i.due_date) / 86400 AS INTEGER) <= 0 THEN i.total_price - COALESCE(i.total_paid_amount, 0) ELSE 0 END), 2) AS REAL) AS current_due,
  CAST(ROUND(SUM(CASE WHEN CAST((strftime('%s','now') - i.due_date) / 86400 AS INTEGER) BETWEEN 1 AND 30 THEN i.total_price - COALESCE(i.total_paid_amount, 0) ELSE 0 END), 2) AS REAL) AS days_1_30,
  CAST(ROUND(SUM(CASE WHEN CAST((strftime('%s','now') - i.due_date) / 86400 AS INTEGER) BETWEEN 31 AND 60 THEN i.total_price - COALESCE(i.total_paid_amount, 0) ELSE 0 END), 2) AS REAL) AS days_31_60,
  CAST(ROUND(SUM(CASE WHEN CAST((strftime('%s','now') - i.due_date) / 86400 AS INTEGER) BETWEEN 61 AND 90 THEN i.total_price - COALESCE(i.total_paid_amount, 0) ELSE 0 END), 2) AS REAL) AS days_61_90,
  CAST(ROUND(SUM(CASE WHEN CAST((strftime('%s','now') - i.due_date) / 86400 AS INTEGER) > 90 THEN i.total_price - COALESCE(i.total_paid_amount, 0) ELSE 0 END), 2) AS REAL) AS days_90_plus
FROM invoice i
JOIN company c ON i.customer_id = c.id
WHERE i.is_paid = 0
  AND i.status NOT IN ('void')
  AND i.type = 'invoice'
GROUP BY c.id, c.name
HAVING CAST(ROUND(SUM(i.total_price - COALESCE(i.total_paid_amount, 0)), 2) AS REAL) > 0
ORDER BY total_outstanding DESC;
