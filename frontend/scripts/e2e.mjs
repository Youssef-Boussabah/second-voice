// Browser e2e (mock mode) that walks docs/07-demo-script.md beat by beat.
// Asserts each beat is ≤ 2 taps and that the screen shows what the script says, then resets
// and checks a second rehearsal starts clean. Also audits overflow / tiny targets / tiny text.
// Usage: VITE_USE_MOCKS=true dev server, then `node scripts/e2e.mjs 1024x768 <shots dir>` (installed Chrome; no download).
// CHROME_PATH overrides the browser; E2E_URL overrides the app URL.
import { chromium } from "playwright-core";
import { existsSync, mkdirSync } from "node:fs";
const [w, h] = process.argv[2].split("x").map(Number);
const out = process.argv[3] ?? "node_modules/.e2e";
mkdirSync(out, { recursive: true });
const URL = process.env.E2E_URL ?? "http://127.0.0.1:5173/";
const CHROME = process.env.CHROME_PATH ?? [
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/usr/bin/google-chrome",
].find((p) => existsSync(p));
const browser = await chromium.launch({ executablePath: CHROME, headless: true });
const page = await browser.newPage({ viewport: { width: w, height: h }, hasTouch: true });
const errs = [];
page.on("console", (m) => (m.type() === "error" || m.type() === "warning") && errs.push(`${m.type()}: ${m.text()}`));
page.on("pageerror", (e) => errs.push(`pageerror: ${e.message}`));
const tag = `[${w}x${h}]`;
let failed = false;
const fail = (m) => { console.log(`${tag} FAIL ${m}`); failed = true; };

let n = 0, taps = 0;
const shot = async (name) => { await page.waitForTimeout(450); await page.screenshot({ path: `${out}/${w}x${h}-${String(++n).padStart(2, "0")}-${name.replace(/[^\w.-]+/g, "_")}.png` }); };
const tap = async (loc) => { taps++; await loc.click(); };
const beat = async (name, fn, max = 2) => {
  taps = 0;
  try { await fn(); } catch (e) { fail(`${name}: ${e.message.split("\n")[0]}`); }
  if (taps > max) fail(`${name}: ${taps} taps (max ${max})`);
  console.log(`${tag} ${taps <= max ? "ok " : "!! "} ${name} (${taps} taps)`);
  await audit(name); await shot(name);
};
const audit = async (label) => {
  const r = await page.evaluate(() => {
    const issues = [];
    if (document.documentElement.scrollWidth > window.innerWidth + 1) issues.push(`h-overflow ${document.documentElement.scrollWidth}>${window.innerWidth}`);
    for (const el of document.querySelectorAll("button, textarea, input")) {
      const b = el.getBoundingClientRect();
      if (b.width && (b.height < 44 || b.width < 44)) issues.push(`small target ${Math.round(b.width)}x${Math.round(b.height)} "${(el.getAttribute("aria-label") || el.textContent || "").trim().slice(0, 30)}"`);
    }
    for (const el of document.querySelectorAll("body *")) {
      if (![...el.childNodes].some((c) => c.nodeType === 3 && c.textContent.trim())) continue;
      const s = getComputedStyle(el);
      if (parseFloat(s.fontSize) < 14 && s.position !== "absolute") issues.push(`tiny text ${s.fontSize} "${el.textContent.trim().slice(0, 30)}"`);
    }
    return [...new Set(issues)];
  });
  if (r.length) fail(`${label} audit: ${r.join(" | ")}`);
};
let lastCards = "";
const cards = async () => {
  // wait for a NEW set that has finished personalizing (final stage)
  await page.waitForFunction((prev) => {
    const now = [...document.querySelectorAll('[aria-label^="Say:"]')].map((x) => x.getAttribute("aria-label")).join("|");
    return !document.body.innerText.includes("Personalizing for") && now.split("|").length >= 3 && now !== prev;
  }, lastCards, { timeout: 8000 });
  const c = await page.$$eval('[aria-label^="Say:"]', (e) => e.map((x) => x.getAttribute("aria-label").slice(5)));
  lastCards = c.map((t) => `Say: ${t}`).join("|");
  return c;
};
const expectText = async (re, what) => { const t = await page.innerText("body"); if (!re.test(t)) fail(`missing ${what}: ${t.replace(/\s+/g, " ").slice(0, 300)}`); };
const person = (name) => page.getByRole("radio", { name: new RegExp(`^${name}`) });
const line = (t) => page.getByText(`“${t}”`);

await page.goto(URL);
await person("Dana").waitFor();
// personas per docs/01-product.md: Sam is Maya's grandson (family), never a sibling/friend
{
  const picker = await page.getByRole("radiogroup").innerText();
  if (!/Sam Chen\s+Grandson, 16/.test(picker) || /brother|sibling|friend/i.test(picker)) fail(`Sam persona wrong: ${picker.replace(/\s+/g, " ")}`);
}

await beat("0:20 Dana: 'Here for your refill?'", async () => {
  await tap(person("Dana")); await tap(line("Hi Maya! Here for your refill?"));
  const c = await cards();
  await expectText(/Dana Okafor\s+Pharmacist at Shoppers · Last talked (Oct 28|28 Oct)/, "Dana header");
  await expectText(/Dana was checking on blister packs/, "blister-pack thread chip");
  if (!c.includes("Yes please, same as October") || !c.includes("Did the blister packs come in?")) fail(`Dana cards: ${c.join(" / ")}`);
});
await beat("0:20 Maya taps 'blister packs' card → spoken", async () => {
  await tap(page.getByRole("button", { name: /^Say: Did the blister/ }));
  await page.getByText("Speaking · tap to stop").waitFor({ timeout: 3000 });
  await page.waitForFunction(() => !document.body.innerText.includes("tap to stop"), null, { timeout: 15000 });
  await expectText(/YOU\s+Did the blister packs come in\?/i, "Maya's reply in transcript");
}, 1);
await beat("1:00 Mike: 'How've you been?'", async () => {
  await tap(person("Mike")); await tap(line("Hey Maya! How've you been?"));
  const c = await cards();
  if (!c.includes("Honestly the new meds have been rough.")) fail(`Mike cards: ${c.join(" / ")}`);
});
await beat("1:00 Long-press → Too personal → Learned toast", async () => {
  await tap(page.getByRole("button", { name: /More options for: Honestly/ }));
  await tap(page.getByRole("button", { name: /Too personal/ }));
  await page.getByText("Learned: keep health & medication private with acquaintances.").waitFor({ timeout: 3000 });
  await expectText(/Checked against 23 past replies, no conflicts\./, "validation line");
});
await beat("1:45 Mike: 'Anything new?' → small talk + 1 hidden", async () => {
  await tap(line("Anything new?"));
  const c = await cards();
  if (c.some((t) => /dose|meds|physio|dizzy/i.test(t))) fail(`health leaked: ${c.join(" / ")}`);
  await page.waitForTimeout(300);
  const pill = await page.locator('[aria-label*="hidden by your privacy rules"]').getAttribute("aria-label");
  if (!/^1 suggestion hidden/.test(pill ?? "")) {
    await page.locator('[aria-label*="hidden by your privacy rules"]').click();
    const hidden = (await page.getByRole("dialog").innerText()).replace(/\s+/g, " ");
    await page.keyboard.press("Escape");
    fail(`hidden pill after final stage: "${pill}" :: ${hidden}`);
  }
});
await beat("1:45 (optional) show which rule hid it", async () => {
  await tap(page.getByRole("button", { name: /hidden by your privacy rules/ }));
  await expectText(/Keep health & medication private with acquaintances/, "hidden-by rule");
  // privacy: the hidden wording must not be on screen (or in the DOM) until asked for
  const dialog = await page.getByRole("dialog").innerText();
  if (/doctor upped my dose/i.test(dialog) || !/Sensitive suggestion hidden/.test(dialog)) fail(`hidden sheet discloses text: ${dialog.replace(/\s+/g, " ")}`);
  await page.keyboard.press("Escape");
}, 1);
await beat("2:10 Dana: 'Any side effects…?' → meds still shown", async () => {
  await tap(person("Dana")); await tap(line("Any side effects with the new generic?"));
  const c = await cards();
  if (!c.some((t) => /side effects|dizzy|take it with food/i.test(t))) fail(`Dana meds missing: ${c.join(" / ")}`);
});
await beat("2:25 Scoreboard", async () => {
  await tap(page.getByRole("button", { name: /Evaluation|Eval/ }));
  await page.getByText("Hit@4 (right reply in top 4)").waitFor({ timeout: 3000 });
}, 1);
await beat("back to Talk keeps state", async () => {
  await tap(page.getByRole("button", { name: "Talk", exact: true }));
  await page.getByRole("button", { name: /^Say:/ }).first().waitFor({ timeout: 2000 });
}, 1);
await beat("Memory & privacy shows learned rule (evidence concealed until Show)", async () => {
  await tap(page.getByRole("button", { name: /Memory & privacy/ }));
  await expectText(/Learned from a reply you marked too personal/, "learned rule evidence label");
  if (/Honestly the new meds/.test(await page.content())) fail("rejected text is in the DOM before Show");
  await tap(page.getByRole("button", { name: "Show the hidden reply" }).first());
  await expectText(/Honestly the new meds have been rough\./, "evidence after an intentional Show");
}, 2);
// setup action between rehearsals (not a stage beat): 2 taps on this screen
await beat("Reset demo (between rehearsals)", async () => {
  await tap(page.getByRole("button", { name: /Reset demo/ }));
  await tap(page.getByRole("button", { name: /Tap again to reset/ }));
  await page.getByText("Who are you talking to?").waitFor({ timeout: 3000 });
});
await beat("Rehearsal 2 starts clean (Mike sees meds card again)", async () => {
  await tap(person("Mike")); await tap(line("Hey Maya! How've you been?"));
  const c = await cards();
  if (!c.includes("Honestly the new meds have been rough.")) fail(`after reset: ${c.join(" / ")}`);
});
await beat("Sam (grandson) gets hockey replies", async () => {
  await tap(person("Sam")); await tap(line("Hi Grandma! We won on Saturday!"));
  await expectText(/Sam Chen\s+Grandson, 16/, "Sam header");
  const c = await cards();
  if (!c.some((t) => /bud/.test(t))) fail(`Sam cards lack "bud": ${c.join(" / ")}`);
});
await beat("End chat → memory saved", async () => {
  await tap(page.getByRole("button", { name: /End conversation/ }));
  await page.getByText(/Remembered your chat with Sam/).first().waitFor({ timeout: 3000 });
}, 1);

console.log(`${tag} console: ${errs.length ? errs.join("\n") : "clean"}`);
if (errs.length) failed = true;
await browser.close();
process.exit(failed ? 1 : 0);
