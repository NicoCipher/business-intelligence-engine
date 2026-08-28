import { expect, test } from "@playwright/test";

test("overview prioritizes operating state and explicit attention", async ({ page }) => {
  await page.goto("/overview");
  await expect(page.getByRole("heading", { name: "BIA operations" })).toBeVisible();
  await expect(page.getByText("API + evidence fresh")).toBeVisible();
  await expect(page.getByText("No opportunities are persisted.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Review latest report" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "What changed since last looked" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open report" })).toBeVisible();
});

test("unseen changes are shown, linked to their referenced problem, and acknowledgement clears them", async ({ page }) => {
  await page.goto("/overview");

  await expect(page.getByText("1 unseen")).toBeVisible();
  const changeLink = page.getByRole("link", { name: "Solo therapists lack scheduling tools" });
  await expect(changeLink).toBeVisible();
  await expect(changeLink).toHaveAttribute("href", "/problems/p1");
  await expect(page.getByText("problem created")).toBeVisible();

  await page.getByRole("button", { name: /Mark reviewed through/ }).click();

  await expect(page.getByText("Up to date")).toBeVisible();
  await expect(page.getByText("No Problem or Opportunity changes have been recorded since your last review.")).toBeVisible();
});

test("supported evidence and empty operational states are reachable", async ({ page }) => {
  await page.goto("/signals");
  await expect(page.getByRole("heading", { name: "Signals" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Signals" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("region", { name: "Observed signal evidence table" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Evidence from an external source" })).toHaveAttribute("rel", "noopener noreferrer");

  await page.goto("/opportunities");
  await expect(page.getByText("No Opportunities match this view.")).toBeVisible();

  await page.goto("/reports/does-not-exist");
  await expect(page.getByText("That operational record was not found.")).toBeVisible();
});

test("mobile navigation and evidence tables avoid page-level overflow", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/signals");

  await expect(page.getByRole("link", { name: "System health" })).toBeVisible();
  await expect.poll(() => page.locator("html").evaluate((element) => element.scrollWidth <= window.innerWidth)).toBe(true);
  await expect.poll(() => page.getByRole("region", { name: "Observed signal evidence table" }).evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);
});
