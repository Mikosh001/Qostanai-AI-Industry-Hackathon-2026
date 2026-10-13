const fs = require("node:fs"),
  path = require("node:path"),
  crypto = require("node:crypto");
const root = path.resolve(__dirname, ".."),
  entries = [];
function walk(folder, prefix) {
  for (const name of fs.readdirSync(folder).sort()) {
    const file = path.join(folder, name),
      rel = prefix + name,
      stat = fs.lstatSync(file);
    if (rel === "guard/runtime") continue;
    // The Windows x64 package never loads ARM64 PortAudio. Keep inventory
    // identical to extraResources; older NSIS extractors omit these PE files.
    if (
      /^backend\/_internal\/_sounddevice_data\/portaudio-binaries\/libportaudioarm64(?:-asio)?\.dll$/.test(
        rel,
      )
    )
      continue;
    if (stat.isSymbolicLink()) throw Error("Linked build input: " + rel);
    if (stat.isDirectory()) walk(file, rel + "/");
    else if (stat.isFile())
      entries.push({
        path: rel,
        size: stat.size,
        sha256: crypto
          .createHash("sha256")
          .update(fs.readFileSync(file))
          .digest("hex"),
      });
    else throw Error("Unsupported build input: " + rel);
  }
}
for (const [folder, prefix] of [
  ["build/backend", "backend/"],
  ["build/guard", "guard/"],
  ["dist", "ui/"],
  ["models", "models/"],
])
  walk(path.join(root, folder), prefix);
const result = {
  schema: 1,
  files: entries.sort((a, b) => a.path.localeCompare(b.path, "en")),
};
fs.writeFileSync(
  path.join(root, "desktop/resource-manifest.json"),
  JSON.stringify(result),
);
console.log(
  JSON.stringify({
    files: entries.length,
    bytes: entries.reduce((n, e) => n + e.size, 0),
  }),
);
