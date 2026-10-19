import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockApi, renderApp } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState({}, "", "/");
});

const me = { signed_in: true, has_passkeys: true, needs_passkey: false };
const reply = {
  id: 7,
  kind: "reply_email",
  payload: { item_id: 5, body: "" },
  reason: "Reply requested",
  scopes: ["quokka"],
  item_id: 5,
  item_title: "Terms",
  status: "proposed",
  applied_ref: null,
  error: null,
  created_at: "2026-10-20T08:00:00Z",
};

test("a reply is written, saved to Drafts and listed as saved", async () => {
  window.history.pushState({}, "", "/assistant");
  let approved: unknown = null;
  const calls = mockApi({
    "GET /api/auth/me": me,
    "GET /api/suggestions": () => ({ suggestions: approved ? [] : [reply] }),
    "GET /api/suggestions?status=recent": () => ({
      suggestions: approved
        ? [{ ...reply, status: "applied", applied_ref: "<kb-suggestion-7@x>" }]
        : [],
    }),
    "POST /api/suggestions/7/approve": (init?: RequestInit) => {
      approved = JSON.parse(String(init?.body));
      return { applied_ref: "queued" };
    },
  });
  renderApp();
  expect(await screen.findByRole("link", { name: "Terms" })).toHaveAttribute("href", "/c/5");
  await userEvent.type(screen.getByLabelText("Reply"), "Confirmed, thank you.");
  await userEvent.click(screen.getByRole("button", { name: "Save to Drafts" }));
  await waitFor(() => expect(approved).toEqual({ payload: { body: "Confirmed, thank you." } }));
  expect(await screen.findByText("Saved to Drafts")).toBeInTheDocument();
  expect(screen.getByText("Nothing to approve.")).toBeInTheDocument();
  expect(calls.some((c) => c.method === "POST" && c.path === "/api/suggestions/7/approve")).toBe(
    true,
  );
});

test("Send waits 10 seconds and can be undone", async () => {
  window.history.pushState({}, "", "/assistant");
  let undone = false;
  const calls = mockApi({
    "GET /api/auth/me": me,
    "GET /api/suggestions": { suggestions: [{ ...reply, payload: { item_id: 5, body: "Ok" } }] },
    "GET /api/suggestions?status=recent": { suggestions: [] },
    "POST /api/suggestions/7/send": () => ({
      send_after: new Date(Date.now() + 10_000).toISOString(),
    }),
    "POST /api/suggestions/7/undo": () => {
      undone = true;
      return { ok: true };
    },
  });
  renderApp();
  await userEvent.click(await screen.findByRole("button", { name: "Send" }));
  expect(await screen.findByText(/Sending in (10|9) s/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Undo" }));
  await waitFor(() => expect(undone).toBe(true));
  expect(await screen.findByRole("button", { name: "Send" })).toBeInTheDocument();
  const sends = calls.filter((c) => c.path === "/api/suggestions/7/send");
  expect(sends).toHaveLength(1);
  expect(JSON.parse(String(sends[0].init?.body))).toEqual({ payload: { body: "Ok" } });
});

test("a Telegram nudge is copied and its chat opened", async () => {
  window.history.pushState({}, "", "/assistant");
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  const open = vi.spyOn(window, "open").mockReturnValue(null);
  mockApi({
    "GET /api/auth/me": me,
    "GET /api/suggestions": {
      suggestions: [
        {
          ...reply,
          id: 9,
          kind: "nudge",
          payload: { channel: "telegram", body: "Any news?", link: "https://t.me/c/1/2" },
          reason: "Olga: Customs documents — 2 days overdue",
        },
      ],
    },
    "GET /api/suggestions?status=recent": { suggestions: [] },
    "POST /api/suggestions/9/approve": { applied_ref: "copied" },
  });
  renderApp();
  expect(screen.queryByRole("button", { name: "Send" })).not.toBeInTheDocument();
  await userEvent.click(await screen.findByRole("button", { name: "Copy and open chat" }));
  expect(writeText).toHaveBeenCalledWith("Any news?");
  expect(open).toHaveBeenCalledWith("https://t.me/c/1/2", "_blank", "noreferrer");
  open.mockRestore();
});
