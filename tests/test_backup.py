import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from kb import health
from kb.config import Config

PG_BIN = Path(".venv/lib/python3.12/site-packages/pgserver/pginstall/bin").resolve()


@pytest.mark.skipif(not (PG_BIN / "pg_dump").exists(), reason="pg tools not available")
def test_backup_script_dumps_restores_and_records(conn, pg_url, tmp_path):
    conn.execute(
        "INSERT INTO raw_records (source_id, external_id, kind, payload, content_hash) "
        "VALUES ('s', 'e1', 'email', '{}', 'h1')"
    )
    u = urlparse(pg_url)
    env = {
        **os.environ,
        "PATH": f"{PG_BIN}:{os.environ['PATH']}",
        "PGHOST": parse_qs(u.query)["host"][0],
        "PGUSER": u.username or "postgres",
        "KB_DB": u.path.lstrip("/"),
        "BACKUP_DIR": str(tmp_path),
        "BACKUP_ONCE": "1",
    }
    run = subprocess.run(
        ["sh", "docker/backup.sh"], env=env, capture_output=True, text=True, timeout=300
    )
    assert run.returncode == 0, run.stderr[-2000:]
    dumps = list(tmp_path.glob("kb-*.dump"))
    assert len(dumps) == 1 and dumps[0].stat().st_size > 0
    row = conn.execute("SELECT * FROM backup_checks ORDER BY id DESC LIMIT 1").fetchone()
    assert row["status"] == "ok", row["detail"]
    assert "raw_records=1" in row["detail"]
    st = health.status(conn, Config())
    assert st["backup"]["last_status"] == "ok" and st["backup"]["stale"] is False
    # scratch restore database was cleaned up
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM pg_database WHERE datname = 'kb_restore_check'"
        ).fetchone()["n"]
        == 0
    )
    shutil.rmtree(tmp_path, ignore_errors=True)
