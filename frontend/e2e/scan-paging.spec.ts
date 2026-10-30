import { expect, test } from "@playwright/test";

import { BACKEND_URL } from "../playwright.config";
import {
  clearDuplicates,
  gotoApp,
  markConfigured,
  seedDuplicateSets,
  uniqueTitle,
} from "./helpers";

// How many sets the Scan page loads at a time
const SETS_PER_PAGE = 100;

test.describe("paging through duplicate sets", () => {
  test.beforeEach(async ({ request }) => {
    await markConfigured(request);
  });

  // Left pending, the sets would slow every later Delete All
  test.afterEach(async ({ request }) => {
    await clearDuplicates(request);
  });

  test("every set can be reached, and Delete All counts them all", async ({ page, request }) => {
    // Seeding and then deleting more than a page of sets takes a while
    test.slow();
    const run = uniqueTitle("Paging");
    await seedDuplicateSets(
      request,
      Array.from({ length: SETS_PER_PAGE + 1 }, (_, n) => `${run} ${n}`)
    );
    const res = await request.get(`${BACKEND_URL}/api/scan/status`);
    expect(res.ok()).toBeTruthy();
    const status = await res.json();
    const total = status.total_duplicate_sets;

    await gotoApp(page, "/scan");
    const sets = page.locator('[data-testid^="duplicate-set-"]');
    await expect(sets).toHaveCount(SETS_PER_PAGE);
    await expect(page.getByTestId("sets-shown")).toHaveText(
      `Showing ${SETS_PER_PAGE} of ${total} duplicate sets`
    );
    await expect(page.getByTestId("duplicate-items")).toHaveText(String(total));

    // With one page loaded, Delete All still counts every pending set
    const deleteAll = page.getByTestId("delete-all");
    await expect(deleteAll).toHaveText(`Delete All (${status.pending_sets})`);
    await deleteAll.click();
    await expect(page.getByTestId("delete-confirm-all")).toContainText(
      `delete ${status.pending_files_to_delete} files across ${status.pending_sets} sets`
    );

    // A set found now moves every other one a place down, across the pages
    await seedDuplicateSets(request, [`${run} late`]);
    for (let shown = SETS_PER_PAGE; shown <= total; shown += SETS_PER_PAGE) {
      await page.getByTestId("load-more").click();
      await expect(sets).toHaveCount(Math.min(shown + SETS_PER_PAGE, total + 1));
    }

    await expect(page.getByTestId("load-more")).toHaveCount(0);
    const ids = await sets.evaluateAll((cards) => cards.map((card) => card.dataset.testid));
    expect(new Set(ids).size).toBe(total + 1);
  });
});
