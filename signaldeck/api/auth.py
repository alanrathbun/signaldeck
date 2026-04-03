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
