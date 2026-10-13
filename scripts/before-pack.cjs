module.exports = async () => {
  const modulePath = require.resolve("./create-integrity-manifest.cjs");
  delete require.cache[modulePath];
  require(modulePath);
};
