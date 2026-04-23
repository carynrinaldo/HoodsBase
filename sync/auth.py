"""Authenticate against the ServiceTrade API using session auth.

Reuses a saved session token if one exists and is still valid.
Otherwise logs in fresh and saves the new token to .session_token.
"""

import os
import json
import sys
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logging_config import get_logger

logger = get_logger(__name__)

BASE_URL = "https://api.servicetrade.com/api"
TOKEN_FILE = "/app/.session_token"

session = requests.Session()

# --- Try existing token first ---
token = None
if os.path.exists(TOKEN_FILE):
    try:
        token = open(TOKEN_FILE).read().strip()
    except OSError as e:
        logger.error(f"Failed to read token file {TOKEN_FILE}: {e}")
        token = None

    if token:
        session.cookies.set("PHPSESSID", token)
        logger.info("Found saved token, checking if still valid...")
        try:
            check = session.get(f"{BASE_URL}/auth")
            logger.info(f"GET /api/auth -> {check.status_code}")
            if check.status_code == 200:
                logger.info("Session is valid. No login needed.")
                print(json.dumps(check.json(), indent=2))
                raise SystemExit(0)
            else:
                logger.info("Saved token expired. Logging in fresh...")
                session.cookies.clear()
        except requests.RequestException as e:
            logger.error(f"Network error checking session: {e}")
            raise SystemExit(1)

# --- Log in with credentials ---
username = os.environ["SERVICETRADE_USERNAME"]
password = os.environ["SERVICETRADE_PASSWORD"]

logger.info("Logging in...")
try:
    resp = session.post(f"{BASE_URL}/auth", json={"username": username, "password": password})
except requests.RequestException as e:
    logger.error(f"Network error during login: {e}")
    raise SystemExit(1)

logger.info(f"POST /api/auth -> {resp.status_code}")

if resp.status_code != 200:
    logger.error(f"Auth failed (HTTP {resp.status_code})")
    raise SystemExit(1)

data = resp.json()
print(json.dumps(data, indent=2))

auth_token = data.get("data", {}).get("authToken")
logger.info(f"authToken received: {'yes' if auth_token else 'NO (missing!)'}")

# --- Save token ---
try:
    with open(TOKEN_FILE, "w") as f:
        f.write(auth_token)
    logger.info(f"Token saved to {TOKEN_FILE}")
except OSError as e:
    logger.error(f"Failed to save token to {TOKEN_FILE}: {e}")
    raise SystemExit(1)

# --- Verify ---
logger.info("Verifying session...")
try:
    check = session.get(f"{BASE_URL}/auth")
    logger.info(f"GET /api/auth -> {check.status_code}")
    if check.status_code == 200:
        logger.info("Session is valid.")
    else:
        logger.warning("Session check failed.")
except requests.RequestException as e:
    logger.error(f"Network error during session verification: {e}")
