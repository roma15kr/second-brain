import { startAuthentication, startRegistration } from "@simplewebauthn/browser";
import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api } from "../api/client";

// Sign-in screen: passkey only (web-access spec). The first passkey needs the server's setup code.
export function SignIn({ hasPasskeys }: { hasPasskeys: boolean }) {
  const queryClient = useQueryClient();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(step: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await step();
      await queryClient.invalidateQueries({ queryKey: ["me"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const signIn = () =>
    run(async () => {
      const optionsJSON = await api<Parameters<typeof startAuthentication>[0]["optionsJSON"]>(
        "/api/auth/login/begin",
        { method: "POST" },
      );
      const credential = await startAuthentication({ optionsJSON });
      await api("/api/auth/login/finish", { method: "POST", body: { credential } });
    });

  const enroll = (e: FormEvent) => {
    e.preventDefault();
    return run(async () => {
      const optionsJSON = await api<Parameters<typeof startRegistration>[0]["optionsJSON"]>(
        "/api/auth/register/begin",
        { method: "POST", body: { setup_code: code } },
      );
      const credential = await startRegistration({ optionsJSON });
      await api("/api/auth/register/finish", { method: "POST", body: { credential } });
    });
  };

  return (
    <main className="signin">
      <div className="card">
        <h1>Second brain</h1>
        {hasPasskeys ? (
          <button className="btn primary" onClick={signIn} disabled={busy}>
            Sign in with passkey
          </button>
        ) : (
          <form onSubmit={enroll}>
            <p className="muted">
              First start: run <code>kb web setup-code</code> on the server and enter the code to
              create your passkey.
            </p>
            <label>
              Setup code
              <input
                value={code}
                onChange={(e) => setCode(e.target.value)}
                autoComplete="one-time-code"
              />
            </label>
            <button className="btn primary" type="submit" disabled={busy || !code}>
              Create passkey
            </button>
          </form>
        )}
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
      </div>
    </main>
  );
}
