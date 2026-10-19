"""Dictation (voice-dictation spec; assistant-command-v1 tasks 4.1-4.2)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kb import db, dictation
from kb.api import auth
from kb.api.app import build_app
from tests.test_brief_ai import FakeLlm

NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
CSRF = {"X-KB-Request": "1"}
SPOKEN = (
    "Отже, значить, так, ми з Максом домовились, що банери для Rozetka оновимо до пʼятниці, "
    "проте ціни на Prom поки не чіпаємо, оскільки, власне, чекаємо відповідь від постачальника"
)


class FakeTranscriber:
    def __init__(self, text=SPOKEN, error=None):
        self.text, self.error, self.calls = text, error, []

    def transcribe(self, path, model):
        self.calls.append((Path(path).exists(), model))
        if self.error:
            raise self.error
        return self.text


@pytest.fixture(autouse=True)
def audio_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_DICTATION_DIR", str(tmp_path))
    return tmp_path


def upload(conn, data=b"\x1aE\xdf\xa3webm", mime="audio/webm;codecs=opus", seconds=42):
    return dictation.store_upload(conn, data, mime, seconds)


def row(conn, did):
    return conn.execute("SELECT * FROM dictations WHERE id = %s", (did,)).fetchone()


def test_audio_deleted_after_transcript(conn, config, audio_dir):
    did = upload(conn)
    path = Path(row(conn, did)["audio_path"])
    assert path.exists() and path.parent == audio_dir and path.suffix == ".webm"
    t = FakeTranscriber()
    dictation.transcribe(conn, config, t, did, NOW)
    r = row(conn, did)
    assert t.calls == [(True, "gpt-transcribe")]
    assert r["status"] == "done" and r["transcript"] == SPOKEN and r["audio_path"] is None
    assert not path.exists() and list(audio_dir.iterdir()) == []
    assert float(r["cost_usd"]) == pytest.approx(42 / 60 * 0.006)


def test_transcript_redacted(conn, config):
    did = upload(conn)
    secret = "sk-proj-" + "A1b2C3d4E5f6G7h8I9j0" * 3
    dictation.transcribe(conn, config, FakeTranscriber(f"the key is {secret} ok"), did, NOW)
    assert secret not in row(conn, did)["transcript"]


def test_failed_transcription_retried_then_deleted(conn, config):
    did = upload(conn)
    path = Path(row(conn, did)["audio_path"])
    dictation.transcribe(conn, config, FakeTranscriber(error=RuntimeError("timeout")), did, NOW)
    assert row(conn, did)["status"] == "failed" and path.exists()  # kept for retries
    # retried after 10 minutes, not before
    t = FakeTranscriber()
    assert dictation.maintain(conn, config, t, NOW + timedelta(minutes=5)) == 0
    conn.execute("UPDATE dictations SET created_at = %s", (NOW,))
    assert dictation.maintain(conn, config, t, NOW + timedelta(minutes=11)) == 1
    assert row(conn, did)["status"] == "done" and not path.exists()
    # a failure that never recovers: audio deleted after 7 days
    other = upload(conn)
    other_path = Path(row(conn, other)["audio_path"])
    conn.execute("UPDATE dictations SET created_at = %s WHERE id = %s", (NOW, other))
    dictation.transcribe(conn, config, FakeTranscriber(error=RuntimeError("bad")), other, NOW)
    dictation.maintain(conn, config, None, NOW + timedelta(days=8))
    assert not other_path.exists() and row(conn, other)["audio_path"] is None


def test_upload_rejects_bad_input(conn):
    with pytest.raises(dictation.DictationError, match="unsupported"):
        upload(conn, mime="video/mp4")
    with pytest.raises(dictation.DictationError, match="empty"):
        upload(conn, data=b"")


def done(conn, config, text=SPOKEN):
    did = upload(conn)
    dictation.transcribe(conn, config, FakeTranscriber(text), did, NOW)
    return did


def test_clean_keeps_wording_or_falls_back(conn, config):
    did = done(conn, config)
    good = (
        "Ми з Максом домовились, що банери для Rozetka оновимо до пʼятниці, проте ціни на Prom "
        "поки не чіпаємо, оскільки чекаємо відповідь від постачальника."
    )
    llm = FakeLlm({"text": good})
    assert dictation.render(conn, config, llm, did, "clean", NOW) == {"text": good}
    dictation.render(conn, config, llm, did, "clean", NOW)
    assert len(llm.calls) == 1  # cached
    other = done(conn, config)
    reworded = FakeLlm({"text": "Банери оновлюємо в пʼятницю."})
    out = dictation.render(conn, config, reworded, other, "clean", NOW)
    assert out["text"] == SPOKEN and "verbatim" in out["note"]


def structured(actions):
    return {
        "summary": "Домовленості з Максом щодо Rozetka та Prom.",
        "sections": [{"heading": "Rozetka", "bullets": ["Оновити банери"]}],
        "decisions": ["Ціни на Prom не змінюємо"],
        "actions": actions,
    }


def test_structured_drops_invented_due_dates(conn, config):
    did = done(conn, config)
    llm = FakeLlm(
        structured(
            [
                {"text": "Оновити банери Rozetka", "owner": "Макс", "due": "пʼятниці"},
                {"text": "Чекати відповідь постачальника", "owner": None, "due": "2026-10-25"},
            ]
        )
    )
    out = dictation.render(conn, config, llm, did, "structured", NOW)
    assert [a["due"] for a in out["actions"]] == ["пʼятниці", None]
    assert out["text"].startswith("Домовленості з Максом")
    assert "## Decisions" in out["text"] and "(Макс, пʼятниці)" in out["text"]
    assert llm.calls[0]["model"] == "gpt-6.1-sol"


def test_mixed_language_kept(conn, config):
    did = done(conn, config)
    llm = FakeLlm(structured([]))
    dictation.render(conn, config, llm, did, "structured", NOW)
    call = llm.calls[0]
    assert call["text"] == SPOKEN  # Ukrainian with English names goes in untouched
    assert "main language" in call["system"] and "never invent" in call["system"]


@pytest.fixture
def client(conn, pg_url, config):
    app = build_app(
        None,
        connect=lambda: db.connect(pg_url),
        rp=auth.RelyingParty("https://os.x"),
        config=config,
    )
    app.state.assistant_submit = lambda job: job()
    app.state.transcriber = FakeTranscriber()
    app.state.dictation_llm = FakeLlm(structured([]))
    c = TestClient(app, base_url="https://os.x")
    c.cookies.set(auth.SESSION_COOKIE, auth.create_session(conn, "t", datetime.now(UTC)))
    return c


def test_dictation_saved_as_note(client, conn):
    r = client.post(
        "/api/dictations?seconds=12.5",
        content=b"\x00\x00\x00\x18ftypM4A ",
        headers={**CSRF, "Content-Type": "audio/mp4"},
    )
    did = r.json()["id"]
    got = client.get(f"/api/dictations/{did}").json()
    assert got["status"] == "done" and got["transcript"] == SPOKEN and got["seconds"] == 12.5
    form = client.post(
        f"/api/dictations/{did}/render", json={"form": "structured"}, headers=CSRF
    ).json()
    assert form["summary"].startswith("Домовленості")
    doc = client.post(
        f"/api/dictations/{did}/save", json={"form": "structured", "scope": "quokka"}, headers=CSRF
    ).json()
    d = conn.execute(
        "SELECT kind, scopes, title FROM documents WHERE id = %s", (doc["document_id"],)
    ).fetchone()
    assert d["kind"] == "note" and d["scopes"] == ["quokka"] and d["title"].startswith("Dictation ")
    [listed] = client.get("/api/dictations").json()["dictations"]
    assert listed["saved_doc_id"] == doc["document_id"] and listed["first_line"].startswith(
        "Отже, значить"
    )
    assert (
        client.post(
            "/api/dictations", content=b"", headers={**CSRF, "Content-Type": "audio/mp4"}
        ).status_code
        == 400
    )
