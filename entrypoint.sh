#!/bin/sh
set -e

echo "HoodsBase — starting up"

# Parse system/schedule.yml and write /etc/cron.d/hoodsbase
python3 /app/system/write_crontab.py

# Ensure the logs directory exists
mkdir -p /app/logs

echo "Cron daemon starting. Sync will run per system/schedule.yml."
echo "Pipeline log: logs/pipeline.log"

# Run cron in the foreground — this keeps the container alive
exec cron -f
