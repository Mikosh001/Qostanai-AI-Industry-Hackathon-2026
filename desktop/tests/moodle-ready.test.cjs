const { test } = require('node:test');
const assert = require('node:assert/strict');
const { waitForMoodle } = require('../moodle-ready.cjs');

test('Waits for the hub acknowledgement before opening the first exam page', async () => {
  let calls = 0;
  await waitForMoodle({ alive: () => true, interval: 1,
    probe: async () => ({ ready: ++calls === 3 }) });
  assert.equal(calls, 3);
});
test('Unavailable hub produces a useful error instead of showing a dead launch link', async () => {
  await assert.rejects(waitForMoodle({ alive: () => true, timeout: 2, interval: 1,
    probe: async () => ({ ready: false, message: 'Hub unavailable' }) }), /Hub unavailable/);
});
test('A cancelled session never opens Moodle even when a delayed acknowledgement arrives', async () => {
  let active = true;
  await assert.rejects(waitForMoodle({ alive: () => active,
    probe: async () => { active = false; return { ready: true }; } }), /тоқтатылды/);
});

test('A hung readiness request cannot leave the student waiting indefinitely', async () => {
  const started = Date.now();
  await assert.rejects(waitForMoodle({ alive: () => true, timeout: 20,
    probe: () => new Promise(() => {}) }), /уақыты бітті/);
  assert.ok(Date.now() - started < 500);
});

test('A brief connection error retries within the deadline', async () => {
  let calls=0;
  await waitForMoodle({alive:()=>true,interval:1,timeout:100,
    probe:async()=>{if(++calls===1)throw new Error('fetch failed');return {ready:true};}});
  assert.equal(calls,2);
});

test('Authentication failures are reported immediately', async () => {
  let calls=0;
  await assert.rejects(waitForMoodle({alive:()=>true,timeout:100,
    probe:async()=>{calls++;const e=new Error('Unauthorized');e.status=401;throw e;}}),/Unauthorized/);
  assert.equal(calls,1);
});
