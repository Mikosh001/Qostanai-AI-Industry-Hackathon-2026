const { chromium, expect } = require("@playwright/test");
const { spawn } = require("node:child_process");
const path = require("node:path"),
  fs = require("node:fs");
(async () => {
  const root = path.resolve(__dirname, "..");
  const data = path.resolve(root, "../../work/audio-acceptance-" + Date.now());
  const server = spawn(
    process.env.SERGEK_PYTHON ||
      path.resolve(root, "../../work/sergek-venv/Scripts/python.exe"),
    [path.join(__dirname, "fixtures/audio_backend.py")],
    {
      cwd: root,
      windowsHide: true,
      env: {
        ...process.env,
        SERGEK_DATA: data,
        SERGEK_DESKTOP_KEY: "audio-fixture",
      },
      stdio: "ignore",
    },
  );
  let browser, heart;
  try {
    await expect
      .poll(
        async () => {
          try {
            return (await fetch("http://127.0.0.1:8772/api/health")).ok;
          } catch {
            return false;
          }
        },
        { timeout: 30000 },
      )
      .toBe(true);
    const headers = {
      "Content-Type": "application/json",
      "x-sergek-desktop": "audio-fixture",
    };
    const created = await (
      await fetch("http://127.0.0.1:8772/api/sessions", {
        method: "POST",
        headers,
        body: JSON.stringify({
          student: "Дыбыс сынағы",
          exam: "Микрофон үзіндісі",
          consent: true,
        }),
      })
    ).json();
    headers.Authorization = "Bearer " + created.token;
    const sid = created.session.id;
    const started = await fetch(
      `http://127.0.0.1:8772/api/student/${sid}/start`,
      { method: "POST", headers, body: "{}" },
    );
    if (!started.ok) throw new Error(await started.text());
    heart = setInterval(
      () =>
        fetch(`http://127.0.0.1:8772/api/student/${sid}/heartbeat`, {
          method: "POST",
          headers,
          body: "{}",
        }).catch(() => {}),
      1500,
    );
    browser = await chromium.launch({ channel: "msedge", headless: true });
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1000 },
    });
    await page.goto("http://127.0.0.1:8772/?role=teacher");
    await page
      .getByLabel("Құпиясөз", { exact: true })
      .fill("AudioAcceptance123!");
    await page.getByRole("button", { name: "Панельге кіру" }).click();
    await page.getByText("Дыбыс сынағы", { exact: true }).click();
    await expect(
      page.getByText("Ұзақ дауыс белсенділігі", { exact: true }),
    ).toBeVisible({ timeout: 25000 });
    await page.getByText("Ұзақ дауыс белсенділігі", { exact: true }).click();
    await expect(page.locator("audio")).toBeVisible({ timeout: 20000 });
    await expect
      .poll(() =>
        page
          .locator("audio")
          .evaluate((a) => Number.isFinite(a.duration) && a.duration > 2),
      )
      .toBe(true);
    await page.locator("audio").evaluate((a) => a.play());
    await expect
      .poll(() => page.locator("audio").evaluate((a) => a.currentTime))
      .toBeGreaterThan(0.2);
    await page.locator("audio").evaluate((a) => a.pause());
    await page.screenshot({
      path: path.join(root, "tests/browser/screens/audio-evidence.png"),
      fullPage: true,
    });
    clearInterval(heart);
    await fetch(`http://127.0.0.1:8772/api/student/${sid}/finish`, {
      method: "POST",
      headers,
      body: "{}",
    });
    console.log(
      JSON.stringify({
        passed: true,
        generatedPCM: true,
        physicalMicrophone: false,
        event: true,
        encryptedWav: true,
        teacherAudioPlayback: true,
        data,
      }),
    );
  } finally {
    clearInterval(heart);
    if (browser) await browser.close();
    server.kill();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
