import { expect, type Page } from "@playwright/test";

export const PASSWORD = "e2e-demo-password";
export const DANA = "dana.whitfield@undercover.example";
export const LEON = "leon.abara@undercover.example";
export const ADMIN = "admin@undercover.example";
export const ADA = "ada.okonkwo@acme.example";

/** Sign in on the dashboard and wait for the queue. */
export async function signIn(page: Page, email = DANA, path = "/") {
  await page.goto(path);
  const form = page.getByRole("form", { name: "Sign in" });
  await form.getByLabel("Email").fill(email);
  await form.getByLabel("Password").fill(PASSWORD);
  await form.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

/** Sign out and wait for the sign-in form. */
export async function signOut(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("form", { name: "Sign in" })).toBeVisible();
}
