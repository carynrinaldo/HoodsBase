# Getting Started with HoodsBase

## What this is

HoodsBase is a business intelligence system for a commercial hood cleaning company called SafeHoods. It pulls operational data out of [ServiceTrade](https://servicetrade.com) (the company's field service platform) into a local database on your computer, then lets Claude AI answer business questions in plain English.

In practice, you open Claude Desktop and ask questions like:

- "Which customers are overdue for service?"
- "What's our revenue by technician this quarter?"
- "Show me all invoices over $500 that are past due"

Claude looks up the answer in the database and responds in plain English. No dashboards to build, no reports to maintain — just ask.

---

## How the pieces fit together

Before installing anything, it helps to see the big picture. HoodsBase has three main pieces, and they each do one job:

```
  ┌──────────────┐         ┌──────────────────────────────────────────┐
  │              │         │  Your Computer (Docker Container)        │
  │ ServiceTrade │ ──API──▶│                                          │
  │   (cloud)    │         │  Sync Scripts ──▶ SQLite Database        │
  │              │         │                        │                 │
  └──────────────┘         │                    MCP Server            │
                           └────────────────────────┬─────────────────┘
                                                    │
                                              MCP connection
                                                    │
                                            ┌───────▼────────┐
                                            │ Claude Desktop  │
                                            │  (on your PC)   │
                                            │                 │
                                            │  You ask a      │
                                            │  question here  │
                                            └─────────────────┘
```

**1. The sync pipeline** runs inside a Docker container on your computer. It reaches out to the ServiceTrade API on a schedule (nightly by default), pulls down business data — customers, jobs, invoices, quotes, etc. — and stores it in a local SQLite database. After the first run, it only grabs what's changed.

**2. The MCP server** also runs inside that container. MCP (Model Context Protocol) is a way for Claude to talk to outside tools and data. In this case, it's the bridge that lets Claude reach into the database, look things up, and run data syncs — all on your behalf.

**3. Claude Desktop** is the app on your computer where you actually have conversations. This is where you ask business questions and get answers.

### Claude Desktop is not the same as Claude on the web

You may already be familiar with Claude at [claude.ai](https://claude.ai) — the chat interface you use in a browser. Claude Desktop is a separate app that runs on your computer, and the key difference is that **it can connect to local tools and data**.

On the web, Claude can only work with what you paste into the conversation. Claude Desktop can reach into databases, files, and services running on your machine through MCP connections. That's what makes HoodsBase work — Claude Desktop connects to the MCP server in the Docker container, which gives it access to the full business database.

The conversations feel the same. You type questions, Claude answers. The difference is that Claude Desktop can go look things up in real data instead of just working with what you tell it.

> **Placeholder: screenshots**
> Two images would help here:
> 1. Claude on the web (claude.ai) — showing a plain conversation
> 2. Claude Desktop — showing a conversation where Claude is querying the HoodsBase database
>
> The visual contrast makes the difference immediately clear.

---

## Setting up your computer

You need to install two things before HoodsBase can run: Docker (which runs the data pipeline) and Claude Desktop (which is how you talk to it). The next two sections walk through both.

---

## Installing Docker Desktop on Windows 11

HoodsBase runs inside a **Docker container**. If that term is new to you, here's the short version: a container is like a lightweight, self-contained computer running inside your computer. It has its own operating system (Linux), its own Python installation, and all the libraries HoodsBase needs — completely isolated from everything else on your machine.

This matters for HoodsBase because:

- **You don't install Python or any dependencies on your machine.** Everything runs inside the container.
- **The sync jobs, cron schedule, and database all live inside the container.** You interact with it by sending commands in, but it manages itself.
- **It's portable.** The same container runs identically on any machine with Docker installed — no "works on my machine" problems.

Docker Desktop is the app that lets you run containers on Windows. Here's how to install it.

### Step 1: Enable WSL2

Docker Desktop on Windows runs on top of WSL2 (Windows Subsystem for Linux) — a built-in Windows feature that lets your machine run a real Linux kernel. Docker needs this to run its Linux-based containers.

1. Open **PowerShell as Administrator** (right-click the Start button → "Terminal (Admin)" or search for PowerShell → "Run as administrator")
2. Run this command:

   ```powershell
   wsl --install
   ```

3. **Restart your computer** when prompted

After the restart, WSL2 will finish setting up. It may open a window asking you to create a Linux username and password — go ahead and set those. They're just for the Linux subsystem, not your Windows account, and you probably won't need them again.

To confirm it worked, open PowerShell and run:

```powershell
wsl --version
```

You should see a version number for WSL and a Linux kernel version. If you see an error, run `wsl --update` and try again.

### Step 2: Install Docker Desktop

1. Go to [https://www.docker.com/products/docker-desktop/](https://www.docker.com/products/docker-desktop/)
2. Click **Download for Windows**
3. Run the installer (`Docker Desktop Installer.exe`)
4. During installation, make sure **"Use WSL 2 instead of Hyper-V"** is checked (it should be by default)
5. Click **OK** and let it install
6. **Restart your computer** if prompted

### Step 3: Start Docker Desktop and verify

1. Launch **Docker Desktop** from the Start menu
2. It may take a minute to start up — you'll see the Docker whale icon in your system tray when it's ready
3. Accept the license agreement if prompted
4. Open **PowerShell** (regular, not Admin) and run:

   ```powershell
   docker --version
   ```

   You should see something like `Docker version 28.x.x` — the exact number doesn't matter, just that it responds.

5. Test that containers work:

   ```powershell
   docker run hello-world
   ```

   If you see "Hello from Docker!" in the output, you're set.

### Tip: Let Docker start with Windows

Open Docker Desktop → Settings (gear icon) → General → check **"Start Docker Desktop when you sign in to Windows."** This way the container and its nightly sync will keep running whenever your computer is on.

---

## Installing Claude Desktop

Claude Desktop is an app from Anthropic (the company that makes Claude). The app itself is free to install, and you can use it with a free account, though a paid Pro subscription gives you significantly more usage. If you already use Claude on the web at claude.ai, you can use the same account.

### Step 1: Download and install

1. Go to [https://claude.ai/download](https://claude.ai/download)
2. Click **Download for Windows**
3. Run the installer and follow the prompts
4. Launch Claude Desktop from the Start menu

### Step 2: Sign in

Sign in with your Anthropic account (the same one you use at claude.ai). If you don't have one, you can create one during this step.

### Step 3: Verify it works

Once you're signed in, you should see a chat interface — similar to the web version. Try asking Claude a quick question to confirm everything is working. At this point it's just regular Claude — we'll connect it to the HoodsBase database later in the setup process.

> **Placeholder: screenshot**
> A screenshot of Claude Desktop's main chat window after sign-in would help here — so the reader knows they're in the right place.

---

## Get it running

### What you need

At this point you should have both Docker Desktop and Claude Desktop installed. You also need:

- **ServiceTrade credentials** — already included in the `.env` file inside the project folder

### Step by step

**1. Unzip and open a terminal in the project folder**

Unzip the project folder somewhere on your computer (e.g., `C:\HoodsBase`). The `.env` file with the ServiceTrade credentials is already included — you shouldn't need to change anything.

Open **PowerShell** and navigate to the project folder:

```powershell
cd C:\HoodsBase
```

All the commands below need to be run from this folder — Docker expects to find its configuration files here.

**2. Build and start the container for the first time**

```powershell
docker compose up --build -d
```

The `--build` flag tells Docker to build the image from scratch. This is only needed the first time, or if the code changes. After this initial build, you'll start the container with just:

```powershell
docker compose up -d
```

The container runs a cron job that handles the nightly sync automatically.

**3. Verify the database is working**

The database is already included in the zip file with all current data, so there's nothing to build or sync for the first run. Let's just confirm the container can see it:

Copy and paste this entire block into PowerShell — it's a single command that checks all the tables:

```powershell
docker exec hoodsbase-dev python -c "
import sqlite3
db = sqlite3.connect('data/hoodsbase.db')
for row in db.execute('SELECT resource, record_count FROM sync_status ORDER BY resource'):
    print(f'{row[0]:25s} {row[1]:>6,d}')
"
```

You should see a table of resources with record counts — companies, jobs, invoices, etc. If you see numbers, you're good. The nightly sync will keep this data up to date automatically from here on.

If you ever need to rebuild the database from scratch, see the [runbooks](docs/runbooks.md).

---

## Connect Claude Desktop to the database

Right now Claude Desktop is just regular Claude — it can't see the HoodsBase data yet. This step connects the two by registering the MCP server so Claude knows how to reach the database inside the Docker container.

### Step 1: Open the Claude Desktop config file

Claude Desktop stores its MCP server configuration in a JSON file. To open it:

1. Open **Claude Desktop**
2. Click the **hamburger menu** (☰) in the top-left corner
3. Go to **Settings** → **Developer** → **Edit Config**

This opens the file `claude_desktop_config.json` in your text editor. It may be empty or have an empty `{}` in it.

### Step 2: Add the HoodsBase MCP server

Replace the contents of the file with:

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

Save and close the file.

This tells Claude Desktop: "there's a server called `hoodsbase` — to reach it, run this command inside the Docker container." **The container must be running for this to work.**

### Step 3: Restart Claude Desktop and verify

Closing the window isn't enough — Claude Desktop keeps running in the background. You need to fully quit it:

1. Look in the **system tray** (the small icons near the clock in the bottom-right corner of your screen). You may need to click the **^** arrow to show hidden icons.
2. Find the **Claude icon**, right-click it, and choose **Quit**
3. Relaunch Claude Desktop from the Start menu
4. Start a new conversation and try asking: **"How many companies are in the database?"**

If Claude comes back with a number, the connection is working. Claude now has the full database schema in context and can run queries on your behalf.

### What Claude can do

Once connected, Claude can:

- Answer business questions by writing and running SQL queries
- Run a data sync from ServiceTrade (just ask: *"Run a sync"* or *"Sync just invoices"*)
- Check how fresh the data is (when the last sync ran)
- Create saved report views that you can name and reuse
- List and manage existing report views

There are also 19 pre-built report views (in the `reports/` directory) that were created during earlier conversations — things like revenue tracking, AR aging, and compliance reports. Ask Claude to list them.

---

## Connect Excel or Access to the database (optional)

Once the system is running, you can also connect Excel or Access directly to the SQLite database using an ODBC driver. This lets you build spreadsheets and reports on top of live data — and any saved report views that Claude creates will show up as tables you can pull into a workbook.

This is completely optional. You can do everything through Claude. But if you're more comfortable in Excel, this gives you direct access.

Full setup instructions are in [docs/future/odbc-setup.md](docs/future/odbc-setup.md) — it covers driver installation, DSN configuration, and connecting from both Excel and Access. The short version:

1. Download the SQLite ODBC driver from http://www.ch-werner.de/sqliteodbc/ — make sure you match 32-bit or 64-bit to your Office installation
2. Set up a DSN (a saved connection profile) pointing to `data/hoodsbase.db` in read-only mode
3. In Excel: **Data** → **Get Data** → **From ODBC** → select the DSN

---

## How this project works with AI

This is worth understanding because it shapes everything about how the project is built.

**HoodsBase was developed by AI and is operated by AI.** The code was written through conversations with Claude, and the end user interacts with the system through Claude. This isn't a traditional codebase with an AI bolted on — it was designed from the ground up for this workflow.

That shows up in a few key ways:

**YAML is the source of truth, not Python.** YAML is a simple text format for structured data — think of it like a settings file you can read and edit in any text editor. It uses indentation and colons to organize information, like this:

```yaml
sync_time: "02:00"        # when the nightly sync runs
resources:
  - company
  - job
  - invoice
```

The alternative would have been writing custom Python code for every API endpoint, every database table, and every field transformation — hundreds of lines of bespoke programming that only a developer could maintain. Instead, all of that lives in a handful of YAML files that describe *what* to do, and a small set of generic Python scripts figure out *how*. Adding a new API endpoint means adding a line to a YAML file and running a rebuild command, not writing new code.

**The database blueprint doubles as Claude's prompt.** The file `schema.sql` is the complete blueprint for the database — it defines every table, every column, and how they relate to each other. It's what we use to create the database from scratch. But it also serves a second purpose: when Claude connects, this same file is delivered to Claude as context so it knows exactly what data is available and how to query it. One file, two jobs. It's kept deliberately lean so it doesn't waste Claude's attention on things it doesn't need.

**The docs orient Claude, not just humans.** Every major folder has a `README.md` explaining what it does, and the `docs/` folder contains detailed documentation on architecture, operations, API authentication, and more. These aren't just for you — they're written so that Claude can read them and understand the system. The documentation is as much a part of the system as the code.

For example, say the nightly sync stops working. You could open Claude Desktop and say: *"The sync seems broken — can you check the log and tell me what's wrong?"* Claude will pull up the recent log entries through the MCP server and help you figure out the issue. If you need more help, you can open the [runbooks](docs/runbooks.md) yourself and paste the relevant section into the conversation for Claude to work through with you.

Or say you want to start pulling a new type of data from ServiceTrade. You could open the [system README](system/README.md), paste the "Adding a new endpoint" section into Claude Desktop, and say: *"Walk me through adding the technician endpoint."* Claude sees the YAML-driven pattern and guides you through editing the right config file.

**Most changes are config edits, not code changes.** Want to add a new API endpoint? Edit a YAML file and run a rebuild command. Want to change the sync schedule? Edit one line in `system/schedule.yml`. Want to adjust how a field is stored? Edit `system/api_knowledge.yml`. The Python rarely needs to change. The [runbooks](docs/runbooks.md) walk through these common tasks step by step — from everyday operations to structural changes and recovery procedures.

---

## Where things live

```
HoodsBase/
├── CLAUDE.md                 # Brief for Claude — read first when starting a conversation
├── GETTING_STARTED.md        # You are here
├── Dockerfile                # Container definition (Python 3.12)
├── docker-compose.yml        # Docker configuration
├── .env                      # ServiceTrade credentials
│
├── system/                   # Pipeline configuration and orchestration
│   ├── endpoints.yml         # Which API endpoints to sync
│   ├── api_knowledge.yml     # Human-curated field rules and business context
│   ├── schedule.yml          # Cron schedule (one line to edit)
│   ├── db_settings.yml       # Database pragmas and creation mode
│   └── rebuild_all.py        # Regenerate everything from the API
│
├── schema/                   # Generated files (don't hand-edit these)
│   ├── schema.sql            # Database blueprint — also Claude's prompt
│   ├── mappings.yml          # Auto-discovered API structure
│   ├── context.yml           # Auto-generated field transforms
│   └── generate_schema.py    # YAML → SQL generator
│
├── sync/                     # Data sync from ServiceTrade
│   └── sync.py               # Generic sync engine (YAML-driven)
│
├── mcp/                      # Claude's database interface
│   └── server.py             # MCP server (queries, sync, reports)
│
├── docs/                     # Full documentation
├── reports/                  # Pre-built SQL report views
├── data/                     # SQLite database (gitignored)
└── logs/                     # Pipeline logs (gitignored)
```

**Hand-edited files** (the ones you'd change): the YAML files in `system/`

**Generated files** (rebuilt by scripts, don't hand-edit): `schema/mappings.yml`, `schema/context.yml`, `schema/schema.sql`

**Local to your machine** (not shared): `data/` (the database), `logs/`, `.env` (credentials)

---

## Common tasks — where to look

Your first stop for most day-to-day work is the [runbooks](docs/runbooks.md). It's organized from most common to most disruptive and covers checking data freshness, running manual syncs, adding or removing endpoints, resetting resources, and recovering from errors. If you're not sure what to do, start there.

For deeper dives into specific areas, here's where to look:

| I want to...                           | Start here                                                    |
|----------------------------------------|---------------------------------------------------------------|
| Understand how the sync pipeline works | [sync/README.md](sync/README.md)                              |
| Understand how the schema is generated | [system/README.md](system/README.md)                          |
| Understand the database structure      | [schema/README.md](schema/README.md)                          |
| Understand the full architecture       | [docs/architecture.md](docs/architecture.md)                  |
| Learn about API authentication         | [docs/auth-reference.md](docs/auth-reference.md)              |
| See how the API was explored           | [docs/incremental-api-plan.md](docs/incremental-api-plan.md)  |
| Connect Excel/Access via ODBC          | [docs/future/odbc-setup.md](docs/future/odbc-setup.md)        |
| Understand saved report views          | [docs/saved-views.md](docs/saved-views.md)                    |

---

## Tips for getting good answers from Claude

Claude is powerful, but how you ask matters — especially with a database this size (~34,000 records across 18 tables). Here are some things that work well and some things to avoid.

### Ask questions, not queries

You don't need to know SQL. Just ask in plain English:

- "Which customers haven't had service in the last 6 months?"
- "What's our total revenue this quarter compared to last quarter?"
- "Show me the top 10 locations by invoice amount"

Claude knows the database structure and will write the SQL for you. If the answer doesn't look right, say so — "that doesn't look right, can you check the date range?" works great.

### Be specific about what you want

Vague questions get vague answers. Compare:

- **Vague:** "Tell me about our invoices" — Claude might pull thousands of rows trying to summarize everything
- **Specific:** "How many invoices are past due and what's the total amount?" — Claude writes a tight query that comes back fast

The more specific you are, the smaller and faster the result. This matters because every piece of data Claude retrieves counts against the conversation's token budget — think of tokens like a meter running. A focused question uses a small, cheap query. A broad question can blow through tokens returning data that isn't useful.

### Ask for summaries and counts, not raw data

This is the single biggest thing you can do to use the system effectively:

- **Good:** "How many jobs did each technician complete last month?" — Claude runs a summary query and returns a small table
- **Avoid:** "Show me all jobs from last month" — this could return hundreds or thousands of rows, each one eating tokens

Claude is instructed to prefer summaries, but if you explicitly ask for "all" of something, it will try to deliver. If you really need to see individual records, narrow it down first: "Show me all past-due invoices over $1,000" is much better than "Show me all invoices."

### Build up, don't dump

If you're exploring a topic, start narrow and widen:

1. "How many overdue invoices do we have?" *(a single number)*
2. "Break that down by customer" *(a summary table)*
3. "Show me the details for ABC Restaurant" *(a handful of rows)*

Each step gives you context to ask a better next question. This is much more effective (and cheaper) than starting with "Show me everything about overdue invoices."

### Save reports you'll reuse

If you find yourself asking the same question regularly, ask Claude to save it as a report: *"Save that as the monthly revenue report."* Claude creates a named view in the database that you can pull into Excel anytime, without using Claude or tokens at all. There are already 19 saved reports from earlier work — ask Claude to list them.

### Things to avoid

- **"Show me all records from [table]"** — some tables have thousands of rows. Ask for a count or summary first.
- **Asking the same question in a fresh conversation** — Claude doesn't remember previous conversations. If it's a question you'll repeat, save it as a report.
- **Very long conversations** — after many back-and-forth exchanges, the conversation history itself starts using up tokens. If things slow down or Claude seems to lose track, start a fresh conversation.

### If something goes wrong

- If Claude says it can't connect to the database, make sure Docker Desktop is running (check for the whale icon in your system tray) and that the container is started. Open PowerShell, navigate to the project folder, and run `docker compose up -d`.
- If the data seems stale, ask Claude: *"When was the last sync?"* — it can check directly. You can also just say *"Run a sync"* and Claude will pull fresh data from ServiceTrade right there in the conversation.
- If Claude gives an error about a query, try rephrasing your question. You can also say *"What tables do you have access to?"* to remind yourself what data is available.

---

## What's next

The `docs/future/` directory contains design notes for features that haven't been built yet. The [incremental-api-plan.md](docs/incremental-api-plan.md) documents how the API was explored endpoint-by-endpoint — useful context if you want to pull in additional data.

For day-to-day operations, the [runbooks](docs/runbooks.md) cover everything from checking sync status to full database rebuilds.
