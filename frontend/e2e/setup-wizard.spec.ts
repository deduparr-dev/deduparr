import { test, expect } from "@playwright/test";
import { gotoApp, markUnconfigured } from "./helpers";

test.describe("setup wizard", () => {
  test.beforeEach(async ({ request }) => {
    await markUnconfigured(request);
  });

  test("an unconfigured instance redirects the dashboard to /setup", async ({ page }) => {
    await gotoApp(page, "/");
    await expect(page).toHaveURL(/\/setup$/);
  });

  test("welcome step explains what the wizard needs", async ({ page }) => {
    await gotoApp(page, "/setup");

    await expect(page.getByText("Welcome to deduparr!")).toBeVisible();
    await expect(page.getByText("Access to your Plex server")).toBeVisible();
    await expect(page.getByRole("button", { name: "Get Started" })).toBeVisible();
  });

  test("Get Started advances to the Plex authentication step", async ({ page }) => {
    await gotoApp(page, "/setup");
    await page.getByRole("button", { name: "Get Started" }).click();

    await expect(page.getByText("Authenticate with Plex")).toBeVisible();
    // The welcome copy is gone, so the wizard actually changed step.
    await expect(page.getByText("Welcome to deduparr!")).toBeHidden();
  });

  test("the progress indicator appears once past the welcome step", async ({ page }) => {
    await gotoApp(page, "/setup");
    await page.getByRole("button", { name: "Get Started" }).click();

    await expect(page.getByText("Authenticate with Plex")).toBeVisible();
  });
});
