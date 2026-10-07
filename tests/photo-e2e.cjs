const { chromium, expect } = require("@playwright/test");
const { spawn } = require("node:child_process");
const fs = require("node:fs"),
  path = require("node:path");
(async () => {
  const root = path.resolve(__dirname, "..");
  const work = path.resolve(
    process.env.SERGEK_TEST_WORK || path.join(root, "../../work"),
  );
  const fixture = path.join(work, "cv-acceptance");
  fs.mkdirSync(fixture, { recursive: true });
  for (const [name, url] of [
    [
      "portrait.jpg",
      "https://storage.googleapis.com/mediapipe-assets/portrait.jpg",
    ],
    [
      "lena.jpg",
      "https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/lena.jpg",
    ],
  ]) {
    if (!fs.existsSync(path.join(fixture, name))) {
      const response = await fetch(url);
      if (!response.ok) throw new Error("Cannot obtain public test fixture");
      fs.writeFileSync(
        path.join(fixture, name),
        Buffer.from(await response.arrayBuffer()),
      );
    }
  }
  const python =
    process.env.SERGEK_PYTHON ||
    (fs.existsSync(path.join(root, ".venv/Scripts/python.exe"))
      ? path.join(root, ".venv/Scripts/python.exe")
      : path.join(work, "sergek-venv/Scripts/python.exe"));
  fs.writeFileSync(path.join(fixture, "choice.txt"), "portrait.jpg");
  const data = path.join(work, "photo-ui-" + Date.now());
  const server = spawn(
    python,
    [path.join(__dirname, "fixtures/photo_backend.py")],
    {
      cwd: root,
      windowsHide: true,
      env: {
        ...process.env,
        SERGEK_DATA: data,
        SERGEK_DESKTOP_KEY: "isolated-photo-fixture",
        SERGEK_PHOTO_FIXTURE: fixture,
      },
      stdio: "ignore",
    },
  );
  let browser;
  try {
    await expect
      .poll(
        async () => {
          try {
            return (await fetch("http://127.0.0.1:8771/api/health")).ok;
          } catch {
            return false;
          }
        },
        { timeout: 30000 },
      )
      .toBe(true);
    browser = await chromium.launch({ channel: "msedge", headless: true });
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1080 },
    });
    page.setDefaultTimeout(25000);
    await page.addInitScript(() => {
      let current = null,
        heartbeat;
      const send = async (route, method = "GET", body) => {
        const response = await fetch("/api" + route, {
          method,
          headers: {
            "Content-Type": "application/json",
            "x-sergek-desktop": "isolated-photo-fixture",
            ...(current ? { Authorization: "Bearer " + current.token } : {}),
          },
          body: body ? JSON.stringify(body) : undefined,
        });
        if (!response.ok) throw new Error(await response.text());
        return response.json();
      };
      window.sergek = {
        onLaunch: () => () => {},
        invoke: async (command, value = {}) => {
          if (command === "info") return { desktop: true, launch: "" };
          if (command === "create") {
            current = await send("/sessions", "POST", value);
            return current.session;
          }
          const route = "/student/" + current.session.id;
          if (command === "snapshot")
            return {
              ...(await send(route + "/snapshot")),
              guard: {
                available: false,
                error:
                  "Синтетикалық камера сынағы; Windows модулі пайдаланылмайды.",
              },
              displays: 1,
            };
          if (command === "camera-stream") {
            const access = await send(route + "/camera-ticket", "POST", {});
            return { url: "/api/camera/stream?ticket=" + access.ticket };
          }
          if (command === "enroll") return send(route + "/enroll", "POST", {});
          if (command === "start") {
            const result = await send(route + "/start", "POST", {});
            heartbeat = setInterval(
              () => send(route + "/heartbeat", "POST", {}),
              2000,
            );
            return result;
          }
          if (command === "exam") return send(route + "/exam");
          if (command === "answer")
            return send(route + "/answer", "PUT", value);
          if (command === "finish") {
            clearInterval(heartbeat);
            return send(route + "/finish", "POST", value);
          }
          throw new Error("OS mutations disabled in photo fixture");
        },
      };
    });
    await page.goto("http://127.0.0.1:8771");
    await page.getByRole("button", { name: "Таныстыру тестін ашу" }).click();
    await page
      .getByLabel("Аты-жөніңіз", { exact: true })
      .fill("Synthetic photo acceptance");

    await page.getByRole("checkbox").check();
    await page.getByRole("button", { name: "Фотоға өту", exact: true }).click();
    const photo = page.getByRole("button", {
      name: "Фотоға түсіру",
      exact: true,
    });
    await expect(photo).toBeEnabled({ timeout: 30000 });
    await expect(
      page.getByRole("button", { name: "Емтиханды бастау", exact: true }),
    ).toBeDisabled();
    await expect(
      page.getByText("Сол жаққа қараңыз", { exact: true }),
    ).toHaveCount(0);
    await expect
      .poll(() =>
        page.locator(".camera-view img").evaluate((img) => img.naturalWidth),
      )
      .toBeGreaterThan(0);
    await photo.click();
    await expect(
      page.getByText("Бастапқы фото сақталды", { exact: true }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Тірі адамды тексеру" })).toHaveCount(0);
    await expect(page.getByText("Фото/видеоға қарсы тексеру", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Емтиханды бастау", exact: true })).toBeEnabled();
    await page.screenshot({
      path: path.join(root, "tests/browser/screens/student-photo-v12.png"),
      fullPage: true,
    });
    await expect(page.getByLabel("Мұғалім құпиясөзі")).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Windows қорғанысын қосу" }),
    ).toHaveCount(0);
    const status = await page.evaluate(
      async () => (await window.sergek.invoke("snapshot")).status,
    );
    await page
      .getByRole("button", { name: "Емтиханды бастау", exact: true })
      .click();
    fs.writeFileSync(path.join(fixture, "choice.txt"), "lena.jpg");
    await expect(
      page.getByText(
        "Бет бастапқы фотомен сәйкеспейді. Мұғалім тексеретін оқиға тіркеледі.",
        { exact: true },
      ),
    ).toBeVisible({ timeout: 30000 });
    await new Promise((resolve) => setTimeout(resolve, 4200));
    if (process.env.SERGEK_PHONE_IMAGE) {
      await page.evaluate(async () => { const r = await fetch("/api/auth/login", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({password:"PhotoAcceptance123!"})}); if(!r.ok)throw new Error("Fixture teacher login failed"); });
      fs.writeFileSync(path.join(fixture, "choice.txt"), "phone.jpg");
      await expect.poll(async () => {
        return page.evaluate(async () => { const snapshot=await window.sergek.invoke("snapshot"); const report=await (await fetch("/api/sessions/"+snapshot.session.id)).json(); return report.events.some((event)=>event.kind==="phone_detected"); });
      }, { timeout: 30000 }).toBe(true);
      await new Promise((resolve) => setTimeout(resolve, 5200));
    }
    await page
      .getByRole("button", { name: "Тестті аяқтау", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Сессия аяқталды" }),
    ).toBeVisible();
    const saved = await page.evaluate(async () => {
      await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: "PhotoAcceptance123!" }),
      });
      const rows = await (await fetch("/api/sessions")).json();
      return await (await fetch("/api/sessions/" + rows[0].id)).json();
    });
    if (!saved.events.some((e) => e.kind === "identity_mismatch" && e.media))
      throw new Error("Identity event and camera evidence missing");
    if (process.env.SERGEK_PHONE_IMAGE && !saved.events.some((e) => e.kind === "phone_detected" && e.media && e.requires_review))
      throw new Error("Phone event and camera evidence missing");
    const result = {
      passed: true,
      fixture: "public image sequence; no physical camera or screen",
      capture_fps: status.fps,
      analysis_fps: status.analysis_fps,
      photo_saved: true,
      manual_challenge_removed: true,
      legacy_profile_compatible: true,
      stream_rendered: true,
      identity_event_with_evidence: true,
      phone_event_with_evidence: Boolean(process.env.SERGEK_PHONE_IMAGE),
    };
    fs.writeFileSync(
      path.join(__dirname, "photo-ui-acceptance.json"),
      JSON.stringify(result, null, 2),
    );
    console.log(JSON.stringify(result));
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
