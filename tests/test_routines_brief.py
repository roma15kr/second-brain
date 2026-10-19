from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from kb import db
from kb.api import auth
from kb.api.app import build_app
from kb.routines import KYIV, briefs, factpack

# Tuesday 20 Oct 2026, 08:00 Kyiv (UTC+3) → window since Monday 19:00 Kyiv.
NOW = datetime(2026, 10, 20, 8, 0, tzinfo=KYIV)


def add_item(conn, key, kind, scopes, at, title="t", summary=None, locator=None, hidden=False):
    return conn.execute(
        "INSERT INTO items (source_id, source_item_key, kind, scopes, title, summary, raw_text,"
        " last_activity_at, locator, hidden) VALUES ('s', %s, %s, %s, %s, %s, 'raw text', %s,"
        " %s, %s) RETURNING id",
        (key, kind, scopes, title, summary, at, locator, hidden),
    ).fetchone()["id"]


def test_morning_window_starts_at_last_evening_slot():
    start, end = factpack.morning_window(NOW)
    assert start == datetime(2026, 10, 19, 19, 0, tzinfo=KYIV) and end == NOW
    late = datetime(2026, 10, 20, 21, 0, tzinfo=KYIV)
    assert factpack.morning_window(late)[0] == datetime(2026, 10, 20, 19, 0, tzinfo=KYIV)


def test_factpack_morning_window_and_scopes(conn):
    evening = datetime(2026, 10, 19, 19, 0, tzinfo=KYIV)
    a = add_item(conn, "a", "tg_conversation", ["rdim"], evening + timedelta(hours=2))
    b = add_item(conn, "b", "email_thread", ["quokka"], evening + timedelta(hours=10))
    c = add_item(conn, "c", "tg_conversation", ["rdim", "digisoft"], evening + timedelta(hours=5))
    d = add_item(conn, "d", "email_thread", ["unsorted"], evening + timedelta(hours=1))
    add_item(conn, "old", "email_thread", ["rdim"], evening - timedelta(minutes=1))
    add_item(conn, "hidden", "email_thread", ["rdim"], evening + timedelta(hours=3), hidden=True)
    add_item(conn, "p", "passage", ["rdim"], evening + timedelta(hours=3))
    add_item(conn, "future", "email_thread", ["rdim"], NOW + timedelta(minutes=5))

    pack = factpack.build(conn, "morning", factpack.morning_window(NOW))

    assert list(pack.by_scope) == ["digisoft", "quokka", "rdim", "unsorted"]  # unsorted last
    assert [f.id for f in pack.by_scope["rdim"]] == [c, a]  # newest first
    assert [f.id for f in pack.by_scope["digisoft"]] == [c]  # multi-scope item in each
    assert [f.id for f in pack.by_scope["quokka"]] == [b]
    assert [f.id for f in pack.by_scope["unsorted"]] == [d]
    assert pack.counts == {"tg_conversation": 2, "email_thread": 2}


def test_data_only_brief_lists_scopes_with_source_links(conn):
    evening = datetime(2026, 10, 19, 19, 0, tzinfo=KYIV)
    add_item(
        conn,
        "a",
        "email_thread",
        ["quokka"],
        evening + timedelta(hours=1),
        title="Listing price",
        summary="Dealer asks about the listing price.",
        locator="https://mail.google.com/mail/#search/rfc822msgid:x",
    )
    add_item(
        conn,
        "b",
        "tg_conversation",
        ["rdim"],
        evening + timedelta(hours=2),
        locator="telegram://chat/1/2",
    )
    brief_id = briefs.run_morning(conn, NOW)
    brief = briefs.latest(conn, ["morning"])
    assert brief is not None
    assert brief["id"] == brief_id and brief["mode"] == "data"
    assert brief["headline"] == "Morning brief: 2 conversations across 2 scopes"
    quokka = next(s for s in brief["sections"] if s["title"] == "quokka")
    assert quokka["text"] == "1 email thread"
    item = quokka["items"][0]
    assert item["title"] == "Listing price" and item["link"].startswith("https://mail.google.com")
    rdim = next(s for s in brief["sections"] if s["title"] == "rdim")
    assert rdim["items"][0]["link"] is None  # only openable https links are offered


def test_quiet_night_brief(conn):
    briefs.run_morning(conn, NOW)
    brief = briefs.latest(conn, ["morning"])
    assert brief is not None
    assert brief["headline"] == "Morning brief: nothing new"
    assert [x["title"] for x in brief["sections"]] == ["Coming up", "Quiet"]


def test_api_today_returns_latest_brief(conn, pg_url):
    app = build_app(None, connect=lambda: db.connect(pg_url), rp=auth.RelyingParty("https://os.x"))
    client = TestClient(app, base_url="https://os.x")
    client.cookies.set(auth.SESSION_COOKIE, auth.create_session(conn, "t", datetime.now(UTC)))
    assert client.get("/api/today").json() == {"brief": None, "meetings": []}
    briefs.run_morning(conn, NOW)
    assert client.get("/api/today").json()["brief"]["routine"] == "morning"


def test_kb_routines_run_morning_command(conn, pg_url, monkeypatch, capsys):
    from kb import cli

    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setenv("KB_CONFIG_YAML", "sources: []")
    cli.main(["routines", "run", "morning"])
    assert "Morning brief" in capsys.readouterr().out
    assert briefs.latest(conn, ["morning"]) is not None
