import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { api } from "../api/client";
import { ScopeTag } from "../shell/ScopeTag";

export type Meeting = {
  id: number;
  title: string;
  start: string;
  end: string;
  all_day: boolean;
  location: string;
  link: string | null;
  attendees: { email: string; name: string; status: string; person_id?: number | null }[];
  my_status: string | null;
  calendar: string;
  scopes: string[];
  prep?: Prep | null;
};

type Prep = {
  people: { email: string; name: string; person_id: number | null }[];
  conversations: { ref: string; title: string; summary: string; date: string }[];
  loops: {
    ref: string;
    kind: string;
    title: string;
    counterpart: string;
    due_date: string | null;
  }[];
  tasks: { ref: string; title: string; status: string; due: string | null }[];
  goals: { title: string; scope: string }[];
  agenda: { text: string; ref: string }[];
};

function refLink(ref: string): string {
  return ref.startsWith("item:") ? `/c/${ref.slice(5)}` : "/loops";
}

const DIRECTION: Record<string, string> = {
  i_owe: "you promised",
  owed_to_me: "promised to you",
  needs_reply: "waiting for your reply",
  manual: "reminder",
};

function PrepView({ p }: { p: Prep }) {
  return (
    <section className="prep">
      <h3>Prep</h3>
      {p.agenda.length > 0 && (
        <>
          <h4>Suggested agenda</h4>
          <ol>
            {p.agenda.map((a) => (
              <li key={a.text}>
                {a.text} <Link to={refLink(a.ref)}>source</Link>
              </li>
            ))}
          </ol>
        </>
      )}
      {p.loops.length > 0 && (
        <>
          <h4>Open both ways</h4>
          <ul className="list">
            {p.loops.map((l) => (
              <li key={l.ref}>
                {l.title} <span className="muted">· {DIRECTION[l.kind] ?? l.kind}</span>
                {l.due_date && <span className="muted"> · due {l.due_date}</span>}
              </li>
            ))}
          </ul>
        </>
      )}
      {p.conversations.length > 0 && (
        <>
          <h4>Last conversations</h4>
          <ul className="list">
            {p.conversations.map((c) => (
              <li key={c.ref}>
                <Link to={refLink(c.ref)}>{c.title || "(no subject)"}</Link>
                <span className="muted"> · {c.date}</span>
                {c.summary && <div className="muted">{c.summary}</div>}
              </li>
            ))}
          </ul>
        </>
      )}
      {p.tasks.length > 0 && (
        <>
          <h4>Their open ClickUp tasks</h4>
          <ul className="list">
            {p.tasks.map((t) => (
              <li key={t.ref}>
                <Link to={refLink(t.ref)}>{t.title}</Link>
                <span className="muted"> · {t.status}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {p.goals.length > 0 && (
        <p className="muted">Goals: {p.goals.map((g) => g.title).join("; ")}</p>
      )}
    </section>
  );
}

const time = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Kyiv",
  hour: "2-digit",
  minute: "2-digit",
});
const day = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Kyiv",
  weekday: "long",
  day: "numeric",
  month: "long",
});

export function MeetingLine({ m }: { m: Meeting }) {
  return (
    <li className={m.my_status === "DECLINED" ? "muted" : ""}>
      <span className="muted">
        {m.all_day
          ? "all day"
          : `${time.format(new Date(m.start))}–${time.format(new Date(m.end))}`}
      </span>{" "}
      <Link to={`/meetings/${m.id}`}>{m.title}</Link>{" "}
      {m.scopes.map((s) => (
        <ScopeTag key={s} scope={s} />
      ))}
      {m.attendees.length > 1 && <span className="muted"> · {m.attendees.length} people</span>}
      {m.my_status === "DECLINED" && <span className="muted"> · declined</span>}
      {m.link && (
        <>
          {" "}
          <a href={m.link} target="_blank" rel="noreferrer">
            Join
          </a>
        </>
      )}
    </li>
  );
}

// Meetings: the next 7 days from the marked calendars (calendar-meetings spec).
export function Meetings() {
  const q = useQuery({
    queryKey: ["meetings"],
    queryFn: () => api<{ meetings: Meeting[] }>("/api/meetings?days=7"),
  });
  if (q.isPending) return <p className="muted">Loading…</p>;
  if (q.isError) return <p className="error">{q.error.message}</p>;
  if (!q.data.meetings.length)
    return (
      <p className="muted">
        No meetings in the next 7 days. <Link to="/connectors/calendars">Connect calendars</Link>
      </p>
    );
  const byDay = new Map<string, Meeting[]>();
  for (const m of q.data.meetings) {
    const d = day.format(new Date(m.start));
    byDay.set(d, [...(byDay.get(d) ?? []), m]);
  }
  return (
    <>
      {[...byDay].map(([d, ms]) => (
        <section key={d} className="card group">
          <h3>{d}</h3>
          <ul className="list">
            {ms.map((m) => (
              <MeetingLine key={m.id} m={m} />
            ))}
          </ul>
        </section>
      ))}
    </>
  );
}

// One meeting: time, place, attendees linked to People.
export function MeetingPage() {
  const { id } = useParams();
  const q = useQuery({
    queryKey: ["meeting", id],
    queryFn: () => api<Meeting>(`/api/meetings/${id}`),
  });
  if (q.isPending) return <p className="muted">Loading…</p>;
  if (q.isError) return <p className="error">{q.error.message}</p>;
  const m = q.data;
  return (
    <article className="card">
      <h2>{m.title}</h2>
      <p>
        {day.format(new Date(m.start))},{" "}
        {m.all_day
          ? "all day"
          : `${time.format(new Date(m.start))}–${time.format(new Date(m.end))}`}{" "}
        · <span className="muted">{m.calendar}</span>{" "}
        {m.scopes.map((s) => (
          <ScopeTag key={s} scope={s} />
        ))}
      </p>
      {m.location && <p>{m.location}</p>}
      {m.link && (
        <p>
          <a className="btn primary" href={m.link} target="_blank" rel="noreferrer">
            Join the call
          </a>
        </p>
      )}
      {m.attendees.length > 0 && (
        <>
          <h3>Attendees</h3>
          <ul className="list">
            {m.attendees.map((a) => (
              <li key={a.email}>
                {a.person_id ? (
                  <Link to={`/people/${a.person_id}`}>{a.name || a.email}</Link>
                ) : (
                  a.name || a.email
                )}{" "}
                <span className="muted">
                  {a.status.toLowerCase().replace("needs-action", "no reply")}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
      {m.prep ? (
        <PrepView p={m.prep} />
      ) : (
        m.attendees.length > 1 && (
          <p className="muted">
            The prep is ready 30 minutes before (by 07:00 for early meetings).
          </p>
        )
      )}
    </article>
  );
}
