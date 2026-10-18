import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SignIn } from "./auth/SignIn";
import { useMe } from "./auth/useMe";

function Gate() {
  const me = useMe();
  if (me.isPending) return <p className="muted center">Loading…</p>;
  if (me.isError)
    return <p className="error center">Cannot reach the server: {me.error.message}</p>;
  if (!me.data.signed_in) return <SignIn hasPasskeys={me.data.has_passkeys} />;
  return <h1>Second brain</h1>;
}

export function App({ client = new QueryClient() }: { client?: QueryClient }) {
  return (
    <QueryClientProvider client={client}>
      <Gate />
    </QueryClientProvider>
  );
}
