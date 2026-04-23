"""Generate v_ views with human-readable _dt columns for all timestamp fields.

Reads context.yml to find db_type: timestamp fields, then creates views in the
live database. Each view selects all base columns plus datetime(col, 'unixepoch',
'localtime') AS col_dt for every timestamp column.

Idempotent — safe to run repeatedly (DROP VIEW IF EXISTS before each CREATE).

Usage: python generate_views.py
"""

import yaml
import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logging_config import get_logger

logger = get_logger(__name__)

CONTEXT_FILE = "context.yml"
DB_FILE = os.path.join("data", "safehoods.db")

# Same map as generate_schema.py
TABLE_NAME_MAP = {
    "serviceline": "service_line",
    "invoiceitem": "invoice_item",
    "quoteitem": "quote_item",
    "servicerecurrence": "service_recurrence",
    "servicerecurrenceitem": "service_recurrence_item",
    "paymentterms": "payment_terms",
    "taxrate": "tax_rate",
}


def table_name(endpoint):
    return TABLE_NAME_MAP.get(endpoint, endpoint)


def find_timestamp_columns(ctx_fields):
    """Return list of db column names that are timestamps."""
    ts_cols = []
    if not ctx_fields:
        return ts_cols
    for api_name, field_cfg in ctx_fields.items():
        if not isinstance(field_cfg, dict):
            continue
        if field_cfg.get("skip"):
            continue
        if field_cfg.get("db_type") == "timestamp":
            col = field_cfg.get("db_column", api_name)
            ts_cols.append(col)
    return ts_cols


def main():
    # Locate context.yml
    for base in [".", "schema", "/app/schema"]:
        c_path = os.path.join(base, CONTEXT_FILE)
        if os.path.exists(c_path):
            break
    else:
        logger.error(f"Cannot find {CONTEXT_FILE}")
        sys.exit(1)

    # Locate database
    for db_base in [".", "/app"]:
        db_path = os.path.join(db_base, DB_FILE)
        if os.path.exists(db_path):
            break
    else:
        logger.error(f"Cannot find {DB_FILE}")
        sys.exit(1)

    try:
        with open(c_path) as f:
            context = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        logger.exception(f"Failed to load {c_path}: {e}")
        sys.exit(1)

    ctx_resources = context.get("resources", {})

    try:
        conn = sqlite3.connect(db_path)
        created = []
        skipped = []

        for endpoint, ctx_res in ctx_resources.items():
            tbl = table_name(endpoint)
            fields = ctx_res.get("fields", {})
            ts_cols = find_timestamp_columns(fields)

            if not ts_cols:
                skipped.append(tbl)
                continue

            view_name = f"v_{tbl}"
            dt_exprs = ", ".join(
                f"datetime({col}, 'unixepoch', 'localtime') AS {col}_dt"
                for col in ts_cols
            )

            conn.execute(f"DROP VIEW IF EXISTS {view_name}")
            conn.execute(f"CREATE VIEW {view_name} AS SELECT *, {dt_exprs} FROM {tbl}")
            created.append((view_name, ts_cols))

        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.exception(f"Database error while creating views: {e}")
        sys.exit(1)

    logger.info(f"Created {len(created)} views in {db_path}")
    for vname, cols in created:
        logger.info(f"  {vname}: {', '.join(c + '_dt' for c in cols)}")
    if skipped:
        logger.info(f"Skipped (no timestamps): {', '.join(skipped)}")


if __name__ == "__main__":
    main()
