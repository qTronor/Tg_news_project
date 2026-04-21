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
    if (url.includes("/analytics/")) {
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
  await page.getByRole("button", { name: /sign in|войти/i }).last().click();
  await page.waitForURL("**/", { timeout: 15000 }).catch(() => {});

  await page.goto("http://localhost:3000/topics", {
    waitUntil: "networkidle",
    timeout: 30000,
  });

  const modeButton = page.getByRole("button", { name: /demo|live api|демо/i }).first();
  const modeText = await modeButton.innerText().catch(() => "");
  if (/demo|демо/i.test(modeText) && !/live/i.test(modeText)) {
    await modeButton.click();
  }

  await page.waitForResponse(
    (res) => res.url().includes("/analytics/overview/clusters") && res.status() === 200,
    { timeout: 15000 },
  );
  await page.waitForTimeout(1000);

  const firstTopic = page.locator('a[href^="/topics/gpt_topics_"]').first();
  const href = await firstTopic.getAttribute("href");
  await firstTopic.click();

  await page.waitForResponse(
    (res) => res.url().includes("/analytics/clusters/") && res.status() === 200,
    { timeout: 15000 },
  );
  await page.waitForLoadState("networkidle", { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(1500);

  const bodyText = await page.locator("body").innerText();
  console.log(`TOPIC_HREF=${href}`);
  console.log(`HAS_FAILED_FETCH=${/failed to fetch/i.test(bodyText)}`);
  console.log(`HAS_TOPIC_ANALYTICS=${/Topic analytics/i.test(bodyText)}`);
  console.log("TEXT_START");
  console.log(bodyText.slice(0, 2000));
  console.log("TEXT_END");
  console.log("RESPONSES");
  console.log(responses.join("\n"));

  await browser.close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
