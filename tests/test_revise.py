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


def seo_tasks(conn):
    return [
        suggestions.propose(
            conn,
            "task",
            {"list_id": "L1", "name": n, "description": d, "assignee_name": "Kate Oleksyuk",
             "assignee_emails": [], "due_date": due, "source_item_id": 77},
            reason="From the meeting “Weekly Kate”",
            refs=["item:77"],
            scopes=["quokka"],
            item_id=77,
        )
        for n, d, due in [
            ("SEO: titles for puzzles", "Rewrite 40 titles", "2026-11-07"),
            ("SEO: descriptions", "Add keywords to descriptions", "2026-11-05"),
            ("SEO: alt texts", "Alt texts for images", None),
        ]
    ]  # fmt: skip


def test_merge_three_proposals_into_one(conn, config):
    ids = seo_tasks(conn)
    llm = FakeLlm(
        {
            "name": "SEO optimisation of puzzle listings",
            "description": "- Rewrite 40 titles\n- Keywords in descriptions\n- Alt texts",
            "assignee": "Kate Oleksyuk",
            "due": "2026-11-05",
        }
    )
    s = revise.merge(conn, config, llm, ids, "one SEO task for Kate", NOW)
    p = s["payload"]
    assert s["kind"] == "task" and s["status"] == "proposed"
    assert p["name"] == "SEO optimisation of puzzle listings" and p["merged_from"] == ids
    assert p["list_id"] == "L1" and p["source_item_id"] == 77 and p["due_date"] == "2026-11-05"
    assert s["reason"] == "From the meeting “Weekly Kate”" and s["refs"] == ["item:77"]
    old = conn.execute("SELECT status, discard_reason FROM suggestions WHERE id = ANY(%s)", (ids,))
    assert {(r["status"], r["discard_reason"]) for r in old} == {
        ("discarded", f"merged into proposal {s['id']}")
    }
    assert "Rewrite 40 titles" in llm.calls[0]["text"]


def test_merge_needs_two_open_task_proposals(conn, config):
    ids = seo_tasks(conn)
    llm = FakeLlm({})
    import pytest

    with pytest.raises(suggestions.SuggestionError, match="at least two"):
        revise.merge(conn, config, llm, ids[:1], "", NOW)
    comment = suggestions.propose(conn, "clickup_comment", {"body": "x"}, reason="r")
    with pytest.raises(suggestions.SuggestionError, match="only task"):
        revise.merge(conn, config, llm, [ids[0], comment], "", NOW)


def test_assistant_finds_and_merges_proposals(conn, config, monkeypatch):
    from kb.assistant import actions, agent

    ids = seo_tasks(conn)
    run = agent.Run(conn, 0, None, now=NOW, config=config)
    monkeypatch.setattr(run, "step", lambda tool, summary: None)
    monkeypatch.setattr(run, "record", lambda entry: None)
    found = actions.proposals(run, "Weekly Kate")
    assert {f["proposal_id"] for f in found} == set(ids)
    assert found[0]["task"].startswith("SEO")
    llm = FakeLlm(
        {
            "name": "SEO optimisation",
            "description": "- all three",
            "assignee": "Kate Oleksyuk",
            "due": "",
        }
    )
    monkeypatch.setattr(actions, "_structured_llm", lambda run: llm)
    out = actions.merge_proposals(run, ids, None)
    assert out["merged_into"]["task"] == "SEO optimisation"
    assert "proposals" in {t["name"] for t in agent.TOOLS}
    assert "`proposals`" in agent.SYSTEM
