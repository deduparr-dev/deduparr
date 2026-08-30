import { APIRequestContext, expect, Page } from "@playwright/test";
import { BACKEND_URL } from "../playwright.config";

/** Overwrite a single config key through the real API. */
export async function setConfig(request: APIRequestContext, key: string, value: string | null) {
  const res = await request.put(`${BACKEND_URL}/api/config/${key}`, { data: { value } });
  expect(res.ok()).toBeTruthy();
}

export async function deleteConfig(request: APIRequestContext, key: string) {
  await request.delete(`${BACKEND_URL}/api/config/${key}`);
}

export async function getConfig(
  request: APIRequestContext
): Promise<Record<string, string | null>> {
  const res = await request.get(`${BACKEND_URL}/api/config/`);
  expect(res.ok()).toBeTruthy();
  return res.json();
}

/**
 * Put the instance into the "Plex is configured" state that App.tsx checks
 * before it stops redirecting to the setup wizard.
 */
export async function markConfigured(request: APIRequestContext) {
  await setConfig(request, "plex_auth_token", "e2e-test-token");
  await setConfig(request, "plex_server_name", "E2E Test Server");
}

export async function markUnconfigured(request: APIRequestContext) {
  await deleteConfig(request, "plex_auth_token");
  await deleteConfig(request, "plex_server_name");
}

/** Wait for the SPA to hydrate and the initial config query to settle. */
export async function gotoApp(page: Page, path: string) {
  await page.goto(path);
  await page.waitForLoadState("networkidle");
}
