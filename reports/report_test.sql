-- name: report_test
-- description: Test
-- created_at: 2026-03-20T05:07:26Z
CREATE OR REPLACE VIEW report_test AS
SELECT id, status, total_price FROM invoice WHERE is_paid = 0;
