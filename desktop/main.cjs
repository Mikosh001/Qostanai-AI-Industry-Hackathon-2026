const {
  app,
  BrowserWindow,
  WebContentsView,
  ipcMain,
  screen,
  session,
  shell,
} = require("electron");
const { spawn } = require("node:child_process");
const path = require("node:path");
const fs = require("node:fs");
const crypto = require("node:crypto");
const net = require("node:net");
const readline = require("node:readline");
const { allowedUrl, blockedInput } = require("./policy.cjs");
const { startProtectedExam } = require("./start-flow.cjs");
const root = path.join(__dirname, "..");
let window,
  examView,
  backend,
  guard,
  current,
  guardState = {},
  heartbeat,
  origin,
  port,
  profile;
let exiting = false;
let lastSnapshot = null;
let heartbeatBusy = false;
let guardHeartbeat,
  guardHeartbeatBusy = false,
  guardFailure = "";
let surfaceTimer,
  surfaceBusy = false;
async function captureExamSurface() {
  if (
    surfaceBusy ||
    !current ||
    current.session.status !== "active" ||
    !profile?.policy.screen_recording ||
    !window ||
    window.isDestroyed()
  )
    return;
  surfaceBusy = true;
  try {
    const sid = current.session.id;
    if (!window.isFocused()) {
      await api("/api/desktop/frame", "POST", { sid, clear: true });
      return;
    }
    const contents = examView?.webContents || window.webContents;
    const image = await contents.capturePage();
    if (image.isEmpty()) return;
    const content = window.getContentBounds();
    const view = examView?.getBounds();
    const scale = screen.getDisplayMatching(window.getBounds()).scaleFactor;
    const bounds = {
      x: Math.round((content.x + (view?.x || 0)) * scale),
      y: Math.round((content.y + (view?.y || 0)) * scale),
      width: Math.round((view?.width || content.width) * scale),
      height: Math.round((view?.height || content.height) * scale),
    };
    const jpeg = image
      .resize({ width: Math.min(image.getSize().width, 1280) })
      .toJPEG(68)
      .toString("base64");
    await api("/api/desktop/frame", "POST", { sid, jpeg, bounds });
  } catch (error) {
    log("exam surface: " + error.message);
  } finally {
    surfaceBusy = false;
  }
}
let pendingLaunch = "";
let portalView, portalSession;
let starting = false;
let pendingAttempt = null;
const pending = new Map();
const blockedAudit = new Map();
const desktopKey = crypto.randomBytes(32).toString("hex");
const demoPointer = path.join(app.getPath("userData"), "demo-launch.json");
const demoArgument = process.argv.find((x) => x.startsWith("--demo-config="));
const demoConfigPath =
  demoArgument?.slice("--demo-config=".length) ||
  process.env.SERGEK_DEMO_CONFIG ||
  (process.env.SERGEK_TESTING !== "1" && fs.existsSync(demoPointer)
    ? JSON.parse(fs.readFileSync(demoPointer, "utf8")).config
    : "");
const demoConfig = demoConfigPath
  ? JSON.parse(fs.readFileSync(demoConfigPath, "utf8"))
  : null;
const data =
  process.env.SERGEK_DATA ||
  demoConfig?.data ||
  (app.isPackaged ? app.getPath("userData") : path.join(root, "runtime"));
fs.mkdirSync(data, { recursive: true });
if (process.env.SERGEK_TESTING === "1") {
  const testProfile = path.join(data, "electron-test-profile");
  fs.mkdirSync(testProfile, { recursive: true });
  app.setPath("userData", testProfile);
}
function log(text) {
  fs.appendFileSync(
    path.join(data, "desktop.log"),
    new Date().toISOString() + " " + text + "\n",
  );
}
function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
async function api(route, method = "GET", body, student = false) {
  const response = await fetch(origin + route, {
    method,
    signal: AbortSignal.timeout(route.endsWith("/moodle-ready") ? 8000 : 12000),
    headers: {
      "Content-Type": "application/json",
      "x-sergek-desktop": desktopKey,
      ...(student && current
        ? { Authorization: "Bearer " + current.token }
        : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let detail;
    try {
      detail = (await response.json()).detail;
    } catch {
      detail = response.statusText;
    }
    const error = new Error(
      typeof detail === "string" ? detail : JSON.stringify(detail),
    );
    error.status = response.status;
    throw error;
  }
  return response.json();
}
function guardCommand(command, payload = {}) {
  if (!guard || guard.exitCode !== null)
    return Promise.resolve({
      available: false,
      error: "Windows guard executable unavailable",
    });
  const id = crypto.randomUUID();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error("Windows guard response timed out"));
    }, 12000);
    pending.set(id, { resolve, reject, timer });
    guard.stdin.write(JSON.stringify({ id, command, ...payload }) + "\n");
  });
}
async function record(kind, detail = {}) {
  if (current)
    try {
      await api(
        `/api/student/${current.session.id}/event`,
        "POST",
        { kind, detail },
        true,
      );
    } catch (error) {
      log(error.message);
    }
}
async function auditBlocked(action, detail = {}) {
  const sid = current?.session.id || "portal";
  const key = [sid, action, detail.host || "", detail.resource_type || ""].join(
    ":",
  );
  const now = Date.now();
  if (now - (blockedAudit.get(key) || 0) < 60000) return;
  if (blockedAudit.size >= 256) blockedAudit.clear();
  blockedAudit.set(key, now);
  try {
    await api("/api/desktop/audit", "POST", {
      action,
      detail: { ...detail, sid, blocked: true },
    });
  } catch (error) {
    log("audit: " + error.message);
  }
}
function urlHost(value) {
  try {
    return new URL(value).hostname;
  } catch {
    return "invalid";
  }
}
function startGuard() {
  const executable = app.isPackaged
    ? path.join(process.resourcesPath, "guard", "Sergek.Guard.exe")
    : path.join(root, "build", "guard", "Sergek.Guard.exe");
  if (!fs.existsSync(executable)) {
    guardState = { available: false, error: "Guard must be built" };
    return;
  }
  guard = spawn(executable, [], {
    windowsHide: true,
    env: { ...process.env, SERGEK_GUARD_DATA: data },
    stdio: ["pipe", "pipe", "pipe"],
  });
  readline.createInterface({ input: guard.stdout }).on("line", async (line) => {
    try {
      const message = JSON.parse(line);
      if (message.type === "response") {
        guardState = message.status;
        const task = pending.get(message.id);
        if (task) {
          clearTimeout(task.timer);
          pending.delete(message.id);
          task.resolve(message.status);
        }
      } else if (message.type === "event") {
        const fatal = [
          "emergency_release",
          "guard_lost",
          "application_close_failed",
          "remote_enforcement_failed",
          "storage_enforcement_failed",
          "protected_desktop_left",
        ].includes(message.kind);
        if (fatal) {
          guardFailure =
            {
              application_close_failed:
                message.detail?.reason === "launcher_owns_exam"
                  ? "Қосымшаны жұмыс үстеліндегі Sergек таныстыру таңбашасымен қайта ашыңыз"
                  : "Бөгде терезені жабу расталмады",
              guard_lost: "Windows қорғанысымен байланыс жоғалды",
              storage_enforcement_failed: "USB қолжетімділігі бұғатталмады",
              remote_enforcement_failed:
                "Қашықтан басқару қорғанысы расталмады",
              protected_desktop_left: "Windows жұмыс ортасы ауысты",
              emergency_release: "Апаттық шығу орындалды",
            }[message.kind] || message.kind;
          log(
            "guard failure: " +
              message.kind +
              " " +
              (message.detail?.name || message.detail?.reason || ""),
          );
        }
        await record(message.kind, message.detail);
        if (fatal) await interrupt(message.kind);
      } else if (message.error) log("guard: " + message.error);
    } catch (error) {
      log(error.message);
    }
  });
  guard.stderr.on("data", (value) => log("guard stderr: " + value));
  guard.on("error", (error) => {
    guardState = { available: false, error: error.message };
  });
  guard.on("exit", async (code) => {
    for (const task of pending.values()) {
      clearTimeout(task.timer);
      task.reject(new Error("Guard exited"));
    }
    pending.clear();
    guardState = { available: false, error: "Guard exited " + code };
    if (current?.session.status === "active")
      await interrupt("guard_process_exited");
  });
}
function layoutExam() {
  if ((!examView && !portalView) || !window) return;
  const { width, height } = window.getContentBounds();
  (examView || portalView).setBounds({
    x: 0,
    y: 76,
    width,
    height: Math.max(0, height - 76),
  });
}
function configureSession(isolated) {
  isolated.setCertificateVerifyProc((request, callback) => {
    const pin = profile.tls_pins?.[request.hostname];
    if (!pin) return callback(-3);
    try {
      const cert = new crypto.X509Certificate(request.certificate.data);
      const actual = cert.fingerprint256.replaceAll(":", "").toLowerCase();
      const valid =
        Date.parse(cert.validFrom) <= Date.now() &&
        Date.parse(cert.validTo) >= Date.now();
      callback(valid && pin.toLowerCase() === actual ? 0 : -2);
    } catch {
      callback(-2);
    }
  });
  isolated.setPermissionRequestHandler((_wc, _permission, callback) =>
    callback(false),
  );
  isolated.setPermissionCheckHandler(() => false);
}
function closePortal(clear = false) {
  if (portalView) {
    window.contentView.removeChildView(portalView);
    portalView.webContents.close();
    portalView = null;
  }
  if (clear) {
    const previous = portalSession;
    portalSession = null;
    previous?.clearStorageData().catch((error) => log(error.message));
  }
}
async function openPortal() {
  if (current) throw new Error("Алдыңғы сессияны аяқтаңыз");
  profile = await api("/api/profile");
  if (!allowedUrl(profile.moodle_url, profile.allowed_hosts))
    throw new Error("Moodle мекенжайын әкімші баптауы қажет");
  closePortal(true);
  window.webContents.send("sergek:launch", { portalAuthenticated: false });
  portalSession = session.fromPartition("sergek-portal-" + crypto.randomUUID());
  configureSession(portalSession);
  portalSession.webRequest.onBeforeRequest((details, callback) =>
    callback({
      cancel:
        !allowedUrl(details.url, profile.allowed_hosts, origin) &&
        !details.url.startsWith("data:"),
    }),
  );
  portalSession.on("will-download", (event) => event.preventDefault());
  portalView = new WebContentsView({
    webPreferences: {
      session: portalSession,
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
      devTools: false,
    },
  });
  const contents = portalView.webContents;
  contents.on("dom-ready", async () => {
    // A protected Moodle quiz supplies the signed launch link itself. Students
    // choose the quiz; the desktop completes the handoff without another form.
    if (current || portalView?.webContents !== contents) return;
    try {
      const pageUrl = new URL(contents.getURL());
      if (!allowedUrl(pageUrl.href, profile.allowed_hosts)) return;
      const authenticated = await contents.executeJavaScript(
        `Boolean(document.querySelector('a[href*="/login/logout.php"]')) && !Boolean(document.querySelector('body.notloggedin'))`,
      );
      if (!contents.isDestroyed() && portalView?.webContents === contents)
        window.webContents.send("sergek:launch", {
          portalAuthenticated: authenticated,
        });
      const target = await contents.executeJavaScript(`(() => {
        return document.querySelector('a[href^="sergek://launch?"]')?.href ||
          document.querySelector('a[href*="/mod/quiz/accessrule/sergek/launch.php?"]')?.href || null;
      })()`);
      if (!target || current || portalView?.webContents !== contents) return;
      if (target.startsWith("sergek://")) await acceptPortalLaunch(target);
      else {
        const launchUrl = new URL(target);
        if (
          launchUrl.origin === pageUrl.origin &&
          launchUrl.pathname.endsWith(
            "/mod/quiz/accessrule/sergek/launch.php",
          ) &&
          allowedUrl(launchUrl.href, profile.allowed_hosts)
        )
          await contents.loadURL(launchUrl.href);
      }
    } catch (error) {
      if (!contents.isDestroyed()) log("portal handoff: " + error.message);
    }
  });
  contents.on("will-navigate", (event, url) => {
    if (url.startsWith("sergek://")) {
      event.preventDefault();
      acceptPortalLaunch(url);
    } else if (!allowedUrl(url, profile.allowed_hosts)) event.preventDefault();
  });
  contents.on("will-redirect", (event, url) => {
    if (url.startsWith("sergek://")) {
      event.preventDefault();
      acceptPortalLaunch(url);
    } else if (!allowedUrl(url, profile.allowed_hosts)) event.preventDefault();
  });
  contents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("sergek://")) acceptPortalLaunch(url);
    else if (allowedUrl(url, profile.allowed_hosts))
      contents.loadURL(url).catch((error) => log(error.message));
    return { action: "deny" };
  });
  contents.on("did-fail-load", (_event, code, message, url, isMainFrame) => {
    if (isMainFrame && code !== -3)
      window.webContents.send("sergek:launch", {
        portalError: "Moodle ашылмады: " + message,
      });
  });
  window.contentView.addChildView(portalView);
  layoutExam();
  const loginUrl = new URL(profile.moodle_url);
  if (!loginUrl.pathname.includes("/login/")) {
    const basePath = loginUrl.pathname.endsWith("/")
      ? loginUrl.pathname
      : loginUrl.pathname.slice(0, loginUrl.pathname.lastIndexOf("/") + 1);
    loginUrl.pathname = basePath + "login/index.php";
    loginUrl.search = "";
    loginUrl.hash = "";
  }
  try {
    await contents.loadURL(loginUrl.href);
  } catch (error) {
    // A student can submit the login form before the first page finishes loading.
    // Chromium aborts that old navigation; the newer navigation must stay open.
    if (!String(error).includes("ERR_ABORTED")) {
      closePortal(true);
      throw error;
    }
  }
  return { ok: true };
}
async function acceptPortalLaunch(url) {
  try {
    if (current) return;
    const parsed = new URL(url);
    if (parsed.hostname !== "launch") return;
    const token = parsed.searchParams.get("token") || "";
    if (token.length > 12000) throw new Error("Жарамсыз Moodle сессиясы");
    await api("/api/desktop/resolve-launch", "POST", { token });
    closePortal(); // Keep the isolated Moodle login for the protected exam.
    handleLaunch(url);
  } catch (error) {
    window.webContents.send("sergek:launch", { portalError: error.message });
  }
}
async function activateProtection() {
  guardFailure = "";
  window.setContentProtection(true);
  const handle = window.getNativeWindowHandle();
  const hwnd =
    handle.length === 8
      ? Number(handle.readBigUInt64LE())
      : handle.readUInt32LE();
  guardState = await guardCommand("activate", {
    applications: profile.policy.close_applications,
    remote: profile.policy.remote_block,
    owner_pid: process.pid,
    trusted_pids: [process.pid, backend?.pid, guard?.pid].filter(Boolean),
    usb: profile.policy.usb_block,
    keyboard: profile.policy.keyboard_block,
    copy_paste: profile.policy.copy_paste,
    window: hwnd,
    forbidden: profile.policy.forbidden_processes,
  });
  return guardState;
}
function startProgress(message) {
  window?.webContents.send("sergek:launch", { startProgress: message });
}
async function loadExamPage(contents, url, options = {}) {
  let timer;
  try {
    await Promise.race([
      contents.loadURL(url, options),
      new Promise((_, reject) => {
        timer = setTimeout(() => {
          contents.stop();
          reject(new Error("Moodle бетін жүктеу уақыты бітті. Қайта көріңіз."));
        }, 15000);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}
async function openExam() {
  if (!current) return;
  const item = current.session;
  if (item.data.platform === "local") return;
  if (item.data.platform === "moodle") {
    const { waitForMoodle } = require("./moodle-ready.cjs");
    await waitForMoodle({
      alive: () =>
        current?.session.id === item.id &&
        ["preflight", "active"].includes(current.session.status) &&
        !guardFailure,
      probe: () =>
        api(`/api/student/${item.id}/moodle-ready`, "POST", {}, true),
    });
  }
  if (examView) {
    layoutExam();
    if (pendingAttempt && item.status === "active") {
      const navigation = pendingAttempt;
      pendingAttempt = null;
      await loadExamPage(examView.webContents, navigation.url, {
        postData: navigation.postData,
        ...(navigation.postData
          ? {
              extraHeaders:
                "Content-Type: application/x-www-form-urlencoded\r\n",
            }
          : {}),
      });
    }
    examView.setVisible(true);
    startProgress("");
    return;
  }
  const isolated =
    item.data.platform === "moodle" && portalSession
      ? portalSession
      : session.fromPartition("sergek-exam-" + item.id);
  isolated.setCertificateVerifyProc((request, callback) => {
    const pin = profile.tls_pins?.[request.hostname];
    if (!pin) {
      callback(-3);
      return;
    }
    try {
      const cert = new crypto.X509Certificate(request.certificate.data);
      const actual = cert.fingerprint256.replaceAll(":", "").toLowerCase();
      const valid =
        Date.parse(cert.validFrom) <= Date.now() &&
        Date.parse(cert.validTo) >= Date.now();
      callback(valid && pin.toLowerCase() === actual ? 0 : -2);
    } catch {
      callback(-2);
    }
  });
  isolated.setPermissionRequestHandler((_wc, _permission, callback) =>
    callback(false),
  );
  isolated.setPermissionCheckHandler(() => false);
  isolated.webRequest.onBeforeRequest((details, callback) => {
    const target = new URL(details.url);
    const selected = current?.session;
    const base = selected && new URL(selected.data.exam_url);
    if (
      selected?.data.platform === "moodle" &&
      selected.status === "preflight" &&
      target.origin === base.origin &&
      details.resourceType === "mainFrame" &&
      ((target.pathname ===
        base.pathname.replace(/view\.php$/, "startattempt.php") &&
        details.method === "POST") ||
        (target.pathname ===
          base.pathname.replace(/view\.php$/, "attempt.php") &&
          details.method === "GET"))
    ) {
      callback({ cancel: true });
      examView?.setVisible(false);
      startProgress("Емтихан қорғанысы қосылуда…");
      if (
        !starting &&
        (details.method === "GET" ||
          (details.uploadData?.length &&
            details.uploadData.every((p) => p.bytes && !p.file)))
      ) {
        pendingAttempt = {
          url: details.url,
          postData: details.uploadData?.map((p) => ({
            type: "rawData",
            bytes: p.bytes,
          })),
        };
        startCurrentExam().catch((error) => {
          pendingAttempt = null;
          log("Moodle start: " + error.message);
          startProgress("");
          window.webContents.send("sergek:launch", {
            startError: error.message,
          });
          examView?.setVisible(false);
        });
      }
      return;
    }
    const allowed =
      allowedUrl(details.url, profile.allowed_hosts, origin) ||
      details.url.startsWith("data:");
    if (!allowed)
      auditBlocked(
        details.resourceType === "mainFrame"
          ? "navigation_blocked"
          : "resource_blocked",
        {
          host: urlHost(details.url),
          resource_type: details.resourceType,
        },
      );
    callback({ cancel: !allowed });
  });
  isolated.on("will-download", (event) => {
    event.preventDefault();
    auditBlocked("download_blocked");
  });
  examView = new WebContentsView({
    webPreferences: {
      session: isolated,
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
      devTools: false,
    },
  });
  examView.setVisible(false);
  window.contentView.addChildView(examView);
  layoutExam();
  const contents = examView.webContents;
  contents.on("dom-ready", () => {
    // Also cover a site's print button and DOM clipboard actions, not just shortcuts.
    const disableClipboard = !profile.policy.copy_paste;
    contents
      .executeJavaScript(
        `(() => {
      try {
      if (window.print?.__sergekBlocked) return {ok:true};
      const blockedPrint = () => {};
      Object.defineProperty(blockedPrint, '__sergekBlocked', {value:true});
      Object.defineProperty(window, 'print', {value: blockedPrint, configurable: false, writable: false});
      if (${JSON.stringify(disableClipboard)}) {
        for (const kind of ['copy', 'cut', 'paste']) document.addEventListener(kind, event => {
          event.preventDefault(); event.stopImmediatePropagation();
        }, true);
      }
      return {ok:true};
      } catch(error) {return {ok:false,error:String(error)};}
    })()`,
      )
      .then((result) => {
        if (!result?.ok)
          throw new Error(
            result?.error || "Exam protection initialization failed",
          );
      })
      .catch((error) => {
        log(error.message);
        interrupt("exam_page_protection_failed");
      });
  });
  contents.setWindowOpenHandler(({ url }) => {
    auditBlocked("window_blocked", { host: urlHost(url) });
    return { action: "deny" };
  });
  contents.on("will-navigate", (event, url) => {
    if (!allowedUrl(url, profile.allowed_hosts)) {
      event.preventDefault();
      auditBlocked("navigation_blocked", { host: urlHost(url) });
    }
  });
  contents.on("will-redirect", (event, url) => {
    if (!allowedUrl(url, profile.allowed_hosts)) {
      event.preventDefault();
      auditBlocked("navigation_blocked", { host: urlHost(url) });
    }
  });
  contents.on("before-input-event", (event, input) => {
    if (blockedInput(input, profile.policy)) {
      event.preventDefault();
      if (input.type === "keyDown")
        record("shortcut_blocked", {
          key: input.key,
          scope: "exam_view",
          blocked: true,
        });
    }
  });
  contents.on("context-menu", (event) => event.preventDefault());
  contents.on("render-process-gone", (_, details) => {
    record("exam_renderer_crashed", details);
    interrupt("exam_renderer_crashed");
  });
  try {
    await loadExamPage(contents, item.data.exam_url);
  } catch (error) {
    window.contentView.removeChildView(examView);
    contents.close();
    examView = null;
    throw error;
  }
  examView?.setVisible(true);
  startProgress("");
}
async function releaseGuard() {
  try {
    await guardCommand("release");
  } catch (error) {
    log(error.message);
  }
  if (window && !window.isDestroyed()) {
    window.setKiosk(false);
    window.setContentProtection(false);
    window.setAlwaysOnTop(false);
  }
  pendingAttempt = null;
  if (examView) {
    examView.webContents.close();
    window?.contentView.removeChildView(examView);
    examView = null;
  }
}
async function interrupt(reason) {
  if (!current) return;
  const sid = current.session.id;
  try {
    await api("/api/desktop/interrupt", "POST", {
      sid,
      reason,
    });
    if (!current || current.session.id !== sid) return;
    const snapshot = await api(
      `/api/student/${current.session.id}/snapshot`,
      "GET",
      undefined,
      true,
    );
    lastSnapshot = {
      ...snapshot,
      guard: guardState,
      displays: screen.getAllDisplays().length,
    };
  } catch (error) {
    log(error.message);
  }
  await releaseGuard();
  closePortal(true);
  current = null;
}
async function startCurrentExam() {
  if (!current) throw new Error("No active session");
  const route = `/api/student/${current.session.id}`;
  if (starting || current.session.status !== "preflight")
    throw new Error("Емтихан іске қосылып жатыр немесе басталған");
  starting = true;
  const sid = current.session.id;
  try {
    const check = await api(route + "/snapshot", "GET", undefined, true);
    if (!current || current.session.id !== sid)
      throw new Error(guardFailure || "Сессия тоқтатылды");
    if (
      profile.policy.microphone_required &&
      (!check.status.microphone_running || check.status.microphone_error)
    )
      throw new Error(check.status.microphone_error || "Микрофонды қосыңыз");
    if (
      profile.policy.camera_required &&
      (!check.status.identity_enrolled ||
        check.signals.faces !== 1 ||
        check.signals.quality !== "good")
    )
      throw new Error("Алдымен камераға қарап, фотоға түсіңіз");
    if (profile.policy.single_monitor && screen.getAllDisplays().length !== 1)
      throw new Error("Емтихан үшін бір монитор қажет");
    // Confirm the server before applying Windows restrictions.
    if (current.session.data.platform === "moodle") {
      startProgress("Moodle байланысы тексерілуде…");
      const { waitForMoodle } = require("./moodle-ready.cjs");
      await waitForMoodle({
        alive: () => current?.session.id === sid,
        probe: () => api(route + "/moodle-ready", "POST", {}, true),
      });
    }
    startProgress("Қорғаныс қосылып, тест ашылуда…");
    const startAt = Date.now();
    const result = await startProtectedExam({
      strict: current.session.data.mode === "strict",
      protect: async () => window.setContentProtection(true),
      activate: activateProtection,
      probe: async () => {
        if (!current || current.session.id !== sid)
          throw new Error(guardFailure || "Сессия тоқтатылды");
        guardState = await guardCommand("probe", {
          forbidden: profile.policy.forbidden_processes,
        });
        return { ...guardState, error: guardFailure || guardState.error };
      },
      start: async (native) => {
        if (!current || current.session.id !== sid)
          throw new Error("Сессия тоқтатылды");
        current.session = await api(
          route + "/start",
          "POST",
          {
            guard: native,
            desktop: { displays: screen.getAllDisplays().length },
          },
          true,
        );
        return current.session;
      },
      open: async () => {
        if (!current || current.session.id !== sid)
          throw new Error(guardFailure || "Сессия тоқтатылды");
        if (current.session.data.mode === "strict") {
          window.setKiosk(true);
          window.setAlwaysOnTop(true);
        }
        await openExam();
        await record("session_started", {
          mode: current.session.data.mode,
          microphone_recording: profile.policy.microphone_required,
          screen_recording: profile.policy.screen_recording,
        });
      },
      release: releaseGuard,
      interrupt,
    });
    log(`exam ready: ${Date.now() - startAt} ms`);
    return result;
  } finally {
    starting = false;
  }
}

function validateSender(event) {
  if (
    !window ||
    event.sender !== window.webContents ||
    !event.senderFrame ||
    new URL(event.senderFrame.url).origin !== origin
  )
    throw new Error("Untrusted IPC sender");
}
ipcMain.handle("sergek:command", async (event, command, value) => {
  validateSender(event);
  if (command === "get-language") {
    try {
      const saved = JSON.parse(
        fs.readFileSync(path.join(data, "preferences.json"), "utf8"),
      );
      return {
        language: ["kk", "ru", "en"].includes(saved.language)
          ? saved.language
          : "kk",
      };
    } catch {
      return { language: null };
    }
  }
  if (command === "set-language") {
    if (!["kk", "ru", "en"].includes(value?.language))
      throw new Error("Invalid interface language");
    // UI preferences have a stable path even when the local backend port changes.
    const target = path.join(data, "preferences.json");
    fs.writeFileSync(
      target + ".tmp",
      JSON.stringify({ language: value.language }),
      "utf8",
    );
    fs.renameSync(target + ".tmp", target);
    return { ok: true };
  }
  if (command === "info")
    return {
      desktop: true,
      origin,
      platform: process.platform,
      guard: guardState,
      launch: pendingLaunch,
    };
  if (command === "open-portal") return openPortal();
  if (command === "close-portal") {
    closePortal(true);
    return { ok: true };
  }
  if (command === "setup")
    return api("/api/setup", "POST", { password: value.password });
  if (command === "resolve-launch") {
    const result = await api("/api/desktop/resolve-launch", "POST", value);
    closePortal();
    return result;
  }
  if (command === "open-dashboard") {
    if (current?.session.status === "active")
      throw new Error("Finish exam before opening dashboard");
    window.loadURL(origin + "/?role=teacher");
    return { ok: true };
  }
  if (command === "create") {
    if (current) throw new Error("Session already exists");
    current = await api("/api/sessions", "POST", value);
    lastSnapshot = null;
    profile = await api("/api/profile");
    guardState = await guardCommand("probe", {
      forbidden: profile.policy.forbidden_processes,
    });
    pendingLaunch = "";
    return current.session;
  }
  if (!current) {
    if (
      command === "snapshot" &&
      lastSnapshot &&
      ["completed", "interrupted"].includes(lastSnapshot.session.status)
    )
      return lastSnapshot;
    throw new Error("No active session");
  }
  const route = `/api/student/${current.session.id}`;
  if (command === "snapshot") {
    const result = await api(route + "/snapshot", "GET", undefined, true);
    lastSnapshot = {
      ...result,
      guard: guardState,
      displays: screen.getAllDisplays().length,
    };
    return lastSnapshot;
  }
  if (command === "calibrate")
    return api(route + "/calibrate", "POST", value, true);
  if (command === "enroll") return api(route + "/enroll", "POST", {}, true);
  if (command === "camera-stream") {
    const access = await api(route + "/camera-ticket", "POST", {}, true);
    return {
      url:
        origin +
        "/api/camera/stream?ticket=" +
        encodeURIComponent(access.ticket),
    };
  }
  if (command === "probe") {
    if (
      current.session.status === "preflight" &&
      profile.policy.microphone_required
    )
      await api(route + "/microphone/retry", "POST", {}, true);
    guardState = await guardCommand("probe", {
      forbidden: profile.policy.forbidden_processes,
    });
    return { guard: guardState, displays: screen.getAllDisplays().length };
  }
  if (command === "activate") {
    await api("/api/desktop/authorize", "POST", { password: value.password });
    await activateProtection();
    return { guard: guardState, displays: screen.getAllDisplays().length };
  }
  if (command === "start") {
    if (current.session.data.platform === "moodle") {
      await openExam();
      return current.session;
    }
    return startCurrentExam();
  }
  if (command === "exam") return api(route + "/exam", "GET", undefined, true);
  if (command === "answer") return api(route + "/answer", "PUT", value, true);
  if (command === "show-exam") {
    await openExam();
    return { ok: true };
  }
  if (command === "hide-exam") {
    if (current.session.status === "active")
      await api("/api/desktop/authorize", "POST", { password: value.password });
    examView?.setVisible(false);
    return { ok: true };
  }
  if (command === "finish") {
    const result = await api(route + "/finish", "POST", value, true);
    await releaseGuard();
    closePortal(true);
    current = null;
    return result;
  }
  throw new Error("Unsupported command");
});
async function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const port = server.address().port;
      server.close(() => resolve(port));
    });
  });
}
async function startBackend() {
  port = process.env.SERGEK_PORT
    ? Number(process.env.SERGEK_PORT)
    : await freePort();
  origin = `http://127.0.0.1:${port}`;
  const env = {
    ...process.env,
    SERGEK_VERSION: app.getVersion(),
    ...(demoConfig
      ? {
          SERGEK_DEMO_CONFIG: demoConfigPath,
          SERGEK_CA_FILE: demoConfig.ca_file,
        }
      : {}),
    SERGEK_DATA: data,
    SERGEK_DESKTOP_KEY: desktopKey,
    SERGEK_UI: app.isPackaged
      ? path.join(process.resourcesPath, "ui")
      : path.join(root, "dist"),
    SERGEK_MODELS: app.isPackaged
      ? path.join(process.resourcesPath, "models")
      : path.join(root, "models"),
  };
  const localPython = path.join(root, ".venv", "Scripts", "python.exe");
  const python =
    process.env.SERGEK_PYTHON ||
    (fs.existsSync(localPython)
      ? localPython
      : path.resolve(
          root,
          "..",
          "..",
          "work",
          "sergek-venv",
          "Scripts",
          "python.exe",
        ));
  const executable = app.isPackaged
    ? path.join(process.resourcesPath, "backend", "sergek-backend.exe")
    : python;
  const args = app.isPackaged
    ? ["--port", String(port)]
    : ["-m", "backend.run", "--port", String(port)];
  backend = spawn(executable, args, {
    cwd: app.isPackaged ? process.resourcesPath : root,
    windowsHide: true,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  backend.stdout.on("data", (value) => log("backend: " + value));
  backend.stderr.on("data", (value) => log("backend: " + value));
  backend.on("error", (error) => log(error.message));
  for (let attempt = 0; attempt < 120; attempt++) {
    if (backend.exitCode !== null)
      throw new Error("Backend stopped. See " + path.join(data, "desktop.log"));
    try {
      await api("/api/health");
      await api("/api/desktop/ping");
      return;
    } catch {}
    await delay(500);
  }
  throw new Error("Backend startup timed out");
}
function handleLaunch(value) {
  try {
    if (current) return;
    const url = new URL(value);
    if (url.protocol !== "sergek:" || url.hostname !== "launch") return;
    pendingLaunch = url.searchParams.get("token") || "";
    if (pendingLaunch.length > 12000) {
      pendingLaunch = "";
      return;
    }
    window?.webContents.send("sergek:launch", { token: pendingLaunch });
    window?.show();
  } catch {}
}
const locked = app.requestSingleInstanceLock();
if (!locked) app.quit();
else {
  if (process.env.SERGEK_TESTING !== "1")
    app.setAsDefaultProtocolClient("sergek");
  app.on("second-instance", (_, argv) => {
    const url = argv.find((x) => x.startsWith("sergek://"));
    if (url) handleLaunch(url);
    if (window) {
      if (window.isMinimized()) window.restore();
      window.show();
      window.focus();
    }
  });
  app.on("open-url", (event, url) => {
    event.preventDefault();
    handleLaunch(url);
  });
  app.whenReady().then(async () => {
    try {
      log(
        `startup: version=${app.getVersion()} pid=${process.pid} parent=${process.ppid}`,
      );
      await startBackend();
      startGuard();
      window = new BrowserWindow({
        width: 1380,
        height: 900,
        minWidth: 980,
        minHeight: 700,
        show: false,
        backgroundColor: "#f4f6fb",
        autoHideMenuBar: true,
        webPreferences: {
          preload: path.join(__dirname, "preload.cjs"),
          contextIsolation: true,
          nodeIntegration: false,
          sandbox: true,
          devTools: false,
        },
      });
      window.setMenu(null);
      window.on("resize", layoutExam);
      window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
      window.webContents.on("will-navigate", (event, url) => {
        if (new URL(url).origin !== origin) event.preventDefault();
      });
      window.webContents.on("before-input-event", (event, input) => {
        if (
          current?.session.status === "active" &&
          blockedInput(input, profile.policy)
        ) {
          event.preventDefault();
          if (input.type === "keyDown")
            record("shortcut_blocked", {
              key: input.key,
              scope: "local_exam",
              blocked: true,
            });
        }
      });
      window.on("blur", () => {
        if (current?.session.status !== "active") return;
        if (current.session.data.mode !== "strict") {
          record("focus_lost", { blocked: false });
          return;
        }
        setTimeout(() => {
          if (
            !window ||
            window.isDestroyed() ||
            current?.session.status !== "active"
          )
            return;
          window.focus();
          setTimeout(() => {
            if (
              !window ||
              window.isDestroyed() ||
              current?.session.status !== "active"
            )
              return;
            const restored = window.isFocused();
            record("focus_lost", {
              blocked: restored,
              action: "restore_exam_focus",
            });
            if (!restored) interrupt("cannot_restore_exam_focus");
          }, 200);
        }, 200);
      });
      screen.on("display-added", () =>
        record("display_changed", { displays: screen.getAllDisplays().length }),
      );
      screen.on("display-added", () => {
        if (
          current?.session.status === "active" &&
          current.session.data.mode === "strict" &&
          profile.policy.single_monitor
        )
          interrupt("additional_monitor_connected");
      });
      screen.on("display-removed", () =>
        record("display_changed", { displays: screen.getAllDisplays().length }),
      );
      window.on("close", (event) => {
        if (!exiting && current?.session.status === "active") {
          event.preventDefault();
          window.webContents.send("sergek:launch", { exitRequested: true });
        }
      });
      await window.loadURL(origin);
      window.show();
      surfaceTimer = setInterval(captureExamSurface, 400);
      // Native recovery lease is independent of camera/backend HTTP processing.
      guardHeartbeat = setInterval(async () => {
        if (!current || guardHeartbeatBusy) return;
        guardHeartbeatBusy = true;
        try {
          await guardCommand("heartbeat");
        } catch (error) {
          log("guard heartbeat: " + error.message);
          if (current?.session.status === "active" || starting)
            await interrupt("backend_or_guard_connection_lost");
        } finally {
          guardHeartbeatBusy = false;
        }
      }, 2000);
      const launch = process.argv.find((x) => x.startsWith("sergek://"));
      if (launch) handleLaunch(launch);
      heartbeat = setInterval(async () => {
        if (!current || heartbeatBusy) return;
        heartbeatBusy = true;
        const sid = current.session.id;
        try {
          const result = await api(
            `/api/student/${sid}/heartbeat`,
            "POST",
            {},
            true,
          );
          if (!current || current.session.id !== sid) return;
          if (["completed", "interrupted"].includes(result.status)) {
            const snapshot = await api(
              `/api/student/${current.session.id}/snapshot`,
              "GET",
              undefined,
              true,
            );
            lastSnapshot = {
              ...snapshot,
              guard: guardState,
              displays: screen.getAllDisplays().length,
            };
            if (!current || current.session.id !== sid) return;
            await releaseGuard();
            closePortal(true);
            current = null;
          }
        } catch (error) {
          log(error.message);
          if (current?.session.id === sid)
            await interrupt("backend_or_guard_connection_lost");
        } finally {
          heartbeatBusy = false;
        }
      }, 2000);
    } catch (error) {
      log(error.stack);
      const { dialog } = require("electron");
      dialog.showErrorBox("Sergek startup failed", error.message);
      app.quit();
    }
  });
  app.on("before-quit", () => {
    exiting = true;
    clearInterval(heartbeat);
    clearInterval(guardHeartbeat);
    clearInterval(surfaceTimer);
    guard?.stdin.end();
    backend?.kill();
  });
  app.on("window-all-closed", () => app.quit());
}
