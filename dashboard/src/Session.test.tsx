import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { csrfToken } from "./api";
import { Session } from "./Session";
import { ME, Refusal, stubApi, summary } from "./testing";

const SIGNED_OUT = new Refusal(401, "Sign in first.");
const DASHBOARD = {
  "GET /api/claims": [summary(1)],
  "GET /api/voice/config": { enabled: false, provider: "browser" },
};

beforeEach(() => {
  window.location.hash = "";
  document.cookie = "cc_csrf=; max-age=0";
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function signIn(email: string, password: string) {
  fireEvent.change(screen.getByLabelText("Email"), {
    target: { value: email },
  });
  fireEvent.change(screen.getByLabelText("Password"), {
    target: { value: password },
  });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

it("asks for sign-in, then shows the dashboard", async () => {
  const calls = stubApi({
    ...DASHBOARD,
    "GET /api/auth/me": SIGNED_OUT,
    "POST /api/auth/login": ME,
  });
  render(<Session />);
  expect(await screen.findByRole("form", { name: "Sign in" })).toBeDefined();
  const submit = screen.getByRole("button", { name: "Sign in" });
  expect((submit as HTMLButtonElement).disabled).toBe(true);
  signIn(" dana@undercover.example ", "secret");
  expect(await screen.findByText("Dana Whitfield")).toBeDefined();
  expect(await screen.findByRole("button", { name: /CLM-1001/ })).toBeDefined();
  expect(calls.find((c) => c.key === "POST /api/auth/login")?.body).toEqual({
    email: "dana@undercover.example",
    password: "secret",
  });
});

it("says when the email or password is wrong", async () => {
  stubApi({
    "GET /api/auth/me": SIGNED_OUT,
    "POST /api/auth/login": new Refusal(401, "The email or password is wrong."),
  });
  render(<Session />);
  await screen.findByRole("form", { name: "Sign in" });
  signIn("dana@undercover.example", "wrong");
  expect((await screen.findByRole("alert")).textContent).toBe(
    "The email or password is wrong.",
  );
});

it("goes back to sign-in when the session ends", async () => {
  stubApi({ ...DASHBOARD, "GET /api/auth/me": ME });
  render(<Session />);
  expect(await screen.findByText("Dana Whitfield")).toBeDefined();
  stubApi({ ...DASHBOARD, "GET /api/claims": SIGNED_OUT });
  expect(
    await screen.findByRole("form", { name: "Sign in" }, { timeout: 4000 }),
  ).toBeDefined();
});

it("signs out", async () => {
  const calls = stubApi({
    ...DASHBOARD,
    "GET /api/auth/me": ME,
    "POST /api/auth/logout": { status: "signed_out" },
  });
  render(<Session />);
  fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
  expect(await screen.findByRole("form", { name: "Sign in" })).toBeDefined();
  expect(calls.some((c) => c.key === "POST /api/auth/logout")).toBe(true);
});

it("sends the CSRF token from its cookie on every write", async () => {
  document.cookie = "cc_csrf=abc%3D123";
  expect(csrfToken()).toBe("abc=123");
  stubApi({
    ...DASHBOARD,
    "GET /api/auth/me": ME,
    "POST /api/auth/logout": { status: "signed_out" },
  });
  render(<Session />);
  fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
  await screen.findByRole("form", { name: "Sign in" });
  const post = vi
    .mocked(fetch)
    .mock.calls.find(([path]) => path === "/api/auth/logout");
  const headers = post?.[1]?.headers as Record<string, string>;
  expect(headers["X-CSRF-Token"]).toBe("abc=123");
});
