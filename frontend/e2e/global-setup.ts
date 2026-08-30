import fs from "fs";
import { E2E_TMP } from "../playwright.config";

/**
 * Start every run from a clean backend database so specs see deterministic
 * state (an unconfigured instance) regardless of what a previous run left.
 */
export default function globalSetup() {
  fs.rmSync(E2E_TMP, { recursive: true, force: true });
  fs.mkdirSync(E2E_TMP, { recursive: true });
  fs.mkdirSync(`${E2E_TMP}/media`, { recursive: true });
}
