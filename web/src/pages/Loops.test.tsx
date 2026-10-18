import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockApi, renderApp } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState({}, "", "/");
});

const me = { signed_in: true, has_passkeys: true, needs_passkey: false };
const loop = (id: number, title: string, extra = {}) => ({
  id,
  kind: "owed_to_me",
  title,
  counterpart: "Олена",
  scopes: ["quokka"],
  status: "open",
  due_date: "2026-10-21",
  overdue: true,
  due_today: false,
  age_days: 3,
  link: "https://t.me/c/1/2",
  ...extra,
});

test("loops page shows overdue promises and snoozing removes them", async () => {
  window.history.pushState({}, "", "/loops");
  let snoozed = false;
  const calls = mockApi({
    "GET /api/auth/me": me,
    "GET /api/loops?status=open": () => ({
      loops: snoozed ? [] : [loop(5, "Customs documents")],
      open_counts: { owed_to_me: snoozed ? 0 : 1 },
    }),
    "POST /api/loops/5/act": (init?: RequestInit) => {
      snoozed = JSON.parse(String(init?.body)).action === "snooze";
      return { ok: true };
    },
  });
  renderApp();
  expect(await screen.findByText("Customs documents")).toBeInTheDocument();
  expect(screen.getByText("· overdue since 2026-10-21")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Snooze to Monday" }));
  await waitFor(() => expect(screen.queryByText("Customs documents")).not.toBeInTheDocument());
  const body = JSON.parse(String(calls.find((c) => c.path === "/api/loops/5/act")?.init?.body));
  expect(body.action).toBe("snooze");
  expect(body.until).toMatch(/^\d{4}-\d{2}-\d{2}$/);
});

test("filters by direction and scope build the query", async () => {
  window.history.pushState({}, "", "/loops");
  const calls = mockApi({
    "GET /api/auth/me": me,
    "GET /api/loops?status=open": { loops: [], open_counts: { i_owe: 2 } },
    "GET /api/loops?status=open&kind=i_owe": { loops: [], open_counts: {} },
    "GET /api/loops?status=open&kind=i_owe&scope=rdim": {
      loops: [loop(6, "Send price list", { kind: "i_owe", scopes: ["rdim"], overdue: false })],
      open_counts: {},
    },
  });
  renderApp();
  await userEvent.click(await screen.findByRole("button", { name: "I owe 2" }));
  await userEvent.selectOptions(screen.getByLabelText("Scope"), "rdim");
  expect(await screen.findByText("Send price list")).toBeInTheDocument();
  expect(calls.some((c) => c.path === "/api/loops?status=open&kind=i_owe&scope=rdim")).toBe(true);
});

test("adding a manual loop posts its title", async () => {
  window.history.pushState({}, "", "/loops");
  const calls = mockApi({
    "GET /api/auth/me": me,
    "GET /api/loops?status=open": { loops: [], open_counts: {} },
    "POST /api/loops": { id: 9 },
  });
  renderApp();
  await userEvent.type(await screen.findByLabelText("New loop"), "Renew the domain");
  await userEvent.click(screen.getByRole("button", { name: "Add" }));
  await waitFor(() =>
    expect(calls.some((c) => c.path === "/api/loops" && c.method === "POST")).toBe(true),
  );
  const post = calls.find((c) => c.path === "/api/loops" && c.method === "POST");
  expect(JSON.parse(String(post?.init?.body))).toEqual({ title: "Renew the domain" });
});
