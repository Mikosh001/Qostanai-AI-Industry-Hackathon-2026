const test = require("node:test");
const assert = require("node:assert/strict");
const { allowedUrl, blockedInput } = require("../policy.cjs");
test("Exact HTTPS allowlist rejects credentials, subdomain suffix attacks and alternate ports", () => {
  const hosts = ["md.ksu.edu.kz"];
  assert.equal(allowedUrl("https://md.ksu.edu.kz/mod/quiz", hosts), true);
  for (const value of [
    "https://md.ksu.edu.kz.evil.example",
    "http://md.ksu.edu.kz",
    "https://user:pass@md.ksu.edu.kz",
    "https://md.ksu.edu.kz:8443",
    "javascript:alert(1)",
    "file:///C:/secret",
  ])
    assert.equal(allowedUrl(value, hosts), false, value);
});
test("Exam key filtering respects permitted copy and paste without allowing new tabs", () => {
  assert.equal(
    blockedInput({ key: "v", control: true }, { copy_paste: false }),
    true,
  );
  assert.equal(
    blockedInput({ key: "v", control: true }, { copy_paste: true }),
    false,
  );
  assert.equal(
    blockedInput({ key: "t", control: true }, { copy_paste: true }),
    true,
  );
  assert.equal(blockedInput({ key: "a" }, { copy_paste: false }), false);
});
