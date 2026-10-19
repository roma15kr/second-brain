"""Calendars, read-only (calendar-meetings spec; web-os-v1 design D15).

- Google: each calendar's "secret address in iCal format" (plain HTTPS GET, no OAuth).
- Apple iCloud and other CalDAV servers: the account email and an app-specific password;
  calendars are discovered with PROPFIND (current-user-principal → calendar-home-set →
  calendars) and events read with REPORT calendar-query for a time range.
Only read methods exist. Recurring events are expanded in the window (30 days back, 90 ahead)
and stored as one row per occurrence; the owner's own response (accepted, declined…) is kept.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree

import httpx
from psycopg.types.json import Jsonb

from kb.db import Conn

log = logging.getLogger(__name__)

PAST_DAYS, FUTURE_DAYS = 30, 90
SYNC_EVERY = timedelta(minutes=10)
ICLOUD = "https://caldav.icloud.com/"
NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav", "a": "http://apple.com/ns/ical/"}
MEET_LINK = re.compile(
    r"https://(?:meet\.google\.com|[\w.-]*zoom\.us|teams\.microsoft\.com|"
    r"teams\.live\.com|[\w.-]*webex\.com)/[^\s<>\"']+"
)


class CalendarError(RuntimeError):
    pass


@dataclass
class Event:
    uid: str
    start: datetime
    end: datetime
    all_day: bool
    title: str
    location: str = ""
    description: str = ""
    link: str | None = None
    attendees: list[dict[str, str]] = field(default_factory=list)
    my_status: str | None = None
    cancelled: bool = False


def window(now: datetime) -> tuple[datetime, datetime]:
    return now - timedelta(days=PAST_DAYS), now + timedelta(days=FUTURE_DAYS)


# --- parsing ----------------------------------------------------------------------------------


def _email(value: Any) -> str:
    return str(value).removeprefix("mailto:").removeprefix("MAILTO:").strip().lower()


def _when(value: Any, tz: Any) -> tuple[datetime, bool]:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=tz)), False
    if isinstance(value, date):
        return datetime.combine(value, time(0), tzinfo=tz), True
    raise CalendarError(f"unexpected date {value!r}")


def parse_ics(data: str | bytes, start: datetime, end: datetime, owner: set[str]) -> list[Event]:
    """Every occurrence in the window, recurring events expanded (Kyiv time for floating and
    all-day dates)."""
    import icalendar
    import recurring_ical_events

    from kb.routines import KYIV

    cal = icalendar.Calendar.from_ical(data)
    out = []
    for ev in recurring_ical_events.of(cal).between(start, end):
        s, all_day = _when(ev.get("DTSTART").dt, KYIV)
        if ev.get("DTEND") is not None:
            e, _ = _when(ev.get("DTEND").dt, KYIV)
        elif ev.get("DURATION") is not None:
            e = s + ev.get("DURATION").dt
        else:
            e = s + (timedelta(days=1) if all_day else timedelta(0))
        attendees, mine = [], None
        raw = ev.get("ATTENDEE") or []
        for a in raw if isinstance(raw, list) else [raw]:
            email = _email(a)
            status = str(a.params.get("PARTSTAT", "NEEDS-ACTION")).upper()
            attendees.append(
                {"email": email, "name": str(a.params.get("CN", "")), "status": status}
            )
            if email in owner:
                mine = status
        organizer = ev.get("ORGANIZER")
        if mine is None and organizer is not None and _email(organizer) in owner:
            mine = "ACCEPTED"
        text = " ".join(
            str(ev.get(k) or "") for k in ("LOCATION", "DESCRIPTION", "URL", "X-GOOGLE-CONFERENCE")
        )
        link = MEET_LINK.search(text)
        out.append(
            Event(
                uid=str(ev.get("UID") or f"{s.isoformat()}-{ev.get('SUMMARY')}"),
                start=s.astimezone(UTC),
                end=e.astimezone(UTC),
                all_day=all_day,
                title=str(ev.get("SUMMARY") or ""),
                location=str(ev.get("LOCATION") or ""),
                description=str(ev.get("DESCRIPTION") or "")[:4000],
                link=link.group(0) if link else None,
                attendees=attendees,
                my_status=mine,
                cancelled=str(ev.get("STATUS") or "").upper() == "CANCELLED",
            )
        )
    return out


# --- sources ----------------------------------------------------------------------------------


def fetch_ics(url: str, transport: httpx.BaseTransport | None = None) -> bytes:
    url = re.sub(r"^webcal://", "https://", url.strip(), flags=re.IGNORECASE)
    if not url.startswith("https://"):
        raise CalendarError("the calendar address must start with https:// or webcal://")
    with httpx.Client(transport=transport, timeout=30, follow_redirects=True) as c:
        r = c.get(url)
    if r.status_code != 200 or b"BEGIN:VCALENDAR" not in r.content[:2000]:
        raise CalendarError(f"not an iCal calendar (HTTP {r.status_code})")
    return r.content


class CalDavClient:
    """CalDAV, read-only: PROPFIND for discovery and REPORT for events. Nothing else."""

    def __init__(
        self,
        username: str,
        password: str,
        base: str = ICLOUD,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base = base
        self.http = httpx.Client(
            auth=(username, password), transport=transport, timeout=30, follow_redirects=True
        )

    def _xml(self, method: str, url: str, body: str, depth: str) -> ElementTree.Element:
        r = self.http.request(
            method,
            url,
            content=body.encode(),
            headers={"Depth": depth, "Content-Type": "application/xml; charset=utf-8"},
        )
        if r.status_code == 401:
            raise CalendarError("the server refused the email or app-specific password")
        if r.status_code != 207:
            raise CalendarError(f"{method} {url}: HTTP {r.status_code}")
        return ElementTree.fromstring(r.content)

    def _href(self, root: ElementTree.Element, prop: str, url: str) -> str:
        el = root.find(f".//{prop}/d:href", NS)
        if el is None or not el.text:
            raise CalendarError(f"no {prop} at {url}")
        return urljoin(url, el.text.strip())

    def calendars(self) -> list[tuple[str, str]]:
        """(collection URL, display name) for every calendar holding events."""
        principal = self._href(
            self._xml(
                "PROPFIND",
                self.base,
                '<d:propfind xmlns:d="DAV:"><d:prop><d:current-user-principal/></d:prop>'
                "</d:propfind>",
                "0",
            ),
            "d:current-user-principal",
            self.base,
        )
        home = self._href(
            self._xml(
                "PROPFIND",
                principal,
                '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop>'
                "<c:calendar-home-set/></d:prop></d:propfind>",
                "0",
            ),
            "c:calendar-home-set",
            principal,
        )
        root = self._xml(
            "PROPFIND",
            home,
            '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop>'
            "<d:resourcetype/><d:displayname/><c:supported-calendar-component-set/>"
            "</d:prop></d:propfind>",
            "1",
        )
        out = []
        for resp in root.findall("d:response", NS):
            if resp.find(".//d:resourcetype/c:calendar", NS) is None:
                continue
            comps = [c.get("name") for c in resp.findall(".//c:comp", NS)]
            if comps and "VEVENT" not in comps:
                continue  # reminders / tasks lists
            href = resp.find("d:href", NS)
            name = resp.find(".//d:displayname", NS)
            if href is not None and href.text:
                url = urljoin(home, href.text.strip())
                out.append((url, (name.text if name is not None and name.text else url).strip()))
        return out

    def events(self, url: str, start: datetime, end: datetime) -> list[str]:
        """The iCalendar data of every event with an occurrence in the window."""
        fmt = "%Y%m%dT%H%M%SZ"
        root = self._xml(
            "REPORT",
            url,
            '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            "<d:prop><c:calendar-data/></d:prop><c:filter>"
            '<c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">'
            f'<c:time-range start="{start.astimezone(UTC):{fmt}}" '
            f'end="{end.astimezone(UTC):{fmt}}"/>'
            "</c:comp-filter></c:comp-filter></c:filter></c:calendar-query>",
            "1",
        )
        return [el.text for el in root.findall(".//c:calendar-data", NS) if el.text]


# --- storage ----------------------------------------------------------------------------------


def store(conn: Conn, calendar_id: int, events: list[Event], start: datetime, end: datetime) -> int:
    """Upserts the window's occurrences and removes the ones no longer in the calendar."""
    keep = []
    for e in events:
        row = conn.execute(
            """
            INSERT INTO events (calendar_id, uid, start_at, end_at, all_day, title, location,
                                link, description, attendees, my_status, cancelled, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (calendar_id, uid, start_at) DO UPDATE SET end_at = EXCLUDED.end_at,
                all_day = EXCLUDED.all_day, title = EXCLUDED.title, location = EXCLUDED.location,
                link = EXCLUDED.link, description = EXCLUDED.description,
                attendees = EXCLUDED.attendees, my_status = EXCLUDED.my_status,
                cancelled = EXCLUDED.cancelled, updated_at = now()
            RETURNING id
            """,
            (
                calendar_id,
                e.uid,
                e.start,
                e.end,
                e.all_day,
                e.title,
                e.location,
                e.link,
                e.description,
                Jsonb(e.attendees),
                e.my_status,
                e.cancelled,
            ),
        ).fetchone()
        assert row is not None
        keep.append(int(row["id"]))
    conn.execute(
        "DELETE FROM events WHERE calendar_id = %s AND start_at >= %s AND start_at < %s"
        " AND NOT (id = ANY(%s))",
        (calendar_id, start, end, keep),
    )
    return len(keep)


def account(conn: Conn, account_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
    from kb import secrets

    row = conn.execute(
        "SELECT * FROM connector_accounts WHERE id = %s AND kind = 'calendar'", (account_id,)
    ).fetchone()
    if row is None:
        raise CalendarError(f"no calendar account {account_id}")
    return dict(row["settings"]), secrets.unseal(row["secret"])


def sync_calendar(
    conn: Conn,
    cal: dict[str, Any],
    now: datetime,
    owner: set[str],
    transport: httpx.BaseTransport | None = None,
) -> int:
    settings, secret = account(conn, int(cal["account_id"]))
    start, end = window(now)
    if settings["type"] == "ical":
        events = parse_ics(fetch_ics(secret["url"], transport), start, end, owner)
    else:
        client = CalDavClient(settings["username"], secret["password"], settings["base"], transport)
        mine = owner | {settings["username"].lower()}
        events = [
            e
            for data in client.events(cal["href"], start, end)
            for e in parse_ics(data, start, end, mine)
        ]
    n = store(conn, int(cal["id"]), events, start, end)
    conn.execute(
        "UPDATE calendars SET synced_at = %s, error = NULL WHERE id = %s", (now, cal["id"])
    )
    return n


def sync_due(
    conn: Conn, now: datetime, owner: set[str], transport: httpx.BaseTransport | None = None
) -> int:
    """Marked calendars not synced in the last 10 minutes; a failing one records its error."""
    n = 0
    for cal in conn.execute(
        "SELECT c.* FROM calendars c JOIN connector_accounts a ON a.id = c.account_id"
        " WHERE c.sync AND a.state = 'active' AND (c.synced_at IS NULL OR c.synced_at < %s)",
        (now - SYNC_EVERY,),
    ).fetchall():
        try:
            n += sync_calendar(conn, dict(cal), now, owner, transport)
        except Exception as e:
            log.warning("calendar %s failed: %s", cal["id"], e)
            conn.execute(
                "UPDATE calendars SET synced_at = %s, error = %s WHERE id = %s",
                (now, str(e)[:300], cal["id"]),
            )
    return n


def connect_ical(
    conn: Conn, url: str, name: str, transport: httpx.BaseTransport | None = None
) -> int:
    """One Google (or any iCal) calendar by its secret address; the address is sealed."""
    from kb import secrets

    data = fetch_ics(url, transport)
    import icalendar

    cal_name = name.strip() or str(icalendar.Calendar.from_ical(data).get("X-WR-CALNAME") or "")
    row = conn.execute(
        "INSERT INTO connector_accounts (kind, label, settings, secret)"
        " VALUES ('calendar', %s, %s, %s) RETURNING id",
        (cal_name or "Calendar", Jsonb({"type": "ical"}), secrets.seal({"url": url.strip()})),
    ).fetchone()
    assert row is not None
    conn.execute(
        "INSERT INTO calendars (account_id, href, name) VALUES (%s, %s, %s)",
        (row["id"], f"ical:{row['id']}", cal_name or "Calendar"),
    )
    return int(row["id"])


def connect_caldav(
    conn: Conn,
    username: str,
    password: str,
    base: str = ICLOUD,
    transport: httpx.BaseTransport | None = None,
) -> int:
    """An iCloud (or other CalDAV) account; its calendars are listed for marking."""
    from kb import secrets

    found = CalDavClient(username, password, base, transport).calendars()
    if not found:
        raise CalendarError("no calendars found for this account")
    row = conn.execute(
        "INSERT INTO connector_accounts (kind, label, settings, secret)"
        " VALUES ('calendar', %s, %s, %s) RETURNING id",
        (
            username,
            Jsonb({"type": "caldav", "username": username, "base": base}),
            secrets.seal({"password": password}),
        ),
    ).fetchone()
    assert row is not None
    for href, name in found:
        conn.execute(
            "INSERT INTO calendars (account_id, href, name) VALUES (%s, %s, %s)"
            " ON CONFLICT (account_id, href) DO UPDATE SET name = EXCLUDED.name",
            (row["id"], href, name),
        )
    return int(row["id"])
