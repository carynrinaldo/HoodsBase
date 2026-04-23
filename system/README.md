# system/ — API Knowledge, Schema Pipeline, Database Setup & Scheduling

This folder contains the **source-of-truth files** that drive reproducible schema generation from the ServiceTrade API, database creation, and the nightly sync schedule. Nothing in `schema/` needs to be hand-edited — it's all generated from the files here plus `schema/generate_schema.py`.

For end-to-end operational procedures (add/remove endpoints, resets, data recovery), see [docs/runbooks.md](../docs/runbooks.md).

## Quick Start

```bash
# Full pipeline (requires live API session):
python system/rebuild_all.py

# Skip API calls (reuse existing mappings.yml):
python system/rebuild_all.py --skip-mappings

# Create the SQLite database from schema.sql:
python system/create_db.py
```

## Pipeline

```
system/endpoints.yml ──→ rebuild_mappings.py ──→ schema/mappings.yml
                                                       │
system/api_knowledge.yml ──────────────────────────────┤
                                                       ▼
                              rebuild_context.py ──→ schema/context.yml
                                                          │
                                    schema/mappings.yml ──┤
                                                          ▼
                                       generate_schema.py ──→ schema/schema.sql (MCP prompt)
                                                                    │
                                    system/db_settings.yml ─────────┤
                                                                    ▼
                                                 create_db.py ──→ data/safehoods.db
```

## Files

### db_settings.yml
Database configuration in YAML — edit this instead of modifying Python code. Two settings:

| Setting | Purpose |
|---------|---------|
| `pragmas` | SQLite PRAGMA statements applied after database creation (e.g. `journal_mode=WAL` for concurrent access) |
| `create_mode` | How `CREATE TABLE` is handled: `create_if_not_exists` (safe to re-run, default) or `drop_and_create` (destroys all data) |

See the file itself for detailed comments on each option and common pragma values.

### create_db.py
Reads `schema/schema.sql` and `system/db_settings.yml`, creates `data/safehoods.db`. Safe to run repeatedly — with `create_if_not_exists` mode, existing tables and data are untouched and new tables are added.

```bash
python system/create_db.py
```

### endpoints.yml
Lists every ServiceTrade API endpoint to explore. Two sections:
- **static_resources** — reference tables synced in full (serviceline, tag, paymentterms, region, taxrate)
- **resources** — core tables synced incrementally, with optional `required_params` (e.g. asset needs `updatedAfter`)

Child resources (invoiceitem, quoteitem) are auto-detected and don't need listing here.

### api_knowledge.yml
All field-level decisions that can't be derived from API response structure alone. This is a curated digest of `docs/APIdocumentation.pdf` — it captures the knowledge needed to produce a correct, token-optimized schema. It is **not** an exhaustive reproduction of the PDF; it focuses on what affects schema generation.

Six sections:

| Section | Purpose |
|---------|---------|
| `global_rules` | Mechanical transforms applied to every field: camelCase→snake_case, boolean→integer, FK object extraction, address flattening, array-of-objects skip, standard field renames |
| `timestamp_fields` | Integer fields that are Unix timestamps (not counts). Get `db_type: timestamp` → INTEGER with `_dt` companion at sync time |
| `type_corrections` | Fields where API type inference is unreliable (money fields inferred as integer, sort fields as text). Maps field name → correct `db_type`, applied globally |
| `is_prefix_renames` | Boolean API fields that lack an `is_` prefix (e.g. `customer` → `is_customer`) |
| `enums` | Status/type/severity enum values → inline SQL comments. What Claude needs for correct WHERE clauses |
| `resource_overrides` | Per-resource field rules: skips, FK extracts for `unknown`-type fields, type overrides, `prompt_comment` values, table descriptions. Also supports `skip_resource: true` to exclude a resource entirely |

**When to edit:**
- Adding a new endpoint — add `resource_overrides` entry with description and field rules
- A field's behavior doesn't match global rules — add a field override
- New enum values — add to `enums` section
- New timestamp field — add to `timestamp_fields`
- API type inference is wrong for a field (e.g. money inferred as integer) — add to `type_corrections`
- Fields with `api_type: unknown` that are FK objects — add `extract_key: id` + `db_type: integer`

### rebuild_mappings.py
Reads `system/endpoints.yml`, calls the ServiceTrade API for each endpoint, and writes `schema/mappings.yml` with inferred field types, nested object keys, and pagination info. Automatically detects child resources (e.g. invoiceitem from invoice's `items` array).

**Options:**
- `--only <endpoint>` — process a single endpoint instead of all (must be listed in endpoints.yml)
- `--verbose` — print raw JSON (first 3 records) and field-by-field type/sample analysis

**Important:** `mappings.yml` is approximate — field types depend on which records the API returns. Fields that are null across all first-page records get `api_type: unknown`. This is corrected by `api_knowledge.yml` overrides.

### rebuild_context.py
Reads `schema/mappings.yml` + `system/api_knowledge.yml`, outputs `schema/context.yml`.

Applies rules in priority order per field:
1. Field overrides from `resource_overrides` (highest priority)
2. Global field renames (created→created_at, etc.)
3. Timestamp field detection
4. Address object flattening
5. FK object extraction (objects with `id` in nested_keys)
6. Array-of-objects skip
7. Boolean→integer coercion + `is_` prefix renames
8. Arrays of primitives → text
9. Objects without special handling → text
10. camelCase→snake_case catch-all
11. Enum prompt_comments

After generating context.yml, prints **validation warnings** for:
- Fields with `api_type: unknown` that have no override (likely missing FK definitions)
- Resources with no description in `api_knowledge.yml`

### rebuild_all.py
Orchestration script — runs the full pipeline in order:
1. `rebuild_mappings.py` (live API → mappings.yml)
2. `rebuild_context.py` (mappings + knowledge → context.yml)
3. `generate_schema.py` (mappings + context → schema.sql)

Use `--skip-mappings` to skip step 1 when mappings.yml is already current.

---

## Scheduling

These files control when the nightly sync runs inside the Docker container.

### schedule.yml
**The only file the user needs to edit to change the sync schedule.** Set the time in 24-hour format — the container's timezone is America/Los_Angeles (set in the Dockerfile).

```yaml
sync_time: "02:00"   # 2:00 AM Pacific
```

To apply a change: edit this file and restart the container (`docker restart safehoods-dev`). The new schedule takes effect on the next startup.

### write_crontab.py
Called automatically by `entrypoint.sh` at container startup. Reads `schedule.yml`, validates the time format, and writes `/etc/cron.d/safehoods`. Not intended to be run manually.

**What it does:**
- Parses `sync_time` from `schedule.yml`
- Validates format (`HH:MM`, 24-hour) and range — exits non-zero with a clear error if invalid so the container fails fast rather than silently never syncing
- Writes the cron entry to `/etc/cron.d/safehoods` with correct permissions (0644, required by cron)

---

## Logging

All pipeline scripts write to a single shared log file: `logs/pipeline.log`.

Log entries follow a standard format:

```
2026-03-18 02:14:33  sync.sync            INFO      [invoice] Fetched 48 records (3 page(s))
2026-03-18 02:14:35  sync.sync            WARNING   Rate limit budget low (8200ms), waiting 7s...
2026-03-18 02:14:36  sync.auth            ERROR     Auth: failed (HTTP 401)
```

**Format:** `datetime  module               level     message`

The log is written by `utils/logging_config.py`, which is imported by every pipeline script. It configures:
- **File handler** → `logs/pipeline.log`, rotating at 5 MB, keeping 5 backups
- **Stream handler** → stdout (visible in terminal for interactive / on-demand runs)

Log rotation is handled automatically in Python — no external logrotate config is needed.

To view the log from inside the container:

```bash
tail -100 logs/pipeline.log
```

To view errors only:

```bash
grep " ERROR " logs/pipeline.log
grep " WARNING " logs/pipeline.log
```

Claude can also read the log directly via the MCP `read_log(lines)` tool — useful during troubleshooting sessions.

---

## How to add a new API endpoint

For the full end-to-end procedure including populating the table, see [docs/runbooks.md](../docs/runbooks.md). The schema pipeline steps are:

1. Run `python system/rebuild_mappings.py --only <endpoint> --verbose` to inspect the API response and write the `mappings.yml` entry
2. Add a `resource_overrides` entry to `api_knowledge.yml` with at minimum a `description`. Ask Claude to help using the relevant pages of `docs/APIdocumentation.pdf`.
3. Run `python system/rebuild_all.py --skip-mappings` to regenerate `context.yml` and `schema.sql`
4. Check for warnings — any `api_type: unknown` fields without overrides need attention
5. Verify the new table in `schema/schema.sql`
6. Run `python system/create_db.py` to add the new table to the live database (safe — existing data untouched)
7. Run `python sync/sync.py <resource>` to populate the new table

## How to remove an endpoint

For the full procedure including dropping the table, see [docs/runbooks.md](../docs/runbooks.md). The schema pipeline steps are:

1. In `api_knowledge.yml`, find the resource's `resource_overrides` entry and add `skip_resource: true`
2. Run `python system/rebuild_all.py --skip-mappings` — the table will no longer appear in `schema.sql` or `context.yml`, and the sync will ignore it going forward
3. Optionally drop the table from the database (see runbooks). If you don't, the table sits there harmlessly. Note that `create_db.py` will not recreate a dropped table.

## Debugging a single endpoint

To inspect the raw API response and field analysis for one endpoint without rebuilding everything:

```bash
python system/rebuild_mappings.py --only asset --verbose
```

This prints:
- Raw JSON (first 3 records) — see exactly what the API returns
- Field analysis — every field with its inferred type and a sample value
- Child item detection — if the endpoint has embedded items

Useful when:
- Adding a new endpoint and you need to see the response shape
- A field has `api_type: unknown` and you need to check what the API actually returns
- You suspect the API response structure has changed

## Key concepts

- **`api_type: unknown`** — Fields null in the first API page. `rebuild_context.py` warns about these. Most need explicit overrides: FK objects need `extract_key: id` + `db_type: integer`; text fields need `db_type: text`; timestamps are handled if listed in `timestamp_fields`.
- **`skip_fk_extract: true`** — Prevents FK extraction on fields that look like objects but are plain text (e.g. `serviceLine` on job is a deprecated text abbreviation, not a FK).
- **`skip_resource: true`** — Excludes an entire resource from context.yml and schema.sql.
- **`prompt_comment`** — Terse inline SQL comment for Claude's MCP system prompt. Only add where the column name alone isn't enough. Saves tokens.
- **Token optimization** — `schema.sql` loads into Claude's system prompt on every conversation (~3,300 tokens). Only add comments that help Claude write correct SQL.
- **Parent FK columns** — Child resources (invoiceitem, quoteitem) automatically get a parent FK column (e.g. `invoice_id`) from the `parent_id_field` in mappings.yml, even if the API doesn't return it directly.
