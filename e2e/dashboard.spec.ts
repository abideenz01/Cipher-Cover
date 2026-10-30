import { expect, test, type Locator, type Page } from "@playwright/test";

function column(page: Page, name: string) {
  return page.getByRole("region", { name, exact: true });
}

function card(page: Page | Locator, claimId: string) {
  return page.getByRole("button", { name: new RegExp(claimId) }).first();
}

async function runClaim(page: Page, claimId: string) {
  await card(page, claimId).click();
  await page.getByRole("tab", { name: "Decision" }).click();
  await page.getByRole("button", { name: "Run the agent" }).click();
}

test("the queue shows 35 claims and opens one in the drawer", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: /^CLM-/ })).toHaveCount(35);
  await card(page, "CLM-1002").click();
  const drawer = page.getByRole("complementary", { name: "Claim CLM-1002" });
  await expect(drawer.getByText(/My suitcase|suitcase/i).first()).toBeVisible();
  await drawer.getByRole("tab", { name: "Documents" }).click();
  await expect(drawer.locator(".doc")).toHaveCount(3);
  await drawer.getByRole("tab", { name: "Decision" }).click();
  await expect(drawer.getByText(/No decision yet/)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
});

test("a run moves a claim to Decided with its ledger and trace", async ({
  page,
}) => {
  await page.goto("/");
  await runClaim(page, "CLM-1001");
  const drawer = page.getByRole("complementary", { name: "Claim CLM-1001" });
  await expect(drawer.getByText("Approve", { exact: true })).toBeVisible();
  await expect(drawer.locator(".payout")).toHaveText("$420.00");
  await expect(drawer.locator(".ledger")).toContainText("Payout");
  await drawer.getByRole("tab", { name: "Trace" }).click();
  await expect(drawer.getByText("calculate_payout").first()).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(card(column(page, "Decided"), "CLM-1001")).toBeVisible();
});

test("a payout over $1,000.00 waits for a handler who may sign off", async ({
  page,
}) => {
  await page.goto("/");
  await runClaim(page, "CLM-1011");
  await page.keyboard.press("Escape");
  await expect(
    card(column(page, "Waiting for sign-off"), "CLM-1011"),
  ).toBeVisible();
  await page.getByRole("link", { name: "Sign-off" }).click();
  const row = page.getByRole("listitem", { name: "Sign-off CLM-1011" });
  await expect(row).toContainText("$1,500.00");
  const signOff = row.getByRole("button", { name: "Sign off" });
  await row.getByRole("combobox").selectOption("HND-04");
  await expect(signOff).toBeDisabled();
  await row.getByRole("combobox").selectOption("HND-01");
  await signOff.click();
  await expect(row).toBeHidden();
  await page.getByRole("link", { name: "Queue" }).click();
  await expect(card(column(page, "Decided"), "CLM-1011")).toBeVisible();
});

test("send back returns a claim to Waiting", async ({ page }) => {
  await page.goto("/");
  await runClaim(page, "CLM-1008");
  await page.keyboard.press("Escape");
  await page.getByRole("link", { name: "Sign-off" }).click();
  const row = page.getByRole("listitem", { name: "Sign-off CLM-1008" });
  await row.getByRole("combobox").selectOption("HND-02");
  await row.getByRole("textbox").fill("Check the supplier refunds.");
  await row.getByRole("button", { name: "Send back" }).click();
  await expect(row).toBeHidden();
  await page.getByRole("link", { name: "Queue" }).click();
  await expect(card(column(page, "Waiting"), "CLM-1008")).toBeVisible();
});

test("the instructions are shown read only", async ({ page }) => {
  await page.goto("/#/instructions");
  await expect(page.locator(".instructions")).toContainText(
    "# The UnderCover Agent",
  );
});

test("on a phone the rail is a bottom bar and the drawer fills the screen", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const rail = await page.getByRole("navigation").boundingBox();
  expect(rail?.y).toBeGreaterThan(700);
  await card(page, "CLM-1003").click();
  const drawer = await page.getByRole("complementary").boundingBox();
  expect(drawer?.width).toBeCloseTo(390, 0);
});

test("reduced motion opens the drawer with a fade", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await card(page, "CLM-1004").click();
  const animation = await page
    .getByRole("complementary")
    .evaluate((el) => getComputedStyle(el).animationName);
  expect(animation).toBe("fade-in");
});
