const fs = require("node:fs/promises"),
  path = require("node:path"),
  crypto = require("node:crypto"),
  { createReadStream } = require("node:fs");
async function digest(file) {
  const hash = crypto.createHash("sha256");
  for await (const chunk of createReadStream(file)) hash.update(chunk);
  return hash.digest("hex");
}
async function verifyGuardBootstrap(resources, entries) {
  const expected = new Map(
    entries
      .filter((e) => typeof e.path === "string" && e.path.startsWith("guard/"))
      .map((e) => [e.path, e]),
  );
  if (
    !expected.has("guard/Sergek.Guard.exe") ||
    !expected.has("guard/Sergek.Guard.dll")
  )
    throw Error("Guard manifest incomplete");
  const actual = [];
  async function walk(folder, prefix) {
    const stat = await fs.lstat(folder);
    if (stat.isSymbolicLink()) throw Error("Linked guard folder");
    for (const name of await fs.readdir(folder)) {
      const file = path.join(folder, name),
        rel = prefix + name,
        s = await fs.lstat(file);
      if (s.isSymbolicLink()) throw Error("Linked guard file");
      if (s.isDirectory()) await walk(file, rel + "/");
      else if (s.isFile()) actual.push(rel);
      else throw Error("Invalid guard file");
    }
  }
  await walk(path.join(resources, "guard"), "guard/");
  if (
    actual.length !== expected.size ||
    actual.some((rel) => !expected.has(rel))
  )
    throw Error("Guard inventory changed");
  for (const rel of actual) {
    const entry = expected.get(rel),
      file = path.join(resources, ...rel.split("/"));
    if (
      (await fs.stat(file)).size !== entry.size ||
      (await digest(file)) !== entry.sha256
    )
      throw Error("Guard digest mismatch");
  }
  return { files: actual.length };
}
module.exports = { verifyGuardBootstrap };
