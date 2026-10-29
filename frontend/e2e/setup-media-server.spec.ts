import { expect, test, type Page, type Route } from "@playwright/test";

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

  test("going back from the libraries returns to the server set up last", async ({ page }) => {
    await openServerChoice(page);
    await page.locator("#choose-jellyfin").check();
    await page.getByTestId("server-choice-continue").click();
    await page.locator("#jellyfin-url").fill(JELLYFIN_URL);
    await page.locator("#jellyfin-api-key").fill(JELLYFIN_API_KEY);
    await page.getByTestId("jellyfin-test").click();
    await page.getByTestId("jellyfin-continue").click();
    await expect(page.getByText(JELLYFIN_LIBRARY)).toBeVisible();

    // It went to the Plex step, which a Jellyfin-only setup never had
    await page.getByRole("button", { name: "Back" }).click();
    await expect(page.getByRole("heading", { name: /connect jellyfin/i })).toBeVisible();
  });
});

/**
 * Stand in for a signed-in plex.tv account with one server and one movie
 * library, answering the wizard's Plex calls in the browser.
 */
async function signInToPlex(page: Page) {
  const reply = (body: unknown) => (route: Route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
  await page.route("**/api/setup/plex/auth/initiate", reply({ pin_id: "1", auth_url: "" }));
  await page.route(
    "**/api/setup/plex/auth/check/1",
    reply({ success: true, encrypted_token: "plex-token" })
  );
  await page.route(
    "**/api/setup/plex/servers",
    reply({
      servers: [
        {
          name: "Home",
          client_identifier: "home",
          product: "Plex Media Server",
          platform: "Linux",
          owned: true,
        },
      ],
    })
  );
  await page.route(
    "**/api/setup/plex/libraries",
    reply([{ key: "1", title: "Plex Movies", type: "movie" }])
  );
}

test.describe("setup wizard Plex steps", () => {
  test.beforeEach(async ({ page, request }) => {
    await markUnconfigured(request);
    await markJellyfinUnconfigured(request);
    await setJellyfinMode(request, "default");
    await signInToPlex(page);
    await gotoApp(page, "/setup");
    await page.getByRole("button", { name: "Get Started" }).click();
  });

  test("with Jellyfin chosen too, it is set up after signing in to Plex", async ({ page }) => {
    await page.locator("#choose-plex").check();
    await page.locator("#choose-jellyfin").check();
    await page.getByTestId("server-choice-continue").click();

    // It went straight to the libraries, and Jellyfin was never saved
    await expect(page.getByRole("heading", { name: /connect jellyfin/i })).toBeVisible();
    await page.locator("#jellyfin-url").fill(JELLYFIN_URL);
    await page.locator("#jellyfin-api-key").fill(JELLYFIN_API_KEY);
    await page.getByTestId("jellyfin-test").click();
    await page.getByTestId("jellyfin-continue").click();

    await expect(page.getByText("Plex Movies")).toBeVisible();
    await expect(page.getByText(JELLYFIN_LIBRARY)).toBeVisible();
  });

  test("the Plex step's test signs in with the token and server", async ({ page }) => {
    let sent: unknown;
    await page.route("**/api/setup/test/plex", async (route) => {
      sent = { method: route.request().method(), body: route.request().postDataJSON() };
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ success: true, server_name: "Home", version: "1.42.1" }),
      });
    });
    await page.locator("#choose-plex").check();
    await page.getByTestId("server-choice-continue").click();
    await expect(page.getByText("Plex Movies")).toBeVisible();
    await page.getByRole("button", { name: "Back" }).click();
    await expect(page.getByRole("heading", { name: "Connect to Plex" })).toBeVisible();

    // A GET this route does not take, so the test always failed and Next never came
    await page.getByRole("button", { name: "Test Connection" }).click();
    await expect(page.getByText("Connection successful")).toBeVisible();
    expect(sent).toEqual({
      method: "POST",
      body: { auth_token: "plex-token", server_name: "Home" },
    });
    await page.getByRole("button", { name: "Next: Libraries" }).click();
    await expect(page.getByText("Plex Movies")).toBeVisible();
  });
});
