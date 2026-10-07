// Real Electron acceptance. Administrator's test profile disables camera and OS restrictions.
const { _electron: electron, expect } = require("@playwright/test");
const fs = require("node:fs");
const path = require("node:path");
const root = path.resolve(__dirname, "..");
const data = path.resolve(root, "../../work/languages-acceptance-" + Date.now());
const launch = () => electron.launch({
  ...(process.env.SERGEK_EXECUTABLE ? { executablePath: process.env.SERGEK_EXECUTABLE } : {}),
  args: process.env.SERGEK_EXECUTABLE ? [] : [root], cwd: root,
  env: { ...process.env, SERGEK_DATA: data, SERGEK_TESTING: "1" }, timeout: 90000,
});
(async () => {
  let app = await launch();
  let firstOrigin;
  try {
    const page = await app.firstWindow();
    page.setDefaultTimeout(30000);
    await page.locator(".language-selector select").selectOption("en");
    expect(await page.evaluate(async () => (await (await fetch("/api/health")).json()).version)).toBe("1.4.3");
    firstOrigin = new URL(page.url()).origin;
    await page.getByRole("button", { name: "Teacher dashboard" }).click();
    await page.getByLabel("Password", { exact: true }).fill("LanguageAcceptance123!");
    await page.getByRole("button", { name: "Set password" }).click();
    await expect(page.getByRole("heading", { name: "Everything in one dashboard." })).toBeVisible();
    await page.evaluate(async () => {
      const profile = await (await fetch("/api/profile")).json();
      Object.assign(profile.policy, { camera_required: false, microphone_required: false, screen_recording: false });
      profile.exam_mode = "monitor";
      const response = await fetch("/api/profile", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(profile) });
      if (!response.ok) throw new Error("Could not save software test profile");
    });
    await page.getByRole("button", { name: "Student mode" }).click();
    await page.getByRole("button", { name: "Open demonstration test" }).click();
    await page.getByLabel("Your full name", { exact: true }).fill("Мейірбек — Language fixture");
    await page.getByRole("checkbox").check();
    await page.locator(".language-selector select").selectOption("ru");
    await expect(page.getByLabel("Ваше имя и фамилия", { exact: true })).toHaveValue("Мейірбек — Language fixture");
    await expect(page.getByRole("checkbox")).toBeChecked();
    await page.getByRole("button", { name: "Перейти к фото" }).click();
    await page.getByRole("button", { name: "Начать экзамен", exact: true }).click();
    await page.getByRole("button", { name: "B tuple" }).click();
    const before = await page.evaluate(() => window.sergek.invoke("snapshot"));
    await page.locator(".language-selector select").selectOption("kk");
    await expect(page.getByRole("button", { name: "B tuple" })).toHaveClass(/selected/);
    const after = await page.evaluate(() => window.sergek.invoke("snapshot"));
    expect(after.session.id).toBe(before.session.id);
    expect(after.session.status).toBe("active");
    await page.locator(".language-selector select").selectOption("en");
    await page.getByRole("button", { name: "Finish test" }).click();
    await expect(page.getByRole("heading", { name: "Session completed" })).toBeVisible();
    const invalid = await page.evaluate(async () => {
      try { await window.sergek.invoke("set-language", { language: "../invalid" }); return false; }
      catch { return (await window.sergek.invoke("get-language")).language === "en"; }
    });
    expect(invalid).toBe(true);
    await page.screenshot({ path: path.join(root, "tests/browser/screens/three-languages-desktop.png") });
  } finally { await app.close(); }
  app = await launch();
  try {
    const page = await app.firstWindow();
    await expect(page.locator(".language-selector select")).toHaveValue("en", { timeout: 30000 });
    await expect(page.getByRole("heading", { name: /Focus on your knowledge/ })).toBeVisible();
    const result = { passed: true, version: "1.4.3", languages: ["kk", "ru", "en"], firstOrigin, secondOrigin: new URL(page.url()).origin,
      packaged: Boolean(process.env.SERGEK_EXECUTABLE), savedAcrossRestart: true, activeSessionAndAnswerPreserved: true, invalidLanguageRejected: true, physicalProtectionTested: false };
    fs.writeFileSync(path.join(root, "tests/languages-v143.json"), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result));
  } finally { await app.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
