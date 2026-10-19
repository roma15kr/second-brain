"""Calendars, read-only (calendar-meetings spec; web-os-v1 task 13.1)."""

import base64
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from kb import db, meetings, push
from kb.api import auth
from kb.api.app import build_app
from kb.connectors import calendar
from kb.routines import KYIV

NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
CSRF = {"X-KB-Request": "1"}
OWNER = {"me@example.com"}


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("KB_SECRET_KEY", "a-long-test-passphrase-for-the-secret-key")


ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Google Inc//Google Calendar 70.9054//EN
X-WR-CALNAME:RDIM
BEGIN:VTIMEZONE
TZID:Europe/Kyiv
BEGIN:STANDARD
DTSTART:19701025T040000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
TZOFFSETFROM:+0300
TZOFFSETTO:+0200
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:19700329T030000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
TZOFFSETFROM:+0200
TZOFFSETTO:+0300
END:DAYLIGHT
END:VTIMEZONE
BEGIN:VEVENT
UID:weekly-sync@google.com
DTSTART;TZID=Europe/Kyiv:20261019T150000
DTEND;TZID=Europe/Kyiv:20261019T153000
RRULE:FREQ=WEEKLY;COUNT=3
SUMMARY:RDIM sync
DESCRIPTION:Join: https://meet.google.com/abc-defg-hij
ORGANIZER;CN=Олена:mailto:olena@rdim.example
ATTENDEE;CN=Олена;PARTSTAT=ACCEPTED:mailto:olena@rdim.example
ATTENDEE;CN=Me;PARTSTAT=ACCEPTED:mailto:me@example.com
ATTENDEE;CN=Макс;PARTSTAT=TENTATIVE:mailto:max@rdim.example
END:VEVENT
BEGIN:VEVENT
UID:holiday@google.com
DTSTART;VALUE=DATE:20261021
DTEND;VALUE=DATE:20261022
SUMMARY:Day off
END:VEVENT
BEGIN:VEVENT
UID:declined@google.com
DTSTART:20261020T120000Z
DTEND:20261020T130000Z
SUMMARY:Vendor pitch
ATTENDEE;PARTSTAT=DECLINED:mailto:me@example.com
ATTENDEE;PARTSTAT=ACCEPTED:mailto:vendor@x.example
END:VEVENT
END:VCALENDAR
"""


def test_ics_recurring_expanded_kyiv():
    start, end = calendar.window(NOW)
    events = sorted(calendar.parse_ics(ICS, start, end, OWNER), key=lambda e: e.start)
    sync = [e for e in events if e.title == "RDIM sync"]
    # 15:00 Kyiv every week, across the switch to winter time on 25 October
    assert [e.start.astimezone(KYIV).strftime("%m-%d %H:%M") for e in sync] == [
        "10-19 15:00",
        "10-26 15:00",
        "11-02 15:00",
    ]
    assert sync[0].start == datetime(2026, 10, 19, 12, 0, tzinfo=UTC)  # UTC+3
    assert sync[1].start == datetime(2026, 10, 26, 13, 0, tzinfo=UTC)  # UTC+2
    assert sync[0].link == "https://meet.google.com/abc-defg-hij"
    assert sync[0].my_status == "ACCEPTED" and len(sync[0].attendees) == 3
    day_off = next(e for e in events if e.title == "Day off")
    assert day_off.all_day and day_off.start.astimezone(KYIV).hour == 0
    assert next(e for e in events if e.title == "Vendor pitch").my_status == "DECLINED"


PRINCIPAL = """<?xml version="1.0" encoding="UTF-8"?>
<multistatus xmlns="DAV:"><response><href>/</href><propstat><prop>
<current-user-principal><href>/1234567/principal/</href></current-user-principal>
</prop><status>HTTP/1.1 200 OK</status></propstat></response></multistatus>"""

HOME = """<?xml version="1.0" encoding="UTF-8"?>
<multistatus xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><response>
<href>/1234567/principal/</href><propstat><prop><C:calendar-home-set>
<href xmlns="DAV:">https://p42-caldav.icloud.com:443/1234567/calendars/</href>
</C:calendar-home-set></prop><status>HTTP/1.1 200 OK</status></propstat></response></multistatus>"""

CALENDARS = """<?xml version="1.0" encoding="UTF-8"?>
<multistatus xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
<response><href>/1234567/calendars/</href><propstat><prop><resourcetype><collection/></resourcetype>
</prop><status>HTTP/1.1 200 OK</status></propstat></response>
<response><href>/1234567/calendars/home/</href><propstat><prop>
<resourcetype><collection/><C:calendar/></resourcetype><displayname>Home</displayname>
<C:supported-calendar-component-set><C:comp name="VEVENT"/></C:supported-calendar-component-set>
</prop><status>HTTP/1.1 200 OK</status></propstat></response>
<response><href>/1234567/calendars/family/</href><propstat><prop>
<resourcetype><collection/><C:calendar/></resourcetype><displayname>Family</displayname>
<C:supported-calendar-component-set><C:comp name="VEVENT"/></C:supported-calendar-component-set>
</prop><status>HTTP/1.1 200 OK</status></propstat></response>
<response><href>/1234567/calendars/tasks/</href><propstat><prop>
<resourcetype><collection/><C:calendar/></resourcetype><displayname>Reminders</displayname>
<C:supported-calendar-component-set><C:comp name="VTODO"/></C:supported-calendar-component-set>
</prop><status>HTTP/1.1 200 OK</status></propstat></response>
</multistatus>"""

FAMILY_ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:dentist
DTSTART:20261020T130000Z
DTEND:20261020T140000Z
SUMMARY:Dentist
END:VEVENT
END:VCALENDAR"""


def report(ics):
    return (
        '<?xml version="1.0"?><multistatus xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
        "<response><href>/1234567/calendars/family/dentist.ics</href><propstat><prop>"
        f"<C:calendar-data>{ics}</C:calendar-data></prop>"
        "<status>HTTP/1.1 200 OK</status></propstat></response></multistatus>"
    )


class ICloud:
    def __init__(self, password="abcd-efgh-ijkl-mnop"):
        self.password, self.requests = password, []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, str(request.url), request.content.decode()))
        url = str(request.url)
        if request.method == "GET" and "calendar.google.com" in url:
            return httpx.Response(200, text=ICS)  # a secret address: no credentials
        auth = request.headers.get("authorization", "Basic ")
        pw = base64.b64decode(auth.split()[1]).decode().partition(":")[2]
        if pw != self.password:
            return httpx.Response(401)
        if request.method == "PROPFIND" and url == "https://caldav.icloud.com/":
            return httpx.Response(207, text=PRINCIPAL)
        if request.method == "PROPFIND" and url.endswith("/principal/"):
            return httpx.Response(207, text=HOME)
        if request.method == "PROPFIND" and url.endswith("/calendars/"):
            return httpx.Response(207, text=CALENDARS)
        if request.method == "REPORT" and url.endswith("/family/"):
            return httpx.Response(207, text=report(FAMILY_ICS))
        if request.method == "REPORT":
            return httpx.Response(207, text=report(""))
        return httpx.Response(404)

    def transport(self):
        return httpx.MockTransport(self.handler)


def test_caldav_discovery_icloud_fixture(conn):
    icloud = ICloud()
    aid = calendar.connect_caldav(
        conn, "me@icloud.com", "abcd-efgh-ijkl-mnop", transport=icloud.transport()
    )
    names = [r["name"] for r in conn.execute("SELECT name FROM calendars ORDER BY name")]
    assert names == ["Family", "Home"]  # the Reminders list (VTODO) is not a calendar of events
    hrefs = {r["href"] for r in conn.execute("SELECT href FROM calendars")}
    assert "https://p42-caldav.icloud.com:443/1234567/calendars/family/" in hrefs
    secret = conn.execute(
        "SELECT settings::text AS s, secret FROM connector_accounts WHERE id = %s", (aid,)
    ).fetchone()
    assert "abcd-efgh" not in secret["s"] and b"abcd-efgh" not in bytes(secret["secret"])
    with pytest.raises(calendar.CalendarError, match="refused"):
        calendar.connect_caldav(conn, "me@icloud.com", "wrong", transport=icloud.transport())


def test_caldav_report_time_range(conn):
    icloud = ICloud()
    calendar.connect_caldav(
        conn, "me@icloud.com", "abcd-efgh-ijkl-mnop", transport=icloud.transport()
    )
    conn.execute("UPDATE calendars SET sync = true, scopes = '{personal}' WHERE name = 'Family'")
    assert calendar.sync_due(conn, NOW, OWNER, icloud.transport()) == 1
    [rep] = [r for r in icloud.requests if r[0] == "REPORT"]
    assert 'start="20260920T090000Z"' in rep[2] and 'end="20270118T090000Z"' in rep[2]
    [ev] = meetings.today(conn, NOW)
    assert ev["title"] == "Dentist" and ev["scopes"] == ["personal"] and ev["calendar"] == "Family"
    # within 10 minutes nothing is fetched again
    before = len(icloud.requests)
    calendar.sync_due(conn, NOW + timedelta(minutes=5), OWNER, icloud.transport())
    assert len(icloud.requests) == before


def test_calendar_client_has_no_write_methods(conn):
    icloud = ICloud()
    calendar.connect_caldav(
        conn, "me@icloud.com", "abcd-efgh-ijkl-mnop", transport=icloud.transport()
    )
    conn.execute("UPDATE calendars SET sync = true, scopes = '{personal}'")
    calendar.connect_ical(
        conn,
        "webcal://calendar.google.com/calendar/ical/x/private-y/basic.ics",
        "",
        icloud.transport(),
    )
    conn.execute("UPDATE calendars SET sync = true, scopes = '{rdim}'")
    calendar.sync_due(conn, NOW, OWNER, icloud.transport())
    assert {m for m, _, _ in icloud.requests} <= {"PROPFIND", "REPORT", "GET"}
    public = {n for n in dir(calendar.CalDavClient) if not n.startswith("_")}
    assert public == {"calendars", "events"}


def test_declined_and_all_day_not_reminded(conn, monkeypatch):
    sent = []

    def fake_send(conn, routine, headline, url, now, **kw):
        sent.append((routine, headline, url))
        return 1

    monkeypatch.setattr(push, "send", fake_send)
    icloud = ICloud()
    calendar.connect_ical(
        conn,
        "https://calendar.google.com/calendar/ical/x/private-y/basic.ics",
        "",
        icloud.transport(),
    )
    conn.execute("UPDATE calendars SET sync = true, scopes = '{rdim}'")
    calendar.sync_due(conn, NOW, OWNER, icloud.transport())
    # 11:55 UTC: the declined 12:00 pitch is due; 2026-10-21 all-day; the next sync is 10-26
    assert meetings.remind_due(conn, datetime(2026, 10, 20, 11, 55, tzinfo=UTC)) == 0
    assert meetings.remind_due(conn, datetime(2026, 10, 21, 0, 0, tzinfo=KYIV)) == 0
    # the weekly sync on 26 October, 15:00 Kyiv = 13:00 UTC: reminded at 12:50, once
    assert meetings.remind_due(conn, datetime(2026, 10, 26, 12, 49, tzinfo=UTC)) == 0
    assert meetings.remind_due(conn, datetime(2026, 10, 26, 12, 50, tzinfo=UTC)) == 1
    assert meetings.remind_due(conn, datetime(2026, 10, 26, 12, 55, tzinfo=UTC)) == 0
    [(routine, headline, url)] = sent
    assert routine == "meetings" and headline == "15:00 RDIM sync — 3 people"
    assert url.startswith("/meetings/")


@pytest.fixture
def client(conn, pg_url, config):
    app = build_app(
        None,
        connect=lambda: db.connect(pg_url),
        rp=auth.RelyingParty("https://os.x"),
        config=config,
    )
    app.state.calendar_transport = ICloud().transport()
    c = TestClient(app, base_url="https://os.x")
    c.cookies.set(auth.SESSION_COOKIE, auth.create_session(conn, "t", datetime.now(UTC)))
    return c


def test_connect_mark_and_list_meetings(client, conn):
    r = client.post(
        "/api/connectors/calendars/caldav",
        json={"username": "me@icloud.com", "password": "abcd-efgh-ijkl-mnop"},
        headers=CSRF,
    )
    assert r.status_code == 200
    cals = client.get("/api/connectors/calendars").json()["calendars"]
    family = next(c for c in cals if c["name"] == "Family")
    assert family["sync"] is False
    assert (
        client.post(
            f"/api/connectors/calendars/{family['id']}", json={"sync": True}, headers=CSRF
        ).status_code
        == 400
    )
    ok = client.post(
        f"/api/connectors/calendars/{family['id']}",
        json={"sync": True, "scopes": ["personal"], "remind_minutes": 15},
        headers=CSRF,
    )
    assert ok.status_code == 200
    bad = client.post(
        "/api/connectors/calendars/ical",
        json={"url": "http://insecure.example/x.ics"},
        headers=CSRF,
    )
    assert bad.status_code == 400
