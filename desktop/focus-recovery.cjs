// Electron's BrowserWindow.isFocused() can be false while a WebContentsView
// owns the foreground. Only the native HWND check may end a protected exam.
function createFocusRecovery({
  read,
  restore,
  record,
  interrupt,
  now = Date.now,
  graceMs = 4000,
}) {
  let sid = null,
    lostAt = null,
    busy = false,
    generation = 0;
  function reset() {
    sid = null;
    lostAt = null;
    generation++;
  }
  async function check(session, alive) {
    if (busy || !session || !session.strict || session.starting) return;
    if (sid !== session.id) {
      sid = session.id;
      lostAt = null;
      generation++;
    }
    const epoch = generation;
    busy = true;
    try {
      const state = await read();
      if (epoch !== generation || !alive(session.id)) return;
      if (!state.available || !state.active) {
        await interrupt("guard_inactive_during_focus_check");
        return;
      }
      if (state.exam_foreground === true) {
        if (lostAt !== null)
          await record("focus_lost", {
            blocked: true,
            action: "restore_exam_focus",
            duration_ms: now() - lostAt,
          });
        lostAt = null;
        return;
      }
      if (state.exam_foreground !== false)
        throw new Error("Native foreground verification unavailable");
      if (lostAt === null) lostAt = now();
      await restore();
      if (
        epoch !== generation ||
        !alive(session.id) ||
        now() - lostAt < graceMs
      )
        return;
      // Re-read after restoration: never terminate on a stale blur notification.
      const verified = await read();
      if (epoch !== generation || !alive(session.id)) return;
      if (
        verified.available &&
        verified.active &&
        verified.exam_foreground === true
      ) {
        await record("focus_lost", {
          blocked: true,
          action: "restore_exam_focus",
          duration_ms: now() - lostAt,
        });
        lostAt = null;
        return;
      }
      await record("focus_lost", {
        blocked: false,
        action: "native_foreground_verification",
        foreground_pid: verified.foreground_pid,
        duration_ms: now() - lostAt,
      });
      await interrupt("cannot_restore_exam_focus");
    } finally {
      busy = false;
    }
  }
  return { check, reset };
}
module.exports = { createFocusRecovery };
