const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const asar=require('@electron/asar');
const root=path.resolve(__dirname,'..'),version=require('../package.json').version;
const resources=path.resolve(process.argv[2]||path.join(root,`release-v${version}/win-unpacked`),'resources');
const digest=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const checks=[];
for(const name of ['main.cjs','focus-recovery.cjs','start-flow.cjs','policy.cjs','navigation.cjs','preload.cjs']) {
 const file='desktop/'+name,expected=digest(fs.readFileSync(path.join(root,file))),actual=digest(asar.extractFile(path.join(resources,'app.asar'),file));
 assert.equal(actual,expected,file);checks.push(file);
}
assert.equal(JSON.parse(asar.extractFile(path.join(resources,'app.asar'),'package.json')).version,version);
for(const [from,to] of [['build/guard/Sergek.Guard.exe','guard/Sergek.Guard.exe'],['build/guard/Sergek.Guard.dll','guard/Sergek.Guard.dll'],['build/backend/sergek-backend.exe','backend/sergek-backend.exe'],['dist/index.html','ui/index.html'],...fs.readdirSync(path.join(root,'dist/assets')).map(n=>['dist/assets/'+n,'ui/assets/'+n])]) {
 assert.equal(digest(fs.readFileSync(path.join(root,from))),digest(fs.readFileSync(path.join(resources,to))),to);checks.push(to);
}
const result={passed:true,version,scope:resources.startsWith(path.join(root,`release-v${version}`))?'packaged application':'installed application',checks};
fs.writeFileSync(process.argv[3]||path.join(root,'tests/session-repair-package.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
