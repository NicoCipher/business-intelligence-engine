import { expect, test } from "@playwright/test";

test("overview prioritizes operating state and explicit attention", async ({ page }) => {
  await page.goto("/overview");
  await expect(page.getByRole("heading", { name: "BIA operations" })).toBeVisible();
  await expect(page.getByText("Operating normally")).toBeVisible();
  await expect(page.getByText("No opportunities are persisted.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Open report" })).toBeVisible();
});

test("supported evidence and empty operational states are reachable", async ({ page }) => {
  await page.goto("/signals");
  await expect(page.getByRole("heading", { name: "Signals" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Evidence from an external source" })).toHaveAttribute("rel", "noopener noreferrer");

  await page.goto("/opportunities");
  await expect(page.getByText("No Opportunities match this view.")).toBeVisible();

  await page.goto("/reports/does-not-exist");
  await expect(page.getByText("That operational record was not found.")).toBeVisible();
});
