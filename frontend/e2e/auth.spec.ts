import { test, expect } from "@playwright/test";

test.describe("Authentication", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/login");
  });

  test("login page renders correctly", async ({ page }) => {
    await expect(page.locator("h1")).toContainText("TG News Analytics");
    await expect(page.getByRole("button", { name: /войти|sign in/i })).toBeVisible();
  });

  test("shows error on invalid credentials", async ({ page }) => {
    await page.fill('input[type="text"]', "wrong@user.com");
    await page.fill('input[type="password"]', "wrongpassword");
    await page.getByRole("button", { name: /войти|sign in/i }).last().click();

    await expect(page.locator(".text-destructive")).toBeVisible({ timeout: 10_000 });
  });

  test("can switch between login and register modes", async ({ page }) => {
    const registerTab = page.getByRole("button", { name: /регистрация|sign up/i });
    await registerTab.click();

    await expect(page.getByPlaceholder("email@example.com")).toBeVisible();
    await expect(page.getByPlaceholder("username")).toBeVisible();
  });

  test("forgot password link navigates to forgot-password page", async ({ page }) => {
    await page.getByText(/забыли пароль|forgot password/i).click();
    await expect(page).toHaveURL(/forgot-password/);
  });

  test("successful login redirects to dashboard", async ({ page }) => {
    await page.fill('input[type="text"]', "admin@tgnews.local");
    await page.fill('input[type="password"]', "Admin123!");
    await page.getByRole("button", { name: /войти|sign in/i }).last().click();

    await expect(page).toHaveURL("/", { timeout: 10_000 });
    await expect(page.locator("h1")).toContainText(/dashboard|дашборд/i);
  });
});

test.describe("Navigation", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/login");
    await page.fill('input[type="text"]', "admin@tgnews.local");
    await page.fill('input[type="password"]', "Admin123!");
    await page.getByRole("button", { name: /войти|sign in/i }).last().click();
    await expect(page).toHaveURL("/", { timeout: 10_000 });
  });

  test("sidebar navigation works", async ({ page }) => {
    await page.getByRole("link", { name: /лента|feed/i }).click();
    await expect(page).toHaveURL("/feed");

    await page.getByRole("link", { name: /темы|topics/i }).click();
    await expect(page).toHaveURL("/topics");

    await page.getByRole("link", { name: /сущности|entities/i }).click();
    await expect(page).toHaveURL("/entities");
  });
});
