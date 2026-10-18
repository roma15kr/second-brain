import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { addPasskey } from "./passkey";

// After a recovery-code sign-in the owner is asked to register a passkey (web-access spec).
export function NeedsPasskey() {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="note banner" role="alert">
      You signed in with a recovery code. Add a passkey on this device now.{" "}
      <button
        className="btn primary"
        onClick={() =>
          addPasskey()
            .then(() => queryClient.invalidateQueries({ queryKey: ["me"] }))
            .catch((e: Error) => setError(e.message))
        }
      >
        Add passkey
      </button>
      {error && <div className="error">{error}</div>}
    </div>
  );
}
