import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { kyivTime } from "../briefs/BriefView";
import { addPasskey } from "./passkey";
import { RecoveryCodes } from "./RecoveryCodes";

type SessionsData = {
  sessions: {
    id: string;
    device: string;
    last_seen_at: string;
    current: boolean;
    recovery: boolean;
  }[];
  passkeys: { id: string; device: string; created_at: string; last_used_at: string | null }[];
  recovery_codes_left: number;
};

// Signing out also drops the offline copy of pages kept by the service worker.
async function signOut() {
  await api("/api/auth/logout", { method: "POST" }).catch(() => {});
  if ("caches" in window) await caches.delete("api-read");
  window.location.assign("/");
}

// Settings › Security: signed-in devices, passkeys and recovery codes (web-access spec).
export function Security() {
  const queryClient = useQueryClient();
  const data = useQuery({
    queryKey: ["sessions"],
    queryFn: () => api<SessionsData>("/api/auth/sessions"),
  });
  const [codes, setCodes] = useState<string[] | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["sessions"] });
  const fail = (e: Error) => setMessage(e.message);
  const revoke = useMutation({
    mutationFn: (id: string) => api(`/api/auth/sessions/${id}/revoke`, { method: "POST" }),
    onSuccess: refresh,
    onError: fail,
  });
  const everywhere = useMutation({
    mutationFn: () =>
      api<{ revoked: number }>("/api/auth/sessions/revoke-others", { method: "POST" }),
    onSuccess: (r) => {
      setMessage(`Signed out ${r.revoked} other device(s).`);
      return refresh();
    },
    onError: fail,
  });
  const regenerate = useMutation({
    mutationFn: () =>
      api<{ recovery_codes: string[] }>("/api/auth/recovery-codes", { method: "POST" }),
    onSuccess: (r) => {
      setCodes(r.recovery_codes);
      return refresh();
    },
    onError: fail,
  });
  const passkey = useMutation({
    mutationFn: () => addPasskey(),
    onSuccess: () => {
      setMessage("Passkey added on this device.");
      return refresh();
    },
    onError: fail,
  });
  if (!data.data) return <p className="muted">Loading…</p>;
  const d = data.data;
  return (
    <section className="card group">
      <h3>Security</h3>
      <h4>Signed-in devices</h4>
      <ul className="list">
        {d.sessions.map((s) => (
          <li key={s.id}>
            {s.device.slice(0, 70) || "Unknown device"}
            {s.current && <strong> · this device</strong>}
            {s.recovery && <span className="error"> · signed in with a recovery code</span>}
            <span className="muted"> · {kyivTime.format(new Date(s.last_seen_at))}</span>{" "}
            {!s.current && (
              <button className="btn" onClick={() => revoke.mutate(s.id)}>
                Sign out
              </button>
            )}
          </li>
        ))}
      </ul>
      <div className="row">
        <button className="btn" onClick={() => everywhere.mutate()}>
          Sign out everywhere else
        </button>
        <button className="btn" onClick={() => void signOut()}>
          Sign out of this device
        </button>
      </div>
      <h4>Passkeys</h4>
      <ul className="list">
        {d.passkeys.map((p) => (
          <li key={p.id}>
            {p.device.slice(0, 70) || "Passkey"}{" "}
            <span className="muted">
              · added {kyivTime.format(new Date(p.created_at))}
              {p.last_used_at && ` · last used ${kyivTime.format(new Date(p.last_used_at))}`}
            </span>
          </li>
        ))}
      </ul>
      <button className="btn" onClick={() => passkey.mutate()}>
        Add a passkey on this device
      </button>
      <h4>Recovery codes</h4>
      {codes ? (
        <RecoveryCodes codes={codes} onDone={() => setCodes(null)} />
      ) : (
        <p>
          {d.recovery_codes_left} of 10 left.{" "}
          <button className="btn" onClick={() => regenerate.mutate()}>
            Generate new codes
          </button>
        </p>
      )}
      {message && (
        <p role="status" className="muted">
          {message}
        </p>
      )}
    </section>
  );
}
