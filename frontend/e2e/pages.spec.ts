import { test, expect } from "@playwright/test";
import { gotoApp, markConfigured } from "./helpers";

test.describe("pages", () => {
  test.beforeEach(async ({ request }) => {
    await markConfigured(request);
  });

  test("dashboard renders its activity panels on a fresh install", async ({ page }) => {
    await gotoApp(page, "/");

    await expect(page.getByText("Recent Activity").first()).toBeVisible();
    await expect(page.getByText("Recent Deletions").first()).toBeVisible();
  });

  test("system page reports live component versions from the backend", async ({ page }) => {
    await gotoApp(page, "/system");

    await expect(page.getByText("Component Versions").first()).toBeVisible();
    await expect(page.getByText("Python:").first()).toBeVisible();
    await expect(page.getByText("FastAPI:").first()).toBeVisible();
  });

  test("scan page offers the scan entry point", async ({ page }) => {
    await gotoApp(page, "/scan");

    await expect(page.getByText("Scan for Duplicates").first()).toBeVisible();
  });

  test("no page logs an uncaught application error", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));

    for (const path of ["/", "/scan", "/settings", "/system"]) {
      await gotoApp(page, path);
    }

    expect(errors).toEqual([]);
  });
});
