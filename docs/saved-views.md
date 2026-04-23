# Saved Views — User-Created Reports via Claude

> **Status: Implemented.** The tools described here (`create_view`, `list_views`, `drop_view`) are live in `mcp/server.py`. The `reports/` backup directory and `create_db.py` restoration logic are also in place.



## Problem

The CFO wants to ask Claude ad hoc questions, review the results, and then save useful queries as named reports he can pull into Excel or Access anytime — without needing Claude in the loop for repeat access.

## Solution

SQLite views act as saved reports. Claude creates them on demand during conversation, and they appear as named tables in the CFO's ODBC connection.

### User Workflow

1. CFO asks Claude a natural language question (e.g., "Show me all invoices over $500 that are past due")
2. Claude writes and executes a SELECT query via `execute_query`, returns results
3. CFO reviews the results and says "Save that as the Large Past Due report"
4. Claude calls `create_view` to persist the query as a named SQLite view
5. The view immediately appears in the CFO's Excel/Access ODBC connection as a table he can refresh at will

### Why Views Work Here

- A SQLite view is just a named SELECT — it stores the query, not the data
- Every time the CFO refreshes in Excel, the view runs against current data
- Views show up alongside tables in ODBC — no special configuration needed
- No stored procedure support is needed; views cover this use case cleanly

## MCP Tools

### `create_view(name, sql)`

Creates a named SQLite view from a SELECT statement.

**Behavior:**
- Validate that `sql` is a SELECT statement (reject anything else)
- Enforce a naming convention: all views prefixed with `report_` (e.g., `report_large_past_due`)
- Validate that the SELECT executes successfully before creating the view
- Use `CREATE VIEW IF NOT EXISTS` to avoid errors on duplicate names, or `CREATE OR REPLACE VIEW` to allow updates
- Log the creation (view name, timestamp, original natural language question if available)

**Guardrails:**
- Only SELECT statements allowed in the view body
- View names must match `report_[a-z0-9_]+` pattern
- Claude should confirm the view name with the CFO before creating it

### `list_views()`

Returns all user-created views (filtered to `report_` prefix).

**Returns:** view name, SQL definition, creation metadata.

**Use case:** Claude can remind the CFO what reports already exist, avoid duplicates, and help manage the library over time.

### `drop_view(name)`

Drops a named view.

**Behavior:**
- Only allows dropping views with the `report_` prefix (protects any system views)
- Confirms the view exists before attempting to drop

**Use case:** CFO says "I don't need the XYZ report anymore" — Claude removes it.

## Integration with Existing Architecture

- The `execute_query` tool remains SELECT-only — no changes needed
- View management is handled by dedicated tools with their own validation
- Views are stored in the same SQLite database file (bind-mounted), so they persist across container restarts
- The ODBC connection on the host sees views automatically — no reconfiguration after adding a new view

## Open Questions

- Should there be a limit on the number of saved views?
- Should view definitions be backed up or exported separately (e.g., as a `.sql` file) in case the database is recreated from schema?
- Should Claude track the original natural language question that prompted each view, so it can explain what a report does later?
