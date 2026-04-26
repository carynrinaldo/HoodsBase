-- name: report_primary_hood_next_service_v3
-- description: V3 of report_primary_hood_next_service. Same purpose (Rick's monthly scheduling reference). Iterates on v2 with: (1) Cadence formula updated — Calc Next Due Date is derived from MAX(last scheduled job, last completed job) + cadence interval. When BOTH are NULL, it passes through ST Next Due as-is so Rick's filters always see a value. (2) Row Status `new` split into two — `new (unscheduled)` (no history, no future job) and `new (scheduled)` (no history, first job booked). (3) Column names use spaces and double-quoting for Excel-friendly headers. (4) `Last Sched Job Status` and `Last Sched Job Primary Svc Status` columns dropped — info is rolled into Row Status / Row Status Reason. (5) Reason text rewritten in user's preferred phrasing throughout. (6) `cancelled` spelled with two L's in human-facing text (matches user's old-school spelling preference); database enum stays `canceled`. (7) Canceled services are FILTERED OUT entirely from the most-recent lookup — they don't anchor anything. (8) `cancelled` row status bucket dropped — when most recent service is canceled but a prior closed one exists, the row falls through to `closed` bucket with a soft signal " (a more recent attempt was cancelled)" appended to the reason text. (9) Parked threshold: next_due_PT > today + 18 months. Sort: ORDER BY Calc Next Due Date ASC NULLS FIRST. (10) Re-added "Last Compl Job DOM" column (day of month from Last Compl Job) — Rick's quick anchor for "what part of the month does this customer normally get serviced." Positioned just before Row Status.
-- created_at: 2026-04-26T18:02:29Z
DROP VIEW IF EXISTS report_primary_hood_next_service_v3;
CREATE VIEW report_primary_hood_next_service_v3 AS
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
last_noncanceled_per_recurrence AS (
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
    WHERE sreq.status != 'canceled'
  )
  WHERE rn = 1
),
last_canceled_per_recurrence AS (
  SELECT recurrence_id, MAX(job_scheduled_date) AS last_canceled_ts
  FROM (
    SELECT 
      rhc.active_id AS recurrence_id,
      j.scheduled_date AS job_scheduled_date
    FROM recurrence_history_chain rhc
    JOIN service_request sreq ON sreq.service_recurrence_id = rhc.historical_id
    JOIN job j ON j.id = sreq.job_id
    WHERE sreq.status = 'canceled'
  )
  GROUP BY recurrence_id
),
calc_inputs AS (
  SELECT
    apr.recurrence_id,
    apr.location_id,
    apr.description,
    apr.frequency,
    apr.interval,
    apr.estimated_price,
    apr.currently_due,
    lcpr.last_closed_ts,
    lncpr.sreq_status,
    lncpr.job_status,
    lncpr.job_scheduled_date,
    lcanpr.last_canceled_ts,
    CASE
      WHEN lncpr.job_scheduled_date IS NOT NULL THEN lncpr.job_scheduled_date
      WHEN lcpr.last_closed_ts IS NOT NULL THEN lcpr.last_closed_ts
      ELSE NULL
    END AS calc_anchor_ts,
    CASE
      WHEN lcanpr.last_canceled_ts IS NOT NULL
        AND (lncpr.job_scheduled_date IS NULL OR lcanpr.last_canceled_ts > lncpr.job_scheduled_date)
      THEN 1 ELSE 0
    END AS has_more_recent_cancellation
  FROM active_primary_recurrences apr
  LEFT JOIN last_closed_per_recurrence lcpr ON lcpr.recurrence_id = apr.recurrence_id
  LEFT JOIN last_noncanceled_per_recurrence lncpr ON lncpr.recurrence_id = apr.recurrence_id
  LEFT JOIN last_canceled_per_recurrence lcanpr ON lcanpr.recurrence_id = apr.recurrence_id
)
SELECT
  c.name AS "Company Name",
  l.name AS "Location Name",
  SUBSTR(ci.description, 12, INSTR(SUBSTR(ci.description, 12), 'x') - 1) AS "Primary Type",
  ci.estimated_price AS "Primary Price",
  ci.frequency AS "Frequency",
  ci.interval AS "Interval",
  date(ci.last_closed_ts, 'unixepoch', 'localtime') AS "Last Compl Job",
  date(ci.job_scheduled_date, 'unixepoch', 'localtime') AS "Last Sched Job",
  date(ci.currently_due, 'unixepoch', 'localtime') AS "ST Next Due Date",
  CASE
    WHEN ci.calc_anchor_ts IS NULL AND ci.currently_due IS NOT NULL 
      THEN date(ci.currently_due, 'unixepoch', 'localtime')
    WHEN ci.calc_anchor_ts IS NULL THEN NULL
    WHEN ci.frequency = 'daily'   THEN date(ci.calc_anchor_ts, 'unixepoch', 'localtime', '+' || ci.interval || ' days')
    WHEN ci.frequency = 'weekly'  THEN date(ci.calc_anchor_ts, 'unixepoch', 'localtime', '+' || (ci.interval * 7) || ' days')
    WHEN ci.frequency = 'monthly' THEN date(ci.calc_anchor_ts, 'unixepoch', 'localtime', '+' || ci.interval || ' months')
    WHEN ci.frequency = 'yearly'  THEN date(ci.calc_anchor_ts, 'unixepoch', 'localtime', '+' || ci.interval || ' years')
  END AS "Calc Next Due Date",
  CASE
    WHEN ci.calc_anchor_ts IS NULL OR ci.currently_due IS NULL THEN NULL
    ELSE CAST(julianday(date(ci.currently_due, 'unixepoch', 'localtime'))
            - julianday(
                CASE
                  WHEN ci.frequency = 'daily'   THEN date(ci.calc_anchor_ts, 'unixepoch', 'localtime', '+' || ci.interval || ' days')
                  WHEN ci.frequency = 'weekly'  THEN date(ci.calc_anchor_ts, 'unixepoch', 'localtime', '+' || (ci.interval * 7) || ' days')
                  WHEN ci.frequency = 'monthly' THEN date(ci.calc_anchor_ts, 'unixepoch', 'localtime', '+' || ci.interval || ' months')
                  WHEN ci.frequency = 'yearly'  THEN date(ci.calc_anchor_ts, 'unixepoch', 'localtime', '+' || ci.interval || ' years')
                END
              ) AS INTEGER)
  END AS "ST vs Calc Next Due Days Diff",
  CASE
    WHEN ci.last_closed_ts IS NULL THEN NULL
    ELSE CAST(strftime('%d', ci.last_closed_ts, 'unixepoch', 'localtime') AS INTEGER)
  END AS "Last Compl Job DOM",
  CASE
    WHEN ci.currently_due > strftime('%s','now','+18 months') THEN 'parked'
    WHEN ci.last_closed_ts IS NULL AND ci.job_scheduled_date IS NULL THEN 'new (unscheduled)'
    WHEN ci.last_closed_ts IS NULL AND ci.job_scheduled_date IS NOT NULL THEN 'new (scheduled)'
    WHEN ci.sreq_status = 'open' AND ci.job_scheduled_date > strftime('%s','now') THEN 'scheduled'
    WHEN ci.sreq_status = 'open' AND ci.job_scheduled_date <= strftime('%s','now') THEN 'field incompletion'
    WHEN ci.sreq_status = 'closed' AND ci.job_status != 'completed' 
         AND ci.job_scheduled_date < strftime('%s','now') - (7 * 86400) THEN 'pending close *'
    WHEN ci.sreq_status = 'closed' AND ci.job_status != 'completed' THEN 'pending close'
    WHEN ci.sreq_status = 'closed' AND ci.job_status = 'completed' THEN 'closed'
    ELSE 'unknown'
  END AS "Row Status",
  CASE
    WHEN ci.currently_due > strftime('%s','now','+18 months') 
      THEN 'Next Due ' || date(ci.currently_due, 'unixepoch', 'localtime') || ' > 18m out — parked'
    WHEN ci.last_closed_ts IS NULL AND ci.job_scheduled_date IS NULL 
      THEN 'No job history and no job scheduled yet. Next Due ' || date(ci.currently_due, 'unixepoch', 'localtime') || '.'
    WHEN ci.last_closed_ts IS NULL AND ci.job_scheduled_date IS NOT NULL 
      THEN 'No job history. First job scheduled for ' || date(ci.job_scheduled_date, 'unixepoch', 'localtime') || '.'
    WHEN ci.sreq_status = 'open' AND ci.job_scheduled_date > strftime('%s','now') 
      THEN 'Future job scheduled for ' || date(ci.job_scheduled_date, 'unixepoch', 'localtime') || ' (primary service open)'
    WHEN ci.sreq_status = 'open' AND ci.job_scheduled_date <= strftime('%s','now') 
      THEN 'Past job ' || date(ci.job_scheduled_date, 'unixepoch', 'localtime') || ' still has open primary service — tech did not mark closed in field'
    WHEN ci.sreq_status = 'closed' AND ci.job_status != 'completed' 
         AND ci.job_scheduled_date < strftime('%s','now') - (7 * 86400) 
      THEN 'Primary service for ' || date(ci.job_scheduled_date, 'unixepoch', 'localtime') || ' job marked closed (' || CAST((strftime('%s','now') - ci.job_scheduled_date) / 86400 AS INTEGER) || 'd ago), but job not yet marked complete'
    WHEN ci.sreq_status = 'closed' AND ci.job_status != 'completed' 
      THEN 'Primary service for ' || date(ci.job_scheduled_date, 'unixepoch', 'localtime') || ' job marked closed (' || CAST((strftime('%s','now') - ci.job_scheduled_date) / 86400 AS INTEGER) || 'd ago), but job not yet marked complete'
    WHEN ci.sreq_status = 'closed' AND ci.job_status = 'completed' AND ci.has_more_recent_cancellation = 1
      THEN 'Last scheduled job ' || date(ci.job_scheduled_date, 'unixepoch', 'localtime') || ' closed; awaiting release of next job (a more recent attempt was cancelled)'
    WHEN ci.sreq_status = 'closed' AND ci.job_status = 'completed' 
      THEN 'Last scheduled job ' || date(ci.job_scheduled_date, 'unixepoch', 'localtime') || ' closed; awaiting release of next job'
  END AS "Row Status Reason"
FROM calc_inputs ci
JOIN location l ON ci.location_id = l.id
JOIN company c ON l.company_id = c.id
WHERE l.status = 'active'
  AND c.status = 'active'
ORDER BY 
  CASE
    WHEN ci.calc_anchor_ts IS NULL AND ci.currently_due IS NOT NULL THEN ci.currently_due
    WHEN ci.calc_anchor_ts IS NULL THEN NULL
    WHEN ci.frequency = 'daily'   THEN strftime('%s', date(ci.calc_anchor_ts, 'unixepoch', 'localtime', '+' || ci.interval || ' days'))
    WHEN ci.frequency = 'weekly'  THEN strftime('%s', date(ci.calc_anchor_ts, 'unixepoch', 'localtime', '+' || (ci.interval * 7) || ' days'))
    WHEN ci.frequency = 'monthly' THEN strftime('%s', date(ci.calc_anchor_ts, 'unixepoch', 'localtime', '+' || ci.interval || ' months'))
    WHEN ci.frequency = 'yearly'  THEN strftime('%s', date(ci.calc_anchor_ts, 'unixepoch', 'localtime', '+' || ci.interval || ' years'))
  END,
  c.name, l.name, ci.description;
