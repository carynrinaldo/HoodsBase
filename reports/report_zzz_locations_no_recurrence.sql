-- name: report_zzz_locations_no_recurrence
-- description: Active customer locations that have no service recurrence set up — being serviced ad hoc with no contracted schedule.
-- created_at: 2026-04-24T23:02:26Z
DROP VIEW IF EXISTS report_zzz_locations_no_recurrence;
CREATE VIEW report_zzz_locations_no_recurrence AS
SELECT
  c.name AS customer,
  c.status AS customer_status,
  l.name AS location,
  l.address_city AS city,
  l.address_state AS state,
  l.status AS location_status,
  MAX(date(j.completed_on, 'unixepoch')) AS last_service_date
FROM location l
JOIN company c ON l.company_id = c.id
LEFT JOIN service_recurrence sr ON sr.location_id = l.id
  AND (sr.ends_on IS NULL OR sr.ends_on > strftime('%s','now'))
LEFT JOIN job j ON j.location_id = l.id AND j.status = 'completed'
WHERE sr.id IS NULL
  AND l.status = 'active'
  AND c.is_customer = 1
  AND c.status = 'active'
GROUP BY c.id, c.name, l.id, l.name
ORDER BY c.name, l.name;
