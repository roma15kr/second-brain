import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockApi, renderApp } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState({}, "", "/");
});

const me = { signed_in: true, has_passkeys: true, needs_passkey: false };
const profile = (merges: { id: number; merged_id: number; reason: string }[]) => ({
  person_id: 4,
  display_name: "Hostinger",
  names: ["Hostinger"],
  identities: merges.length
    ? ["email:billing@hostinger.example", "email:support@hostinger.example"]
    : ["email:billing@hostinger.example"],
  scopes: ["digisoft"],
  first_interaction: "2026-01-01T00:00:00Z",
  last_interaction: "2026-10-20T00:00:00Z",
  conversations: 3,
  recent: [],
  merges,
  open_loops: [],
});

test("people list links to a person", async () => {
  window.history.pushState({}, "", "/people");
  mockApi({
    "GET /api/auth/me": me,
    "GET /api/briefs": { briefs: [] },
    "GET /api/people": {
      people: [
        {
          id: 4,
          name: "Hostinger",
          channels: ["email"],
          scopes: ["digisoft"],
          last_interaction: "2026-10-20T00:00:00Z",
          conversations: 3,
          open_loops: 1,
        },
      ],
    },
  });
  renderApp();
  expect(await screen.findByRole("link", { name: "Hostinger" })).toHaveAttribute(
    "href",
    "/people/4",
  );
  expect(screen.getByText("↺ 1")).toBeInTheDocument();
});

test("merge two Hostinger people, then undo from the person page", async () => {
  window.history.pushState({}, "", "/people/4");
  let merged = false;
  const calls = mockApi({
    "GET /api/auth/me": me,
    "GET /api/briefs": { briefs: [] },
    "GET /api/people/4": () => profile(merged ? [{ id: 11, merged_id: 5, reason: "manual" }] : []),
    "GET /api/people?q=Host&limit=8": {
      people: [
        { id: 4, name: "Hostinger" },
        { id: 5, name: "Hostinger Support" },
      ],
    },
    "POST /api/people/4/merge": () => {
      merged = true;
      return { merge_id: 11 };
    },
    "POST /api/people/merges/11/undo": () => {
      merged = false;
      return { ok: true };
    },
  });
  renderApp();
  await userEvent.type(await screen.findByLabelText("Find a person to merge"), "Host");
  await userEvent.click(await screen.findByRole("button", { name: "Merge into Hostinger" }));
  expect(await screen.findByText("email:support@hostinger.example")).toBeInTheDocument();
  expect(
    JSON.parse(String(calls.find((c) => c.path === "/api/people/4/merge")?.init?.body)),
  ).toEqual({ other_id: 5 });
  await userEvent.click(screen.getByRole("button", { name: "Undo merge" }));
  await waitFor(() =>
    expect(screen.queryByText("email:support@hostinger.example")).not.toBeInTheDocument(),
  );
});

test("scope page shows decisions and can be archived", async () => {
  window.history.pushState({}, "", "/scopes/rdim");
  let archived = false;
  mockApi({
    "GET /api/auth/me": me,
    "GET /api/briefs": { briefs: [] },
    "GET /api/scopes/rdim": () => ({
      scope: "rdim",
      archived,
      activity: [{ day: "2026-10-20", kind: "email_thread", n: 3 }],
      open_loops: [],
      key_people: [{ name: "Вячеслав", conversations: 4 }],
      decisions: [
        {
          item_id: 9,
          title: "Dealer terms",
          outcome: "Agreed 5 days delivery",
          at: "2026-10-20T00:00:00Z",
        },
      ],
    }),
    "POST /api/scopes/rdim/archive": () => {
      archived = true;
      return { archived: true };
    },
  });
  renderApp();
  expect(await screen.findByText("Agreed 5 days delivery")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Archive scope…" }));
  expect(await screen.findByText(/archived \(read-only/)).toBeInTheDocument();
});
