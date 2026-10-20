import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockApi, renderApp } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState({}, "", "/");
});

const me = { signed_in: true, has_passkeys: true, needs_passkey: false };
const meeting = {
  id: 3,
  title: "RDIM sync",
  start: "2026-10-20T12:00:00Z",
  end: "2026-10-20T12:30:00Z",
  all_day: false,
  location: "",
  link: "https://meet.google.com/abc-defg-hij",
  attendees: [
    { email: "olena@rdim.example", name: "Олена", status: "ACCEPTED", person_id: 8 },
    { email: "me@example.com", name: "Me", status: "ACCEPTED", person_id: null },
  ],
  my_status: "ACCEPTED",
  cancelled: false,
  calendar: "RDIM",
  scopes: ["rdim"],
};

test("Today lists today's meetings in Kyiv time with a join link", async () => {
  mockApi({
    "GET /api/auth/me": me,
    "GET /api/today": { brief: null, meetings: [meeting] },
    "GET /api/briefs": { briefs: [] },
  });
  renderApp();
  expect(await screen.findByRole("link", { name: "RDIM sync" })).toHaveAttribute(
    "href",
    "/meetings/3",
  );
  expect(screen.getByText("15:00–15:30")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Join" })).toHaveAttribute("href", meeting.link);
});

test("the meeting page links attendees to People", async () => {
  window.history.pushState({}, "", "/meetings/3");
  mockApi({ "GET /api/auth/me": me, "GET /api/meetings/3": meeting });
  renderApp();
  expect(await screen.findByRole("link", { name: "Олена" })).toHaveAttribute("href", "/people/8");
  expect(screen.getByRole("link", { name: "Join the call" })).toBeInTheDocument();
});

test("the meeting page shows the prep with sourced agenda points", async () => {
  window.history.pushState({}, "", "/meetings/3");
  mockApi({
    "GET /api/auth/me": me,
    "GET /api/meetings/3": {
      ...meeting,
      prep: {
        people: [{ email: "olena@rdim.example", name: "Олена", person_id: 8 }],
        conversations: [
          { ref: "item:12", title: "Price list", summary: "Prices for Q4", date: "2026-10-15" },
        ],
        loops: [
          {
            ref: "loop:4",
            kind: "i_owe",
            title: "Send the price list",
            counterpart: "Олена",
            due_date: "2026-10-21",
          },
        ],
        tasks: [],
        goals: [],
        agenda: [{ text: "Confirm the Q4 price list", ref: "item:12" }],
      },
    },
  });
  renderApp();
  expect(await screen.findByText("Confirm the Q4 price list")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "source" })).toHaveAttribute("href", "/c/12");
  expect(screen.getByText("Send the price list")).toBeInTheDocument();
  expect(screen.getByText(/you promised/)).toBeInTheDocument();
});

test("a processed recording shows summary, decisions, actions and the transcript", async () => {
  window.history.pushState({}, "", "/meetings/3");
  mockApi({
    "GET /api/auth/me": me,
    "GET /api/meetings/3": {
      ...meeting,
      recordings: [
        {
          id: 9,
          kind: "call",
          source: "Zoom",
          title: "RDIM sync",
          event_id: 3,
          started_at: "2026-10-20T12:00:00Z",
          ended_at: "2026-10-20T12:30:00Z",
          segments: [
            {
              speaker: "Олена",
              is_owner: false,
              start: 62,
              end: 70,
              text: "I will update the listings",
            },
          ],
          notes: "",
          item_id: 40,
          result: {
            summary: "Prices agreed.",
            decisions: ["Prices stay the same"],
            actions: [{ text: "Update the listings", owner: "Олена", is_me: false, due: "Friday" }],
          },
          processed: true,
        },
      ],
    },
  });
  renderApp();
  expect(await screen.findByText("Prices agreed.")).toBeInTheDocument();
  expect(screen.getByText("Prices stay the same")).toBeInTheDocument();
  expect(screen.getByText("Update the listings")).toBeInTheDocument();
  expect(screen.getByText("01:02")).toBeInTheDocument();
  expect(screen.getByText("Attach notes or a transcript")).toBeInTheDocument();
});

const recording = {
  id: 9,
  kind: "call",
  source: "Telegram",
  title: "Call with Олена · 2026-10-20 15:00",
  event_id: null,
  started_at: "2026-10-20T12:00:00Z",
  ended_at: "2026-10-20T12:30:00Z",
  segments: [],
  scopes: ["unsorted"],
  notes: "",
  item_id: 40,
  result: null,
  processed: false,
  audio: [],
};

test("an unscheduled call can be attached to a nearby meeting or a new one", async () => {
  window.history.pushState({}, "", "/recordings/9");
  const linked: unknown[] = [];
  mockApi({
    "GET /api/auth/me": me,
    "GET /api/recordings/9": recording,
    "GET /api/meetings?around=2026-10-20T12%3A00%3A00Z&hours=36": { meetings: [meeting] },
    "POST /api/recordings/9/link": (init?: RequestInit) => {
      linked.push(JSON.parse(String(init?.body)));
      return { event_id: 3, title: "RDIM sync", scopes: ["rdim"] };
    },
    "GET /api/meetings/3": meeting,
  });
  renderApp();
  await userEvent.click(await screen.findByRole("button", { name: "Attach to a meeting" }));
  await userEvent.click(await screen.findByRole("button", { name: /RDIM sync/ }));
  await waitFor(() => expect(linked[0]).toEqual({ event_id: 3 }));
  await waitFor(() => expect(window.location.pathname).toBe("/meetings/3"));
});

test("a spontaneous call gets a new meeting with participants", async () => {
  window.history.pushState({}, "", "/recordings/9");
  const linked: unknown[] = [];
  mockApi({
    "GET /api/auth/me": me,
    "GET /api/recordings/9": recording,
    "GET /api/meetings?around=2026-10-20T12%3A00%3A00Z&hours=36": { meetings: [] },
    "GET /api/projects": { projects: [{ name: "quokka" }, { name: "rdim" }] },
    "POST /api/recordings/9/link": (init?: RequestInit) => {
      linked.push(JSON.parse(String(init?.body)));
      return { event_id: 12, title: "Dealer — October prices", scopes: ["quokka"] };
    },
    "GET /api/meetings/12": { ...meeting, id: 12, title: "Dealer — October prices", local: true },
  });
  renderApp();
  await userEvent.click(await screen.findByRole("button", { name: "Attach to a meeting" }));
  await userEvent.click(await screen.findByRole("button", { name: "New meeting…" }));
  await userEvent.type(screen.getByLabelText("Meeting title"), "Dealer — October prices");
  await userEvent.type(screen.getByLabelText("Participants"), "Oleh, max@quokka.example");
  await userEvent.click(screen.getByRole("button", { name: "Create and attach" }));
  await waitFor(() =>
    expect(linked[0]).toEqual({
      new_meeting: {
        title: "Dealer — October prices",
        scope: "quokka",
        participants: ["Oleh", "max@quokka.example"],
      },
    }),
  );
  expect(await screen.findByRole("button", { name: "Edit meeting" })).toBeInTheDocument();
});
