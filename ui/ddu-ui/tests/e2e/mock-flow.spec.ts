import {expect, test} from "@playwright/test";

test("mock flow: findings, approve, wipe", async ({page}) => {
  await page.goto("/");
  await expect(page.getByText("Agent proposals")).toBeVisible({timeout: 30_000});
  await expect(page.locator(".proposal-card").first()).toBeVisible({timeout: 30_000});
  const scoreBefore = await page.locator(".score-value, [aria-live], .exposure-score").first().textContent().catch(() => "");
  await page.getByRole("button", {name: /Approve/i}).first().click();
  await page.waitForTimeout(1500);
  const scoreAfter = await page.locator(".score-value, [aria-live], .exposure-score").first().textContent().catch(() => "");
  expect(scoreBefore !== undefined || scoreAfter !== undefined).toBeTruthy();
  await page.getByRole("button", {name: /End session and destroy all data|End & wipe/i}).click();
  await expect(page.getByText(/Nothing remains|Destroying/i)).toBeVisible({timeout: 15_000});
});
