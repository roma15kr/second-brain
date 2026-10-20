import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { api } from "../api/client";
import { useProjects } from "../shell/useProjects";
import type { Meeting, Recording } from "./Meetings";

const time = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Kyiv",
  weekday: "short",
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

// Participants typed as "Oleh, max@quokka.example"; names are suggested from People.
function ParticipantsInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const last = value.split(",").pop()?.trim() ?? "";
  const people = useQuery({
    queryKey: ["people-suggest", last],
    enabled: last.length >= 2,
    queryFn: () =>
      api<{ people: { id: number; name: string }[] }>(
        `/api/people?q=${encodeURIComponent(last)}&limit=5`,
      ),
  });
  return (
    <>
      <input
        aria-label="Participants"
        className="btn wide-input"
        list="people-suggestions"
        placeholder="Participants: names or emails, comma-separated"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      <datalist id="people-suggestions">
        {(people.data?.people ?? []).map((p) => {
          const head = value.includes(",") ? value.slice(0, value.lastIndexOf(",") + 1) + " " : "";
          return <option key={p.id} value={`${head}${p.name}`} />;
        })}
      </datalist>
    </>
  );
}

export function splitPeople(value: string): string[] {
  return value
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

export function MeetingForm({
  initial,
  withTime,
  submitLabel,
  onSubmit,
}: {
  initial?: { title?: string; scope?: string; participants?: string };
  withTime?: boolean;
  submitLabel: string;
  onSubmit: (v: {
    title: string;
    scope: string;
    participants: string[];
    start?: string;
    end?: string;
  }) => void;
}) {
  const projects = useProjects();
  const [title, setTitle] = useState(initial?.title ?? "");
  const [scope, setScope] = useState(initial?.scope ?? projects[0] ?? "personal");
  const [people, setPeople] = useState(initial?.participants ?? "");
  const now = new Date();
  const local = (d: Date) =>
    new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const [start, setStart] = useState(local(now));
  const [end, setEnd] = useState(local(new Date(now.getTime() + 3600_000)));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit({
      title,
      scope,
      participants: splitPeople(people),
      ...(withTime
        ? { start: new Date(start).toISOString(), end: new Date(end).toISOString() }
        : {}),
    });
  };
  return (
    <form className="meeting-form" onSubmit={submit}>
      <div className="row">
        <input
          aria-label="Meeting title"
          className="btn wide-input"
          placeholder="Title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <select
          aria-label="Project"
          className="btn"
          value={scope}
          onChange={(e) => setScope(e.target.value)}
        >
          {[...projects, "unsorted"].map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </div>
      <ParticipantsInput value={people} onChange={setPeople} />
      {withTime && (
        <div className="row">
          <input
            aria-label="Starts"
            type="datetime-local"
            className="btn"
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
          <input
            aria-label="Ends"
            type="datetime-local"
            className="btn"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
          />
        </div>
      )}
      <button className="btn primary" type="submit" disabled={!title.trim()}>
        {submitLabel}
      </button>
    </form>
  );
}

// On a recording: move it to another meeting, a new meeting, or mark the project of a call.
export function LinkRecording({ r, onChanged }: { r: Recording; onChanged: () => void }) {
  const projects = useProjects();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const near = useQuery({
    queryKey: ["meetings-around", r.started_at],
    enabled: open,
    queryFn: () =>
      api<{ meetings: Meeting[] }>(
        `/api/meetings?around=${encodeURIComponent(r.started_at)}&hours=36`,
      ),
  });
  const link = useMutation({
    mutationFn: (body: unknown) =>
      api<{ event_id: number | null }>(`/api/recordings/${r.id}/link`, { method: "POST", body }),
    onSuccess: (res) => {
      setOpen(false);
      setCreating(false);
      onChanged();
      if (res.event_id && res.event_id !== r.event_id) void navigate(`/meetings/${res.event_id}`);
    },
    onError: (e) => setError(e.message),
  });
  if (!open)
    return (
      <div className="row">
        <button className="btn" onClick={() => setOpen(true)}>
          {r.event_id ? "Change meeting" : "Attach to a meeting"}
        </button>
        {!r.event_id && (
          <select
            aria-label="Project of this call"
            className="btn"
            value={r.scopes[0] ?? ""}
            onChange={(e) => link.mutate({ scope: e.target.value })}
          >
            {[...projects, "unsorted"].map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        )}
      </div>
    );
  return (
    <div className="card">
      <ul className="list">
        {(near.data?.meetings ?? []).map((m) => (
          <li key={m.id}>
            <button className="link" onClick={() => link.mutate({ event_id: m.id })}>
              {time.format(new Date(m.start))} {m.title}
            </button>
            {m.id === r.event_id && <span className="muted"> · current</span>}
          </li>
        ))}
        {near.data && near.data.meetings.length === 0 && (
          <li className="muted">No meetings near this call.</li>
        )}
      </ul>
      <div className="row">
        <button className="btn" onClick={() => setCreating(true)}>
          New meeting…
        </button>
        {r.event_id && (
          <button className="btn" onClick={() => link.mutate({ event_id: null })}>
            Detach from the meeting
          </button>
        )}
        <button className="btn" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
      {creating && (
        <MeetingForm
          submitLabel="Create and attach"
          onSubmit={(v) =>
            link.mutate({
              new_meeting: { title: v.title, scope: v.scope, participants: v.participants },
            })
          }
        />
      )}
      {error && <p className="error">{error}</p>}
    </div>
  );
}

// Meetings page: a meeting that is not in any calendar.
export function NewMeeting() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: (body: unknown) => api<{ id: number }>("/api/meetings", { method: "POST", body }),
    onSuccess: (r) => {
      void queryClient.invalidateQueries({ queryKey: ["meetings"] });
      void navigate(`/meetings/${r.id}`);
    },
    onError: (e) => setError(e.message),
  });
  if (!open)
    return (
      <button className="btn" onClick={() => setOpen(true)}>
        New meeting
      </button>
    );
  return (
    <section className="card">
      <h3>New meeting</h3>
      <MeetingForm withTime submitLabel="Create" onSubmit={(v) => create.mutate(v)} />
      {error && <p className="error">{error}</p>}
    </section>
  );
}

// Meeting page: edit a meeting created in the second brain (calendar meetings are read-only).
export function EditLocalMeeting({ m, onChanged }: { m: Meeting; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (body: unknown) => api(`/api/meetings/${m.id}`, { method: "PATCH", body }),
    onSuccess: () => {
      setOpen(false);
      onChanged();
    },
    onError: (e) => setError(e.message),
  });
  if (!open)
    return (
      <button className="btn" onClick={() => setOpen(true)}>
        Edit meeting
      </button>
    );
  return (
    <>
      <MeetingForm
        initial={{
          title: m.title,
          scope: m.scopes[0],
          participants: m.attendees.map((a) => a.name || a.email).join(", "),
        }}
        submitLabel="Save"
        onSubmit={(v) =>
          save.mutate({ title: v.title, scope: v.scope, participants: v.participants })
        }
      />
      {error && <p className="error">{error}</p>}
    </>
  );
}
