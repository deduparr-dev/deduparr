import { APIRequestContext, expect, Page } from "@playwright/test";
import fs from "fs";
import path from "path";

import {
  BACKEND_URL,
  E2E_TMP,
  JELLYFIN_API_KEY,
  JELLYFIN_LIBRARY,
  JELLYFIN_URL,
} from "../playwright.config";

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

/** Put the instance into the "Jellyfin is configured" state, with no Plex. */
export async function markJellyfinConfigured(request: APIRequestContext) {
  await setConfig(request, "jellyfin_url", JELLYFIN_URL);
  await setConfig(request, "jellyfin_api_key", JELLYFIN_API_KEY);
  await setConfig(request, "media_libraries", JELLYFIN_LIBRARY);
}

export async function markJellyfinUnconfigured(request: APIRequestContext) {
  await deleteConfig(request, "jellyfin_url");
  await deleteConfig(request, "jellyfin_api_key");
}

/**
 * Create the files the stand-in Jellyfin claims to hold.
 *
 * A duplicate set is only stored when every file is present on disk, so these
 * have to exist for a scan to produce anything.
 */
export function seedJellyfinMedia() {
  const dir = path.join(E2E_TMP, "media", "Movies", "Fake Duplicate (2024)");
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, "Fake Duplicate (2024) 1080p.mkv"), Buffer.alloc(8_000_000, 1));
  fs.writeFileSync(path.join(dir, "Fake Duplicate (2024) 720p.mkv"), Buffer.alloc(2_000_000, 2));

  const single = path.join(E2E_TMP, "media", "Movies", "Fake Single (2024)");
  fs.mkdirSync(single, { recursive: true });
  fs.writeFileSync(path.join(single, "Fake Single (2024) 1080p.mkv"), Buffer.alloc(5_000_000, 3));

  return {
    keep: path.join(dir, "Fake Duplicate (2024) 1080p.mkv"),
    drop: path.join(dir, "Fake Duplicate (2024) 720p.mkv"),
  };
}

/** Point the stand-in Jellyfin at a different library state. */
export async function setJellyfinMode(
  request: APIRequestContext,
  mode: "default" | "empty" | "no-duplicates"
) {
  const res = await request.post(`${JELLYFIN_URL}/reset`, { data: { mode } });
  expect(res.ok()).toBeTruthy();
}

/** Run a scan through the real API and return what it reported. */
export async function runScan(request: APIRequestContext, libraries: string[]) {
  const res = await request.post(`${BACKEND_URL}/api/scan/start`, {
    data: { library_names: libraries, media_types: ["movie"] },
  });
  if (!res.ok()) {
    throw new Error(`scan failed: HTTP ${res.status()} ${await res.text()}`);
  }
  return res.json();
}

/** Remove every duplicate set, so a spec starts from a known state. */
export async function clearDuplicates(request: APIRequestContext) {
  const res = await request.post(`${BACKEND_URL}/api/scan/duplicates/delete-all`, {
    data: { dry_run: false },
  });
  expect(res.ok()).toBeTruthy();
}
