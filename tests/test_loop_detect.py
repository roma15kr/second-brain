from datetime import date, datetime, timedelta

import pytest
from psycopg.types.json import Jsonb

from kb import loops
from kb.config import Config
from kb.loop_detect import detect, detect_cycle, resolve_due
from kb.routines import KYIV
from tests.test_brief_ai import FakeLlm

# Thursday 22 Oct 2026, 10:00 Kyiv
SAID = datetime(2026, 10, 22, 10, 0, tzinfo=KYIV)
NOW = SAID + timedelta(hours=2)


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("by Monday", date(2026, 10, 26)),
        ("до понеділка", date(2026, 10, 26)),
        ("в понедельник", date(2026, 10, 26)),
        ("завтра", date(2026, 10, 23)),
        ("tomorrow", date(2026, 10, 23)),
        ("післязавтра", date(2026, 10, 24)),
        ("послезавтра", date(2026, 10, 24)),
        ("до п'ятниці", date(2026, 10, 23)),
        ("до п" + chr(0x2019) + "ятниці", date(2026, 10, 23)),  # typographic apostrophe
        ("к пятнице", date(2026, 10, 23)),
        ("by Friday", date(2026, 10, 23)),
        ("в четвер", date(2026, 10, 29)),  # said on Thursday → next Thursday
        ("сьогодні", date(2026, 10, 22)),
        ("сегодня до вечера", date(2026, 10, 22)),
        ("через 3 дні", date(2026, 10, 25)),
        ("in 10 days", date(2026, 11, 1)),
        ("next week", date(2026, 10, 26)),
        ("наступного тижня", date(2026, 10, 26)),
        ("до кінця тижня", date(2026, 10, 23)),
        ("до конца месяца", date(2026, 10, 31)),
        ("до 25.10", date(2026, 10, 25)),
        ("01.02", date(2027, 2, 1)),  # already past this year → next year
        ("2026-11-03", date(2026, 11, 3)),
        ("", None),
        ("soon", None),
    ],
)
def test_resolve_due_phrases_uk_ru_en(phrase, expected):
    assert resolve_due(phrase, SAID) == expected


def thread(conn, key, kind, messages):
    """messages: list of (author, body, minutes_after_SAID, identity_keys)."""
    item = conn.execute(
        "INSERT INTO items (source_id, source_item_key, kind, scopes, title, raw_text,"
        " last_activity_at, locator, content_hash) VALUES ('s', %s, %s, '{rdim}', 'Prices', 'x',"
        " %s, 'https://t.me/c/1/2', %s) RETURNING id",
        (key, kind, SAID + timedelta(minutes=messages[-1][2]), f"h-{key}"),
    ).fetchone()["id"]
    for n, (author, body, minutes, ids) in enumerate(messages):
        conn.execute(
            "INSERT INTO messages (source_id, message_key, kind, unit_key, author, sent_at, body,"
            " identity_keys, locator, metadata) VALUES ('s', %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                f"{key}:{n}",
                "email" if kind == "email_thread" else "tg",
                key,
                author,
                SAID + timedelta(minutes=minutes),
                body,
                ids,
                f"https://t.me/c/1/{n}",
                Jsonb({}),
            ),
        )
    return item


@pytest.fixture
def owner_tg(conn):
    loops.set_setting(conn, "telegram_self_ids", ["111"])


def promise(kind, title, message, due="", counterpart="Вячеслав"):
    return {
        "kind": kind,
        "title": title,
        "counterpart": counterpart,
        "message": message,
        "due_phrase": due,
    }


def test_loop_detect_promise_by_owner_with_due(conn, config, owner_tg):
    item = thread(
        conn,
        "c1",
        "tg_conversation",
        [
            ("Вячеслав", "Коли буде прайс?", 0, ["tg:222"]),
            ("Me", "Надішлю оновлений прайс до понеділка", 3, ["tg:111"]),
        ],
    )
    llm = FakeLlm(
        {
            "new": [promise("i_owe", "Send the updated price list", "m2", "до понеділка")],
            "fulfilled": [],
        }
    )
    assert detect(conn, config, llm, item, NOW) == {"opened": 1, "closed": 0}
    loop = conn.execute("SELECT * FROM loops").fetchone()
    assert loop["kind"] == "i_owe" and loop["due_date"] == date(2026, 10, 26)
    assert loop["counterpart"] == "Вячеслав" and loop["source_message_key"] == "c1:1"
    assert loop["source_link"] == "https://t.me/c/1/1" and loop["scopes"] == ["rdim"]
    assert "[m2]" in llm.calls[0]["text"] and "ME: Надішлю" in llm.calls[0]["text"]


def test_promise_to_owner(conn, config, owner_tg):
    item = thread(
        conn,
        "c2",
        "tg_conversation",
        [
            ("Олена", "Митні документи надішлю завтра", 0, ["tg:333"]),
        ],
    )
    llm = FakeLlm(
        {
            "new": [promise("owed_to_me", "Customs documents", "m1", "завтра", "Олена")],
            "fulfilled": [],
        }
    )
    detect(conn, config, llm, item, NOW)
    loop = conn.execute("SELECT kind, due_date FROM loops").fetchone()
    assert loop == {"kind": "owed_to_me", "due_date": date(2026, 10, 23)}


def test_chitchat_no_loop(conn, config, owner_tg):
    item = thread(conn, "c3", "tg_conversation", [("Олена", "ok, thanks 👍", 0, ["tg:333"])])
    detect(conn, config, FakeLlm({"new": [], "fulfilled": []}), item, NOW)
    assert conn.execute("SELECT count(*) AS n FROM loops").fetchone()["n"] == 0


def test_wrong_direction_and_unknown_message_ignored(conn, config, owner_tg):
    item = thread(conn, "c4", "tg_conversation", [("Олена", "I'll send it", 0, ["tg:333"])])
    llm = FakeLlm(
        {
            "new": [promise("i_owe", "Send it", "m1"), promise("owed_to_me", "X", "m9")],
            "fulfilled": [],
        }
    )
    detect(conn, config, llm, item, NOW)
    assert conn.execute("SELECT count(*) AS n FROM loops").fetchone()["n"] == 0


def test_dismissed_source_not_recreated(conn, config, owner_tg):
    item = thread(conn, "c5", "tg_conversation", [("Me", "I'll call you", 0, ["tg:111"])])
    conn.execute("INSERT INTO loop_dismissed_sources (source_message_key) VALUES ('c5:0')")
    llm = FakeLlm({"new": [promise("i_owe", "Call back", "m1")], "fulfilled": []})
    detect(conn, config, llm, item, NOW)
    assert conn.execute("SELECT count(*) AS n FROM loops").fetchone()["n"] == 0


def test_fulfilled_closes_with_message(conn, config, owner_tg):
    item = thread(
        conn,
        "c6",
        "tg_conversation",
        [
            ("Me", "Надішлю прайс завтра", 0, ["tg:111"]),
            ("Me", "Ось прайс 📎", 60, ["tg:111"]),
        ],
    )
    detect(
        conn,
        config,
        FakeLlm({"new": [promise("i_owe", "Send price list", "m1", "завтра")], "fulfilled": []}),
        item,
        NOW,
    )
    loop_id = conn.execute("SELECT id FROM loops").fetchone()["id"]
    detect(
        conn,
        config,
        FakeLlm({"new": [], "fulfilled": [{"loop": f"loop:{loop_id}", "message": "m2"}]}),
        item,
        NOW,
    )
    loop = conn.execute("SELECT status, closing_message_key FROM loops").fetchone()
    assert loop == {"status": "done", "closing_message_key": "c6:1"}


def test_detect_cycle_checks_each_content_once_and_needs_tg_owner(conn, config):
    email = thread(conn, "e1", "email_thread", [("x@example.org", "hello", 0, [])])
    tg = thread(conn, "t1", "tg_conversation", [("Олена", "hi", 0, ["tg:333"])])
    llm = FakeLlm({"new": [], "fulfilled": []})
    assert detect_cycle(conn, Config(), llm, NOW) == 1  # Telegram skipped: owner id unknown
    loops.set_setting(conn, "telegram_self_ids", ["111"])
    assert detect_cycle(conn, Config(), llm, NOW) == 1  # now the chat; the email was done
    assert detect_cycle(conn, Config(), llm, NOW) == 0
    checked = {
        r["id"] for r in conn.execute("SELECT id FROM items WHERE loops_checked IS NOT NULL")
    }
    assert checked == {email, tg}


def test_detect_cycle_waits_until_settled(conn):
    thread(conn, "e2", "email_thread", [("x@example.org", "hello", 110, [])])  # 10 min before NOW
    assert detect_cycle(conn, Config(), FakeLlm({"new": [], "fulfilled": []}), NOW) == 0
