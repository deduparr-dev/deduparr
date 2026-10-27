import fs from "fs";

import { expect, test } from "@playwright/test";

import { getPendingSets, gotoApp, markConfigured, seedDuplicateSet } from "./helpers";

test.describe("delete all duplicates", () => {
  test.beforeEach(async ({ request }) => {
    await markConfigured(request);
  });

  test("the button is absent while nothing is pending", async ({ page, request }) => {
    test.skip((await getPendingSets(request)).length > 0, "a pending set already exists");

    await gotoApp(page, "/scan");

    await expect(page.getByTestId("delete-all")).toHaveCount(0);
  });

  test("a dry run reports every pending set without deleting anything", async ({
    page,
    request,
  }) => {
    const { keep, drop } = await seedDuplicateSet(request, "Delete All Movie (2024)");
    const pendingBefore = await getPendingSets(request);
    expect(pendingBefore.length).toBeGreaterThan(0);

    await gotoApp(page, "/scan");

    const deleteAll = page.getByTestId("delete-all");
    // Exactly one bulk control, whatever the number of pending sets
    await expect(deleteAll).toHaveCount(1);
    await expect(deleteAll).toHaveText(new RegExp(`Delete All \\(${pendingBefore.length}\\)`));
    await deleteAll.click();

    // Dry run is pre-selected, so the destructive action is never the default
    const dryRun = page.locator("#dry-run-all");
    await expect(dryRun).toBeChecked();
    const confirm = page.getByRole("button", { name: "Test Deletion (Dry Run)" });
    await expect(confirm).toBeVisible();

    await confirm.click();

    await expect(page.getByText("Dry Run Complete")).toBeVisible();
    expect(fs.existsSync(keep)).toBe(true);
    expect(fs.existsSync(drop)).toBe(true);
    expect(await getPendingSets(request)).toHaveLength(pendingBefore.length);
  });

  test("cancelling closes the confirmation", async ({ page, request }) => {
    await seedDuplicateSet(request, "Cancel Movie (2024)");

    await gotoApp(page, "/scan");
    await expect(page.getByTestId("delete-all")).toHaveCount(1);
    await page.getByTestId("delete-all").click();

    const panel = page.getByTestId("delete-confirm-all");
    await expect(panel).toBeVisible();

    await panel.getByRole("button", { name: "Cancel" }).click();

    await expect(panel).toHaveCount(0);
  });
});
