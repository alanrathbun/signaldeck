# Single-User Auth + Location-Aware Audio Modes

**Date:** 2026-04-10
**Branch:** TBD (probably `feature/single-user-auth`)
**Status:** Approved

## Overview

Make SignalDeck reachable and controllable from any of the operator's devices (desktop, laptop, phone, tablet) without requiring per-device state, while keeping it safe from strangers who stumble onto the server's address. Audio must work correctly in both "operator sitting at the server machine" and "operator on their phone in another room" cases, without the operator having to remember to flip a switch.

The design is deliberately **single-user**. There are no roles, no multi-user coordination primitives, no account creation flows, and no permission grants. One person uses this. What this project delivers is a clean way for that one person to access their server from multiple places without clashes or manual reconfiguration.

## Non-goals

- **Multi-user accounts, roles, or permission tiers.** If this project ever becomes a team tool, that's a separate spec.
- **Multi-listener audio (different stations at once).** Only one tuning at a time, as today. A "WebSDR-style" DSP pipeline for per-client virtual channels is a separate project.
- **Reverse-proxy / TLS termination / Dynamic DNS / port forwarding.** Out of scope — handled by Tailscale in the operator's actual environment. A config knob exists (`auth.trust_x_forwarded_for`) to make future proxy deployment easier, but nothing wires it up beyond accepting the config value.
- **Per-device synchronized UI preferences** beyond the Live Signals column selection. Volume, waterfall toggle, current page, and filter inputs stay per-device because those are hardware- or context-specific.
- **Changes to the scanner engine, gqrx lifecycle, scan profile resolution, or the RF path.** This is an auth + session + one-setting project.

## Architecture

Four subsystems change. Everything else in SignalDeck is untouched.

1. **`AuthMiddleware` gets smarter.** Instead of all-or-nothing, it decides per-request based on (a) client IP and (b) an optional remember-me cookie. Loopback or LAN (including Tailscale CGNAT) → pass. Valid cookie → pass. Otherwise → 401.
2. **A login overlay** appears only when the middleware 401s a remote client. User logs in once, the server sets a long-lived cookie, subsequent requests from that browser are silently allowed. A "Signed-in devices" card in Settings lists and revokes those cookies.
3. **Audio backend becomes a runtime decision.** A new `audio_mode: auto | gqrx | pcm_stream` setting controls whether audio plays on the server's local speakers via gqrx or streams PCM to browsers over `/ws/audio`. In `auto` mode (the default), the decision tracks who's connected to `/ws/audio`: any remote subscriber → PCM stream; all LAN or no subscribers → gqrx local.
4. **UI preferences gain a small sync surface.** The Live Signals column selection moves from browser-only Alpine state into `config/user_settings.yaml` under a new `ui:` section, so it follows the operator across devices.

There are **no database schema migrations** except for one new table (`remember_tokens`). Bookmarks already live in SQLite, hardware config already lives in `user_settings.yaml`. Everything else is reused.

## Constraints and defaults

- **Backwards compatible by default.** Everything new hides behind `auth.enabled: true`. The current default (`auth.enabled: false`) keeps working unchanged — no LAN check, no login, no WebSocket auth, no audio mode decision (it just picks gqrx when there are no remote WS subscribers, matching today's behavior).
- **Tailscale is the primary access path.** The operator already runs Tailscale on all their devices. The LAN allowlist includes Tailscale CGNAT (`100.64.0.0/10`) by default, so devices reaching the server over Tailscale never see a login page. The remember-me flow exists for the rare case of a browser that isn't on the tailnet.
- **Single operator, one account.** Hardcoded username `admin`, auto-generated password on first auth-enable. The existing `AuthManager` scaffolding handles this today; this spec extends it but does not rewrite it.
- **gqrx is always the tuner.** In every audio mode, gqrx keeps tracking the current frequency. Switching from `gqrx` to `pcm_stream` mode means setting gqrx's AF gain to 0 (muted, still tuned) and starting the scanner's own demodulator for PCM streaming. Switching back restores gqrx's stored volume. No gqrx restart, no subprocess lifecycle changes, near-instant mode flips.

## Component design

### 1. `is_lan_client` helper and config

**New file or additions to `signaldeck/api/auth.py`** (implementer's choice — either works):

```python
import ipaddress

DEFAULT_LAN_ALLOWLIST = [
    "127.0.0.0/8",      # IPv4 loopback
    "::1/128",          # IPv6 loopback
    "10.0.0.0/8",       # RFC1918
    "172.16.0.0/12",    # RFC1918
    "192.168.0.0/16",   # RFC1918 (home router default)
    "fc00::/7",         # IPv6 unique-local addresses
    "100.64.0.0/10",    # Tailscale CGNAT
]

def is_lan_client(client_ip: str, allowlist: list[str]) -> bool:
    """Return True if client_ip is in any of the allowlist CIDR ranges."""
    try:
        ip = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    for cidr in allowlist:
        try:
            if ip in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False
```

Config additions to `config/default.yaml` under `auth:`:

```yaml
auth:
  enabled: false                    # existing
  credentials_path: config/credentials.yaml   # existing
  lan_allowlist:                    # NEW — overrides DEFAULT_LAN_ALLOWLIST if set
    - 127.0.0.0/8
    - ::1/128
    - 10.0.0.0/8
    - 172.16.0.0/12
    - 192.168.0.0/16
    - fc00::/7
    - 100.64.0.0/10
  trust_x_forwarded_for: false      # NEW — placeholder for future reverse-proxy setup
  remember_token_days: null         # NEW — null means no expiration (revoke-only)
```

### 2. `AuthMiddleware` dispatch rewrite

**File:** `signaldeck/api/server.py`

New dispatch logic, replacing the existing `AuthMiddleware.dispatch` method:

```
1. If auth_mgr is None (auth.enabled is false) → pass through.
2. Allow public paths: /api/health, /api/auth/login, /api/auth/toggle.
   (Other /api/auth/* routes are now protected — they operate on sessions,
   which must be authenticated.)
3. Non-API paths (static files) → pass through. The frontend handles its own
   401 detection via apiFetch().
4. Determine client IP: request.client.host, or X-Forwarded-For[0] if
   auth.trust_x_forwarded_for is True.
5. If is_lan_client(client_ip, allowlist) → pass through.
6. Check Authorization: Bearer header → valid api_token → pass through.
7. Check remember-me cookie (sd_remember) → valid token in remember_tokens
   table → update last_used_at → pass through.
8. Otherwise → 401.
```

**Why some `/api/auth/*` routes become protected:** today, the entire `/api/auth/*` prefix is public. That's fine when the only endpoint behind it is `login`, but the new `/api/auth/sessions` endpoints (list/rename/revoke devices) must be authenticated. The middleware change is: allowlist the *specific* public auth endpoints (`login`, `toggle`) instead of the whole prefix.

### 3. WebSocket auth

**Files:** `signaldeck/api/websocket/audio_stream.py`, `live_signals.py`, `waterfall.py`

Each WebSocket handler calls a new helper at the top of its handshake:

```python
async def _ws_authorized(websocket: WebSocket) -> bool:
    """Run the same auth gate as AuthMiddleware against a WebSocket handshake."""
    auth_mgr = _state.get("auth")
    if auth_mgr is None:
        return True  # auth disabled

    client_ip = websocket.client.host if websocket.client else ""
    cfg = _state.get("config", {})
    allowlist = cfg.get("auth", {}).get("lan_allowlist", DEFAULT_LAN_ALLOWLIST)
    if is_lan_client(client_ip, allowlist):
        return True

    # Bearer header check (rare on WS, but possible from native clients)
    auth_header = dict(websocket.headers).get("authorization", "")
    if auth_header.startswith("Bearer ") and auth_mgr.verify_token(auth_header[7:]):
        return True

    # Remember-me cookie check (the normal browser path)
    db = _state.get("db")
    cookie = websocket.cookies.get("sd_remember")
    if cookie and db is not None and await auth_mgr.verify_remember_token(db, cookie):
        return True

    return False
```

Usage:

```python
@router.websocket("/ws/audio")
async def ws_audio(websocket: WebSocket):
    if not await _ws_authorized(websocket):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    # ... rest of handler unchanged
```

This closes a pre-existing hole where remote clients could open `/ws/audio`, `/ws/signals`, or `/ws/waterfall` without any credentials even when auth was enabled for REST endpoints.

### 4. Remember-me tokens

**New SQLite table** (created in `signaldeck/storage/database.py` via the existing schema initialization path):

```sql
CREATE TABLE IF NOT EXISTS remember_tokens (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash     TEXT NOT NULL UNIQUE,
    created_at     TEXT NOT NULL,
    last_used_at   TEXT NOT NULL,
    user_agent     TEXT,
    ip_first_seen  TEXT,
    label          TEXT
);
CREATE INDEX IF NOT EXISTS idx_remember_tokens_hash ON remember_tokens(token_hash);
```

**Hashing:** SHA-256 of the raw token, stored in `token_hash`. The raw token is never written to the database. Rationale: bcrypt is too slow for per-request verification, and SHA-256 is sufficient because the raw token is 256 bits of CSPRNG entropy — brute force is infeasible regardless of hash choice. The hash protects against database-exfil leaks.

**New methods on `AuthManager`** (`signaldeck/api/auth.py`):

```python
async def create_remember_token(
    self, db, user_agent: str, ip: str, label: str | None = None
) -> str:
    """Generate a new token, insert a row, return the raw token to set as cookie."""

async def verify_remember_token(self, db, raw_token: str) -> bool:
    """Return True if the token's SHA-256 hash matches a row in remember_tokens.
    On a successful match, updates that row's last_used_at to the current time.
    Returns False (and performs no writes) on any failed lookup or DB error."""

async def list_remember_tokens(self, db) -> list[dict]:
    """Return all rows (minus token_hash) for the Devices UI."""

async def rename_remember_token(self, db, token_id: int, label: str) -> bool:
    """Update the label on a row. Returns False if no such row."""

async def revoke_remember_token(self, db, token_id: int) -> bool:
    """Delete a row. Returns False if no such row."""
```

Label auto-generation from user-agent: extract a short friendly string (e.g., `"iPhone Safari"`, `"MacBook Chrome"`) by matching well-known substrings. Fallback: first 40 characters of the raw UA string. This is cosmetic — user can rename.

**Token expiration:** `auth.remember_token_days: null` (default) means tokens never expire. They live until explicitly revoked. `last_used_at` is still tracked so the Devices UI shows "last used 2 hours ago," but it is not used to enforce expiry. A future change could set `remember_token_days` to a number to enforce sliding-window expiry.

### 5. Login endpoint changes

**File:** `signaldeck/api/routes/auth_routes.py`

The existing `POST /api/auth/login` handler is extended to:

1. Verify username + password via `AuthManager.verify_login` (already done today).
2. Generate a new remember-me token via `AuthManager.create_remember_token`, passing `User-Agent`, `request.client.host`, and `None` for the label (auto-generated).
3. Return the raw token in the response body (for CLI/curl users).
4. Set the `sd_remember` cookie: `Set-Cookie: sd_remember=<token>; HttpOnly; SameSite=Lax; Path=/; Max-Age=<seconds>`. When `auth.remember_token_days` is an integer, `Max-Age = days * 86400`. When it is `null` (the default), `Max-Age` is set to `315360000` seconds (10 years) — effectively forever for browser purposes, while the server-side row remains the actual source of truth. This guarantees that a device the operator has logged in from stays logged in across browser restarts until they explicitly revoke it.
5. Do **not** return or set any dead `session_token` field. That field is removed from the response.

The response body becomes:

```json
{ "username": "admin", "remember_token": "<raw-token>" }
```

### 6. Session management endpoints

**New routes in `signaldeck/api/routes/auth_routes.py`:**

```
GET    /api/auth/sessions           — list all remember_tokens rows (no hashes)
PATCH  /api/auth/sessions/{id}      — rename: body { "label": "New name" }
DELETE /api/auth/sessions/{id}      — revoke
POST   /api/auth/logout             — convenience: revoke the *current* token from cookie
```

All four are authenticated (the middleware already gates `/api/auth/sessions` because it's not on the public allowlist).

The list response includes a `is_current: true` flag on whichever row matches the requesting client's own cookie, so the UI can show "this device."

### 7. First-run password visibility

**File:** `signaldeck/api/routes/auth_routes.py`

When `POST /api/auth/toggle` enables auth AND a new `admin` account is being created for the first time, the response includes the freshly-generated password:

```json
{ "enabled": true, "first_run_password": "xyz123..." }
```

`first_run_password` is only present on the response that caused the initial credentials file creation. Subsequent calls to `/api/auth/toggle` never return it, even if auth is disabled and re-enabled (because `credentials.yaml` already exists with a hashed password).

**Frontend:** when this field is present in the toggle response, the dashboard shows a modal:

> **Auth enabled.** Your admin password is:
> `xyz123abc456def789`
> [Copy to clipboard]
> Save this in your password manager now. You will not see it again.
> [ I've saved it ]

The modal is blocking — user can't dismiss without clicking "I've saved it." Pure UX, no server-side enforcement.

### 8. CLI password-reset escape hatch

**File:** `signaldeck/main.py`

New Click subcommand group:

```python
@cli.group()
def auth():
    """Manage SignalDeck authentication."""

@auth.command("set-password")
@click.option("--user", default="admin", help="Username to update.")
@click.password_option("--password", help="New password (prompted if not provided).")
def auth_set_password(user: str, password: str) -> None:
    """Reset a user's password without needing the current one."""
    cfg = load_config(None)
    cred_path = cfg.get("auth", {}).get("credentials_path", "config/credentials.yaml")
    mgr = AuthManager(credentials_path=cred_path)
    mgr.initialize()
    mgr.change_password(user, password)
    click.echo(f"Password updated for {user}.")
```

This bypasses the current-password check that `/api/auth/change-password` enforces — rationale: the person running the CLI is already the local operator (they have shell access to the server), so they implicitly have authority to rewrite credentials. This is the recovery path for a forgotten password.

### 9. Audio mode auto-switching

**Config addition** to `config/default.yaml`:

```yaml
scanner:
  audio_mode: auto   # auto | gqrx | pcm_stream
```

And in `config/user_settings.yaml` (written on settings save).

**Runtime state** (`signaldeck/api/websocket/audio_stream.py`):

The existing `_audio_clients: dict[WebSocket, float | None]` is replaced with a richer structure:

```python
_audio_clients: dict[WebSocket, dict] = {}
# Each value: {"freq": float | None, "is_lan": bool, "remote_addr": str}
```

On subscribe, the handler records the WebSocket's `client.host` and its LAN-or-remote classification.

**Decision function** (new, in `audio_stream.py` or a sibling module):

```python
def resolve_effective_audio_mode(configured_mode: str) -> str:
    """Return the effective audio mode based on config + current subscribers."""
    if configured_mode == "gqrx":
        return "gqrx"
    if configured_mode == "pcm_stream":
        return "pcm_stream"
    # auto
    if any(c["freq"] is not None and not c["is_lan"] for c in _audio_clients.values()):
        return "pcm_stream"
    return "gqrx"
```

**Scanner integration:** the existing code path that starts/stops the scanner's demodulator consults `resolve_effective_audio_mode()` whenever the set of `/ws/audio` subscribers changes or when the configured mode changes. On a flip:

- `gqrx → pcm_stream`: send rigctl `L AF 0` to mute gqrx (remembering the previous volume), start the scanner's demodulator at the current frequency.
- `pcm_stream → gqrx`: stop the scanner's demodulator, send rigctl `L AF <saved_volume>` to restore gqrx audio.

gqrx tuning (`F <freq>`) is untouched in both directions — gqrx always tracks the current frequency regardless of mode.

**Status reporting:** the audio WebSocket's `subscribed` reply now includes the effective mode:

```json
{ "type": "subscribed", "frequency_hz": 90100000, "effective_mode": "pcm_stream" }
```

And `GET /api/status` adds a field:

```json
{
  "audio": {
    "configured_mode": "auto",
    "effective_mode": "pcm_stream",
    "subscriber_count": 1,
    "remote_subscriber_count": 1
  }
}
```

**Settings UI addition:** a new "Audio Output" card on the Settings page, above or adjacent to the existing "Audio Preferences" card:

> **Audio Output**
>
> - ( ) Automatic — gqrx when listening locally, browser stream when remote (default)
> - ( ) Local gqrx — always play through server speakers
> - ( ) Browser stream — always stream PCM to connected browsers
>
> **Currently active:** Browser stream (1 remote client: iPhone Safari, 100.93.40.9)

The "Currently active" line is populated from the `/api/status.audio` fields and updates on the existing status poll (3 seconds).

**Silence detection edge case:** if `configured_mode == "gqrx"` (manual pin) and a remote client subscribes to `/ws/audio`, the server will still accept the subscription but won't stream. The frontend compares the `effective_mode` in the `subscribed` reply against what it expected and shows a banner:

> Audio mode is set to **Local gqrx** — this browser will not receive audio. [Switch to Automatic]

One-click resolution: the link hits `PUT /api/settings` with `audio_mode: "auto"` and the mode flips immediately.

### 10. UI preferences persistence (column selection)

**Config addition** to `config/user_settings.yaml`:

```yaml
ui:
  live_visible_cols:
    - frequency
    - modulation
    - protocol
    - hits
    - last_seen
    - activity_summary
```

**Frontend changes** (`signaldeck/web/js/app.js`):

- `applySettings(settings)` copies `settings.ui.live_visible_cols` into `this.liveVisibleCols` if present.
- `saveSettings()` includes `ui: { live_visible_cols: this.liveVisibleCols }` in the PUT payload.
- When the user toggles a column, the change is debounced and auto-saved (e.g., 500ms after the last click) so they don't have to manually hit Save.

Other UI state (`audioVolume`, `showWaterfall`, `mobileMenuOpen`, `currentPage`, filter inputs) stays in Alpine local state / browser storage. They're device-specific and shouldn't sync.

### 11. Login overlay

**Frontend changes** (`signaldeck/web/js/app.js` and `signaldeck/web/index.html`):

- New Alpine state: `loginRequired: false`, `loginUsername: ''`, `loginPassword: ''`, `loginError: ''`, `_retryAfterLogin: null`.
- `apiFetch(url, opts)` is extended: if the response status is 401, it sets `loginRequired = true`, stashes the failed request in `_retryAfterLogin`, and returns null.
- The overlay is a fixed-position full-screen modal in `index.html`, hidden by default, shown when `loginRequired` is true. Contains a username field (default `admin`), a password field, a Submit button, and an error message area.
- On submit, calls `POST /api/auth/login` with the credentials. On success, clears `loginRequired`, re-runs `_retryAfterLogin`, and shows a success toast.
- On failure (401), shows the error message and keeps the modal visible.

The overlay uses the existing CSS variables and toast system — no new style primitives.

### 12. Signed-in devices UI

**Frontend additions** (`signaldeck/web/index.html`, `signaldeck/web/js/app.js`):

New card in the Settings page, below the existing auth settings:

```
Signed-in devices
─────────────────────────────────────────────
| Label            | First seen | Last used  |         |
|------------------|------------|------------|---------|
| iPhone Safari    | 2026-04-05 | 2h ago     | [Rename] [Revoke] |
| MacBook Chrome   | 2026-03-30 | now (this) | [Rename] [Revoke] |

[ + Generate new API token for scripts ]
[ Change password ]
```

Backed by:
- `fetchSessions()` — calls `GET /api/auth/sessions`, stores in `this.sessions`.
- `renameSession(id, newLabel)` — calls `PATCH /api/auth/sessions/{id}`.
- `revokeSession(id)` — calls `DELETE /api/auth/sessions/{id}`. If the revoked session is `is_current`, the next request will 401 and trigger the login overlay.
- The existing API token and change-password flows are linked in the same card for discoverability.

## Error handling

- **Malformed client IPs** (theoretically impossible from a real TCP socket, but guard anyway): `is_lan_client` returns False, request proceeds to bearer/cookie checks, and 401s if those also fail.
- **Missing `remember_tokens` table** (shouldn't happen after initial run, but guard for version-skew): `verify_remember_token` catches the SQLite error, logs a warning, returns False. The user will be forced to log in again.
- **Cookie present but expired or revoked**: `verify_remember_token` returns False, middleware 401s, frontend shows the login overlay. The stale cookie is not explicitly cleared server-side, but it will be overwritten on the next successful login.
- **WebSocket handshake without cookie on a remote client**: handler calls `websocket.close(code=1008)`. Frontend's WebSocket reconnect logic should detect the close code and trigger the same login overlay flow as a 401 on REST.
- **Mode-flip failure** (gqrx rigctl unreachable during a `gqrx ↔ pcm_stream` transition): log a warning, the effective mode field in `/api/status` still updates to the *intended* mode, the user sees "no audio" in the UI. Next mode change retries the rigctl command.

## Testing strategy

New test files under `tests/`:

### `tests/test_is_lan_client.py`

Pure function, no fixtures needed. Parameterized tests covering:

- Loopback: `127.0.0.1`, `127.1.2.3`, `::1` → True
- RFC1918: `10.0.0.1`, `172.16.5.5`, `192.168.1.100` → True
- Tailscale CGNAT: `100.64.0.1`, `100.94.221.106`, `100.127.255.254` → True
- IPv6 ULA: `fd00::1` → True
- Public IPv4: `8.8.8.8`, `1.1.1.1` → False
- Public IPv6: `2001:4860:4860::8888` → False
- Malformed: `"not-an-ip"`, `""`, `None` → False
- Edge of CGNAT: `100.63.255.255` → False, `100.64.0.0` → True, `100.127.255.255` → True, `100.128.0.0` → False
- Custom allowlist override: empty allowlist rejects everything; single-entry allowlist accepts only that range

### `tests/test_auth_middleware.py`

Uses FastAPI `TestClient` with a test app that mounts `AuthMiddleware`. Tests:

- Auth disabled → any request passes
- Auth enabled + loopback client → request passes without credentials
- Auth enabled + LAN client → request passes without credentials
- Auth enabled + Tailscale CGNAT client → request passes without credentials
- Auth enabled + remote client + valid bearer → request passes
- Auth enabled + remote client + valid remember-me cookie → request passes, last_used_at updated
- Auth enabled + remote client + no credentials → 401
- Auth enabled + remote client + invalid cookie → 401
- Auth enabled + remote client + revoked cookie → 401
- Public paths (`/api/health`, `/api/auth/login`, `/api/auth/toggle`) → always pass
- WebSocket handshake with auth → closes 1008 on remote-no-cookie, accepts on LAN

Client-IP injection is done via a test middleware that rewrites `request.scope["client"]` before `AuthMiddleware` runs, allowing tests to simulate different IPs without actually binding to them.

### `tests/test_remember_tokens.py`

Uses a real SQLite in-memory database via the existing test fixture pattern. Tests:

- `create_remember_token` inserts a row, returns a raw token, hashes match
- `verify_remember_token` accepts freshly-created tokens
- `verify_remember_token` rejects unknown tokens
- `verify_remember_token` updates `last_used_at` on successful verify
- `list_remember_tokens` returns all rows, `token_hash` is never in the output
- `rename_remember_token` updates the label, returns True; returns False for unknown id
- `revoke_remember_token` deletes the row, returns True; returns False for unknown id
- Revoked token no longer verifies
- Raw token never appears in the database (query the `token_hash` column directly, assert it's a 64-char hex string, not the raw value)

### `tests/test_audio_mode.py`

Unit tests for `resolve_effective_audio_mode` with mocked `_audio_clients`:

- `configured_mode="gqrx"` + any subscribers → `"gqrx"` (manual pin)
- `configured_mode="pcm_stream"` + any subscribers → `"pcm_stream"` (manual pin)
- `configured_mode="auto"` + no subscribers → `"gqrx"`
- `configured_mode="auto"` + 1 LAN subscriber → `"gqrx"`
- `configured_mode="auto"` + 1 remote subscriber → `"pcm_stream"`
- `configured_mode="auto"` + mixed LAN and remote → `"pcm_stream"`
- `configured_mode="auto"` + subscriber with `freq=None` (subscribed but not tuned) → ignored in the decision
- Subscriber disconnect transitions the effective mode back correctly

### Regression coverage

Existing tests in `tests/test_api_server.py` and `tests/test_api_process.py` are re-run with a new fixture that enables auth and simulates a loopback client. Loopback bypass must preserve today's behavior — if any existing test starts failing with auth enabled, it means the middleware is being too strict on `127.0.0.1`.

## Migration and backwards compatibility

**For users on today's default (`auth.enabled: false`):** zero action required. Nothing breaks. Audio defaults to `auto` mode, which picks `gqrx` in the absence of remote subscribers — identical to today's behavior. Column selection is persisted to `user_settings.yaml` on first save, which is additive and harmless.

**For users enabling auth:**

1. Pull the new build, restart the service.
2. Flip `auth.enabled: true` via `POST /api/auth/toggle` (or edit `config/default.yaml`).
3. If this is the first time auth has been enabled on this install, the toggle response returns the generated admin password. The UI shows a one-time modal; the operator copies it to their password manager.
4. From Tailscale-enabled devices, the operator continues to access the dashboard at `http://<server-tailscale-ip-or-hostname>:9090` with no login required — Tailscale IPs are in the LAN allowlist.
5. From any browser that's not on the tailnet (rare), the login overlay appears on first access. The operator logs in with `admin` + the saved password. A remember-me cookie is set; future visits from that browser skip the prompt until revoked.
6. If the password is ever lost, `signaldeck auth set-password` on the server host resets it without needing the current password.

**Database migration:** a single `CREATE TABLE IF NOT EXISTS remember_tokens` in the storage initialization path. No data migration, no downtime, idempotent.

**Forward compatibility:** the `auth.remember_token_days` config knob exists as `null` by default (no expiration). Setting it to an integer enforces sliding-window expiry. This is the future hook for operators who want stricter behavior.

## Open questions and deferred items

- **Reverse-proxy support.** `auth.trust_x_forwarded_for` is accepted by the config loader but not fully wired through `AuthMiddleware`. If this project ever sits behind nginx/Caddy, a follow-up implements the header parsing (including validation of the trusted proxy source IP).
- **MagicDNS health warning on the operator's current install.** Separate networking rabbit hole (systemd-resolved vs. Tailscale's DNS), not a blocker — the server's raw Tailscale IP `100.94.221.106:9090` works regardless.
- **Multi-listener DSP pipeline.** Out of scope for this project (WebSDR-style per-client virtual channels). If it ever ships, `resolve_effective_audio_mode` would grow from a 2-way decision to a multi-channel router and the schema around `_audio_clients` would need per-client demod state.
- **Scan result dedupe / holdoff.** Tracked separately in the handoff doc; unrelated to this project.

## Acceptance criteria

This project is considered complete when all of the following are true:

1. With `auth.enabled: false`, every existing test in the repo still passes and the dashboard behaves identically to today.
2. With `auth.enabled: true` and an auto-generated admin password, the operator can access the dashboard from `http://<server-tailscale-ip>:9090` on their iPhone without typing a password.
3. With `auth.enabled: true`, an attacker hitting the server's public IP (if such an IP existed) receives a 401 on every `/api/*` endpoint and a WebSocket close code 1008 on every `/ws/*` endpoint.
4. Opening the dashboard from a non-Tailscale browser shows a login overlay; successful login sets a cookie and future visits from that browser skip the prompt.
5. The Settings page shows a "Signed-in devices" list; revoking a device's row causes that device's next request to 401.
6. The Settings page shows an "Audio Output" card with the three-way selector and a live "Currently active: ..." status line.
7. With `audio_mode: auto`, subscribing to `/ws/audio` from a remote client causes the server to mute gqrx and start streaming PCM. Unsubscribing causes gqrx's volume to restore.
8. With `audio_mode: gqrx` (manual), a remote client subscribing to `/ws/audio` sees a "no audio in this mode" banner.
9. Toggling Live Signals columns on one browser and refreshing on another browser (both logged in as the same admin) shows the same column selection.
10. `signaldeck auth set-password` on the CLI resets the admin password without requiring the current password.
11. All new tests listed in the testing strategy section pass.
