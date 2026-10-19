import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { api } from "../api/client";
import { Recorder } from "./Recorder";

export type Created = { id: number; thread_id: number };

export function ask(text: string, threadId?: number): Promise<Created> {
  return api<Created>("/api/assistant/requests", {
    method: "POST",
    body: threadId ? { text, thread_id: threadId } : { text },
  });
}

// Waits for a dictation's transcript (polls; transcription takes a few seconds).
export async function transcript(id: number, tries = 80): Promise<string> {
  for (let i = 0; i < tries; i++) {
    const d = await api<{ status: string; transcript: string | null; error: string | null }>(
      `/api/dictations/${id}`,
    );
    if (d.status === "done") return d.transcript ?? "";
    if (d.status === "failed") throw new Error(d.error ?? "not transcribed");
    await new Promise((r) => setTimeout(r, 1500));
  }
  throw new Error("transcription is taking long; see Dictate");
}

// The request field (assistant-requests: ask from anywhere). A new question opens its thread.
export function AskBox({
  threadId,
  onAsked,
  placeholder = "Ask, draft, find… e.g. “what did we agree with Rozetka about delivery?”",
}: {
  threadId?: number;
  onAsked?: (c: Created) => void;
  placeholder?: string;
}) {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [transcribing, setTranscribing] = useState(false);
  // a voice request: the transcript goes into the field so the owner can check it first
  const onSpoken = (id: number) => {
    setTranscribing(true);
    void transcript(id)
      .then((t) => setText((old) => (old ? `${old} ${t}` : t)))
      .finally(() => setTranscribing(false));
  };
  const send = useMutation({
    mutationFn: () => ask(text.trim(), threadId),
    onSuccess: (c) => {
      setText("");
      if (onAsked) onAsked(c);
      else void navigate(`/assistant/t/${c.thread_id}`);
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (text.trim()) send.mutate();
  };
  return (
    <form className="row ask" onSubmit={submit}>
      <textarea
        aria-label="Ask the assistant"
        className="btn wide"
        rows={2}
        value={text}
        placeholder={placeholder}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) submit(e);
        }}
      />
      <Recorder compact onUploaded={onSpoken} />
      {transcribing && <span className="muted">Transcribing…</span>}
      <button className="btn primary" type="submit" disabled={send.isPending || !text.trim()}>
        Ask
      </button>
      {send.isError && <div className="error">{send.error.message}</div>}
    </form>
  );
}
