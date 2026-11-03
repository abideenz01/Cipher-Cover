import { expect, test, type Page } from "@playwright/test";
import { DANA, LEON, signIn, signOut } from "./session";

async function open(page: Page, email = DANA) {
  await page.clock.install();
  await page.addInitScript(() => {
    localStorage.setItem("voice-consent", "yes");
  });
  await signIn(page, email);
  await expect(page.getByRole("button", { name: /^CLM-/ })).toHaveCount(35);
}

async function type(page: Page, text: string) {
  await page.getByRole("textbox", { name: "Type instead" }).fill(text);
  await page.getByRole("button", { name: "Send" }).click();
}

function captions(page: Page) {
  return page.getByRole("list", { name: "Captions" });
}

test("holding the mic sends what it heard and opens the claim", async ({
  page,
}) => {
  await open(page);
  const mic = page.getByRole("button", { name: /Hold to talk/ });
  await mic.hover();
  await page.mouse.down();
  await expect(page.getByText("Listening")).toBeVisible();
  await page.clock.fastForward(500);
  await page.mouse.up();
  await expect(captions(page)).toContainText("open claim ten twenty four");
  await expect(captions(page)).toContainText("Opening CLM-1024.");
  await expect(
    page.getByRole("complementary", { name: "Claim CLM-1024" }),
  ).toBeVisible();
});

test("asking what is waiting reads back the sign-off queue", async ({
  page,
}) => {
  await open(page);
  await type(page, "what is waiting for my sign off");
  await expect(captions(page)).toContainText("Waiting for sign-off:");
});

test("a sign-off by voice is only confirmed by a click", async ({ page }) => {
  await open(page, LEON);
  await page
    .getByRole("button", { name: /CLM-1405/ })
    .first()
    .click();
  await page.getByRole("tab", { name: "Decision" }).click();
  await page.getByRole("button", { name: "Run the agent" }).click();
  await expect(page.locator(".payout")).toHaveText("$1,500.00");
  await page.keyboard.press("Escape");

  await expect(page.getByText("Speaking as HND-04 Leon Abara")).toBeVisible();
  await type(page, "sign off fourteen oh five");
  await expect(captions(page)).toContainText("not allowed to sign off");
  await expect(page.locator(".signoff.highlight")).toHaveCount(0);

  await signOut(page);
  await signIn(page);
  await type(page, "sign off fourteen oh five");
  const row = page.getByRole("listitem", { name: "Sign-off CLM-1405" });
  await expect(row).toHaveClass(/highlight/);
  await page.getByRole("link", { name: "Queue" }).click();
  await expect(
    page
      .getByRole("region", { name: "Waiting for sign-off", exact: true })
      .getByRole("button", { name: /CLM-1405/ }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Sign-off" }).click();
  await row.getByRole("button", { name: /Confirm sign-off as HND-01/ }).click();
  await expect(row).toBeHidden();
  await page.getByRole("link", { name: "Queue" }).click();
  await expect(
    page
      .getByRole("region", { name: "Decided", exact: true })
      .getByRole("button", { name: /CLM-1405/ }),
  ).toBeVisible();
});

test("with voice off there is no mic", async ({ page }) => {
  await page.route("**/api/voice/config", (route) =>
    route.fulfill({ json: { enabled: false, provider: "browser" } }),
  );
  await signIn(page);
  await expect(page.getByRole("button", { name: /^CLM-/ })).toHaveCount(35);
  await expect(page.getByRole("button", { name: /Hold to talk/ })).toHaveCount(
    0,
  );
});
