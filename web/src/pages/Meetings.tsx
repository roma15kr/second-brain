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
};

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
    </article>
  );
}
