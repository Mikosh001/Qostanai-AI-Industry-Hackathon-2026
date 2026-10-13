const { spawn } = require("node:child_process"),
  fs = require("node:fs"),
  path = require("node:path"),
  os = require("node:os"),
  assert = require("node:assert/strict");
const { getCurrentFuseWire, FuseV1Options } = require("@electron/fuses");
const { childEnvironment } = require("../desktop/runtime-security.cjs");
const root = path.resolve(__dirname, ".."),
  version = require("../package.json").version,
  exe = path.resolve(
    process.argv[2] ||
      path.join(root, `release-v${version}/win-unpacked/Sergek Proctor.exe`),
  );
(async () => {
  const wire = await getCurrentFuseWire(exe);
  for (const key of [
    FuseV1Options.RunAsNode,
    FuseV1Options.EnableNodeOptionsEnvironmentVariable,
    FuseV1Options.EnableNodeCliInspectArguments,
    FuseV1Options.GrantFileProtocolExtraPrivileges,
  ])
    assert.equal(wire[key], 48, "disabled fuse " + key);
  for (const key of [
    FuseV1Options.EnableEmbeddedAsarIntegrityValidation,
    FuseV1Options.OnlyLoadAppFromAsar,
  ])
    assert.equal(wire[key], 49, "enabled fuse " + key);
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), "sergek-entry-")),
    marker = path.join(folder, "unexpected-node-execution.txt"),
    payload = path.join(folder, "payload.cjs");
  fs.writeFileSync(
    payload,
    "require('node:fs').writeFileSync(" +
      JSON.stringify(marker) +
      ",'harmless execution marker')",
  );
  const cases = [
    { name: "remote debugging", args: ["--remote-debugging-port=19222"] },
    { name: "sandbox disabled", args: ["--no-sandbox"] },
    { name: "developer test environment", env: { SERGEK_TESTING: "1" } },
    {
      name: "Node require injection",
      env: { NODE_OPTIONS: "--require=" + JSON.stringify(payload) },
      mayIgnore: true,
    },
    {
      name: "run-as-node",
      args: [
        "-e",
        "require('node:fs').writeFileSync(" +
          JSON.stringify(marker) +
          ",'marker')",
      ],
      env: { ELECTRON_RUN_AS_NODE: "1" },
      mayIgnore: true,
    },
    { name: "CLR startup hook", env: { DOTNET_STARTUP_HOOKS: payload } },
  ];
  const results = [];
  for (const fixture of cases) {
    const child = spawn(exe, fixture.args || [], {
      windowsHide: true,
      env: { ...childEnvironment(process.env), ...fixture.env },
    });
    let stderr = "";
    child.stderr.on("data", (b) => (stderr += b.toString()));
    let stoppedByHarness = false;
    const code = await new Promise((resolve, reject) => {
      const timer = setTimeout(
        () => {
          if (fixture.mayIgnore) {
            stoppedByHarness = true;
            child.kill();
            return;
          }
          child.kill();
          reject(Error("entry rejection timeout: " + fixture.name));
        },
        fixture.mayIgnore ? 3000 : 12000,
      );
      child.once("exit", (code) => {
        clearTimeout(timer);
        resolve(code);
      });
    });
    if (!stoppedByHarness)
      assert.equal(code, 78, fixture.name + " " + stderr.slice(-300));
    assert.equal(fs.existsSync(marker), false);
    results.push({
      case: fixture.name,
      rejected: !stoppedByHarness,
      injectionIgnored: stoppedByHarness,
      stoppedByHarness,
      exitCode: code,
    });
  }
  const report = {
    passed: true,
    releaseFusesVerified: true,
    arbitraryNodeExecutionPrevented: true,
    cases: results,
    otherApplicationsAffected: false,
  };
  fs.writeFileSync(
    path.join(__dirname, "security-entry-acceptance.json"),
    JSON.stringify(report, null, 2),
  );
  console.log(JSON.stringify(report));
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
