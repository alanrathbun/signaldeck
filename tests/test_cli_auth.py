"""Tests for the `signaldeck auth` CLI subcommand group."""
from pathlib import Path

from click.testing import CliRunner

from signaldeck.main import cli
from signaldeck.api.auth import AuthManager


def test_auth_set_password_creates_credentials_and_sets_pw(tmp_path, monkeypatch):
    # Point config to a tmp dir so we don't touch real credentials.yaml
    cred_path = tmp_path / "credentials.yaml"

    # Seed an initial credentials file so the command has something to update.
    initial = AuthManager(credentials_path=str(cred_path))
    initial.initialize()
    old_pw = initial._initial_password

    # Monkeypatch load_config so the CLI command sees our tmp path.
    import signaldeck.main as main_mod
    def fake_load_config(path):
        return {"auth": {"credentials_path": str(cred_path)}}
    monkeypatch.setattr(main_mod, "load_config", fake_load_config)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["auth", "set-password", "--user", "admin", "--password", "brand-new-password"],
    )
    assert result.exit_code == 0, result.output
    assert "updated" in result.output.lower()

    # Reload and verify the new password works, old one does not
    mgr = AuthManager(credentials_path=str(cred_path))
    mgr.initialize()
    assert mgr.verify_login("admin", "brand-new-password")
    assert not mgr.verify_login("admin", old_pw)


def test_auth_set_password_defaults_user_to_admin(tmp_path, monkeypatch):
    cred_path = tmp_path / "credentials.yaml"
    initial = AuthManager(credentials_path=str(cred_path))
    initial.initialize()

    import signaldeck.main as main_mod
    def fake_load_config(path):
        return {"auth": {"credentials_path": str(cred_path)}}
    monkeypatch.setattr(main_mod, "load_config", fake_load_config)

    runner = CliRunner()
    # Invoke with --password to skip the interactive prompt
    result = runner.invoke(cli, ["auth", "set-password", "--password", "new-pw-789"])
    assert result.exit_code == 0, result.output

    mgr = AuthManager(credentials_path=str(cred_path))
    mgr.initialize()
    assert mgr.verify_login("admin", "new-pw-789")
