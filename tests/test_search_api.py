import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from kb import db
from kb.api import auth, routes_search
from kb.api.app import build_app
from kb.mcp_server import build_app as build_mcp_app

CSRF = {"X-KB-Request": "1"}
TOKEN = "t" * 40
NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


@pytest.fixture
def client(conn, pg_url, config):
    app = build_app(
        None,
        connect=lambda: db.connect(pg_url),
        rp=auth.RelyingParty("https://os.x"),
        config=config,
    )
    c = TestClient(app, base_url="https://os.x")
    c.cookies.set(auth.SESSION_COOKIE, auth.create_session(conn, "t", datetime.now(UTC)))
    return c


def conversation(conn, key="c1", n=120, kind="tg_conversation", scopes=("rdim",)):
    item = conn.execute(
        "INSERT INTO items (source_id, source_item_key, kind, scopes, title, raw_text, summary,"
        " last_activity_at, locator) VALUES ('mail-test', %s, %s, %s, 'Epicentr launch',"
        " 'commission Epicentr twelve percent', 'Launch on Epicentr agreed', %s,"
        " 'https://t.me/c/1/1') RETURNING id",
        (key, kind, list(scopes), NOW),
    ).fetchone()["id"]
    for i in range(n):
        conn.execute(
            "INSERT INTO messages (source_id, message_key, kind, unit_key, author, sent_at, body,"
            " locator) VALUES ('mail-test', %s, 'tg', %s, 'Олена', %s, %s, %s)",
            (
                f"{key}:{i}",
                key,
                NOW - timedelta(minutes=n - i),
                f"message {i}",
                f"https://t.me/c/1/{i}",
            ),
        )
    return item


def test_brief_found_by_search(client, conn):
    conn.execute(
        "INSERT INTO briefs (routine, window_start, window_end, headline, sections, mode)"
        " VALUES ('weekly_review', now(), now(), 'Weekly review: 40 conversations', %s, 'ai')",
        (
            json.dumps(
                [{"title": "Quokka", "text": "Epicentr commission agreed at 12%", "items": []}]
            ),
        ),
    )
    data = client.get("/api/search", params={"q": "Epicentr"}).json()
    assert [b["routine"] for b in data["briefs"]] == ["weekly_review"]


def test_local_search_finds_conversation_with_filters(client, conn):
    item = conversation(conn, n=3)
    data = client.get(
        "/api/search", params={"q": "Epicentr", "kind": "chats", "scope": "rdim"}
    ).json()
    assert [r["item_id"] for r in data["results"]] == [item]
    assert (
        client.get("/api/search", params={"q": "Epicentr", "kind": "mail"}).json()["results"] == []
    )
    bad = client.get("/api/search", params={"q": "x", "scope": "acme"})
    assert bad.status_code == 400 and "valid scopes" in bad.json()["detail"]


def test_remote_searcher_calls_mcp_with_token(monkeypatch):
    seen: dict[str, object] = {}

    def fake_post(url, json, headers, timeout):
        seen.update(url=url, json=json, auth=headers["Authorization"])
        return httpx.Response(
            200, json={"results": [{"item_id": 1}]}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(routes_search.httpx, "post", fake_post)
    run = routes_search.remote_searcher("http://mcp:8765/internal/search", TOKEN)
    assert run({"query": "x"}) == [{"item_id": 1}]
    assert seen["auth"] == f"Bearer {TOKEN}" and seen["json"] == {"query": "x"}


def test_mcp_internal_search_requires_token_and_returns_json(conn, pg_url, config):
    conversation(conn, n=2)
    mcp = TestClient(build_mcp_app(lambda: db.connect(pg_url), TOKEN, config))
    assert mcp.post("/internal/search", json={"query": "Epicentr"}).status_code == 401
    r = mcp.post(
        "/internal/search", json={"query": "Epicentr"}, headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert r.status_code == 200 and r.json()["results"][0]["title"] == "Epicentr launch"
    bad = mcp.post(
        "/internal/search",
        json={"query": "x", "scopes": ["acme"]},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert bad.status_code == 400


def test_conversation_opens_on_matched_message_page(client, conn):
    item = conversation(conn, n=120)
    conn.execute(
        "INSERT INTO loops (kind, title, item_id) VALUES ('owed_to_me', 'Customs documents', %s)",
        (item,),
    )
    first = client.get(f"/api/items/{item}").json()
    assert first["total"] == 120 and len(first["messages"]) == 50 and first["next_offset"] == 50
    assert first["loops"][0]["title"] == "Customs documents"
    page = client.get(f"/api/items/{item}", params={"around": "https://t.me/c/1/75"}).json()
    assert page["offset"] == 50
    assert any(m["locator"] == "https://t.me/c/1/75" for m in page["messages"])
    assert client.get("/api/items/999999").status_code == 404


def test_scope_change_on_conversation(client, conn):
    item = conversation(conn, n=1)
    r = client.post(f"/api/items/{item}/scope", json={"scope": "quokka"}, headers=CSRF)
    assert r.status_code == 200
    assert conn.execute("SELECT scopes FROM items WHERE id = %s", (item,)).fetchone()["scopes"] == [
        "quokka"
    ]
    assert (
        client.post(f"/api/items/{item}/scope", json={"scope": "acme"}, headers=CSRF).status_code
        == 400
    )
