#!/usr/bin/env python3
"""hoodsbase MCP Server — gives Claude read-only access to the business database."""

import json
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "hoodsbase.db")
SCHEMA_PATH = os.path.join(ROOT, "schema", "schema.sql")
LOG_PATH = os.path.join(ROOT, "logs", "pipeline.log")
DEFAULT_ROW_LIMIT = 1000

# All logging to stderr — stdout is the JSON-RPC channel
logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("hoodsbase-mcp")

# ---------------------------------------------------------------------------
# Database helper
# ---------------------------------------------------------------------------
DISALLOWED_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|ATTACH|DETACH|PRAGMA|REPLACE)\b",
    re.IGNORECASE,
)


def get_connection():
    """Open a read-only SQLite connection with per-connection PRAGMAs."""
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"Database not found: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA cache_size = -8000")
    return conn


def validate_select_sql(sql: str) -> str:
    """Validate that sql is a read-only SELECT/WITH statement.

    Returns the stripped SQL (no LIMIT injection). Raises ValueError on failure.
    Used by both validate_query and create_view.
    """
    stripped = sql.strip().rstrip(";")
    if not stripped:
        raise ValueError("Empty query")

    first_word = stripped.split()[0].upper()
    if first_word not in ("SELECT", "WITH"):
        raise ValueError(
            f"Only SELECT queries are allowed. Got: {first_word}"
        )

    if DISALLOWED_KEYWORDS.search(stripped):
        match = DISALLOWED_KEYWORDS.search(stripped)
        raise ValueError(
            f"Disallowed keyword: {match.group(0).upper()}"
        )

    return stripped


def validate_query(sql: str) -> str:
    """Validate and sanitise a SQL query. Returns the (possibly modified) SQL.

    Raises ValueError if the query is not a read-only SELECT/WITH statement.
    Appends a default LIMIT if none is present.
    """
    stripped = validate_select_sql(sql)

    # Append default LIMIT if none present
    if not re.search(r"\bLIMIT\b", stripped, re.IGNORECASE):
        stripped = f"{stripped} LIMIT {DEFAULT_ROW_LIMIT}"

    return stripped


def get_write_connection():
    """Open a writable SQLite connection for view management tools."""
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"Database not found: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


# ---------------------------------------------------------------------------
# Server instructions (delivered to clients on connect)
# ---------------------------------------------------------------------------
with open(SCHEMA_PATH) as _f:
    _schema_sql = _f.read()

INSTRUCTIONS = f"""\
You are a BI assistant for a commercial hood cleaning company.
You have read-only access to a SQLite database synced nightly from ServiceTrade.

## Tools
- execute_query(sql) — Run a SELECT query. LIMIT 1000 auto-applied if omitted.
- get_sync_status() — Check data freshness (last sync time per resource).
- run_sync(resource, full) — Run a data sync from ServiceTrade. Defaults to incremental sync of all resources. Pass a resource name (e.g. "invoice") to sync one, or full=True to re-pull everything.
- read_log(lines) — Tail the pipeline log file (default 100 lines). Use when troubleshooting sync failures or errors.
- create_view(name, description, sql) — Save a SELECT query as a named SQLite view. The name must start with report_ (e.g. report_large_past_due). Always confirm the name with the user before calling. Do NOT add a LIMIT — views must return all rows for ODBC consumers.
- list_views() — List all saved report views with their descriptions and SQL definitions.
- drop_view(name) — Remove a saved report view by name.

## How to answer
1. The full schema is below — do NOT call get_schema().
2. Write SQL using aggregations to keep results small.
3. Call execute_query() with your SQL.
4. Return a conversational answer. Use formatted tables for data-heavy responses.

## Saving reports
- Only save a report when the user explicitly asks to save it.
- Confirm the proposed view name (report_ prefix, snake_case) with the user before calling create_view().
- Pass the user's original question as the description so it can be recalled later.
- Never inject LIMIT into view SQL — views are consumed by ODBC and must return all rows.
- Always CAST computed columns to explicit types in view SQL: use CAST(... AS INTEGER) for counts and whole numbers, CAST(... AS REAL) for decimals and rounded values. SQLite's loose typing means the ODBC driver cannot infer column types for aggregate expressions (COUNT, SUM, ROUND, AVG, etc.), causing Excel Power Query to silently drop the values and show blanks.

## Refining reports
- create_view() replaces the view if one with the same name already exists — no need to drop it first.
- When the user asks to modify or extend an existing report, call list_views() first to retrieve the current SQL, then modify it and call create_view() with the same name.
- Show the user a diff-style summary of what changed (columns added, joins modified, filters applied) rather than the full SQL.
- Do not ask for confirmation before updating — the user has already named the report and approved the refinement.
- Update the description parameter to reflect the report's current purpose after each refinement.

## Database schema

```sql
{_schema_sql}
```"""

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------
mcp = FastMCP("hoodsbase", instructions=INSTRUCTIONS)


@mcp.resource("hoodsbase://schema")
def schema_resource() -> str:
    """The annotated hoodsbase database schema."""
    with open(SCHEMA_PATH) as f:
        return f.read()


@mcp.tool()
def execute_query(sql: str) -> str:
    """Run a read-only SQL query against the hoodsbase database.

    Returns results as a JSON array of objects. Only SELECT statements are
    allowed. A default LIMIT of 1000 rows is applied if none is specified.
    Use SQL aggregations (COUNT, SUM, AVG, GROUP BY) to keep result sets small.
    """
    try:
        sql = validate_query(sql)
    except ValueError as e:
        return f"Error: {e}"

    try:
        conn = get_connection()
        rows = conn.execute(sql).fetchall()
        result = [dict(row) for row in rows]
        conn.close()
        return json.dumps(result, default=str)
    except Exception as e:
        return f"SQLite error: {e}"


@mcp.tool()
def get_sync_status() -> str:
    """Check data freshness. Returns the last sync time and record count
    for each resource in the database."""
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT resource, last_synced_at_dt, record_count "
            "FROM sync_status ORDER BY resource"
        ).fetchall()
        result = [dict(row) for row in rows]
        conn.close()
        return json.dumps(result, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def get_schema() -> str:
    """Return the annotated database schema (CREATE TABLE statements with
    comments explaining each table and column)."""
    try:
        with open(SCHEMA_PATH) as f:
            return f.read()
    except FileNotFoundError:
        return f"Error: Schema file not found: {SCHEMA_PATH}"


@mcp.tool()
def read_log(lines: int = 100) -> str:
    """Return the last N lines of the pipeline log file.

    Use this when troubleshooting sync failures, errors, or unexpected
    behaviour. The log covers all pipeline scripts (sync, schema generation,
    database setup) and includes timestamps, module names, and log levels.

    Args:
        lines: Number of lines to return from the end of the log (default 100).
    """
    if not os.path.exists(LOG_PATH):
        return "No pipeline log found. The pipeline may not have run yet."
    try:
        with open(LOG_PATH, encoding="utf-8") as f:
            all_lines = f.readlines()
        tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
        return "".join(tail)
    except Exception as e:
        return f"Error reading log: {e}"


REPORTS_DIR = os.path.join(ROOT, "reports")
VIEW_NAME_RE = re.compile(r"^report_[a-z0-9_]+$")
_CREATE_METADATA_SQL = """
    CREATE TABLE IF NOT EXISTS report_metadata (
        name        TEXT PRIMARY KEY,
        description TEXT,
        sql         TEXT,
        created_at  TEXT
    )
"""


@mcp.tool()
def create_view(name: str, description: str, sql: str) -> str:
    """Save a SELECT query as a named SQLite view (persisted report).

    The view appears immediately in any ODBC connection to the database and
    returns live data on every refresh. A backup .sql file is written to the
    reports/ directory so the view can be restored if the database is recreated.

    Args:
        name: View name, must match report_[a-z0-9_]+ (e.g. report_past_due).
        description: The original question or context that prompted this report.
        sql: A SELECT statement. Do NOT include a LIMIT — views must return all rows.
    """
    if not VIEW_NAME_RE.match(name):
        return (
            f"Error: Invalid view name '{name}'. "
            "Must match report_[a-z0-9_]+ (e.g. report_past_due)."
        )

    try:
        clean_sql = validate_select_sql(sql)
    except ValueError as e:
        return f"Error: {e}"

    # Test-execute before committing anything
    try:
        conn = get_connection()
        conn.execute(clean_sql).fetchone()
        conn.close()
    except Exception as e:
        return f"SQL error (view not saved): {e}"

    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Write backup .sql file
    try:
        os.makedirs(REPORTS_DIR, exist_ok=True)
        sql_path = os.path.join(REPORTS_DIR, f"{name}.sql")
        with open(sql_path, "w", encoding="utf-8") as f:
            f.write(f"-- name: {name}\n")
            f.write(f"-- description: {description}\n")
            f.write(f"-- created_at: {created_at}\n")
            f.write(f"DROP VIEW IF EXISTS {name};\n")
            f.write(f"CREATE VIEW {name} AS\n{clean_sql};\n")
    except Exception as e:
        return f"Error writing backup file: {e}"

    # Create view and upsert metadata
    try:
        conn = get_write_connection()
        conn.execute(f"DROP VIEW IF EXISTS {name}")
        conn.execute(f"CREATE VIEW {name} AS {clean_sql}")
        conn.execute(_CREATE_METADATA_SQL)
        conn.execute(
            "INSERT OR REPLACE INTO report_metadata (name, description, sql, created_at) "
            "VALUES (?, ?, ?, ?)",
            (name, description, clean_sql, created_at),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        return f"Database error: {e}"

    log.info(f"Created report view: {name}")
    return f"Report saved as '{name}'. It will appear in your ODBC connection immediately."


@mcp.tool()
def list_views() -> str:
    """List all saved report views (report_ prefix) with descriptions and SQL.

    Returns a JSON array of objects with: name, description, created_at, sql.
    """
    try:
        conn = get_connection()

        # Check whether report_metadata exists yet (it's created on first create_view call)
        has_metadata = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='report_metadata'"
        ).fetchone()

        if has_metadata:
            rows = conn.execute(
                """
                SELECT s.name,
                       m.description,
                       m.created_at,
                       s.sql
                FROM sqlite_master s
                LEFT JOIN report_metadata m ON m.name = s.name
                WHERE s.type = 'view' AND s.name LIKE 'report_%'
                ORDER BY s.name
                """
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type='view' AND name LIKE 'report_%' ORDER BY name"
            ).fetchall()

        conn.close()
        return json.dumps([dict(r) for r in rows], default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def drop_view(name: str) -> str:
    """Remove a saved report view by name.

    Only views with the report_ prefix can be dropped. Also removes the
    backup .sql file and metadata record.

    Args:
        name: The full view name (must start with report_).
    """
    if not name.startswith("report_"):
        return f"Error: Can only drop views with the report_ prefix. Got: '{name}'"

    try:
        conn = get_write_connection()

        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='view' AND name=?", (name,)
        ).fetchone()
        if not exists:
            conn.close()
            return f"View '{name}' does not exist."

        conn.execute(f"DROP VIEW IF EXISTS {name}")
        conn.execute(_CREATE_METADATA_SQL)
        conn.execute("DELETE FROM report_metadata WHERE name = ?", (name,))
        conn.commit()
        conn.close()
    except Exception as e:
        return f"Database error: {e}"

    # Remove backup file
    sql_path = os.path.join(REPORTS_DIR, f"{name}.sql")
    if os.path.exists(sql_path):
        try:
            os.remove(sql_path)
        except Exception as e:
            log.warning(f"Could not remove backup file {sql_path}: {e}")

    log.info(f"Dropped report view: {name}")
    return f"Report '{name}' has been removed."


# ---------------------------------------------------------------------------
# Sync tool
# ---------------------------------------------------------------------------
SYNC_SCRIPT = os.path.join(ROOT, "sync", "sync.py")


@mcp.tool()
def run_sync(resource: str = "", full: bool = False) -> str:
    """Run a data sync from ServiceTrade into the local database.

    By default, runs an incremental sync of all resources (only fetches records
    changed since the last sync). A full sync of all resources takes ~90 seconds;
    incremental syncs typically finish in under 10 seconds.

    Args:
        resource: Optional — sync a single resource (e.g. "company", "invoice").
                  Leave empty to sync all resources.
        full: If True, ignore last sync timestamps and re-pull everything.
    """
    import subprocess

    cmd = [sys.executable, SYNC_SCRIPT]
    if resource:
        cmd.append(resource)
    if full:
        cmd.append("--full")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=ROOT,
        )
    except subprocess.TimeoutExpired:
        return "Error: Sync timed out after 5 minutes."

    output = result.stdout + result.stderr

    # Return the summary section if present, otherwise the full output
    if "SYNC SUMMARY" in output:
        summary_start = output.index("SYNC SUMMARY")
        # Back up to the === line before SYNC SUMMARY
        prefix = output[:summary_start].rfind("=" * 60)
        if prefix >= 0:
            return output[prefix:]
        return output[summary_start:]

    if result.returncode != 0:
        return f"Sync failed (exit code {result.returncode}):\n{output[-2000:]}"

    return output[-2000:] if len(output) > 2000 else output


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run(transport="stdio")
