import { test, expect } from "@playwright/test";
import { gotoApp, markConfigured } from "./helpers";

test.describe("navigation", () => {
  test.beforeEach(async ({ request }) => {
    // A configured instance renders the main layout instead of the wizard.
    await markConfigured(request);
  });

  test("the header exposes every top-level destination", async ({ page }) => {
    await gotoApp(page, "/");

    const header = page.locator("header");
    for (const name of ["Dashboard", "Scan", "Settings", "System"]) {
      await expect(header.getByRole("link", { name, exact: true }).first()).toBeVisible();
    }
  });

  test("navigating to Scan renders the scan page", async ({ page }) => {
    await gotoApp(page, "/");
    await page.locator("header").getByRole("link", { name: "Scan", exact: true }).first().click();

    await expect(page).toHaveURL(/\/scan$/);
    await expect(page.getByText("Scan for Duplicates").first()).toBeVisible();
  });

  test("navigating to Settings renders the settings page", async ({ page }) => {
    await gotoApp(page, "/");
    await page
      .locator("header")
      .getByRole("link", { name: "Settings", exact: true })
      .first()
      .click();

    await expect(page).toHaveURL(/\/settings$/);
    await expect(page.getByText("General Settings").first()).toBeVisible();
  });

  test("navigating to System renders the system page", async ({ page }) => {
    await gotoApp(page, "/");
    await page.locator("header").getByRole("link", { name: "System", exact: true }).first().click();

    await expect(page).toHaveURL(/\/system$/);
    await expect(page.getByText("Component Versions").first()).toBeVisible();
  });

  test("the logo returns to the dashboard", async ({ page }) => {
    await gotoApp(page, "/scan");
    await page.locator("header a").first().click();

    await expect(page).toHaveURL(/\/$/);
  });

  test("deep-linking straight to a route works (SPA fallback)", async ({ page }) => {
    await gotoApp(page, "/system");
    await expect(page.getByText("Component Versions").first()).toBeVisible();
  });

  test("an unknown route renders the 404 page", async ({ page }) => {
    await gotoApp(page, "/this-route-does-not-exist");

    await expect(page.getByText("404")).toBeVisible();
    await expect(page.getByText("Oops! Page not found")).toBeVisible();
    await expect(page.getByRole("link", { name: "Return to Home" })).toBeVisible();
  });
});
