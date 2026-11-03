import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "../App";
import type { UiAction } from "../api";
import { claim, ME, POLICY, stubApi } from "../testing";
import { STUB_TRANSCRIPT, stubProvider } from "./providers/stub";

const SIGNOFF = {
  claim_id: "CLM-1011",
  customer: "Owen G.",
  payout: 1500,
  reason: "Covered.",
  section: "Section 5",
  waiting_since: new Date().toISOString(),
  hours_waiting: 0,
  overdue: false,
};

class FakeRecognition {
  lang = "";
  interimResults = true;
  continuous = true;
  onresult: ((event: { results: { transcript: string }[][] }) => void) | null =
    null;
  onend: (() => void) | null = null;
  start = vi.fn();
  stop = vi.fn(() => {
    this.onresult?.({
      results: [[{ transcript: "open claim ten twenty four" }]],
    });
    this.onend?.();
  });
}

const speechSynthesis = { speak: vi.fn(), cancel: vi.fn() };

function reply(action: UiAction, text = "Opening CLM-1024.") {
  return { reply: text, speech: text, ui_action: action, status: "succeeded" };
}

function setup(action: UiAction, enabled = true) {
  return stubApi({
    "GET /api/claims": [claim({ claim_id: "CLM-1024" })],
    "GET /api/voice/config": { enabled, provider: "browser" },
    "GET /api/signoffs": [SIGNOFF],
    "GET /api/claims/CLM-1024": claim({ claim_id: "CLM-1024" }),
    "GET /api/policies/POL-2002": POLICY,
    "POST /api/voice/turn": reply(action),
  });
}

beforeEach(() => {
  window.location.hash = "";
  localStorage.clear();
  localStorage.setItem("voice-consent", "yes");
  vi.stubGlobal("SpeechRecognition", FakeRecognition);
  vi.stubGlobal("speechSynthesis", speechSynthesis);
  vi.stubGlobal(
    "SpeechSynthesisUtterance",
    class {
      onend: (() => void) | null = null;
      onerror: (() => void) | null = null;
      lang = "";
      constructor(public text: string) {}
    },
  );
  speechSynthesis.speak.mockClear();
  speechSynthesis.cancel.mockClear();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function mic() {
  return screen.findByRole("button", { name: /Hold to talk/ });
}

it("sends what it heard and opens the claim it is told to", async () => {
  const calls = setup({ type: "open_claim", claim_id: "CLM-1024" });
  render(<App me={ME} onSignOut={vi.fn()} />);
  const button = await mic();
  const clock = vi.spyOn(Date, "now").mockReturnValue(0);
  fireEvent.pointerDown(button);
  expect(screen.getByText("Listening")).toBeDefined();
  clock.mockReturnValue(1000);
  fireEvent.pointerUp(button);
  clock.mockRestore();
  const captions = screen.getByRole("list", { name: "Captions" });
  expect(
    await within(captions).findByText("open claim ten twenty four"),
  ).toBeDefined();
  expect(await within(captions).findByText("CLM-1024")).toBeDefined();
  expect(calls.find((c) => c.key === "POST /api/voice/turn")?.body).toEqual({
    session_id: expect.any(String) as string,
    text: "open claim ten twenty four",
  });
  expect(
    await screen.findByRole("complementary", { name: "Claim CLM-1024" }),
  ).toBeDefined();
  expect(speechSynthesis.speak).toHaveBeenCalled();
});

it("highlights a sign-off but never signs off by itself", async () => {
  const calls = setup({ type: "focus_signoff", claim_id: "CLM-1011" });
  render(<App me={ME} onSignOut={vi.fn()} />);
  fireEvent.change(
    await screen.findByRole("textbox", { name: "Type instead" }),
    {
      target: { value: "sign off ten eleven" },
    },
  );
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  const row = await screen.findByRole("listitem", {
    name: "Sign-off CLM-1011",
  });
  expect(row.className).toContain("highlight");
  const confirm = within(row).getByRole("button", { name: /Confirm sign-off/ });
  expect(document.activeElement).toBe(confirm);
  expect(calls.some((c) => c.key.includes("/sign-off"))).toBe(false);
});

it("talks while V is held and stops speech on Escape or a new turn", async () => {
  const calls = setup({ type: "none", claim_id: "" });
  render(<App me={ME} onSignOut={vi.fn()} />);
  await mic();
  fireEvent.keyDown(window, { key: "v" });
  expect(screen.getByText("Listening")).toBeDefined();
  expect(speechSynthesis.cancel).toHaveBeenCalledTimes(1);
  fireEvent.keyUp(window, { key: "v" });
  await vi.waitFor(() => {
    expect(calls.some((c) => c.key === "POST /api/voice/turn")).toBe(true);
  });
  await screen.findByText("Speaking");
  fireEvent.keyDown(window, { key: "Escape" });
  expect(speechSynthesis.cancel).toHaveBeenCalledTimes(2);
  expect(await screen.findByText("Ready")).toBeDefined();
});

it("has no mic when voice is off", async () => {
  setup({ type: "none", claim_id: "" }, false);
  render(<App me={ME} onSignOut={vi.fn()} />);
  await screen.findByRole("button", { name: /CLM-1024/ });
  expect(screen.queryByRole("button", { name: /Hold to talk/ })).toBeNull();
  expect(screen.queryByRole("region", { name: "Voice assistant" })).toBeNull();
});

it("asks for consent once", async () => {
  localStorage.clear();
  setup({ type: "none", claim_id: "" });
  render(<App me={ME} onSignOut={vi.fn()} />);
  fireEvent.pointerDown(await mic());
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.pointerDown(await mic());
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.getByText("Listening")).toBeDefined();
});

it("shows refusals in the captions and hides the panel", async () => {
  stubApi({
    "GET /api/claims": [],
    "GET /api/voice/config": { enabled: true, provider: "stub" },
    "POST /api/voice/turn": new Error("Too many requests."),
  });
  render(<App me={ME} onSignOut={vi.fn()} />);
  const input = await screen.findByRole("textbox", { name: "Type instead" });
  fireEvent.change(input, { target: { value: "hello" } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  expect(await screen.findByText("Too many requests.")).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Hide" }));
  expect(screen.queryByRole("textbox", { name: "Type instead" })).toBeNull();
});

it("the stub provider hears a fixed transcript", async () => {
  const heard: string[] = [];
  const stop = stubProvider.listen(
    (text) => heard.push(text),
    () => heard.push("end"),
  );
  stop();
  expect(heard).toEqual([STUB_TRANSCRIPT, "end"]);
  await new Promise<void>((resolve) => {
    stubProvider.speak("hi", resolve);
  });
  act(() => {
    stubProvider.cancel();
  });
});
