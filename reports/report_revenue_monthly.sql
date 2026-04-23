-- name: report_revenue_monthly
-- description: Monthly revenue trends by service line, based on invoiced amounts and transaction date.
-- created_at: 2026-03-20T21:11:41Z
DROP VIEW IF EXISTS report_revenue_monthly;
CREATE VIEW report_revenue_monthly AS
SELECT
  strftime('%Y-%m', i.transaction_date, 'unixepoch') AS year_month,
  strftime('%Y', i.transaction_date, 'unixepoch') AS year,
  strftime('%m', i.transaction_date, 'unixepoch') AS month,
  COALESCE(sl.name, 'Unassigned') AS service_line,
  CAST(COUNT(DISTINCT i.id) AS INTEGER) AS invoice_count,
  CAST(ROUND(SUM(ii.subtotal), 2) AS REAL) AS revenue
FROM invoice i
JOIN invoice_item ii ON ii.invoice_id = i.id
LEFT JOIN service_line sl ON ii.service_line_id = sl.id
WHERE i.type = 'invoice'
  AND i.status NOT IN ('void')
  AND i.transaction_date IS NOT NULL
GROUP BY
  strftime('%Y-%m', i.transaction_date, 'unixepoch'),
  COALESCE(sl.name, 'Unassigned')
ORDER BY year_month DESC, revenue DESC;
