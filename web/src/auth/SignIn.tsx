import { startAuthentication } from "@simplewebauthn/browser";
import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { addPasskey } from "./passkey";
import { RecoveryCodes } from "./RecoveryCodes";

// Sign-in screen: passkey only (web-access spec). The first passkey needs the server's setup
// code; a recovery code signs in once and then asks for a new passkey.
export function SignIn({ hasPasskeys }: { hasPasskeys: boolean }) {
  const queryClient = useQueryClient();
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState("");
  const [showRecovery, setShowRecovery] = useState(false);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["me"] });

  async function run(step: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await step();
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
      await refresh();
    });

  const enroll = (e: FormEvent) => {
    e.preventDefault();
    return run(async () => {
      const recoveryCodes = await addPasskey(code);
      if (recoveryCodes.length) setCodes(recoveryCodes);
      else await refresh();
    });
  };

  const recover = (e: FormEvent) => {
    e.preventDefault();
    return run(async () => {
      await api("/api/auth/recover", { method: "POST", body: { code: recovery } });
      await refresh();
    });
  };

  return (
    <main className="signin">
      <div className="card">
        <h1>Second brain</h1>
        {codes ? (
          <RecoveryCodes codes={codes} onDone={() => void refresh()} />
        ) : hasPasskeys ? (
          <>
            <button className="btn primary" onClick={signIn} disabled={busy}>
              Sign in with passkey
            </button>
            {showRecovery ? (
              <form onSubmit={recover}>
                <label>
                  Recovery code
                  <input
                    value={recovery}
                    onChange={(e) => setRecovery(e.target.value)}
                    autoComplete="off"
                  />
                </label>
                <button className="btn" type="submit" disabled={busy || !recovery}>
                  Sign in with recovery code
                </button>
              </form>
            ) : (
              <button className="btn" onClick={() => setShowRecovery(true)}>
                Lost your device? Use a recovery code
              </button>
            )}
          </>
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
