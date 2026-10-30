import { test, expect } from "@playwright/test";
import {
  getConfig,
  gotoApp,
  markConfigured,
  markJellyfinConfigured,
  markJellyfinUnconfigured,
  markServicesConfigured,
  markServicesUnconfigured,
  setConfig,
} from "./helpers";

test.describe("settings", () => {
  test.beforeEach(async ({ request }) => {
    await markConfigured(request);
    await setConfig(request, "enable_deep_scan", "false");
    await setConfig(request, "prefer_arr_quality_profile", "false");
    await setConfig(request, "radarr_path_mappings", "");
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

  test("toggling *arr quality profile and saving persists to the backend", async ({
    page,
    request,
  }) => {
    await gotoApp(page, "/settings");

    const preferArr = page.locator("#prefer-arr-quality-profile");
    await expect(preferArr).not.toBeChecked();

    await preferArr.check();
    await page.getByRole("button", { name: "Save Configuration" }).click();

    await expect
      .poll(async () => (await getConfig(request)).prefer_arr_quality_profile, {
        timeout: 10_000,
      })
      .toBe("true");
  });

  test("Radarr path mappings are saved, and can be cleared", async ({ page, request }) => {
    await gotoApp(page, "/settings");
    await page.getByRole("button", { name: "Radarr" }).click();

    const mappings = page.locator("#path-mappings");
    await mappings.fill("/data/movies=/movies");
    await page.getByRole("button", { name: "Save Configuration" }).click();

    await expect
      .poll(async () => (await getConfig(request)).radarr_path_mappings, { timeout: 10_000 })
      .toBe("/data/movies=/movies");

    await gotoApp(page, "/settings");
    await page.getByRole("button", { name: "Radarr" }).click();
    await expect(page.locator("#path-mappings")).toHaveValue("/data/movies=/movies");

    await page.locator("#path-mappings").fill("");
    await page.getByRole("button", { name: "Save Configuration" }).click();
    await expect
      .poll(async () => (await getConfig(request)).radarr_path_mappings, { timeout: 10_000 })
      .toBe("");
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

test.describe("settings connection tests", () => {
  test.beforeEach(async ({ request }) => {
    await markConfigured(request);
    await markJellyfinConfigured(request);
    await markServicesConfigured(request);
  });

  test.afterEach(async ({ request }) => {
    await markServicesUnconfigured(request);
    await markJellyfinUnconfigured(request);
  });

  // The saved Jellyfin key is kept out of its field, and the saved qBittorrent
  // password went back encrypted twice: both tests failed with nothing retyped
  for (const tab of ["Jellyfin", "Radarr", "Sonarr", "qBittorrent"]) {
    test(`${tab} tests with what is saved`, async ({ page }) => {
      await gotoApp(page, "/settings");
      await page.getByRole("button", { name: tab, exact: true }).click();
      await page.getByRole("button", { name: "Test Connection" }).click();

      await expect(page.getByText("Connection successful")).toBeVisible();
    });
  }

  test("a failed test says why", async ({ page }) => {
    await gotoApp(page, "/settings");
    await page.getByRole("button", { name: "Radarr", exact: true }).click();
    await page.locator("#api-key").fill("not-the-key");
    await page.getByRole("button", { name: "Test Connection" }).click();

    await expect(page.getByText("Connection failed")).toBeVisible();
    await expect(page.getByText("API key invalid or unauthorized")).toBeVisible();
  });
});
