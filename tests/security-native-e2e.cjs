// Real Defender + real Windows file locks. No user apps are closed, no USB,
// keyboard, touchpad or remote policies are applied. Run against a build copy.
const { spawn } = require("node:child_process"),
  fs = require("node:fs"),
  path = require("node:path"),
  os = require("node:os"),
  assert = require("node:assert/strict");
const asar = require("@electron/asar");
const { childEnvironment } = require("../desktop/runtime-security.cjs");
const root = path.resolve(__dirname, ".."),
  version = require("../package.json").version;
const resources = path.resolve(
  process.argv[2] || path.join(root, `release-v${version}/win-unpacked`),
  "resources",
);
const manifest = JSON.parse(
  asar.extractFile(
    path.join(resources, "app.asar"),
    "desktop/resource-manifest.json",
  ),
);
const data = fs.mkdtempSync(path.join(os.tmpdir(), "sergek-security-ipc-")),
  events = [],
  latencies = [];
const child = spawn(path.join(resources, "guard/Sergek.Guard.exe"), [], {
  windowsHide: true,
  env: childEnvironment(process.env, { SERGEK_GUARD_DATA: data }),
});
let buffer = "",
  serial = 0,
  resolveReady;
const pending = new Map();
const ready = new Promise((r) => (resolveReady = r)),
  exited = new Promise((r) => child.once("exit", r));
child.stdout.on("data", (chunk) => {
  buffer += chunk;
  let end;
  while ((end = buffer.indexOf("\n")) >= 0) {
    const m = JSON.parse(buffer.slice(0, end));
    buffer = buffer.slice(end + 1);
    if (m.type === "ready") resolveReady();
    if (m.type === "event") events.push(m);
    if (m.id && pending.has(m.id)) {
      pending.get(m.id)(m.status);
      pending.delete(m.id);
    }
  }
});
const delay = (ms) => new Promise((r) => setTimeout(r, ms));
function send(command, extra = {}) {
  return new Promise((resolve, reject) => {
    const id = String(++serial),
      timer = setTimeout(() => {
        pending.delete(id);
        reject(Error("native IPC timeout"));
      }, 10000);
    pending.set(id, (s) => {
      clearTimeout(timer);
      resolve(s);
    });
    child.stdin.write(JSON.stringify({ id, command, ...extra }) + "\n");
  });
}
async function waitFor(test, seconds) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    const s = await send("probe");
    if (test(s)) return s;
    await delay(200);
  }
  throw Error("native condition timeout");
}
(async () => {
  let heartbeat, extra;
  try {
    await Promise.race([
      ready,
      delay(10000).then(() => {
        throw Error("native startup timeout");
      }),
    ]);
    const av = await waitFor((s) => s.antimalware?.ready === true, 15);
    await send("verify-resources", { entries: manifest.files });
    const verified = await waitFor(
      (s) => s.package_integrity?.ready === true,
      60,
    );
    assert.equal(verified.package_integrity.files, manifest.files.length);
    const sample = manifest.files.find(
      (e) => e.path.startsWith("ui/assets/") && e.path.endsWith(".js"),
    );
    let denied = false;
    try {
      const fd = fs.openSync(path.join(resources, sample.path), "r+");
      fs.closeSync(fd);
    } catch (e) {
      denied = ["EPERM", "EBUSY", "EACCES"].includes(e.code);
    }
    assert(denied, "verified code must not be openable for writes");
    await send("scan-antimalware");
    assert.equal((await send("monitor")).active, true);
    heartbeat = setInterval(() => send("heartbeat").catch(() => {}), 1000);
    // Twenty readiness requests per second while Defender and WMI work separately.
    for (let i = 0; i < 250; i++) {
      const t = Date.now();
      const s = await send("probe");
      latencies.push(Date.now() - t);
      assert.equal(s.active, true);
      await delay(Math.max(0, 50 - (Date.now() - t)));
    }
    const scanned = await waitFor(
      (s) => s.antimalware?.scan?.state !== "running",
      180,
    );
    assert.equal(
      scanned.antimalware.scan.state,
      "clean",
      JSON.stringify(scanned.antimalware.scan),
    );
    await send("release");
    const protectedState = await send("activate", {
      applications: false,
      remote: false,
      usb: false,
      keyboard: false,
      antimalware: true,
      package_integrity: true,
      owner_pid: process.pid,
      trusted_pids: [process.pid, child.pid],
      forbidden: [],
    });
    assert.equal(protectedState.active, true, protectedState.error);
    // Only this build directory gets a harmless added text fixture, then cleanup.
    extra = path.join(resources, "ui/security-inventory-fixture.txt");
    assert(!fs.existsSync(extra));
    fs.writeFileSync(extra, "harmless owned inventory test");
    await waitFor(
      (s) => s.active === false && s.package_integrity?.ready === false,
      20,
    );
    assert(events.some((e) => e.kind === "package_integrity_lost"));
    fs.unlinkSync(extra);
    extra = null;
    await send("shutdown");
    child.stdin.end();
    await exited;
    const sorted = [...latencies].sort((a, b) => a - b),
      p95 = sorted[Math.floor(sorted.length * 0.95)];
    assert(p95 < 500, "native readiness p95 must stay below 500 ms");
    const result = {
      passed: true,
      windowsBuild: os.release(),
      resourceFiles: manifest.files.length,
      resourceVerificationMs: verified.package_integrity.duration_ms,
      fileWriteDenied: true,
      unexpectedFileReleasedGuard: true,
      defender: {
        ready: av.antimalware.ready,
        tamperProtected: av.antimalware.tamper_protected,
        signatureAgeDays: av.antimalware.signature_age_days,
        activeThreats: av.antimalware.active_threats,
        scan: scanned.antimalware.scan,
      },
      ipc: {
        requests: latencies.length,
        p95Ms: p95,
        maxMs: sorted.at(-1),
        leaseSurvived: true,
      },
      otherApplicationsClosed: false,
      usbKeyboardRemotePolicies: false,
      malwareSamplesUsed: false,
    };
    fs.writeFileSync(
      path.join(__dirname, "security-native-acceptance.json"),
      JSON.stringify(result, null, 2),
    );
    console.log(JSON.stringify(result));
  } finally {
    clearInterval(heartbeat);
    if (extra && fs.existsSync(extra)) fs.unlinkSync(extra);
    child.stdin.end();
    if (child.exitCode === null) await Promise.race([exited, delay(5000)]);
    if (child.exitCode === null) child.kill();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
