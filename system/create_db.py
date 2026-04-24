#!/usr/bin/env python3
"""Create the HoodsBase SQLite database from schema.sql."""

import glob
import os
import re
import sqlite3
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logging_config import get_logger

logger = get_logger(__name__)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(ROOT, "schema", "schema.sql")
SETTINGS_PATH = os.path.join(ROOT, "system", "db_settings.yml")
DB_DIR = os.path.join(ROOT, "data")
DB_PATH = os.path.join(DB_DIR, "hoodsbase.db")
REPORTS_DIR = os.path.join(ROOT, "reports")


def load_settings():
    try:
        with open(SETTINGS_PATH) as f:
            return yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        logger.exception(f"Failed to load {SETTINGS_PATH}: {e}")
        sys.exit(1)


def apply_create_mode(sql, mode):
    if mode == "create_if_not_exists":
        return re.sub(
            r"CREATE TABLE\b", "CREATE TABLE IF NOT EXISTS", sql, flags=re.IGNORECASE
        )
    if mode == "drop_and_create":
        # Extract table names and prepend DROP statements
        tables = re.findall(r"CREATE TABLE\s+(\w+)", sql, re.IGNORECASE)
        drops = "\n".join(f"DROP TABLE IF EXISTS {t};" for t in tables)
        return drops + "\n\n" + sql
    return sql


def _restore_report_views(conn: sqlite3.Connection) -> int:
    """Reapply report views from reports/*.sql backup files.

    Creates the report_metadata table if needed, then replays each saved view
    and restores its metadata. Returns the number of views restored.
    """
    if not os.path.isdir(REPORTS_DIR):
        return 0

    report_files = sorted(glob.glob(os.path.join(REPORTS_DIR, "*.sql")))
    if not report_files:
        return 0

    conn.execute("""
        CREATE TABLE IF NOT EXISTS report_metadata (
            name        TEXT PRIMARY KEY,
            description TEXT,
            sql         TEXT,
            created_at  TEXT
        )
    """)

    restored = 0
    for path in report_files:
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()

            name_m = re.search(r"^-- name: (.+)$", content, re.MULTILINE)
            desc_m = re.search(r"^-- description: (.+)$", content, re.MULTILINE)
            created_m = re.search(r"^-- created_at: (.+)$", content, re.MULTILINE)

            # Strip comment lines to get just the CREATE OR REPLACE VIEW statement
            view_sql = re.sub(r"^--[^\n]*\n", "", content, flags=re.MULTILINE).strip()

            conn.executescript(view_sql)
            conn.execute(
                "INSERT OR REPLACE INTO report_metadata (name, description, sql, created_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    name_m.group(1).strip() if name_m else None,
                    desc_m.group(1).strip() if desc_m else None,
                    view_sql,
                    created_m.group(1).strip() if created_m else None,
                ),
            )
            restored += 1
        except Exception as e:
            logger.warning(f"Could not restore report view from {path}: {e}")

    conn.commit()
    return restored


def main():
    if not os.path.exists(SCHEMA_PATH):
        logger.error(f"Schema file not found: {SCHEMA_PATH}")
        sys.exit(1)

    if not os.path.exists(SETTINGS_PATH):
        logger.error(f"Settings file not found: {SETTINGS_PATH}")
        sys.exit(1)

    settings = load_settings()
    create_mode = settings.get("create_mode", "create_if_not_exists")
    pragmas = settings.get("pragmas", [])

    os.makedirs(DB_DIR, exist_ok=True)

    try:
        with open(SCHEMA_PATH) as f:
            schema_sql = f.read()
    except OSError as e:
        logger.exception(f"Failed to read schema file: {e}")
        sys.exit(1)

    schema_sql = apply_create_mode(schema_sql, create_mode)

    try:
        conn = sqlite3.connect(DB_PATH)

        for pragma in pragmas:
            conn.execute(f"PRAGMA {pragma}")

        conn.executescript(schema_sql)

        # Verify pragmas
        for pragma in pragmas:
            key = pragma.split("=")[0].strip()
            result = conn.execute(f"PRAGMA {key}").fetchone()
            logger.info(f"PRAGMA {key} = {result[0]}")

        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()

        # Restore user-created report views from reports/*.sql backups
        restored = _restore_report_views(conn)

        conn.close()
    except sqlite3.Error as e:
        logger.exception(f"Database error: {e}")
        sys.exit(1)

    logger.info(f"Database: {DB_PATH} ({create_mode})")
    logger.info(f"{len(tables)} tables: {', '.join(t[0] for t in tables)}")
    if restored:
        logger.info(f"Restored {restored} report view(s) from reports/")


if __name__ == "__main__":
    main()
