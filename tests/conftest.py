"""Test database: an embedded Postgres (pgserver, includes pgvector), one per test session."""

from __future__ import annotations

import tempfile
from collections.abc import Iterator

import pytest

from kb import db
from kb.config import Config, ImapSource


@pytest.fixture(scope="session")
def pg_url() -> Iterator[str]:
    pgserver = pytest.importorskip("pgserver")
    srv = pgserver.get_server(tempfile.mkdtemp(prefix="kb-test-pg-"), cleanup_mode="stop")
    srv.psql("DROP DATABASE IF EXISTS kb_test;")
    srv.psql("CREATE DATABASE kb_test;")
    yield srv.get_uri("kb_test")


@pytest.fixture
def conn(pg_url: str) -> Iterator[db.Conn]:
    with db.connect(pg_url) as c:
        c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        db.migrate(c)
        yield c


@pytest.fixture
def source(monkeypatch: pytest.MonkeyPatch) -> ImapSource:
    monkeypatch.setenv("TEST_IMAP_USER", "me@example.com")
    monkeypatch.setenv("TEST_IMAP_PASS", "secret")
    return ImapSource(
        id="mail-test",
        type="imap",
        scopes=["digisoft"],
        host="imap.example.com",
        username_env="TEST_IMAP_USER",
        password_env="TEST_IMAP_PASS",
        backfill_days=365,
    )


@pytest.fixture
def config(source: ImapSource) -> Config:
    return Config(sources=[source])
