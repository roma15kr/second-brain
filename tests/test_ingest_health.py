import argparse
import json

from kb import cli, db, health
from kb.config import load_config
from kb.connectors import imap

CONFIG = """
sources:
  - id: mail
    type: imap
    host: imap.example.com
    username_env: TEST_U
    password_env: TEST_P
"""


def test_expired_credentials_make_source_unhealthy(pg_url, conn, monkeypatch):
    """A login failure inside the real ingest loop is recorded and reported by status."""
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setenv("KB_CONFIG_YAML", CONFIG)
    monkeypatch.setenv("TEST_U", "me@example.com")
    monkeypatch.setenv("TEST_P", "revoked-app-password")

    def login_fails(source):
        raise RuntimeError("b'[AUTHENTICATIONFAILED] Invalid credentials (Failure)'")

    monkeypatch.setattr(imap, "open_client", login_fails)
    cli.cmd_ingest(argparse.Namespace(once=True))
    with db.connect(pg_url) as c:
        st = health.status(c, load_config())
    [src] = st["sources"]
    assert src["healthy"] is False and st["healthy"] is False
    assert "AUTHENTICATIONFAILED" in src["last_error"]
    json.dumps(st, default=str)  # status is serializable for the MCP tool / CLI
