"""What the server offers paired recorder devices (mac-recorder-v1 device-api spec)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from kb import db, distill, settings_store
from kb.api import auth
from kb.api.app import build_app
from tests.test_brief_ai import FakeLlm
from tests.test_dictation import SPOKEN, FakeTranscriber, structured
from tests.test_recordings import paired

CSRF = {"X-KB-Request": "1"}
AUDIO = b"\x00\x00\x00\x18ftypM4A dictation"


@pytest.fixture(autouse=True)
def audio_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_DICTATION_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def app(conn, pg_url, config):
    a = build_app(
        None,
        connect=lambda: db.connect(pg_url),
        rp=auth.RelyingParty("https://os.x"),
        config=config,
    )
    a.state.transcriber = FakeTranscriber()
    a.state.dictation_llm = FakeLlm(structured([]))
    return a


@pytest.fixture
def owner(app, conn):
    c = TestClient(app, base_url="https://os.x")
    c.cookies.set(auth.SESSION_COOKIE, auth.create_session(conn, "t", datetime.now(UTC)))
    return c


@pytest.fixture
def device(app, owner):
    client, token = paired(app, owner)
    return client, {"Authorization": f"Bearer {token}", "Content-Type": "audio/mp4"}


def dictate(device, form="verbatim", seconds=8):
    client, headers = device
    return client.post(
        f"/api/devices/dictations?form={form}&seconds={seconds}", content=AUDIO, headers=headers
    )


def test_device_dictation_forms(device, owner, conn):
    r = dictate(device)
    assert r.status_code == 200 and r.json()["text"] == SPOKEN
    s = dictate(device, "structured").json()
    assert s["text"].startswith("Домовленості з Максом")
    rows = conn.execute(
        "SELECT device_id, status, transcript FROM dictations ORDER BY id"
    ).fetchall()
    assert all(r["device_id"] is not None and r["status"] == "done" for r in rows)
    history = owner.get("/api/dictations").json()["dictations"]
    assert len(history) == 2  # listed in the web OS history
    costs = conn.execute("SELECT kind, provider, seconds FROM transcription_costs").fetchall()
    assert [(c["kind"], c["provider"], float(c["seconds"])) for c in costs] == [
        ("dictation", "openai", 8.0),
        ("dictation", "openai", 8.0),
    ]
    assert distill.month_spend_usd(conn) > 0  # transcription counts towards the AI budget


def test_device_dictation_over_budget_returns_verbatim(device, conn):
    settings_store.save(conn, {"ai_budget_usd": 0})
    r = dictate(device, "clean").json()
    assert r["text"] == SPOKEN and "budget" in r["note"]


def test_device_dictation_audio_not_kept(device, app, audio_dir):
    assert dictate(device).status_code == 200
    assert [p for p in Path(audio_dir).iterdir()] == []
    app.state.transcriber = FakeTranscriber(error=RuntimeError("OpenAI down"))
    r = dictate(device)
    assert r.status_code == 422 and "OpenAI down" in r.json()["detail"]
    assert [p for p in Path(audio_dir).iterdir()] == []  # the Mac typed its own version


def test_device_token_still_cannot_read_kb(device, app):
    client, headers = device
    bearer = {"Authorization": headers["Authorization"]}
    for path in ("/api/dictations", "/api/dictations/1", "/api/today"):
        assert client.get(path, headers=bearer).status_code == 401
    anon = TestClient(app, base_url="https://os.x")
    r = anon.post("/api/devices/dictations", content=AUDIO, headers={"Content-Type": "audio/mp4"})
    assert r.status_code == 401


# --- cloud transcription of uploaded tracks (1.2) -------------------------------------------------

from datetime import timedelta  # noqa: E402

from kb import transcription  # noqa: E402
from tests.test_audio import AUDIO as TRACK_AUDIO  # noqa: E402
from tests.test_audio import announce, put  # noqa: E402
from tests.test_recordings import START, upload_body  # noqa: E402


class FakeApi:
    def __init__(self):
        self.calls = []

    def segments(self, provider, path):
        self.calls.append((provider.name, Path(path).name))
        if "owner" in Path(path).name:
            return [{"start": 1.0, "end": 3.0, "text": "Let's agree on prices", "speaker": None}]
        if provider.name == "openai-diarize":
            return [
                {"start": 4.0, "end": 6.0, "text": "Five percent", "speaker": "A"},
                {"start": 7.0, "end": 8.0, "text": "Agreed", "speaker": "B"},
            ]
        return [{"start": 4.0, "end": 6.0, "text": "Five percent works", "speaker": None}]


@pytest.fixture
def uploaded(app, owner, tmp_path, monkeypatch):
    monkeypatch.setenv("KB_AUDIO_DIR", str(tmp_path / "audio"))
    client, token = paired(app, owner)
    h = {"Authorization": f"Bearer {token}"}
    rid = client.post("/api/devices/recordings", json=upload_body(), headers=h).json()[
        "recording_id"
    ]
    for track in ("owner", "others"):
        announce(client, h, rid, track)
        put(client, h, rid, 0, TRACK_AUDIO, track)
    return client, h, rid


def test_cloud_transcription_replaces_segments_and_records_cost(uploaded, conn):
    client, h, rid = uploaded
    est = client.post(
        f"/api/devices/recordings/{rid}/transcribe", json={"dry_run": True}, headers=h
    ).json()
    assert est["provider"] == "openai-diarize" and est["estimated_usd"] == pytest.approx(
        0.36, abs=0.01
    )
    r = client.post(f"/api/devices/recordings/{rid}/transcribe", json={}, headers=h)
    assert r.status_code == 200
    conn.execute("UPDATE recordings SET processed_at = now(), result = '{}'::jsonb")
    api = FakeApi()
    assert transcription.run_jobs(conn, START + timedelta(hours=1), api) == 1
    rec = conn.execute("SELECT segments, processed_at, result FROM recordings").fetchone()
    assert [(s["speaker"], s["text"]) for s in rec["segments"]] == [
        ("me", "Let's agree on prices"),
        ("others A", "Five percent"),
        ("others B", "Agreed"),
    ]
    assert rec["processed_at"] is None and rec["result"] is None  # processed again
    costs = conn.execute("SELECT kind, provider, usd FROM transcription_costs").fetchall()
    assert {c["kind"] for c in costs} == {"call"} and len(costs) == 2
    job = conn.execute("SELECT status, usd FROM transcription_jobs").fetchone()
    assert job["status"] == "done" and float(job["usd"]) > 0


def test_groq_provider_uses_openai_compatible_endpoint(uploaded, conn, monkeypatch):
    client, h, rid = uploaded
    settings_store.save(conn, {"calls_provider": "groq"})
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    r = client.post(f"/api/devices/recordings/{rid}/transcribe", json={}, headers=h)
    assert r.status_code == 400 and "not configured" in r.json()["detail"]
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    assert (
        client.post(f"/api/devices/recordings/{rid}/transcribe", json={}, headers=h).status_code
        == 200
    )
    seen: dict[str, object] = {}

    class FakeTranscriptions:
        def create(self, model, file, **kw):
            seen.update(model=model, **kw)

            class R:
                def model_dump(self):
                    return {"segments": [{"start": 0, "end": 1, "text": " hi "}]}

            return R()

    class FakeOpenAI:
        def __init__(self, api_key=None, base_url=None):
            seen.update(api_key=api_key, base_url=base_url)
            self.audio = type("A", (), {"transcriptions": FakeTranscriptions()})()

    import openai

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    transcription.run_jobs(conn, START + timedelta(hours=1))
    assert seen["base_url"] == transcription.GROQ_BASE_URL and seen["api_key"] == "gsk_test"
    assert seen["model"] == "whisper-large-v3-turbo" and seen["response_format"] == "verbose_json"


def test_speakers_use_diarize_for_others_track(uploaded, conn):
    client, h, rid = uploaded
    conn.execute(
        "UPDATE recordings SET segments = %s",
        (
            Jsonb(
                [{"speaker": "Roman", "is_owner": True, "start": 0.5, "end": 2, "text": "local me"}]
            ),
        ),
    )
    client.post(f"/api/devices/recordings/{rid}/transcribe", json={"speakers": True}, headers=h)
    api = FakeApi()
    transcription.run_jobs(conn, START + timedelta(hours=1), api)
    assert api.calls == [("openai-diarize", f"{rid}-others.ogg")]  # "me" is not re-done
    segs = conn.execute("SELECT segments FROM recordings").fetchone()["segments"]
    assert segs[0]["text"] == "local me" and segs[1]["speaker"] == "others A"


def test_transcribe_refuses_other_devices_and_missing_audio(app, owner, uploaded, conn):
    _client, _h, rid = uploaded
    other, token = paired(app, owner)
    oh = {"Authorization": f"Bearer {token}"}
    assert (
        other.post(f"/api/devices/recordings/{rid}/transcribe", json={}, headers=oh).status_code
        == 404
    )
    rid2 = other.post(
        "/api/devices/recordings", json=upload_body(idempotency_key="x2"), headers=oh
    ).json()["recording_id"]
    r = other.post(f"/api/devices/recordings/{rid2}/transcribe", json={}, headers=oh)
    assert r.status_code == 400 and "upload the audio first" in r.json()["detail"]


def test_month_spend_includes_transcription(conn):
    from datetime import date

    before = distill.month_spend_usd(conn, date(2026, 10, 20))
    transcription.record_cost(
        conn, "call", "groq", "whisper-large-v3-turbo", 3600, 0.04, date(2026, 10, 5)
    )
    transcription.record_cost(
        conn, "call", "groq", "whisper-large-v3-turbo", 3600, 0.04, date(2026, 9, 30)
    )
    assert distill.month_spend_usd(conn, date(2026, 10, 20)) == pytest.approx(before + 0.04)
    assert transcription.month_by_kind(conn, date(2026, 10, 20)) == {"dictation": 0.0, "call": 0.04}


# --- meetings around now, linking, meetings outside the calendar (1.3, 1.4) -----------------------

from kb import meetings  # noqa: E402
from tests.test_meeting_prep import event, setup_calendar  # noqa: E402


@pytest.fixture
def mac(app, owner):
    client, token = paired(app, owner)
    return client, {"Authorization": f"Bearer {token}"}


def test_device_meetings_minimal_fields(mac, conn):
    client, h = mac
    cal = setup_calendar(conn)
    now = datetime.now(UTC)
    current = event(conn, cal, now - timedelta(minutes=5), "Quokka sync")
    event(conn, cal, now + timedelta(hours=2), "Dealer call")
    event(conn, cal, now + timedelta(days=2), "Far away")
    got = client.get("/api/devices/meetings", headers=h).json()["meetings"]
    assert [m["title"] for m in got] == ["Quokka sync", "Dealer call"]
    assert got[0]["in_progress"] is True and got[0]["id"] == current
    assert set(got[0]) == {"id", "title", "start", "end", "in_progress"}  # no attendees, prep…


def test_device_token_reads_only_meetings(mac, conn):
    client, h = mac
    cal = setup_calendar(conn)
    eid = event(conn, cal, datetime.now(UTC), "Quokka sync")
    for path in (f"/api/meetings/{eid}", "/api/meetings", "/api/recordings", "/api/people"):
        assert client.get(path, headers=h).status_code == 401


def test_chosen_meeting_wins_over_time_match(mac, conn):
    client, h = mac
    cal = setup_calendar(conn)
    other = event(conn, cal, START, "Overlapping by time")
    chosen = event(conn, cal, START - timedelta(hours=3), "Picked by the owner")
    rid = client.post(
        "/api/devices/recordings", json=upload_body(event_id=chosen), headers=h
    ).json()["recording_id"]
    rec = conn.execute("SELECT event_id, title FROM recordings WHERE id = %s", (rid,)).fetchone()
    assert rec["event_id"] == chosen != other and rec["title"] == "Picked by the owner"


def test_relink_moves_recording_and_reprocesses(mac, owner, conn):
    client, h = mac
    cal = setup_calendar(conn)
    first = event(conn, cal, START, "Wrong meeting")
    right = event(conn, cal, START - timedelta(days=1), "Dealer call")
    rid = client.post("/api/devices/recordings", json=upload_body(), headers=h).json()[
        "recording_id"
    ]
    rec = conn.execute("SELECT event_id, item_id FROM recordings WHERE id = %s", (rid,)).fetchone()
    assert rec["event_id"] == first
    conn.execute("UPDATE recordings SET processed_at = now(), result = '{}'::jsonb")
    stale = conn.execute(
        "INSERT INTO suggestions (kind, payload) VALUES ('task', %s) RETURNING id",
        (Jsonb({"name": "old", "source_item_id": rec["item_id"]}),),
    ).fetchone()["id"]
    r = owner.post(f"/api/recordings/{rid}/link", json={"event_id": right}, headers=CSRF)
    assert r.json()["event_id"] == right and r.json()["title"] == "Dealer call"
    after = conn.execute("SELECT processed_at, result FROM recordings").fetchone()
    assert after["processed_at"] is None and after["result"] is None
    item = conn.execute(
        "SELECT locator, title FROM items WHERE id = %s", (rec["item_id"],)
    ).fetchone()
    assert item["locator"] == f"/meetings/{right}" and item["title"] == "Dealer call"
    assert (
        conn.execute("SELECT status FROM suggestions WHERE id = %s", (stale,)).fetchone()["status"]
        == "discarded"
    )
    # detach, then mark the project of the call without a meeting
    client.post(f"/api/devices/recordings/{rid}/link", json={"event_id": None}, headers=h)
    client.post(f"/api/devices/recordings/{rid}/link", json={"scope": "rdim"}, headers=h)
    rec = conn.execute("SELECT event_id, scopes FROM recordings").fetchone()
    assert rec["event_id"] is None and rec["scopes"] == ["rdim"]


def test_link_refuses_other_devices(app, owner, mac, conn):
    client, h = mac
    rid = client.post("/api/devices/recordings", json=upload_body(), headers=h).json()[
        "recording_id"
    ]
    other, token = paired(app, owner)
    r = other.post(
        f"/api/devices/recordings/{rid}/link",
        json={"scope": "rdim"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


def test_device_creates_meeting_with_participants(mac, conn):
    from kb import people

    client, h = mac
    pid = people.register(conn, [people.email_key("oleh@shop.example")], "Oleh Kovalenko")
    body = upload_body(
        new_meeting={
            "title": "Dealer — October prices",
            "scope": "quokka",
            "participants": ["Oleh", "max@quokka.example"],
        }
    )
    rid = client.post("/api/devices/recordings", json=body, headers=h).json()["recording_id"]
    rec = conn.execute(
        "SELECT event_id, title, scopes FROM recordings WHERE id = %s", (rid,)
    ).fetchone()
    assert rec["title"] == "Dealer — October prices" and rec["scopes"] == ["quokka"]
    m = meetings.get(conn, rec["event_id"])
    assert m is not None and m["local"] is True and m["scopes"] == ["quokka"]
    assert [(a["name"], a["person_id"]) for a in m["attendees"]] == [
        ("Oleh Kovalenko", pid),
        ("max@quokka.example", None),
    ]
    assert m["attendees"][0]["email"] == "oleh@shop.example"


def test_unscheduled_call_made_a_meeting_and_reprocessed(mac, owner, conn):
    client, h = mac
    rid = client.post("/api/devices/recordings", json=upload_body(), headers=h).json()[
        "recording_id"
    ]
    assert conn.execute("SELECT event_id FROM recordings").fetchone()["event_id"] is None
    r = owner.post(
        f"/api/recordings/{rid}/link",
        json={"new_meeting": {"title": "Spontaneous with Olena", "scope": "quokka"}},
        headers=CSRF,
    )
    eid = r.json()["event_id"]
    assert eid and owner.get(f"/api/meetings/{eid}").json()["recordings"][0]["id"] == rid
    # editing the created meeting renames the recording too
    assert (
        owner.patch(
            f"/api/meetings/{eid}", json={"title": "Olena — listings"}, headers=CSRF
        ).status_code
        == 200
    )
    assert conn.execute("SELECT title FROM recordings").fetchone()["title"] == "Olena — listings"
    created = owner.post(
        "/api/meetings",
        json={
            "title": "Coffee with Max",
            "scope": "personal",
            "start": START.isoformat(),
            "end": (START + timedelta(hours=1)).isoformat(),
        },
        headers=CSRF,
    ).json()["id"]
    assert owner.get(f"/api/meetings/{created}").json()["local"] is True


def test_local_meetings_not_synced_or_written_to_connected_calendars(mac, owner, conn):
    from kb.connectors import calendar

    cal = setup_calendar(conn)
    google = event(conn, cal, START, "From Google")
    r = owner.patch(f"/api/meetings/{google}", json={"title": "x"}, headers=CSRF)
    assert r.status_code == 400 and "read-only" in r.json()["detail"]
    meetings.local_calendar(conn)
    conn.execute("UPDATE calendars SET synced_at = NULL")
    calendar.sync_due(
        conn, datetime.now(UTC), set(), transport=None
    )  # ical "x" fails, local skipped
    errors = {r["name"]: r["error"] for r in conn.execute("SELECT name, error FROM calendars")}
    assert errors["Second brain"] is None


def test_event_scope_override(conn):
    cal = setup_calendar(conn)  # calendar marked rdim
    eid = event(conn, cal, START, "Sync")
    conn.execute("UPDATE events SET scopes = '{quokka}' WHERE id = %s", (eid,))
    m = meetings.get(conn, eid)
    assert m is not None and m["scopes"] == ["quokka"]


def test_status_recording_coverage_and_spend(owner, mac, conn):
    from datetime import date

    from tests.test_meeting_prep import event, setup_calendar

    client, h = mac
    cal = setup_calendar(conn)
    now = datetime.now(UTC)
    recorded = event(conn, cal, now - timedelta(hours=3), "Recorded sync")
    event(conn, cal, now - timedelta(hours=5), "Missed call")
    event(
        conn,
        cal,
        now - timedelta(hours=6),
        "Solo focus",
        attendees=[{"email": "me@example.com", "status": "ACCEPTED"}],
    )
    body = upload_body(event_id=recorded)
    client.post("/api/devices/recordings", json=body, headers=h)
    transcription.record_cost(
        conn, "dictation", "openai", "gpt-transcribe", 60, 0.0045, date.today()
    )
    st = owner.get("/api/status").json()["recording"]
    assert st["meetings"] == 2 and st["recorded"] == 1  # the solo event does not count
    assert st["transcription_usd"]["dictation"] == pytest.approx(0.0045)
