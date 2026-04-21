const { chromium } = require("../frontend/node_modules/@playwright/test");

async function main() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const responses = [];
  page.on("response", (res) => {
    const url = res.url();
    if (url.includes("/analytics/") || url.includes("/api/auth/")) {
      responses.push(`${res.status()} ${url}`);
    }
  });
  page.on("pageerror", (err) => {
    console.log(`pageerror ${err.message}`);
  });

  await page.goto("http://localhost:3000/login", {
    waitUntil: "networkidle",
    timeout: 30000,
  });
  await page.locator('input[type="text"]').first().fill("admin@tgnews.local");
  await page.locator('input[type="password"]').fill("Admin123!");
  await page.getByRole("button", { name: /войти|sign in/i }).last().click();
  await page.waitForURL("**/", { timeout: 15000 }).catch(() => {});

  await page.goto("http://localhost:3000/feed", {
    waitUntil: "networkidle",
    timeout: 30000,
  });
  await page.getByRole("button", { name: /demo|демо/i }).first().click();
  await page
    .waitForResponse(
      (res) => res.url().includes("/analytics/messages") && res.status() === 200,
      { timeout: 10000 },
    )
    .catch(() => {});
  await page.waitForTimeout(2500);

  const bodyText = await page.locator("body").innerText();
  console.log("TEXT_START");
  console.log(bodyText.slice(0, 4000));
  console.log("TEXT_END");
  console.log(`HAS_NEGATIVE=${/Negative|Негатив/.test(bodyText)}`);
  console.log(`HAS_POSITIVE=${/Positive|Позитив/.test(bodyText)}`);
  console.log(`HAS_LIVE_API=${/Live API/.test(bodyText)}`);
  console.log("RESPONSES");
  console.log(responses.join("\n"));
  await browser.close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
