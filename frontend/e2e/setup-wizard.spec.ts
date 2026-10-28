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

  test("Get Started asks which media server to use", async ({ page }) => {
    await gotoApp(page, "/setup");
    await page.getByRole("button", { name: "Get Started" }).click();

    // Plex is no longer assumed, so the first question is which server
    await expect(page.getByRole("heading", { name: /choose your media server/i })).toBeVisible();
    // The welcome copy is gone, so the wizard actually changed step.
    await expect(page.getByText("Welcome to deduparr!")).toBeHidden();
  });

  test("the progress indicator appears once past the welcome step", async ({ page }) => {
    await gotoApp(page, "/setup");

    // Nothing to show progress through while still on the welcome screen
    await expect(page.getByTestId("wizard-progress")).toHaveCount(0);

    await page.getByRole("button", { name: "Get Started" }).click();

    await expect(page.getByTestId("wizard-progress")).toBeVisible();
  });
});
