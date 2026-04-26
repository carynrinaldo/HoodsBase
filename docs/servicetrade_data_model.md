# ServiceTrade Architecture (as it lives in HoodsBase)

This file documents how ServiceTrade's data model actually works — both at the architecture level and as it shows up in our synced HoodsBase database. It exists because the picture you'd build from skimming the schema is *almost* right but wrong in a few load-bearing ways, and those wrong pieces will bite anyone who builds reports without knowing them.

If you're working on a new report and something doesn't match what you expect, start here. The "Known Quirks & Gotchas" section near the end is the cheat-sheet for the failure modes that have already cost us hours of confusion.

---

## The big picture

ServiceTrade has three conceptual layers, from most stable to most ephemeral:

```
Location  ─►  Recurrence(s)  ─►  Job(s) / Service(s) / Appointment(s)
(the site)    (the policy)       (real events with the customer)
```

Everything else in the schema hangs off these. Get the layering right and the rest follows.

### Layer 1: Location (the customer's site)

A location is a physical address you service. It belongs to a company. Both have status fields (`active`, `inactive`, `on_hold`).

**A location does not directly hold any schedule.** It's just the place. The schedule lives one layer down.

### Layer 2: Recurrences (the policy / template)

Each location has one or more **recurrences**. A recurrence is a standing instruction:

> "At this location, perform this specific service on this cadence, for this price."

Each recurrence holds:
- A description with the work scope (e.g. `PrimaryxxxxMainHoodxxxxxx...`)
- A cadence (`frequency` × `interval` — "every 3 months", "every 1 year")
- A price (the current price)
- A `currently_due` date — when this specific service is next due
- A status pair (`current_service_recurrence_id` + `ends_on`) that handles retire-and-replace

**This is where the schedule lives.** The `currently_due` date you see in ServiceTrade's "Currently Due" column comes from this row, not from a job.

#### The retire-and-replace lifecycle

When you edit a recurrence's price (or other material fields), ServiceTrade does *not* update the row in place. Instead it:

1. Creates a new row with the new values
2. Sets the new row's `parent_id` to point back at the old row
3. Stamps the old row with `ends_on = today`
4. Sets both rows' `current_service_recurrence_id` to point at the new row

The "active" recurrence is the one where:

```sql
sr.id = sr.current_service_recurrence_id  -- pointing at itself = is current
AND sr.ends_on IS NULL                     -- not retired
```

Both filters are required. Either one alone misses cases. This is a pattern you'll see again — ServiceTrade really likes audit trails and tends to express "this changed" by creating new rows rather than updating existing ones.

#### The Primary / Secondary convention

Recurrence descriptions follow a naming convention:
- `Primary…` = a **schedule-driving** recurrence. It generates its own job stream on its own cadence.
- `Secondary…` = a **piggyback** recurrence. It rides along on whichever Primary's job lands on its due date.

**This convention is the most important architectural fact for reporting.** Each location has one or more Primary recurrences and zero or more Secondaries.

Two common patterns:

- **Lisa Dupar pattern (the common case):** 1 Primary + N Secondaries. The Primary's quarterly cadence creates jobs. Whatever Secondaries happen to be due on the same date come along for the ride. Some quarters it's just the Primary; some quarters multiple Secondaries align and you get a 5-service job. Underneath, every Secondary still has its own independent cadence — they just happen to be set up to align with the Primary's, which makes it *look* like one stream.

- **Salish pattern (the case that bit us hard):** 2+ Primaries with no shared anchor. Each Primary has its own independent cadence and creates its own jobs in its own months. They're not piggybacks of each other; they're parallel schedule tracks at the same location.

This is why our primary-hood report's grain is **per-Primary-recurrence**, not per-location. Lisa Dupar gets 1 row; Salish gets 2 (Main Hood + Catering Hood, each with self-consistent dates).

### Layer 3: The execution layer (jobs, services, appointments)

When the time comes to do a recurrence's work, ServiceTrade creates a job. The job is the unit of customer commitment ("we said we'd come do this"); the recurrence keeps existing as the policy.

Inside the job sit two child entities, both linked via `job_id`:

#### Services on the job (what got done)

Each work item on the job is a row in the `service_request` table. ServiceTrade calls these "service requests"; we just call them **services on the job**. When the job was created, each service was populated by **copying** fields from the relevant location-level recurrence at that moment in time — description, price, duration. Once copied, the service is **frozen**:

- If the recurrence's price changes next year, this service's stored price stays the same forever
- If the recurrence is retired/replaced, this service still points back at the version it was created from
- Nothing flows through `service_recurrence_id` after creation; it's purely a historical pointer

A service has its own status (`open`, `closed`, `canceled`) which is **independent** of the job's status. A tech can mark services closed in the field while the job sits at `scheduled` for weeks. (We currently have ~176 such cases in the database — see Known Quirks.)

#### Appointments on the job (when it happens)

An **appointment** is a time block on the dispatch board — when a tech is going to be on-site. It's a row linked via `job_id`. Appointments and services are *siblings under the job*; neither contains the other.

For SafeHoods specifically, almost every job has exactly one appointment. ServiceTrade allows multi-appointment jobs (a remodel where an electrician comes Monday and a plumber comes Wednesday) but you don't use that pattern.

**Appointment statuses you'll actually see in the data:**
- `completed` — appointment happened
- `scheduled` — booked, hasn't happened yet
- `canceled_by_vendor` — got called off

That's it. No `canceled_by_customer`, no `in_progress`, nothing else, despite what the schema enum suggests.

---

## How the layers connect

This is the part that confused us repeatedly. Three different relationships, three different uses:

### Service → Recurrence (historical pointer)

`service_request.service_recurrence_id` points at the recurrence row that was the template when this service was created. This is **how you find the history of a recurrence**: collect all services pointing back at it (or pointing at any earlier version of it via the chain), then look at their parent jobs.

**Critical:** ~46% of historical Primary services in our data point at *retired* recurrence rows, not the active one. To find the full history of a recurrence, you have to walk the retire-and-replace chain. The pattern:

```sql
-- Find all historical recurrence rows that resolve to this active recurrence
SELECT sr_any.id 
FROM service_recurrence sr_active
JOIN service_recurrence sr_any 
  ON sr_any.current_service_recurrence_id = sr_active.id
WHERE sr_active.id = <active_recurrence_id>
```

Then join services to `sr_any.id`, not just to `sr_active.id`. Without this you silently drop almost half the history.

### Job → Appointment (the date)

`job.scheduled_date` mirrors the most recent **non-canceled** appointment's `window_start`. This is the field ServiceTrade itself uses everywhere — the "Job Date" you see in the ServiceTrade UI is `j.scheduled_date`.

**For 99.3% of jobs, `j.scheduled_date` matches the most recent appointment's window_start exactly.** The 0.7% mismatch are jobs with weird histories — most often jobs whose only appointment is canceled, where the field falls through to something else (see Known Quirks).

### Job → Services (what got done on this visit)

`service_request.job_id` is the foreign key. Multiple services per job, all sharing the appointment date. For SafeHoods, all services on a job are conceptually for the same single visit (because we never have multi-day jobs).

---

## Where we used to get tangled

These are the conceptual mistakes we made and corrected. Worth bookmarking — most "wait, why doesn't this query give the right answer?" moments will trace back to one of these.

1. **Conflating services with appointments.** They are separate things. Services = work items. Appointments = time blocks. Both are children of the job, not nested in each other. A service does not "have a time"; the *appointment* does, and the service inherits it operationally because it's all on one job.

2. **Thinking the location holds the schedule.** It doesn't. The recurrence(s) at the location hold the schedule. The location is just the address. To know "when is this customer next due?", you look at the recurrence, not the location.

3. **Thinking services on a job are live-linked to the recurrence.** They're not — they're frozen copies that remember their origin. Edits to the recurrence don't propagate to existing job services. This is what produces the "old job has the old price" behavior.

4. **Assuming one Primary per location.** Lisa Dupar fits, Salish doesn't, and the data model doesn't enforce it either way. Your reports have to handle both shapes.

5. **Assuming `j.status` reflects everything that's been done.** It doesn't — services have their own status that can advance independently. "Closed service on a still-scheduled job" is a real and legitimate state in the data, and it's the cohort we currently call `pending close` on the report.

6. **Trusting `service_request.window_start` as a real date.** It's not. It's the cadence projection — when ServiceTrade originally calculated this would be due. **Never use the service's window_start for "when did/will this happen".** Always use the appointment date (or `j.scheduled_date`, which is the same thing for SafeHoods).

7. **Assuming canceled services should anchor cadence math.** They shouldn't. A canceled service didn't reset the cycle. For "most recent visit" lookups, filter out `service.status = 'canceled'` and use the most recent service that's `open` or `closed`.

---

## SafeHoods-specific operational patterns

These are things SafeHoods does in ServiceTrade that aren't universal — they're our team's conventions that the data has come to reflect over time. Worth knowing because reports designed for SafeHoods's data will assume these and break elsewhere.

### One appointment per job

Almost every job has exactly one appointment. We don't do multi-day work. The handful of multi-appointment jobs in the data are reschedule artifacts (one canceled, one completed) rather than intentional multi-visit projects.

### "Park it at 2030"

For problem customers Rick doesn't want to mark inactive but also doesn't want to schedule, he pushes the recurrence's `currently_due` out to year 2030 (occasionally 2035). This is our equivalent of "soft delete" — the row stays but sorts to the bottom of any time-ordered report. The primary-hood report calls these `parked` and styles them in gray italic.

### We invoice in QuickBooks, not ServiceTrade

ServiceTrade's invoice-related job statuses (`pending_invoice`, `sending_invoice`, `invoiced`, `closed`) are **never** populated in our data. SafeHoods uses ServiceTrade for scheduling and field operations, then invoices customers via QuickBooks separately. So jobs in our system only ever sit at `completed` after work happens — there's no further status progression on the ServiceTrade side.

This means anything you read in the schema about invoice-stage statuses is irrelevant for SafeHoods and you can ignore it.

### "Click close the job" workflow (mostly Caryn)

After work happens, Caryn:
1. Adds the comment that says the job is done
2. Attaches the customer service report
3. Sends the service report and comment to the customer via the ServiceTrade interface
4. Creates an invoice in ServiceTrade (which pushes to QuickBooks)
5. Clicks "close the job" — which appears to set `j.status = 'completed'`
6. Updates the next due date on the recurrence (Rick's preference: re-anchor to actual completion date + interval, not the cadence default)

The 176-row `pending close` cohort = jobs where step 1-4 may have happened (the *service* is `closed`) but step 5 hasn't (the *job* is still `scheduled`).

### Manually re-anchoring next due dates

When ServiceTrade auto-projects the next due date, it ignores when the previous job was actually completed and projects from the original cadence date. SafeHoods customers usually don't accept compressed gaps ("we did it on the 17th, no way are we doing the next one on the 1st") so Caryn manually updates `currently_due` to actual-completion-date + interval. The primary-hood report's `Calc Next Due Date` column is our independent cadence projection that helps Rick decide where to set the next visit; the `ST Next Due Date` shows what's actually saved in ServiceTrade.

---

## Known Quirks & Gotchas

This section exists because every one of these has cost us time at least once and will cost us time again if we don't write them down. When something looks weird in a report, check here first.

### Quirk 1: `j.scheduled_date` lies when all appointments are canceled

**What it is:** When a job has appointments and none of them are still alive (only `canceled_by_vendor`), `j.scheduled_date` doesn't fall back to a sensible default — it gets stamped with the service's `window_start`, which is the original cadence projection date, which is fictional.

**Example:** Chickadee Bakeshop's job 47157897 had one appointment (March 31, canceled), and its only Primary service got marked `canceled` too. `j.scheduled_date` reads as **April 15** — a date that doesn't appear anywhere on any real appointment. It's the cadence projection from the service.

**The fix in the v3 report:** filter out canceled services entirely when computing `Last Sched Job`. This makes Chickadee fall through to the previous closed service's date (April 29, 2025) rather than showing the fictional April 15.

**Lesson:** Trust `j.scheduled_date` only when at least one non-canceled appointment exists on the job. For all-canceled-appointments jobs, the field is unreliable.

### Quirk 2: ServiceTrade's UI splices service date with appointment time

**What it is:** When ServiceTrade displays service info in its UI, it shows the service's `window_start` *date* glued together with the appointment's *time*. So for Chickadee, the UI shows "April 15, 11:30 AM" — but April 15 came from the service's frozen cadence projection and 11:30 AM came from the canceled March 31 appointment. The combined date-time **is a moment that never existed**.

**Lesson:** Times on services are appointment times. Dates on services are cadence projections. The two are independent and combining them produces fiction. Always pull date and time from the appointment, never from the service.

### Quirk 3: 46% of historical services point at retired recurrences

**What it is:** Each price change to a recurrence retires the old row and creates a new one. Existing services keep pointing at the version they were created from. So when you query "all services for the active recurrence" by joining on `sreq.service_recurrence_id = active_recurrence.id`, you get only the slice of history since the most recent price change.

**The fix in the v3 report:** the recurrence_history_chain CTE walks via `sr_any.current_service_recurrence_id = active.id` so it picks up all historical versions of the recurrence and their associated services.

**Lesson:** When traversing recurrence history, always walk the chain. Don't just match on the active recurrence's ID.

### Quirk 4: Job-level statuses that ServiceTrade's docs claim exist but don't appear in our data

**What it is:** ServiceTrade's `job.status` enum supposedly includes values like `pending_invoice`, `sending_invoice`, `invoiced`, `closed`, `canceled`, `new`. **Across nearly a decade of SafeHoods jobs, only three values actually appear**: `completed` (4,985), `scheduled` (1,191), and `new` (1, our SafeHoods Shop repair job).

**Lesson:** Don't write report logic that branches on statuses that don't exist in our data. The `pending_invoice` etc. statuses are dead ends because we don't use ServiceTrade for invoicing. The `canceled` job status is dead because SafeHoods expresses "canceled job" by canceling all the appointments rather than setting `j.status`.

### Quirk 5: "Cancelled job" doesn't exist as a concept in our data

**What it is:** When SafeHoods cancels a job, we don't change `j.status` — we cancel the appointment(s) and don't book replacements. The job stays at `scheduled` forever. If you wanted to find "canceled jobs," you'd actually have to find jobs whose every appointment is canceled.

**In our active customers, only one such case exists in the data right now (Chickadee).** The other 8 examples we found were all at inactive locations and don't appear on reports.

### Quirk 6: Sync coverage gaps can cause silent data staleness

**What it is:** The sync pipeline's `CORE_ORDER` list in `sync/sync.py` controls which resources get pulled during a default `python sync/sync.py` (or `--full`) run. **If a resource isn't in CORE_ORDER, it silently doesn't sync** — even though it has a mapping, a context entry, and a fully working table. The only way it ever syncs is if someone explicitly runs `python sync/sync.py <that_resource>`.

**How we found this:** April 2026, `service_request` data was 48 hours stale. The headline sync log didn't mention service_request at all (because the loop never reached it), but other tables also didn't get headline log entries even though they were syncing fine. The actual ground truth was in the `sync_status` table — every working resource had a today-timestamped `last_synced_at_dt` while service_request was frozen at Friday 9:11 PM. Confirmed root cause: `servicerequest` was missing from CORE_ORDER.

**The fix:** Add `"servicerequest"` to CORE_ORDER between `"appointment"` and `"invoice"`. (See git history for the commit.)

**Lesson:** When adding a new resource to the sync, three things must happen: (1) the mapping in `schema/mappings.yml`, (2) a context entry in `schema/context.yml`, AND (3) the resource string added to `CORE_ORDER` in `sync/sync.py`. Forget any of the three and the sync silently fails to include it.

**How to detect this in the future:** Query `sync_status` periodically. Every active resource should have a `last_synced_at_dt` within the last 24 hours of any full sync. If one is stuck several days behind while others advance, it's almost certainly missing from CORE_ORDER. (We may add a `report_qual_stale_sync` view to make this monitoring automatic.)

---

## Open Questions

These are things we wondered about during the v3 work that we deferred answering. None of them are blocking; all of them are worth knowing if they bite us later.

### What triggers `currently_due` to roll forward?

**What we know:** Marking a job as completed appears to roll the recurrence's `currently_due` forward. We've also seen behavior suggesting other actions can trigger it, but we haven't pinned down what they are.

**Why it matters:** If something else moves `currently_due`, our cadence math could silently get out of sync with what ServiceTrade thinks. Worth investigating if we ever notice unexplained drift between reports and the UI.

### Should we drop `service.window_start` from the sync?

**What it is:** The service's `window_start` field is the cadence projection — never a real date. We've now established it should never be used in any report or query.

**The decision we deferred:** Whether to remove it from the sync entirely (purge from DB, modify sync code to skip it) or leave it in place but document it as Do-Not-Use.

**Argument for removing it:** Eliminates the failure mode permanently. Anyone querying the table can't accidentally use a field that doesn't exist.

**Argument for keeping it:** Touching the sync architecture is a bigger lift than we wanted. Documentation here is a reasonable substitute. ServiceTrade's API will keep returning the field whether we sync it or not, so future-you might still encounter it via direct API access.

**Current status:** Documented, not removed. Revisit if it causes problems.

---

## Quick reference: queries that get this right

When traversing recurrence history correctly:

```sql
-- All services that ever pointed at this active recurrence
-- (including those pointing at retired versions of it)
WITH recurrence_chain AS (
  SELECT sr_any.id AS historical_id
  FROM service_recurrence sr_any
  WHERE sr_any.current_service_recurrence_id = <active_id>
)
SELECT sreq.* 
FROM service_request sreq
JOIN recurrence_chain rc ON sreq.service_recurrence_id = rc.historical_id
```

When finding the "most recent visit" for a recurrence:

```sql
-- Most recent service for this recurrence, ignoring canceled ones
SELECT sreq.*, j.scheduled_date AS visit_date
FROM service_request sreq
JOIN job j ON j.id = sreq.job_id
JOIN recurrence_chain rc ON sreq.service_recurrence_id = rc.historical_id
WHERE sreq.status != 'canceled'
ORDER BY j.scheduled_date DESC
LIMIT 1
```

When finding the "last completed visit" for cadence-anchor purposes:

```sql
-- Most recent CLOSED service (work actually done in field)
SELECT MAX(j.scheduled_date) AS last_completed_ts
FROM service_request sreq
JOIN job j ON j.id = sreq.job_id
JOIN recurrence_chain rc ON sreq.service_recurrence_id = rc.historical_id
WHERE sreq.status = 'closed'
```

When checking "is this an active customer recurrence to include in reports":

```sql
WHERE sr.id = sr.current_service_recurrence_id  -- active version
  AND sr.ends_on IS NULL                         -- not retired
  AND l.status = 'active'                        -- location active
  AND c.status = 'active'                        -- customer active
```

When checking sync freshness across all resources:

```sql
SELECT resource, last_synced_at_dt, record_count
FROM sync_status
ORDER BY last_synced_at_dt
-- any resource with a noticeably older timestamp than the rest is suspect
```
