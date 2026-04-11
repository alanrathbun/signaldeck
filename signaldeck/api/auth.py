import hashlib
import ipaddress
import logging
import secrets
from pathlib import Path

import bcrypt
import yaml

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """Hash a password with bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a bcrypt hash."""
    return bcrypt.checkpw(password.encode(), hashed.encode())


def generate_api_token() -> str:
    """Generate a cryptographically secure API token."""
    return secrets.token_urlsafe(48)


DEFAULT_LAN_ALLOWLIST: list[str] = [
    "127.0.0.0/8",      # IPv4 loopback
    "::1/128",          # IPv6 loopback
    "10.0.0.0/8",       # RFC1918 private
    "172.16.0.0/12",    # RFC1918 private
    "192.168.0.0/16",   # RFC1918 private (typical home router)
    "fc00::/7",         # IPv6 unique-local addresses
    "100.64.0.0/10",    # Tailscale CGNAT
]


def is_lan_client(client_ip: str | None, allowlist: list[str]) -> bool:
    """Return True if client_ip is inside any CIDR range in the allowlist.

    Returns False for None, empty strings, malformed addresses, or IPs
    outside every range. Malformed CIDR entries in the allowlist are
    silently skipped (not an error) to keep a single bad config entry
    from locking the operator out of their own box.
    """
    if not client_ip:
        return False
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


class AuthManager:
    """Manages authentication credentials for SignalDeck.

    On first run, generates a random admin password and API token,
    stores them in a YAML file with the password bcrypt-hashed.
    """

    def __init__(self, credentials_path: str = "config/credentials.yaml") -> None:
        self._path = Path(credentials_path)
        self.api_token: str | None = None
        self.admin_password_hash: str | None = None
        self._initial_password: str | None = None  # only set on first run
        self._users: dict[str, str] = {}  # username -> password_hash

    def initialize(self) -> None:
        """Load or create credentials."""
        if self._path.exists():
            self._load()
        else:
            self._create()

    def _create(self) -> None:
        """Create new credentials on first run."""
        self._initial_password = secrets.token_urlsafe(16)
        self.admin_password_hash = hash_password(self._initial_password)
        self.api_token = generate_api_token()
        self._users = {"admin": self.admin_password_hash}

        self._save()
        logger.info("=" * 60)
        logger.info("FIRST RUN — credentials generated:")
        logger.info("  Admin password: %s", self._initial_password)
        logger.info("  API token: %s", self.api_token)
        logger.info("  Saved to: %s", self._path)
        logger.info("  CHANGE THE PASSWORD after first login!")
        logger.info("=" * 60)

    def _load(self) -> None:
        """Load existing credentials."""
        with open(self._path) as f:
            data = yaml.safe_load(f)

        self.api_token = data.get("api_token", "")
        self._users = data.get("users", {})
        self.admin_password_hash = self._users.get("admin", "")
        logger.info("Credentials loaded from %s", self._path)

    def _save(self) -> None:
        """Save credentials to file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "api_token": self.api_token,
            "users": self._users,
        }
        with open(self._path, "w") as f:
            yaml.dump(data, f, default_flow_style=False)
        # Restrict permissions
        self._path.chmod(0o600)

    def verify_token(self, token: str) -> bool:
        """Verify an API bearer token."""
        return secrets.compare_digest(token, self.api_token or "")

    def verify_login(self, username: str, password: str) -> bool:
        """Verify username/password credentials."""
        if username not in self._users:
            return False
        return verify_password(password, self._users[username])

    def change_password(self, username: str, new_password: str) -> None:
        """Change a user's password."""
        self._users[username] = hash_password(new_password)
        if username == "admin":
            self.admin_password_hash = self._users[username]
        self._save()
        logger.info("Password changed for user: %s", username)

    def create_session_token(self) -> str:
        """Create a session token for web login."""
        return secrets.token_urlsafe(32)

    # ---- Remember-me tokens (database-backed) ----

    @staticmethod
    def _hash_token(raw: str) -> str:
        """Return the SHA-256 hex digest of a raw token."""
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _auto_label_from_ua(user_agent: str | None) -> str:
        """Derive a short human-readable label from a User-Agent string.

        Examples:
            iPhone Safari, iPad Safari, Android Chrome, Mac Safari,
            Mac Chrome, Windows Firefox. Falls back to the first 40 chars
            of the UA if no known pattern matches.
        """
        if not user_agent:
            return "Unknown device"
        ua = user_agent
        # Device
        if "iPhone" in ua:
            device = "iPhone"
        elif "iPad" in ua:
            device = "iPad"
        elif "Android" in ua:
            device = "Android"
        elif "Macintosh" in ua or "Mac OS X" in ua:
            device = "Mac"
        elif "Windows" in ua:
            device = "Windows"
        elif "Linux" in ua:
            device = "Linux"
        else:
            device = None
        # Browser
        if "Edg/" in ua:
            browser = "Edge"
        elif "Firefox/" in ua:
            browser = "Firefox"
        elif "Chrome/" in ua and "Chromium" not in ua:
            browser = "Chrome"
        elif "Safari/" in ua:
            browser = "Safari"
        else:
            browser = None
        if device and browser:
            return f"{device} {browser}"
        if device:
            return device
        if browser:
            return browser
        return ua[:40]

    async def create_remember_token(
        self,
        db,
        *,
        user_agent: str | None,
        ip: str | None,
        label: str | None = None,
    ) -> str:
        """Generate a new random token, persist its hash, return the raw token.

        The raw value is the cookie the browser will store. The database
        only ever sees the SHA-256 hash.
        """
        raw = secrets.token_urlsafe(32)  # 256 bits of entropy
        token_hash = self._hash_token(raw)
        chosen_label = label if label is not None else self._auto_label_from_ua(user_agent)
        await db.insert_remember_token(
            token_hash=token_hash,
            user_agent=user_agent,
            ip_first_seen=ip,
            label=chosen_label,
        )
        return raw

    async def verify_remember_token(self, db, raw_token: str) -> bool:
        """Return True iff the token's hash matches a remember_tokens row.

        On success, touches the row's last_used_at. On any failure —
        missing token, unknown hash, or database error — returns False
        and performs no writes.
        """
        if not raw_token:
            return False
        try:
            token_hash = self._hash_token(raw_token)
            row = await db.get_remember_token_by_hash(token_hash)
            if row is None:
                return False
            await db.update_remember_token_last_used(token_hash)
            return True
        except Exception as e:
            logger.warning("verify_remember_token error: %s", e)
            return False
