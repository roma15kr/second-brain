import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { api } from "../api/client";
import { ScopeTag } from "../shell/ScopeTag";
import { AudioTranscript, type Track } from "./AudioPlayer";
import { EditLocalMeeting, LinkRecording, NewMeeting } from "./MeetingLinking";

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
  recordings?: Recording[];
  local?: boolean;
};

export type Recording = {
  id: number;
  kind: string;
  source: string;
  title: string;
  event_id: number | null;
  started_at: string;
  ended_at: string;
  segments: { speaker: string; is_owner: boolean; start: number; end: number; text: string }[];
  scopes: string[];
  notes: string;
  item_id: number | null;
  result: {
    summary: string;
    decisions: string[];
    actions: { text: string; owner: string; is_me: boolean; due: string | null }[];
  } | null;
  processed: boolean;
  audio?: Track[];
  transcription?: { status: string; error: string | null; finished_at: string | null } | null;
};

// The last cloud transcription of a recording (the Mac's "Cloud" mode or "Separate speakers").
function CloudTranscription({ job }: { job: Recording["transcription"] }) {
  if (!job || job.status === "done") return null;
  if (job.status === "failed") {
    return job.error === "replaced by the Mac transcript" ? null : (
      <p className="error">Cloud transcription failed: {job.error}</p>
    );
  }
  return <p className="muted">Transcribing in the cloud…</p>;
}

export function RecordingView({ r, onChanged }: { r: Recording; onChanged: () => void }) {
  return (
    <section className="recording">
      <h3>
        {r.kind === "notes" ? "Notes" : `${r.source || "Recording"}`}{" "}
        <span className="muted small">{day.format(new Date(r.started_at))}</span>
      </h3>
      <LinkRecording r={r} onChanged={onChanged} />
      <CloudTranscription job={r.transcription} />
      {r.result ? (
        <>
          <p>{r.result.summary}</p>
          {r.result.decisions.length > 0 && (
            <>
              <h4>Decisions</h4>
              <ul>
                {r.result.decisions.map((d) => (
                  <li key={d}>{d}</li>
                ))}
              </ul>
            </>
          )}
          {r.result.actions.length > 0 && (
            <>
              <h4>Actions</h4>
              <ul>
                {r.result.actions.map((a) => (
                  <li key={a.text}>
                    {a.text} <span className="muted">· {a.is_me ? "you" : a.owner}</span>
                    {a.due && <span className="muted"> · {a.due}</span>}
                  </li>
                ))}
              </ul>
              <p className="muted small">
                Your actions are in <Link to="/loops">Loops</Link>; the team's are task drafts in
                the <Link to="/assistant">Assistant</Link> queue.
              </p>
            </>
          )}
        </>
      ) : (
        <p className="muted">{r.processed ? "Not processed." : "Processing…"}</p>
      )}
      {r.segments.length > 0 || (r.audio ?? []).length > 0 ? (
        <details open={(r.audio ?? []).some((t) => t.available)}>
          <summary>
            {(r.audio ?? []).some((t) => t.available) ? "Listen" : "Transcript"} (
            {r.segments.length} lines)
          </summary>
          <AudioTranscript
            recordingId={r.id}
            tracks={r.audio ?? []}
            segments={r.segments}
            onDeleted={onChanged}
          />
        </details>
      ) : null}
      {r.notes && <div className="answer">{r.notes}</div>}
    </section>
  );
}

function AttachNotes({ id, onDone }: { id: number; onDone: () => void }) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const send = useMutation({
    mutationFn: (body: unknown) => api(`/api/meetings/${id}/notes`, { method: "POST", body }),
    onSuccess: () => {
      setText("");
      onDone();
    },
    onError: (e) => setError(e.message),
  });
  const onFile = async (f: File | undefined) => {
    if (!f) return;
    const bytes = new Uint8Array(await f.arrayBuffer());
    let bin = "";
    bytes.forEach((b) => (bin += String.fromCharCode(b)));
    send.mutate({ file: { filename: f.name, data: btoa(bin) } });
  };
  return (
    <details>
      <summary>Attach notes or a transcript</summary>
      <textarea
        aria-label="Meeting notes"
        className="btn wide"
        rows={5}
        value={text}
        placeholder="Paste notes…"
        onChange={(e) => setText(e.target.value)}
      />
      <div className="row">
        <button className="btn" disabled={!text.trim()} onClick={() => send.mutate({ text })}>
          Attach notes
        </button>
        <input
          aria-label="Notes file"
          type="file"
          accept=".txt,.md,.vtt,.srt,.docx"
          onChange={(e) => void onFile(e.target.files?.[0])}
        />
      </div>
      {error && <p className="error">{error}</p>}
    </details>
  );
}

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

function Calls() {
  const q = useQuery({
    queryKey: ["unscheduled-calls"],
    queryFn: () => api<{ recordings: Recording[] }>("/api/recordings?unscheduled=true"),
  });
  if (!q.data?.recordings.length) return null;
  return (
    <section className="card group">
      <h3>Calls without a calendar event</h3>
      <ul className="list">
        {q.data.recordings.slice(0, 10).map((r) => (
          <li key={r.id}>
            <Link to={`/recordings/${r.id}`}>{r.title}</Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function RecordingPage() {
  const { id } = useParams();
  const q = useQuery({
    queryKey: ["recording", id],
    queryFn: () => api<Recording>(`/api/recordings/${id}`),
  });
  if (q.isPending) return <p className="muted">Loading…</p>;
  if (q.isError) return <p className="error">{q.error.message}</p>;
  return (
    <article className="card">
      <h2>{q.data.title}</h2>
      <RecordingView r={q.data} onChanged={() => void q.refetch()} />
    </article>
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
      <>
        <NewMeeting />
        <p className="muted">
          No meetings in the next 7 days. <Link to="/connectors/calendars">Connect calendars</Link>
        </p>
        <Calls />
      </>
    );
  const byDay = new Map<string, Meeting[]>();
  for (const m of q.data.meetings) {
    const d = day.format(new Date(m.start));
    byDay.set(d, [...(byDay.get(d) ?? []), m]);
  }
  return (
    <>
      <NewMeeting />
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
      <Calls />
    </>
  );
}

// One meeting: time, place, attendees linked to People.
export function MeetingPage() {
  const { id } = useParams();
  const queryClient = useQueryClient();
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
      {m.local && (
        <EditLocalMeeting
          m={m}
          onChanged={() => void queryClient.invalidateQueries({ queryKey: ["meeting", id] })}
        />
      )}
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
      {(m.recordings ?? []).map((r) => (
        <RecordingView
          key={r.id}
          r={r}
          onChanged={() => void queryClient.invalidateQueries({ queryKey: ["meeting", id] })}
        />
      ))}
      <AttachNotes
        id={m.id}
        onDone={() => void queryClient.invalidateQueries({ queryKey: ["meeting", id] })}
      />
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
