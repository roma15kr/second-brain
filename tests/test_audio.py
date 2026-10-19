"""Meeting audio: resumable upload, playback, retention, backups (web-os-v1 task 13.4)."""

import hashlib
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from kb import audio, db
from kb.api import auth
from kb.api.app import build_app
from tests.test_backup import PG_BIN
from tests.test_recordings import START, paired, upload_body

CSRF = {"X-KB-Request": "1"}
AUDIO = bytes(range(256)) * 400  # 100 KB of "audio"
SUM = hashlib.sha256(AUDIO).hexdigest()


@pytest.fixture(autouse=True)
def audio_dir(tmp_path, monkeypatch):
    d = tmp_path / "audio"
    monkeypatch.setenv("KB_AUDIO_DIR", str(d))
    return d


@pytest.fixture
def app(conn, pg_url, config):
    return build_app(
        None,
        connect=lambda: db.connect(pg_url),
        rp=auth.RelyingParty("https://os.x"),
        config=config,
    )


@pytest.fixture
def owner(app, conn):
    c = TestClient(app, base_url="https://os.x")
    c.cookies.set(auth.SESSION_COOKIE, auth.create_session(conn, "t", datetime.now(UTC)))
    return c


@pytest.fixture
def device(app, owner):
    client, token = paired(app, owner)
    h = {"Authorization": f"Bearer {token}"}
    rid = client.post("/api/devices/recordings", json=upload_body(), headers=h).json()[
        "recording_id"
    ]
    return client, h, rid


TOTAL = len(AUDIO)


def announce(client, h, rid, track="mixed", sha=SUM, total=TOTAL):
    return client.post(
        f"/api/devices/recordings/{rid}/audio/{track}",
        json={"mime": "audio/ogg", "total_bytes": total, "sha256": sha, "duration_seconds": 1800},
        headers=h,
    )


def put(client, h, rid, start, data, track="mixed"):
    end = start + len(data) - 1
    return client.put(
        f"/api/devices/recordings/{rid}/audio/{track}",
        content=data,
        headers={**h, "Content-Range": f"bytes {start}-{end}/{len(AUDIO)}"},
    )


def test_resumable_upload_continues_from_received_length(device, audio_dir):
    client, h, rid = device
    assert announce(client, h, rid).json()["received_bytes"] == 0
    assert put(client, h, rid, 0, AUDIO[:40_000]).json()["received_bytes"] == 40_000
    # the connection drops; the app asks where to continue
    head = client.head(f"/api/devices/recordings/{rid}/audio/mixed", headers=h)
    assert head.headers["Upload-Offset"] == "40000" and head.headers["Upload-Complete"] == "0"
    # a repeated chunk is refused with the offset to continue from
    again = put(client, h, rid, 0, AUDIO[:40_000])
    assert again.status_code == 409 and again.headers["Upload-Offset"] == "40000"
    assert announce(client, h, rid).json()["received_bytes"] == 40_000  # re-announce resumes
    done = put(client, h, rid, 40_000, AUDIO[40_000:]).json()
    assert done["complete"] is True
    files = [p for p in audio_dir.rglob("*") if p.is_file()]
    assert [p.name for p in files] == [f"{rid}-mixed.ogg"] and files[0].read_bytes() == AUDIO
    assert files[0].parent == audio_dir / "2026" / "10"


def test_checksum_mismatch_rejected(device, audio_dir):
    client, h, rid = device
    announce(client, h, rid, sha="0" * 64)
    r = put(client, h, rid, 0, AUDIO)
    assert r.status_code == 422 and "checksum" in r.json()["detail"]
    assert [p for p in audio_dir.rglob("*") if p.is_file()] == []
    assert put(client, h, rid, 0, AUDIO[:10]).status_code == 200  # starts over


def test_range_playback_requires_session(app, device, owner):
    client, h, rid = device
    announce(client, h, rid)
    put(client, h, rid, 0, AUDIO)
    part = owner.get(f"/api/recordings/{rid}/audio/mixed", headers={"Range": "bytes=100-199"})
    assert part.status_code == 206 and part.content == AUDIO[100:200]
    assert part.headers["content-type"].startswith("audio/ogg")
    dl = owner.get(f"/api/recordings/{rid}/audio/mixed?download=true")
    assert "attachment" in dl.headers["content-disposition"]
    anon = TestClient(app, base_url="https://os.x")
    assert anon.get(f"/api/recordings/{rid}/audio/mixed").status_code == 401
    assert client.get(f"/api/recordings/{rid}/audio/mixed", headers=h).status_code == 401
    [track] = owner.get(f"/api/recordings/{rid}").json()["audio"]
    assert track["available"] and track["expires_at"].startswith("2027-10-20")


def test_retention_deletes_audio_keeps_transcript(conn, device, owner):
    client, h, rid = device
    announce(client, h, rid)
    put(client, h, rid, 0, AUDIO)
    path = Path(conn.execute("SELECT path FROM recording_audio").fetchone()["path"])
    assert audio.expire(conn, START + timedelta(days=364)) == 0 and path.exists()
    assert audio.expire(conn, START + timedelta(days=366)) == 1 and not path.exists()
    rec = owner.get(f"/api/recordings/{rid}").json()
    assert (
        rec["segments"] and rec["audio"][0]["available"] is False and rec["audio"][0]["deleted_at"]
    )
    assert owner.get(f"/api/recordings/{rid}/audio/mixed").status_code == 404


def test_delete_scope_audio(conn, device, owner):
    client, h, rid = device
    announce(client, h, rid)
    put(client, h, rid, 0, AUDIO)
    conn.execute("UPDATE recordings SET scopes = '{rdim}'")
    assert owner.post("/api/scopes/rdim/delete-audio", headers=CSRF).json() == {"deleted": 1}
    assert owner.get(f"/api/recordings/{rid}").json()["segments"]  # the transcript stays


@pytest.mark.skipif(not (PG_BIN / "pg_dump").exists(), reason="pg tools not available")
def test_audio_backup_copies_new_files_and_verifies(conn, pg_url, tmp_path, device, audio_dir):
    client, h, rid = device
    announce(client, h, rid)
    put(client, h, rid, 0, AUDIO)
    u = urlparse(pg_url)
    env = {
        **os.environ,
        "PATH": f"{PG_BIN}:{os.environ['PATH']}",
        "PGHOST": parse_qs(u.query)["host"][0],
        "PGUSER": u.username or "postgres",
        "KB_DB": u.path.lstrip("/"),
        "BACKUP_DIR": str(tmp_path / "backups"),
        "AUDIO_DIR": str(audio_dir),
        "BACKUP_ONCE": "1",
    }
    (tmp_path / "backups").mkdir()

    def run():
        r = subprocess.run(
            ["sh", "docker/backup.sh"], env=env, capture_output=True, text=True, timeout=300
        )
        assert r.returncode == 0, r.stderr[-2000:]
        return conn.execute(
            "SELECT status, detail FROM backup_checks WHERE kind = 'audio' ORDER BY id DESC LIMIT 1"
        ).fetchone()

    first = run()
    copy = tmp_path / "backups" / "audio" / "2026" / "10" / f"{rid}-mixed.ogg"
    assert (
        first["status"] == "ok" and "copied 1 new" in first["detail"] and copy.read_bytes() == AUDIO
    )
    assert "copied 0 new" in run()["detail"]  # incremental
    conn.execute("UPDATE recording_audio SET deleted_at = now()")
    run()
    assert not copy.exists()  # deleted audio leaves the backup too
    st = audio.storage(conn, datetime.now(UTC))
    assert st["last_backup"]["status"] == "ok"
