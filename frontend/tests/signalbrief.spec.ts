import { expect, test } from "@playwright/test";

test("SignalBrief Desk runs sync and async research flows", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "SignalBrief Desk" })).toBeVisible();

  await page.getByLabel("Company").fill("SurveyMonkey");
  await page.getByLabel("Focus").fill("survey customer feedback AI insights");
  await page.getByRole("button", { name: /run sync brief/i }).click();
  await expect(page.locator("#brief").getByRole("heading", { name: "SurveyMonkey" })).toBeVisible({ timeout: 90_000 });
  await expect(page.locator("#graph").getByText("planner", { exact: true })).toBeVisible();

  await page.getByText("Async mode").click();
  await page.getByRole("button", { name: /create async job/i }).click();
  await expect(page.locator("#jobs").getByText("Job Board")).toBeVisible();
  await expect(page.locator("#jobs").getByText(/completed|running|queued/i).first()).toBeVisible({ timeout: 120_000 });

  await page.getByRole("button", { name: /open event debugger/i }).click();
  await expect(page.getByTestId("event-drawer")).toBeVisible();
  await expect(page.locator("#events").getByText("node_input").first()).toBeVisible();
  await expect(page.locator("#events").getByText("node_output").first()).toBeVisible();
  await expect(page.getByTestId("event-drawer").getByText("node_input").first()).toBeVisible();
});
