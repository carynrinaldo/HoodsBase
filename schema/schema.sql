-- ServiceTrade hood cleaning business — SQLite schema
-- Conventions:
--   _id suffix = FK to that table's id
--   INTEGER timestamps have _dt TEXT companions (ISO 8601 Pacific, e.g. created_at_dt)
--   TEXT columns for arrays/objects contain JSON
--   INTEGER booleans: 0=false, 1=true

-- Trade categories (e.g. Kitchen Exhaust Cleaning, Pressure Washing, Grease Containment). Each job and service recurrence is tied to a service line.
CREATE TABLE service_line (
  id INTEGER PRIMARY KEY,
  name TEXT,
  trade TEXT,  -- e.g. "Exhaust Cleaning", "Pressure Washing"
  abbr TEXT,  -- short code e.g. KEC, GC, PRWSH
  icon_url TEXT
);

-- Freeform labels for segmenting companies, locations, jobs, invoices.
CREATE TABLE tag (
  id INTEGER PRIMARY KEY,
  name TEXT
);

-- Payment terms (e.g. Due Upon Receipt, Net 7, Net 30).
CREATE TABLE payment_terms (
  id INTEGER PRIMARY KEY,
  name TEXT,
  order_index INTEGER
);

-- Customer or vendor business. Most are customers (is_customer=1). Some are vendors or prime contractors.
CREATE TABLE company (
  id INTEGER PRIMARY KEY,
  name TEXT,
  status TEXT,  -- active|pending|inactive|on_hold
  ref_number TEXT,
  is_customer INTEGER,
  is_vendor INTEGER,
  is_parts_vendor INTEGER,
  is_prime_contractor INTEGER,
  address_street TEXT,
  address_city TEXT,
  address_state TEXT,
  address_postal TEXT,
  phone TEXT,
  default_brand_id INTEGER,
  created_at INTEGER,
  updated_at INTEGER,
  external_ids TEXT
);

-- Physical service address under a company. Hood cleaning is performed at the location level.
CREATE TABLE location (
  id INTEGER PRIMARY KEY,
  name TEXT,
  ref_number TEXT,
  legacy_id INTEGER,
  lat REAL,
  lon REAL,
  phone TEXT,
  email TEXT,
  primary_contact_id INTEGER,
  address_street TEXT,
  address_city TEXT,
  address_state TEXT,
  address_postal TEXT,
  taxable INTEGER,
  status TEXT,  -- active|inactive|pending
  tax_group_id INTEGER,
  geocode_quality INTEGER,
  general_manager TEXT,  -- name text, not a FK
  created_at INTEGER,
  updated_at INTEGER,
  store_number TEXT,  -- deprecated, use ref_number
  company_id INTEGER,
  brand_id INTEGER,
  remit_to_source TEXT,
  external_ids TEXT
);

-- Person associated with companies and/or locations. Can be linked to multiple.
CREATE TABLE contact (
  id INTEGER PRIMARY KEY,
  first_name TEXT,
  last_name TEXT,
  phone TEXT,
  mobile TEXT,
  alternate_phone TEXT,
  email TEXT,
  types TEXT,  -- JSON array e.g. management, sales, Invoice/Report
  status TEXT,  -- public|private|inactive
  created_at INTEGER,
  updated_at INTEGER,
  external_ids TEXT
);

-- Work order — the central entity. Tied to customer, location, vendor. API defaults to status=scheduled unless another status is specified.
CREATE TABLE job (
  id INTEGER PRIMARY KEY,
  name TEXT,
  custom_name TEXT,
  type TEXT,  -- cleaning|inspection|repair|construction|upgrade|etc
  job_type_weight INTEGER,  -- higher = higher importance
  status TEXT,  -- new|scheduled|canceled|bidding|completed|pending_invoice|sending_invoice|invoiced|closed
  display_status TEXT,
  substatus TEXT,  -- pending_approval|po_hold|construction_hold|awaiting_parts|rework_required|needs_review_sales|needs_review_ops|sales_approved|ops_approved|null
  visibility TEXT,
  section_visibilities TEXT,
  number INTEGER,
  ref_number TEXT,
  customer_po TEXT,
  description TEXT,
  scheduled_date INTEGER,  -- most recent open appointment
  latest_clock_in INTEGER,
  ivr_open INTEGER,  -- 1 if last IVR event was clock-in
  ivr_activity TEXT,  -- onsite|offsite|enroute|null
  service_line TEXT,  -- DEPRECATED text abbr, not a FK
  estimated_price REAL,  -- sum of non-canceled service requests
  due_by INTEGER,
  due_after INTEGER,
  completed_on INTEGER,
  vendor_id INTEGER,
  customer_id INTEGER,
  location_id INTEGER,
  owner_id INTEGER,
  sales_id INTEGER,
  primary_contact_id INTEGER,
  assigned_office_id INTEGER,
  created_at INTEGER,
  updated_at INTEGER,
  percent_complete INTEGER,
  is_project INTEGER,
  service_link_attachment_visibility INTEGER,
  service_link_comment_visibility INTEGER,
  service_link_attachment_category_visibility TEXT,
  budgeted INTEGER,
  current_appointment_id INTEGER,
  external_ids TEXT,
  terms_id INTEGER,
  contract_id INTEGER,
  project_id INTEGER
);

-- Scheduled time block on a job — dispatch board entry. Jobs can have multiple appointments.
CREATE TABLE appointment (
  id INTEGER PRIMARY KEY,
  name TEXT,
  status TEXT,  -- scheduled|unscheduled|canceled_by_vendor|canceled_by_customer|completed|no_show
  window_start INTEGER,
  window_end INTEGER,
  location_id INTEGER,
  vendor_id INTEGER,
  job_id INTEGER,
  due_by INTEGER,
  released INTEGER,
  created_at INTEGER,
  updated_at INTEGER
);

-- Bill sent to customer. Line items extracted into invoice_item table.
CREATE TABLE invoice (
  id INTEGER PRIMARY KEY,
  name TEXT,
  type TEXT,  -- invoice|vendorbill|external|unknown
  status TEXT,  -- ok|internal_review|pending_accounting|processed|paid|sent|failed|void
  substatus TEXT,  -- pending|review_needed|needs_review_sales|rejected|sales_approved|approved|null
  invoice_number TEXT,
  ref_number TEXT,
  tax_amount REAL,
  subtotal REAL,
  total_price REAL,
  total_paid_amount REAL,
  location_id INTEGER,
  job_id INTEGER,
  visibility TEXT,
  assigned_user_id INTEGER,
  customer_id INTEGER,
  vendor_id INTEGER,
  customer_po TEXT,
  notes TEXT,
  partial INTEGER,
  is_paid INTEGER,
  is_sent INTEGER,
  transaction_date INTEGER,
  contract_id INTEGER,
  assigned_office_id INTEGER,
  payment_terms_id INTEGER,
  due_date INTEGER,
  created_at INTEGER,
  updated_at INTEGER
);

-- Line item on an invoice. Extracted from parent invoice response during sync.
CREATE TABLE invoice_item (
  invoice_id INTEGER,
  id INTEGER PRIMARY KEY,
  description TEXT,
  quantity REAL,
  price REAL,
  subtotal REAL,
  tax_group_id INTEGER,
  tax_rate REAL,
  tax_rate_details TEXT,
  tax_amount REAL,
  total_price REAL,
  order_index INTEGER,
  lib_item_id INTEGER,
  service_line_id INTEGER,
  job_item_id INTEGER,
  service_request_id INTEGER,
  created_at INTEGER,
  updated_at INTEGER
);

-- Proposal for planned work. Lifecycle: draft→submitted→accepted/rejected. Line items extracted into quote_item table.
CREATE TABLE quote (
  id INTEGER PRIMARY KEY,
  name TEXT,
  ref_number TEXT,
  status TEXT,  -- accepted|canceled|draft|new|rejected|submitted
  notes TEXT,
  customer_id INTEGER,
  vendor_id INTEGER,
  location_id INTEGER,
  deficiency_severity TEXT,  -- suggested|deficient|inoperable|null
  deficiency_jobs TEXT,
  respond_by INTEGER,
  expires_on INTEGER,
  latest_submission INTEGER,
  latest_accepted INTEGER,
  created_at INTEGER,
  updated_at INTEGER,
  subtotal REAL,  -- API returns formatted string, stored as real
  tax_amount REAL,
  total_price REAL,
  quote_request_id INTEGER,
  contract_id INTEGER,
  assigned_to_id INTEGER,
  owner_id INTEGER,
  sales_id INTEGER,
  substatus TEXT,  -- customer_hold|needs_review_ops|needs_review_sales|negotiation|on_hold|ops_approved|ready_to_sent|requote|sales_approved|null
  visibility TEXT,
  customer_po TEXT,
  customer_po_required INTEGER,
  terms_id INTEGER,
  assigned_office_id INTEGER,
  description TEXT,
  job_type TEXT,  -- cleaning|inspection|repair|etc
  tasking_detail_level TEXT,
  quote_link_attachment_visibility INTEGER,
  quote_link_comment_visibility INTEGER,
  section_visibilities TEXT,
  external_ids TEXT
);

-- Line item on a quote. Full detail via /quote/{id}/item endpoint.
CREATE TABLE quote_item (
  quote_id INTEGER,
  id INTEGER PRIMARY KEY,
  description TEXT,
  lib_item_id INTEGER,
  service_line_id INTEGER,
  service_request_id INTEGER,
  price REAL,
  quantity REAL,
  tax_rate REAL,
  tax_rate_details TEXT,
  cost REAL,  -- internal cost, not shown to customer
  visibility TEXT
);

-- Equipment at a location — hoods, fans, filters. Hierarchical: location→building→system→hood. Requires updatedAfter filter param.
CREATE TABLE asset (
  id INTEGER PRIMARY KEY,
  type TEXT,  -- location|kitchen_exhaust_hood|kitchen_exhaust_system|etc
  name TEXT,
  location_id INTEGER,
  service_line_id INTEGER,
  legacy_id INTEGER,
  status TEXT,  -- active|inactive
  display TEXT,  -- human-readable type name
  properties TEXT,  -- flexible JSON — hood dimensions, filter sizes, fan specs
  parent_id INTEGER,
  created_at INTEGER,
  updated_at INTEGER,
  order_index INTEGER,
  asset_definition_id INTEGER,
  is_abstract_group INTEGER,  -- grouping node, not a real asset
  has_active_task_list INTEGER,
  external_ids TEXT
);

-- Compliance issue found during service. Reported against assets with severity levels. Lifecycle: new→verified/fixed/rejected.
CREATE TABLE deficiency (
  id INTEGER PRIMARY KEY,
  ref_number TEXT,
  reported_on INTEGER,
  severity TEXT,  -- suggested|deficient|inoperable
  title TEXT,
  status TEXT,  -- new|invalid|verified|fixed
  last_reported_status TEXT,
  resolution TEXT,  -- new|invalid|fixed|out_for_quote|notified|rejected
  report_source TEXT,  -- manual|lsn|ivr|mobile|jcw
  description TEXT,
  proposed_fix TEXT,
  owner_id INTEGER,
  sales_id INTEGER,
  reporter_id INTEGER,
  asset_id INTEGER,
  location_id INTEGER,
  service_line_id INTEGER,
  job_id INTEGER,
  visibility TEXT,
  created_at INTEGER,
  updated_at INTEGER,
  external_ids TEXT
);

-- Recurring service schedule — critical for compliance. Defines how often a location/asset needs service. frequency+interval = "every [interval] [frequency]s" e.g. interval=3, frequency=monthly means quarterly. The `currently_due` and `current_service_recurrence_id` columns are populated via the `serviceRecurrence.nextDueService` sideload (see system/endpoints.yml). When a user manually edits the "Currently Due" date in the ServiceTrade UI, ServiceTrade creates a NEW recurrence record with the new date and links the old one via `current_service_recurrence_id`. The active recurrence for any location is the one where `id = current_service_recurrence_id`.
CREATE TABLE service_recurrence (
  id INTEGER PRIMARY KEY,
  description TEXT,
  service_line_id INTEGER,
  asset_id INTEGER,
  location_id INTEGER,
  first_start INTEGER,
  first_end INTEGER,
  frequency TEXT,  -- daily|weekly|monthly|yearly|null(task_list)
  interval INTEGER,  -- every [interval] [frequency]s
  frequency_category TEXT,  -- for task_list only: monthly|quarterly|semi-annually|annually|multi-year
  scheduling_type TEXT,  -- default|task_list
  repeat_weekday INTEGER,  -- monthly only: tied to specific weekday
  ends_on INTEGER,
  parent_id INTEGER,  -- old recurrence when schedule modified
  contract_id INTEGER,
  preferred_vendor_id INTEGER,
  estimated_price REAL,
  duration INTEGER,  -- seconds
  preferred_start_time INTEGER,  -- seconds from midnight
  created_at INTEGER,
  updated_at INTEGER,
  currently_due INTEGER,  -- next due date from ServiceTrade UI; matches Currently Due column
  current_service_recurrence_id INTEGER  -- FK to currently active recurrence; equals id when this row is the active one
);

-- Job-level service request — a specific item of work to be done (e.g. "Kitchen exhaust hood cleaning"). Derived from service recurrences, referenced by invoice_item and quote_item via service_request_id. Distinct from service_recurrence (location template) and invoice_item (billing line).
CREATE TABLE service_request (
  id INTEGER PRIMARY KEY,
  status TEXT,
  description TEXT,  -- e.g. "Kitchen exhaust hood cleaning"
  service_line_id INTEGER,
  asset_id INTEGER,
  location_id INTEGER,
  job_id INTEGER,
  deficiency_id INTEGER,
  change_order_id INTEGER,
  budget_id INTEGER,
  contract_id INTEGER,
  window_start INTEGER,
  window_end INTEGER,
  closed_on INTEGER,
  created_at INTEGER,
  updated_at INTEGER,
  service_recurrence_id INTEGER,
  preferred_vendor_id INTEGER,
  estimated_price REAL,
  duration INTEGER,  -- seconds
  preferred_start_time INTEGER,  -- seconds from midnight
  visibility TEXT,
  original_window_start INTEGER,
  original_window_end INTEGER,
  service_link_attachment_visibility INTEGER,
  service_link_comment_visibility INTEGER,
  quote_link_attachment_visibility INTEGER,
  quote_link_comment_visibility INTEGER,
  service_link_attachment_category_visibility TEXT
);

-- ServiceTrade user — technicians, office staff, salespeople.
CREATE TABLE user (
  id INTEGER PRIMARY KEY,
  name TEXT,
  status TEXT,  -- active|inactive
  email TEXT,
  is_tech INTEGER,
  is_helper INTEGER,
  first_name TEXT,
  last_name TEXT,
  username TEXT,
  phone TEXT,
  timezone TEXT,
  is_sales INTEGER,
  company_id INTEGER,
  location_id INTEGER,
  manager_id INTEGER,
  details TEXT,
  activities TEXT,
  mfa_required INTEGER,
  created_at INTEGER,
  updated_at INTEGER,
  external_ids TEXT
);


-- Tracks last successful sync per resource. Used for incremental sync.
CREATE TABLE sync_status (
  resource TEXT PRIMARY KEY,
  last_synced_at INTEGER,
  last_synced_at_dt TEXT,
  last_run_at INTEGER,
  last_run_at_dt TEXT,
  record_count INTEGER DEFAULT 0
);

-- Historical log of every sync run.
CREATE TABLE sync_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  resource TEXT,
  started_at INTEGER,
  started_at_dt TEXT,
  finished_at INTEGER,
  finished_at_dt TEXT,
  status TEXT, -- success|partial|failed
  records_fetched INTEGER DEFAULT 0,
  records_upserted INTEGER DEFAULT 0,
  error_message TEXT
);
