-- name: report_primary_hood_next_service
-- description: For each active location with an active Primary Main Hood service recurrence, show the location, the recurrence's price/frequency/interval, the SCHEDULED date of the most recent completed hood-cleaning job (last_completed_job_pacific — sourced from job.scheduled_date because completed_on reflects when the technician marked the job done in the UI, not when work was performed), the next due date (Pacific) per ServiceTrade, the calculated next due date (last scheduled + frequency*interval), the day-of-month of the last completed job, and the drift between ServiceTrade's next due and the calculated next due (positive = ServiceTrade is later than the cadence would suggest). All dates date-only, no time-of-day.
-- created_at: 2026-04-25T00:47:00Z
DROP VIEW IF EXISTS report_primary_hood_next_service;
CREATE VIEW report_primary_hood_next_service AS
WITH base AS (
  SELECT
    c.name AS company_name,
    l.name AS location_name,
    (
      SELECT MAX(j.scheduled_date)
      FROM job j
      WHERE j.location_id = l.id
        AND j.status = 'completed'
    ) AS last_completed_ts,
    sr.estimated_price AS primary_hood_price,
    sr.frequency,
    sr.interval,
    sr.currently_due
  FROM service_recurrence sr
  JOIN location l ON sr.location_id = l.id
  JOIN company c ON l.company_id = c.id
  WHERE sr.description LIKE 'PrimaryxxxxMainHoodxxxxxx%'
    AND sr.service_line_id = 10
    AND sr.id = sr.current_service_recurrence_id
    AND sr.ends_on IS NULL
    AND l.status = 'active'
    AND c.status = 'active'
)
SELECT
  company_name,
  location_name,
  primary_hood_price,
  frequency,
  interval,
  date(last_completed_ts, 'unixepoch', 'localtime') AS last_completed_job_pacific,
  date(currently_due, 'unixepoch', 'localtime') AS next_due_pacific,
  CASE
    WHEN last_completed_ts IS NULL THEN NULL
    WHEN frequency = 'daily'   THEN date(last_completed_ts, 'unixepoch', 'localtime', '+' || interval || ' days')
    WHEN frequency = 'weekly'  THEN date(last_completed_ts, 'unixepoch', 'localtime', '+' || (interval * 7) || ' days')
    WHEN frequency = 'monthly' THEN date(last_completed_ts, 'unixepoch', 'localtime', '+' || interval || ' months')
    WHEN frequency = 'yearly'  THEN date(last_completed_ts, 'unixepoch', 'localtime', '+' || interval || ' years')
    ELSE NULL
  END AS calculated_next_due_pacific,
  CASE
    WHEN last_completed_ts IS NULL THEN NULL
    ELSE CAST(strftime('%d', last_completed_ts, 'unixepoch', 'localtime') AS INTEGER)
  END AS last_completed_job_day_of_month,
  CASE
    WHEN last_completed_ts IS NULL THEN NULL
    WHEN currently_due IS NULL THEN NULL
    ELSE CAST(julianday(date(currently_due, 'unixepoch', 'localtime'))
            - julianday(
                CASE frequency
                  WHEN 'daily'   THEN date(last_completed_ts, 'unixepoch', 'localtime', '+' || interval || ' days')
                  WHEN 'weekly'  THEN date(last_completed_ts, 'unixepoch', 'localtime', '+' || (interval * 7) || ' days')
                  WHEN 'monthly' THEN date(last_completed_ts, 'unixepoch', 'localtime', '+' || interval || ' months')
                  WHEN 'yearly'  THEN date(last_completed_ts, 'unixepoch', 'localtime', '+' || interval || ' years')
                END
              ) AS INTEGER)
  END AS next_due_vs_calc_due_days
FROM base
ORDER BY currently_due, company_name, location_name;
