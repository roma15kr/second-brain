"""Changing proposals before they are created (assistant-moderation-v1)."""

from datetime import UTC, date, datetime, timedelta

from psycopg.types.json import Jsonb

from kb.assistant import revise, suggestions
from tests.test_brief_ai import FakeLlm
from tests.test_email_drafts import web_client

H = {"X-KB-Request": "1"}
NOW = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)  # a Tuesday


def task(conn):
    conn.execute(
        "INSERT INTO items (source_id, source_item_key, kind, title, metadata) VALUES"
        " ('clickup-1', 'k', 'clickup_task', 'x', %s)",
        (Jsonb({"assignees": ["Kate Oleksyuk"], "assignee_emails": ["kate@adducates.com"]}),),
    )
    return suggestions.propose(
        conn,
        "task",
        {
            "list_id": "L1",
            "name": "Update the bundle page with the new buy box and the new photos",
            "description": "From the meeting “Weekly Nastya”",
            "assignee_name": "Anastasiya Tarasova",
            "assignee_emails": [],
            "due_date": "2026-11-06",
        },
        reason="From the meeting “Weekly Nastya”",
    )


def test_revise_task_by_instruction(conn, config):
    sid = task(conn)
    llm = FakeLlm(
        {
            "name": "Update the bundle page",
            "description": "From the meeting “Weekly Nastya”",
            "assignee": "Kate",
            "due": "Monday",
        }
    )
    s = revise.revise(conn, config, llm, sid, "shorter, assign to Kate, due Monday", NOW)
    p = s["payload"]
    assert p["name"] == "Update the bundle page"
    assert p["assignee_name"] == "Kate Oleksyuk" and p["assignee_emails"] == ["kate@adducates.com"]
    assert p["due_date"] == (date(2026, 11, 9)).isoformat()  # the next Monday
    assert p["revisions"][0]["instruction"] == "shorter, assign to Kate, due Monday"
    assert s["status"] == "proposed" and s["edited"]  # still waiting for approval
    assert "INSTRUCTION: shorter, assign to Kate" in llm.calls[0]["text"]
    assert "TEAM: Anastasiya Tarasova" in llm.calls[0]["text"]


def test_unchanged_fields_keep_their_values(conn, config):
    sid = task(conn)
    llm = FakeLlm(
        {
            "name": "Update the bundle page with the new buy box and the new photos",
            "description": "Photos from the shoot on Thursday",
            "assignee": "Anastasiya Tarasova",
            "due": "2026-11-06",
        }
    )
    p = revise.revise(conn, config, llm, sid, "add that photos come from Thursday", NOW)["payload"]
    assert p["description"] == "Photos from the shoot on Thursday"
    assert p["due_date"] == "2026-11-06" and p["assignee_name"] == "Anastasiya Tarasova"


def test_owner_edit_used_on_create(conn, pg_url, config):
    sid = suggestions.propose(
        conn,
        "clickup_comment",
        {"task_id": "t1", "body": "AI words", "item_id": None},
        reason="From the meeting",
    )
    client = web_client(conn, pg_url, config)
    r = client.patch(
        f"/api/suggestions/{sid}", json={"fields": {"body": "My own words"}}, headers=H
    )
    assert r.status_code == 200 and r.json()["suggestion"]["payload"]["body"] == "My own words"
    # fields the kind does not have are ignored
    client.patch(f"/api/suggestions/{sid}", json={"fields": {"list_id": "X"}}, headers=H)
    assert "list_id" not in suggestions.get(conn, sid)["payload"]
    posted = []

    class Fake:
        def comments(self, task_id):
            return []

        def create_comment(self, task_id, text, *rest):
            posted.append(text)
            return {"id": "c1"}

    client.app.state.clickup_factory = lambda conn: lambda: Fake()
    client.post(f"/api/suggestions/{sid}/approve", json={}, headers=H)
    assert posted == ["My own words"]


def test_revise_route_and_refusals(conn, pg_url, config):
    sid = task(conn)
    client = web_client(conn, pg_url, config)
    client.app.state.dictation_llm = FakeLlm(
        {"name": "Short", "description": "", "assignee": "Anastasiya Tarasova", "due": "2026-11-06"}
    )
    r = client.post(f"/api/suggestions/{sid}/revise", json={"instruction": "shorter"}, headers=H)
    assert r.status_code == 200 and r.json()["suggestion"]["payload"]["name"] == "Short"
    assert (
        client.post(
            f"/api/suggestions/{sid}/revise", json={"instruction": " "}, headers=H
        ).status_code
        == 400
    )
    suggestions.discard(conn, sid, "no", NOW + timedelta(minutes=1))
    r = client.post(f"/api/suggestions/{sid}/revise", json={"instruction": "x"}, headers=H)
    assert r.status_code == 400 and "discarded" in r.json()["detail"]
