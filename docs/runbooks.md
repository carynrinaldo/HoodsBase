# SafeHoods Operations Runbook

Organized from most common to most disruptive. The first half covers everyday tasks you can run safely and repeatedly. The second half covers structural changes and recovery procedures — read the notes before running anything there.

Start the container if it isn't running:

```bash
docker compose up -d
```

All commands run inside the Docker container. Either open a shell:

```bash
docker exec -it safehoods-dev bash
```

Or prefix each command with `docker exec safehoods-dev`.

To watch all container activity (syncs, errors, cron output) as a single stream:

```bash
docker compose logs -f
```

---

## Everyday Tasks

### Check data freshness

Ask Claude: *"When was the data last synced?"* — it will call `get_sync_status()` and tell you. Or query directly:

```sql
SELECT resource, last_synced_at_dt, record_count FROM sync_status ORDER BY resource;
```

### View the sync log

```bash
tail -100 logs/pipeline.log
```

To filter to errors and warnings only:

```bash
grep -E " (ERROR|WARNING) " logs/pipeline.log
```

The log covers all pipeline scripts (sync, schema generation, database setup) with timestamps, module names, and log levels. It rotates automatically at 5 MB, keeping 5 backups (`pipeline.log.1` through `pipeline.log.5`).

For a summary of sync run outcomes (success/failure per resource), query the database:

```sql
SELECT resource, status, error_message, started_at_dt FROM sync_log WHERE status = 'failed' ORDER BY id DESC;
```

You can also ask Claude to check the logs during a conversation — it has a `read_log()` tool that returns recent log entries.

### Trigger a manual sync

The container runs the sync automatically each night, but you can run it anytime from inside the container:

```bash
python sync/sync.py
```

Incremental — only fetches records changed since the last run. Typically under 10 seconds if nothing has changed.

### Sync a single resource

```bash
python sync/sync.py invoice
python sync/sync.py job
```

### Change the sync schedule

Edit `system/schedule.yml` — it's the only file you need:

```yaml
sync_time: "02:00"   # change this to any 24-hour time
```

Then restart the container to apply it:

```bash
docker restart safehoods-dev
```

---

## Maintenance Tasks

### Force a full re-pull of one resource

Use this when you suspect local data is stale or out of sync with ServiceTrade:

```bash
python sync/sync.py invoice --full
```

Re-fetches all records and upserts them. **Does not delete existing rows first** — if a record was deleted in ServiceTrade, it will remain in SQLite. Use the selective reset below if you need to clear deleted records.

### Selective reset — one resource

Use this when a resource has records in SQLite that were deleted in ServiceTrade. `--full` won't clear them because it upserts rather than replacing the whole table.

**Only affects the specified resource. Everything else is untouched.**

```bash
# Step 1: Open SQLite
docker exec -it safehoods-dev python3 -c "import sqlite3; conn = sqlite3.connect('data/safehoods.db')"
```

Actually, open SQLite directly:

```bash
docker exec -it safehoods-dev python3 -c "
import sqlite3
conn = sqlite3.connect('data/safehoods.db')
conn.execute('DELETE FROM invoice')
conn.execute('DELETE FROM invoice_item')
conn.execute(\"DELETE FROM sync_status WHERE resource IN ('invoice', 'invoiceitem')\")
conn.commit()
print('Done')
"
```

Or use any SQLite client pointed at `data/safehoods.db`, then:

```bash
# Step 2: Full re-pull
python sync/sync.py invoice
```

Child table pairs to remember:
- `invoice` → also clear `invoice_item`
- `quote` → also clear `quote_item`

---

## Structural Changes

These procedures change what data the system collects. They touch the schema pipeline and the database structure, not just the data.

### Add a new endpoint / table

This crosses two parts of the system — the schema pipeline (`system/`) and the sync. Do the steps in order.

**1. Inspect the API response**

```bash
python system/rebuild_mappings.py --only newresource --verbose
```

This prints the raw JSON shape and inferred field types. It writes the new entry into `schema/mappings.yml`.

**2. Add business context**

Add a `resource_overrides` entry to `system/api_knowledge.yml`. At minimum you need a `description`. Ask Claude to help by pointing it at the relevant section of `docs/APIdocumentation.pdf`. See existing entries in the file for the format.

**3. Rebuild the schema pipeline**

```bash
python system/rebuild_all.py --skip-mappings
```

Check the output for warnings. Any `api_type: unknown` fields without overrides need attention in `api_knowledge.yml` before continuing.

**4. Verify the new table in the schema**

Open `schema/schema.sql` and confirm the new `CREATE TABLE` block is there and looks right.

**5. Add the table to the live database**

```bash
python system/create_db.py
```

Safe to run on a live database — it only adds new tables, existing data is untouched.

**6. Populate the table**

```bash
python sync/sync.py newresource
```

### Remove an endpoint / table

Removing an endpoint stops it from syncing but **does not automatically remove the table from the database**. The data will just sit there unused unless you explicitly drop it.

**1. Mark it for exclusion**

In `system/api_knowledge.yml`, find the resource's `resource_overrides` entry and add:

```yaml
skip_resource: true
```

**2. Rebuild the pipeline**

```bash
python system/rebuild_all.py --skip-mappings
```

The table will no longer appear in `schema/schema.sql` or `schema/context.yml`. The sync script will ignore it going forward.

**3. Optionally drop the table from the database**

You don't have to do this — the table will just sit there harmlessly. But if you want it gone:

```sql
DROP TABLE resource_name;
DELETE FROM sync_status WHERE resource = 'resourcename';
```

Note: `create_db.py` uses `CREATE TABLE IF NOT EXISTS` by default, so re-running it will **not** recreate a dropped table. The removal is permanent until you reverse step 1.

---

## Recovery Procedures

These procedures delete data or rebuild core files. Read the notes before running anything.

### Complete database reset

**When to use:** The database is corrupt, badly out of sync, or you want a guaranteed clean slate.

**What it deletes:** All ~34,000 records. The full backfill to restore takes approximately 90–100 seconds.

**What it does NOT affect:** The schema pipeline files (`mappings.yml`, `context.yml`, `schema.sql`). You are resetting the data only, not the structure.

```bash
# Step 1: Delete the database files
rm data/safehoods.db data/safehoods.db-wal data/safehoods.db-shm

# Step 2: Recreate the empty database from the existing schema
#         Also restores any saved report views from reports/*.sql automatically
python system/create_db.py

# Step 3: Full backfill (~90-100 seconds)
python sync/sync.py
```

Any report views previously saved via Claude's `create_view` tool are automatically restored in Step 2 from their backup files in `reports/`. No manual action needed.

### Rebuild the schema pipeline from scratch

**When to use:** The YAML pipeline files (`schema/mappings.yml`, `schema/context.yml`, `schema/schema.sql`) are out of date or you've made substantial changes to `system/api_knowledge.yml` and want everything regenerated clean. Requires a live ServiceTrade API session.

**What it changes:** Regenerates `schema/mappings.yml`, `schema/context.yml`, and `schema/schema.sql`. Does not touch the database.

**Important:** If the regenerated schema adds or removes columns compared to what's in the live database, the schema and database are now out of sync. The safest response is to follow up with a complete database reset (above) so the structure and data match.

```bash
# Regenerate all pipeline files from the live API
python system/rebuild_all.py

# If the schema changed, reset the database too
rm data/safehoods.db data/safehoods.db-wal data/safehoods.db-shm
python system/create_db.py
python sync/sync.py
```

To skip the live API calls and regenerate from the existing `mappings.yml` (faster, but uses cached field structure):

```bash
python system/rebuild_all.py --skip-mappings
```
