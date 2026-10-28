import { expect, test } from "@playwright/test";

import { JELLYFIN_API_KEY, JELLYFIN_URL } from "../playwright.config";
import { getConfig, gotoApp, markConfigured, markJellyfinUnconfigured, setConfig } from "./helpers";

test.describe("settings jellyfin tab", () => {
  test.beforeEach(async ({ request }) => {
    // Plex configured, so the app does not redirect to the wizard
    await markConfigured(request);
    await markJellyfinUnconfigured(request);
  });

  test("the Jellyfin tab renders its fields and shows the saved url", async ({ page, request }) => {
    // The tab existed once while its panel rendered nothing at all
    await setConfig(request, "jellyfin_url", JELLYFIN_URL);
    await gotoApp(page, "/settings");

    await page.getByRole("button", { name: "Jellyfin" }).click();

    await expect(page.getByRole("heading", { name: /jellyfin configuration/i })).toBeVisible();
    await expect(page.locator("#url")).toBeVisible();
    await expect(page.locator("#api-key")).toBeVisible();
    await expect(page.getByRole("button", { name: "Test Connection" })).toBeVisible();

    // The stored url is shown, and the default port hint is Jellyfin's
    await expect(page.locator("#url")).toHaveValue(JELLYFIN_URL);
    await expect(page.locator("#url")).toHaveAttribute("placeholder", "http://localhost:8096");
  });

  test("a saved api key is never rendered back into the field", async ({ page, request }) => {
    await setConfig(request, "jellyfin_url", JELLYFIN_URL);
    await setConfig(request, "jellyfin_api_key", JELLYFIN_API_KEY);
    await gotoApp(page, "/settings");

    await page.getByRole("button", { name: "Jellyfin" }).click();

    // Empty, because the stored value is ciphertext; the placeholder says so
    await expect(page.locator("#api-key")).toHaveValue("");
    await expect(page.locator("#api-key")).toHaveAttribute("placeholder", /Saved/i);
  });

  test("Jellyfin can be added to an instance that already runs Plex", async ({ page, request }) => {
    await gotoApp(page, "/settings");

    await page.getByRole("button", { name: "Jellyfin" }).click();
    await page.locator("#url").fill(JELLYFIN_URL);
    await page.locator("#api-key").fill(JELLYFIN_API_KEY);

    await page.getByRole("button", { name: "Test Connection" }).click();
    await expect(page.getByText(/Fake Jellyfin|connected|success/i).first()).toBeVisible();

    await page.getByRole("button", { name: "Save Configuration" }).click();

    await expect
      .poll(async () => (await getConfig(request)).jellyfin_url, { timeout: 10_000 })
      .toBe(JELLYFIN_URL);
  });

  test("a bad key is reported rather than silently saved", async ({ page }) => {
    await gotoApp(page, "/settings");

    await page.getByRole("button", { name: "Jellyfin" }).click();
    await page.locator("#url").fill(JELLYFIN_URL);
    await page.locator("#api-key").fill("not-an-admin-key");

    await page.getByRole("button", { name: "Test Connection" }).click();

    await expect(page.getByText(/administrator|invalid|failed/i).first()).toBeVisible();
  });

  test("the api key is never stored in the clear", async ({ request }) => {
    // The config API used to persist secrets verbatim, so only the wizard
    // encrypted them
    const res = await request.put("/api/config/jellyfin_api_key", {
      data: { value: "super-secret-key" },
    });
    expect(res.ok()).toBeTruthy();

    const stored = (await getConfig(request)).jellyfin_api_key;
    expect(stored).toBeTruthy();
    expect(stored).not.toBe("super-secret-key");
  });
});
