import fs from "fs";

import { expect, test } from "@playwright/test";

import { JELLYFIN_API_KEY, JELLYFIN_LIBRARY, JELLYFIN_URL } from "../playwright.config";
import {
  getPendingSets,
  gotoApp,
  markConfigured,
  markJellyfinConfigured,
  markJellyfinUnconfigured,
  markUnconfigured,
  runScan,
  seedJellyfinMedia,
  setJellyfinMode,
} from "./helpers";

test.describe("jellyfin", () => {
  test.beforeEach(async ({ request }) => {
    await setJellyfinMode(request, "default");
    seedJellyfinMedia();
  });

  test("an instance with only Jellyfin reaches the dashboard", async ({ page, request }) => {
    // The point of issue #470: Plex must not be a requirement
    await markUnconfigured(request);
    await markJellyfinConfigured(request);

    await gotoApp(page, "/");

    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("heading", { name: /dashboard/i })).toBeVisible();
  });

  test("an instance with no media server is sent to setup", async ({ page, request }) => {
    await markUnconfigured(request);
    await markJellyfinUnconfigured(request);

    await gotoApp(page, "/");

    await expect(page).toHaveURL(/\/setup$/);
  });

  test("the connection test accepts an admin key and rejects anything else", async ({
    request,
  }) => {
    const ok = await request.post("/api/setup/test/jellyfin", {
      data: { url: JELLYFIN_URL, api_key: JELLYFIN_API_KEY },
    });
    expect(ok.ok()).toBeTruthy();
    const okBody = await ok.json();
    expect(okBody.success).toBe(true);
    expect(okBody.server_name).toBe("Fake Jellyfin");
    expect(okBody.version).toBe("12.4.0");

    const bad = await request.post("/api/setup/test/jellyfin", {
      data: { url: JELLYFIN_URL, api_key: "not-an-admin-key" },
    });
    const badBody = await bad.json();
    expect(badBody.success).toBe(false);
    expect(badBody.error).toBeTruthy();

    const unreachable = await request.post("/api/setup/test/jellyfin", {
      data: { url: "http://127.0.0.1:9", api_key: JELLYFIN_API_KEY },
    });
    expect((await unreachable.json()).success).toBe(false);
  });

  test("only movie and show libraries are offered", async ({ request }) => {
    await markJellyfinConfigured(request);

    const res = await request.get("/api/setup/libraries");
    expect(res.ok()).toBeTruthy();
    const libraries = await res.json();

    const jellyfin = libraries.filter((lib: { server: string }) => lib.server === "jellyfin");
    expect(jellyfin.map((lib: { title: string }) => lib.title)).toEqual([JELLYFIN_LIBRARY]);
    expect(jellyfin[0].type).toBe("movie");
    // The fake also serves a music library, which Deduparr does not handle
    expect(jellyfin.map((lib: { title: string }) => lib.title)).not.toContain("Fake Music");
  });

  test("a scan finds the duplicate and keeps the better file", async ({ page, request }) => {
    await markUnconfigured(request);
    await markJellyfinConfigured(request);

    const result = await runScan(request, [JELLYFIN_LIBRARY]);
    expect(result.sets_created).toBeGreaterThanOrEqual(1);

    const pending = await getPendingSets(request);
    const set = pending.find((s: { title: string }) => s.title === "Fake Duplicate (2024)");
    expect(set).toBeTruthy();

    // Stored against Jellyfin, not Plex
    const detail = await (await request.get("/api/scan/duplicates")).json();
    const stored = detail.find((s: { title: string }) => s.title === "Fake Duplicate (2024)");
    expect(stored.media_server).toBe("jellyfin");

    const kept = stored.files.filter((f: { keep: boolean }) => f.keep);
    expect(kept).toHaveLength(1);
    expect(kept[0].file_path).toContain("1080p");

    // And it shows up in the UI
    await gotoApp(page, "/scan");
    await expect(page.getByText("Fake Duplicate (2024)")).toBeVisible();
  });

  test("a library with nothing duplicated creates no sets", async ({ request }) => {
    await markJellyfinConfigured(request);
    await setJellyfinMode(request, "no-duplicates");

    const result = await runScan(request, [JELLYFIN_LIBRARY]);

    expect(result.sets_created).toBe(0);
    const titles = (await getPendingSets(request)).map((s: { title: string }) => s.title);
    expect(titles).not.toContain("Fake Duplicate (2024)");
  });

  test("a set is dropped once the server stops reporting it", async ({ request }) => {
    await markJellyfinConfigured(request);

    await runScan(request, [JELLYFIN_LIBRARY]);
    expect(
      (await getPendingSets(request)).some(
        (s: { title: string }) => s.title === "Fake Duplicate (2024)"
      )
    ).toBe(true);

    await setJellyfinMode(request, "empty");
    await runScan(request, [JELLYFIN_LIBRARY]);

    expect(
      (await getPendingSets(request)).some(
        (s: { title: string }) => s.title === "Fake Duplicate (2024)"
      )
    ).toBe(false);
  });

  test("a deletion removes the file the scan chose to drop", async ({ request }) => {
    await markJellyfinConfigured(request);
    const { keep, drop } = seedJellyfinMedia();

    await runScan(request, [JELLYFIN_LIBRARY]);
    const sets = await (await request.get("/api/scan/duplicates")).json();
    const set = sets.find((s: { title: string }) => s.title === "Fake Duplicate (2024)");

    // Dry run leaves both files alone
    const dry = await request.post(`/api/scan/duplicates/${set.id}/delete`, {
      data: { dry_run: true },
    });
    expect((await dry.json()).dry_run).toBe(true);
    expect(fs.existsSync(drop)).toBe(true);

    const real = await request.post(`/api/scan/duplicates/${set.id}/delete`, {
      data: { dry_run: false },
    });
    expect(real.ok()).toBeTruthy();

    expect(fs.existsSync(drop)).toBe(false);
    expect(fs.existsSync(keep)).toBe(true);
  });

  test("both servers can be configured at once", async ({ request }) => {
    await markConfigured(request);
    await markJellyfinConfigured(request);

    const libraries = await (await request.get("/api/setup/libraries")).json();
    const servers = new Set(libraries.map((lib: { server: string }) => lib.server));

    // Plex uses a fake token here so it cannot answer, but Jellyfin must still
    // be listed: one server failing cannot hide the other
    expect(servers.has("jellyfin")).toBe(true);
  });
});
