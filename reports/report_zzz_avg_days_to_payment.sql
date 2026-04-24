-- name: report_zzz_avg_days_to_payment
-- description: Average days from invoice transaction date to paid status, by customer. Only includes invoices marked as paid.
-- created_at: 2026-04-24T23:00:25Z
DROP VIEW IF EXISTS report_zzz_avg_days_to_payment;
CREATE VIEW report_zzz_avg_days_to_payment AS
SELECT
  c.name AS customer,
  CAST(COUNT(i.id) AS INTEGER) AS paid_invoices,
  CAST(ROUND(AVG(CAST((i.updated_at - i.transaction_date) / 86400 AS INTEGER)), 1) AS REAL) AS avg_days_to_payment,
  CAST(MIN(CAST((i.updated_at - i.transaction_date) / 86400 AS INTEGER)) AS INTEGER) AS min_days,
  CAST(MAX(CAST((i.updated_at - i.transaction_date) / 86400 AS INTEGER)) AS INTEGER) AS max_days
FROM invoice i
JOIN company c ON i.customer_id = c.id
WHERE i.is_paid = 1
  AND i.type = 'invoice'
  AND i.transaction_date IS NOT NULL
GROUP BY c.id, c.name
ORDER BY avg_days_to_payment DESC;
