// Real Electron HWND / owned windows + real native foreground IPC.
// No USB/service policies, keyboard hooks or closure of other applications.
const { _electron: electron, expect } = require("@playwright/test");
const { spawn } = require("node:child_process");
const fs = require("node:fs"),
  path = require("node:path"),
  os = require("node:os");
const assert = require("node:assert/strict");
const { createFocusRecovery } = require("../desktop/focus-recovery.cjs");
(async () => {
  const root = path.resolve(__dirname, ".."),
    data = fs.mkdtempSync(path.join(os.tmpdir(), "sergek-focus-"));
  const fixture = path.join(data, "fixture.cjs");
  fs.writeFileSync(
    fixture,
    `const {app,BrowserWindow,WebContentsView}=require('electron');app.whenReady().then(async()=>{global.main=new BrowserWindow({width:450,height:240,show:true});main.setAlwaysOnTop(true,'screen-saver');global.view=new WebContentsView();main.contentView.addChildView(view);view.setBounds({x:0,y:0,width:450,height:240});await view.webContents.loadURL('data:text/html,<h1>Isolated Sergек focus test</h1>');main.focus();view.webContents.focus();});app.on('window-all-closed',()=>app.quit());`,
  );
  const app = await electron.launch({
    args: [fixture],
    cwd: root,
    timeout: 30000,
  });
  let external, heartbeat;
  const child = spawn(path.join(root, "build/guard/Sergek.Guard.exe"), [], {
    windowsHide: true,
    env: { ...process.env, SERGEK_GUARD_DATA: path.join(data, "guard") },
  });
  let buffer = "",
    serial = 0;
  const pending = new Map();
  let ready;
  const started = new Promise((resolve, reject) => {
    ready = resolve;
    child.on("error", reject);
  });
  child.stdout.on("data", (chunk) => {
    buffer += chunk;
    let p;
    while ((p = buffer.indexOf("\n")) >= 0) {
      const m = JSON.parse(buffer.slice(0, p));
      buffer = buffer.slice(p + 1);
      if (m.type === "ready") ready();
      if (m.id && pending.has(m.id)) {
        pending.get(m.id)(m.status);
        pending.delete(m.id);
      }
    }
  });
  function command(command, extra = {}) {
    return new Promise((resolve, reject) => {
      const id = String(++serial),
        timer = setTimeout(() => {
          pending.delete(id);
          reject(Error("native IPC timeout"));
        }, 4000);
      pending.set(id, (s) => {
        clearTimeout(timer);
        resolve(s);
      });
      child.stdin.write(JSON.stringify({ id, command, ...extra }) + "\n");
    });
  }
  try {
    await started;
    await app.firstWindow();
    const target = await app.evaluate(() => {
      const h = main.getNativeWindowHandle();
      return { window: Number(h.readBigUInt64LE()), owner_pid: process.pid };
    });
    await command("activate", {
      ...target,
      applications: false,
      usb: false,
      keyboard: false,
      remote: false,
      forbidden: [],
      trusted_pids: [target.owner_pid, child.pid],
    });
    heartbeat = setInterval(() => command("heartbeat").catch(() => {}), 2000);
    await expect
      .poll(
        async () => {
          await app.evaluate(() => {
            main.show();
            main.focus();
            view.webContents.focus();
          });
          return (await command("foreground")).exam_foreground;
        },
        { timeout: 8000 },
      )
      .toBe(true);
    const ownView = await command("foreground");
    assert.equal(ownView.exam_foreground, true);
    await app.evaluate(async ({ BrowserWindow }) => {
      global.owned = new BrowserWindow({
        parent: main,
        modal: true,
        width: 350,
        height: 200,
        show: true,
      });
      await owned.loadURL("data:text/html,Owned dialog");
      owned.setAlwaysOnTop(true, "screen-saver");
      owned.focus();
    });
    await expect
      .poll(async () => {
        await app.evaluate(() => owned.focus());
        return (await command("foreground")).exam_foreground;
      })
      .toBe(true);
    const electronFocused = await app.evaluate(() => main.isFocused());
    assert.equal(
      electronFocused,
      false,
      "fixture reproduces false BrowserWindow focus",
    );
    const interruptions = [];
    const recovery = createFocusRecovery({
      read: () => command("foreground"),
      restore: async () => app.evaluate(() => owned.focus()),
      record: async () => {},
      interrupt: async (reason) => interruptions.push(reason),
    });
    let samples = 0;
    const requiredSamples = 8, sampleDeadline = Date.now() + 30000;
    while (samples < requiredSamples && Date.now() < sampleDeadline) {
      await app.evaluate(() => owned.focus());
      // This fixture deliberately leaves the user's desktop unprotected. If
      // the user focuses Codex/another app, that is a real foreign foreground,
      // not an Electron false-blur case. Sample only the intended precondition.
      if (!(await command("foreground")).exam_foreground) {
        await new Promise((resolve) => setTimeout(resolve, 250));
        continue;
      }
      await recovery.check(
        { id: "fixture", strict: true, starting: false },
        () => true,
      );
      assert.deepEqual(
        interruptions,
        [],
        JSON.stringify(await command("foreground")),
      );
      samples++;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    assert.equal(samples,requiredSamples,'inconclusive: the user desktop held foreground; own-window observations unavailable');
    assert.equal(
      interruptions.length,
      0,
      "owned foreground must not terminate exam",
    );
    // A different process using the very same Electron executable must remain
    // untrusted. This represents Chrome/Edge without touching the user's browser.
    await app.evaluate(() => {owned.close();main.setAlwaysOnTop(false);});
    external = await electron.launch({
      args: [fixture],
      cwd: root,
      timeout: 30000,
    });
    await external.firstWindow();
    const externalPid = await external.evaluate(() => process.pid);
    assert.notEqual(externalPid, target.owner_pid);
    await expect
      .poll(async () => {
        await external.evaluate(() => main.focus());
        return (await command("foreground")).exam_foreground;
      })
      .toBe(false);
    await external.close();
    external = null;
    await app.evaluate(() => {
      main.focus();
      view.webContents.focus();
    });
    await expect
      .poll(async () => {
        await app.evaluate(() => main.focus());
        return (await command("foreground")).exam_foreground;
      })
      .toBe(true);
    const report = {
      passed: true,
      realElectronWebContentsView: true,
      ownedModalElectronFocusFalse: true,
      nativeOwnWindowAccepted: true,
      ownedForegroundSamples: samples,
      minimumSampleIntervalMs: 250,
      sameExecutableDifferentProcessRejected: true,
      globalRestrictions: false,
      otherApplicationsClosed: false,
    };
    fs.writeFileSync(
      path.join(__dirname, "focus-native-acceptance.json"),
      JSON.stringify(report, null, 2),
    );
    console.log(JSON.stringify(report));
  } finally {
    clearInterval(heartbeat);
    await command("shutdown").catch(() => {});
    child.stdin.end();
    if (child.exitCode === null) child.kill();
    if (external) await external.close();
    await app.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
