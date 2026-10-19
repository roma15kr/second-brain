"""Recorder apps, notes import and meeting processing (calendar-meetings; web-os-v1 13.3)."""

import base64
import io
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from kb import db, recordings
from kb.api import auth
from kb.api.app import build_app
from kb.assistant import suggestions
from kb.routines import KYIV
from tests.test_brief_ai import FakeLlm
from tests.test_meeting_prep import event, setup_calendar

CSRF = {"X-KB-Request": "1"}
START = datetime(2026, 10, 20, 15, 0, tzinfo=KYIV)


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


def paired(app, owner):
    code = owner.post("/api/settings/devices/pair-code", headers=CSRF).json()["code"]
    device = TestClient(app, base_url="https://os.x")
    r = device.post(
        "/api/devices/pair", json={"code": code, "name": "Roman's Mac", "platform": "macos"}
    )
    return device, r.json()["token"]


def upload_body(**extra):
    return {
        "kind": "call",
        "started_at": START.isoformat(),
        "ended_at": (START + timedelta(minutes=30)).isoformat(),
        "source": "Zoom",
        "segments": [
            {
                "speaker": "Roman",
                "is_owner": True,
                "start": 2,
                "end": 9,
                "text": "Let's agree on the prices.",
            },
            {
                "speaker": "Олена",
                "is_owner": False,
                "start": 10,
                "end": 20,
                "text": "I will update the listings by Friday.",
            },
        ],
        **extra,
    }


def test_pairing_code_single_use_and_expires(app, owner, conn):
    code = owner.post("/api/settings/devices/pair-code", headers=CSRF).json()["code"]
    anon = TestClient(app, base_url="https://os.x")
    first = anon.post("/api/devices/pair", json={"code": code.lower(), "name": "iPhone"})
    assert first.status_code == 200 and len(first.json()["token"]) > 30
    assert anon.post("/api/devices/pair", json={"code": code, "name": "again"}).status_code == 400
    late, _ = recordings.new_pair_code(conn, datetime.now(UTC) - timedelta(minutes=11))
    assert anon.post("/api/devices/pair", json={"code": late, "name": "late"}).status_code == 400
    stored = conn.execute("SELECT token_hash FROM devices").fetchone()["token_hash"]
    assert stored != first.json()["token"]  # only a hash is kept
    assert [d["name"] for d in owner.get("/api/settings/devices").json()["devices"]] == ["iPhone"]


def test_device_token_cannot_read_kb(app, owner):
    device, token = paired(app, owner)
    bearer = {"Authorization": f"Bearer {token}"}
    for path in ("/api/today", "/api/search?q=x", "/api/recordings", "/api/settings/devices"):
        assert device.get(path, headers=bearer).status_code == 401
    assert device.post("/api/devices/recordings", json=upload_body()).status_code == 401  # no token


def test_recording_matched_to_overlapping_event(app, owner, conn):
    cal = setup_calendar(conn)
    eid = event(conn, cal, START, "Quokka sync")
    device, token = paired(app, owner)
    body = upload_body(started_at=(START + timedelta(minutes=2)).isoformat())
    rid = device.post(
        "/api/devices/recordings", json=body, headers={"Authorization": f"Bearer {token}"}
    ).json()["recording_id"]
    rec = owner.get(f"/api/recordings/{rid}").json()
    assert rec["event_id"] == eid and rec["title"] == "Quokka sync" and rec["scopes"] == ["rdim"]
    item = conn.execute(
        "SELECT kind, raw_text, locator FROM items WHERE id = %s", (rec["item_id"],)
    ).fetchone()
    assert item["kind"] == "meeting" and "Олена: I will update the listings" in item["raw_text"]
    assert item["locator"] == f"/meetings/{eid}"
    assert owner.get(f"/api/meetings/{eid}").json()["recordings"][0]["id"] == rid


def test_unscheduled_call_created(app, owner, conn):
    device, token = paired(app, owner)
    rid = device.post(
        "/api/devices/recordings", json=upload_body(), headers={"Authorization": f"Bearer {token}"}
    ).json()["recording_id"]
    rec = owner.get(f"/api/recordings/{rid}").json()
    assert rec["event_id"] is None and rec["title"] == "Call with Олена · 2026-10-20 15:00"
    assert rec["scopes"] == ["personal"]  # the device's default mark
    assert [
        r["id"] for r in owner.get("/api/recordings?unscheduled=true").json()["recordings"]
    ] == [rid]


def test_revoked_device_refused(app, owner, conn):
    device, token = paired(app, owner)
    did = conn.execute("SELECT id FROM devices").fetchone()["id"]
    assert owner.delete(f"/api/settings/devices/{did}", headers=CSRF).status_code == 200
    r = device.post(
        "/api/devices/recordings", json=upload_body(), headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 401


def test_upload_idempotent(app, owner, conn):
    device, token = paired(app, owner)
    h = {"Authorization": f"Bearer {token}"}
    a = device.post(
        "/api/devices/recordings", json=upload_body(idempotency_key="mac-123"), headers=h
    ).json()
    b = device.post(
        "/api/devices/recordings", json=upload_body(idempotency_key="mac-123"), headers=h
    ).json()
    assert a == b and conn.execute("SELECT count(*) AS n FROM recordings").fetchone()["n"] == 1


def test_notes_import_vtt_and_docx(owner, conn):
    cal = setup_calendar(conn)
    eid = event(conn, cal, START)
    vtt = (
        "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n<v Олена>Prices stay the same</v>\n\n"
        "00:01:02.500 --> 00:01:05.000\nMax: I'll send the deck\n"
    )
    r = owner.post(
        f"/api/meetings/{eid}/notes",
        json={"file": {"filename": "call.vtt", "data": base64.b64encode(vtt.encode()).decode()}},
        headers=CSRF,
    )
    rec = owner.get(f"/api/recordings/{r.json()['recording_id']}").json()
    assert [(s["speaker"], s["text"], s["start"]) for s in rec["segments"]] == [
        ("Олена", "Prices stay the same", 1.0),
        ("Max", "I'll send the deck", 62.5),
    ]
    import docx

    d = docx.Document()
    d.add_paragraph("Decided: launch on Prom in November")
    buf = io.BytesIO()
    d.save(buf)
    r2 = owner.post(
        f"/api/meetings/{eid}/notes",
        json={
            "file": {"filename": "notes.docx", "data": base64.b64encode(buf.getvalue()).decode()}
        },
        headers=CSRF,
    )
    assert (
        "launch on Prom"
        in owner.get(f"/api/recordings/{r2.json()['recording_id']}").json()["notes"]
    )
    assert (
        owner.post(f"/api/meetings/{eid}/notes", json={"text": "  "}, headers=CSRF).status_code
        == 400
    )


def test_notes_to_loops_and_task_drafts(conn, config):
    from tests.test_assistant_requests import clickup_list

    clickup_list(conn, "L1", "Marketplaces", default=True)
    conn.execute(
        "INSERT INTO items (source_id, source_item_key, kind, title, metadata) VALUES"
        " ('clickup-1', 't1', 'clickup_task', 'x', %s)",
        (Jsonb({"assignees": ["Олена"], "assignee_emails": ["olena@quokka.example"]}),),
    )
    rid = recordings.store(
        conn, "call", START, START + timedelta(minutes=30), upload_body()["segments"]
    )
    llm = FakeLlm(
        {
            "summary": "Prices agreed; listings to be updated.",
            "decisions": ["Prices stay the same"],
            "actions": [
                {"text": "Update the listings", "owner": "Олена", "is_me": False, "due": "Friday"},
                {
                    "text": "Send the price list to the dealer",
                    "owner": "me",
                    "is_me": True,
                    "due": None,
                },
            ],
        }
    )
    assert recordings.process_due(conn, config, llm, START + timedelta(hours=1)) == 1
    [task] = suggestions.listing(conn)
    p = task["payload"]
    assert task["kind"] == "task" and p["assignee_emails"] == ["olena@quokka.example"]
    assert p["due_date"] == "2026-10-23" and p["list_id"] == "L1"  # the Friday after the meeting
    loop = conn.execute("SELECT kind, title, due_date, item_id FROM loops").fetchone()
    assert loop["kind"] == "i_owe" and loop["title"] == "Send the price list to the dealer"
    rec = conn.execute("SELECT result, item_id FROM recordings WHERE id = %s", (rid,)).fetchone()
    assert loop["item_id"] == rec["item_id"] and rec["result"]["decisions"] == [
        "Prices stay the same"
    ]
    assert "(OWNER)" in llm.calls[0]["text"]
    assert (
        conn.execute("SELECT summary FROM items WHERE id = %s", (rec["item_id"],))
        .fetchone()["summary"]
        .startswith("Prices agreed")
    )
    assert recordings.process_due(conn, config, llm, START + timedelta(hours=2)) == 0  # once
