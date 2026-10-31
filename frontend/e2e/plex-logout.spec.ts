import { expect, test, type Page } from "@playwright/test";

import {
  deleteConfig,
  getConfig,
  gotoApp,
  markConfigured,
  markJellyfinConfigured,
  markJellyfinUnconfigured,
  setConfig,
} from "./helpers";

test.describe("logging out of Plex", () => {
  test.beforeEach(async ({ request }) => {
    await markConfigured(request);
  });

  test.afterEach(async ({ request }) => {
    await markConfigured(request);
    await markJellyfinUnconfigured(request);
    await deleteConfig(request, "plex_libraries");
  });

  async function logOut(page: Page) {
    await gotoApp(page, "/settings");
    await page.getByRole("button", { name: "Plex" }).click();
    await page.getByTestId("plex-logout").click();
  }

  test("Settings says so when Plex rejects the sign-in", async ({ page }) => {
    const detail = "Plex server rejected the authentication token.";
    await page.route("**/api/setup/plex/servers", (route) =>
      route.fulfill({ status: 500, json: { detail } })
    );

    await gotoApp(page, "/settings");
    await page.getByRole("button", { name: "Plex" }).click();

    await expect(page.getByTestId("plex-status")).toHaveText(detail);
  });

  test("a scan says it skipped Plex when Plex cannot be read", async ({ page, request }) => {
    await markJellyfinConfigured(request);
    await setConfig(request, "plex_libraries", "Movies");

    await gotoApp(page, "/scan");
    await page.getByRole("button", { name: "Start Scan" }).click();

    await expect(page.getByText("Scan Incomplete", { exact: true })).toBeVisible();
    await expect(page.getByText(/^Skipped Plex: /)).toBeVisible();
  });

  test("keeps Jellyfin and goes to the dashboard", async ({ page, request }) => {
    await markJellyfinConfigured(request);

    await logOut(page);

    await expect(page).toHaveURL(/:\d+\/$/);
    const config = await getConfig(request);
    expect(config.plex_auth_token ?? null).toBeNull();
    expect(config.plex_server_name ?? null).toBeNull();
    expect(config.jellyfin_url).toBeTruthy();
    expect(config.jellyfin_api_key).toBeTruthy();
  });

  test("goes to the wizard when no media server is left", async ({ page, request }) => {
    await markJellyfinUnconfigured(request);

    await logOut(page);

    await expect(page).toHaveURL(/\/setup$/);
    expect((await getConfig(request)).plex_auth_token ?? null).toBeNull();
  });
});
