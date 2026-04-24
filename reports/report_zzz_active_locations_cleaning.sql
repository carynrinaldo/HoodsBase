-- name: report_zzz_active_locations_cleaning
-- description: Active locations with KEC (Kitchen Exhaust Cleaning) service details, including last and next cleaning dates and service interval frequency.
-- created_at: 2026-04-24T22:59:29Z
DROP VIEW IF EXISTS report_zzz_active_locations_cleaning;
CREATE VIEW report_zzz_active_locations_cleaning AS
WITH latest_recurrence AS (
  SELECT
    sr.location_id,
    sr.frequency,
    sr.interval,
    sr.frequency_category,
    ROW_NUMBER() OVER (PARTITION BY sr.location_id ORDER BY sr.created_at DESC) AS rn
  FROM service_recurrence sr
  JOIN service_line sl ON sl.id = sr.service_line_id
  WHERE sl.abbr = 'KEC'
)
SELECT
  l.name AS location_name,
  c.name AS company_name,
  l.address_street,
  l.address_city,
  l.address_state,
  l.address_postal,
  date(MAX(CASE WHEN j.status = 'completed' THEN j.scheduled_date END), 'unixepoch') AS last_cleaning_date,
  date(MIN(CASE WHEN j.scheduled_date > strftime('%s', 'now') AND j.status NOT IN ('canceled') THEN j.scheduled_date END), 'unixepoch') AS next_cleaning_date,
  CASE lr.frequency
    WHEN 'weekly'  THEN 'Every ' || lr.interval || ' week(s)'
    WHEN 'monthly' THEN 'Every ' || lr.interval || ' month(s)'
    WHEN 'yearly'  THEN 'Every ' || lr.interval || ' year(s)'
    WHEN 'daily'   THEN 'Every ' || lr.interval || ' day(s)'
    ELSE lr.frequency_category
  END AS service_interval
FROM location l
JOIN company c ON l.company_id = c.id
LEFT JOIN job j ON j.location_id = l.id AND j.type = 'cleaning'
LEFT JOIN latest_recurrence lr ON lr.location_id = l.id AND lr.rn = 1
WHERE l.status = 'active'
GROUP BY l.id, l.name, c.name, l.address_street, l.address_city, l.address_state, l.address_postal, lr.frequency, lr.interval, lr.frequency_category
ORDER BY l.name;
