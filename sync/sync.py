#!/usr/bin/env python3
"""Sync ServiceTrade API data into the local SQLite database.

Usage:
    python sync/sync.py                  # sync all resources
    python sync/sync.py company          # sync one resource
    python sync/sync.py invoice --full   # force full pull (ignore sync_status)
    python sync/sync.py --full           # full pull on all resources

Driven by schema/mappings.yml (API structure) and schema/context.yml (field
transforms). Static resources (service_line, tag, etc.) are only pulled when
their table is empty, unless explicitly requested or --full is used.
"""

import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone

import requests
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logging_config import get_logger

logger = get_logger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAPPINGS_PATH = os.path.join(ROOT, "schema", "mappings.yml")
CONTEXT_PATH = os.path.join(ROOT, "schema", "context.yml")
ENDPOINTS_PATH = os.path.join(ROOT, "system", "endpoints.yml")
DB_PATH = os.path.join(ROOT, "data", "hoodsbase.db")
TOKEN_FILE = os.path.join(ROOT, ".session_token")
ENV_FILE = os.path.join(ROOT, ".env")

BASE_URL = "https://api.servicetrade.com/api"

# Budget threshold — pause when API budget drops below this (ms)
BUDGET_THRESHOLD_MS = 10_000
BATCH_SIZE = 500

# Table name overrides (same as generate_schema.py)
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

# Core resources in dependency order
CORE_ORDER = [
    "company", "location", "contact", "job", "appointment",
    "invoice", "quote", "asset", "deficiency", "servicerecurrence", "user",
]


# ── Helpers ───────────────────────────────────────────────────────────

def table_name(resource):
    """Convert API resource name to SQL table name."""
    return TABLE_NAME_MAP.get(resource, resource)


def camel_to_snake(name):
    """Convert camelCase to snake_case."""
    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def ts_to_iso(ts):
    """Convert Unix timestamp to ISO 8601 UTC string."""
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except (ValueError, OSError, OverflowError):
        return None


def parse_money_string(val):
    """Parse formatted money string like '9,250.00' to float."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None




# ── Auth ──────────────────────────────────────────────────────────────

def load_env():
    """Load .env file into os.environ if it exists."""
    if not os.path.exists(ENV_FILE):
        return
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())


def get_session():
    """Return an authenticated requests.Session."""
    load_env()
    session = requests.Session()

    # Try saved token
    if os.path.exists(TOKEN_FILE):
        try:
            token = open(TOKEN_FILE).read().strip()
        except OSError as e:
            logger.warning(f"Auth: could not read token file: {e}")
            token = None
        if token:
            session.cookies.set("PHPSESSID", token)
            try:
                check = session.get(f"{BASE_URL}/auth")
            except requests.RequestException as e:
                logger.error(f"Auth: network error checking session: {e}")
                sys.exit(1)
            if check.status_code == 200:
                logger.info("Auth: existing session valid")
                return session
            logger.info("Auth: saved token expired, logging in fresh...")
            session.cookies.clear()

    # Login
    username = os.environ.get("SERVICETRADE_USERNAME")
    password = os.environ.get("SERVICETRADE_PASSWORD")
    if not username or not password:
        logger.error("Auth: SERVICETRADE_USERNAME and SERVICETRADE_PASSWORD required")
        sys.exit(1)

    try:
        resp = session.post(
            f"{BASE_URL}/auth", json={"username": username, "password": password}
        )
    except requests.RequestException as e:
        logger.error(f"Auth: network error during login: {e}")
        sys.exit(1)

    if resp.status_code != 200:
        logger.error(f"Auth: failed (HTTP {resp.status_code})")
        sys.exit(1)

    auth_token = resp.json().get("data", {}).get("authToken")
    try:
        with open(TOKEN_FILE, "w") as f:
            f.write(auth_token)
    except OSError as e:
        logger.error(f"Auth: could not save token: {e}")
        sys.exit(1)
    logger.info("Auth: logged in, token saved")
    return session


# ── API fetching ──────────────────────────────────────────────────────

def extract_records(data, endpoint):
    """Extract the records list from the API response data.

    Same logic as rebuild_mappings.py — tries plural key variants,
    then falls back to any list key that isn't pagination metadata.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        candidates = [endpoint, endpoint + "s", "items"]
        if endpoint.endswith("y"):
            candidates.insert(1, endpoint[:-1] + "ies")
        for key in candidates:
            if key in data and isinstance(data[key], list):
                return data[key]
        skip_keys = {"page", "totalPages", "totalCount", "pageSize"}
        for key, val in data.items():
            if key not in skip_keys and isinstance(val, list):
                return val
    return []


def check_budget(response_json, session):
    """Check API rate limit budget and sleep if needed.

    Returns the remaining budget in ms, or None if not available.
    """
    meta = response_json.get("meta", {})
    stats = meta.get("stats", {})
    balance = stats.get("resourceBalanceMs")
    if balance is not None and balance < BUDGET_THRESHOLD_MS:
        wait_secs = max(5, (BUDGET_THRESHOLD_MS - balance) / 1000 + 2)
        logger.warning(f"Rate limit budget low ({balance}ms), waiting {wait_secs:.0f}s...")
        time.sleep(wait_secs)
    return balance


def fetch_all_pages(session, endpoint, params=None):
    """Fetch all pages from an API endpoint.

    Returns (all_records, total_pages, last_budget_ms, sideloads).

    `sideloads` is a dict mapping each sideloaded section name (e.g.
    "serviceRequests") to a flat list of all sideloaded records collected
    across all pages.  Empty dict if no sideloads are present in the
    response.

    The sideloaded sections appear alongside the primary records section
    in the response. ServiceTrade returns them when the request includes
    a `_sideload` parameter (see system/endpoints.yml). Sideloaded
    sections are recognised as: any list-valued key in `data` that is
    NOT the primary records list and NOT a pagination metadata key.
    """
    url = f"{BASE_URL}/{endpoint}"
    if params is None:
        params = {}

    all_records = []
    sideloads = {}              # section_name -> list of sideloaded records
    page = 1
    total_pages = 1
    last_budget = None

    # Pagination metadata keys that should never be treated as sideloads
    pagination_keys = {"page", "totalPages", "totalCount", "pageSize"}

    while page <= total_pages:
        req_params = {**params, "page": page}
        resp = session.get(url, params=req_params)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 15))
            logger.warning(f"429 rate limited on {endpoint}, waiting {retry_after}s...")
            time.sleep(retry_after)
            continue  # retry same page

        if resp.status_code != 200:
            raise RuntimeError(
                f"API error {resp.status_code} on GET {endpoint} page {page}"
            )

        try:
            payload = resp.json()
        except ValueError as e:
            raise RuntimeError(f"Invalid JSON response from {endpoint} page {page}: {e}")
        data = payload.get("data", payload)

        # Get pagination on first page
        if page == 1:
            if isinstance(data, dict):
                tp = data.get("totalPages")
                if tp:
                    total_pages = int(tp)

        records = extract_records(data, endpoint)
        all_records.extend(records)

        # Collect sideloaded sections: any list-valued key that isn't the
        # primary records list, isn't pagination metadata, and isn't empty.
        # We identify the primary list by object identity, not by key name,
        # because extract_records() may have matched any of several plural
        # variants.
        if isinstance(data, dict):
            for key, val in data.items():
                if key in pagination_keys:
                    continue
                if not isinstance(val, list):
                    continue
                if val is records:        # this is the primary records list
                    continue
                sideloads.setdefault(key, []).extend(val)

        last_budget = check_budget(payload, session)

        if total_pages > 1:
            logger.info(f"  {endpoint}: page {page}/{total_pages} — {len(records)} records (budget: {last_budget}ms)")

        page += 1

    return all_records, total_pages, last_budget, sideloads


# ── Record transformation ────────────────────────────────────────────

def transform_record(record, ctx_fields, mapping_fields):
    """Transform an API record into a flat dict of {db_column: value}.

    Applies context.yml rules: skip, flatten, extract_key, rename, type coercion.
    """
    row = {}

    # Always include id
    if "id" in record:
        row["id"] = record["id"]

    for api_name, api_val in record.items():
        # Skip id (already handled) and uri (not in schema)
        if api_name in ("id", "uri"):
            continue

        ctx = ctx_fields.get(api_name, {})

        # Skip
        if ctx.get("skip"):
            continue

        # Flatten (address objects)
        if "flatten" in ctx:
            if isinstance(api_val, dict):
                for nested_key, flat_col in ctx["flatten"].items():
                    row[flat_col] = api_val.get(nested_key)
            else:
                for flat_col in ctx["flatten"].values():
                    row[flat_col] = None
            continue

        # Extract key (FK objects like company → company_id)
        if "extract_key" in ctx:
            col = ctx.get("db_column", api_name)
            if isinstance(api_val, dict):
                row[col] = api_val.get(ctx["extract_key"])
            else:
                row[col] = api_val
            continue

        # Determine the target column name
        col = ctx.get("db_column", camel_to_snake(api_name))
        db_type = ctx.get("db_type")

        # Type coercions
        if db_type == "integer" and isinstance(api_val, bool):
            row[col] = 1 if api_val else 0
        elif db_type == "real" and isinstance(api_val, str):
            # Money fields returned as formatted strings (quote subtotal etc.)
            row[col] = parse_money_string(api_val)
        elif db_type == "timestamp":
            row[col] = api_val
            # Generate _dt companion
            row[col + "_dt"] = ts_to_iso(api_val)
        elif isinstance(api_val, (dict, list)):
            row[col] = json.dumps(api_val)
        elif isinstance(api_val, bool):
            row[col] = 1 if api_val else 0
        else:
            row[col] = api_val

        # Timestamp companion for fields that are timestamps by context
        # but didn't go through db_type == "timestamp" above
        # (handles cases where db_type is set but value isn't bool/str/etc.)
        if db_type == "timestamp" and col + "_dt" not in row:
            row[col + "_dt"] = ts_to_iso(api_val)

    return row


# ── Database operations ──────────────────────────────────────────────

def get_db():
    """Open a SQLite connection with recommended pragmas."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def table_row_count(conn, tbl):
    """Return row count for a table, or -1 if table doesn't exist."""
    try:
        return conn.execute(f"SELECT COUNT(*) FROM [{tbl}]").fetchone()[0]
    except sqlite3.OperationalError:
        return -1


def get_table_columns(conn, tbl):
    """Return set of column names for a table."""
    cursor = conn.execute(f"PRAGMA table_info([{tbl}])")
    return {row[1] for row in cursor.fetchall()}


def upsert_records(conn, tbl, records):
    """INSERT OR REPLACE records into a table. Returns count upserted."""
    if not records:
        return 0

    # Get valid columns for this table
    valid_cols = get_table_columns(conn, tbl)
    if not valid_cols:
        logger.warning(f"Table [{tbl}] has no columns or doesn't exist")
        return 0

    count = 0
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i : i + BATCH_SIZE]

        for row in batch:
            # Filter to only valid columns
            filtered = {k: v for k, v in row.items() if k in valid_cols}
            if not filtered:
                continue

            cols = list(filtered.keys())
            placeholders = ", ".join("?" for _ in cols)
            col_names = ", ".join(f"[{c}]" for c in cols)
            sql = f"INSERT OR REPLACE INTO [{tbl}] ({col_names}) VALUES ({placeholders})"

            try:
                conn.execute(sql, [filtered[c] for c in cols])
                count += 1
            except sqlite3.Error as e:
                logger.warning(f"Upsert failed for record in [{tbl}]: {e}")

        conn.commit()

    return count


def get_sync_timestamp(conn, resource):
    """Get last_synced_at for a resource, or None if never synced."""
    row = conn.execute(
        "SELECT last_synced_at FROM sync_status WHERE resource = ?", (resource,)
    ).fetchone()
    return row[0] if row else None


def update_sync_status(conn, resource, tbl):
    """Update sync_status for a resource after successful sync."""
    now = int(time.time())
    count = table_row_count(conn, tbl)
    conn.execute(
        """INSERT OR REPLACE INTO sync_status
           (resource, last_synced_at, last_synced_at_dt,
            last_run_at, last_run_at_dt, record_count)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (resource, now, ts_to_iso(now), now, ts_to_iso(now), count),
    )
    conn.commit()


def write_sync_log(conn, resource, started_at, status, fetched, upserted, error=None):
    """Write a sync_log entry."""
    now = int(time.time())
    conn.execute(
        """INSERT INTO sync_log
           (resource, started_at, started_at_dt, finished_at, finished_at_dt,
            status, records_fetched, records_upserted, error_message)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            resource, started_at, ts_to_iso(started_at),
            now, ts_to_iso(now), status, fetched, upserted, error,
        ),
    )
    conn.commit()


# ── Sync logic ────────────────────────────────────────────────────────

def sync_resource(session, conn, resource, mapping, ctx_resource,
                  required_params, is_static, force_full=False,
                  _endpoints_cfg=None):
    """Sync a single resource from the API into SQLite.

    Returns (records_fetched, records_upserted, status, error_msg, raw_records).
    raw_records is the list of raw API dicts (for child resource syncing).
    """
    tbl = table_name(resource)
    endpoint = mapping["api_endpoint"].replace("/api/", "")
    ctx_fields = ctx_resource.get("fields", {}) if ctx_resource else {}
    started_at = int(time.time())

    # --- Decide full vs incremental ---
    if is_static and not force_full:
        existing = table_row_count(conn, tbl)
        if existing > 0:
            logger.info(f"[{tbl}] Skipping (static, {existing} rows already present)")
            write_sync_log(conn, resource, started_at, "skipped", 0, 0)
            return 0, 0, "skipped", None, []

    params = {}
    if required_params:
        params.update(required_params)

    if not force_full and not is_static:
        last_ts = get_sync_timestamp(conn, resource)
        if last_ts:
            params["updatedAfter"] = last_ts
            logger.info(f"[{tbl}] Incremental sync (updatedAfter={last_ts}, {ts_to_iso(last_ts)})")
        else:
            logger.info(f"[{tbl}] Full sync (no prior sync_status)")
    elif force_full:
        logger.info(f"[{tbl}] Full sync (--full)")
    else:
        logger.info(f"[{tbl}] Full sync (static resource)")

    # --- Special case: job API defaults to status=scheduled ---
    # We need all statuses, so explicitly pass status=all
    if resource == "job" and "status" not in params:
        params["status"] = "all"

    # --- Sideloads (see system/endpoints.yml) ---
    # If this resource declares a sideload, ask the API to include the
    # related records alongside the primary ones in a single response.
    sideload_list = get_sideload(resource, _endpoints_cfg)
    if sideload_list:
        params["_sideload"] = ",".join(sideload_list)
        logger.info(f"[{tbl}] Sideload requested: {params['_sideload']}")

    # --- Fetch ---
    try:
        records, total_pages, _, sideloads = fetch_all_pages(session, endpoint, params)
    except RuntimeError as e:
        logger.error(f"[{tbl}] Fetch failed: {e}")
        write_sync_log(conn, resource, started_at, "failed", 0, 0, str(e))
        return 0, 0, "failed", str(e), []

    logger.info(f"[{tbl}] Fetched {len(records)} records ({total_pages} page(s))")

    if not records:
        update_sync_status(conn, resource, tbl)
        write_sync_log(conn, resource, started_at, "success", 0, 0)
        return 0, 0, "success", None, []

    # --- Sideload extraction: enrich primary records with sideloaded data ---
    # For service_recurrence with the nextDueService sideload, the response
    # includes a separate `serviceRequests` section containing the projected
    # next-due service request for each recurrence (real or synthetic).
    # We pluck windowStart from each one and attach it to its parent
    # recurrence as a `currentlyDue` field so transform_record() picks it up
    # via the api_knowledge.yml override.
    #
    # Matching: the sideloaded service request points back to its parent
    # recurrence via the `serviceRecurrence` field. For synthetic projections
    # (where no real service request exists yet), the sideloaded record's id
    # is the negation of the parent recurrence id.
    if sideloads and resource == "servicerecurrence":
        sr_list = sideloads.get("serviceRequests", [])
        # Build a lookup: parent recurrence id -> sideloaded service request
        by_parent = {}
        for sr in sr_list:
            parent_id = sr.get("serviceRecurrence")
            if parent_id is not None:
                by_parent[parent_id] = sr
            # Also handle synthetic records keyed by negative id
            sr_id = sr.get("id")
            if sr_id is not None and sr_id < 0:
                by_parent[-sr_id] = sr
        # Walk each recurrence and inject currentlyDue from its match
        matched = 0
        for rec in records:
            rec_id = rec.get("id")
            sideloaded = by_parent.get(rec_id)
            if sideloaded:
                rec["currentlyDue"] = sideloaded.get("windowStart")
                matched += 1
        logger.info(f"[{tbl}] Matched currently_due for {matched}/{len(records)} recurrences (from {len(sr_list)} sideloaded records)")

    # --- Transform ---
    transformed = []
    for rec in records:
        transformed.append(transform_record(rec, ctx_fields, mapping.get("fields", {})))

    # --- Upsert ---
    upserted = upsert_records(conn, tbl, transformed)
    logger.info(f"[{tbl}] Upserted {upserted} records")

    # --- Update sync_status ---
    update_sync_status(conn, resource, tbl)
    write_sync_log(conn, resource, started_at, "success", len(records), upserted)

    return len(records), upserted, "success", None, records


def sync_child_resource(session, conn, child_resource, child_mapping, ctx_resource,
                        parent_records, force_full=False):
    """Sync a child resource (invoice items, quote items) from parent records.

    Two strategies based on inline data completeness:
    - Invoice items: fully embedded in parent response → extract inline (0 API calls)
    - Quote items: sparse inline (only id/uri/desc) → call /api/{parent}/{id}/item
    """
    tbl = table_name(child_resource)
    parent_resource = child_mapping["parent_resource"]
    parent_id_field = camel_to_snake(child_mapping["parent_id_field"])
    ctx_fields = ctx_resource.get("fields", {}) if ctx_resource else {}
    started_at = int(time.time())

    # Determine if inline items are complete enough to skip API calls.
    # Check if the first parent with items has more than just id/uri/description.
    use_inline = False
    for rec in parent_records:
        items = rec.get("items", [])
        if items:
            # If inline items have more than 3 keys, they're fully detailed
            use_inline = len(items[0].keys()) > 4
            break

    all_items = []
    api_calls = 0

    if use_inline:
        logger.info(f"[{tbl}] Extracting inline items from {len(parent_records)} {parent_resource}(s)...")
        for parent_rec in parent_records:
            parent_id = parent_rec.get("id")
            if not parent_id:
                continue
            items = parent_rec.get("items", [])
            for item in items:
                item[child_mapping["parent_id_field"]] = parent_id
            all_items.extend(items)
        logger.info(f"[{tbl}] Extracted {len(all_items)} inline items (0 API calls)")
    else:
        logger.info(f"[{tbl}] Fetching items for {len(parent_records)} {parent_resource}(s) via API...")
        for parent_rec in parent_records:
            parent_id = parent_rec.get("id")
            if not parent_id:
                continue

            item_url = f"{BASE_URL}/{parent_resource}/{parent_id}/item"
            resp = session.get(item_url)

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 15))
                logger.warning(f"[{tbl}] 429 rate limited, waiting {retry_after}s...")
                time.sleep(retry_after)
                resp = session.get(item_url)

            if resp.status_code != 200:
                logger.warning(f"[{tbl}] Failed to fetch items for {parent_resource}/{parent_id} (HTTP {resp.status_code})")
                continue

            api_calls += 1
            try:
                payload = resp.json()
            except ValueError as e:
                logger.warning(f"[{tbl}] Invalid JSON for {parent_resource}/{parent_id}: {e}")
                continue
            data = payload.get("data", payload)

            items = extract_records(data, "item")
            for item in items:
                item[child_mapping["parent_id_field"]] = parent_id

            all_items.extend(items)

            check_budget(payload, session)

            if api_calls % 50 == 0:
                logger.info(f"[{tbl}] ... {api_calls} API calls, {len(all_items)} items so far")

        logger.info(f"[{tbl}] Fetched {len(all_items)} items across {api_calls} API calls")

    if not all_items:
        write_sync_log(conn, child_resource, started_at, "success", 0, 0)
        return 0, 0, "success", None

    # Transform
    transformed = []
    for item in all_items:
        row = transform_record(item, ctx_fields, child_mapping.get("fields", {}))
        # Ensure parent FK is set
        if parent_id_field not in row:
            row[parent_id_field] = item.get(child_mapping["parent_id_field"])
        transformed.append(row)

    # Upsert
    upserted = upsert_records(conn, tbl, transformed)
    logger.info(f"[{tbl}] Upserted {upserted} child items")

    update_sync_status(conn, child_resource, tbl)
    write_sync_log(conn, child_resource, started_at, "success", len(all_items), upserted)

    return len(all_items), upserted, "success", None


# ── Main ──────────────────────────────────────────────────────────────

def load_config():
    """Load mappings.yml, context.yml, and endpoints.yml."""
    with open(MAPPINGS_PATH) as f:
        mappings = yaml.safe_load(f)
    with open(CONTEXT_PATH) as f:
        context = yaml.safe_load(f)
    with open(ENDPOINTS_PATH) as f:
        endpoints_cfg = yaml.safe_load(f)
    return mappings, context, endpoints_cfg


def resolve_resource_name(name, mappings):
    """Resolve a user-provided name to a mappings.yml resource key.

    Accepts: 'company', 'service_line', 'serviceline', 'invoice_item', etc.
    """
    resources = mappings.get("resources", {})

    # Direct match
    if name in resources:
        return name

    # Try removing underscores (service_line → serviceline)
    no_underscore = name.replace("_", "")
    if no_underscore in resources:
        return no_underscore

    # Try reverse table name map
    for api_name, tbl_name in TABLE_NAME_MAP.items():
        if tbl_name == name:
            return api_name

    return None


def get_required_params(resource, endpoints_cfg):
    """Get required_params for a resource from endpoints.yml."""
    for entry in endpoints_cfg.get("resources", []):
        if isinstance(entry, dict):
            if entry.get("endpoint") == resource:
                return entry.get("required_params")
        elif entry == resource:
            return None
    return None


def get_sideload(resource, endpoints_cfg):
    """Get sideload list for a resource from endpoints.yml.

    Returns a list of sideload names (e.g. ["serviceRecurrence.nextDueService"])
    or None if no sideload is configured for the resource.

    Sideloads are a ServiceTrade API feature: they request related records
    in the same response as the primary records, avoiding extra HTTP calls.
    See system/endpoints.yml for the per-resource sideload config.
    """
    for entry in endpoints_cfg.get("resources", []):
        if isinstance(entry, dict):
            if entry.get("endpoint") == resource:
                return entry.get("sideload")
        elif entry == resource:
            return None
    return None


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Sync ServiceTrade data to SQLite")
    parser.add_argument("resource", nargs="?", help="Specific resource to sync (e.g. company, invoice)")
    parser.add_argument("--full", action="store_true", help="Force full pull (ignore sync_status)")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("HoodsBase Sync")
    logger.info("=" * 60)

    # Load config
    mappings, context, endpoints_cfg = load_config()
    resources = mappings.get("resources", {})
    ctx_resources = context.get("resources", {})
    static_set = set(mappings.get("static_resources", []))

    # Determine which resources to sync
    if args.resource:
        resolved = resolve_resource_name(args.resource, mappings)
        if not resolved:
            logger.error(f"Unknown resource '{args.resource}'")
            logger.error(f"Available: {', '.join(sorted(resources.keys()))}")
            sys.exit(1)
        sync_list = [resolved]
        # When explicitly requesting a static resource, force it
        force_static = resolved in static_set
    else:
        # Static first, then core order, skip child resources
        child_resources = {
            k for k, v in resources.items() if v.get("api_endpoint") == "embedded"
        }
        sync_list = [r for r in static_set if r in resources]
        sync_list += [r for r in CORE_ORDER if r in resources and r not in static_set]
        force_static = False

    # Auth
    session = get_session()

    # DB
    if not os.path.exists(DB_PATH):
        logger.error(f"Database not found at {DB_PATH}")
        logger.error("Run: python system/create_db.py")
        sys.exit(1)

    conn = get_db()

    # Find child resources
    child_map = {}  # parent_resource → [(child_key, child_mapping, child_ctx)]
    for key, mapping in resources.items():
        if mapping.get("api_endpoint") == "embedded":
            parent = mapping["parent_resource"]
            child_ctx = ctx_resources.get(key, {})
            # Skip children with no context entry (e.g. servicerecurrenceitem)
            if key not in ctx_resources:
                continue
            child_map.setdefault(parent, []).append((key, mapping, child_ctx))

    # Sync
    results = []
    total_start = time.time()

    for resource in sync_list:
        mapping = resources.get(resource)
        if not mapping:
            continue
        if mapping.get("api_endpoint") == "embedded":
            continue  # child resources handled with parent

        ctx_res = ctx_resources.get(resource)
        if not ctx_res:
            logger.info(f"[{resource}] Skipped (no context entry)")
            continue

        is_static = resource in static_set
        force = args.full or (force_static and args.resource)
        required_params = get_required_params(resource, endpoints_cfg)

        logger.info("─" * 40)
        logger.info(f"[{table_name(resource)}] ({resource})")
        logger.info("─" * 40)

        fetched, upserted, status, error, raw_records = sync_resource(
            session, conn, resource, mapping, ctx_res,
            required_params, is_static, force_full=force,
            _endpoints_cfg=endpoints_cfg,
        )
        results.append((table_name(resource), fetched, upserted, status, error))

        # Sync child resources if parent had records
        if resource in child_map and fetched > 0:
            for child_key, child_mapping, child_ctx in child_map[resource]:
                logger.info(f"── [{table_name(child_key)}] (child of {table_name(resource)})")
                cf, cu, cs, ce = sync_child_resource(
                    session, conn, child_key, child_mapping, child_ctx,
                    raw_records, force_full=force,
                )
                results.append((table_name(child_key), cf, cu, cs, ce))

    conn.close()

    # Summary
    elapsed = time.time() - total_start
    logger.info("=" * 60)
    logger.info("SYNC SUMMARY")
    logger.info("=" * 60)
    logger.info(f"{'Table':<25} {'Fetched':>8} {'Upserted':>9} {'Status':>10}")
    logger.info(f"{'─' * 25} {'─' * 8} {'─' * 9} {'─' * 10}")
    for tbl, fetched, upserted, status, error in results:
        logger.info(f"{tbl:<25} {fetched:>8} {upserted:>9} {status:>10}")
        if error:
            logger.error(f"  {tbl} error: {error}")
    logger.info(f"Completed in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
