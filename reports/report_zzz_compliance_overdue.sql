-- name: report_zzz_compliance_overdue
-- description: Customers with active service recurrence schedules where the time since last completed visit exceeds the scheduled interval. Used to identify locations that are overdue for service based on their contracted frequency.
-- created_at: 2026-04-24T23:00:42Z
DROP VIEW IF EXISTS report_zzz_compliance_overdue;
CREATE VIEW report_zzz_compliance_overdue AS
WITH last_visit AS (
  SELECT
    j.location_id,
    MAX(j.completed_on) AS last_completed_ts
  FROM job j
  WHERE j.status = 'completed'
    AND j.completed_on > strftime('%s', '2023-01-01')
  GROUP BY j.location_id
),
schedule AS (
  SELECT
    c.name AS customer,
    l.name AS location,
    sr.frequency,
    sr.interval,
    CASE sr.frequency
      WHEN 'monthly' THEN sr.interval * 30
      WHEN 'yearly'  THEN sr.interval * 365
      WHEN 'weekly'  THEN sr.interval * 7
    END AS interval_days,
    date(lv.last_completed_ts, 'unixepoch') AS last_completed,
    CAST((strftime('%s','now') - lv.last_completed_ts) / 86400 AS INTEGER) AS days_since_service
  FROM service_recurrence sr
  JOIN location l ON sr.location_id = l.id
  JOIN company c ON l.company_id = c.id
  JOIN last_visit lv ON lv.location_id = l.id
  WHERE (sr.ends_on IS NULL OR sr.ends_on > strftime('%s','now'))
)
SELECT
  customer,
  location,
  frequency,
  interval,
  interval_days,
  last_completed,
  days_since_service,
  days_since_service - interval_days AS days_overdue
FROM schedule
WHERE days_since_service > interval_days
ORDER BY days_since_service - interval_days DESC;
