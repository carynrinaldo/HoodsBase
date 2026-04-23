-- name: report_asset_inventory
-- description: Equipment/asset inventory by location and service line, showing active assets with their type and properties.
-- created_at: 2026-03-20T21:22:02Z
DROP VIEW IF EXISTS report_asset_inventory;
CREATE VIEW report_asset_inventory AS
SELECT
  c.name AS customer,
  l.name AS location,
  l.address_city AS city,
  sl.name AS service_line,
  a.display AS asset_type,
  a.name AS asset_name,
  a.status AS asset_status,
  CAST(COUNT(a.id) AS INTEGER) AS asset_count
FROM asset a
JOIN location l ON a.location_id = l.id
JOIN company c ON l.company_id = c.id
LEFT JOIN service_line sl ON a.service_line_id = sl.id
WHERE a.status = 'active'
  AND a.is_abstract_group = 0
GROUP BY c.id, c.name, l.id, l.name, sl.name, a.display
ORDER BY c.name, l.name, sl.name, a.display;
