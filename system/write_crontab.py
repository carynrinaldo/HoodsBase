#!/usr/bin/env python3
"""Reads system/schedule.yml and writes /etc/cron.d/hoodsbase.

Called by entrypoint.sh at container startup. Validates the sync_time
value and generates the cron entry. Exits non-zero on bad config so the
container fails fast with a clear error message rather than silently
never running the sync.
"""
import os
import re
import sys

import yaml

SCHEDULE_PATH = "/app/system/schedule.yml"
CRON_PATH = "/etc/cron.d/hoodsbase"

with open(SCHEDULE_PATH) as f:
    config = yaml.safe_load(f)

sync_time = str(config.get("sync_time", "02:00")).strip()

if not re.match(r"^\d{1,2}:\d{2}$", sync_time):
    print(f"ERROR: Invalid sync_time in system/schedule.yml: {sync_time!r}", file=sys.stderr)
    print("Expected 24-hour format, e.g. 02:00 or 22:30", file=sys.stderr)
    sys.exit(1)

hour, minute = sync_time.split(":")

if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
    print(f"ERROR: sync_time out of range: {sync_time!r}", file=sys.stderr)
    print("Hour must be 0-23, minute must be 0-59", file=sys.stderr)
    sys.exit(1)

cron_line = (
    f"{minute} {hour} * * *"
    f"  root"
    f"  cd /app && python sync/sync.py >> /proc/1/fd/1 2>&1\n"
)

with open(CRON_PATH, "w") as f:
    f.write(cron_line)

os.chmod(CRON_PATH, 0o644)

print(f"Cron scheduled: daily at {sync_time} (America/Los_Angeles)")
