import { act, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AudioTranscript, type Track } from "./AudioPlayer";

const tracks: Track[] = [
  {
    track: "owner",
    available: true,
    deleted_at: null,
    expires_at: "2027-10-20T12:00:00Z",
    bytes: 1,
  },
  {
    track: "others",
    available: true,
    deleted_at: null,
    expires_at: "2027-10-20T12:00:00Z",
    bytes: 1,
  },
];
const segments = [
  { speaker: "Roman", start: 0, end: 9, text: "Let's agree on the commission." },
  { speaker: "Олена", start: 62, end: 70, text: "Five percent works for us." },
];

function setup(t = tracks) {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <AudioTranscript recordingId={9} tracks={t} segments={segments} onDeleted={() => undefined} />
    </QueryClientProvider>,
  );
}

test("tapping a line plays from that moment and highlights it", () => {
  const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
  setup();
  const audio = screen.getByLabelText("Recording") as HTMLAudioElement;
  expect(audio.getAttribute("src")).toBe("/api/recordings/9/audio/owner");
  fireEvent.click(screen.getByRole("button", { name: "01:02" }));
  expect(audio.currentTime).toBe(62);
  expect(play).toHaveBeenCalled();
  act(() => {
    fireEvent.timeUpdate(audio);
  });
  expect(screen.getByText(/Five percent works for us/).closest("li")).toHaveAttribute(
    "aria-current",
    "true",
  );
  play.mockRestore();
});

test("either track or both can be played, and audio can be downloaded", () => {
  setup();
  expect(screen.getByRole("button", { name: "Both" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Others" }));
  expect(screen.getByLabelText("Recording").getAttribute("src")).toBe(
    "/api/recordings/9/audio/others",
  );
  expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute(
    "href",
    "/api/recordings/9/audio/others?download=true",
  );
});

test("deleted audio leaves the transcript", () => {
  setup([{ ...tracks[0], available: false, deleted_at: "2027-10-21T00:00:00Z" }]);
  expect(screen.queryByLabelText("Recording")).not.toBeInTheDocument();
  expect(screen.getByText(/Audio deleted on/)).toBeInTheDocument();
  expect(screen.getByText(/Five percent works for us/)).toBeInTheDocument();
});
