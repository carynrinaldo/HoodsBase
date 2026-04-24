-- name: report_zzz_revenue_by_customer
-- description: Total revenue by customer across all non-void invoices, ranked highest to lowest.
-- created_at: 2026-04-24T23:05:22Z
DROP VIEW IF EXISTS report_zzz_revenue_by_customer;
CREATE VIEW report_zzz_revenue_by_customer AS
SELECT
  c.name AS customer,
  c.status AS customer_status,
  CAST(COUNT(i.id) AS INTEGER) AS invoice_count,
  CAST(ROUND(SUM(i.total_price), 2) AS REAL) AS total_invoiced,
  CAST(ROUND(SUM(i.total_paid_amount), 2) AS REAL) AS total_paid,
  CAST(ROUND(SUM(i.total_price - COALESCE(i.total_paid_amount, 0)), 2) AS REAL) AS total_outstanding
FROM invoice i
JOIN company c ON i.customer_id = c.id
WHERE i.type = 'invoice'
  AND i.status NOT IN ('void')
GROUP BY c.id, c.name, c.status
ORDER BY total_invoiced DESC;
