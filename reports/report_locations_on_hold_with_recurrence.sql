-- name: report_locations_on_hold_with_recurrence
-- description: Locations with an on_hold status that still have active service recurrences — may need attention.
-- created_at: 2026-03-20T20:55:24Z
DROP VIEW IF EXISTS report_locations_on_hold_with_recurrence;
CREATE VIEW report_locations_on_hold_with_recurrence AS
SELECT
  c.name AS customer,
  c.status AS customer_status,
  l.name AS location,
  l.address_city AS city,
  l.status AS location_status,
  COUNT(sr.id) AS active_recurrences,
  MIN(sr.frequency || ' / every ' || sr.interval) AS sample_schedule,
  MAX(date(sr.first_start, 'unixepoch')) AS latest_recurrence_start
FROM location l
JOIN company c ON l.company_id = c.id
JOIN service_recurrence sr ON sr.location_id = l.id
  AND (sr.ends_on IS NULL OR sr.ends_on > strftime('%s','now'))
WHERE l.status IN ('on_hold', 'inactive')
  OR c.status IN ('on_hold', 'inactive')
GROUP BY c.id, c.name, l.id, l.name, l.status
ORDER BY c.name, l.name;
