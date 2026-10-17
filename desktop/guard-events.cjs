// Preparation can be retried after release. An active attempt must fail closed.
function shouldInterruptForGuardFailure(session) {
  return session?.status === "active";
}
module.exports = { shouldInterruptForGuardFailure };
