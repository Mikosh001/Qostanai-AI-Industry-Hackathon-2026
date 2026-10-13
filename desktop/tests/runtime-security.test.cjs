const { test } = require("node:test"),
  assert = require("node:assert/strict");
const {
  startupViolations,
  childEnvironment,
  trustedFrame,
  validatePayload,
} = require("../runtime-security.cjs");
for (const name of [
  "inspect",
  "inspect-brk",
  "remote-debugging-port",
  "remote-debugging-pipe",
  "no-sandbox",
  "disable-web-security",
  "ignore-certificate-errors",
  "load-extension",
  "proxy-server",
  "js-flags",
  "disable-features",
  "user-data-dir",
  "app",
]) {
  test("Packaged startup rejects " + name, () =>
    assert.equal(
      startupViolations(["sergek.exe", "--" + name + "=fixture"], {}, true)
        .length,
      1,
    ),
  );
}
for (const name of [
  "NODE_OPTIONS",
  "NODE_EXTRA_CA_CERTS",
  "NODE_TLS_REJECT_UNAUTHORIZED",
  "ELECTRON_RUN_AS_NODE",
  "ELECTRON_NO_ASAR",
  "PYTHONSTARTUP",
  "DOTNET_STARTUP_HOOKS",
  "CORECLR_ENABLE_PROFILING",
  "COR_PROFILER_PATH",
  "COMPLUS_ReadyToRun",
  "SERGEK_TESTING",
]) {
  test("Packaged startup rejects inherited " + name, () =>
    assert.equal(startupViolations([], { [name]: "fixture" }, true).length, 1),
  );
}
test("Normal launch and permitted language arguments are accepted without leaking a launch token", () =>
  assert.deepEqual(
    startupViolations(
      ["sergek.exe", "--lang=ru", "sergek://launch?token=private"],
      { PATH: "system" },
      true,
    ),
    [],
  ));
test("Developer instrumentation is restricted to the unpackaged build", () =>
  assert.deepEqual(
    startupViolations(["--inspect=0"], { SERGEK_TESTING: "1" }, false),
    [],
  ));
test("Native/Python child processes do not inherit injection hooks or enabled diagnostics", () => {
  const clean = childEnvironment(
    {
      PATH: "system",
      DOTNET_STARTUP_HOOKS: "bad",
      CORECLR_ENABLE_PROFILING: "1",
      PYTHONPATH: "bad",
      NODE_OPTIONS: "bad",
      dotnet_EnableDiagnostics: "1",
    },
    { SERGEK_GUARD_DATA: "owned" },
  );
  assert.equal(clean.PATH, "system");
  assert.equal(clean.SERGEK_GUARD_DATA, "owned");
  for (const key of [
    "DOTNET_STARTUP_HOOKS",
    "CORECLR_ENABLE_PROFILING",
    "PYTHONPATH",
    "NODE_OPTIONS",
    "dotnet_EnableDiagnostics",
  ])
    assert.equal(clean[key], undefined);
  assert.equal(clean.DOTNET_EnableDiagnostics, "0");
});
test("Only the exact main frame of the trusted renderer may send desktop IPC", () => {
  const mainFrame = { url: "http://127.0.0.1:1234/" },
    contents = { mainFrame };
  assert(
    trustedFrame(
      { sender: contents, senderFrame: mainFrame },
      contents,
      "http://127.0.0.1:1234",
    ),
  );
  for (const event of [
    { sender: contents, senderFrame: { url: mainFrame.url } },
    { sender: {}, senderFrame: mainFrame },
    { sender: contents, senderFrame: { url: "https://localhost/" } },
    { sender: contents },
  ])
    assert(!trustedFrame(event, contents, "http://127.0.0.1:1234"));
});
test("IPC rejects invalid and oversized payloads", () => {
  validatePayload("create", { token: "x".repeat(12000) });
  for (const payload of [null, [], "string", { huge: "x".repeat(65537) }])
    assert.throws(() => validatePayload("create", payload));
  assert.throws(() => validatePayload({}, {}));
});
