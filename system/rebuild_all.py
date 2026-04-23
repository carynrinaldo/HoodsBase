"""Rebuild the full schema pipeline.

Runs all steps in order:
  1. rebuild_mappings.py  — endpoints.yml → mappings.yml  (live API calls)
  2. rebuild_context.py   — mappings.yml + api_knowledge.yml → context.yml
  3. generate_schema.py   — mappings.yml + context.yml → schema.sql
  4. generate_views.py    — context.yml → v_ views in safehoods.db

Usage: python system/rebuild_all.py [--skip-mappings]

The --skip-mappings flag skips step 1 (useful when mappings.yml is already
up to date and you just want to regenerate context + schema).

Step 4 (views) requires the database to exist. If it doesn't, the step is
skipped with a warning — run create_db.py and sync.py first, then re-run
or run generate_views.py standalone.
"""

import os
import sys
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logging_config import get_logger

logger = get_logger(__name__)


def find_base():
    """Find the project root."""
    for base in [".", "/app"]:
        if os.path.exists(os.path.join(base, "system", "endpoints.yml")):
            return base
    logger.error("Cannot find project root (system/endpoints.yml not found)")
    sys.exit(1)


def run_step(description, cmd, cwd):
    """Run a pipeline step and return success/failure."""
    logger.info(f"{'─' * 60}")
    logger.info(f"Step: {description}")
    logger.info(f"{'─' * 60}")
    result = subprocess.run(
        [sys.executable, "-u"] + cmd,
        cwd=cwd,
    )
    return result.returncode == 0


def main():
    skip_mappings = "--skip-mappings" in sys.argv
    base = find_base()

    steps = []
    if not skip_mappings:
        steps.append(
            ("Rebuild mappings from live API", ["system/rebuild_mappings.py"])
        )
    steps.append(
        ("Rebuild context from mappings + api_knowledge", ["system/rebuild_context.py"])
    )
    steps.append(
        ("Generate schema from mappings + context", ["schema/generate_schema.py"])
    )

    # Views require the database to exist
    db_path = os.path.join(base, "data", "safehoods.db")
    if os.path.exists(db_path):
        steps.append(
            ("Generate views in database", ["schema/generate_views.py"])
        )
    else:
        logger.warning(f"{db_path} not found — skipping view generation.")
        logger.warning("Run create_db.py + sync.py first, then generate_views.py.")

    logger.info(f"Pipeline: {len(steps)} steps")

    for desc, cmd in steps:
        ok = run_step(desc, cmd, base)
        if not ok:
            logger.error(f"Pipeline failed at: {desc}")
            sys.exit(1)

    logger.info("=" * 60)
    logger.info("Pipeline complete.")


if __name__ == "__main__":
    main()
