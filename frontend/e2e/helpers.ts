import { APIRequestContext, expect, Page } from "@playwright/test";
import fs from "fs";
import path from "path";

import { BACKEND_URL, E2E_TMP } from "../playwright.config";

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

/**
 * Create a duplicate set from two real files on disk via the dev disk scan.
 * Returns the paths, highest-scoring first.
 */
export async function seedDuplicateSet(
  request: APIRequestContext,
  title: string
): Promise<{ keep: string; drop: string }> {
  const dir = path.join(E2E_TMP, "media", "Movies", title);
  fs.mkdirSync(dir, { recursive: true });

  const keep = path.join(dir, `${title} 1080p BluRay x265.mkv`);
  const drop = path.join(dir, `${title} 720p HDTV x264.mkv`);
  fs.writeFileSync(keep, Buffer.alloc(3_000_000, 1));
  fs.writeFileSync(drop, Buffer.alloc(1_000_000, 2));

  const res = await request.post(`${BACKEND_URL}/api/scan/dev/disk-scan`, {
    data: { paths: [path.join(E2E_TMP, "media", "Movies")] },
  });
  expect(res.ok()).toBeTruthy();

  return { keep, drop };
}

/** Pending duplicate sets, as the API reports them. */
export async function getPendingSets(
  request: APIRequestContext
): Promise<{ id: number; title: string; status: string }[]> {
  const res = await request.get(`${BACKEND_URL}/api/scan/duplicates?status=pending`);
  expect(res.ok()).toBeTruthy();
  return res.json();
}
