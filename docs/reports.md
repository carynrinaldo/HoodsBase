# Reports

This file documents the production reports in HoodsBase — what they're for, how to read them, and the naming conventions that organize them. Reports are SQLite views saved in the database (live, refresh on every query) with backup `.sql` files in the `reports/` folder so they survive any database rebuild.

---

## Naming conventions

| Prefix | Meaning |
|--------|---------|
| `report_` | Real, in-use production report |
| `report_qual_` | Data quality report — should typically return zero rows. If it returns rows, something needs cleanup in ServiceTrade |
| `report_zzz_` | Archived or legacy reports — kept available but deprioritized. Most are demo reports built by the original architect (Al) that demonstrate ServiceTrade query patterns but query data SafeHoods doesn't actively use (e.g. invoice/AR reports — SafeHoods invoices via QuickBooks, not ServiceTrade). They sort to the bottom of the alphabetical view list and Claude can still find/run them by description, but they shouldn't be used for actual business decisions |

When adding a new report, choose the prefix carefully — it controls both the alphabetical sort order in tools like Excel and how Claude reasons about whether to surface the report.

---

## `report_primary_hood_next_service`

**The primary production report. Rick uses this for monthly scheduling.**

### What it is

For every active location with an active Primary Main Hood service recurrence, this report returns one row showing the location, the recurrence cadence and price, the date the most recent hood-cleaning job was scheduled for, the next due date that ServiceTrade currently shows, a calculated next due date based on actual cadence math, and the drift between the two. All dates are shown date-only — no time-of-day clutter.

### How Rick uses it

Rick keeps this report open on a second screen while he works in the ServiceTrade scheduling UI on his main screen. As he plans the upcoming month's work, he uses the report to make decisions about where in the month each job should be scheduled. The calculated next due date and the day-of-month anchor help him judge how much flexibility he has to move a customer's appointment earlier or later without making them unhappy.

### Why "Primary Main Hood" (and not all services)

Every active SafeHoods location has at least one Primary Main Hood service. It is the minimum recurring service, present at every active location, and serves as the trusted anchor for "when did we last meaningfully visit this customer." Rick has multiple service types per location (filter exchange, fan maintenance, fan belt changes, etc.) but the Primary Main Hood is the one used as the schedule reference point. The report deliberately filters to one row per location, anchored on this service.

The filter `description LIKE 'PrimaryxxxxMainHoodxxxxxx%'` matches ServiceTrade's internal naming pattern for this service. The `xxxx` padding is part of how ServiceTrade groups services for sort and display purposes inside the platform — it's not garbage, it's their convention.

### Why `service_line_id = 10` (KEC)

The jobs being scheduled are specifically Kitchen Exhaust Cleaning. Other service lines (fire suppression, etc.) get cleaned on different cadences and aren't part of this report. All Primary Main Hood recurrences are on service_line_id = 10.

### Why those specific filters for "active"

A service recurrence is considered active if AND ONLY IF both of these conditions hold:

```sql
WHERE id = current_service_recurrence_id   -- not superseded by a newer record
  AND ends_on IS NULL                       -- not explicitly retired
```

ServiceTrade implements price changes (and some other material edits) by retiring the old recurrence and creating a new one with the new values. The old record gets `ends_on = today`; the new record gets a `parent` pointer back; the old record gets a `currentServiceRecurrence` pointer forward. Either filter alone misses cases — both are required. See `docs/incremental-api-plan.md` for the full discovery story.

The companion data quality report `report_qual_primary_hood_duplicates` will surface any location that breaks this assumption.

### Why `scheduled_date` (not `completed_on`)

The `last_completed_job_pacific` column is sourced from the `scheduled_date` of the most recent completed job — NOT from `completed_on`. This is a deliberate choice based on how technicians actually use ServiceTrade.

`completed_on` is the timestamp when somebody clicked "complete" in the ServiceTrade UI, which can happen days, weeks, or even months after the work was actually done. Technicians sometimes forget to mark jobs complete; admins sometimes batch-process completions. The minute-precision time of day on `completed_on` is just whenever the person was sitting at their computer pressing the button — meaningless for scheduling.

`scheduled_date` is when the job was scheduled to be done, which is much closer to the truth — and the date Rick actually wants for cadence math. The job either happened on that date or near it; what matters is that the cadence interval starts from there.

### The columns

| Column | Meaning |
|--------|---------|
| `company_name` | The customer (often the same as location name for single-site customers) |
| `location_name` | The specific physical location being serviced |
| `primary_hood_price` | The estimated price for one Primary Main Hood cleaning at this location, per the active recurrence template |
| `frequency` | The cadence unit: `weekly`, `monthly`, or `yearly` (and `daily` though it doesn't appear in practice) |
| `interval` | The number of those units between visits. So `frequency = monthly`, `interval = 3` means quarterly |
| `last_completed_job_pacific` | The scheduled date of the most recent COMPLETED job at this location. NULL means no work has ever been completed here yet — usually a brand-new customer. Date only, no time-of-day |
| `next_due_pacific` | The next due date per ServiceTrade's "Currently Due" UI field. This includes any manual edits Rick has made (including his "park it at 2030" trick for problem customers). Date only, no time-of-day |
| `calculated_next_due_pacific` | A cadence-based projection: take the scheduled date of the last completed job and add `interval × frequency`. NULL when there's no last completed job. Date only |
| `last_completed_job_day_of_month` | An integer 1–31, the day-of-month of the last completed job's scheduled date. Rick's quick anchor for "what part of the month does this customer normally get serviced?" — useful when deciding whether to schedule the next visit earlier or later in the target month |
| `next_due_vs_calc_due_days` | The drift in days between ServiceTrade's next due date and our calculated next due date: `next_due_pacific - calculated_next_due_pacific`. Positive = ServiceTrade is later than the cadence would suggest (Rick has parked it forward, or scheduling has drifted). Negative = ServiceTrade is earlier than the cadence would suggest. Large positive numbers (hundreds or thousands of days) indicate parking dates |

### Sort order

Sorted by `currently_due` ascending — most urgent at the top of the report, parking dates at the bottom.

### Known data nuances

- **Rick's "parking" practice.** For problem customers Rick doesn't want to mark inactive, he pushes the Currently Due date out to year 2030 (a few at 2035). This works fine for our reports — the parked rows naturally sort to the bottom and don't pollute near-term scheduling decisions. The `next_due_vs_calc_due_days` column will show very large positive numbers (1,000+) for these rows.
- **Locations with NULL last completed job.** A handful of active locations have no completed job in the database — usually brand new customers with the recurrence set up but no work done yet, or locations with only scheduled-but-not-yet-completed work. The `calculated_next_due_pacific`, `last_completed_job_day_of_month`, and `next_due_vs_calc_due_days` columns are NULL for these rows since there's no anchor date to project from.

---

## `report_qual_primary_hood_duplicates`

**Data quality safety net for the primary report. Should be empty.**

### What it does

Surfaces any active location that has more than one active Primary Main Hood recurrence (after applying the same filters as the main report). The main report assumes one Primary Main Hood per location — this is the safety net that catches violations.

### How to read it

Empty result → all good.

Non-empty result → the locations listed have orphaned or duplicate Primary Main Hood recurrences in ServiceTrade that need cleanup. Each row shows the recurrence IDs and prices so you can identify which one is canonical and which should be retired.

### Currently returns 0 rows.

---

## Adding new reports

The MCP server provides Claude with tools to create and drop views. The flow:

1. Use the `create_view` MCP tool with three arguments: `name` (must start with `report_`), `description` (the question or context that prompted the report — Claude reads this to decide which report answers a future question), and `sql` (a SELECT statement; do NOT include LIMIT — views must return all rows)
2. The view is immediately available in any ODBC connection (Excel, etc.)
3. A backup `.sql` file is automatically written to the `reports/` folder so the view survives database rebuilds
4. To remove a report, use the `drop_view` MCP tool — this removes the view AND deletes the backup `.sql` file

Use the appropriate prefix — `report_` for production, `report_qual_` for data quality, `report_zzz_` for archived or experimental.

If a future report should NOT be findable by Claude as a candidate when answering business questions, prepend `[ARCHIVED — do not use]` to the description so Claude skips it. (None of the current reports do this — Caryn explicitly wants the `report_zzz_` reports to remain discoverable.)
