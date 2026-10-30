import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Handler, SignOffItem } from "../api";
import { stubApi } from "../testing";
import { Instructions } from "./Instructions";
import { SignOff } from "./SignOff";

const HANDLERS: Handler[] = [
  {
    handler_id: "HND-01",
    name: "Dana Whitfield",
    role: "Senior",
    can_approve_over_limit: true,
  },
  {
    handler_id: "HND-04",
    name: "Leon Abara",
    role: "In training",
    can_approve_over_limit: false,
  },
];

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

function renderSignOff(onChanged = vi.fn()) {
  render(
    <SignOff
      version="1"
      now={new Date()}
      highlight={{ claimId: "CLM-1011", handlerId: "HND-01" }}
      onOpen={vi.fn()}
      onChanged={onChanged}
    />,
  );
}

it("signs off only with a handler who may", async () => {
  const onChanged = vi.fn();
  const calls = stubApi({
    "GET /api/handlers": HANDLERS,
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
  const select = within(row).getByRole("combobox");
  const signOff = within(row).getByRole("button", { name: "Sign off" });
  await screen.findByRole("option", { name: /HND-04/ });
  fireEvent.change(select, { target: { value: "HND-04" } });
  expect((signOff as HTMLButtonElement).disabled).toBe(true);
  expect(within(row).getByText(/cannot sign off/)).toBeDefined();
  fireEvent.change(select, { target: { value: "HND-01" } });
  expect((signOff as HTMLButtonElement).disabled).toBe(false);
  fireEvent.click(signOff);
  await vi.waitFor(() => {
    expect(onChanged).toHaveBeenCalled();
  });
  expect(calls.at(-1)).toEqual({
    key: "POST /api/claims/CLM-1011/sign-off",
    body: { handler_id: "HND-01" },
  });
});

it("sends back with a reason and shows refusals", async () => {
  stubApi({
    "GET /api/handlers": HANDLERS,
    "GET /api/signoffs": [ITEM],
    "POST /api/claims/CLM-1011/send-back": new Error("Not waiting."),
  });
  renderSignOff();
  const row = await screen.findByRole("listitem", {
    name: "Sign-off CLM-1011",
  });
  await screen.findByRole("option", { name: /HND-04/ });
  const sendBack = within(row).getByRole("button", { name: "Send back" });
  fireEvent.change(within(row).getByRole("combobox"), {
    target: { value: "HND-04" },
  });
  expect((sendBack as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(within(row).getByRole("textbox"), {
    target: { value: "Check the receipts." },
  });
  fireEvent.click(sendBack);
  expect(await within(row).findByText("Not waiting.")).toBeDefined();
});

it("says when nothing is waiting", async () => {
  stubApi({ "GET /api/handlers": [], "GET /api/signoffs": [] });
  renderSignOff();
  expect(
    await screen.findByText(/Nothing is waiting for sign-off/),
  ).toBeDefined();
});

it("shows the instructions read only, with a copy button", async () => {
  stubApi({ "GET /api/instructions": { text: "# The UnderCover Agent" } });
  const writeText = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  render(<Instructions />);
  expect(await screen.findByText("# The UnderCover Agent")).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Copy" }));
  expect(await screen.findByRole("button", { name: "Copied" })).toBeDefined();
  expect(writeText).toHaveBeenCalledWith("# The UnderCover Agent");
});
