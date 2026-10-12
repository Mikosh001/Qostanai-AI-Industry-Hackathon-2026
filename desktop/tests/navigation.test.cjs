const {test}=require('node:test');
const assert=require('node:assert/strict');
const {loadExamDocument}=require('../navigation.cjs');
function fixture(extra={}) {
 const calls=[];
 return {calls,args:{expectedUrl:'https://localhost/mod/quiz/startattempt.php',
 load:async()=>{throw new Error('ERR_ABORTED')},inspect:async()=>({url:'https://localhost/mod/quiz/attempt.php?attempt=1',ready:true,content:true}),
 protect:async()=>calls.push('protected'),alive:()=>true,timeout:10,sleep:async()=>{},...extra}};
}
test('A superseded Moodle load recovers only after its new document is ready',async()=>{
 const f=fixture();await loadExamDocument(f.args);assert.deepEqual(f.calls,['protected']);
});
test('A blocked navigation cannot recover into another origin, an error page or a blank document',async()=>{
 for(const state of [{url:'https://evil.example/mod/quiz/attempt.php',ready:true,content:true},{url:'https://localhost/error/index.php',ready:true,content:true},{url:'https://localhost/mod/quiz/attempt.php',ready:true,content:false}]){
 const f=fixture({inspect:async()=>state});await assert.rejects(()=>loadExamDocument(f.args),/ERR_ABORTED/);assert.deepEqual(f.calls,[]);
 }
});
test('Network failures and expired sessions remain fail-closed',async()=>{
 const a=fixture({load:async()=>{throw new Error('ERR_CONNECTION_REFUSED')}});await assert.rejects(()=>loadExamDocument(a.args),/REFUSED/);
 const b=fixture({load:async()=>{},alive:()=>false});await assert.rejects(()=>loadExamDocument(b.args),/stopped/);
});
