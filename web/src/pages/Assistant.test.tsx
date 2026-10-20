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

test("a ClickUp comment draft is posted on approval", async () => {
  window.history.pushState({}, "", "/assistant");
  let posted: unknown = null;
  mockApi({
    "GET /api/auth/me": me,
    "GET /api/suggestions": {
      suggestions: [
        {
          ...reply,
          id: 11,
          kind: "clickup_comment",
          item_title: "Time optimization",
          payload: {
            item_id: 5,
            task_id: "86abc",
            body: "Bogdan, please check",
            assignee_name: "Bogdan",
          },
        },
      ],
    },
    "GET /api/suggestions?status=recent": { suggestions: [] },
    "GET /api/assistant/threads": { threads: [] },
    "POST /api/suggestions/11/approve": (init?: RequestInit) => {
      posted = JSON.parse(String(init?.body));
      return { applied_ref: "90150" };
    },
  });
  renderApp();
  expect(await screen.findByText(/Assigned to Bogdan/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Send" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Post comment" }));
  await waitFor(() => expect(posted).toEqual({ payload: { body: "Bogdan, please check" } }));
});

test("images can be added to a ClickUp comment draft", async () => {
  window.history.pushState({}, "", "/assistant");
  let files: { id: number; filename: string; size: number }[] = [];
  let uploaded: { filename: string; mime: string; data: string } | null = null;
  mockApi({
    "GET /api/auth/me": me,
    "GET /api/suggestions": () => ({
      suggestions: [
        {
          ...reply,
          id: 12,
          kind: "clickup_comment",
          item_title: "Time optimization",
          payload: { item_id: 5, task_id: "86abc", body: "See the screenshots" },
          files,
        },
      ],
    }),
    "GET /api/suggestions?status=recent": { suggestions: [] },
    "GET /api/assistant/threads": { threads: [] },
    "POST /api/suggestions/12/files": (init?: RequestInit) => {
      uploaded = JSON.parse(String(init?.body));
      files = [{ id: 1, filename: "chart.png", size: 4 }];
      return { id: 1 };
    },
  });
  renderApp();
  const input = await screen.findByLabelText("Add images");
  await userEvent.upload(input, new File(["png!"], "chart.png", { type: "image/png" }));
  expect(await screen.findByText(/chart\.png/)).toBeInTheDocument();
  expect(uploaded).toEqual({ filename: "chart.png", mime: "image/png", data: btoa("png!") });
});
