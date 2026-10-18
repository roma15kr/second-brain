import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockApi, renderApp } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState({}, "", "/");
});

const me = { signed_in: true, has_passkeys: true, needs_passkey: false };
const base = {
  "GET /api/auth/me": me,
  "GET /api/briefs": { briefs: [] },
  "GET /api/projects": {
    projects: ["personal", "rdim"].map((name) => ({ name, label: name, archived: false })),
  },
};

test("hub shows health, marks, planned connectors and WhatsApp as not possible", async () => {
  window.history.pushState({}, "", "/connectors");
  mockApi({
    ...base,
    "GET /api/connectors": {
      mail: [
        {
          source_id: "mail",
          account_id: null,
          label: "mail",
          address: "digisoftou@gmail.com",
          from_config: true,
          scopes: ["digisoft"],
          healthy: true,
          last_ok: "2026-10-20T08:00:00Z",
          last_error: null,
          items: 625,
        },
        {
          source_id: "mail-1",
          account_id: 1,
          label: "Personal",
          address: "me@personal.example",
          from_config: false,
          scopes: ["personal"],
          healthy: false,
          last_ok: null,
          last_error: "AUTHENTICATIONFAILED",
          items: 0,
        },
      ],
      telegram: [
        {
          source_id: "tg",
          healthy: true,
          last_ok: "2026-10-20T08:00:00Z",
          last_error: null,
          included: 12,
          to_mark: 4,
          items: 2207,
        },
      ],
      catalog: [
        { key: "github", name: "GitHub", state: "planned", adds: "Code, issues and PRs" },
        {
          key: "whatsapp",
          name: "WhatsApp",
          state: "not_possible",
          adds: "No official API; chat-export import is planned",
        },
      ],
    },
  });
  renderApp();
  expect(await screen.findByText("needs attention")).toBeInTheDocument();
  expect(screen.getByText("AUTHENTICATIONFAILED")).toBeInTheDocument();
  expect(screen.getByText("· 4 to mark")).toBeInTheDocument();
  expect(screen.getByText("not possible live")).toBeInTheDocument();
});

test("connecting a mailbox shows the server's login error and keeps the form", async () => {
  window.history.pushState({}, "", "/connectors/mail");
  const calls = mockApi({
    ...base,
    "GET /api/connectors/mail": { mailboxes: [] },
    "GET /api/connectors/mail/senders": { senders: [] },
    "GET /api/settings/rules": { rules: [] },
  });
  renderApp();
  await userEvent.type(await screen.findByLabelText("Email address"), "me@personal.example");
  await userEvent.type(screen.getByLabelText("App password"), "abcd efgh");
  await userEvent.selectOptions(screen.getByLabelText("Default mark"), "personal");
  await userEvent.click(screen.getByRole("button", { name: "Connect" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("not mocked");
  const post = calls.find((c) => c.path === "/api/connectors/mail" && c.method === "POST");
  expect(JSON.parse(String(post?.init?.body)).mailbox).toMatchObject({
    preset: "gmail",
    address: "me@personal.example",
    scopes: ["personal"],
  });
  await waitFor(() =>
    expect(screen.getByLabelText("Email address")).toHaveValue("me@personal.example"),
  );
});
