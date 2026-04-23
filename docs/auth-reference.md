# ServiceTrade API Authentication Reference

Base URL: `https://api.servicetrade.com/api`

We use **session auth** (not OAuth2). The API gives us a long-lived session token that we reuse for all requests.

## Logging In

`POST /api/auth` with JSON body:

```json
{"username": "you@example.com", "password": "your_password"}
```

On success (200), the response includes:
- `data.authToken` — the session token string
- `data.authenticated` — boolean, should be `true`
- `data.eulaNeeded` — boolean, whether the user needs to accept a EULA
- `data.user` — object with `id`, `email`, `firstName`, `lastName`, `username`, `phone`, `isTech`, `isHelper`, `timezone`, `company`, etc.
- A `Set-Cookie` header with `PHPSESSID=<token>`

**Error responses:**
| Code | Meaning |
|------|---------|
| 400  | Username and/or password not provided |
| 403  | Username/password mismatch |

## Using the Token

Send the session cookie on every subsequent request:

```
Cookie: PHPSESSID=<authToken>
```

With Python `requests.Session()`, this is automatic — the session object captures the cookie from the login response and sends it on all future requests.

## Checking if the Session is Still Valid

`GET /api/auth`

- **200** — session is alive, keep using it
- **404** — session expired, need to `POST /api/auth` again

## Logging Out

`DELETE /api/auth`

- **204** — session closed
- **404** — no active session found

## Token Lifecycle

- Tokens are **long-lived**. The API docs explicitly say to get one and reuse it.
- There is no documented expiration time. The recommended pattern is: authenticate once, reuse the token, and only re-authenticate if `GET /api/auth` returns 404.
- For a sync script that runs periodically: check `GET /api/auth` at the start of each run. If 404, log in again.

## Session Limits

- **Soft limit:** 100 open sessions per user
- **Hard limit:** 200 open sessions per user
- Past 200, the API automatically prunes the oldest sessions down to 100

If you're seeing unexpected 401s, check whether something is creating sessions without reusing them (e.g., a script that logs in on every run without checking first).

## Token Persistence (`.session_token`)

The session token is saved to `.session_token` in the project root (gitignored). The auth script (`sync/auth.py`) follows this flow:

1. If `.session_token` exists, load it and `GET /api/auth` to check validity
2. If valid (200), done — no login needed
3. If expired (404) or file missing, `POST /api/auth` with credentials from `.env`
4. Save the new token to `.session_token`

To force a fresh login, just delete the file: `rm .session_token`

## Rate Limiting (`meta.stats`)

Every API response includes a `meta.stats` object with rate limit information:

```json
"meta": {
  "stats": {
    "requestDurationMs": 907,
    "resourceUsageMs": 21,
    "resourceBalanceMs": 60000
  }
}
```

| Field | Meaning |
|-------|---------|
| `requestDurationMs` | Wall-clock time for the request (ms) |
| `resourceUsageMs` | Compute time charged against your budget (ms) |
| `resourceBalanceMs` | Remaining budget this minute (ms). Observed: 60000 = 60 seconds |

The budget replenishes each minute. If `resourceBalanceMs` hits 0, expect 429 responses with `Retry-After` headers. During sync, monitor this value and back off before hitting the limit.

## OAuth2 (Not Our Path)

The API also supports OAuth2 via `Authorization: Bearer <access_token>` headers and the `/api/oauth2/token` endpoint. We're not using this — session auth is simpler for our use case. Mentioned here only so you know it exists if you see references to it.

## Troubleshooting Checklist

| Symptom | Check |
|---------|-------|
| 400 on POST /api/auth | Are both `username` and `password` in the JSON body? Is `Content-Type: application/json` set? |
| 403 on POST /api/auth | Wrong username or password. Verify credentials in `.env`. |
| 401 on any other endpoint | Session expired or cookie not being sent. Run `GET /api/auth` to check. |
| 404 on GET /api/auth | No active session. Need to `POST /api/auth` to get a new one. |
| Intermittent auth failures | Hitting the 200-session hard limit? Make sure the script reuses tokens instead of creating new ones each run. |
| `PHPSESSID` cookie missing | If using `requests.Session()`, the cookie is handled automatically. If using raw `requests.get/post`, you need to pass the cookie manually. |
