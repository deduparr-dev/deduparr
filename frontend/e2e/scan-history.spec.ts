import { expect, test } from "@playwright/test";

import {
  clearDuplicates,
  getPendingSets,
  gotoApp,
  markConfigured,
  seedDuplicateSets,
  uniqueTitle,
} from "./helpers";

test("a deleted set leaves the Scan page and stays in the Dashboard's activity", async ({
  page,
  request,
}) => {
  await markConfigured(request);
  const [{ keep }] = await seedDuplicateSets(request, [uniqueTitle("History")]);
  const pending = await getPendingSets(request);
  const set = pending.find((s) => s.files.some((file) => file.file_path === keep));
  expect(set).toBeTruthy();
  const card = page.getByTestId(`duplicate-set-${set!.id}`);

  await gotoApp(page, "/scan");
  await expect(card).toHaveCount(1);

  await clearDuplicates(request);

  await gotoApp(page, "/scan");
  await expect(card).toHaveCount(0);
  await gotoApp(page, "/");
  await expect(page.getByTestId(`activity-${set!.id}`)).toHaveCount(1);
});
