"""Generate schema.sql from mappings.yml + context.yml.

Reads both YAML files and produces a token-optimized SQLite schema for use
in Claude's MCP system prompt. Comments are minimal — only where column names
alone don't convey the meaning (enums, non-obvious semantics).

Usage: python generate_schema.py
Output: schema.sql (overwrites existing)
"""

import yaml
import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logging_config import get_logger

logger = get_logger(__name__)

MAPPINGS_FILE = "mappings.yml"
CONTEXT_FILE = "context.yml"
OUTPUT_FILE = "schema.sql"

# Map API types to SQLite types
TYPE_MAP = {
    "integer": "INTEGER",
    "text": "TEXT",
    "real": "REAL",
    "boolean": "INTEGER",
    "unknown": "TEXT",
    "object": "TEXT",
    "array": "TEXT",
}

# Table name overrides (API endpoint → SQL table name)
TABLE_NAME_MAP = {
    "serviceline": "service_line",
    "invoiceitem": "invoice_item",
    "quoteitem": "quote_item",
    "servicerecurrence": "service_recurrence",
    "servicerecurrenceitem": "service_recurrence_item",
    "servicerequest": "service_request",
    "paymentterms": "payment_terms",
    "taxrate": "tax_rate",
}

# Admin tables appended at the end (not generated from YAML)
ADMIN_TABLES_SQL = """
-- Tracks last successful sync per resource. Used for incremental sync.
CREATE TABLE sync_status (
  resource TEXT PRIMARY KEY,
  last_synced_at INTEGER,
  last_synced_at_dt TEXT,
  last_run_at INTEGER,
  last_run_at_dt TEXT,
  record_count INTEGER DEFAULT 0
);

-- Historical log of every sync run.
CREATE TABLE sync_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  resource TEXT,
  started_at INTEGER,
  started_at_dt TEXT,
  finished_at INTEGER,
  finished_at_dt TEXT,
  status TEXT, -- success|partial|failed
  records_fetched INTEGER DEFAULT 0,
  records_upserted INTEGER DEFAULT 0,
  error_message TEXT
);
"""

# Compact header for the schema — conventions explained once
HEADER = """\
-- ServiceTrade hood cleaning business — SQLite schema
-- Conventions:
--   _id suffix = FK to that table's id
--   INTEGER timestamps have _dt TEXT companions (ISO 8601 Pacific, e.g. created_at_dt)
--   TEXT columns for arrays/objects contain JSON
--   INTEGER booleans: 0=false, 1=true
"""


def table_name(endpoint):
    """Convert API endpoint name to SQL table name."""
    return TABLE_NAME_MAP.get(endpoint, endpoint)


def sql_type(api_type, ctx_field=None):
    """Determine SQLite type for a field.

    Special case: db_type 'timestamp' returns INTEGER for the raw column.
    """
    if ctx_field and "db_type" in ctx_field:
        db_type = ctx_field["db_type"]
        if db_type == "timestamp":
            return "INTEGER"
        return db_type.upper()
    return TYPE_MAP.get(api_type, "TEXT")


def generate_columns(mapping_fields, ctx_fields):
    """Generate list of (col_name, sql_type, prompt_comment) tuples for a table.

    Handles skip, flatten, extract_key, db_column rename, db_type override.
    No _dt companion columns — those are documented in the header convention.
    """
    columns = []
    ctx_fields = ctx_fields or {}

    for api_name, mapping_info in mapping_fields.items():
        # Skip 'uri' — internal API field, not useful in the database
        if api_name == "uri":
            continue

        ctx = ctx_fields.get(api_name, {})

        # Skip if context says to skip
        if ctx.get("skip"):
            continue

        api_type = mapping_info.get("api_type", "unknown")

        # Handle flatten (nested object → multiple flat columns)
        if "flatten" in ctx:
            for nested_key, flat_col in ctx["flatten"].items():
                columns.append((flat_col, "TEXT", None))
            continue

        # Handle extract_key (FK object → store just the id)
        if "extract_key" in ctx:
            final_col = ctx.get("db_column", api_name)
            final_type = sql_type(api_type, ctx)
            comment = ctx.get("prompt_comment")
            columns.append((final_col, final_type, comment))
            continue

        # Handle arrays without skip — store as JSON text
        if api_type == "array" and not ctx.get("skip"):
            final_col = ctx.get("db_column", api_name)
            final_type = sql_type(api_type, ctx)
            comment = ctx.get("prompt_comment")
            columns.append((final_col, final_type, comment))
            continue

        # Handle objects without flatten/extract_key — store as JSON text
        if api_type == "object" and "flatten" not in ctx and "extract_key" not in ctx:
            final_col = ctx.get("db_column", api_name)
            final_type = sql_type(api_type, ctx)
            comment = ctx.get("prompt_comment")
            columns.append((final_col, final_type, comment))
            continue

        # Standard field
        final_col = ctx.get("db_column", api_name)
        final_type = sql_type(api_type, ctx)
        comment = ctx.get("prompt_comment")
        columns.append((final_col, final_type, comment))

        # No _dt companion columns — convention documented in header

    # Context-only fields: emit columns for fields declared in context.yml
    # that don't exist in mappings.yml. These are typically populated by
    # the sync code from sideloaded sub-responses (see sync/sync.py).
    seen_api_names = set(mapping_fields.keys())
    seen_db_columns = {c[0] for c in columns}
    for api_name, ctx in ctx_fields.items():
        if api_name in seen_api_names:
            continue
        if ctx.get("skip"):
            continue
        final_col = ctx.get("db_column", api_name)
        if final_col in seen_db_columns:
            continue
        # For context-only fields, db_type must be explicitly set
        # (we have no api_type to infer from)
        db_type = ctx.get("db_type")
        if not db_type:
            continue
        # Map context db_type to SQL type — same logic as sql_type() but
        # without an api_type to fall back on
        sql_t = {
            "integer": "INTEGER",
            "real": "REAL",
            "text": "TEXT",
            "timestamp": "INTEGER",
        }.get(db_type, "TEXT")
        comment = ctx.get("prompt_comment")
        columns.append((final_col, sql_t, comment))

    return columns


def format_table(endpoint, mapping, ctx_resource):
    """Generate a CREATE TABLE statement for one resource."""
    tname = table_name(endpoint)
    ctx_fields = ctx_resource.get("fields", {}) if ctx_resource else {}
    description = ctx_resource.get("description", "").strip() if ctx_resource else ""

    columns = generate_columns(mapping["fields"], ctx_fields)

    # Add parent FK column for child resources (e.g. invoice_id on invoice_item)
    parent_id_field = mapping.get("parent_id_field")
    if parent_id_field:
        # Convert camelCase to snake_case
        s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", parent_id_field)
        fk_col = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()
        # Only add if not already present (it might be in the API response)
        existing_cols = {c[0] for c in columns}
        if fk_col not in existing_cols:
            columns.insert(0, (fk_col, "INTEGER", None))

    # Skip tables with no columns (e.g. region, tax_rate with 0 records)
    if not columns:
        return None

    lines = []

    # Table comment — single line, compact
    if description:
        desc_text = " ".join(description.split())
        lines.append(f"-- {desc_text}")

    lines.append(f"CREATE TABLE {tname} (")

    for i, (cname, ctype, comment) in enumerate(columns):
        is_last = (i == len(columns) - 1)
        pk = " PRIMARY KEY" if cname == "id" else ""
        comma = "" if is_last else ","

        line = f"  {cname} {ctype}{pk}{comma}"

        if comment:
            line = f"{line}  -- {comment}"

        lines.append(line)

    lines.append(");")

    return "\n".join(lines)


def main():
    # Allow running from project root, schema/ dir, or /app in Docker
    for base in [".", "schema", "/app/schema"]:
        m_path = os.path.join(base, MAPPINGS_FILE)
        c_path = os.path.join(base, CONTEXT_FILE)
        if os.path.exists(m_path) and os.path.exists(c_path):
            break
    else:
        logger.error(f"Cannot find {MAPPINGS_FILE} and {CONTEXT_FILE}")
        sys.exit(1)

    try:
        with open(m_path) as f:
            mappings = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        logger.exception(f"Failed to load {m_path}: {e}")
        sys.exit(1)

    try:
        with open(c_path) as f:
            context = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        logger.exception(f"Failed to load {c_path}: {e}")
        sys.exit(1)

    resources = mappings.get("resources", {})
    ctx_resources = context.get("resources", {})
    static = set(mappings.get("static_resources", []))

    # Separate static (reference) tables from core tables
    static_endpoints = [ep for ep in resources if ep in static]
    core_endpoints = [ep for ep in resources if ep not in static]

    out = [HEADER]

    table_count = 0
    skipped = []

    for ep in static_endpoints + core_endpoints:
        # Skip resources not in context.yml (e.g. skip_resource: true)
        if ep not in ctx_resources:
            skipped.append(table_name(ep))
            continue
        ctx_res = ctx_resources.get(ep)
        table_sql = format_table(ep, resources[ep], ctx_res)
        if table_sql:
            out.append(table_sql)
            out.append("")
            table_count += 1
        else:
            skipped.append(table_name(ep))

    # Admin tables
    out.append(ADMIN_TABLES_SQL)

    output = "\n".join(out)

    o_path = os.path.join(os.path.dirname(m_path), OUTPUT_FILE)
    try:
        with open(o_path, "w") as f:
            f.write(output)
    except OSError as e:
        logger.exception(f"Failed to write {o_path}: {e}")
        sys.exit(1)

    logger.info(f"Generated {o_path}")
    logger.info(f"  Tables: {table_count} + 2 admin = {table_count + 2}")
    if skipped:
        logger.info(f"  Skipped (empty): {', '.join(skipped)}")


if __name__ == "__main__":
    main()
