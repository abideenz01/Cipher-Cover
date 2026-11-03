import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Me, SignOffItem } from "../api";
import { ME, stubApi, TRAINEE } from "../testing";
import { Instructions } from "./Instructions";
import { SignOff } from "./SignOff";

const ITEM: SignOffItem = {
  claim_id: "CLM-1011",
  customer: "Owen G.",
  payout: 1500,
  reason: "Covered baggage loss.",
  section: "Section 5",
  waiting_since: new Date(Date.now() - 2 * 3600 * 1000).toISOString(),
  hours_waiting: 2,
  overdue: true,
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderSignOff(onChanged = vi.fn(), me: Me = ME) {
  render(
    <SignOff
      me={me}
      version="1"
      now={new Date()}
      highlight={{ claimId: "CLM-1011", handlerId: "HND-01" }}
      onOpen={vi.fn()}
      onChanged={onChanged}
    />,
  );
}

it("signs off as the signed-in handler", async () => {
  const onChanged = vi.fn();
  const calls = stubApi({
    "GET /api/signoffs": [ITEM],
    "POST /api/claims/CLM-1011/sign-off": {},
  });
  renderSignOff(onChanged);
  const row = await screen.findByRole("listitem", {
    name: "Sign-off CLM-1011",
  });
  expect(row.className).toContain("highlight");
  expect(within(row).getByText("Overdue")).toBeDefined();
  expect(within(row).getByText(/Waited 2 h/)).toBeDefined();
  expect(within(row).queryByRole("combobox")).toBeNull();
  const signOff = within(row).getByRole("button", { name: "Sign off" });
  expect((signOff as HTMLButtonElement).disabled).toBe(false);
  fireEvent.click(signOff);
  await vi.waitFor(() => {
    expect(onChanged).toHaveBeenCalled();
  });
  expect(calls.at(-1)).toEqual({
    key: "POST /api/claims/CLM-1011/sign-off",
    body: {},
  });
});

it("does not let a handler in training sign off", async () => {
  stubApi({ "GET /api/signoffs": [ITEM] });
  renderSignOff(vi.fn(), TRAINEE);
  const row = await screen.findByRole("listitem", {
    name: "Sign-off CLM-1011",
  });
  const signOff = within(row).getByRole("button", { name: "Sign off" });
  expect((signOff as HTMLButtonElement).disabled).toBe(true);
  expect(within(row).getByText(/Leon Abara cannot sign off/)).toBeDefined();
  expect(within(row).queryByRole("button", { name: /Confirm/ })).toBeNull();
});

it("sends back with a reason and shows refusals", async () => {
  const calls = stubApi({
    "GET /api/signoffs": [ITEM],
    "POST /api/claims/CLM-1011/send-back": new Error("Not waiting."),
  });
  renderSignOff();
  const row = await screen.findByRole("listitem", {
    name: "Sign-off CLM-1011",
  });
  const sendBack = within(row).getByRole("button", { name: "Send back" });
  expect((sendBack as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(within(row).getByRole("textbox"), {
    target: { value: "Check the receipts." },
  });
  fireEvent.click(sendBack);
  expect(await within(row).findByText("Not waiting.")).toBeDefined();
  expect(calls.at(-1)?.body).toEqual({ reason: "Check the receipts." });
});

it("says when nothing is waiting", async () => {
  stubApi({ "GET /api/signoffs": [] });
  renderSignOff();
  expect(
    await screen.findByText(/Nothing is waiting for sign-off/),
  ).toBeDefined();
});

it("shows both sets of instructions read only, with copy buttons", async () => {
  stubApi({
    "GET /api/instructions": {
      queue: "# Running the queue",
      claim: "# Working a claim",
      fingerprint: "a1b2c3d4e5f6",
    },
  });
  const writeText = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  render(<Instructions />);
  expect(await screen.findByText("# Running the queue")).toBeDefined();
  expect(screen.getByText("# Working a claim")).toBeDefined();
  expect(screen.getByText("Fingerprint a1b2c3d4e5f6")).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Copy Working a claim" }));
  expect(await screen.findByText("Copied")).toBeDefined();
  expect(writeText).toHaveBeenCalledWith("# Working a claim");
});
