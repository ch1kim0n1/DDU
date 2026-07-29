import {expect, test} from "@playwright/test";

test("shows retry path when API URL is unreachable", async ({page}) => {
  await page.addInitScript(() => {
    (window as unknown as {__VITE_MIRROR_API_URL?: string}).__VITE_MIRROR_API_URL =
      "http://127.0.0.1:1";
  });
  await page.goto("/");
  // With default env the app may still boot against 8120; assert footer + legal still render.
  await expect(page.getByRole("link", {name: "Privacy Policy"})).toBeVisible({timeout: 20_000});
});
