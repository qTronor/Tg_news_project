import { expect, test } from "@playwright/test";

const sourceChannel = process.env.E2E_SOURCE_CHANNEL;
const sourceStartDate = process.env.E2E_SOURCE_START_DATE ?? "2026-04-14";

test.describe("User Telegram sources", () => {
  test.skip(!sourceChannel, "Set E2E_SOURCE_CHANNEL to run the live sources happy path.");

  test("login -> add channel -> see status -> open first data in feed", async ({ page }) => {
    await page.goto("/login");
    await page.fill('input[type="text"]', "admin@tgnews.local");
    await page.fill('input[type="password"]', "Admin123!");
    await page.getByRole("button", { name: /РІРѕР№С‚Рё|sign in/i }).last().click();
    await expect(page).toHaveURL("/", { timeout: 10_000 });

    await page.goto("/sources");
    await page.getByPlaceholder("@channel_name or https://t.me/channel_name").fill(sourceChannel!);
    await page.locator('input[type="date"]').fill(sourceStartDate);
    await page.getByRole("button", { name: /submit/i }).click();

    await expect(
      page.getByText(/Validating|Backfilling|Ready|Live enabled/i).first(),
    ).toBeVisible({ timeout: 30_000 });

    await expect(page.getByText(/Progress|Queue|First data/i).first()).toBeVisible({
      timeout: 60_000,
    });

    const feedLink = page.getByRole("link", { name: /open in feed/i }).first();
    await expect(feedLink).toBeVisible({ timeout: 180_000 });
    await feedLink.click();
    await expect(page).toHaveURL(/\/feed\?channel=/, { timeout: 10_000 });
  });
});
