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


@pytest.fixture(scope="session")
def migrated(pg_url: str) -> str:
    """Schema built once per test session; each test then starts from empty tables."""
    with db.connect(pg_url) as c:
        c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        db.migrate(c)
    return pg_url


@pytest.fixture
def conn(migrated: str) -> Iterator[db.Conn]:
    with db.connect(migrated) as c:
        tables = [
            r["tablename"]
            for r in c.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                " AND tablename <> 'schema_migrations'"
            )
        ]
        # DELETE is ~100x faster than TRUNCATE on these small tables; FK checks are off while
        # emptying, and sequences restart so every test sees the same ids.
        c.execute("SET session_replication_role = replica")
        for table in tables:
            c.execute(f"DELETE FROM {table}")
        c.execute("SET session_replication_role = DEFAULT")
        for r in c.execute(
            "SELECT sequencename FROM pg_sequences WHERE schemaname = 'public'"
        ).fetchall():
            c.execute(f"ALTER SEQUENCE {r['sequencename']} RESTART")
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
