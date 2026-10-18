import { startRegistration } from "@simplewebauthn/browser";
import { api } from "../api/client";

// Registers a passkey on this device; returns recovery codes when it was the first passkey.
export async function addPasskey(setupCode?: string): Promise<string[]> {
  const optionsJSON = await api<Parameters<typeof startRegistration>[0]["optionsJSON"]>(
    "/api/auth/register/begin",
    { method: "POST", body: setupCode ? { setup_code: setupCode } : {} },
  );
  const credential = await startRegistration({ optionsJSON });
  const r = await api<{ recovery_codes: string[] }>("/api/auth/register/finish", {
    method: "POST",
    body: { credential },
  });
  return r.recovery_codes ?? [];
}
