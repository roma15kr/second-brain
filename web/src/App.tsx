import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router";
import { SignIn } from "./auth/SignIn";
import { useMe } from "./auth/useMe";
import { BriefPage } from "./pages/BriefPage";
import { Briefs } from "./pages/Briefs";
import { Conversation } from "./pages/Conversation";
import { Inbox } from "./pages/Inbox";
import { Loops } from "./pages/Loops";
import { People } from "./pages/People";
import { Person } from "./pages/Person";
import { Scope } from "./pages/Scope";
import { Search } from "./pages/Search";
import { Settings } from "./pages/Settings";
import { Today } from "./pages/Today";
import { Week } from "./pages/Week";
import { Notifications } from "./push/Notifications";
import { Shell } from "./shell/Shell";

function Routed() {
  return (
    <Shell>
      <Routes>
        <Route
          path="/"
          element={
            <>
              <Notifications />
              <Today />
            </>
          }
        />
        <Route path="/inbox" element={<Inbox />} />
        <Route path="/loops" element={<Loops />} />
        <Route path="/briefs" element={<Briefs />} />
        <Route path="/briefs/:id" element={<BriefPage />} />
        <Route path="/week" element={<Week />} />
        <Route path="/search" element={<Search />} />
        <Route path="/c/:id" element={<Conversation />} />
        <Route path="/people" element={<People />} />
        <Route path="/people/:id" element={<Person />} />
        <Route path="/scopes/:scope" element={<Scope />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<p className="muted">Page not found.</p>} />
      </Routes>
    </Shell>
  );
}

function Gate() {
  const me = useMe();
  if (me.isPending) return <p className="muted center">Loading…</p>;
  if (me.isError)
    return <p className="error center">Cannot reach the server: {me.error.message}</p>;
  if (!me.data.signed_in) return <SignIn hasPasskeys={me.data.has_passkeys} />;
  return <Routed />;
}

export function App({ client = new QueryClient() }: { client?: QueryClient }) {
  return (
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <Gate />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
