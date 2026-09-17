import { expect, test } from "@playwright/test";

test.describe("Root page", () => {
  test("redirects unauthenticated visitor to /login", async ({ page }) => {
    await page.goto("/");

    // Should redirect to /login
    await page.waitForURL("**/login");
    await expect(page).toHaveURL(/\/login/);
  });
});
