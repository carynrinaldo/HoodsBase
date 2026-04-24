-- name: report_zzz_technician_workload
-- description: Technician workload summary — completed jobs and appointments per user.
-- created_at: 2026-04-24T23:08:03Z
DROP VIEW IF EXISTS report_zzz_technician_workload;
CREATE VIEW report_zzz_technician_workload AS
SELECT
  u.name AS technician,
  u.email,
  CAST(COUNT(DISTINCT j.id) AS INTEGER) AS completed_jobs,
  CAST(COUNT(DISTINCT a.id) AS INTEGER) AS total_appointments,
  MIN(date(j.completed_on, 'unixepoch')) AS first_job,
  MAX(date(j.completed_on, 'unixepoch')) AS last_job,
  CAST(ROUND(AVG(CAST((a.window_end - a.window_start) / 3600.0 AS REAL)), 1) AS REAL) AS avg_appointment_hours
FROM user u
LEFT JOIN job j ON j.owner_id = u.id AND j.status = 'completed'
LEFT JOIN appointment a ON a.job_id = j.id AND a.status = 'completed'
WHERE u.is_tech = 1
  AND u.status = 'active'
GROUP BY u.id, u.name, u.email
ORDER BY completed_jobs DESC;
