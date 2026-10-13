// Opt-in real Windows test. Only the guard's keyboard/touchpad restrictions are
// exercised. Never closes other applications or changes USB/remote policies.
const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs"),
  os = require("node:os"),
  path = require("node:path");
const assert = require("node:assert/strict");
const exe =
  process.env.SERGEK_GUARD_EXE ||
  path.resolve(__dirname, "../build/guard/Sergek.Guard.exe");
const delay = (ms) => new Promise((r) => setTimeout(r, ms));
const globalJournal=path.join(process.env.LOCALAPPDATA,"Sergek Proctor","gesture-recovery.json");
function snapshot() {
  const r = spawnSync(exe, ["--probe-gestures"], {
    windowsHide: true,
    encoding: "utf8",
    timeout: 10000,
  });
  assert.equal(r.status, 0, r.stderr || r.stdout);
  const s = JSON.parse(r.stdout.trim());
  assert.equal(s.passed, true);
  return s.settings;
}
async function cycle(eof) {
  const data = fs.mkdtempSync(path.join(os.tmpdir(), "sergek-touchpad-ipc-"));
  const child = spawn(exe, [], {
    windowsHide: true,
    env: { ...process.env, SERGEK_GUARD_DATA: data },
  });
  const tasks = new Map();
  let serial = 0,
    buffer = "",
    resolveReady;
  const ready = new Promise((r) => (resolveReady = r));
  const exited = new Promise((r) => child.once("exit", r));
  child.stdout.on("data", (chunk) => {
    buffer += chunk;
    let end;
    while ((end = buffer.indexOf("\n")) >= 0) {
      const m = JSON.parse(buffer.slice(0, end));
      buffer = buffer.slice(end + 1);
      if (m.type === "ready") resolveReady();
      if (m.id && tasks.has(m.id)) {
        tasks.get(m.id)(m.status);
        tasks.delete(m.id);
      }
    }
  });
  function send(command, extra = {}) {
    return new Promise((resolve, reject) => {
      const id = String(++serial),
        timer = setTimeout(
          () => reject(Error("Guard IPC timeout: " + command)),
          10000,
        );
      tasks.set(id, (s) => {
        clearTimeout(timer);
        resolve(s);
      });
      child.stdin.write(JSON.stringify({ id, command, ...extra }) + "\n");
    });
  }
  try {
    await Promise.race([
      ready,
      delay(10000).then(() => {
        throw Error("Guard startup timeout");
      }),
    ]);
    assert.equal((await send("probe")).gestures_enforced, false);
    const t = Date.now();
    const active = await send("activate", {
      keyboard: true,
      usb: false,
      applications: false,
      remote: false,
      window: 0,
      owner_pid: process.pid,
      trusted_pids: [process.pid, child.pid],
      forbidden: [],
    });
    assert.equal(active.active, true, active.error);
    assert.equal(active.keyboard_enforced, true);
    assert.equal(active.gestures_enforced, true);
    assert.equal(fs.existsSync(globalJournal),true);
    const activationMs = Date.now() - t;
    assert(snapshot().every((s) => s.registry === 0 && s.live === 0));
    // A second profile must not restore or overwrite the first exam's policy.
    const other = spawnSync(exe, [], {
      windowsHide: true,
      encoding: "utf8",
      timeout: 10000,
      env: {
        ...process.env,
        SERGEK_GUARD_DATA: fs.mkdtempSync(
          path.join(os.tmpdir(), "sergek-touchpad-other-"),
        ),
      },
      input:
        JSON.stringify({
          id: "other",
          command: "activate",
          keyboard: true,
          usb: false,
          applications: false,
          remote: false,
          forbidden: [],
        }) +
        "\n" +
        JSON.stringify({ id: "stop", command: "shutdown" }) +
        "\n",
    });
    assert.equal(other.status, 0, other.stderr || other.stdout);
    const rejected = other.stdout
      .trim()
      .split(/\r?\n/)
      .map((s) => JSON.parse(s))
      .find((s) => s.id === "other");
    assert.equal(rejected?.status.active, false);
    assert(snapshot().every((s) => s.registry === 0 && s.live === 0));
    await delay(1200);
    const kept = await send("heartbeat");
    assert.equal(kept.active, true);
    assert.equal(kept.gestures_enforced, true);
    if (eof) child.stdin.end();
    else {
      assert.equal((await send("release")).gestures_enforced, false);
      await send("shutdown");
      child.stdin.end();
    }
    await Promise.race([
      exited,
      delay(10000).then(() => {
        throw Error("Guard shutdown timeout");
      }),
    ]);
    assert.equal(
      fs.existsSync(globalJournal),
      false,
    );
    return {
      exit: eof ? "stdin EOF" : "explicit release",
      activationMs,
      keyboardAndLiveGesturesVerified: true,
      secondHelperRejectedWithoutRestoringActivePolicy: true,
    };
  } finally {
    // EOF is the ordinary recovery path if an assertion fails after activation.
    child.stdin.end();
    if (child.exitCode === null) await Promise.race([exited, delay(5000)]);
    if (child.exitCode === null) child.kill();
  }
}
(async () => {
  const before = snapshot();
  const cycles = [];
  for (const eof of [false, true]) {
    cycles.push(await cycle(eof));
    assert.deepEqual(snapshot(), before);
  }
  const result = {
    passed: true,
    windowsBuild: os.release(),
    cycles,
    originalSettingsRestored: true,
    globalApplicationClosure: false,
    usbOrRemoteRestrictions: false,
    physicalSwipeTest: false,
  };
  fs.writeFileSync(
    process.env.SERGEK_TOUCHPAD_RESULT ||
      path.join(__dirname, "touchpad-ipc-acceptance.json"),
    JSON.stringify(result, null, 2),
  );
  console.log(JSON.stringify(result));
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
