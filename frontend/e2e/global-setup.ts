import fs from "fs";

import { E2E_TMP, JELLYFIN_API_KEY, JELLYFIN_URL } from "../playwright.config";

/**
 * Ensure the scratch directory the test backend writes into exists.
 *
 * This deliberately does NOT clear the directory. Playwright starts `webServer`
 * *before* globalSetup runs, so deleting it here pulls the SQLite database out
 * from under a backend that has already opened it, and every subsequent query
 * fails with "disk I/O error". Some filesystems tolerate the unlink and some
 * do not, which makes it an intermittent failure that reproduces on CI but not
 * necessarily locally.
 *
 * Specs do not depend on a pristine database: each one establishes the state it
 * needs in `beforeEach` via markConfigured / markUnconfigured / setConfig.
 */
export default async function globalSetup() {
  fs.mkdirSync(`${E2E_TMP}/media`, { recursive: true });

  // webServer reuses whatever already listens on the port, so a Jellyfin left
  // over from a dev session would be used instead of the suite's own and every
  // request would come back 401. Fail here rather than halfway through a spec.
  const response = await fetch(`${JELLYFIN_URL}/system/info`, {
    headers: { Authorization: `MediaBrowser Token="${JELLYFIN_API_KEY}"` },
  });
  if (!response.ok) {
    throw new Error(
      `The Jellyfin on ${JELLYFIN_URL} does not accept this suite's API key ` +
        `(HTTP ${response.status}). Something else is listening on that port.`
    );
  }
}
