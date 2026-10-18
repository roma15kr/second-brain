import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockApi, renderApp } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState({}, "", "/");
});

const me = { signed_in: true, has_passkeys: true, needs_passkey: false };
const dialog = (chat_id: number, title: string, scopes: string[] = []) => ({
  chat_id,
  title,
  username: null,
  type: "channel",
  last_message_at: "2026-10-20T07:00:00Z",
  scopes,
  messages_7d: 9,
});

test("new dialogs wait under To mark and can be included with a project", async () => {
  window.history.pushState({}, "", "/connectors/telegram");
  let included = false;
  const calls = mockApi({
    "GET /api/auth/me": me,
    "GET /api/briefs": { briefs: [] },
    "GET /api/projects": {
      projects: ["personal", "quokka"].map((name) => ({ name, label: name, archived: false })),
    },
    "GET /api/connectors/telegram": () => ({
      to_mark: included ? [] : [dialog(-1004444, "Quokka · Marketplaces")],
      included: included ? [dialog(-1004444, "Quokka · Marketplaces", ["quokka"])] : [],
      ignored: [],
      self_ids: ["111"],
      login: null,
    }),
    "POST /api/connectors/telegram/dialogs/-1004444": () => {
      included = true;
      return { rescoped_messages: 0 };
    },
  });
  renderApp();
  await userEvent.click(await screen.findByRole("button", { name: "Include as quokka" }));
  await waitFor(() => expect(screen.getByText("Included (1)")).toBeInTheDocument());
  const body = JSON.parse(
    String(calls.find((c) => c.path.startsWith("/api/connectors/telegram/dialogs"))?.init?.body),
  );
  expect(body).toEqual({ included: true, scopes: ["quokka"] });
});

test("QR login shows the code from the server", async () => {
  window.history.pushState({}, "", "/connectors/telegram");
  mockApi({
    "GET /api/auth/me": me,
    "GET /api/briefs": { briefs: [] },
    "GET /api/projects": { projects: [] },
    "GET /api/connectors/telegram": {
      to_mark: [],
      included: [],
      ignored: [],
      self_ids: [],
      login: { id: 3, status: "qr", error: null, qr_svg: '<svg data-testid="qr"></svg>' },
    },
    "GET /api/connectors/telegram/login/3": {
      id: 3,
      status: "qr",
      error: null,
      qr_svg: '<svg data-testid="qr"></svg>',
    },
  });
  renderApp();
  expect(await screen.findByText(/Link Desktop Device/)).toBeInTheDocument();
  expect(screen.getByTestId("qr")).toBeInTheDocument();
});
