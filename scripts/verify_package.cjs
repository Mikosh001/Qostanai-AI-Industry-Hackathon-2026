const fs = require("node:fs"),
  path = require("node:path"),
  crypto = require("node:crypto"),
  assert = require("node:assert/strict");
const asar = require("@electron/asar");
const root = path.resolve(__dirname, ".."),
  version = require("../package.json").version;
const resources = path.resolve(
  process.argv[2] || path.join(root, `release-v${version}/win-unpacked`),
  "resources",
);
const digest = (bytes) =>
  crypto.createHash("sha256").update(bytes).digest("hex");
const checks = [];
for (const name of [
  "main.cjs",
  "focus-recovery.cjs",
  "start-flow.cjs",
  "policy.cjs",
  "navigation.cjs",
  "preload.cjs",
  "runtime-security.cjs",
  "bootstrap-integrity.cjs",
  "resource-manifest.json",
]) {
  const file = "desktop/" + name,
    expected = digest(fs.readFileSync(path.join(root, file))),
    actual = digest(asar.extractFile(path.join(resources, "app.asar"), file));
  assert.equal(actual, expected, file);
  checks.push(file);
}
assert.equal(
  JSON.parse(asar.extractFile(path.join(resources, "app.asar"), "package.json"))
    .version,
  version,
);
for (const [from, to] of [
  ["build/guard/Sergek.Guard.exe", "guard/Sergek.Guard.exe"],
  ["build/guard/Sergek.Guard.dll", "guard/Sergek.Guard.dll"],
  ["build/backend/sergek-backend.exe", "backend/sergek-backend.exe"],
  ["dist/index.html", "ui/index.html"],
  ...fs
    .readdirSync(path.join(root, "dist/assets"))
    .map((n) => ["dist/assets/" + n, "ui/assets/" + n]),
]) {
  assert.equal(
    digest(fs.readFileSync(path.join(root, from))),
    digest(fs.readFileSync(path.join(resources, to))),
    to,
  );
  checks.push(to);
}
// Compare every installed resource, not only entrypoints: NSIS extraction can
// omit individual libraries even when the installer itself exits successfully.
const manifest = JSON.parse(
  asar.extractFile(
    path.join(resources, "app.asar"),
    "desktop/resource-manifest.json",
  ),
);
const actual = [];
function inventory(folder) {
  for (const name of fs.readdirSync(folder)) {
    const file = path.join(folder, name),
      s = fs.lstatSync(file);
    assert(!s.isSymbolicLink(), "linked resource");
    if (s.isDirectory()) inventory(file);
    else actual.push(path.relative(resources, file).replaceAll("\\", "/"));
  }
}
for (const name of ["backend", "guard", "models", "ui"])
  inventory(path.join(resources, name));
assert.deepEqual(
  actual.sort(),
  manifest.files.map((e) => e.path).sort(),
  "complete installed resource inventory",
);
for (const e of manifest.files) {
  const bytes = fs.readFileSync(path.join(resources, e.path));
  assert.equal(bytes.length, e.size, e.path + " size");
  assert.equal(digest(bytes), e.sha256, e.path + " digest");
}
const result = {
  passed: true,
  version,
  scope: resources.startsWith(path.join(root, `release-v${version}`))
    ? "packaged application"
    : "installed application",
  resourceFiles: manifest.files.length,
  resourceBytes: manifest.files.reduce((n, e) => n + e.size, 0),
  checks,
};
fs.writeFileSync(
  process.argv[3] || path.join(root, "tests/session-repair-package.json"),
  JSON.stringify(result, null, 2),
);
console.log(JSON.stringify(result));
