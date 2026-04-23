"""Rebuild mappings.yml from endpoints.yml + live API responses.

Reads system/endpoints.yml for the list of endpoints to explore, calls
each one via the ServiceTrade API, and writes schema/mappings.yml with
inferred field types, nested object keys, and pagination info.

Usage: python system/rebuild_mappings.py [--only <endpoint>] [--verbose]
Input:  system/endpoints.yml
Output: schema/mappings.yml

Options:
  --only <endpoint>  Process only the named endpoint (must be in endpoints.yml)
  --verbose          Print raw JSON (first 3 records) and field-by-field analysis

Child resources (invoiceitem, quoteitem) are auto-detected when a parent
endpoint's response contains an 'items' array of objects.
"""

import os
import sys
import json
import requests
import yaml
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logging_config import get_logger

logger = get_logger(__name__)

BASE_URL = "https://api.servicetrade.com/api"


def find_files():
    """Locate input/output files, supporting project root or /app."""
    for base in [".", "/app"]:
        e = os.path.join(base, "system", "endpoints.yml")
        m = os.path.join(base, "schema", "mappings.yml")
        if os.path.exists(e):
            return e, m
    logger.error("Cannot find system/endpoints.yml")
    sys.exit(1)


def get_session(base):
    """Load saved session token and return an authenticated requests.Session."""
    token_file = os.path.join(base, ".session_token")
    if not os.path.exists(token_file):
        logger.error(f"No session token found at {token_file}. Run auth.py first.")
        sys.exit(1)

    try:
        token = open(token_file).read().strip()
    except OSError as e:
        logger.error(f"Failed to read token file: {e}")
        sys.exit(1)

    session = requests.Session()
    session.cookies.set("PHPSESSID", token)

    try:
        check = session.get(f"{BASE_URL}/auth")
    except requests.RequestException as e:
        logger.error(f"Network error checking session: {e}")
        sys.exit(1)

    if check.status_code != 200:
        logger.error("Session expired. Run auth.py to get a new token.")
        sys.exit(1)

    return session


# ── Type inference ─────────────────────────────────────────────────

def infer_type(value):
    """Infer a simple type string from a Python value."""
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "real"
    if isinstance(value, str):
        return "text"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def analyze_fields(records):
    """Analyze field names, types, and nesting across all records."""
    fields = {}
    for record in records:
        for key, value in record.items():
            if key not in fields:
                fields[key] = {"type": infer_type(value), "sample": value}
            elif fields[key]["type"] == "unknown" and value is not None:
                fields[key]["type"] = infer_type(value)
                fields[key]["sample"] = value
    return fields


def build_fields_dict(fields):
    """Convert analyzed fields into the mapping fields dict."""
    fields_dict = {}
    for name, info in fields.items():
        field_entry = {"api_type": info["type"]}
        if info["type"] == "object" and isinstance(info["sample"], dict):
            field_entry["nested_keys"] = list(info["sample"].keys())
        elif info["type"] == "array":
            if info["sample"] and isinstance(info["sample"][0], dict):
                field_entry["array_item_keys"] = list(info["sample"][0].keys())
        fields_dict[name] = field_entry
    return fields_dict


def build_pagination(data):
    """Extract pagination info from the response data dict."""
    total_pages = data.get("totalPages")
    if total_pages is None or total_pages <= 1:
        return None
    pagination = {"total_pages": total_pages}
    if "totalCount" in data:
        pagination["total_count"] = data["totalCount"]
    if "pageSize" in data:
        pagination["page_size"] = data["pageSize"]
    return pagination


# ── Endpoint exploration ────────────────────────────────────────────

def extract_records(data, endpoint):
    """Extract the records list from the API response data.

    ServiceTrade uses camelCase plural keys (e.g. serviceRecurrences,
    companies). We try exact matches first, then fall back to finding
    any list-valued key that isn't pagination metadata.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # Try exact key matches first
        candidates = [endpoint, endpoint + "s", "items"]
        if endpoint.endswith("y"):
            candidates.insert(1, endpoint[:-1] + "ies")
        for key in candidates:
            if key in data and isinstance(data[key], list):
                return data[key]
        # Fall back: find any list key (skip pagination metadata)
        skip_keys = {"page", "totalPages", "totalCount", "pageSize"}
        for key, val in data.items():
            if key not in skip_keys and isinstance(val, list):
                return val
    return []


def explore_endpoint(session, endpoint, required_params=None):
    """Explore a single API endpoint and return its mapping dict.

    Returns (endpoint_name, mapping_dict, records) or None on failure.
    """
    url = f"{BASE_URL}/{endpoint}"
    params = {}
    if required_params:
        params.update(required_params)

    try:
        resp = session.get(url, params=params)
    except requests.RequestException as e:
        logger.error(f"{endpoint}: network error: {e}")
        return None

    if resp.status_code != 200:
        logger.warning(f"{endpoint}: FAILED (HTTP {resp.status_code})")
        return None

    try:
        payload = resp.json()
    except ValueError as e:
        logger.error(f"{endpoint}: invalid JSON response: {e}")
        return None

    data = payload.get("data", payload)
    records = extract_records(data, endpoint)

    if not records:
        logger.info(f"{endpoint}: 0 records (empty)")
        # Still create a minimal mapping entry
        mapping = {
            "api_endpoint": f"/api/{endpoint}",
            "response_data_key": "data",
            "fields": {},
        }
        return endpoint, mapping, []

    # Analyze fields across all records on the first page
    fields = analyze_fields(records)

    # Build mapping
    mapping = {
        "api_endpoint": f"/api/{endpoint}",
        "response_data_key": "data",
    }

    pagination = build_pagination(data) if isinstance(data, dict) else None
    if pagination:
        mapping["pagination"] = pagination

    mapping["fields"] = build_fields_dict(fields)

    record_count = len(records)
    if pagination:
        total = pagination.get("total_count", "?")
        logger.info(f"{endpoint}: {record_count} records (page 1, {total} total), {len(fields)} fields")
    else:
        logger.info(f"{endpoint}: {record_count} records, {len(fields)} fields")

    return endpoint, mapping, records


def explore_child_items(session, endpoint, records):
    """Detect and explore child items embedded in the parent response.

    Returns (child_name, child_mapping) or None.
    """
    embedded_items = []
    parent_id = None
    for record in records:
        items = record.get("items")
        if items and isinstance(items, list) and isinstance(items[0], dict):
            embedded_items = items
            parent_id = record.get("id")
            break

    if not embedded_items or parent_id is None:
        return None

    embedded_keys = set(embedded_items[0].keys())

    # Try the child endpoint for full detail
    child_url = f"{BASE_URL}/{endpoint}/{parent_id}/item"
    child_resp = session.get(child_url)

    child_records = []
    fetch_mode = "inline"

    if child_resp.status_code == 200:
        child_payload = child_resp.json()
        child_data = child_payload.get("data", child_payload)

        if isinstance(child_data, list):
            child_records = child_data
        elif isinstance(child_data, dict):
            for key in ["items", f"{endpoint}items", "data"]:
                if key in child_data and isinstance(child_data[key], list):
                    child_records = child_data[key]
                    break
            if not child_records:
                for key, val in child_data.items():
                    if isinstance(val, list) and val and isinstance(val[0], dict):
                        child_records = val
                        break

        if child_records:
            child_keys = set(child_records[0].keys())
            if embedded_keys < child_keys:
                fetch_mode = "parent_endpoint"
        else:
            child_records = embedded_items
    else:
        child_records = embedded_items

    # For inline mode, gather ALL embedded items across all parent records
    if fetch_mode == "inline":
        all_embedded = []
        for record in records:
            items = record.get("items", [])
            if isinstance(items, list):
                all_embedded.extend(items)
        if all_embedded and isinstance(all_embedded[0], dict):
            child_records = all_embedded

    child_fields = analyze_fields(child_records)

    child_name = f"{endpoint}item"
    child_mapping = {
        "api_endpoint": "embedded",
        "response_data_key": "items",
        "parent_resource": endpoint,
        "parent_id_field": f"{endpoint}Id",
        "fetch_mode": fetch_mode,
        "fields": build_fields_dict(child_fields),
    }

    logger.info(f"  {child_name}: {len(child_fields)} fields (fetch_mode: {fetch_mode})")
    return child_name, child_mapping


def print_verbose(endpoint, records, fields):
    """Print raw JSON and field analysis for debugging."""
    logger.info(f"\n--- {endpoint}: Raw JSON (first 3 records) ---")
    logger.info(json.dumps(records[:3], indent=2))
    logger.info(f"\n--- {endpoint}: Field Analysis ---")
    for name, info in fields.items():
        sample_str = str(info["sample"])
        if len(sample_str) > 80:
            sample_str = sample_str[:80] + "..."
        logger.info(f"  {name:30s} {info['type']:10s} sample: {sample_str}")


def parse_args():
    """Parse command-line arguments."""
    only = None
    verbose = False
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--only" and i + 1 < len(args):
            only = args[i + 1]
            i += 2
        elif args[i] == "--verbose":
            verbose = True
            i += 1
        else:
            logger.error(f"Unknown argument: {args[i]}")
            logger.error("Usage: python system/rebuild_mappings.py [--only <endpoint>] [--verbose]")
            sys.exit(1)
    return only, verbose


def main():
    only, verbose = parse_args()
    endpoints_path, mappings_path = find_files()
    base = os.path.dirname(os.path.dirname(endpoints_path))

    try:
        with open(endpoints_path) as f:
            config = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        logger.exception(f"Failed to load {endpoints_path}: {e}")
        sys.exit(1)

    session = get_session(base)

    static_list = config.get("static_resources", [])
    resources_list = config.get("resources", [])

    all_mappings = {
        "static_resources": static_list,
        "resources": {},
    }

    # Collect all endpoints to explore
    endpoints = []
    for name in static_list:
        endpoints.append({"endpoint": name, "is_static": True})
    for entry in resources_list:
        ep = entry if isinstance(entry, str) else entry.get("endpoint")
        params = entry.get("required_params") if isinstance(entry, dict) else None
        endpoints.append({"endpoint": ep, "is_static": False, "required_params": params})

    # Filter to single endpoint if --only specified
    if only:
        matched = [ep for ep in endpoints if ep["endpoint"] == only]
        if not matched:
            all_names = [ep["endpoint"] for ep in endpoints]
            logger.error(f"Endpoint '{only}' not found in endpoints.yml")
            logger.error(f"Available: {', '.join(all_names)}")
            sys.exit(1)
        endpoints = matched

    logger.info(f"Exploring {len(endpoints)} endpoint{'s' if len(endpoints) != 1 else ''}...")

    explored = 0
    children = 0
    failed = []

    for ep_info in endpoints:
        endpoint = ep_info["endpoint"]
        params = ep_info.get("required_params")
        logger.info(f"Exploring {endpoint}...")

        result = explore_endpoint(session, endpoint, params)
        if result is None:
            failed.append(endpoint)
            continue

        name, mapping, records = result
        all_mappings["resources"][name] = mapping
        explored += 1

        if verbose and records:
            fields = analyze_fields(records)
            print_verbose(endpoint, records, fields)

        # Check for child items
        if records:
            child = explore_child_items(session, endpoint, records)
            if child:
                child_name, child_mapping = child
                all_mappings["resources"][child_name] = child_mapping
                children += 1

                if verbose:
                    # Re-extract child records for verbose output
                    for record in records:
                        items = record.get("items", [])
                        if items and isinstance(items[0], dict):
                            child_fields = analyze_fields(items)
                            print_verbose(child_name, items, child_fields)
                            break

        # Brief pause to respect rate limits
        time.sleep(0.5)

    # Write output
    try:
        with open(mappings_path, "w") as f:
            yaml.dump(all_mappings, f, default_flow_style=False, sort_keys=False)
    except OSError as e:
        logger.exception(f"Failed to write {mappings_path}: {e}")
        sys.exit(1)

    logger.info(f"Generated {mappings_path}")
    logger.info(f"  Endpoints explored: {explored}")
    logger.info(f"  Child resources: {children}")
    logger.info(f"  Total resources: {explored + children}")
    if failed:
        logger.warning(f"  FAILED endpoints: {', '.join(failed)}")


if __name__ == "__main__":
    main()
