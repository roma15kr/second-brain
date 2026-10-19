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
