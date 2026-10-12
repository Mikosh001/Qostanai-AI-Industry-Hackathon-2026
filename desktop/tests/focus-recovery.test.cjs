const { test } = require("node:test");
const assert = require("node:assert/strict");
const { createFocusRecovery } = require("../focus-recovery.cjs");
function fixture(states) {
  let time = 0,
    index = 0,
    active = "exam";
  const calls = [];
  const recovery = createFocusRecovery({
    now: () => time,
    read: async () => ({
      available: true,
      active: true,
      ...states[Math.min(index++, states.length - 1)],
    }),
    restore: async () => calls.push("restore"),
    record: async (k, d) => calls.push([k, d]),
    interrupt: async (reason) => {
      calls.push(["interrupt", reason]);
      active = null;
    },
  });
  return {
    calls,
    recovery,
    tick: async (t) => {
      time = t;
      await recovery.check(
        { id: "exam", strict: true, starting: false },
        (id) => active === id,
      );
    },
    cancel: () => {
      active = null;
      recovery.reset();
    },
  };
}
test("Native exam foreground survives repeated Electron blur notifications", async () => {
  const f = fixture([{ exam_foreground: true }]);
  for (let t = 0; t <= 15000; t += 200) await f.tick(t);
  assert.deepEqual(f.calls, []);
});
test("A brief external window is restored without ending the exam", async () => {
  const f = fixture([{ exam_foreground: false }, { exam_foreground: true }]);
  await f.tick(0);
  await f.tick(300);
  assert.equal(f.calls[0], "restore");
  assert.equal(f.calls[1][1].blocked, true);
  assert.ok(!f.calls.some((c) => c[0] === "interrupt"));
});
test("An external window persisting beyond the grace period fails closed", async () => {
  const f = fixture([{ exam_foreground: false, foreground_pid: 123 }]);
  await f.tick(0);
  await f.tick(3900);
  assert.ok(!f.calls.some((c) => c[0] === "interrupt"));
  await f.tick(4000);
  assert.equal(f.calls.at(-1)[1], "cannot_restore_exam_focus");
});
test("Restoration at the deadline is confirmed before deciding to interrupt", async () => {
  const f = fixture([
    { exam_foreground: false },
    { exam_foreground: false },
    { exam_foreground: true },
  ]);
  await f.tick(0);
  await f.tick(4100);
  assert.equal(f.calls.at(-1)[1].blocked, true);
  assert.ok(!f.calls.some((c) => c[0] === "interrupt"));
});
test("Lost native protection cannot be accepted as successful focus recovery", async () => {
  const f = fixture([{ active: false, exam_foreground: true }]);
  await f.tick(0);
  assert.equal(f.calls.at(-1)[1], "guard_inactive_during_focus_check");
});
test("An unavailable final verification never counts as restored protection", async () => {
  const f = fixture([
    { exam_foreground: false },
    { exam_foreground: false },
    { available: false, exam_foreground: true },
  ]);
  await f.tick(0);
  await f.tick(4100);
  assert.equal(f.calls.at(-1)[0], "interrupt");
  assert.equal(f.calls.at(-2)[1].blocked, false);
});
test("No focus checks run during initial navigation or a monitor fixture", async () => {
  const f = fixture([{ exam_foreground: false }]);
  await f.recovery.check(
    { id: "exam", strict: true, starting: true },
    () => true,
  );
  await f.recovery.check({ id: "exam", strict: false }, () => true);
  assert.deepEqual(f.calls, []);
});
test("Finishing a session while native IPC is pending cancels its stale callback", async () => {
  let resolve;
  const calls = [];
  const recovery = createFocusRecovery({
    read: () => new Promise((r) => (resolve = r)),
    restore: async () => calls.push("restore"),
    record: async () => {},
    interrupt: async () => calls.push("interrupt"),
  });
  let active = true;
  const pending = recovery.check({ id: "exam", strict: true }, () => active);
  active = false;
  recovery.reset();
  resolve({ available: true, active: true, exam_foreground: false });
  await pending;
  assert.deepEqual(calls, []);
});
