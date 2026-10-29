import { expect, test } from "@playwright/test";

import { JELLYFIN_LIBRARY } from "../playwright.config";
import {
  deleteConfig,
  getConfig,
  getPendingSets,
  gotoApp,
  markJellyfinConfigured,
  markUnconfigured,
  runScan,
  seedJellyfinMedia,
  setConfig,
  setJellyfinMode,
  uniqueTitle,
} from "./helpers";

test.describe("per-server library selection", () => {
  test.beforeEach(async ({ request }) => {
    await markUnconfigured(request);
    await markJellyfinConfigured(request);
  });

  test("a scan with no names uses the selection stored for each server", async ({ request }) => {
    const title = uniqueTitle("Fake Selected");
    await setJellyfinMode(request, "default", title);
    seedJellyfinMedia(title);
    await setConfig(request, "jellyfin_libraries", JELLYFIN_LIBRARY);

    // No libraries given, so the stored selection decides
    const result = await runScan(request);

    expect(result.success).toBe(true);
    expect((await getPendingSets(request)).some((s: { title: string }) => s.title === title)).toBe(
      true
    );
  });

  test("a server with nothing selected is skipped", async ({ request }) => {
    const title = uniqueTitle("Fake Unselected");
    await setJellyfinMode(request, "default", title);
    seedJellyfinMedia(title);
    await deleteConfig(request, "jellyfin_libraries");

    const result = await runScan(request);

    expect(result.sets_created).toBe(0);
    expect((await getPendingSets(request)).some((s: { title: string }) => s.title === title)).toBe(
      false
    );
  });

  test("a library selected for the other server is not scanned here", async ({ request }) => {
    const title = uniqueTitle("Fake Wrong Server");
    await setJellyfinMode(request, "default", title);
    seedJellyfinMedia(title);

    // The name is right, but it is recorded against Plex, not Jellyfin
    await deleteConfig(request, "jellyfin_libraries");
    await setConfig(request, "plex_libraries", JELLYFIN_LIBRARY);

    const result = await runScan(request);

    expect(result.sets_created).toBe(0);
    await deleteConfig(request, "plex_libraries");
  });

  test("the Scan page starts from the stored selection and keeps what it scans", async ({
    page,
    request,
  }) => {
    await gotoApp(page, "/scan");
    const movies = page.getByRole("checkbox", { name: /Fake Movies/ });
    const shows = page.getByRole("checkbox", { name: /Fake Shows/ });

    // Stored for Jellyfin by markJellyfinConfigured, and labelled with it
    await expect(movies).toBeChecked();
    await expect(shows).not.toBeChecked();
    await expect(page.getByText(/on Jellyfin/).first()).toBeVisible();

    await shows.check();
    await page.getByRole("button", { name: "Start Scan" }).click();

    await expect(page.getByText("Scan Complete", { exact: true })).toBeVisible();
    expect((await getConfig(request)).jellyfin_libraries).toBe(`${JELLYFIN_LIBRARY},Fake Shows`);
  });
});
