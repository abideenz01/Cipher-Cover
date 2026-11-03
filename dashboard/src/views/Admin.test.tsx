import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { User } from "../api";
import { ME, stubApi } from "../testing";
import { Admin } from "./Admin";

const ADMIN = {
  ...ME,
  user_id: "USR-ADMIN",
  handler_id: "",
  roles: ["tenant_admin"],
};
const USERS: User[] = [
  {
    user_id: "USR-ADMIN",
    email: "admin@undercover.example",
    name: "Avery Admin",
    handler_id: "",
    roles: ["tenant_admin"],
    status: "active",
  },
  {
    user_id: "USR-04",
    email: "leon.abara@undercover.example",
    name: "Leon Abara",
    handler_id: "HND-04",
    roles: ["claims_handler"],
    status: "active",
  },
];
const SETTINGS = {
  name: "UnderCover Travel Insurance",
  timezone: "UTC",
  external_model_medical: false,
  payout_approval_limit: 1000,
  sign_off_sla_hours: 24,
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function setup(extra: Record<string, unknown> = {}) {
  return stubApi({
    "GET /api/users": USERS,
    "GET /api/tenant/settings": SETTINGS,
    "GET /api/handlers": [],
    ...extra,
  });
}

it("lists the sign-ins and the tenant's settings", async () => {
  setup();
  render(<Admin me={ADMIN} />);
  expect(await screen.findByText("Leon Abara")).toBeDefined();
  expect(
    screen.getByText(/Sign-off over \$1,000.00 within 24 hours/),
  ).toBeDefined();
  const own = screen.getByRole("row", {
    name: "User admin@undercover.example",
  });
  expect(within(own).queryByRole("button", { name: "Disable" })).toBeNull();
  const ownAdmin = within(own).getByRole("checkbox", { name: "tenant admin" });
  expect((ownAdmin as HTMLInputElement).disabled).toBe(true);
});

it("changes roles, disables and switches the medical setting", async () => {
  const calls = setup({
    "PUT /api/users/USR-04/roles": USERS[1],
    "POST /api/users/USR-04/disable": USERS[1],
    "PUT /api/tenant/settings": SETTINGS,
  });
  render(<Admin me={ADMIN} />);
  const leon = await screen.findByRole("row", {
    name: "User leon.abara@undercover.example",
  });
  fireEvent.click(
    within(leon).getByRole("checkbox", { name: "senior handler" }),
  );
  fireEvent.click(within(leon).getByRole("button", { name: "Disable" }));
  fireEvent.click(
    screen.getByRole("checkbox", {
      name: "Send medical documents to the model",
    }),
  );
  await vi.waitFor(() => {
    expect(calls.map((c) => c.key)).toContain("PUT /api/tenant/settings");
  });
  expect(
    calls.find((c) => c.key === "PUT /api/users/USR-04/roles")?.body,
  ).toEqual({
    roles: ["claims_handler", "senior_handler"],
  });
  expect(calls.find((c) => c.key === "PUT /api/tenant/settings")?.body).toEqual(
    {
      external_model_medical: true,
    },
  );
  expect(calls.some((c) => c.key === "POST /api/users/USR-04/disable")).toBe(
    true,
  );
});

it("adds a sign-in and shows a refusal", async () => {
  const calls = setup({
    "POST /api/users": new Error("That email already has a sign-in."),
  });
  render(<Admin me={ADMIN} />);
  await screen.findByText("Leon Abara");
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Nia" } });
  fireEvent.change(screen.getByLabelText("New email"), {
    target: { value: "nia@undercover.example" },
  });
  fireEvent.change(screen.getByLabelText("New password"), {
    target: { value: "a-long-password" },
  });
  fireEvent.change(screen.getByLabelText("Role"), {
    target: { value: "auditor" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Add" }));
  expect((await screen.findByRole("alert")).textContent).toBe(
    "That email already has a sign-in.",
  );
  expect(calls.find((c) => c.key === "POST /api/users")?.body).toEqual({
    name: "Nia",
    email: "nia@undercover.example",
    password: "a-long-password",
    roles: ["auditor"],
    handler_id: "",
  });
});

it("is closed to anyone but a tenant admin", () => {
  render(<Admin me={ME} />);
  expect(
    screen.getByText("Only a tenant admin can manage sign-ins."),
  ).toBeDefined();
});
