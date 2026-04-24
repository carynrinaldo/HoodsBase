-- name: report_primary_hood_next_service
-- description: For each active location with an active Primary Main Hood service recurrence, show the location name, the date of the last completed hood cleaning job, the recurrence's frequency/interval/price, and the next due date+time (Pacific). Used to plan upcoming hood cleaning work.
-- created_at: 2026-04-24T22:41:37Z
DROP VIEW IF EXISTS report_primary_hood_next_service;
CREATE VIEW report_primary_hood_next_service AS
SELECT
  c.name AS company_name,
  l.name AS location_name,
  datetime(
    (SELECT MAX(j.completed_on) FROM job j WHERE j.location_id = l.id AND j.status = 'completed'),
    'unixepoch', 'localtime'
  ) AS last_completed_job_pacific,
  sr.estimated_price AS primary_hood_price,
  sr.frequency,
  sr.interval,
  datetime(sr.currently_due + COALESCE(sr.preferred_start_time, 0), 'unixepoch', 'localtime') AS next_due_pacific
FROM service_recurrence sr
JOIN location l ON sr.location_id = l.id
JOIN company c ON l.company_id = c.id
WHERE sr.description LIKE 'PrimaryxxxxMainHoodxxxxxx%'
  AND sr.service_line_id = 10
  AND sr.id = sr.current_service_recurrence_id
  AND sr.ends_on IS NULL
  AND l.status = 'active'
  AND c.status = 'active'
ORDER BY sr.currently_due, c.name, l.name;
