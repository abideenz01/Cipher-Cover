import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./session";

function todos(page: Page) {
  return page.getByRole("list", { name: "To-do list" }).getByRole("listitem");
}

async function waitingCount(page: Page): Promise<number> {
  const column = page.getByRole("region", { name: "Waiting", exact: true });
  return column.getByRole("button", { name: /^CLM-/ }).count();
}

test("a run capped at three fills its to-do list and ticks it off", async ({
  page,
}) => {
  await signIn(page);
  await expect(page.getByRole("button", { name: /^CLM-/ })).toHaveCount(35);
  const before = await waitingCount(page);
  await page.getByRole("spinbutton", { name: "Claims" }).fill("3");
  await page.getByRole("button", { name: "Run", exact: true }).click();
  await expect(todos(page)).toHaveCount(3);
  await expect(todos(page).filter({ hasText: "Done" })).toHaveCount(3, {
    timeout: 30_000,
  });
  await expect(page.locator(".run-summary")).toHaveText("Decided 3 claims.");
  await expect(page.getByText("It reached its cap.")).toBeVisible();
  await expect(page.locator(".run-usage")).toContainText("3 claims");
  expect(await waitingCount(page)).toBe(before - 3);
});

test("a decided claim shows the sections it read and relied on", async ({
  page,
}) => {
  await signIn(page);
  const decided = page.getByRole("region", { name: "Decided", exact: true });
  await decided.getByRole("button", { name: /^CLM-/ }).first().click();
  const drawer = page.getByRole("complementary");
  await drawer.getByRole("tab", { name: "Decision" }).click();
  await expect(
    drawer.getByRole("list", { name: "Sections relied on" }),
  ).toContainText("wording-10 Section 10. How we work out your payment");
  await drawer.getByRole("tab", { name: "Trace" }).click();
  await expect(
    drawer.getByRole("list", { name: "Sections read" }),
  ).toContainText("wording-10");
  await expect(drawer.getByText(/Attempt \d · succeeded/)).toBeVisible();
});

test("Stop ends the run after the claim in hand", async ({ page }) => {
  await signIn(page);
  await expect(page.getByRole("button", { name: /^CLM-/ })).toHaveCount(35);
  await page.getByRole("checkbox", { name: "All" }).check();
  await page.getByRole("button", { name: "Run", exact: true }).click();
  await page.getByRole("button", { name: "Stop" }).click();
  const panel = page.getByRole("region", { name: "Run" });
  await expect(panel.locator(".view-head").getByText("Stopped")).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByText("A handler stopped it.")).toBeVisible();
  await expect(
    todos(page).filter({ hasText: "Not started" }).first(),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Run", exact: true }),
  ).toBeVisible();
  await page.getByText("Run history").click();
  await expect(page.locator(".history-row")).toHaveCount(2);
});
