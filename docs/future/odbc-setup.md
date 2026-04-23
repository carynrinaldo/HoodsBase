# SQLite ODBC Setup Guide

## Why ODBC?

The SafeHoods SQLite database is the single source of truth for all business data synced from ServiceTrade. ODBC (Open Database Connectivity) lets the CFO query this database directly from Excel and Access — tools he already knows — without going through Claude or any custom interface.

Combined with saved views (see [saved-views.md](saved-views.md)), this gives the CFO a self-service reporting layer on top of live business data.

## How It Works

```
Excel / Access
     |
     | ODBC (read-only)
     v
SQLite .db file (on host, bind-mounted from container)
     ^
     | writes (sync jobs, view creation)
     |
Docker Container
```

The database uses WAL (Write-Ahead Logging) mode, which allows the ODBC connection to read data while the container's sync jobs are writing — no locking conflicts.

## The Driver

**sqliteodbc** by Christian Werner is the standard open-source SQLite ODBC driver.

- Project page: http://www.ch-werner.de/sqliteodbc/
- License: BSD-style, free for commercial use
- Platforms: Windows, macOS, Linux

## Installation (Windows)

1. Download the installer from http://www.ch-werner.de/sqliteodbc/
2. **Important:** Match the driver bitness to your Office installation:
   - 64-bit Office → download the 64-bit driver (`sqliteodbc_w64.exe`)
   - 32-bit Office → download the 32-bit driver (`sqliteodbc.exe`)
   - To check: Open any Office app → File → Account → About → look for "64-bit" or "32-bit"
3. Run the installer with default settings

## DSN Configuration (Windows)

A DSN (Data Source Name) is a saved connection profile that points to your `.db` file.

1. Open **ODBC Data Source Administrator**:
   - Search Windows for "ODBC Data Sources"
   - Use the 64-bit or 32-bit version matching your driver
2. Click the **User DSN** tab → **Add**
3. Select **SQLite3 ODBC Driver** from the list → **Finish**
4. Configure the DSN:
   - **Data Source Name:** `SafeHoods`
   - **Database Name:** Browse to the `.db` file location (e.g., `C:\SafeHoods\data\safehoods.db`)
   - **Flags:** Check "Read Only" — this prevents accidental writes from Excel/Access
5. Click **OK**

## Connecting from Excel

1. Open Excel → **Data** tab → **Get Data** → **From Other Sources** → **From ODBC**
2. Select the `SafeHoods` DSN → **OK**
3. The Navigator panel shows all tables and views in the database
4. Saved report views (prefixed with `report_`) appear alongside regular tables
5. Select the table or view you want → **Load** (for direct import) or **Transform Data** (to filter/reshape in Power Query first)

To refresh data later: **Data** tab → **Refresh All**

## Connecting from Access

1. Open Access → **External Data** tab → **New Data Source** → **From Other Sources** → **ODBC Database**
2. Choose **Link to the data source by creating a linked table**
3. Select the `SafeHoods` DSN on the **Machine Data Source** tab
4. Select the tables/views to link → **OK**
5. Linked tables appear in the Access navigation pane with a globe icon
6. Build queries, forms, and reports on top of them as if they were native Access tables

## Saved Views as Reports

When Claude creates a saved view (e.g., `report_large_past_due`), it immediately appears in the ODBC table list. No reconfiguration needed — just refresh or re-link.

See [saved-views.md](saved-views.md) for details on how views are created and managed through Claude.

## Troubleshooting

| Problem | Likely cause | Fix |
|---|---|---|
| Driver not listed in ODBC Administrator | Bitness mismatch | Use the ODBC Administrator that matches the driver (32-bit or 64-bit) |
| "Database is locked" errors | WAL mode not enabled | Verify with `PRAGMA journal_mode;` — should return `wal` |
| Tables appear empty | Sync hasn't run yet | Check sync status via Claude or look at the `sync_status` table |
| View missing from table list | View was just created | Close and reopen the ODBC connection or click Refresh |
| Excel shows "architecture mismatch" | 32-bit driver with 64-bit Office (or vice versa) | Install the driver matching your Office bitness |
