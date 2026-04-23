FROM python:3.12-slim

ENV TZ=America/Los_Angeles

RUN apt-get update \
    && apt-get install -y --no-install-recommends cron \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir requests pyyaml "mcp[cli]"

WORKDIR /app

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
