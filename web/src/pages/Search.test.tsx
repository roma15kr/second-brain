import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockApi, renderApp } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState({}, "", "/");
});

const me = { signed_in: true, has_passkeys: true, needs_passkey: false };
const result = {
  item_id: 7,
  kind: "tg_conversation",
  scopes: ["quokka"],
  title: "Epicentr launch",
  participants: ["Олена"],
  last_activity_at: "2026-10-20T08:00:00Z",
  excerpt: "",
  locator: "https://t.me/c/1/2",
  summary: "Launch on Epicentr agreed",
  extra: {
    context: [
      {
        author: "Олена",
        sent_at: "2026-10-20T08:00:00Z",
        text: "Комісія 12%",
        matched: true,
        locator: "https://t.me/c/1/75",
      },
    ],
  },
};

test("from result to source: the conversation opens on the matched message", async () => {
  window.history.pushState({}, "", "/search?q=Epicentr");
  mockApi({
    "GET /api/auth/me": me,
    "GET /api/briefs": { briefs: [] },
    "GET /api/search?q=Epicentr": {
      results: [result],
      briefs: [
        {
          id: 3,
          routine: "weekly_review",
          headline: "Weekly review: 40",
          created_at: "2026-10-23T16:00:00Z",
        },
      ],
    },
    "GET /api/items/7?around=https%3A%2F%2Ft.me%2Fc%2F1%2F75": {
      item_id: 7,
      kind: "tg_conversation",
      title: "Epicentr launch",
      scopes: ["quokka"],
      participants: ["Олена"],
      summary: "Launch on Epicentr agreed",
      question: null,
      outcome: "Commission 12%",
      locator: "https://t.me/c/1/1",
      total: 2,
      offset: 0,
      next_offset: null,
      messages: [
        {
          key: "a",
          author: "Олена",
          sent_at: "2026-10-20T07:00:00Z",
          text: "Привіт",
          locator: "https://t.me/c/1/74",
        },
        {
          key: "b",
          author: "Олена",
          sent_at: "2026-10-20T08:00:00Z",
          text: "Комісія 12%",
          locator: "https://t.me/c/1/75",
        },
      ],
      loops: [],
    },
  });
  renderApp();
  expect(await screen.findByText("Weekly review: 40")).toBeInTheDocument(); // briefs are searchable
  expect(screen.getByText("Комісія 12%")).toBeInTheDocument(); // matched context
  await userEvent.click(screen.getByRole("link", { name: "Epicentr launch" }));
  await waitFor(() => expect(window.location.pathname).toBe("/c/7"));
  const matched = await screen.findByText("Комісія 12%", { selector: ".body" });
  expect(matched.closest("li")).toHaveClass("matched");
  expect(screen.getAllByRole("link", { name: /Open original/ })[0]).toHaveAttribute(
    "href",
    "https://t.me/c/1/1",
  );
});

test("filters go into the URL and the query", async () => {
  window.history.pushState({}, "", "/search?q=invoice");
  const calls = mockApi({
    "GET /api/auth/me": me,
    "GET /api/briefs": { briefs: [] },
    "GET /api/search?q=invoice": { results: [], briefs: [] },
    "GET /api/search?q=invoice&scope=rdim": { results: [], briefs: [] },
  });
  renderApp();
  await userEvent.selectOptions(await screen.findByLabelText("Scope"), "rdim");
  await waitFor(() =>
    expect(calls.some((c) => c.path === "/api/search?q=invoice&scope=rdim")).toBe(true),
  );
  expect(window.location.search).toBe("?q=invoice&scope=rdim");
});
