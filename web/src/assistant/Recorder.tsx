import { useCallback, useEffect, useState } from "react";
import { flush, pendingStore, type Pending } from "./pending";
import { clock, useRecorder } from "./useRecorder";

// Microphone controls: record → upload (retried until the server has it) → dictation id.
export function Recorder({
  onUploaded,
  compact = false,
}: {
  onUploaded: (dictationId: number) => void;
  compact?: boolean;
}) {
  const [waiting, setWaiting] = useState(0);
  const [note, setNote] = useState<string | null>(null);

  const send = useCallback(async () => {
    const ids = await flush();
    ids.forEach((id) => onUploaded(id));
    setWaiting((await pendingStore().all()).length);
  }, [onUploaded]);

  const onDone = useCallback(
    (p: Pending, why?: string) => {
      setNote(why ?? null);
      void pendingStore().put(p).then(send);
    },
    [send],
  );
  const r = useRecorder(onDone);

  // recordings left from an earlier visit or a lost connection
  useEffect(() => {
    const first = setTimeout(() => void send(), 0);
    const online = () => void send();
    window.addEventListener("online", online);
    return () => {
      clearTimeout(first);
      window.removeEventListener("online", online);
    };
  }, [send]);

  const recording = r.state === "recording" || r.state === "paused";
  return (
    <div className="row recorder">
      {recording ? (
        <>
          <span className="rec-dot" aria-hidden />{" "}
          <span aria-label="Recording time">{clock(r.seconds)}</span>
          <button type="button" className="btn" onClick={r.pause}>
            {r.state === "paused" ? "Resume" : "Pause"}
          </button>
          <button type="button" className="btn primary" onClick={r.stop}>
            Stop
          </button>
        </>
      ) : (
        <button
          type="button"
          className="btn"
          aria-label={compact ? "Dictate" : undefined}
          onClick={() => void r.start()}
        >
          🎙{compact ? "" : " Dictate"}
        </button>
      )}
      {waiting > 0 && (
        <span className="muted">
          {waiting} waiting to upload{" "}
          <button type="button" className="btn" onClick={() => void send()}>
            Retry
          </button>
        </span>
      )}
      {note && <span className="muted">{note}</span>}
      {r.error && <span className="error">{r.error}</span>}
    </div>
  );
}
