from datetime import timedelta

from psycopg.types.json import Jsonb

from kb import loops
from kb.routines import triage
from tests.test_triage import NOW, TriageLlm, mail


def reply(conn, key, author, at, labels=()):
    conn.execute(
        "INSERT INTO messages (source_id, message_key, kind, unit_key, author, sent_at, body,"
        " metadata) VALUES ('mail-test', %s, 'email', %s, %s, %s, 'reply', %s)",
        (f"{key}-r{at.timestamp()}", key, author, at, Jsonb({"labels": list(labels)})),
    )


def open_loops(conn):
    return conn.execute("SELECT * FROM loops WHERE status = 'open' ORDER BY id").fetchall()


def test_triage_opens_needs_reply_loop_once(conn, config):
    q = mail(
        conn,
        "q",
        "Olga <olga@dealer.example>",
        "Terms",
        "Can you confirm?",
        NOW - timedelta(hours=1),
    )
    triage.run_pass(conn, NOW, TriageLlm(), config)
    triage.run_pass(conn, NOW + timedelta(minutes=1), TriageLlm(), config)
    [loop] = open_loops(conn)
    assert loop["kind"] == "needs_reply" and loop["item_id"] == q
    assert loop["title"] == "Answer Olga" and loop["counterpart"] == "Olga <olga@dealer.example>"
    assert loop["source_link"] == "https://mail.google.com/x"


def test_needs_reply_closes_when_owner_replies(conn, config):
    mail(
        conn,
        "q",
        "Olga <olga@dealer.example>",
        "Terms",
        "Can you confirm?",
        NOW - timedelta(hours=1),
    )
    triage.run_pass(conn, NOW, TriageLlm(), config)
    owner = loops.owner_emails(conn, config)
    assert owner == {"me@example.com"}
    assert loops.close_answered(conn, owner, NOW) == 0  # nothing from the owner yet
    reply(conn, "q", "Me <me@example.com>", NOW + timedelta(minutes=30))
    assert loops.close_answered(conn, owner, NOW + timedelta(hours=1)) == 1
    loop = conn.execute("SELECT * FROM loops").fetchone()
    assert loop["status"] == "done" and loop["closing_message_key"].startswith("q-r")
    actions = [r["action"] for r in conn.execute("SELECT action FROM loop_events ORDER BY id")]
    assert actions == ["opened", "done"]


def test_unsent_draft_is_not_a_reply(conn, config):
    mail(
        conn,
        "q",
        "Olga <olga@dealer.example>",
        "Terms",
        "Can you confirm?",
        NOW - timedelta(hours=1),
    )
    triage.run_pass(conn, NOW, TriageLlm(), config)
    reply(conn, "q", "me@example.com", NOW + timedelta(minutes=5), labels=["\\Draft", "\\Inbox"])
    assert loops.close_answered(conn, {"me@example.com"}, NOW + timedelta(hours=1)) == 0
    assert len(open_loops(conn)) == 1


def test_draft_does_not_count_as_owner_writing_last_in_triage(conn, config):
    mail(
        conn,
        "q",
        "Olga <olga@dealer.example>",
        "Terms",
        "Can you confirm?",
        NOW - timedelta(hours=2),
    )
    reply(conn, "q", "me@example.com", NOW - timedelta(hours=1), labels=["\\Draft"])
    triage.run_pass(conn, NOW, TriageLlm(), config)
    assert conn.execute("SELECT class FROM triage").fetchone()["class"] == "needs_reply"


def test_reply_by_someone_else_does_not_close(conn, config):
    mail(
        conn,
        "q",
        "Olga <olga@dealer.example>",
        "Terms",
        "Can you confirm?",
        NOW - timedelta(hours=1),
    )
    triage.run_pass(conn, NOW, TriageLlm(), config)
    reply(conn, "q", "colleague@dealer.example", NOW + timedelta(minutes=5))
    assert loops.close_answered(conn, {"me@example.com"}, NOW + timedelta(hours=1)) == 0


def test_owner_emails_include_settings(conn, config):
    loops.set_setting(conn, "owner_emails", ["Work@Digisoft.example"])
    assert loops.owner_emails(conn, config) == {"me@example.com", "work@digisoft.example"}


def test_owner_emails_include_the_clickup_login(conn, config):
    from psycopg.types.json import Jsonb

    conn.execute(
        "INSERT INTO connector_accounts (kind, label, settings, secret)"
        " VALUES ('clickup', 'Adducate', %s, '')",
        (Jsonb({"team_id": "T1", "owner_email": "Owner.Login@Gmail.example"}),),
    )
    assert "owner.login@gmail.example" in loops.owner_emails(conn, config)
