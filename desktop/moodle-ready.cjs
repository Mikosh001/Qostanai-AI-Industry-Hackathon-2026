// Do not show a Moodle access-denied page while the hub still has preflight state.
async function waitForMoodle({ probe, alive, timeout = 10000, interval = 300 }) {
  const deadline = Date.now() + timeout;
  let message = "Moodle қорғаныс сессиясын растауды күтіп тұр";
  do {
    if (!alive()) throw new Error("Емтихан сессиясы тоқтатылды");
    let timer;
    let state;
    try {
      state = await Promise.race([probe(), new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error("Moodle байланысын тексеру уақыты бітті")), Math.max(1, deadline - Date.now()));
      })]);
    } catch (error) {
      if (error.status >= 400 && error.status < 500) throw error;
      state = {ready: false, message: error.message || message};
    } finally { clearTimeout(timer); }
    if (!alive()) throw new Error("Емтихан сессиясы тоқтатылды");
    if (state.ready) return;
    // Capacity errors need an action, not repeated network retries. Keep the
    // preflight session so the same button can be used after space is restored.
    if (state.retryable === false) throw new Error(state.message || message);
    message = state.message || message;
    if (Date.now() >= deadline) break;
    await new Promise(resolve => setTimeout(resolve, interval));
  } while (Date.now() < deadline);
  throw new Error(message + ". Тест ашылмады; қайта іске қосып көріңіз.");
}
module.exports = { waitForMoodle };
