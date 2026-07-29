import {expect, test} from "@playwright/test";

test("real mode wizard produces a session", async ({page}) => {
  await page.goto("/");
  await page.getByRole("button", {name: /Real/i}).click();
  await expect(page.getByText(/Real discovery onboarding|Your verified identity/i)).toBeVisible({
    timeout: 15_000,
  });
  await page.getByPlaceholder("you@example.com").fill("operator@example.com");
  await page.getByRole("button", {name: "Add"}).first().click();
  await page.getByRole("button", {name: "Continue"}).click();
  await page.getByRole("button", {name: "Continue"}).click();
  await page.getByRole("button", {name: "Continue"}).click();
  await page.getByLabelText(/I confirm that I am 18/i).check();
  await page.getByLabelText(/I have read and agree/i).check();
  await page.getByRole("button", {name: /Start real scan/i}).click();
  await expect(page.getByText("Agent proposals")).toBeVisible({timeout: 30_000});
});
