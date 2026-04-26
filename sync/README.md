# sync/ — ServiceTrade API Sync

Pulls data from the ServiceTrade API into `data/hoodsbase.db`. Driven entirely by YAML configuration — no per-resource Python code.

For end-to-end operational procedures including add/remove endpoints and full recovery, see [docs/runbooks.md](../docs/runbooks.md).

## Quick Start

```bash
# Inside the Docker container:

# Full sync (all resources — first run does a complete backfill)
python sync/sync.py

# Sync one resource
python sync/sync.py company

# Force full pull (ignore sync_status, re-fetch everything)
python sync/sync.py invoice --full

# Force full pull on all resources
python sync/sync.py --full
```

## Running from Claude

The MCP server exposes a `run_sync` tool, so you can ask Claude to sync without touching the command line:

- *"Run a sync"* — incremental sync of all resources
- *"Sync just invoices"* — single resource
- *"Do a full re-pull of everything"* — full sync

Claude will run the sync and return the summary. This is identical to running the commands below manually.

## Operations

### Daily / Nightly Sync

```bash
python sync/sync.py
```

This is the standard run. Static resources (service_line, tag, etc.) are skipped if already populated. Core resources use `updatedAfter` to fetch only what changed since the last sync. Typical incremental run takes **under 10 seconds** if nothing changed, or a few minutes if there are updates (quote items are the bottleneck at ~100s for a full pull).

### Spot Update — One Resource

```bash
python sync/sync.py invoice
python sync/sync.py job
```

Use this when you know a specific resource has changed and don't want to wait for a full run. Incremental by default — only fetches records updated since the last sync.

### Force Re-Pull — One Resource

```bash
python sync/sync.py invoice --full
```

Ignores `sync_status` and re-fetches everything for that resource. Use when you suspect data drift or want a clean refresh. Does **not** delete existing rows first — it upserts (INSERT OR REPLACE), so stale records from ServiceTrade deletions will remain. See "Nuclear Reset" below if you need to clear those.

### Nuclear Reset — One Resource

When you need a completely clean slate for one resource (e.g. to clear out records that were deleted in ServiceTrade):

```sql
-- In SQLite:
DELETE FROM invoice;
DELETE FROM invoice_item;  -- don't forget child tables
DELETE FROM sync_status WHERE resource IN ('invoice', 'invoiceitem');
```

Then run `python sync/sync.py invoice` — it will do a full backfill.

### Nuclear Reset — Everything

Wipes all data and re-syncs from scratch (~90–100 seconds). This resets data only — the schema pipeline files (`mappings.yml`, `context.yml`, `schema.sql`) are untouched. If you also need to rebuild the schema (e.g. after major changes to `api_knowledge.yml`), see the full procedure in [docs/runbooks.md](../docs/runbooks.md).

```bash
# Recreate empty database
rm data/hoodsbase.db data/hoodsbase.db-wal data/hoodsbase.db-shm
python system/create_db.py

# Full backfill (~90-100 seconds)
python sync/sync.py
```

## Files

| File | Purpose |
|------|---------|
| `sync.py` | Main sync script — auth, fetch, transform, upsert |
| `auth.py` | Standalone auth script (token check + login). `sync.py` has its own `get_session()` that does the same thing as an importable function |

## How It Works

### Resource Types

**Static resources** (service_line, tag, payment_terms, region, tax_rate):
- Only pulled when their table is empty
- Explicitly requesting one (e.g. `python sync/sync.py tag`) forces a re-pull
- `--full` also forces a re-pull

**Core resources** (company, location, contact, job, appointment, service_request, invoice, quote, asset, deficiency, service_recurrence, user):
- First run: full pull (no `sync_status` entry exists)
- Subsequent runs: incremental pull using `updatedAfter={last_synced_at}`
- `--full` ignores `sync_status` and re-fetches everything

**Child resources** (invoice_item, quote_item):
- Not synced independently — handled automatically when their parent syncs
- Invoice items: extracted inline from parent response (0 extra API calls)
- Quote items: sparse inline data, so fetched via `/api/quote/{id}/item` per parent

### Sync Flow

```
1. Load config (mappings.yml, context.yml, endpoints.yml)
2. Authenticate (reuse .session_token or login fresh)
3. For each resource:
   a. Check sync_status → full or incremental?
   b. Fetch all pages from API
   c. Transform each record (context.yml rules)
   d. INSERT OR REPLACE into SQLite
   e. Update sync_status + sync_log
   f. If parent has children → sync child items
```

### Field Transformation

Each API record is transformed using rules from `schema/context.yml`:

| Rule | Example |
|------|---------|
| `skip` | Drop field entirely (e.g. `tags`, `appointments`) |
| `flatten` | `record.address.street` → `address_street` |
| `extract_key: id` | `record.company.id` → `company_id` |
| `db_column` | `refNumber` → `ref_number` |
| `db_type: integer` | `true` → `1`, `false` → `0` |
| `db_type: real` + string | `"9,250.00"` → `9250.0` (quote money fields) |
| `db_type: timestamp` | Kept as integer, `_dt` companion generated (filtered out since schema has no `_dt` columns) |
| dict/list values | `json.dumps()` → stored as TEXT |

### Upsert — How INSERT SQL is Generated

The sync script does **not** use mappings.yml or context.yml to decide which columns to write. Instead, SQL is built dynamically from the intersection of the transformed record and the live schema:

1. **Transform** — `context.yml` rules convert each API record into a flat `{column_name: value}` dict. This dict may contain columns that don't exist in the schema (e.g. `created_at_dt` companion columns).

2. **Schema filter** — Before inserting, `upsert_records()` calls `PRAGMA table_info()` on the target table to get the actual column set from SQLite. Every key in the transformed dict that isn't in that column set is silently dropped. This is how `_dt` companion columns are filtered out — the data tables don't have them.

3. **Dynamic SQL** — For each record, an `INSERT OR REPLACE INTO [table] (col1, col2, ...) VALUES (?, ?, ...)` statement is built from whatever columns survived the filter. Values are passed as parameterized `?` placeholders (no string interpolation). Records are committed in batches of 500.

This means the **schema is the single source of truth** for what gets stored. If you add a column to `schema.sql` and recreate the database, the sync will automatically start writing to it on the next run — no changes to sync.py or the YAML files needed (as long as the transform already produces that column name).

### Rate Limiting

Every API response includes `meta.stats.resourceBalanceMs` — the remaining rate limit budget in milliseconds. The sync script:
- Reads this after every response
- Pauses when budget drops below 10,000ms (configurable via `BUDGET_THRESHOLD_MS`)
- Respects `Retry-After` header on 429 responses

### Resource Name Resolution

The `resource` argument accepts multiple formats:

| Input | Resolves to |
|-------|-------------|
| `company` | `company` (direct match) |
| `service_line` | `serviceline` (underscore removal) |
| `invoice_item` | `invoiceitem` (reverse table name map) |

## API-Specific Behaviors

| Resource | Behavior |
|----------|----------|
| `job` | API defaults to `status=scheduled`; sync passes `status=all` to get all jobs |
| `asset` | API requires `updatedAfter` filter; uses `required_params` from `endpoints.yml` |
| `servicerecurrence` | Same `updatedAfter` requirement; slow endpoint (~17s response) |
| `invoice` (items) | Items fully embedded in parent response — inline extraction |
| `quote` (items) | Items sparse inline — requires per-parent API call to `/quote/{id}/item` |

## Observability

### sync_status table

One row per resource. Updated after each successful sync.

```sql
SELECT resource, last_synced_at_dt, record_count FROM sync_status ORDER BY resource;
```

### sync_log table

One row per resource per sync run. Tracks timing, counts, and errors.

```sql
-- Recent sync activity
SELECT resource, status, records_fetched, records_upserted, started_at_dt
FROM sync_log ORDER BY id DESC LIMIT 20;

-- Find failures
SELECT * FROM sync_log WHERE status = 'failed';
```

### Pipeline Log

All sync activity is written to `logs/pipeline.log` — timestamped, structured entries covering resource names, sync mode (full/incremental), page-by-page progress with API budget, record counts, warnings, and errors. The log also streams to stdout during interactive runs, which means it appears in `docker compose logs` for both on-demand and nightly scheduled syncs.

```bash
# Watch live
docker compose logs -f

# View recent entries directly
docker exec hoodsbase-dev tail -100 logs/pipeline.log

# Filter to errors and warnings
docker exec hoodsbase-dev grep -E " (ERROR|WARNING) " logs/pipeline.log
```

The log rotates automatically at 5 MB, keeping 5 backups. Claude can also read it during a conversation via the MCP `read_log()` tool.

## Record Counts (snapshot)

*Last refreshed: 2026-04-26*

| Table | Records |
|-------|---------|
| service_line | 11 |
| tag | 32 |
| payment_terms | 10 |
| company | 559 |
| location | 637 |
| contact | 897 |
| job | 6,216 |
| appointment | 7,544 |
| service_request | 14,627 |
| invoice | 5,338 |
| invoice_item | 6,635 |
| quote | 630 |
| quote_item | 1,113 |
| asset | 646 |
| deficiency | 73 |
| service_recurrence | 4,497 |
| user | 16 |

## Configuration Files

The sync script reads three YAML files (it does not modify them):

- **`schema/mappings.yml`** — API endpoints, field types, pagination info, child resource annotations
- **`schema/context.yml`** — field transforms (renames, skips, flattens, FK extraction, type overrides)
- **`system/endpoints.yml`** — `required_params` for endpoints that need mandatory filters

## Known Limitations

- **No delete detection**: The API has no "deleted since" endpoint. Records deleted in ServiceTrade remain in SQLite until a selective reset is done.
- **Quote item sync is slow**: ~100s for 627 quotes (one API call per quote). Invoice items are instant (inline extraction).
- **`_dt` companion columns**: The sync generates ISO 8601 timestamps but the schema doesn't include `_dt` columns on data tables, so they're silently filtered out during upsert. Only `sync_status` and `sync_log` have `_dt` columns.
