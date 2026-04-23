# SafeHoods Documentation

## What is SafeHoods?

SafeHoods is a business intelligence system for a commercial hood cleaning company. The business uses [ServiceTrade](https://servicetrade.com) to manage its operations — customers, jobs, invoices, quotes, technician scheduling, and compliance tracking. SafeHoods pulls that data out of the ServiceTrade API into a local SQLite database, then lets Claude AI answer business questions in plain English by writing SQL on the fly.

The primary user is the company's CFO. Instead of clicking through ServiceTrade's UI or building static reports, he can ask questions like:

- "Which customers are overdue for service?"
- "What's our revenue by technician this quarter?"
- "Show me quote-to-job conversion rates for the last 6 months"
- "Which invoices are past due?"

Claude reads the database schema, writes the SQL, runs it, and returns a human-readable answer.

## How it works

The system has three independent pieces:

```
ServiceTrade API  →  Sync Scripts  →  SQLite Database  →  MCP Server  →  Claude  →  User
```

1. **Sync scripts** pull data from ServiceTrade's API and upsert it into a local SQLite database. The first run does a full backfill (~90 seconds, ~34,000 records). After that, only records changed since the last sync are fetched — incremental runs take under 10 seconds.

2. **SQLite database** stores everything locally. No server to manage, no infrastructure to maintain. The schema covers 16 business tables (companies, locations, jobs, invoices, quotes, assets, deficiencies, etc.) plus 2 admin tables for sync tracking.

3. **MCP server** gives Claude read-only access to the database. Claude gets the full schema as context and can run SELECT queries to answer questions. (This component is currently being built.)

## Why it's built this way

**YAML-driven, not hard-coded.** The entire pipeline — from API field discovery to database schema to sync logic — is driven by YAML configuration files. Adding a new API endpoint means editing a YAML file and running one command, not writing new Python. The sync script is a single generic loop with zero per-table code.

**Schema generated from live API data.** Rather than building the schema from documentation (which has gaps), the system calls each API endpoint, inspects the actual response structure, and generates the schema from what it sees. A separate `api_knowledge.yml` file captures human decisions the code can't infer — like which fields are timestamps, which nested objects should be flattened, and what enum values mean.

**Token-optimized for AI.** The generated `schema.sql` (~3,300 tokens) doubles as Claude's system prompt. It's kept deliberately lean: conventions are documented once in a header, inline comments are added only where the column name alone isn't enough, and runtime database settings live in a separate config file. This keeps every Claude conversation efficient.

## Docs in this directory

| File | What it covers |
|------|----------------|
| [runbooks.md](runbooks.md) | Operational procedures — everyday tasks, add/remove endpoints, resets, recovery |
| [architecture.md](architecture.md) | Full system architecture, design decisions, project structure, and table inventory |
| [auth-reference.md](auth-reference.md) | ServiceTrade API authentication — session auth, token lifecycle, rate limiting, troubleshooting |
| [incremental-api-plan.md](incremental-api-plan.md) | How the API was explored endpoint-by-endpoint, discoveries made, and record counts |
| [APIdocumentation.pdf](APIdocumentation.pdf) | ServiceTrade's official API reference (vendor-provided) |
| [future/](future/) | Design notes for features not yet built |

For pipeline and sync operations, see also:
- [system/README.md](../system/README.md) — schema pipeline, adding new endpoints, debugging
- [sync/README.md](../sync/README.md) — sync operations, runbooks, known limitations
- [schema/README.md](../schema/README.md) — generated files, view creation, design decisions

## Quickstart

### Prerequisites

- Docker
- ServiceTrade API credentials (username and password)

### 1. Set up credentials

Create a `.env` file in the project root:

```
SERVICETRADE_USERNAME=you@example.com
SERVICETRADE_PASSWORD=your_password
```

### 2. Build and start the container

```bash
docker compose up --build -d
```

This builds the image and starts the container in the background. The container runs a cron daemon that triggers the nightly sync automatically per `system/schedule.yml`.

### 3. Generate the schema and create the database

If `schema/schema.sql` already exists (it's checked into the repo), skip straight to creating the database:

```bash
docker exec safehoods-dev python system/create_db.py
```

To regenerate the schema from the live API (requires valid credentials):

```bash
docker exec safehoods-dev python system/rebuild_all.py
docker exec safehoods-dev python system/create_db.py
```

### 4. Run the initial sync

```bash
docker exec safehoods-dev python sync/sync.py
```

This does a full backfill on the first run (~90-100 seconds). Watch progress in real time:

```bash
docker compose logs -f
```

### 5. Create timestamp views (optional)

```bash
docker exec safehoods-dev python schema/generate_views.py
```

This creates `v_` views (e.g. `v_job`, `v_invoice`) that include human-readable dates alongside the raw Unix timestamps.

### 6. Verify

```bash
docker exec safehoods-dev python -c "
import sqlite3
db = sqlite3.connect('data/safehoods.db')
for row in db.execute('SELECT resource, record_count FROM sync_status ORDER BY resource'):
    print(f'{row[0]:25s} {row[1]:>6,d}')
"
```

### Day-to-day usage

```bash
# Watch all container activity (syncs, errors, cron output)
docker compose logs -f

# Incremental sync (run nightly or as needed)
docker exec safehoods-dev python sync/sync.py

# Sync a single resource
docker exec safehoods-dev python sync/sync.py invoice

# Force full re-pull of a resource
docker exec safehoods-dev python sync/sync.py invoice --full

# Stop the container
docker compose down
```

See [sync/README.md](../sync/README.md) for more operations including selective resets.
