// Exercise the real helper lease in monitor mode. No hooks, registry or other apps are changed.
const { spawn, spawnSync } = require("node:child_process");
const { mkdtempSync, writeFileSync } = require("node:fs");
const { tmpdir } = require("node:os");
const path = require("node:path");
const assert = require("node:assert/strict");
const root = path.resolve(__dirname, "..");
const exe =
  process.env.SERGEK_GUARD_EXE ||
  path.join(root, "build/guard/Sergek.Guard.exe");
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
(async () => {
  for (const flag of [
    "--self-test",
    "--self-test-windows",
    "--self-test-close",
  ]) {
    const result = spawnSync(exe, [flag], {
      windowsHide: true,
      encoding: "utf8",
      timeout: 30000,
    });
    assert.equal(result.status, 0, result.stderr || result.stdout);
  }
  const data = mkdtempSync(path.join(tmpdir(), "sergek-guard-lease-"));
  const child = spawn(exe, [], {
    windowsHide: true,
    env: { ...process.env, SERGEK_GUARD_DATA: data },
  });
  const pending = new Map(),
    events = [];
  let buffer = "",
    serial = 0;
  const ready = new Promise((resolve, reject) => {
    child.on("error", reject);
    child.stdout.on("data", (chunk) => {
      buffer += chunk;
      let pos;
      while ((pos = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, pos).trim();
        buffer = buffer.slice(pos + 1);
        if (!line) continue;
        const message = JSON.parse(line);
        if (message.type === "ready") resolve(message);
        if (message.type === "event") events.push(message);
        if (message.id && pending.has(message.id)) {
          pending.get(message.id)(message);
          pending.delete(message.id);
        }
      }
    });
  });
  function send(command) {
    const id = String(++serial);
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(new Error("Guard IPC timeout: " + command));
      }, 3000);
      pending.set(id, (result) => {
        clearTimeout(timer);
        resolve(result.status);
      });
      child.stdin.write(JSON.stringify({ command, id, forbidden: [] }) + "\n");
    });
  }
  try {
    await Promise.race([
      ready,
      delay(5000).then(() => {
        throw new Error("Guard did not start");
      }),
    ]);
    assert.equal((await send("monitor")).active, true);
    for (let i = 0; i < 7; i++) {
      await delay(2000);
      assert.equal((await send("heartbeat")).active, true);
    }
    for (let i = 0; i < 12; i++) {
      await delay(1000);
      if (!(await send("probe")).active) break;
    }
    assert.equal((await send("probe")).active, false);
    assert(
      events.some(
        (e) =>
          e.kind === "guard_lost" &&
          e.detail.reason === "lease_expired" &&
          e.detail.restrictions_released,
      ),
    );
    for (let i = 0; i < 2; i++)
      assert.equal((await send("release")).active, false);
    await send("shutdown");
    child.stdin.end();
    const report = {
      passed: true,
      nativeSelfTests: true,
      heartbeatsKeptLeaseBeyond10Seconds: true,
      probeDidNotRenewLease: true,
      leaseExpiredAndReleased: true,
      releaseIdempotent: true,
      globalRestrictions: false,
    };
    writeFileSync(
      path.join(__dirname, "guard-acceptance.json"),
      JSON.stringify(report, null, 2),
    );
    console.log(JSON.stringify(report));
  } finally {
    child.stdin.end();
    if (child.exitCode === null) child.kill();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
