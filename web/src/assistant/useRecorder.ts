import { useCallback, useEffect, useRef, useState } from "react";
import { pendingStore, type Pending } from "./pending";

export const MAX_SECONDS = 15 * 60;
const SLICE_MS = 10_000;
const TYPES = ["audio/webm;codecs=opus", "audio/mp4", "audio/webm", "audio/ogg"];

export function pickMime(): string {
  if (typeof MediaRecorder === "undefined") return "";
  return TYPES.find((t) => MediaRecorder.isTypeSupported?.(t)) ?? "";
}

type State = "idle" | "recording" | "paused" | "stopped";

// Records from the microphone while the app is open (voice-dictation spec). Every 10 s slice is
// saved on the device, so a stop, a locked phone or a crash keeps what was said.
export function useRecorder(onDone: (p: Pending, note?: string) => void) {
  const [state, setState] = useState<State>("idle");
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const rec = useRef<MediaRecorder | null>(null);
  const pending = useRef<Pending | null>(null);
  const note = useRef<string | undefined>(undefined);
  const elapsed = useRef(0);

  const stop = useCallback((why?: string) => {
    if (!rec.current || rec.current.state === "inactive") return;
    note.current = why;
    rec.current.stop();
  }, []);

  const start = useCallback(async () => {
    setError(null);
    if (typeof MediaRecorder === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setError("This browser cannot record audio.");
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setError("Microphone access was not allowed.");
      return;
    }
    const mime = pickMime();
    const r = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
    const p: Pending = {
      key: `d${Date.now()}`,
      chunks: [],
      mime: (r.mimeType || mime || "audio/webm").split(";")[0],
      seconds: 0,
    };
    pending.current = p;
    elapsed.current = 0;
    note.current = undefined;
    r.ondataavailable = (e) => {
      if (e.data.size > 0) {
        p.chunks.push(e.data);
        p.seconds = elapsed.current;
        void pendingStore().put({ ...p, chunks: [...p.chunks] });
      }
    };
    r.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      p.seconds = elapsed.current;
      setState("stopped");
      rec.current = null;
      if (p.chunks.length) onDone({ ...p, chunks: [...p.chunks] }, note.current);
    };
    r.start(SLICE_MS);
    rec.current = r;
    setSeconds(0);
    setState("recording");
  }, [onDone]);

  const pause = useCallback(() => {
    if (rec.current?.state === "recording") {
      rec.current.pause();
      setState("paused");
    } else if (rec.current?.state === "paused") {
      rec.current.resume();
      setState("recording");
    }
  }, []);

  // timer and the 15-minute limit
  useEffect(() => {
    if (state !== "recording") return;
    const t = setInterval(() => {
      elapsed.current += 1;
      setSeconds(elapsed.current);
      if (elapsed.current >= MAX_SECONDS) {
        stop("15-minute limit — start another dictation to continue");
      }
    }, 1000);
    return () => clearInterval(t);
  }, [state, stop]);

  // the browser suspends recording in the background (iPhone): stop and keep what was said
  useEffect(() => {
    const onHide = () => {
      if (document.visibilityState === "hidden") stop();
    };
    document.addEventListener("visibilitychange", onHide);
    return () => document.removeEventListener("visibilitychange", onHide);
  }, [stop]);

  return { state, seconds, error, start, stop: () => stop(), pause };
}

export function clock(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}
