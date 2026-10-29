import { expect, test } from "@playwright/test";

import {
  ARR_API_KEY,
  JELLYFIN_API_KEY,
  JELLYFIN_LIBRARY,
  JELLYFIN_URL,
  RADARR_URL,
} from "../playwright.config";
import {
  gotoApp,
  markJellyfinUnconfigured,
  markUnconfigured,
  seedJellyfinMedia,
  setJellyfinMode,
} from "./helpers";

test.describe("setup wizard media server step", () => {
  test.beforeEach(async ({ request }) => {
    // An unconfigured instance, which is what sends the user to the wizard
    await markUnconfigured(request);
    await markJellyfinUnconfigured(request);
    await setJellyfinMode(request, "default");
    seedJellyfinMedia();
  });

  async function openServerChoice(page: import("@playwright/test").Page) {
    await gotoApp(page, "/setup");
    await page.getByRole("button", { name: "Get Started" }).click();
    await expect(page.getByRole("heading", { name: /choose your media server/i })).toBeVisible();
  }

  test("the welcome screen does not assume Plex", async ({ page }) => {
    await gotoApp(page, "/setup");

    await expect(page.getByText("Welcome to deduparr!")).toBeVisible();
    // Jellyfin-only users are not told they need a Plex account
    await expect(page.getByText(/Plex or Jellyfin/i)).toBeVisible();
    await expect(page.getByText("A Plex account (free or Plex Pass)")).toHaveCount(0);
    await expect(page.getByText("Access to your Plex server")).toHaveCount(0);
  });

  test("the wizard asks which media server to use", async ({ page }) => {
    await openServerChoice(page);

    await expect(page.locator("#choose-plex")).toBeVisible();
    await expect(page.locator("#choose-jellyfin")).toBeVisible();
  });

  test("continuing needs at least one server selected", async ({ page }) => {
    await openServerChoice(page);

    // Nothing is pre-selected, so Continue starts unavailable
    await expect(page.locator("#choose-plex")).not.toBeChecked();
    await expect(page.locator("#choose-jellyfin")).not.toBeChecked();
    await expect(page.getByTestId("server-choice-continue")).toBeDisabled();
    await expect(page.getByText("Select at least one media server")).toBeVisible();

    await page.locator("#choose-jellyfin").check();
    await expect(page.getByTestId("server-choice-continue")).toBeEnabled();
  });

  test("Jellyfin alone leads straight to its own step, skipping Plex", async ({ page }) => {
    await openServerChoice(page);

    await page.locator("#choose-jellyfin").check();
    await page.getByTestId("server-choice-continue").click();

    await expect(page.getByRole("heading", { name: /connect jellyfin/i })).toBeVisible();
    // No Plex step was shown on the way
    await expect(page.getByRole("heading", { name: /authenticate with plex/i })).toHaveCount(0);
  });

  async function openJellyfinStep(page: import("@playwright/test").Page) {
    await openServerChoice(page);
    await page.locator("#choose-jellyfin").check();
    await page.getByTestId("server-choice-continue").click();
    await expect(page.getByRole("heading", { name: /connect jellyfin/i })).toBeVisible();
  }

  /** Through a proven Jellyfin connection and one chosen library. */
  async function openServicesStep(page: import("@playwright/test").Page) {
    await openJellyfinStep(page);
    await page.locator("#jellyfin-url").fill(JELLYFIN_URL);
    await page.locator("#jellyfin-api-key").fill(JELLYFIN_API_KEY);
    await page.getByTestId("jellyfin-test").click();
    await page.getByTestId("jellyfin-continue").click();
    await page.getByText(JELLYFIN_LIBRARY).click();
    await page.getByRole("button", { name: "Next: Services" }).click();
  }

  test("the Jellyfin step will not continue until the connection is proven", async ({ page }) => {
    await openJellyfinStep(page);

    // Nothing entered: both test and continue are unavailable
    await expect(page.getByTestId("jellyfin-test")).toBeDisabled();
    await expect(page.getByTestId("jellyfin-continue")).toBeDisabled();

    await page.locator("#jellyfin-url").fill(JELLYFIN_URL);
    await page.locator("#jellyfin-api-key").fill("not-an-admin-key");
    await expect(page.getByTestId("jellyfin-test")).toBeEnabled();

    await page.getByTestId("jellyfin-test").click();
    await expect(page.getByText(/connection failed|administrator|invalid/i).first()).toBeVisible();
    await expect(page.getByTestId("jellyfin-continue")).toBeDisabled();
  });

  test("a good key reveals the libraries that server holds", async ({ page }) => {
    await openJellyfinStep(page);

    await page.locator("#jellyfin-url").fill(JELLYFIN_URL);
    await page.locator("#jellyfin-api-key").fill(JELLYFIN_API_KEY);
    await page.getByTestId("jellyfin-test").click();

    await expect(page.getByText("Fake Jellyfin").first()).toBeVisible();
    await expect(page.getByTestId("jellyfin-continue")).toBeEnabled();

    await page.getByTestId("jellyfin-continue").click();

    await expect(page.getByRole("heading", { name: /select libraries/i })).toBeVisible();
    await expect(page.getByText(JELLYFIN_LIBRARY)).toBeVisible();
    // Music is not something Deduparr deduplicates
    await expect(page.getByText("Fake Music")).toHaveCount(0);
    // Each library is labelled with the server it came from
    await expect(page.getByText("on Jellyfin")).toHaveCount(2);
  });

  test("the Jellyfin step can go back to the server choice", async ({ page }) => {
    await openJellyfinStep(page);

    await page.getByRole("button", { name: "Back" }).click();

    await expect(page.getByRole("heading", { name: /choose your media server/i })).toBeVisible();
  });

  test("changing the key after a good test asks for another test", async ({ page }) => {
    await openJellyfinStep(page);
    await page.locator("#jellyfin-url").fill(JELLYFIN_URL);
    await page.locator("#jellyfin-api-key").fill(JELLYFIN_API_KEY);
    await page.getByTestId("jellyfin-test").click();
    await expect(page.getByTestId("jellyfin-continue")).toBeEnabled();

    await page.locator("#jellyfin-api-key").fill("someone-elses-key");

    await expect(page.getByTestId("jellyfin-continue")).toBeDisabled();
    await expect(page.getByText("Connection successful")).toHaveCount(0);
  });

  test("the services step tests each connection for real", async ({ page }) => {
    await openServicesStep(page);
    const testRadarr = page.getByRole("button", { name: "Test Connection" }).first();

    // It used to report success for anything, without asking the service
    await page.locator("#radarr-url").fill(RADARR_URL);
    await page.locator("#radarr-key").fill("wrong-key");
    await testRadarr.click();
    await expect(page.getByText(/invalid or unauthorized/i)).toBeVisible();

    await page.locator("#radarr-key").fill(ARR_API_KEY);
    await testRadarr.click();
    await expect(page.getByText("Version: 5.0.0.0")).toBeVisible();
  });

  test("finishing with Jellyfin alone lands on the dashboard", async ({ page }) => {
    await openServicesStep(page);

    await page.getByRole("button", { name: "Complete Setup" }).click();

    // The app kept the configuration it loaded before setup, and sent the
    // user straight back to the wizard
    await expect(page.getByRole("heading", { name: /dashboard/i })).toBeVisible();
    await expect(page).not.toHaveURL(/\/setup/);
  });
});
