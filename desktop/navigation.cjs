// Chromium can reject an older loadURL when a newer allowed Moodle navigation
// supersedes it. Recover only after that new document has actually finished.
async function loadExamDocument({load, inspect, protect, alive, expectedUrl, timeout=15000, sleep=ms=>new Promise(r=>setTimeout(r,ms))}) {
  try {
    await load();
  } catch (error) {
    if (!/ERR_ABORTED|ERR_BLOCKED_BY_CLIENT/.test(String(error))) throw error;
    const expected=new URL(expectedUrl);
    const deadline=Date.now()+timeout;
    let recovered=false;
    while (alive() && Date.now()<deadline) {
      try {
        const state=await inspect();
        const current=new URL(state.url);
        const sameQuizPath=current.pathname===expected.pathname ||
          (/\/(startattempt|attempt)\.php$/.test(expected.pathname) && /\/mod\/quiz\/(startattempt|attempt)\.php$/.test(current.pathname));
        if (current.origin===expected.origin && sameQuizPath && state.ready && state.content) {recovered=true;break;}
      } catch {}
      await sleep(50);
    }
    if (!recovered) throw error;
  }
  if (!alive()) throw new Error('Exam session stopped while loading');
  await protect();
}
module.exports={loadExamDocument};
