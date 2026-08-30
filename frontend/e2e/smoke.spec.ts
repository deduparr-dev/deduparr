import { test, expect } from "@playwright/test";
import { BACKEND_URL } from "../playwright.config";
import { gotoApp, markConfigured } from "./helpers";

test.describe("smoke", () => {
  test("backend health endpoint responds", async ({ request }) => {
    const res = await request.get(`${BACKEND_URL}/health`);
    expect(res.ok()).toBeTruthy();

    const body = await res.json();
    expect(body.status).toBe("ok");
    expect(body.version).toBeTruthy();
  });

  test("frontend serves the built SPA", async ({ page, request }) => {
    await markConfigured(request);
    await gotoApp(page, "/");

    await expect(page).toHaveTitle(/deduparr/i);
    // The app shell rendered rather than an empty root div.
    await expect(page.locator("#root")).not.toBeEmpty();
  });

  test("api requests are proxied through the frontend origin", async ({ page }) => {
    const res = await page.request.get("/api/config/");
    expect(res.ok()).toBeTruthy();
    expect(typeof (await res.json())).toBe("object");
  });
});
