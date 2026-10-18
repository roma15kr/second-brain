import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, NavLink, Route, Routes } from "react-router";
import { SignIn } from "./auth/SignIn";
import { useMe } from "./auth/useMe";
import { BriefPage } from "./pages/BriefPage";
import { Briefs } from "./pages/Briefs";
import { Inbox } from "./pages/Inbox";
import { Today } from "./pages/Today";
import { Notifications } from "./push/Notifications";

function Shell() {
  return (
    <main className="page">
      <nav className="topnav">
        <NavLink to="/" end>
          Today
        </NavLink>
        <NavLink to="/inbox">Inbox</NavLink>
        <NavLink to="/briefs">Briefs</NavLink>
      </nav>
      <Routes>
        <Route
          path="/"
          element={
            <>
              <h1>Today</h1>
              <Notifications />
              <Today />
            </>
          }
        />
        <Route
          path="/briefs"
          element={
            <>
              <h1>Briefs</h1>
              <Briefs />
            </>
          }
        />
        <Route path="/briefs/:id" element={<BriefPage />} />
        <Route
          path="/inbox"
          element={
            <>
              <h1>Inbox</h1>
              <Inbox />
            </>
          }
        />
        <Route path="*" element={<p className="muted">Page not found.</p>} />
      </Routes>
    </main>
  );
}

function Gate() {
  const me = useMe();
  if (me.isPending) return <p className="muted center">Loading…</p>;
  if (me.isError)
    return <p className="error center">Cannot reach the server: {me.error.message}</p>;
  if (!me.data.signed_in) return <SignIn hasPasskeys={me.data.has_passkeys} />;
  return <Shell />;
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
