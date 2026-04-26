# Reports

This file documents the production reports in HoodsBase — what they're for, how to read them, and the naming conventions that organize them.

For background on how ServiceTrade's data model works (jobs vs services vs appointments vs recurrences, and the SafeHoods-specific patterns like Salish, Lisa Dupar, Chickadee), see **servicetrade_data_model.md**. This file assumes that knowledge.

Reports are SQLite views saved in the database (live, refresh on every query) with backup `.sql` files in the `reports/` folder so they survive any database rebuild.

---

## Naming conventions

| Prefix | Meaning |
|--------|---------|
| `report_` | Real, in-use production report |
| `report_qual_` | Data quality report — should typically return zero rows. If it returns rows, something needs cleanup in ServiceTrade or in the sync infrastructure |
| `report_zzz_` | Archived or legacy reports — kept available but deprioritized. Most are demo reports built by the original architect (Al) that demonstrate ServiceTrade query patterns but query data SafeHoods doesn't actively use (e.g. invoice/AR reports — SafeHoods invoices via QuickBooks, not ServiceTrade). They sort to the bottom of the alphabetical view list and Claude can still find/run them by description, but they shouldn't be used for actual business decisions |

When adding a new report, choose the prefix carefully — it controls both the alphabetical sort order in tools like Excel and how Claude reasons about whether to surface the report.

---

## `report_primary_hood_next_service_v3`

**The primary production report. Rick uses this for monthly scheduling.**

This is v3 of the report. v1 (`report_primary_hood_next_service`) and v2 (`report_primary_hood_next_service_v2`) still exist in the database but are superseded — keep using v3.

### What it is

For every active Primary recurrence at every active location, this report returns one row showing the recurrence's cadence and price, the last completed visit date, the last scheduled visit date (any status), the next due date that ServiceTrade currently shows, a calculated next due date based on actual cadence math, and a derived row status that classifies the row's lifecycle position.

Unlike v1, the grain is **per Primary recurrence, not per location**. A location like Salish Lodge & Spa with two independent Primary tracks (Main Hood + Catering Hood on different cadences) gets two rows on the report, each with self-consistent dates. See servicetrade_data_model.md for the Salish vs. Lisa Dupar distinction.

### How Rick uses it

Rick keeps this report open on a second screen while he works in the ServiceTrade scheduling UI on his main screen. As he plans the upcoming month's work, he uses the report to make decisions about where in the month each job should be scheduled.

The Row Status column tells him at a glance which rows need his attention vs. which are already handled. Rows in `closed` status are the "ready to schedule the next visit" cohort — that's the primary working set. Other statuses surface specific situations needing different actions (more on each below).

The Calc Next Due Date and the drift column help him judge how much flexibility he has to move a customer's appointment earlier or later than ServiceTrade's auto-calculated next due, without making the customer unhappy.

### Why filter to "Primary"

Every active SafeHoods location has at least one Primary recurrence. It is the schedule-driving service — the cadence anchor. Secondary services piggyback on the Primary's job dates rather than driving their own schedules.

The filter `description LIKE 'Primary%'` matches all Primary recurrence types (Main Hood, Catering Hood, etc.) — not just Main Hood. This was a v1 → v2 change motivated by Salish Lodge, which has both Main and Catering as Primaries.

### Why `service_line_id = 10` (KEC)

The jobs being scheduled are specifically Kitchen Exhaust Cleaning. Other service lines (fire suppression, etc.) get cleaned on different cadences and aren't part of this report. All Primary recurrences worth scheduling on this report are on `service_line_id = 10`.

### Why those specific filters for "active"

A service recurrence is considered active if **and only if** both of these conditions hold:

```sql
WHERE id = current_service_recurrence_id   -- not superseded by a newer record
  AND ends_on IS NULL                       -- not explicitly retired
```

ServiceTrade implements price changes and other material edits via retire-and-replace (see servicetrade_data_model.md). Either filter alone misses cases — both are required.

The companion data quality report `report_qual_primary_hood_duplicates` will surface any location that breaks this assumption.

### How history lookups work

A naive query like "most recent service for this recurrence" via `service_request.service_recurrence_id = active_recurrence.id` will silently miss roughly 46% of historical visits, because services point at *whichever recurrence version was active when the service was created* — and most pre-existing services point at retired versions.

The v3 report walks the recurrence history chain via `current_service_recurrence_id` to pick up all historical versions and their services. See servicetrade_data_model.md for the SQL pattern.

### How canceled services are handled

Canceled services are filtered out entirely from the "most recent" lookup. They don't anchor anything. A recurrence whose most recent service is canceled but has a prior closed visit will be classified by the prior closed visit, not by the cancellation. The Row Status Reason adds a soft flag — *"(a more recent attempt was cancelled)"* — so Rick still sees that something happened, without putting the row in a special bucket.

This handles the Chickadee Bakeshop case described in servicetrade_data_model.md (Quirk 1 + Quirk 5).

### The columns

| Column | Meaning |
|--------|---------|
| `Company Name` | The customer (often the same as location name for single-site customers) |
| `Location Name` | The specific physical location being serviced |
| `Primary Type` | The hood-type extracted from the recurrence description ("MainHood", "CateringHood", etc.) — disambiguates Salish's two rows |
| `Primary Price` | The estimated price for one Primary cleaning at this location, per the active recurrence template |
| `Frequency` | The cadence unit: `weekly`, `monthly`, or `yearly` (and `daily` though it doesn't appear in practice) |
| `Interval` | The number of those units between visits. So `frequency = monthly`, `interval = 3` means quarterly |
| `Last Compl Job` | Date of the most recent **closed** Primary service for this recurrence. NULL means no work has ever been completed here yet — usually a brand-new customer |
| `Last Sched Job` | Date of the most recent **non-canceled** Primary service for this recurrence (closed or open). For most rows this is the same as Last Compl Job. When there's a future visit booked, it's that future date. When the most recent visit was canceled, it falls through to the prior closed visit's date |
| `ST Next Due Date` | The next due date per ServiceTrade's `currently_due` field. Includes any manual edits Rick has made (including his "park it at 2030" trick) |
| `Calc Next Due Date` | Cadence-based projection: take `Last Sched Job` if present (or `Last Compl Job` if not, or `ST Next Due Date` if neither) and add `interval × frequency`. **Important:** the formula uses Last Sched Job as the anchor when it exists, because that's the operationally relevant "when does the next cycle start" date |
| `ST vs Calc Next Due Days Diff` | The drift in days: `ST Next Due Date - Calc Next Due Date`. Positive = ServiceTrade is later than the cadence would suggest. Negative = ServiceTrade is earlier. Large positive numbers (1,000+) indicate parked dates |
| `Last Compl Job DOM` | Day-of-month integer (1–31) extracted from `Last Compl Job`. Rick's quick anchor for "what part of the month does this customer normally get serviced?" — useful when deciding whether to schedule the next visit earlier or later in the target month |
| `Row Status` | Derived classification: `closed`, `pending close`, `pending close *`, `scheduled`, `field incompletion`, `new (unscheduled)`, `new (scheduled)`, or `parked`. See "Row Status values" below |
| `Row Status Reason` | Plain-language explanation of how Row Status was derived. Safe to hide if Rick doesn't want to see it; useful during the rollout to verify the logic |

### Row Status values

| Value | Meaning | Color in Excel |
|-------|---------|---------|
| `closed` | Last visit fully closed (service `closed`, job `completed`). Awaiting release of next job | (no fill) |
| `pending close` | Service marked closed in field, job not yet marked completed in office. Recent (≤7 days). Just needs paperwork wrap-up | yellow |
| `pending close *` | Same as `pending close` but >7 days old. Slipped — should be closed by now | yellow |
| `scheduled` | Future job already booked, primary service still open | (no fill) |
| `field incompletion` | Past job's primary service still marked open. Tech didn't mark closed in the field | orange |
| `new (unscheduled)` | No job history, no future job booked. Brand-new customer needing first job released | green |
| `new (scheduled)` | No job history, but first job already on the books. Will resolve once the visit happens | (no fill) |
| `parked` | `ST Next Due Date` is more than 18 months out (Rick's "park it at 2030" trick) | gray italic |

When the most recent service was canceled but a prior closed one exists, Row Status is `closed` and Row Status Reason ends with *"(a more recent attempt was cancelled)"*. This handles the Chickadee case.

### Sort order

Sorted by Calc Next Due Date ascending, **NULLs first**. Most-urgent rows float to top. Rows with NULL calc dates would appear at the very top — currently no rows have this state, but the sort treats them as highest-priority defensively.

### Known data nuances

- **Rick's "parking" practice.** For problem customers Rick doesn't want to mark inactive, he pushes the recurrence's `currently_due` out to year 2030 (a few at 2035). This works fine for our reports — the parked rows get classified as `parked` and styled in gray italic. The `ST vs Calc Next Due Days Diff` column will show very large positive numbers (1,000+) for these rows.
- **Locations with NULL Last Compl Job.** A handful of active locations have no completed Primary service in the database — usually brand new customers. They'll be classified as `new (unscheduled)` if there's no future job either, or `new (scheduled)` if a first job is already on the books. The Calc Next Due Date passes through ST Next Due Date in the unscheduled case so Rick's filters always see a value.
- **Multi-Primary locations.** Currently only Salish Lodge & Spa has multiple active Primaries. It appears as 2 rows. If more such locations get set up, they'll automatically get the same multi-row treatment — no report changes needed.

---

## `report_qual_primary_hood_duplicates`

**Data quality safety net for the primary report. Should be empty.**

### What it does

Surfaces any active location that has more than one active recurrence with the *same Primary description* (after applying the same active filters as the main report). The main report does NOT assume one Primary per location anymore (Salish breaks that assumption); it assumes each Primary is uniquely-described per location.

**Note:** This report's scoping pre-dates the Salish discovery — its current SQL still filters on `'PrimaryxxxxMainHoodxxxxxx%'` and looks for "more than one Primary Main Hood at one location," which is a more specific failure mode than the broader "more than one of any Primary type at one location" check the v3 design ideally wants. **TODO:** broaden this check to flag duplicates of any Primary description, so a location that accidentally has two `Primary Main Hood` recurrences (a real cleanup case) AND a location that accidentally has two `Primary Catering Hood` recurrences both get caught.

### How to read it

Empty result → all good.

Non-empty result → the locations listed have orphaned or duplicate Primary recurrences in ServiceTrade that need cleanup. Each row shows the recurrence IDs and prices so you can identify which one is canonical and which should be retired.

### Currently returns 0 rows.

---

## How to use the v3 report (the workflow)

The v3 report has companion tooling that turns it into a formatted Excel file Rick can use:

1. The v3 view lives in the database (refreshes on every query)
2. A Python script (`build_v3_xlsx.py`) on Caryn's laptop runs `docker exec` against `hoodsbase-dev`, dumps the view, and writes a formatted .xlsx with conditional formatting, frozen header, filters, etc.
3. The script saves the .xlsx in the directory it's run from, with a timestamped filename

To generate a fresh report:

```
cd %USERPROFILE%\Downloads
python build_v3_xlsx.py
```

The script connects to the live database every time, so any changes to the underlying data (or to the v3 view's SQL) flow through automatically — no script edits needed.

The script lives in Caryn's Downloads folder. To update its formatting (colors, column widths, etc.), edit the script directly. To update the report's logic, edit the v3 view's SQL.

---

## Adding new reports

The MCP server provides Claude with tools to create and drop views. The flow:

1. Use the `create_view` MCP tool with three arguments: `name` (must start with `report_`), `description` (the question or context that prompted the report — Claude reads this to decide which report answers a future question), and `sql` (a SELECT statement; do NOT include LIMIT — views must return all rows)
2. The view is immediately available in any ODBC connection (Excel, etc.)
3. A backup `.sql` file is automatically written to the `reports/` folder so the view survives database rebuilds
4. To remove a report, use the `drop_view` MCP tool — this removes the view AND deletes the backup `.sql` file

Use the appropriate prefix — `report_` for production, `report_qual_` for data quality, `report_zzz_` for archived or experimental.

If a future report should NOT be findable by Claude as a candidate when answering business questions, prepend `[ARCHIVED — do not use]` to the description so Claude skips it. (None of the current reports do this — Caryn explicitly wants the `report_zzz_` reports to remain discoverable.)

---

## When something looks weird

If a row on the report doesn't match what you expect, work through this checklist before assuming the report is wrong:

**1. Is the data fresh?** Check `sync_status` to see if any tables haven't synced recently:

```sql
SELECT resource, last_synced_at_dt, record_count
FROM sync_status
ORDER BY last_synced_at_dt
```

Any resource whose `last_synced_at_dt` is noticeably older than the rest is suspect — it may have fallen out of the sync pipeline (see servicetrade_data_model.md Quirk 6). Recent example: April 2026, `service_request` was 48 hours stale because it was missing from `CORE_ORDER` in `sync/sync.py`.

**2. Is it a known ServiceTrade quirk?** Most surprises trace back to one of servicetrade_data_model.md's documented quirks:

- A canceled appointment with a misleading `j.scheduled_date` (Quirk 1)
- ServiceTrade's UI splicing dates from one place and times from another (Quirk 2)
- Services pointing at retired recurrence versions (Quirk 3)
- An assumption that a status exists in the data when it doesn't (Quirk 4)
- A "canceled job" that's expressed via canceled appointments, not job status (Quirk 5)
- Sync coverage gap, as just mentioned (Quirk 6)

**3. Is it a new quirk?** If it's none of the above, surface it — it might be a new pattern worth documenting in servicetrade_data_model.md.
