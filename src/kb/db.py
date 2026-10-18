"""Database connections and the SQL migration runner."""

from __future__ import annotations

from importlib import resources

import psycopg
from psycopg.rows import dict_row

Conn = psycopg.Connection[dict]
MIGRATION_LOCK = 7_310_001


def connect(url: str) -> Conn:
    return psycopg.connect(url, row_factory=dict_row, autocommit=True)


def migration_files() -> list[tuple[str, str]]:
    files = resources.files("kb.migrations")
    names = sorted(f.name for f in files.iterdir() if f.name.endswith(".sql"))
    return [(name, (files / name).read_text()) for name in names]


def migrate(conn: Conn) -> list[str]:
    """Apply pending migrations in order; returns the names applied.

    Safe to run from several processes at once: a session advisory lock serializes them.
    """
    conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK,))
    try:
        return _migrate_locked(conn)
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK,))


def _migrate_locked(conn: Conn) -> list[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    done = {r["name"] for r in conn.execute("SELECT name FROM schema_migrations")}
    applied = []
    for name, sql in migration_files():
        if name in done:
            continue
        with conn.transaction():
            conn.execute(sql)
            conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (name,))
        applied.append(name)
    return applied
