import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import type { Brief } from "../api/types";
import { BriefView, kyivTime } from "../briefs/BriefView";
import type { Meeting } from "./Meetings";

const hm = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Kyiv",
  hour: "2-digit",
  minute: "2-digit",
});

function MeetingRow({ m, now }: { m: Meeting; now: number }) {
  const past = !m.all_day && new Date(m.end).getTime() < now;
  const when = m.all_day
    ? "all day"
    : `${hm.format(new Date(m.start))}–${hm.format(new Date(m.end))}`;
  return (
    <li className={past ? "past" : ""}>
      <Link to={`/meetings/${m.id}`} className="line">
        {m.title}
      </Link>
      <span className="sub">
        {when}
        {m.attendees.length > 1 && ` · ${m.attendees.length} people`}
        {m.link && !past && (
          <>
            {" · "}
            <a href={m.link} target="_blank" rel="noreferrer">
              Join
            </a>
          </>
        )}
      </span>
    </li>
  );
}

type Mention = { text: string; title: string | null; item_id: number | null; at: string };
type TodayData = {
  brief: Brief | null;
  meetings?: Meeting[];
  moderate?: number;
  mentions?: Mention[];
};

function ModerateCard({ n }: { n: number }) {
  return (
    <Link to="/moderate" className={`card stat${n ? " attention" : ""}`}>
      <span className="stat-n">{n}</span>
      <span>{n === 1 ? "proposal to moderate" : "to moderate"}</span>
    </Link>
  );
}

function Upcoming({ meetings }: { meetings: Meeting[] }) {
  const [now] = useState(() => Date.now()); // the moment the screen opened
  // the rest of today first, then what already happened (dimmed)
  const later = meetings.filter((m) => m.all_day || new Date(m.end).getTime() > now);
  const next = [...later, ...meetings.filter((m) => !later.includes(m))].slice(0, 4);
  return (
    <section className="card">
      <h3 className="card-title">
        Meetings{" "}
        <Link to="/meetings" className="small">
          All
        </Link>
      </h3>
      {next.length ? (
        <ul className="list compact">
          {next.map((m) => (
            <MeetingRow key={m.id} m={m} now={now} />
          ))}
        </ul>
      ) : (
        <p className="muted">No more meetings today.</p>
      )}
    </section>
  );
}

function Mentions({ mentions }: { mentions: Mention[] }) {
  return (
    <section className="card">
      <h3 className="card-title">
        For you and the team{" "}
        <Link to="/clickup" className="small">
          All
        </Link>
      </h3>
      {mentions.length ? (
        <ul className="list compact">
          {mentions.map((m, i) => (
            <li key={i}>
              {m.item_id ? <Link to={`/c/${m.item_id}`}>{m.text}</Link> : <strong>{m.text}</strong>}
              <span className="sub">
                {m.title ? `${m.title} · ` : ""}
                {kyivTime.format(new Date(m.at))}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">No new mentions.</p>
      )}
    </section>
  );
}

// Today (web-redesign-v1): actions first — what to moderate, next meetings, mentions; then the
// short brief.
export function Today() {
  const today = useQuery({ queryKey: ["today"], queryFn: () => api<TodayData>("/api/today") });
  if (today.isPending) return <p className="muted">Loading…</p>;
  if (today.isError) return <p className="error">{today.error.message}</p>;
  const { brief, meetings = [], moderate = 0, mentions = [] } = today.data;
  return (
    <>
      <div className="today-grid">
        <ModerateCard n={moderate} />
        <Upcoming meetings={meetings} />
        <Mentions mentions={mentions} />
      </div>
      <nav className="quick" aria-label="More">
        <Link to="/inbox">Inbox</Link>
        <Link to="/loops">Loops</Link>
        <Link to="/briefs">Briefs</Link>
        <Link to="/week">Week</Link>
      </nav>
      {brief ? (
        <BriefView brief={brief} />
      ) : (
        <p className="muted">No brief yet — the first one arrives at 08:00.</p>
      )}
    </>
  );
}
