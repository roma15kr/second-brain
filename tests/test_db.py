from kb import db


def test_migrate_is_idempotent(conn):
    assert db.migrate(conn) == []
    names = [r["name"] for r in conn.execute("SELECT name FROM schema_migrations ORDER BY name")]
    assert names == [n for n, _ in db.migration_files()]


def test_concurrent_migrate_is_serialized(conn, pg_url):
    import threading

    conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    results: list[list[str]] = []

    def run():
        with db.connect(pg_url) as c:
            results.append(db.migrate(c))

    threads = [threading.Thread(target=run) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(len(r) for r in results) == [0, 0, len(db.migration_files())]
