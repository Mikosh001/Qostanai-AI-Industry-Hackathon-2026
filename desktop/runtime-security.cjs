// These checks run before configuration is read or any local service is started.
const forbiddenSwitch =
  /^(?:inspect(?:-.+)?|remote-debugging(?:-.+)?|no-sandbox|disable-web-security|disable-site-isolation-trials|ignore-certificate-errors(?:-.+)?|allow-file-access-from-files|load-extension|proxy-server|proxy-pac-url|proxy-bypass-list|js-flags|disable-features|user-data-dir|app|require|import|eval|interactive)$/i;
const injectionVariable =
  /^(?:NODE_(?:OPTIONS|EXTRA_CA_CERTS|TLS_REJECT_UNAUTHORIZED|USE_ENV_PROXY)|ELECTRON_RUN_AS_NODE|ELECTRON_NO_ASAR|PYTHON(?:HOME|PATH|STARTUP|INSPECT|BREAKPOINT)|DOTNET_(?:STARTUP_HOOKS|ADDITIONAL_DEPS|SHARED_STORE|MODIFIABLE_ASSEMBLIES)|(?:CORECLR|COR)_(?:ENABLE_PROFILING|PROFILER(?:_PATH(?:_32|_64)?)?)|COMPLUS_.+)$/i;
function startupViolations(argv, env, packaged) {
  if (!packaged) return [];
  const issues = [];
  for (const arg of argv) {
    if (typeof arg !== "string" || !arg.startsWith("--")) continue;
    const name = arg.slice(2).split("=", 1)[0];
    if (forbiddenSwitch.test(name)) issues.push("switch:" + name.toLowerCase());
  }
  for (const [name, value] of Object.entries(env))
    if (
      value &&
      (injectionVariable.test(name) || name.toUpperCase() === "SERGEK_TESTING")
    )
      issues.push("environment:" + name.toUpperCase());
  return issues;
}
function childEnvironment(env, additions = {}, packaged = true) {
  const clean = {};
  for (const [name, value] of Object.entries(env))
    if (
      !(packaged && injectionVariable.test(name)) &&
      !/^DOTNET_EnableDiagnostics/i.test(name)
    )
      clean[name] = value;
  return {
    ...clean,
    ...additions,
    DOTNET_EnableDiagnostics: "0",
    DOTNET_EnableDiagnostics_IPC: "0",
    DOTNET_EnableDiagnostics_Profiler: "0",
    DOTNET_EnableDiagnostics_Debugger: "0",
  };
}
function trustedFrame(event, contents, origin) {
  try {
    return (
      !!contents &&
      event.sender === contents &&
      event.senderFrame === contents.mainFrame &&
      new URL(event.senderFrame.url).origin === origin
    );
  } catch {
    return false;
  }
}
function validatePayload(command, value) {
  if (
    typeof command !== "string" ||
    command.length > 40 ||
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value)
  )
    throw Error("Invalid desktop request");
  if (Buffer.byteLength(JSON.stringify(value), "utf8") > 65536)
    throw Error("Desktop request too large");
}
module.exports = {
  startupViolations,
  childEnvironment,
  trustedFrame,
  validatePayload,
};
