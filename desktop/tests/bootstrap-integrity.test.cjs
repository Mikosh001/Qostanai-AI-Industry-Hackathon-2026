const { test } = require("node:test"),
  assert = require("node:assert/strict"),
  fs = require("node:fs/promises"),
  path = require("node:path"),
  os = require("node:os"),
  crypto = require("node:crypto");
const { verifyGuardBootstrap } = require("../bootstrap-integrity.cjs");
async function fixture() {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "sergek-bootstrap-"));
  await fs.mkdir(path.join(root, "guard"));
  const entries = [];
  for (const name of ["Sergek.Guard.exe", "Sergek.Guard.dll", "coreclr.dll"]) {
    const data = Buffer.from("own harmless fixture " + name);
    await fs.writeFile(path.join(root, "guard", name), data);
    entries.push({
      path: "guard/" + name,
      size: data.length,
      sha256: crypto.createHash("sha256").update(data).digest("hex"),
    });
  }
  return { root, entries };
}
test("The entire native guard bootstrap is verified before any helper is executed", async () => {
  const f = await fixture();
  assert.equal((await verifyGuardBootstrap(f.root, f.entries)).files, 3);
});
test("A replaced native runtime library is rejected before launch", async () => {
  const f = await fixture();
  await fs.writeFile(path.join(f.root, "guard/coreclr.dll"), "changed");
  await assert.rejects(
    () => verifyGuardBootstrap(f.root, f.entries),
    /mismatch/,
  );
});
test("An unlisted helper library is rejected before launch", async () => {
  const f = await fixture();
  await fs.writeFile(path.join(f.root, "guard/unlisted.dll"), "harmless");
  await assert.rejects(
    () => verifyGuardBootstrap(f.root, f.entries),
    /inventory/,
  );
});
test("A manifest missing its entry executable cannot establish helper trust", async () => {
  const f = await fixture();
  await assert.rejects(
    () => verifyGuardBootstrap(f.root, f.entries.slice(1)),
    /incomplete/,
  );
});
