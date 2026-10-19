import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { memoryStore, setPendingStore } from "./pending";
import { Recorder } from "./Recorder";
import { MAX_SECONDS } from "./useRecorder";

class FakeRecorder {
  static instances: FakeRecorder[] = [];
  static isTypeSupported = (t: string) => t === "audio/mp4"; // like iPhone Safari
  state: "inactive" | "recording" | "paused" = "inactive";
  mimeType: string;
  ondataavailable: ((e: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  constructor(_stream: unknown, opts?: { mimeType?: string }) {
    this.mimeType = opts?.mimeType ?? "";
    FakeRecorder.instances.push(this);
  }
  start() {
    this.state = "recording";
  }
  pause() {
    this.state = "paused";
  }
  resume() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["audio"], { type: this.mimeType }) });
    this.onstop?.();
  }
}

let uploads: { url: string; type: string | null }[] = [];
let online = true;

beforeEach(() => {
  FakeRecorder.instances = [];
  uploads = [];
  online = true;
  setPendingStore(memoryStore());
  vi.stubGlobal("MediaRecorder", FakeRecorder);
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }) },
  });
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    if (!online) throw new TypeError("Failed to fetch");
    uploads.push({ url, type: new Headers(init.headers).get("Content-Type") });
    return new Response(JSON.stringify({ id: 41 }), { status: 200 });
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  setPendingStore(null);
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
});

test("records in the format the browser supports and uploads it", async () => {
  const onUploaded = vi.fn();
  render(<Recorder onUploaded={onUploaded} />);
  await userEvent.click(screen.getByRole("button", { name: /Dictate/ }));
  expect(FakeRecorder.instances[0].mimeType).toBe("audio/mp4");
  await userEvent.click(await screen.findByRole("button", { name: "Stop" }));
  await waitFor(() => expect(onUploaded).toHaveBeenCalledWith(41));
  expect(uploads[0].type).toBe("audio/mp4");
  expect(uploads[0].url).toMatch(/^\/api\/dictations\?seconds=/);
});

test("stops at the 15-minute limit and says so", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const onUploaded = vi.fn();
  render(<Recorder onUploaded={onUploaded} />);
  await userEvent.click(screen.getByRole("button", { name: /Dictate/ }));
  await screen.findByRole("button", { name: "Stop" });
  await act(async () => {
    vi.advanceTimersByTime(MAX_SECONDS * 1000);
  });
  expect(await screen.findByText(/15-minute limit/)).toBeInTheDocument();
  await waitFor(() => expect(onUploaded).toHaveBeenCalledWith(41));
  expect(uploads[0].url).toBe(`/api/dictations?seconds=${MAX_SECONDS}`);
});

test("going to the background stops and keeps what was said", async () => {
  const onUploaded = vi.fn();
  render(<Recorder onUploaded={onUploaded} />);
  await userEvent.click(screen.getByRole("button", { name: /Dictate/ }));
  await screen.findByRole("button", { name: "Stop" });
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
  act(() => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await waitFor(() => expect(onUploaded).toHaveBeenCalledWith(41));
  expect(FakeRecorder.instances[0].state).toBe("inactive");
});

test("offline: the recording waits and uploads when the connection returns", async () => {
  online = false;
  const onUploaded = vi.fn();
  render(<Recorder onUploaded={onUploaded} />);
  await userEvent.click(screen.getByRole("button", { name: /Dictate/ }));
  await userEvent.click(await screen.findByRole("button", { name: "Stop" }));
  expect(await screen.findByText(/1 waiting to upload/)).toBeInTheDocument();
  expect(onUploaded).not.toHaveBeenCalled();
  online = true;
  act(() => {
    window.dispatchEvent(new Event("online"));
  });
  await waitFor(() => expect(onUploaded).toHaveBeenCalledWith(41));
  await waitFor(() => expect(screen.queryByText(/waiting to upload/)).not.toBeInTheDocument());
});
