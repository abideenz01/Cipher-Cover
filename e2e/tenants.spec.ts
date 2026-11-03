import { expect, test } from "@playwright/test";
import { ADA, ADMIN, PASSWORD, signIn, signOut } from "./session";

test("an admin adds a sign-in, and it works", async ({ page }) => {
  await signIn(page, ADMIN);
  await page.getByRole("link", { name: "Admin" }).click();
  const admin = page.getByRole("region", { name: "Admin" });
  await expect(admin).toContainText("Sign-off over $1,000.00 within 24 hours");
  const form = admin.getByRole("form", { name: "Add a sign-in" });
  await form.getByLabel("Name").fill("Nia Reyes");
  await form.getByLabel("New email").fill("nia.reyes@undercover.example");
  await form.getByLabel("New password").fill(PASSWORD);
  await form.getByLabel("Role").selectOption("auditor");
  await form.getByRole("button", { name: "Add" }).click();
  await expect(
    admin.getByRole("row", { name: "User nia.reyes@undercover.example" }),
  ).toBeVisible();
  await signOut(page);
  await signIn(page, "nia.reyes@undercover.example");
  await expect(page.getByRole("button", { name: /^CLM-/ })).toHaveCount(35);
  await expect(page.getByRole("link", { name: "Admin" })).toHaveCount(0);
});

test("another insurer's handler sees only that insurer's claims", async ({
  page,
}) => {
  await signIn(page, ADA);
  await expect(page.getByRole("button", { name: /^CLM-50/ })).toHaveCount(10);
  await expect(page.getByRole("button", { name: /^CLM-10/ })).toHaveCount(0);
});
