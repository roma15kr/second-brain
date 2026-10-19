import { screen } from "@testing-library/react";
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
