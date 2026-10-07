// Real Moodle 4.5.15 + installed PHP plugin + Electron + separate HTTPS teacher hub.
const { chromium, _electron: electron, expect } = require("@playwright/test");
const path = require("node:path");
const fs = require("node:fs");
(async () => {
  const root = path.resolve(__dirname, "..");
  const lab =
    process.env.SERGEK_LAB || path.resolve(root, "../../work/local-moodle");
  const creds = JSON.parse(fs.readFileSync(path.join(lab, "credentials.json")));
  const meta = JSON.parse(fs.readFileSync(path.join(lab, "lab.json")));
  const exam = JSON.parse(fs.readFileSync(path.join(lab, "exam.json")));
  if (process.env.SERGEK_QUIZ_URL) exam.url = process.env.SERGEK_QUIZ_URL;
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  let app;
  const loginTrace=[];
  try {
    page.setDefaultTimeout(30000);
    await page.goto("https://localhost/login/index.php");
    await page.locator("#username").fill(creds.student);
    await page.locator("#password").fill(creds.studentpass);
    await page.locator("#loginbtn").click();
    await page.goto(exam.url);
    await expect(
      page
        .getByText(
          "Start the Sergek session and retry. An active local proctoring session is required.",
        )
        .first(),
    ).toBeVisible();
    const data = path.resolve(root, "../../work/moodle-agent-" + Date.now());
    let demoEnv = {};
    if (process.env.SERGEK_DEMO_ACCEPTANCE === "1") {
      fs.mkdirSync(data, { recursive: true });
      const config = JSON.parse(
        fs.readFileSync(path.join(lab, "demo-config.json")),
      );
      config.data = path.join(data, "demo-agent");
      const file = path.join(data, "demo-config.json");
      fs.writeFileSync(file, JSON.stringify(config));
      demoEnv = { SERGEK_DEMO_CONFIG: file, SERGEK_DATA: config.data };
    }
    app = await electron.launch({
      ...(process.env.SERGEK_EXECUTABLE
        ? { executablePath: process.env.SERGEK_EXECUTABLE }
        : {}),
      args: process.env.SERGEK_EXECUTABLE ? [] : [root],
      cwd: root,
      env: {
        ...process.env,
        SERGEK_DATA: data,
        SERGEK_TESTING: "1",
        SERGEK_CA_FILE: path.join(lab, "localhost.crt"),
        ...demoEnv,
      },
      timeout: 90000,
    });
    const local = await app.firstWindow();
    local.setDefaultTimeout(25000);
    // firstWindow can be returned while the hidden startup page is still loading.
    await expect
      .poll(
        () =>
          app.evaluate(({ BrowserWindow }) =>
            BrowserWindow.getAllWindows().some((window) => window.isVisible()),
          ),
        { timeout: 30000 },
      )
      .toBe(true);
    if (process.env.SERGEK_DEMO_ACCEPTANCE === "1") {
      const bootstrap = await local.evaluate(async () => ({
        health: await (await fetch("/api/health")).json(),
        profile: await (await fetch("/api/profile")).json(),
      }));
      if (
        bootstrap.health.setup_required ||
        bootstrap.profile.moodle_url !== "https://localhost/" ||
        bootstrap.profile.exam_mode !== "strict" ||
        !bootstrap.profile.policy.microphone_required ||
        !bootstrap.profile.policy.usb_block
      )
        throw new Error(
          "Demo was not automatically configured with full protection",
        );
    } else
      await local.evaluate(
        async (password) => window.sergek.invoke("setup", { password }),
        creds.teacherpass,
      );
    if (process.env.SERGEK_HANDOFF_ONLY !== "1")
      await local.evaluate(
        async ({ creds, meta }) => {
          const send = async (route, method, body) => {
            const r = await fetch("/api" + route, {
              method,
              headers: { "Content-Type": "application/json" },
              body: body ? JSON.stringify(body) : undefined,
            });
            if (!r.ok) throw new Error(route + ": " + (await r.text()));
            return r.json();
          };
          await send("/auth/login", "POST", { password: creds.teacherpass });
          let p = await send("/profile", "GET");
          p.policy.camera_required = false;
          p.policy.screen_recording = false;
          p.policy.microphone_required = false;
          p.allowed_hosts = ["localhost"];
          p.moodle_url = "https://localhost/";
          p.platonus_url = "https://localhost/";
          p.tls_pins = { localhost: meta.fingerprint };
          await send("/profile", "PUT", p);
          await send("/integration/moodle", "PUT", { key: creds.sharedkey });
          await send("/integration/hub", "PUT", {
            enabled: true,
            url: meta.hub,
            pairing_key: creds.hubkey,
          });
          await send("/auth/logout", "POST");
        },
        { creds, meta },
      );
    await local.reload();
    await expect(local.getByLabel("Емтихан режимі")).toHaveCount(0);
    await expect(local.getByLabel("Емтихан сілтемесі")).toHaveCount(0);
    await local.getByRole("button", { name: "Moodle-ға кіру" }).click();
    await expect
      .poll(() =>
        app
          .context()
          .pages()
          .some((p) => p.url().startsWith("https://localhost/")),
      )
      .toBe(true);
    const portal = app
      .context()
      .pages()
      .find((p) => p.url().startsWith("https://localhost/"));
    portal.on('response',async r=>{
      try {
        const u=new URL(r.url());if(!u.pathname.endsWith('.php'))return;
        const hash=v=>require('node:crypto').createHash('sha256').update(v||'').digest('hex').slice(0,8);
        const sid=((await r.request().allHeaders()).cookie||'').match(/MoodleSession=([^;]+)/)?.[1];
        const set=(await r.headersArray()).filter(h=>h.name.toLowerCase()==='set-cookie').map(h=>h.value.match(/^MoodleSession=([^;]*)/)?.[1]).filter(v=>v!==undefined);
        if(set.length||u.pathname.includes('/login/')||u.pathname==='/my/')loginTrace.push({path:u.pathname,method:r.request().method(),status:r.status(),requestSid:hash(sid),setSids:set.map(hash)});
      }catch{}
    });
    await portal.locator("#username").fill(creds.student);
    await portal.locator("#password").fill(creds.studentpass);
    await portal.locator("#loginbtn").click();
    await expect(portal.locator('a[href*="/login/logout.php"]').first()).toBeAttached();
    await expect(local.getByText("Moodle: өз логиніңізбен кіріп, тестті таңдаңыз")).toHaveCount(0);
    await portal.goto(exam.url).catch((error) => {
      // The selected protected quiz automatically closes its portal during handoff.
      if (!portal.isClosed() && !String(error).includes("ERR_ABORTED"))
        throw error;
    });
    await expect(local.getByRole("button", { name: "Фотоға өту" })).toBeVisible(
      { timeout: 25000 },
    );
    if (process.env.SERGEK_HANDOFF_ONLY === "1") {
      const resolved = await local.evaluate(async () => {
        const info = await window.sergek.invoke("info");
        return window.sergek.invoke("resolve-launch", { token: info.launch });
      });
      if (
        resolved.mode !== "strict" ||
        !resolved.exam_url.startsWith("https://localhost/")
      )
        throw new Error("Judge demo was not signed for protected local Moodle");
      await local.screenshot({
        path: path.join(
          root,
          "tests/browser/screens/demo-selected-exam-v121.png",
        ),
      });
      console.log(
        JSON.stringify({
          passed: true,
          packaged: Boolean(process.env.SERGEK_EXECUTABLE),
          automaticDemoBootstrap: true,
          realLocalMoodleLogin: true,
          selectedQuizAutomaticHandoff: true,
          signedMode: "strict",
          protectionPolicyUnchanged: true,
          cameraAndNativeRestrictions: "not started; stopped before consent",
          exam: resolved.exam,
        }),
      );
      return;
    }
    await local.getByRole("checkbox").check();
    await local.getByRole("button", { name: "Фотоға өту" }).click();
    await expect(local.getByRole("button", { name: "Тест бетіне өту" })).toBeVisible();
    await expect(local.getByLabel("Мұғалім құпиясөзі")).toHaveCount(0);
    const created = await local.evaluate(
      async () => (await window.sergek.invoke("snapshot")).session,
    );
    if (created.data.moodle.userid !== String(exam.studentid))
      throw new Error("Signed identity was not bound");
    await local.getByRole("button", { name: "Тест бетіне өту" }).click();
    await expect
      .poll(
        () =>
          app
            .context()
            .pages()
            .some((p) => p.url().startsWith("https://localhost/")),
        { timeout: 30000 },
      )
      .toBe(true);
    const protectedPage = app
      .context()
      .pages()
      .find((p) => p.url().startsWith("https://localhost/"));
    protectedPage.setDefaultTimeout(30000);
    await expect(protectedPage.locator("#username")).toHaveCount(0);
    // The Moodle login from the portal survives the signed handoff; no second login.
    const attemptButton = protectedPage.getByRole("button", {
      name: /Attempt quiz|Re-attempt quiz|Continue your attempt/,
    });
    // Regression: the very first protected page must be usable. No manual reload.
    await expect(attemptButton).toBeVisible({ timeout: 30000 });
    await expect(protectedPage.getByRole("link", { name: "Open Sergek Proctor", exact: true })).toHaveCount(0);
    const pageProtection = await protectedPage.evaluate(() => ({
      printBlocked: window.print.__sergekBlocked === true,
      pasteBlocked: !document.dispatchEvent(
        new Event("paste", { bubbles: true, cancelable: true }),
      ),
    }));
    if (!pageProtection.printBlocked || !pageProtection.pasteBlocked)
      throw new Error("Print/clipboard protection did not initialize");
    await protectedPage.evaluate(() => {
      const image = new Image();
      image.src = "https://cdn.jsdelivr.net/sergek-blocked-regression.png";
      window.open("https://example.invalid/sergek-regression", "_blank");
    });
    const prepared = await local.evaluate(async () => (await window.sergek.invoke("snapshot")).session);
    if(prepared.status!=="preflight" || prepared.started) throw new Error("Protection started before Moodle Start attempt");
    await expect(local.getByText('Moodle-де «Start attempt» басыңыз')).toBeVisible();
    const attemptStartWait = Date.now();
    await attemptButton.click();
    const startAttempt = protectedPage.getByRole("button", {
      name: "Start attempt",
      exact: true,
    });
    await expect
      .poll(
        async () =>
          (await startAttempt.isVisible()) ||
          (await protectedPage.locator(".que").count()) > 0,
        { timeout: 30000 },
      )
      .toBe(true);
    if (await startAttempt.isVisible()) await startAttempt.click();
    await expect.poll(async () => (await local.evaluate(async () => (await window.sergek.invoke("snapshot")).session)).status).toBe("active");
    const active = await local.evaluate(async () => (await window.sergek.invoke("snapshot")).session);
    if(!active.started) throw new Error("Actual start not persisted");
    await expect(protectedPage.locator(".que").first()).toBeVisible();
    const startupMilliseconds = Date.now() - attemptStartWait;
    if(startupMilliseconds > 15000) throw new Error("Exam startup exceeded 15 seconds: " + startupMilliseconds);
    if (process.env.SERGEK_QUIZ_URL) {
      const firstPage = new URL(protectedPage.url()); firstPage.searchParams.set("page", "0");
      await protectedPage.goto(firstPage.href);
      for (let i = 0; i < 5; i++) {
        const question = protectedPage.locator(".que").first();
        await expect(question).toBeVisible();
        if(process.env.SERGEK_SLOW_QUIZ === "1") await protectedPage.waitForTimeout(17000);
        const live = await local.evaluate(async () => (await window.sergek.invoke("snapshot")).session);
        if(live.status!=="active" || live.started!==active.started) throw new Error("Session lost at question "+(i+1));
        const text = await question.innerText();
        const correct = text.includes("Алгоритм")
          ? "Мәселені шешуге арналған реттелген қадамдар"
          : text.includes("Айнымалы")
            ? "Бағдарламада мәнді сақтау"
            : text.includes("Функция")
              ? "Кодты бөліктерге бөліп, қайта қолдану үшін"
              : text.includes("Цикл")
                ? "True"
                : text.includes("Массив")
                  ? "False"
                  : null;
        if (!correct) throw new Error("Unexpected authored question");
        await question.getByLabel(correct).check();
        if (i < 4)
          await protectedPage
            .getByRole("button", { name: "Next page", exact: true })
            .click();
      }
    } else {
      await expect(
        protectedPage.getByText(
          "Sergek performs camera inference on the local computer.",
        ),
      ).toBeVisible({ timeout: 30000 });
      await protectedPage.getByLabel("True", { exact: true }).check();
    }
    await protectedPage
      .getByRole("button", { name: "Finish attempt ...", exact: true })
      .click();
    await protectedPage
      .getByRole("button", { name: "Submit all and finish", exact: true })
      .click();
    await protectedPage
      .getByRole("dialog")
      .last()
      .getByRole("button", { name: "Submit all and finish", exact: true })
      .click();
    await expect
      .poll(
        async () =>
          local.evaluate(
            async () => (await window.sergek.invoke("snapshot")).session.status,
          ),
        { timeout: 45000, intervals: [1000] },
      )
      .toBe("completed");
    await expect(
      local.getByRole("heading", { name: "Сессия аяқталды" }),
    ).toBeVisible();
    const completed = await local.evaluate(async () => (await window.sergek.invoke("snapshot")).session);
    if(!completed.ended || completed.ended<completed.started) throw new Error("Actual end not persisted");
    const { execFileSync } = require("node:child_process");
    const python =
      process.env.SERGEK_PYTHON ||
      path.resolve(root, "../../work/sergek-venv/Scripts/python.exe");
    const auditProof = JSON.parse(
      execFileSync(
        python,
        [
          "-c",
          "import sqlite3,json,sys; db=sqlite3.connect(sys.argv[1]); print(json.dumps({'audit':[r[0] for r in db.execute(\"select action from audit where action in ('resource_blocked','window_blocked')\")],'false_flags':db.execute(\"select count(*) from events where kind in ('navigation_blocked','resource_blocked','window_blocked')\").fetchone()[0]}))",
          path.join(demoEnv.SERGEK_DATA || data, "sergek.db"),
        ],
        { windowsHide: true, encoding: "utf8" },
      ),
    );
    if (
      auditProof.false_flags ||
      !auditProof.audit.includes("resource_blocked") ||
      !auditProof.audit.includes("window_blocked")
    )
      throw new Error(
        "Blocked assets/windows did not remain solely in the security audit",
      );
    await page.goto(exam.url);
    await expect
      .poll(
        async () => {
          await page.reload();
          return page
            .getByText(
              "Start the Sergek session and retry. An active local proctoring session is required.",
            )
            .count();
        },
        { timeout: 30000 },
      )
      .toBeGreaterThan(0);
    const result = {
        passed: true,
        moodle: "4.5.15",
        plugin: "quizaccess_sergek",
        signedIdentity: true,
        portalLogin: true,
        automaticallyOpenedFromSelectedQuiz: true,
        loginRetainedDuringHandoff: true,
        noStudentModeOrUrlOrTeacherPassword: true,
        automaticDemoBootstrap: process.env.SERGEK_DEMO_ACCEPTANCE === "1",
        automaticallyReleasedAfterMoodleSubmission: true,
        attemptSubmitted: true,
        protectionDeferredUntilAttempt: true,
        startupMilliseconds,
        persistedStart: completed.started,
        persistedEnd: completed.ended,
        slowQuiz: process.env.SERGEK_SLOW_QUIZ === "1",
        firstProtectedPageUsableWithoutReload: true,
        serverGating: true,
        blockedResourcesAndWindowsAuditOnly: true,
        camera: "disabled administrative software test profile",
        data,
      };
    if(process.env.SERGEK_ACCEPTANCE_OUTPUT) fs.writeFileSync(process.env.SERGEK_ACCEPTANCE_OUTPUT,JSON.stringify(result,null,2));
    console.log(JSON.stringify(result));
  } catch (error) {
    for (const p of app?.context().pages() || [])
      if (p.url().startsWith("https://localhost"))
        await p
          .screenshot({
            path: path.join(
              root,
              "tests/browser/screens/protected-moodle-error.png",
            ),
            fullPage: true,
          })
          .catch(() => {});
    await page
      .screenshot({
        path: path.join(root, "tests/browser/screens/moodle-error.png"),
        fullPage: true,
      })
      .catch(() => {});
    console.error("Login cookie trace (hashes only):",JSON.stringify(loginTrace));
    console.error("Moodle test page:", page.url());
    throw error;
  } finally {
    if (app) await app.close();
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
