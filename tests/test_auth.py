import pytest
from httpx import AsyncClient, ASGITransport

from signaldeck.api.auth import (
    hash_password,
    verify_password,
    generate_api_token,
    AuthManager,
)


def test_hash_and_verify_password():
    """Password hashing and verification works."""
    password = "test-password-123"
    hashed = hash_password(password)
    assert hashed != password
    assert verify_password(password, hashed)
    assert not verify_password("wrong-password", hashed)


def test_generate_api_token():
    """API tokens are generated with sufficient entropy."""
    token1 = generate_api_token()
    token2 = generate_api_token()
    assert len(token1) >= 32
    assert token1 != token2


def test_auth_manager_init(tmp_path):
    """AuthManager creates credentials file on first run."""
    cred_path = str(tmp_path / "credentials.yaml")
    mgr = AuthManager(credentials_path=cred_path)
    mgr.initialize()
    assert mgr.api_token is not None
    assert len(mgr.api_token) >= 32
    assert mgr.admin_password_hash is not None


def test_auth_manager_persists(tmp_path):
    """Credentials persist across restarts."""
    cred_path = str(tmp_path / "credentials.yaml")
    mgr1 = AuthManager(credentials_path=cred_path)
    mgr1.initialize()
    token1 = mgr1.api_token

    mgr2 = AuthManager(credentials_path=cred_path)
    mgr2.initialize()
    assert mgr2.api_token == token1


def test_auth_manager_verify_token(tmp_path):
    cred_path = str(tmp_path / "credentials.yaml")
    mgr = AuthManager(credentials_path=cred_path)
    mgr.initialize()
    assert mgr.verify_token(mgr.api_token)
    assert not mgr.verify_token("invalid-token")


def test_auth_manager_verify_login(tmp_path):
    cred_path = str(tmp_path / "credentials.yaml")
    mgr = AuthManager(credentials_path=cred_path)
    mgr.initialize()
    # Default username is "admin"
    assert mgr.verify_login("admin", mgr._initial_password)
    assert not mgr.verify_login("admin", "wrong")
    assert not mgr.verify_login("nobody", mgr._initial_password)


def test_auth_manager_change_password(tmp_path):
    cred_path = str(tmp_path / "credentials.yaml")
    mgr = AuthManager(credentials_path=cred_path)
    mgr.initialize()
    old_pw = mgr._initial_password
    mgr.change_password("admin", "new-password-456")
    assert mgr.verify_login("admin", "new-password-456")
    assert not mgr.verify_login("admin", old_pw)
