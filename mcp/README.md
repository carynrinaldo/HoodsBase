# mcp/ — HoodsBase MCP Server

Gives Claude read-only access to the HoodsBase SQLite database. Claude connects to this server, receives the full annotated database schema as context, and uses the tools here to answer the CFO's business questions in natural language.

## Files

| File | Purpose |
|------|---------|
| `server.py` | The MCP server — schema injection, query execution, sync status |

## How it works

When a client (Claude) connects, the server delivers the full annotated `schema/schema.sql` as its `instructions` field. Claude has the schema in context for the entire conversation and can call tools to query the database without needing to fetch the schema again on every turn.

The server enforces read-only access: only `SELECT` and `WITH` statements are accepted. Write keywords (`INSERT`, `UPDATE`, `DELETE`, `DROP`, etc.) are blocked by both a first-word check and a regex scan of the full query. A default `LIMIT 1000` is appended to any query that omits one.

## Tools

| Tool | Description |
|------|-------------|
| `execute_query(sql)` | Run a SELECT query against `data/hoodsbase.db`. Returns a JSON array of row objects. |
| `get_sync_status()` | Return last sync time and record count per resource from `sync_status`. Use this to tell the user how fresh the data is. |
| `run_sync(resource, full)` | Run a data sync from ServiceTrade. Defaults to incremental sync of all resources. Pass a resource name to sync one, or `full=True` to re-pull everything. Returns the sync summary. |
| `get_schema()` | Return the raw `schema.sql` text. Rarely needed — the schema is already in the system prompt. |
| `read_log(lines)` | Return the last N lines of `logs/pipeline.log` (default 100). Use during troubleshooting to inspect recent sync activity, errors, and warnings. |

## Running the server

The server communicates over stdio (JSON-RPC). Start it directly:

```bash
python mcp/server.py
```

Or inside the Docker container:

```bash
docker exec hoodsbase-dev python /app/mcp/server.py
```

### Connecting from Claude Desktop

Add an entry to your Claude Desktop `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "hoodsbase": {
      "command": "docker",
      "args": ["exec", "-i", "hoodsbase-dev", "python", "/app/mcp/server.py"]
    }
  }
}
```

The container must be running (`docker compose up -d`) before Claude Desktop connects.

## Prerequisites

- `data/hoodsbase.db` must exist and be populated. Run the sync first if it doesn't:
  ```bash
  docker exec hoodsbase-dev python system/create_db.py
  docker exec hoodsbase-dev python sync/sync.py
  ```
- The `mcp[cli]` package must be installed (included in the Dockerfile).

## Query behavior

- **Aggregations preferred** — Claude is instructed to use `COUNT`, `SUM`, `GROUP BY`, etc. so result sets stay small and token-efficient.
- **Auto-limit** — Queries without a `LIMIT` clause get `LIMIT 1000` appended automatically.
- **Views available** — `v_` views (e.g. `v_job`, `v_invoice`) expose human-readable `_dt` timestamp columns alongside the raw Unix epoch integers. Claude can use these for date comparisons and display.
- **Read-only** — No writes reach the database through this server under any circumstances.

## Related

- [schema/README.md](../schema/README.md) — how `schema.sql` is generated and what the `v_` views cover
- [sync/README.md](../sync/README.md) — how the database is populated and kept current
- [docs/architecture.md](../docs/architecture.md) — full system design and design decisions
