import fs from "fs";
import { E2E_TMP } from "../playwright.config";

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
export default function globalSetup() {
  fs.mkdirSync(`${E2E_TMP}/media`, { recursive: true });
}
