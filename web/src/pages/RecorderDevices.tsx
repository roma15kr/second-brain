import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { kyivTime } from "../briefs/BriefView";
import { useProjects } from "../shell/useProjects";

type Device = {
  id: number;
  name: string;
  platform: string;
  default_scope: string;
  created_at: string;
  last_seen_at: string | null;
};

// Settings › Recorder apps: pair the macOS / iOS recorder apps with a one-time code; revoke.
export function RecorderDevices() {
  const queryClient = useQueryClient();
  const projects = useProjects();
  const list = useQuery({
    queryKey: ["recorder-devices"],
    queryFn: () => api<{ devices: Device[] }>("/api/settings/devices"),
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["recorder-devices"] });
  const [code, setCode] = useState<{ code: string; expires_at: string } | null>(null);
  const newCode = useMutation({
    mutationFn: () =>
      api<{ code: string; expires_at: string }>("/api/settings/devices/pair-code", {
        method: "POST",
      }),
    onSuccess: setCode,
  });
  const revoke = useMutation({
    mutationFn: (id: number) => api(`/api/settings/devices/${id}`, { method: "DELETE" }),
    onSuccess: refresh,
  });
  const mark = useMutation({
    mutationFn: ({ id, scope }: { id: number; scope: string }) =>
      api(`/api/settings/devices/${id}`, { method: "POST", body: { default_scope: scope } }),
    onSuccess: refresh,
  });
  return (
    <>
      <p className="muted">
        The recorder apps deliver call and meeting transcripts and voice notes here. A device can
        only upload; it cannot read your knowledge base.
      </p>
      <div className="row">
        <button className="btn" onClick={() => newCode.mutate()}>
          Pair a device
        </button>
        {code && (
          <span>
            Code <strong className="pair-code">{code.code}</strong>{" "}
            <span className="muted">
              (enter it in the app; valid until {kyivTime.format(new Date(code.expires_at))})
            </span>
          </span>
        )}
      </div>
      <ul className="list">
        {list.data?.devices.map((d) => (
          <li key={d.id}>
            {d.name} <span className="muted">{d.platform}</span>
            <span className="muted">
              {" "}
              · last seen {d.last_seen_at ? kyivTime.format(new Date(d.last_seen_at)) : "never"}
            </span>{" "}
            <select
              aria-label={`Default mark for ${d.name}`}
              className="btn"
              value={d.default_scope}
              onChange={(e) => mark.mutate({ id: d.id, scope: e.target.value })}
            >
              {[...projects, "unsorted"].map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>{" "}
            <button className="btn" onClick={() => revoke.mutate(d.id)}>
              Revoke
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}
