// The same transaction is used by the desktop and exercised without OS mutations in tests.
async function startProtectedExam({
  strict,
  protect,
  activate,
  probe,
  start,
  open,
  release,
  interrupt,
}) {
  let started = false;
  try {
    if (strict) {
      await protect();
      const initial = await activate();
      if (!initial.available || !initial.active || initial.error)
        throw new Error(initial.error || "Windows қорғанысы іске қосылмады");
    }
    let native = await probe();
    const deadline = Date.now() + 15000;
    while (
      strict &&
      (native.unapproved_applications?.length ||
        native.forbidden_processes?.length ||
        native.storage_check_pending) &&
      Date.now() < deadline
    ) {
      await new Promise((resolve) => setTimeout(resolve, 250));
      native = await probe();
      if (!native.active || native.error)
        throw new Error(native.error || "Қорғаныс тоқтады");
    }
    if (strict && (!native.available || !native.active || native.error))
      throw new Error(native.error || "Қорғаныс байланысы жоғалды");
    const result = await start(native);
    started = true;
    await open();
    return result;
  } catch (error) {
    if (started) await interrupt("exam_open_failed");
    else await release();
    throw error;
  }
}
module.exports = { startProtectedExam };
