-- name: report_zzz_customer_churn_risk
-- description: Customers who had completed jobs in 2023 or 2024 but have no completed or scheduled jobs in 2025 — potential churn.
-- created_at: 2026-04-24T23:00:59Z
DROP VIEW IF EXISTS report_zzz_customer_churn_risk;
CREATE VIEW report_zzz_customer_churn_risk AS
SELECT
  c.name AS customer,
  c.status AS customer_status,
  MAX(date(j_past.completed_on, 'unixepoch')) AS last_completed_job,
  COUNT(DISTINCT j_past.id) AS jobs_2023_2024
FROM company c
JOIN job j_past ON j_past.customer_id = c.id
  AND j_past.status = 'completed'
  AND strftime('%Y', j_past.completed_on, 'unixepoch') IN ('2023', '2024')
LEFT JOIN job j_2025 ON j_2025.customer_id = c.id
  AND j_2025.status IN ('completed', 'scheduled', 'new')
  AND strftime('%Y', COALESCE(j_2025.completed_on, j_2025.scheduled_date), 'unixepoch') = '2025'
WHERE j_2025.id IS NULL
  AND c.is_customer = 1
GROUP BY c.id, c.name, c.status
ORDER BY last_completed_job DESC;
