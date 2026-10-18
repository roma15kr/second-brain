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

test("dock lists the apps and marks the current one; phones get a More button", async () => {
  mockApi({
    "GET /api/auth/me": me,
    "GET /api/today": { brief: null },
    "GET /api/briefs": { briefs: [] },
  });
  renderApp();
  const dock = await screen.findByRole("navigation", { name: "Apps" });
  for (const label of ["Today", "Inbox", "Loops", "Briefs", "Week"]) {
    expect(dock).toHaveTextContent(label);
  }
  expect(screen.getByRole("link", { name: /Today/ })).toHaveClass("active");
  expect(screen.getByRole("button", { name: /More/ })).toHaveClass("phone-only");
  expect(screen.getByRole("link", { name: /Week/ })).toHaveClass("desktop-only");
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
  await screen.findByRole("navigation", { name: "Apps" });
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
