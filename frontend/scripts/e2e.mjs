// Browser e2e (mock mode): full Dana → Mike → Dana demo + layout/a11y audit. Usage: npm run dev, then
//   node scripts/e2e.mjs 1024x768 /tmp/shots   (uses installed Google Chrome via playwright-core; no browser download)
import { chromium } from "playwright-core";
const [w, h] = process.argv[2].split("x").map(Number);
const out = process.argv[3];
const browser = await chromium.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true });
const page = await browser.newPage({ viewport: { width: w, height: h }, hasTouch: true });
const errs = [];
page.on("console", (m) => (m.type() === "error" || m.type() === "warning") && errs.push(`${m.type()}: ${m.text()}`));
page.on("pageerror", (e) => errs.push(`pageerror: ${e.message}`));
let n = 0;
const shot = async (name) => { await page.waitForTimeout(450); return page.screenshot({ path: `${out}/${w}x${h}-${String(++n).padStart(2, "0")}-${name}.png`, fullPage: false }); };
const audit = async (label) => {
  const r = await page.evaluate(() => {
    const issues = [];
    if (document.documentElement.scrollWidth > window.innerWidth + 1) issues.push(`h-overflow ${document.documentElement.scrollWidth}>${window.innerWidth}`);
    for (const el of document.querySelectorAll("button, textarea, input, summary")) {
      const b = el.getBoundingClientRect();
      if (b.width === 0) continue;
      if (b.height < 44 || b.width < 44) issues.push(`small target ${Math.round(b.width)}x${Math.round(b.height)} "${(el.getAttribute("aria-label") || el.textContent || "").trim().slice(0, 40)}"`);
    }
    for (const el of document.querySelectorAll("body *")) {
      if (!el.childNodes.length || ![...el.childNodes].some((c) => c.nodeType === 3 && c.textContent.trim())) continue;
      const s = getComputedStyle(el);
      if (parseFloat(s.fontSize) < 14 && s.position !== "absolute") issues.push(`tiny text ${s.fontSize} "${el.textContent.trim().slice(0, 30)}"`);
    }
    return issues;
  });
  if (r.length) console.log(`[${w}x${h} ${label}]`, [...new Set(r)].join(" | "));
};
const cardsReady = () => page.waitForFunction(() => !document.body.innerText.includes("Refining") && document.querySelectorAll('[aria-label^="Say:"]').length === 4, null, { timeout: 5000 });

await page.goto(process.env.E2E_URL ?? "http://127.0.0.1:5173/");
await page.getByRole("radio", { name: /Dana/ }).waitFor();
await audit("picker"); await shot("picker");
await page.getByRole("radio", { name: /Dana/ }).click();
await page.getByText("“Hi Maya! Here for your refill?”").click();
await cardsReady(); await audit("dana-cards"); await shot("dana-cards");
await page.getByRole("button", { name: /^Say: Did the blister/ }).click();
await page.waitForTimeout(400); await shot("dana-speaking");
await page.waitForFunction(() => !document.body.innerText.includes("Speaking…"), null, { timeout: 15000 });

await page.getByRole("radio", { name: /Mike/ }).click();
await page.getByText("“Hey Maya! How've you been?”").click();
await cardsReady(); await shot("mike-cards");
await page.getByRole("button", { name: /More options for: Honestly/ }).click();
await audit("reject-sheet"); await shot("reject-sheet");
await page.getByRole("button", { name: /Too personal/ }).click();
await page.getByText(/Learned: keep/).waitFor({ timeout: 3000 }); await shot("learned-toast");
await page.getByText("“Anything new?”").click();
await cardsReady(); await audit("mike-filtered"); await shot("mike-filtered");
const cards = await page.$$eval('[aria-label^="Say:"]', (e) => e.map((x) => x.getAttribute("aria-label")));
console.log(`[${w}x${h}] Mike after rule:`, cards.join(" / "));
await page.getByRole("button", { name: /hidden by your boundaries/ }).click();
await shot("hidden-list"); await page.keyboard.press("Escape");

await page.getByRole("radio", { name: /Dana/ }).click();
await page.getByText("“Any side effects with the new generic?”").click();
await cardsReady(); await shot("dana-meds");
console.log(`[${w}x${h}] Dana after rule:`, (await page.$$eval('[aria-label^="Say:"]', (e) => e.map((x) => x.getAttribute("aria-label")))).join(" / "));

await page.getByRole("button", { name: /Type my own/ }).click(); await shot("type-own"); await page.keyboard.press("Escape");
await page.getByRole("button", { name: /Memory & privacy/ }).click(); await page.waitForTimeout(300); await audit("memory"); await shot("memory");
await page.getByRole("button", { name: /Scoreboard/ }).click(); await page.waitForTimeout(300); await audit("scoreboard"); await shot("scoreboard");
console.log(`[${w}x${h}] console:`, errs.length ? errs.join("\n") : "clean");
await browser.close();
