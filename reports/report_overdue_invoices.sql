-- name: report_overdue_invoices
-- description: All unpaid, non-void customer invoices where the due date has passed. Shows invoice number, customer name, balance due, due date, and days overdue — sorted by days overdue descending.
-- created_at: 2026-03-20T05:16:49Z
DROP VIEW IF EXISTS report_overdue_invoices;
CREATE VIEW report_overdue_invoices AS
SELECT
  i.id,
  i.invoice_number,
  c.name AS customer_name,
  i.total_price,
  i.total_paid_amount,
  (i.total_price - COALESCE(i.total_paid_amount, 0)) AS balance_due,
  i.status,
  date(i.due_date, 'unixepoch') AS due_date,
  CAST((strftime('%s', 'now') - i.due_date) / 86400 AS INTEGER) AS days_overdue
FROM invoice i
LEFT JOIN company c ON i.customer_id = c.id
WHERE i.is_paid = 0
  AND i.status NOT IN ('void', 'paid')
  AND i.type = 'invoice'
  AND i.due_date IS NOT NULL
  AND i.due_date < strftime('%s', 'now')
ORDER BY days_overdue DESC;
