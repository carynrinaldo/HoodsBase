-- name: report_zzz_appointment_cancellations
-- description: Appointment cancellations broken down by whether they were canceled by the customer or the vendor, with customer and location detail.
-- created_at: 2026-04-24T22:59:37Z
DROP VIEW IF EXISTS report_zzz_appointment_cancellations;
CREATE VIEW report_zzz_appointment_cancellations AS
SELECT
  c.name AS customer,
  l.name AS location,
  l.address_city AS city,
  a.status AS cancellation_type,
  CAST(COUNT(a.id) AS INTEGER) AS cancellation_count,
  MIN(date(a.window_start, 'unixepoch')) AS earliest,
  MAX(date(a.window_start, 'unixepoch')) AS most_recent
FROM appointment a
JOIN job j ON a.job_id = j.id
JOIN company c ON j.customer_id = c.id
LEFT JOIN location l ON a.location_id = l.id
WHERE a.status IN ('canceled_by_customer', 'canceled_by_vendor')
GROUP BY c.id, c.name, l.id, l.name, a.status
ORDER BY cancellation_count DESC;
