import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes, useParams } from "react-router";
import { NeedsPasskey } from "./auth/NeedsPasskey";
import { CalendarConnector } from "./connectors/CalendarConnector";
import { ClickUpConnector } from "./connectors/ClickUpConnector";
import { MeetingPage, Meetings, RecordingPage } from "./pages/Meetings";
import { Connectors } from "./connectors/Connectors";
import { MailConnector } from "./connectors/MailConnector";
import { TelegramConnector } from "./connectors/TelegramConnector";
import { Security } from "./auth/Security";
import { SignIn } from "./auth/SignIn";
import { useMe } from "./auth/useMe";
import { Assistant } from "./pages/Assistant";
import { Thread } from "./assistant/Thread";
import { BriefPage } from "./pages/BriefPage";
import { Briefs } from "./pages/Briefs";
import { ClickUpUpdates } from "./pages/ClickUpUpdates";
import { Conversation } from "./pages/Conversation";
import { Goals } from "./pages/Goals";
import { Inbox } from "./pages/Inbox";
import { Library } from "./pages/Library";
import { LibraryDoc } from "./pages/LibraryDoc";
import { Loops } from "./pages/Loops";
import { Moderate } from "./pages/Moderate";
import { People } from "./pages/People";
import { Person } from "./pages/Person";
import { Scope } from "./pages/Scope";
import { Search } from "./pages/Search";
import { Settings } from "./pages/Settings";
import { Status } from "./pages/Status";
import { Today } from "./pages/Today";
import { Week } from "./pages/Week";
import { Notifications } from "./push/Notifications";
import { Menu, Shell } from "./shell/Shell";

// old dictation links open the assistant with that dictation
function DictationRedirect() {
  const { id } = useParams();
  return <Navigate to={`/assistant?d=${id}`} replace />;
}

function Routed({ needsPasskey }: { needsPasskey: boolean }) {
  return (
    <Shell>
      {needsPasskey && <NeedsPasskey />}
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
        <Route path="/moderate" element={<Moderate />} />
        <Route path="/menu" element={<Menu />} />
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
        <Route path="/settings" element={<Settings security={<Security />} />} />
        <Route path="/status" element={<Status />} />
        <Route path="/clickup" element={<ClickUpUpdates />} />
        <Route path="/assistant" element={<Assistant />} />
        <Route path="/assistant/t/:id" element={<Thread />} />
        <Route path="/dictate" element={<Navigate to="/assistant" replace />} />
        <Route path="/dictate/:id" element={<DictationRedirect />} />
        <Route path="/library" element={<Library goals={<Goals />} />} />
        <Route path="/library/:id" element={<LibraryDoc />} />
        <Route path="/connectors" element={<Connectors />} />
        <Route path="/connectors/mail" element={<MailConnector />} />
        <Route path="/connectors/telegram" element={<TelegramConnector />} />
        <Route path="/connectors/clickup" element={<ClickUpConnector />} />
        <Route path="/connectors/calendars" element={<CalendarConnector />} />
        <Route path="/meetings" element={<Meetings />} />
        <Route path="/meetings/:id" element={<MeetingPage />} />
        <Route path="/recordings/:id" element={<RecordingPage />} />
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
  return <Routed needsPasskey={me.data.needs_passkey} />;
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
