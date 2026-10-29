import { APIRequestContext, expect, Page } from "@playwright/test";
import fs from "fs";
import path from "path";

import {
  ARR_API_KEY,
  BACKEND_URL,
  E2E_TMP,
  JELLYFIN_API_KEY,
  JELLYFIN_LIBRARY,
  JELLYFIN_URL,
  QBIT_PASSWORD,
  QBIT_URL,
  QBIT_USERNAME,
  RADARR_URL,
  SONARR_URL,
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
  await setConfig(request, "jellyfin_libraries", JELLYFIN_LIBRARY);
}

export async function markJellyfinUnconfigured(request: APIRequestContext) {
  await deleteConfig(request, "jellyfin_url");
  await deleteConfig(request, "jellyfin_api_key");
}

const SERVICE_CONFIG = {
  radarr_url: RADARR_URL,
  radarr_api_key: ARR_API_KEY,
  sonarr_url: SONARR_URL,
  sonarr_api_key: ARR_API_KEY,
  qbittorrent_url: QBIT_URL,
  qbittorrent_username: QBIT_USERNAME,
  qbittorrent_password: QBIT_PASSWORD,
};

/** Point Deduparr at the stand-in Radarr, Sonarr and qBittorrent. */
export async function markServicesConfigured(request: APIRequestContext) {
  for (const [key, value] of Object.entries(SERVICE_CONFIG)) {
    await setConfig(request, key, value);
  }
}

export async function markServicesUnconfigured(request: APIRequestContext) {
  for (const key of Object.keys(SERVICE_CONFIG)) {
    await deleteConfig(request, key);
  }
}

/** Put the stand-in services back to their starting state, around one title. */
export async function resetServices(request: APIRequestContext, title?: string) {
  for (const url of [RADARR_URL, SONARR_URL, QBIT_URL]) {
    const res = await request.post(`${url}/reset`, { data: { title } });
    expect(res.ok()).toBeTruthy();
  }
}

/** What a stand-in service holds, and what Deduparr asked of it. */
export async function serviceState(request: APIRequestContext, url: string) {
  const res = await request.get(`${url}/state`);
  expect(res.ok()).toBeTruthy();
  return res.json();
}

/** Where the stand-in Jellyfin's mode puts a movie's two copies. */
type MovieLayout = "default" | "split" | "loose";

/**
 * Create the files the stand-in Jellyfin claims to hold, laid out as its mode
 * has them.
 *
 * A duplicate set is only stored when every file is present on disk, so these
 * have to exist for a scan to produce anything.
 */
export function seedJellyfinMedia(
  title = "Fake Duplicate (2024)",
  layout: MovieLayout = "default"
) {
  const movies = path.join(E2E_TMP, "media", "Movies");
  const keepDir = layout === "loose" ? movies : path.join(movies, title);
  const dropDir =
    layout === "split" ? path.join(E2E_TMP, "media", "Movies 4K", title) : path.join(movies, title);
  const keep = (name: string, size: number) => writeFile(path.join(keepDir, name), size);
  const drop = (name: string, size: number) => writeFile(path.join(dropDir, name), size);

  writeFile(path.join(movies, "Fake Single (2024)", "Fake Single (2024) 1080p.mkv"), 5_000_000);

  return {
    keep: keep(`${title} 1080p.mkv`, 8_000_000),
    keepSidecar: keep(`${title} 1080p.en.srt`, 10),
    drop: drop(`${title} 720p.mkv`, 2_000_000),
    dropSidecars: [drop(`${title} 720p.nfo`, 10), drop(`${title} 720p.en.srt`, 10)],
  };
}

/**
 * Create the episode the stand-in Jellyfin's "episodes" mode holds twice,
 * beside another episode from the same season pack and the season's subtitles.
 */
export function seedEpisodeMedia() {
  const season = path.join(E2E_TMP, "media", "Shows", "Fake Show", "Season 1");
  const file = (name: string, size: number) => writeFile(path.join(season, name), size);

  return {
    keep: file("Fake Show - S01E02 1080p.mkv", 4_000_000),
    drop: file("Fake Show - S01E02 480p.mkv", 700_000),
    sibling: file("Fake Show - S01E03 480p.mkv", 700_000),
    subtitles: file("Subs/Fake Show - S01E03.en.srt", 10),
  };
}

function writeFile(filePath: string, size: number) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, Buffer.alloc(size, 1));
  return filePath;
}

/** Point the stand-in Jellyfin at a different library state. */
export async function setJellyfinMode(
  request: APIRequestContext,
  mode: MovieLayout | "empty" | "no-duplicates" | "episodes",
  title?: string
) {
  const res = await request.post(`${JELLYFIN_URL}/reset`, { data: { mode, title } });
  expect(res.ok()).toBeTruthy();
}

/**
 * Run a scan through the real API and return what it reported. The libraries
 * given per server become the stored selection; left out, it is scanned as is.
 */
export async function runScan(request: APIRequestContext, libraries?: Record<string, string[]>) {
  const res = await request.post(`${BACKEND_URL}/api/scan/start`, {
    data: libraries ? { libraries } : {},
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

/**
 * A title no earlier run can have used.
 *
 * The e2e database is not reset between runs, and a processed set is kept on
 * purpose as a record of a decision, so a spec that creates and deletes a set
 * has to work on its own title each time.
 */
export function uniqueTitle(prefix: string) {
  return `${prefix} (${Date.now().toString(36)})`;
}
