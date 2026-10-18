from datetime import datetime, timedelta

from kb import push
from kb.config import Config, LlmConfig
from kb.distill import Usage, record_usage
from kb.routines import KYIV, triage
from tests.test_brief_ai import FakeLlm

NOW = datetime(2026, 10, 20, 11, 0, tzinfo=KYIV)


def mail(conn, key, author, subject, body, at, summary=None):
    item = conn.execute(
        "INSERT INTO items (source_id, source_item_key, kind, scopes, title, summary, raw_text,"
        " last_activity_at, locator) VALUES ('mail-test', %s, 'email_thread', '{quokka}', %s,"
        " %s, %s, %s, 'https://mail.google.com/x') RETURNING id",
        (key, subject, summary, body, at),
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO messages (source_id, message_key, kind, unit_key, author, sent_at, body,"
        " subject) VALUES ('mail-test', %s, 'email', %s, %s, %s, %s, %s)",
        (key + "-m", key, author, at, body, subject),
    )
    return item


class TriageLlm(FakeLlm):
    """Classifies by keyword so tests read like the spec scenarios."""

    def structured(self, model, system, text, schema, name, effort):
        self.calls.append({"model": model, "text": text})
        items = []
        for block in text.split("\n\n"):
            ref = block[1 : block.index("]")]
            if "newsletter" in block.lower():
                items.append({"ref": ref, "class": "noise", "action": "", "reason": "promo"})
            elif "?" in block:
                items.append(
                    {
                        "ref": ref,
                        "class": "needs_reply",
                        "action": "Answer Olga",
                        "reason": "question",
                    }
                )
            else:
                items.append({"ref": ref, "class": "fyi", "action": "", "reason": "update"})
        return {"items": items}, Usage(2_000, 200)


def latest_revision(conn):
    return conn.execute(
        "SELECT * FROM briefs WHERE routine = 'revision' ORDER BY id DESC"
    ).fetchone()


def test_revision_quiet_pass_no_push(conn, config, monkeypatch):
    mail(conn, "n1", "news@shop.example", "Weekly newsletter", "Sale!", NOW - timedelta(hours=1))
    bid = triage.run_pass(conn, NOW, TriageLlm(), config)
    brief = latest_revision(conn)
    assert brief["id"] == bid and brief["push"] is False
    assert brief["headline"] == "Mail revision: nothing needs you (1 new)"
    sent = []
    monkeypatch.setenv("WEB_PUSH_VAPID_PRIVATE_KEY", "x")
    monkeypatch.setattr(push, "webpush", lambda **kw: sent.append(kw))
    conn.execute(
        "INSERT INTO push_subscriptions (endpoint, p256dh, auth) VALUES ('https://p/1', 'p', 'a')"
    )
    assert push.notify_brief(conn, bid, NOW) == 0 and sent == []


def test_revision_needs_reply_pushes(conn, config):
    q = mail(
        conn,
        "q1",
        "Olga <olga@dealer.example>",
        "Delivery terms",
        "Can you confirm the November terms?",
        NOW - timedelta(hours=2),
    )
    triage.run_pass(conn, NOW, TriageLlm(), config)
    brief = latest_revision(conn)
    assert brief["push"] is True and brief["headline"] == "Mail revision: 1 needs your reply"
    group = brief["sections"][0]
    assert group["title"] == "Needs reply" and group["items"][0]["id"] == q
    assert group["items"][0]["reason"] == "Answer Olga"
    row = conn.execute("SELECT class, action, sender FROM triage").fetchone()
    assert row == {"class": "needs_reply", "action": "Answer Olga", "sender": "olga@dealer.example"}


def test_sender_noise_pref(conn, config):
    triage.set_sender_pref(conn, "Promo <promo@brand.example>", "noise")
    mail(conn, "p1", "promo@brand.example", "Hello?", "Are you there?", NOW - timedelta(hours=1))
    llm = TriageLlm()
    triage.run_pass(conn, NOW, llm, config)
    assert llm.calls == []  # decided by the preference, no AI
    assert conn.execute("SELECT class FROM triage").fetchone()["class"] == "noise"


def test_sender_important_pref_lifts_fyi(conn, config):
    triage.set_sender_pref(conn, "bank@bank.example", "important")
    mail(
        conn,
        "b1",
        "bank@bank.example",
        "Statement",
        "Your statement is ready.",
        NOW - timedelta(hours=1),
    )
    triage.run_pass(conn, NOW, TriageLlm(), config)
    assert conn.execute("SELECT class FROM triage").fetchone()["class"] == "important"


def test_owner_wrote_last_needs_nothing(conn, config):
    mail(conn, "o1", "Me <me@example.com>", "Re: terms?", "Sure, done?", NOW - timedelta(hours=1))
    llm = TriageLlm()
    triage.run_pass(conn, NOW, llm, config)
    assert llm.calls == []
    assert conn.execute("SELECT class, reason FROM triage").fetchone() == {
        "class": "fyi",
        "reason": "you wrote last",
    }


def test_next_pass_only_takes_mail_since_previous_pass(conn, config):
    mail(conn, "a", "x@example.org", "First?", "?", NOW - timedelta(hours=2))
    triage.run_pass(conn, NOW, TriageLlm(), config)
    later = NOW + timedelta(hours=3)
    b = mail(conn, "b", "y@example.org", "Second?", "?", NOW + timedelta(hours=1))
    triage.run_pass(conn, later, TriageLlm(), config)
    ids = [
        r["item_id"]
        for r in conn.execute(
            "SELECT item_id FROM triage WHERE brief_id = %s", (latest_revision(conn)["id"],)
        )
    ]
    assert ids == [b]


def test_budget_reached_lists_without_triage(conn):
    record_usage(conn, "_routines", "gpt-6-luna", "x", Usage(400_000_000, 0))  # $40
    mail(conn, "a", "x@example.org", "Question?", "?", NOW - timedelta(hours=1))
    llm = TriageLlm()
    triage.run_pass(conn, NOW, llm, Config(llm=LlmConfig(monthly_budget_usd=30)))
    brief = latest_revision(conn)
    assert llm.calls == [] and brief["sections"][0]["title"] == "Triage"
    assert brief["push"] is False


def test_quiet_when_no_new_mail(conn, config):
    triage.run_pass(conn, NOW, TriageLlm(), config)
    brief = latest_revision(conn)
    assert brief["headline"] == "Mail revision: nothing new" and brief["push"] is False
