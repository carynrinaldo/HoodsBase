-- name: report_primary_hood_next_service_v2
-- description: V2 of report_primary_hood_next_service. Same purpose (Rick's monthly scheduling reference) but with structural fixes: (1) GRAIN CHANGE — one row per active Primary recurrence instead of one row per location, so locations with multiple Primaries (e.g. Salish's Main Hood + Catering Hood on independent quarterly cadences) get separate self-consistent rows. (2) FILTER CHANGE — description LIKE 'Primary%' instead of 'PrimaryxxxxMainHoodxxxxxx%', catching all Primary recurrence types not just Main Hood. (3) HISTORY LOOKUP — joins through service_request.service_recurrence_id traversing the retired/active recurrence chain via current_service_recurrence_id, so price-change history (47% of services point to retired recurrences) is captured. (4) CADENCE ANCHOR — uses service_request.status='closed' on the Primary service rather than job.status='completed', catching the 176 cases where field work is done but job not yet closed. (5) NEW COLUMNS — hood_type (disambiguates Salish's two rows), last_scheduled_job_PT and last_service_status and last_job_status (give Rick visibility into upcoming/in-flight work), state (single derived label: parked/new/canceled/scheduled/field incompletion/pending close/pending close */closed), state_reason (plain-language explanation of how state was derived; safe to hide). (6) NAMING — _Pacific suffixes renamed to _PT. Parked threshold: next_due_PT > today + 18 months.
-- created_at: 2026-04-25T20:37:34Z
DROP VIEW IF EXISTS report_primary_hood_next_service_v2;
CREATE VIEW report_primary_hood_next_service_v2 AS
WITH active_primary_recurrences AS (
  SELECT 
    sr.id AS recurrence_id,
    sr.location_id,
    sr.description,
    sr.frequency,
    sr.interval,
    sr.estimated_price,
    sr.currently_due
  FROM service_recurrence sr
  WHERE sr.description LIKE 'Primary%'
    AND sr.service_line_id = 10
    AND sr.id = sr.current_service_recurrence_id
    AND sr.ends_on IS NULL
),
recurrence_history_chain AS (
  SELECT 
    apr.recurrence_id AS active_id,
    sr_any.id AS historical_id
  FROM active_primary_recurrences apr
  JOIN service_recurrence sr_any 
    ON sr_any.current_service_recurrence_id = apr.recurrence_id
),
last_closed_per_recurrence AS (
  SELECT 
    rhc.active_id AS recurrence_id,
    MAX(j.scheduled_date) AS last_closed_ts
  FROM recurrence_history_chain rhc
  JOIN service_request sreq ON sreq.service_recurrence_id = rhc.historical_id
  JOIN job j ON j.id = sreq.job_id
  WHERE sreq.status = 'closed'
  GROUP BY rhc.active_id
),
last_any_per_recurrence AS (
  SELECT recurrence_id, sreq_status, job_status, job_scheduled_date
  FROM (
    SELECT 
      rhc.active_id AS recurrence_id,
      sreq.status AS sreq_status,
      j.status AS job_status,
      j.scheduled_date AS job_scheduled_date,
      ROW_NUMBER() OVER (PARTITION BY rhc.active_id ORDER BY j.scheduled_date DESC) AS rn
    FROM recurrence_history_chain rhc
    JOIN service_request sreq ON sreq.service_recurrence_id = rhc.historical_id
    JOIN job j ON j.id = sreq.job_id
  )
  WHERE rn = 1
)
SELECT
  c.name AS company_name,
  l.name AS location_name,
  SUBSTR(apr.description, 12, INSTR(SUBSTR(apr.description, 12), 'x') - 1) AS hood_type,
  apr.estimated_price AS primary_hood_price,
  apr.frequency,
  apr.interval,
  date(lcpr.last_closed_ts, 'unixepoch', 'localtime') AS last_completed_job_PT,
  date(lapr.job_scheduled_date, 'unixepoch', 'localtime') AS last_scheduled_job_PT,
  lapr.sreq_status AS last_service_status,
  lapr.job_status AS last_job_status,
  date(apr.currently_due, 'unixepoch', 'localtime') AS next_due_PT,
  CASE
    WHEN lcpr.last_closed_ts IS NULL THEN NULL
    WHEN apr.frequency = 'daily'   THEN date(lcpr.last_closed_ts, 'unixepoch', 'localtime', '+' || apr.interval || ' days')
    WHEN apr.frequency = 'weekly'  THEN date(lcpr.last_closed_ts, 'unixepoch', 'localtime', '+' || (apr.interval * 7) || ' days')
    WHEN apr.frequency = 'monthly' THEN date(lcpr.last_closed_ts, 'unixepoch', 'localtime', '+' || apr.interval || ' months')
    WHEN apr.frequency = 'yearly'  THEN date(lcpr.last_closed_ts, 'unixepoch', 'localtime', '+' || apr.interval || ' years')
  END AS calculated_next_due_PT,
  CASE
    WHEN lcpr.last_closed_ts IS NULL OR apr.currently_due IS NULL THEN NULL
    ELSE CAST(julianday(date(apr.currently_due, 'unixepoch', 'localtime'))
            - julianday(
                CASE apr.frequency
                  WHEN 'daily'   THEN date(lcpr.last_closed_ts, 'unixepoch', 'localtime', '+' || apr.interval || ' days')
                  WHEN 'weekly'  THEN date(lcpr.last_closed_ts, 'unixepoch', 'localtime', '+' || (apr.interval * 7) || ' days')
                  WHEN 'monthly' THEN date(lcpr.last_closed_ts, 'unixepoch', 'localtime', '+' || apr.interval || ' months')
                  WHEN 'yearly'  THEN date(lcpr.last_closed_ts, 'unixepoch', 'localtime', '+' || apr.interval || ' years')
                END
              ) AS INTEGER)
  END AS next_due_vs_calc_due_days,
  CASE
    WHEN apr.currently_due > strftime('%s','now','+18 months') THEN 'parked'
    WHEN lapr.job_scheduled_date IS NULL THEN 'new'
    WHEN lapr.sreq_status = 'canceled' THEN 'canceled'
    WHEN lapr.sreq_status = 'open' AND lapr.job_scheduled_date > strftime('%s','now') THEN 'scheduled'
    WHEN lapr.sreq_status = 'open' AND lapr.job_scheduled_date <= strftime('%s','now') THEN 'field incompletion'
    WHEN lapr.sreq_status = 'closed' AND lapr.job_status != 'completed' 
         AND lapr.job_scheduled_date < strftime('%s','now') - (7 * 86400) THEN 'pending close *'
    WHEN lapr.sreq_status = 'closed' AND lapr.job_status != 'completed' THEN 'pending close'
    WHEN lapr.sreq_status = 'closed' AND lapr.job_status = 'completed' THEN 'closed'
    ELSE 'unknown'
  END AS state,
  CASE
    WHEN apr.currently_due > strftime('%s','now','+18 months') 
      THEN 'next_due_PT (' || date(apr.currently_due, 'unixepoch', 'localtime') || ') is more than 18 months out — parked'
    WHEN lapr.job_scheduled_date IS NULL 
      THEN 'No job history yet; recurrence first due ' || date(apr.currently_due, 'unixepoch', 'localtime')
    WHEN lapr.sreq_status = 'canceled' 
      THEN 'Most recent service (' || date(lapr.job_scheduled_date, 'unixepoch', 'localtime') || ') was canceled'
    WHEN lapr.sreq_status = 'open' AND lapr.job_scheduled_date > strftime('%s','now') 
      THEN 'Future job booked for ' || date(lapr.job_scheduled_date, 'unixepoch', 'localtime') || ', service still open'
    WHEN lapr.sreq_status = 'open' AND lapr.job_scheduled_date <= strftime('%s','now') 
      THEN 'Past job (' || date(lapr.job_scheduled_date, 'unixepoch', 'localtime') || ') still has open service — tech did not mark closed in field'
    WHEN lapr.sreq_status = 'closed' AND lapr.job_status != 'completed' 
         AND lapr.job_scheduled_date < strftime('%s','now') - (7 * 86400) 
      THEN 'Service closed on ' || date(lapr.job_scheduled_date, 'unixepoch', 'localtime') || ' (' || CAST((strftime('%s','now') - lapr.job_scheduled_date) / 86400 AS INTEGER) || ' days ago); job not yet marked completed (>7 day threshold)'
    WHEN lapr.sreq_status = 'closed' AND lapr.job_status != 'completed' 
      THEN 'Service closed ' || date(lapr.job_scheduled_date, 'unixepoch', 'localtime') || '; job not yet marked completed'
    WHEN lapr.sreq_status = 'closed' AND lapr.job_status = 'completed' 
      THEN 'Last visit ' || date(lapr.job_scheduled_date, 'unixepoch', 'localtime') || ' fully closed; awaiting next cadence cycle'
  END AS state_reason
FROM active_primary_recurrences apr
JOIN location l ON apr.location_id = l.id
JOIN company c ON l.company_id = c.id
LEFT JOIN last_closed_per_recurrence lcpr ON lcpr.recurrence_id = apr.recurrence_id
LEFT JOIN last_any_per_recurrence lapr ON lapr.recurrence_id = apr.recurrence_id
WHERE l.status = 'active'
  AND c.status = 'active'
ORDER BY apr.currently_due, c.name, l.name, apr.description;
