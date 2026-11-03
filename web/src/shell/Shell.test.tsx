import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockApi, renderApp } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState({}, "", "/");
});

const me = { signed_in: true, has_passkeys: true, needs_passkey: false };
const brief = (id: number, opened: boolean) => ({
  id,
  routine: "morning",
  title: "Morning brief",
  headline: `Morning brief ${id}`,
  mode: "ai",
  created_at: "2026-10-20T05:00:00Z",
  opened,
  useful: null,
});

test("the sidebar lists every section in groups; the tab bar centres the assistant", async () => {
  mockApi({
    "GET /api/auth/me": me,
    "GET /api/today": { brief: null, moderate: 3 },
    "GET /api/briefs": { briefs: [] },
  });
  renderApp();
  const side = await screen.findByRole("navigation", { name: "Main" });
  expect([...side.querySelectorAll(".nav-title")].map((t) => t.textContent)).toEqual([
    "Work",
    "Knowledge",
    "Reports",
    "System",
  ]);
  for (const label of [
    "Inbox",
    "Loops",
    "Library",
    "People",
    "Briefs",
    "Week",
    "ClickUp",
    "Connectors",
    "Status",
    "Settings",
  ]) {
    expect(side).toHaveTextContent(label);
  }
  expect(screen.getByRole("link", { name: /Ask or dictate/ })).toHaveAttribute(
    "href",
    "/assistant",
  );
  const tabs = screen.getByRole("navigation", { name: "Tabs" });
  await waitFor(() => expect(tabs.querySelector(".count")).toHaveTextContent("3"));
  expect([...tabs.querySelectorAll("a")].map((a) => a.textContent)).toEqual([
    "Today",
    "Moderate3",
    "Assistant",
    "Meetings",
    "Menu",
  ]);
  expect(side.querySelector("a.active")).toHaveTextContent("Today");
});

test("Menu lists every section on the phone", async () => {
  window.history.pushState({}, "", "/menu");
  mockApi({ "GET /api/auth/me": me, "GET /api/today": { brief: null } });
  renderApp();
  expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Menu");
  const main = screen.getByRole("main");
  for (const label of ["Library", "People", "Connectors", "Status", "Week"]) {
    expect(main.querySelector(`a[href]`)).not.toBeNull();
    expect(main).toHaveTextContent(label);
  }
});

test("a page under a section marks it", async () => {
  window.history.pushState({}, "", "/recordings/4");
  mockApi({ "GET /api/auth/me": me, "GET /api/today": { brief: null } });
  renderApp();
  const side = await screen.findByRole("navigation", { name: "Main" });
  expect(side.querySelector("a.active")).toHaveTextContent("Meetings");
});

test("⌘K palette jumps to a person", async () => {
  mockApi({
    "GET /api/auth/me": me,
    "GET /api/today": { brief: null },
    "GET /api/briefs": { briefs: [] },
    "GET /api/people?q=%D0%92%D1%8F%D1%87%D0%B5%D1%81%D0%BB%D0%B0%D0%B2&limit=5": {
      people: [{ id: 5, name: "Вячеслав" }],
    },
    "GET /api/search?q=%D0%92%D1%8F%D1%87%D0%B5%D1%81%D0%BB%D0%B0%D0%B2&limit=5": { results: [] },
  });
  renderApp();
  await screen.findByRole("navigation", { name: "Main" });
  await userEvent.keyboard("{Meta>}k{/Meta}");
  const input = await screen.findByLabelText("Search or jump to");
  await userEvent.type(input, "Вячеслав");
  expect(await screen.findByRole("option", { name: /👤 Вячеслав/ })).toBeInTheDocument();
  await userEvent.keyboard("{Enter}");
  await waitFor(() => expect(window.location.pathname).toBe("/people/5"));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("palette offers pages and a full search; Escape closes it", async () => {
  mockApi({
    "GET /api/auth/me": me,
    "GET /api/today": { brief: null },
    "GET /api/briefs": { briefs: [] },
  });
  renderApp();
  await userEvent.click(await screen.findByRole("button", { name: /Search or jump to/ }));
  await userEvent.type(screen.getByLabelText("Search or jump to"), "inb");
  expect(screen.getByRole("option", { name: /Inbox/ })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: /Search for “inb”/ })).toBeInTheDocument();
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("notification center lists unopened briefs", async () => {
  mockApi({
    "GET /api/auth/me": me,
    "GET /api/today": { brief: null },
    "GET /api/briefs": { briefs: [brief(2, false), brief(1, true)] },
  });
  renderApp();
  const bell = await screen.findByRole("button", { name: "Notifications (1 unread)" });
  await userEvent.click(bell);
  expect(screen.getByRole("link", { name: "Morning brief 2" })).toHaveAttribute(
    "href",
    "/briefs/2",
  );
  expect(screen.queryByText("Morning brief 1")).not.toBeInTheDocument();
});
