const { URL } = require("node:url");
function allowedUrl(value, hosts, localOrigin = "") {
  try {
    const url = new URL(value);
    if (url.username || url.password) return false;
    if (localOrigin && url.origin === localOrigin) return true;
    return (
      url.protocol === "https:" &&
      hosts.includes(url.hostname) &&
      (!url.port || url.port === "443")
    );
  } catch {
    return false;
  }
}
function blockedInput(input, policy) {
  const key = String(input.key || "").toLowerCase();
  if (input.control && input.alt && key === "f12") return false;
  if (["control", "shift", "alt", "meta"].includes(key)) return false;
  if (
    input.meta ||
    input.alt ||
    key === "escape" ||
    key === "printscreen" ||
    /^f\d{1,2}$/.test(key)
  )
    return true;
  if (input.control) {
    if (
      [
        "a",
        "z",
        "y",
        "arrowleft",
        "arrowright",
        "backspace",
        "delete",
      ].includes(key)
    )
      return false;
    if (policy.copy_paste && ["c", "v", "x"].includes(key)) return false;
    return true;
  }
  return false;
}
module.exports = { allowedUrl, blockedInput };
