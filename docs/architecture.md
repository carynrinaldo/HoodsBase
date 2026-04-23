# Hood Cleaning Business Intelligence System
## Architecture & Engineering Decisions

---

## Overview

This document describes the architecture of a business intelligence system built on top of the ServiceTrade field service management platform for a commercial hood cleaning contractor. The system allows the business owner to ask natural language questions about his business and receive answers powered by Claude AI, backed by a local SQLite database synced from the ServiceTrade API.

---

## Business Context

The client runs a commercial hood cleaning service. This is a compliance-driven business — restaurants and commercial kitchens are required by fire code (NFPA 96) to have their exhaust hoods cleaned on a recurring schedule (quarterly, semi-annually, or annually depending on cooking volume). The business model is therefore largely recurring, contract-based work.

Key business metrics the system is designed to support:
- Which customers are due (or overdue) for service
- Revenue by customer, location, and technician
- Quote-to-job conversion rates
- Invoice aging and collections status
- Deficiency tracking (compliance issues found during service)
- Technician productivity

The primary user is an experienced CFO who currently thinks in terms of reports and structured data. The early use of the system will be natural language querying of business data, with strategic conversation capabilities layered in over time.

---

## System Architecture

The system has three distinct components that operate independently:

```
ServiceTrade API
      |
      | (nightly sync)
      v
 Sync Job(s)
      |
      | (upsert)
      v
 SQLite Database  <---  MCP Server  <---  Claude  <---  User
```

### Component 1: Sync Jobs

A set of scheduled scripts that pull data from the ServiceTrade API and upsert it into the local SQLite database.

**Key design decisions:**

- **Incremental sync**: On first run, a full historical backfill is performed (~90-100 seconds). On subsequent runs, only records updated since the last sync are fetched via `updatedAfter`. Incremental runs take under 10 seconds if nothing changed.
- **YAML-driven generic loop**: A single `sync/sync.py` with no per-resource Python code. All field transformations (renames, type coercion, FK extraction, address flattening) are driven by `schema/mappings.yml` + `schema/context.yml`.
- **Budget-aware throttling**: Every API response includes `meta.stats.resourceBalanceMs`. The sync script monitors this and pauses when budget drops below 10,000ms. Also respects `Retry-After` headers on 429 responses.
- **Sync metadata table**: A `sync_status` table tracks the last successful sync timestamp per resource. This is what makes incremental sync reliable across runs.
- **Sync log table**: Every sync run is recorded in `sync_log` with status, record counts, and any errors. Claude can query this table to tell the user how fresh the data is.
- **Pipeline log file**: All pipeline activity (sync, schema generation, database setup) is written to `logs/pipeline.log` using Python's `logging` module via `utils/logging_config.py`. Entries include timestamp, module name, log level, and message. The log rotates at 5 MB (5 backups). Claude can read it via the MCP `read_log()` tool for troubleshooting.
- **Child resource handling**: Invoice items are extracted inline from the parent response (0 extra API calls). Quote items require per-parent API calls (~100s for 627 quotes).
- **Run frequency**: Nightly is sufficient for most analytical use cases. The sync runs automatically via cron inside the Docker container, configured by `system/schedule.yml`. Also supports manual single-resource sync (`python sync/sync.py invoice`) and forced full re-pull (`--full` flag).

**ServiceTrade API notes:**
- Base URL: `https://api.servicetrade.com/api`
- Authentication: Session-based (POST credentials to `/auth`, reuse the session token) or OAuth2 Bearer token
- Pagination: Results are paginated; use `page=n` parameter to iterate
- Rate limiting: 60 seconds of resource time per minute per user (`resourceBalanceMs` in response `meta.stats`); respect `Retry-After` headers on 429 responses
- All timestamps are Unix epoch integers

### Component 2: SQLite Database

The local data store. Acts as the source of truth for all Claude queries. SQLite is appropriate here because:
- The dataset is single-company and fits comfortably in a local file
- No server infrastructure to maintain
- Excellent query performance for analytical workloads
- Portable and easy to back up

The schema is generated via a four-stage pipeline (see `system/README.md` for details):

1. `system/rebuild_mappings.py` — calls the live API and writes `schema/mappings.yml` (field structure, pagination, child resource annotations)
2. `system/rebuild_context.py` — merges `mappings.yml` with `system/api_knowledge.yml` (curated business context and type rules) to produce `schema/context.yml`
3. `schema/generate_schema.py` — reads `mappings.yml` + `context.yml` and produces `schema/schema.sql`
4. `system/create_db.py` — reads `schema/schema.sql` + `system/db_settings.yml` and creates `data/safehoods.db`

`schema.sql` is deliberately kept as clean DDL — no pragmas, no `IF NOT EXISTS`, no runtime settings — because it doubles as Claude's MCP system prompt (~3,300 tokens). Runtime database settings (WAL mode, create behavior) are configured in `system/db_settings.yml` and applied by `create_db.py` when creating the actual database. This separation keeps the MCP prompt free of noise while allowing database behavior to be changed without regenerating the schema.

Inline comments are limited to enums and non-obvious semantics; conventions (_id = FK, _dt = timestamp companion, JSON TEXT columns, INTEGER booleans) are documented once in a header. Run `python system/rebuild_all.py` to execute stages 1–3 (or `--skip-mappings` to skip API calls), then `python system/create_db.py` for stage 4.

**Tables synced from ServiceTrade API:**

| Table | Description |
|---|---|
| company | Customer businesses (e.g. "Joe's Pizza") |
| location | Physical service addresses under a company |
| contact | People associated with a company or location |
| asset | Equipment at a location (hoods, fans, filters) |
| user | ServiceTrade users (technicians, office staff) |
| service_line | Trade categories (e.g. "Kitchen Exhaust Cleaning") |
| service_recurrence | Recurring contract schedules — critical for compliance tracking |
| job | Work orders — the central entity |
| appointment | Scheduled time blocks on a job (dispatch board entries) |
| invoice | Bills sent to customers |
| invoice_item | Line items on an invoice |
| quote | Price estimates for repair work |
| quote_item | Line items on a quote |
| deficiency | Compliance issues found during service visits |
| region | Geographic territories |
| tag | Freeform labels for segmenting data |
| tax_rate | Tax rates applied to invoices |
| payment_terms | Net-30, Net-15, etc. |

**Admin tables (internal, not from API):**

| Table | Description |
|---|---|
| sync_status | Last successful sync timestamp per resource |
| sync_log | Historical record of every sync run |

### Component 3: MCP Server

A Model Context Protocol server that sits on top of SQLite and exposes tools that Claude can call to answer the user's questions.

**Key design decisions:**

- **Claude writes its own SQL**: Rather than building a library of canned queries, the MCP server provides Claude with the database schema (as an annotated `CREATE` script) and a generic `execute_query` tool. Claude generates the SQL dynamically based on the user's question. This handles the unpredictable nature of a CFO's ad hoc questions far better than pre-built queries.
- **Schema delivered via system prompt**: The annotated schema is loaded into Claude's system prompt once per conversation, not on every message. This avoids repeated token consumption while ensuring Claude always has the structural and business context it needs.
- **SELECT only**: The `execute_query` tool validates that only `SELECT` statements are submitted before execution. No writes, updates, or deletes are permitted through the MCP interface.
- **Small, targeted result sets**: The database does the aggregation work. Claude receives compact, purposeful result sets — not raw table dumps. This keeps token usage efficient.
- **Output formats**: Conversational answers for strategic questions; CSV or formatted tables for data queries. CSV generation is handled by a separate local tool outside the MCP server.

**MCP tools:**

| Tool | Description |
|---|---|
| `execute_query(sql)` | Run a SELECT query against SQLite and return results |
| `get_sync_status()` | Return last sync timestamps so Claude can report data freshness |
| `get_schema()` | Return the annotated schema (used to populate system prompt) |
| `read_log(lines)` | Tail the pipeline log file — used during troubleshooting sessions |
| `create_view(name, description, sql)` | Save a SELECT query as a named SQLite view (`report_` prefix enforced); writes a backup `.sql` file to `reports/` |
| `list_views()` | List all saved report views with their descriptions and SQL definitions |
| `drop_view(name)` | Remove a saved report view and its backup file |

---

## Project Structure

```
SafeHoods/
├── system/                  # Pipeline source-of-truth files & database setup
│   ├── endpoints.yml        # API endpoints to explore
│   ├── api_knowledge.yml    # Curated business context & type rules
│   ├── db_settings.yml      # Database config: pragmas, create mode
│   ├── rebuild_mappings.py  # Live API → mappings.yml
│   ├── rebuild_context.py   # mappings + knowledge → context.yml
│   ├── rebuild_all.py       # Orchestrates the full pipeline
│   ├── create_db.py         # schema.sql + db_settings.yml → safehoods.db
│   ├── schedule.yml         # Sync schedule config — edit this to change run time
│   └── write_crontab.py     # Generates /etc/cron.d/safehoods at container startup
├── schema/                  # Generated schema files
│   ├── mappings.yml         # Auto-generated API field structure
│   ├── context.yml          # Auto-generated business context (from api_knowledge.yml)
│   ├── generate_schema.py   # YAML → schema.sql generator
│   └── schema.sql           # Generated SQLite schema (~3,300 tokens)
├── sync/                    # API sync scripts
│   ├── sync.py              # Main sync script — auth, fetch, transform, upsert
│   ├── auth.py              # Standalone auth script (token check + login)
│   └── README.md            # Sync operations guide and runbooks
├── mcp/
│   └── server.py            # MCP server — schema injection, execute_query, get_sync_status, read_log
├── utils/
│   └── logging_config.py    # Shared logging setup — all pipeline scripts import this
├── logs/                    # Pipeline log files (gitignored)
│   └── pipeline.log         # Rotating log: all pipeline + sync activity
├── data/                    # SQLite database (gitignored)
├── docs/                    # Architecture docs, API reference, runbooks
├── Dockerfile               # Container: python:3.12-slim + cron
├── entrypoint.sh            # Container startup — writes crontab, starts crond
├── .env                     # ServiceTrade credentials (gitignored)
└── .session_token           # Persisted auth token (gitignored)
```

---

## ServiceTrade API — Resources with GET Support

The following resources support GET/read operations and are candidates for syncing. The priority resources for a hood cleaning business are marked.

**High priority for sync:**
account, accountsettings, appointment, asset, assetdefinition, company, contact, deficiency, invoice, invoiceitem, job, jobitem, location, quote, quoteitem, servicerecurrence, servicerequest, serviceline, user

**Moderate priority:**
attachment, budget, comment, clockevent (clock in/out), deficiencyreport, payment, paymentterms, quotetemplate, region, tag, taxrate, taxgroup, terms, timecard, warehouse

**Low priority / operational (likely not needed for analysis):**
auth, eula, externalsync, externalsystem, externalid, heartbeat, history, import, legacylookup, marketing, message, oauth2credentials, oauth2token, role, schedulingqueue, servicetemplate, webhook

---

## Token Efficiency Strategy

Token usage is managed at the MCP layer through query discipline:

1. **SQL does the work**: Aggregations, filters, and joins happen in SQLite. Claude receives results, not raw data.
2. **Schema in system prompt**: Loaded once, not repeated in user turns.
3. **Multiple small tool calls**: For broad questions, Claude makes several targeted calls rather than one large data pull.
4. **No raw table dumps**: The `execute_query` tool should be used with purposeful, specific queries.

---

## What We Don't Know Yet

- The specific reports and questions the CFO will ask most frequently (recommend a discovery interview before building)
- Whether a nightly sync is sufficient or if near-real-time is needed for dispatch/scheduling questions

---

## Next Steps

1. ~~Confirm ServiceTrade API access and credentials~~ — Done
2. ~~Explore API endpoints and build schema pipeline~~ — Done (18 resources, fully automated pipeline)
3. ~~Generate `schema/schema.sql` from YAML files~~ — Done (18 tables: 3 static + 13 core + 2 admin, ~3,300 tokens)
4. ~~Create SQLite database from schema~~ — Done (`system/create_db.py` + `system/db_settings.yml`, WAL mode enabled)
5. ~~Build the sync script driven by `schema/mappings.yml`~~ — Done (`sync/sync.py`, YAML-driven generic loop, see `sync/README.md`)
6. ~~Build the MCP server with the three initial tools~~ — Done (`mcp/server.py`, FastMCP with `execute_query`, `get_sync_status`, `get_schema`, `read_log`)
7. Test end-to-end with Claude against real data
8. ~~Build saved-view report tools (`create_view`, `list_views`, `drop_view`)~~ — Done (see `docs/future/saved-views.md`)
9. Interview the client to identify the top 5-10 questions/reports he wants
10. Iterate on schema and tools based on actual questions asked
