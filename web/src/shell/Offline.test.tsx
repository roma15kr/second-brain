import { act, screen } from "@testing-library/react";
import { OFFLINE_API } from "../sw-handlers";
import { mockApi, renderApp } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.history.pushState({}, "", "/");
});

const me = { signed_in: true, has_passkeys: true, needs_passkey: false };

test("offline: banner shown, actions disabled, back online re-enables", async () => {
  window.history.pushState({}, "", "/loops");
  mockApi({
    "GET /api/auth/me": me,
    "GET /api/briefs": { briefs: [] },
    "GET /api/loops?status=open": {
      loops: [
        {
          id: 1,
          kind: "i_owe",
          title: "Send deck",
          counterpart: "Max",
          scopes: [],
          status: "open",
          due_date: null,
          overdue: false,
          due_today: false,
          age_days: 2,
          link: null,
        },
      ],
      open_counts: {},
    },
  });
  const onLine = vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
  renderApp();
  expect(await screen.findByText("Send deck")).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("Offline");
  expect(screen.getByRole("button", { name: "Done" })).toBeDisabled();
  onLine.mockReturnValue(true);
  act(() => {
    window.dispatchEvent(new Event("online"));
  });
  expect(screen.getByRole("button", { name: "Done" })).toBeEnabled();
});

test("today, briefs and sign-in state are kept for offline reading", () => {
  const cached = (p: string) => OFFLINE_API.some((re) => re.test(p));
  expect(["/api/today", "/api/briefs", "/api/briefs/12", "/api/auth/me"].every(cached)).toBe(true);
  expect(cached("/api/loops")).toBe(false);
});
