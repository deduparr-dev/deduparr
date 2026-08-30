import { test, expect } from "@playwright/test";
import { getConfig, gotoApp, markConfigured, setConfig } from "./helpers";

test.describe("settings", () => {
  test.beforeEach(async ({ request }) => {
    await markConfigured(request);
    await setConfig(request, "enable_deep_scan", "false");
  });

  test("renders the configuration sections", async ({ page }) => {
    await gotoApp(page, "/settings");

    await expect(page.getByText("General Settings").first()).toBeVisible();
    await expect(page.getByText("Scan Settings").first()).toBeVisible();
    await expect(page.getByText("Email Notifications").first()).toBeVisible();
  });

  test("deep scan reflects the value stored in the backend", async ({ page, request }) => {
    await setConfig(request, "enable_deep_scan", "true");
    await gotoApp(page, "/settings");

    await expect(page.locator("#enable-deep-scan")).toBeChecked();
  });

  test("toggling deep scan and saving persists to the backend", async ({ page, request }) => {
    await gotoApp(page, "/settings");

    const deepScan = page.locator("#enable-deep-scan");
    await expect(deepScan).not.toBeChecked();

    await deepScan.check();
    await page.getByRole("button", { name: "Save Configuration" }).click();

    // The value really reached the database, not just React state.
    await expect
      .poll(async () => (await getConfig(request)).enable_deep_scan, { timeout: 10_000 })
      .toBe("true");
  });

  test("a saved setting survives a full page reload", async ({ page }) => {
    await gotoApp(page, "/settings");

    await page.locator("#enable-deep-scan").check();
    await page.getByRole("button", { name: "Save Configuration" }).click();

    await expect(page.locator("#enable-deep-scan")).toBeChecked();

    await gotoApp(page, "/settings");
    await expect(page.locator("#enable-deep-scan")).toBeChecked();
  });

  test("email notification fields appear only when enabled", async ({ page }) => {
    await gotoApp(page, "/settings");

    const toggle = page.locator("#enable-email-notifications");
    await expect(page.locator("#notification-email")).toBeHidden();

    await toggle.check();
    await expect(page.locator("#notification-email")).toBeVisible();
    await expect(page.locator("#smtp-host")).toBeVisible();
  });
});
