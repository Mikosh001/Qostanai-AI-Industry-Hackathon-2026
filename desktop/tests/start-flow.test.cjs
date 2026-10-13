const { test } = require("node:test");
const assert = require("node:assert/strict");
const { startProtectedExam } = require("../start-flow.cjs");

function fixture(extra = {}) {
  const calls = [];
  return {
    calls,
    options: {
      strict: true,
      protect: async () => calls.push("protect"),
      activate: async () => {
        calls.push("activate");
        return { available: true, active: true };
      },
      probe: async () => {
        calls.push("probe");
        return { available: true, active: true };
      },
      start: async (native) => {
        assert.equal(native.active, true);
        calls.push("start");
        return { id: "session" };
      },
      open: async () => calls.push("open"),
      release: async () => calls.push("release"),
      interrupt: async () => calls.push("interrupt"),
      ...extra,
    },
  };
}
test("One start transaction protects pixels before arming and opens only after backend acceptance", async () => {
  const f = fixture();
  const result = await startProtectedExam(f.options);
  assert.equal(result.id, "session");
  assert.deepEqual(f.calls, ["protect", "activate", "probe", "start", "open"]);
});
test("Rejected native activation rolls restrictions back without starting exam", async () => {
  const f = fixture({
    activate: async () => ({ available: true, active: false, error: "denied" }),
  });
  await assert.rejects(() => startProtectedExam(f.options), /denied/);
  assert.deepEqual(f.calls, ["protect", "release"]);
});
test("Backend rejection releases protection; failed exam load interrupts an already active session", async () => {
  const a = fixture({
    start: async () => {
      throw new Error("microphone");
    },
  });
  await assert.rejects(() => startProtectedExam(a.options), /microphone/);
  assert.equal(a.calls.at(-1), "release");
  assert.ok(!a.calls.includes("open"));
  const b = fixture({
    open: async () => {
      throw new Error("network");
    },
  });
  await assert.rejects(() => startProtectedExam(b.options), /network/);
  assert.equal(b.calls.at(-1), "interrupt");
});
test("An administrative software fixture never activates OS restrictions", async () => {
  const f = fixture({ strict: false });
  await startProtectedExam(f.options);
  assert.deepEqual(f.calls, ["probe", "start", "open"]);
});
test("Missing live touchpad protection rejects activation before a Moodle attempt starts", async () => {
  const f = fixture({ requireGestures: true });
  await assert.rejects(() => startProtectedExam(f.options), /Тачпад/);
  assert.deepEqual(f.calls, ["protect", "activate", "release"]);
});
test("Gesture protection must still be active in the final readiness probe", async () => {
  const f = fixture({
    requireGestures: true,
    activate: async () => ({
      available: true,
      active: true,
      gestures_enforced: true,
    }),
  });
  await assert.rejects(() => startProtectedExam(f.options), /Тачпад/);
  assert.ok(!f.calls.includes("start"));
  assert.equal(f.calls.at(-1), "release");
});
test("Verified touchpad protection allows the existing start transaction", async () => {
  const f = fixture({
    requireGestures: true,
    activate: async () => ({
      available: true,
      active: true,
      gestures_enforced: true,
    }),
    probe: async () => ({
      available: true,
      active: true,
      gestures_enforced: true,
    }),
  });
  await startProtectedExam(f.options);
  assert.ok(f.calls.includes("start") && f.calls.includes("open"));
});
test("Antivirus status must be ready before the attempt starts", async () => {
  const f = fixture({ requireAntimalware: true });
  await assert.rejects(() => startProtectedExam(f.options), /Антивирус/);
  assert.ok(!f.calls.includes("start"));
  assert.equal(f.calls.at(-1), "release");
});
test("Unverified package files never reach the exam page", async () => {
  const f = fixture({ requireIntegrity: true });
  await assert.rejects(() => startProtectedExam(f.options), /тұтастығы/);
  assert.ok(!f.calls.includes("start"));
});
test("Verified antivirus and locked package allow the existing start flow", async () => {
  const f = fixture({
    requireAntimalware: true,
    requireIntegrity: true,
    probe: async () => ({
      available: true,
      active: true,
      antimalware: { ready: true },
      package_integrity: { ready: true },
    }),
  });
  await startProtectedExam(f.options);
  assert.ok(f.calls.includes("open"));
});
test("Guard failure during readiness retains its cause and never starts the exam", async () => {
  let probes = 0;
  const f = fixture({
    probe: async () =>
      ++probes === 1
        ? { available: true, active: true, storage_check_pending: true }
        : {
            available: true,
            active: false,
            error: "Бөгде терезені жабу расталмады",
          },
  });
  await assert.rejects(
    () => startProtectedExam(f.options),
    /Бөгде терезені жабу расталмады/,
  );
  assert.equal(f.calls.at(-1), "release");
  assert.ok(!f.calls.includes("start"));
});
