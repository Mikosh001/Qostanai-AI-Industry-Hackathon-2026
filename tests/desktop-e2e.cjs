// Real Electron + real local backend. Camera is explicitly disabled by the teacher test profile.
// This does not simulate native USB enforcement or claim a webcam acceptance test.
const { _electron: electron, expect } = require("@playwright/test");
const path = require("node:path");
const fs = require("node:fs");
(async () => {
  const root = path.resolve(__dirname, "..");
  const data = path.resolve(
    root,
    "../../work/desktop-acceptance-" + Date.now(),
  );
  const app = await electron.launch({
    ...(process.env.SERGEK_EXECUTABLE
      ? { executablePath: process.env.SERGEK_EXECUTABLE }
      : {}),
    args: process.env.SERGEK_EXECUTABLE ? [] : [root],
    cwd: root,
    env: { ...process.env, SERGEK_DATA: data, SERGEK_TESTING: "1" },
    timeout: 90000,
  });
  try {
    const page = await app.firstWindow();
    page.setDefaultTimeout(25000);
    await page.getByRole("button", { name: "Мұғалім панелі" }).click();
    await page
      .getByLabel("Құпиясөз", { exact: true })
      .fill("DesktopAcceptance123!");
    await page.getByRole("button", { name: "Құпиясөзді орнату" }).click();
    await expect(
      page.getByRole("heading", { name: "Бәрі бір панельде." }),
    ).toBeVisible();
    await expect
      .poll(
        async () =>
          page.evaluate(
            async () =>
              (await (await fetch("/api/diagnostics")).json()).vision
                .models_ready,
          ),
        { timeout: 30000 },
      )
      .toBe(true);
    await page.evaluate(async () => {
      const p = await (await fetch("/api/profile")).json();
      p.policy.camera_required = false;
      p.policy.screen_recording = false;
      p.policy.microphone_required = false;
      p.exam_mode = "monitor";
      p.policy.microphone_required = false;
      p.exam_mode = "monitor";
      const r = await fetch("/api/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(p),
      });
      if (!r.ok) throw new Error("Cannot save acceptance profile");
    });
    await page.getByRole("button", { name: "Студент режимі" }).click();
    await page.getByRole("button", { name: "Таныстыру тестін ашу" }).click();
    await page
      .getByLabel("Аты-жөніңіз", { exact: true })
      .fill("Acceptance student");

    await page.getByRole("checkbox").check();

    await page.getByRole("button", { name: "Фотоға өту" }).click();
    await expect(
      page.getByRole("heading", { name: "Фотоға түсіп, емтиханды бастаңыз" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Емтиханды бастау" }).click();
    await expect(
      page.getByRole("heading", {
        name: "Python тіліндегі өзгермейтін құрылым қайсы?",
      }),
    ).toBeVisible();
    await page.getByRole("button", { name: "B tuple" }).click();
    await expect(page.getByRole("button", { name: "B tuple" })).toHaveClass(
      /selected/,
    );
    await app.evaluate(({ BrowserWindow }) => {
      BrowserWindow.getAllWindows()[0].webContents.sendInputEvent({
        type: "keyDown",
        keyCode: "T",
        modifiers: ["control"],
      });
    });
    await expect
      .poll(async () =>
        page.evaluate(
          async () => (await window.sergek.invoke("snapshot")).event_count,
        ),
      )
      .toBeGreaterThan(0);
    fs.mkdirSync(path.join(root, "tests/browser/screens"), { recursive: true });
    await page.screenshot({
      path: path.join(root, "tests/browser/screens/local-exam.png"),
      fullPage: true,
    });
    await page.getByRole("button", { name: "Тестті аяқтау" }).click();
    await expect(
      page.getByRole("heading", { name: "Сессия аяқталды" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Мұғалім панелі" }).click();
    await page
      .getByLabel("Құпиясөз", { exact: true })
      .fill("DesktopAcceptance123!");
    await page.getByRole("button", { name: "Панельге кіру" }).click();
    await expect(
      page.getByText("Acceptance student", { exact: true }),
    ).toBeVisible();
    const saved = await page.evaluate(async () => {
      const rows = await (await fetch("/api/sessions")).json();
      return await (await fetch("/api/sessions/" + rows[0].id)).json();
    });
    if (saved.session.status !== "completed" || saved.answers["1"] !== 1)
      throw new Error("Answer/session was not persisted");
    if (!saved.events.some((e) => e.kind === "shortcut_blocked"))
      throw new Error("Blocked shortcut was not recorded");
    await page.getByRole("button", { name: "Студент режимі" }).click();
    await page.getByRole("button", { name: "Таныстыру тестін ашу" }).click();
    await page
      .getByLabel("Аты-жөніңіз", { exact: true })
      .fill("Teacher stop student");

    await page.getByRole("checkbox").check();

    await page.getByRole("button", { name: "Фотоға өту" }).click();
    await page.getByRole("button", { name: "Емтиханды бастау" }).click();
    await expect(
      page.getByRole("heading", {
        name: "Python тіліндегі өзгермейтін құрылым қайсы?",
      }),
    ).toBeVisible();
    await page.evaluate(async () => {
      const login = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: "DesktopAcceptance123!" }),
      });
      if (!login.ok) throw new Error("Teacher authentication failed");
      const snapshot = await window.sergek.invoke("snapshot");
      const stop = await fetch(
        "/api/sessions/" + snapshot.session.id + "/stop",
        { method: "POST" },
      );
      if (!stop.ok) throw new Error("Teacher stop failed");
    });
    await expect(
      page.getByRole("heading", { name: "Сессия аяқталды" }),
    ).toBeVisible();
    await expect
      .poll(async () =>
        page.evaluate(
          async () => (await window.sergek.invoke("snapshot")).session.status,
        ),
      )
      .toBe("completed");
    console.log(
      JSON.stringify({
        passed: true,
        session: saved.session.status,
        answers: saved.answers,
        eventKinds: saved.events.map((e) => e.kind),
        teacherStop: "completed and terminal snapshot preserved",
        camera: "disabled administrative test profile",
        data,
      }),
    );
  } finally {
    await app.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
