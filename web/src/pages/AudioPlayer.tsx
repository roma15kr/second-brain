import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";

export type Track = {
  track: "owner" | "others" | "mixed";
  available: boolean;
  deleted_at: string | null;
  expires_at: string;
  bytes: number;
};
type Segment = { speaker: string; start: number; end: number; text: string };

const LABEL = { owner: "Me", others: "Others", mixed: "Mixed" };

function mmss(s: number): string {
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

// Listening alongside the transcript (calendar-meetings spec): tap a line to play from there;
// the line being played is highlighted. Audio is streamed with HTTP Range from the owner's
// session only.
export function AudioTranscript({
  recordingId,
  tracks,
  segments,
  onDeleted,
}: {
  recordingId: number;
  tracks: Track[];
  segments: Segment[];
  onDeleted: () => void;
}) {
  const available = tracks.filter((t) => t.available).map((t) => t.track);
  const both = available.includes("owner") && available.includes("others");
  const choices = [...available, ...(both ? (["both"] as const) : [])];
  const [choice, setChoice] = useState<string>(
    available.includes("mixed") ? "mixed" : (choices[0] ?? ""),
  );
  const [now, setNow] = useState(0);
  const main = useRef<HTMLAudioElement>(null);
  const second = useRef<HTMLAudioElement>(null);
  const del = useMutation({
    mutationFn: () => api(`/api/recordings/${recordingId}/audio`, { method: "DELETE" }),
    onSuccess: onDeleted,
  });
  const primary = choice === "both" ? "owner" : choice;
  const url = (t: string) => `/api/recordings/${recordingId}/audio/${t}`;

  // the second track follows the first (play, pause, seek)
  useEffect(() => {
    const a = main.current;
    const b = second.current;
    if (!a || !b) return;
    const sync = () => {
      if (Math.abs(b.currentTime - a.currentTime) > 0.3) b.currentTime = a.currentTime;
    };
    const play = () => void b.play().catch(() => undefined);
    const pause = () => b.pause();
    a.addEventListener("play", play);
    a.addEventListener("pause", pause);
    a.addEventListener("seeked", sync);
    return () => {
      a.removeEventListener("play", play);
      a.removeEventListener("pause", pause);
      a.removeEventListener("seeked", sync);
    };
  }, [choice]);

  const seek = (t: number) => {
    if (!main.current) return;
    main.current.currentTime = t;
    if (second.current) second.current.currentTime = t;
    void main.current.play().catch(() => undefined);
  };
  const deleted = tracks.find((t) => t.deleted_at);
  return (
    <div className="audio">
      {available.length > 0 ? (
        <>
          <div className="row">
            {choices.map((c) => (
              <button
                key={c}
                className={`btn ${choice === c ? "primary" : ""}`}
                onClick={() => setChoice(c)}
              >
                {c === "both" ? "Both" : LABEL[c as Track["track"]]}
              </button>
            ))}
            <a className="btn" href={`${url(primary)}?download=true`}>
              Download
            </a>
            <button className="btn" onClick={() => del.mutate()}>
              Delete audio
            </button>
          </div>
          <audio
            key={primary}
            ref={main}
            aria-label="Recording"
            controls
            preload="metadata"
            src={url(primary)}
            onTimeUpdate={(e) => setNow(e.currentTarget.currentTime)}
          />
          {choice === "both" && <audio key="others" ref={second} src={url("others")} hidden />}
          <p className="muted small">
            Audio is kept until {new Date(tracks[0].expires_at).toLocaleDateString("en-GB")}
          </p>
        </>
      ) : (
        deleted && (
          <p className="muted">
            Audio deleted on {new Date(deleted.deleted_at as string).toLocaleDateString("en-GB")};
            the transcript stays.
          </p>
        )
      )}
      {segments.length > 0 && (
        <ul className="list transcript">
          {segments.map((s, i) => {
            const current = available.length > 0 && now >= s.start && now < s.end;
            return (
              <li
                key={i}
                className={current ? "current" : ""}
                aria-current={current ? "true" : undefined}
              >
                {available.length > 0 ? (
                  <button className="link" onClick={() => seek(s.start)}>
                    {mmss(s.start)}
                  </button>
                ) : (
                  <span className="muted">{mmss(s.start)}</span>
                )}{" "}
                <strong>{s.speaker || "?"}</strong>: {s.text}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
