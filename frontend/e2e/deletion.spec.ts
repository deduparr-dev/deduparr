import fs from "fs";
import path from "path";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { JELLYFIN_LIBRARY, QBIT_URL, RADARR_URL, SONARR_URL } from "../playwright.config";
import {
  clearDuplicates,
  getPendingSets,
  gotoApp,
  markJellyfinConfigured,
  markServicesConfigured,
  markServicesUnconfigured,
  markUnconfigured,
  resetServices,
  runScan,
  seedEpisodeMedia,
  seedJellyfinMedia,
  serviceState,
  setJellyfinMode,
  uniqueTitle,
} from "./helpers";

/** Delete one set for real, the way a user does it on the Scan page. */
async function deleteFromScanPage(page: Page, request: APIRequestContext, title: string) {
  const set = (await getPendingSets(request)).find((s: { title: string }) => s.title === title);
  expect(set).toBeTruthy();

  await gotoApp(page, "/scan");
  const card = page.getByTestId(`duplicate-set-${set.id}`);
  await card.getByRole("button", { name: "Delete Duplicates" }).click();
  await card.getByRole("checkbox", { name: /dry run/i }).uncheck();
  await card.getByRole("button", { name: "Delete Permanently" }).click();
}

test.describe("deleting duplicates through every service", () => {
  test.beforeEach(async ({ request }) => {
    await markUnconfigured(request);
    await markJellyfinConfigured(request);
    await markServicesConfigured(request);
    await clearDuplicates(request);
  });

  test.afterEach(async ({ request }) => {
    await markServicesUnconfigured(request);
  });

  test("a movie goes through Radarr and qBittorrent, and its own files go with it", async ({
    page,
    request,
  }) => {
    const title = uniqueTitle("Fake Pipeline");
    await setJellyfinMode(request, "default", title);
    const media = seedJellyfinMedia(title);
    await resetServices(request, title);
    await runScan(request, { jellyfin: [JELLYFIN_LIBRARY] });

    await deleteFromScanPage(page, request, title);

    await expect(page.getByText("Deletion Complete", { exact: true })).toBeVisible();
    expect(fs.existsSync(media.drop)).toBe(false);
    expect(media.dropSidecars.some((file) => fs.existsSync(file))).toBe(false);
    expect(fs.existsSync(media.keep)).toBe(true);
    expect(fs.existsSync(media.keepSidecar)).toBe(true);

    const radarr = await serviceState(request, RADARR_URL);
    expect(radarr.deletedMovieFiles).toEqual([11]);
    const qbit = await serviceState(request, QBIT_URL);
    expect(qbit.deleted).toEqual([{ hash: "aaaa1111", deleteFiles: true }]);
    expect((await getPendingSets(request)).some((s: { title: string }) => s.title === title)).toBe(
      false
    );
  });

  test("an episode from a season pack leaves the pack and its other episodes alone", async ({
    page,
    request,
  }) => {
    const name = uniqueTitle("Fake Episode");
    await setJellyfinMode(request, "episodes", name);
    const media = seedEpisodeMedia();
    await resetServices(request);
    await runScan(request, { jellyfin: ["Fake Shows"] });

    await deleteFromScanPage(page, request, `Fake Show - S01E02 - ${name}`);

    await expect(page.getByText("Deletion Complete", { exact: true })).toBeVisible();
    expect(fs.existsSync(media.drop)).toBe(false);
    expect(fs.existsSync(media.keep)).toBe(true);
    expect(fs.existsSync(media.sibling)).toBe(true);
    expect(fs.existsSync(media.subtitles)).toBe(true);

    const sonarr = await serviceState(request, SONARR_URL);
    expect(sonarr.deletedEpisodeFiles).toEqual([21]);
    const qbit = await serviceState(request, QBIT_URL);
    expect(qbit.deleted).toEqual([]);
  });

  test("the only title in a library folder takes its own folder, not the library's", async ({
    page,
    request,
  }) => {
    await markServicesUnconfigured(request);
    const title = uniqueTitle("Fake Split");
    await setJellyfinMode(request, "split", title);
    const media = seedJellyfinMedia(title, "split");
    await runScan(request, { jellyfin: [JELLYFIN_LIBRARY] });

    await deleteFromScanPage(page, request, title);

    await expect(page.getByText("Deletion Complete", { exact: true })).toBeVisible();
    const titleFolder = path.dirname(media.drop);
    expect(fs.existsSync(titleFolder)).toBe(false);
    expect(fs.existsSync(path.dirname(titleFolder))).toBe(true);
    expect(fs.existsSync(media.keep)).toBe(true);
  });

  test("a kept copy directly in Radarr's root folder stays put, and the result says why", async ({
    page,
    request,
  }) => {
    const title = uniqueTitle("Fake Loose");
    await setJellyfinMode(request, "loose", title);
    const media = seedJellyfinMedia(title, "loose");
    await resetServices(request, title);
    await runScan(request, { jellyfin: [JELLYFIN_LIBRARY] });

    await deleteFromScanPage(page, request, title);

    await expect(page.getByText("Deletion Complete", { exact: true })).toBeVisible();
    await expect(page.getByText(/sits directly in the root folder/).first()).toBeVisible();
    expect(fs.existsSync(media.drop)).toBe(false);
    expect(fs.existsSync(media.keep)).toBe(true);
    const radarr = await serviceState(request, RADARR_URL);
    expect(radarr.deletedMovieFiles).toEqual([11]);
    // Neither pointed at the root folder nor asked to scan it
    expect(radarr.commands).toEqual([]);
  });

  test("a file nothing could remove is reported, and its set stays to retry", async ({
    page,
    request,
  }) => {
    // With no service to vouch for it, a missing file was counted as deleted
    await markServicesUnconfigured(request);
    const title = uniqueTitle("Fake Missing");
    await setJellyfinMode(request, "default", title);
    const media = seedJellyfinMedia(title);
    await runScan(request, { jellyfin: [JELLYFIN_LIBRARY] });
    fs.rmSync(media.drop);

    await deleteFromScanPage(page, request, title);

    await expect(page.getByText("Deletion Incomplete", { exact: true })).toBeVisible();
    await expect(page.getByText(/File not found for deletion/).first()).toBeVisible();
    expect((await getPendingSets(request)).some((s: { title: string }) => s.title === title)).toBe(
      true
    );

    // With the file back, the same set deletes cleanly
    seedJellyfinMedia(title);
    await deleteFromScanPage(page, request, title);

    await expect(page.getByText("Deletion Complete", { exact: true })).toBeVisible();
    expect(fs.existsSync(media.drop)).toBe(false);
  });
});
