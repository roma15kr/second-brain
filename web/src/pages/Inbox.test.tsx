import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockApi, renderApp } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState({}, "", "/");
});

const me = { signed_in: true, has_passkeys: true, needs_passkey: false };
const item = (id: number, title: string, action = "") => ({
  item_id: id,
  title,
  summary: "",
  action,
  reason: "",
  sender: "olga@dealer.example",
  scopes: ["rdim"],
  link: "https://mail.google.com/x",
  last_activity_at: "2026-10-20T08:00:00Z",
});

test("inbox groups the pass and actions call the API, then refresh", async () => {
  window.history.pushState({}, "", "/inbox");
  let done = false;
  const groups = () => ({
    needs_reply: done ? [] : [item(7, "Delivery terms", "Answer Olga")],
    important: [],
    fyi: [],
    noise: [item(9, "Weekly newsletter")],
  });
  const calls = mockApi({
    "GET /api/auth/me": me,
    "GET /api/inbox": () => ({
      pass: {
        id: 3,
        headline: "Mail revision: 1 needs your reply",
        created_at: "2026-10-20T08:00:00Z",
      },
      groups: groups(),
    }),
    "POST /api/inbox/7/done": () => {
      done = true;
      return { ok: true };
    },
    "POST /api/senders/pref": { ok: true },
  });
  renderApp();
  expect(await screen.findByText("Needs reply (1)")).toBeInTheDocument();
  expect(screen.getByText("→ Answer Olga")).toBeInTheDocument();
  expect(screen.getByText("Noise (1)")).toBeInTheDocument(); // collapsed group
  await userEvent.click(screen.getAllByRole("button", { name: "Sender is noise" })[0]);
  const pref = calls.find((c) => c.path === "/api/senders/pref");
  expect(JSON.parse(String(pref?.init?.body))).toEqual({
    address: "olga@dealer.example",
    pref: "noise",
  });
  await userEvent.click(screen.getAllByRole("button", { name: "Done" })[0]);
  await waitFor(() => expect(screen.queryByText("Needs reply (1)")).not.toBeInTheDocument());
});

test("snooze sends a future time", async () => {
  window.history.pushState({}, "", "/inbox");
  const calls = mockApi({
    "GET /api/auth/me": me,
    "GET /api/inbox": {
      pass: { id: 3, headline: "h", created_at: "2026-10-20T08:00:00Z" },
      groups: { needs_reply: [item(7, "Terms", "Answer")], important: [], fyi: [], noise: [] },
    },
    "POST /api/inbox/7/snooze": { ok: true },
  });
  renderApp();
  await userEvent.click(await screen.findByRole("button", { name: "Snooze to tomorrow" }));
  const call = calls.find((c) => c.path === "/api/inbox/7/snooze");
  const until = new Date(JSON.parse(String(call?.init?.body)).until);
  expect(until.getTime()).toBeGreaterThan(Date.now());
});
