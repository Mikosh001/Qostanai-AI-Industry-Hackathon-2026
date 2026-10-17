const CACHE = 'sergek-prep-560728b8baa350f8';
const FILES = [{"path": "index.html", "size": 25804, "sha256": "b026bb2e5a70327350d9135ddacd8fc1779ff4d8efc8abc028e9396b0a451cb6"}, {"path": "START.html", "size": 25804, "sha256": "b026bb2e5a70327350d9135ddacd8fc1779ff4d8efc8abc028e9396b0a451cb6"}, {"path": "PRESENTATION-RU.html", "size": 22262, "sha256": "602597a266af3f366766b1bd396106e37cc245a1dbb198fa2230bcdedd3e2b77"}, {"path": "PRESENTATION-KK.html", "size": 22371, "sha256": "876e0941b1757cfefe6e02e5c9f107807af9987b6a8b536e1128f6b02986cd13"}, {"path": "app.webmanifest", "size": 392, "sha256": "35d84cda87a9d094dc50047f4b05b5b3eb4547abb30d1739fc784f37e188314a"}, {"path": "Speech-RU.txt", "size": 5256, "sha256": "8e2319f6b0722e82dc1521d52344d25b3aa5d38220f40e216c0bdd104634f9e3"}, {"path": "Defense-Guide-RU.pdf", "size": 79481, "sha256": "630ca29654cb58f43d753a3a01031b9d78dda2158c3fb746398fcada5f3b5b1c"}, {"path": "Sergek-Final-RU.pdf", "size": 2860624, "sha256": "e3fbed7c5ea2aaeba019d0279e1e2045e75185bbe3a1378e54657278d7e854e4"}, {"path": "Sergek-Final-KK.pdf", "size": 2861689, "sha256": "f29e1a7a37c8e4a4166025646147f46e6a8f0803aba414b9a69919c7bbca7312"}, {"path": "Sergek-Final-RU-Video.pptx", "size": 9894059, "sha256": "6011f81f563e51da86cd995c832b4017f1770bd3aed5660a8ada8efeb353bd95"}, {"path": "Sergek-Final-KK-Video.pptx", "size": 9894185, "sha256": "194041dc794fb163483e7e96574a7b6636fc469330b0312f10473436726eb183"}, {"path": "README.txt", "size": 1243, "sha256": "e82955e34818bac00eb4b9a61105dd65565bfc1c23a22d97ee25ea3e7a31256d"}, {"path": "assets/cover.png", "size": 1292764, "sha256": "08299e1389e832f4fe43cb99076e0524a3e7224e1b1c16efa72874216cd40852"}, {"path": "assets/episode.png", "size": 189666, "sha256": "79074c4146d0583679ff0b3622c4e4b4bfebfb5172e40fcb6145f3653b0e3181"}, {"path": "assets/icon-192.png", "size": 21368, "sha256": "8be6565b5df6592fe1ef2e6a69895e53d98a5c38917a384a2f99c72064c3e80b"}, {"path": "assets/icon-512.png", "size": 116035, "sha256": "5370d93ca52afcc5b9bdd8671f95f266821d8235f39be8ff8e379503a29e4c2e"}, {"path": "assets/icon.svg", "size": 357, "sha256": "4dfa4be668dbf3184f393415bb62cab5c54d6e8038eeb482802d068da73a3b99"}, {"path": "assets/offline-client.js", "size": 4687, "sha256": "64939c6af150464eae6b328da451d2408bf5e3cc677b6215a92b525274c7a0b2"}, {"path": "assets/playback.css", "size": 2682, "sha256": "1037b0850c308dae695877d476666da11660112757ccd96ec52d0cae33fb9bbe"}, {"path": "assets/player.js", "size": 2576, "sha256": "def7d791fc62c41642dc546fc42dec5a556692c884eecfd5e92c8df8035125e1"}, {"path": "assets/Sergek-Demo.mp4", "size": 6802303, "sha256": "e730504d95e3cde7c236c8a03175e8125e1878892baa2c58cd4607dae2b23cd0"}, {"path": "assets/Sergek-Demo.webm", "size": 2110568, "sha256": "53a235fc3a7a294f6292581e39c233d9db2348cf121cafa93bf50e3ce49b45f7"}, {"path": "assets/teacher-detail.png", "size": 73097, "sha256": "1b1616f9f0a68e8d933c1aade57d56c3f21cf724256e25d07cdca3f3a228755c"}, {"path": "assets/teacher-queue.png", "size": 112008, "sha256": "6c691428c36f6185f2576595145c93874f5bffad076ce85921a8b282a573913e"}, {"path": "assets/video-poster.png", "size": 547082, "sha256": "9a3a39338a73389d73b146aa92678bcc1a3163cdb104d1ef3706b8d251767691"}];
const BASE = new URL('./', self.location.href);
const absolute = path => new URL(path, BASE).href;
let saveTask;
self.addEventListener('install', event => event.waitUntil((async () => {
  const cache = await caches.open(CACHE);
  // Installation keeps the small shell; the explicit Save button verifies the full pack.
  for (const file of FILES.filter(f => /\.(html|js|css|svg|webmanifest)$/.test(f.path))) {
    const response = await fetch(absolute(file.path), {cache:'reload'});
    if (!response.ok) throw new Error(file.path);
    await cache.put(absolute(file.path), response);
  }
  await self.skipWaiting();
})()));
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
async function state() {
  const cache = await caches.open(CACHE);
  const matches = await Promise.all(FILES.map(f => cache.match(absolute(f.path))));
  return {ready: matches.every(Boolean), count: matches.filter(Boolean).length, total: FILES.length};
}
async function save(notify) {
  const cache = await caches.open(CACHE);
  let done = 0;
  for (const file of FILES) {
    let response = await cache.match(absolute(file.path));
    // Verify bytes, rather than marking a partial or old deployment as offline-ready.
    if (!response || (await response.clone().arrayBuffer()).byteLength !== file.size) response = undefined;
    if (!response) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 300000);
      try {
        const fresh = await fetch(absolute(file.path), {cache:'reload',signal:controller.signal});
        if (fresh.status !== 200) throw new Error(`Не загружен ${file.path} (${fresh.status})`);
        const bytes = await fresh.arrayBuffer();
        const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(n=>n.toString(16).padStart(2,'0')).join('');
        if (bytes.byteLength !== file.size || hash !== file.sha256) throw new Error(`Файл обновляется: ${file.path}. Обновите сайт и повторите сохранение.`);
        await cache.put(absolute(file.path), new Response(bytes,{status:200,headers:fresh.headers}));
      } finally { clearTimeout(timeout); }
    }
    notify({type:'PROGRESS',done:++done,total:FILES.length,name:file.path});
  }
  return state();
}
self.addEventListener('message', event => {
  const port = event.ports[0]; if (!port) return;
  event.waitUntil((async () => {
    try {
      if (event.data.type === 'STATUS') port.postMessage(await state());
      else if (event.data.type === 'SAVE') {
        if (!saveTask) saveTask = save(data=>port.postMessage(data)).finally(()=>saveTask=undefined);
        port.postMessage(await saveTask);
      }
    } catch (error) { port.postMessage({error:error.message || 'Проверьте интернет и свободное место.'}); }
  })());
});
async function ranged(response, range) {
  const bytes = await response.arrayBuffer(), size = bytes.byteLength;
  const match = /^bytes=(\d*)-(\d*)$/.exec(range);
  if (!match || (!match[1] && !match[2])) return new Response(null,{status:416,headers:{'Content-Range':`bytes */${size}`}});
  let start = match[1] ? Number(match[1]) : Math.max(0,size-Number(match[2]));
  let end = match[1] && match[2] ? Math.min(Number(match[2]),size-1) : size-1;
  if (start >= size || start > end) return new Response(null,{status:416,headers:{'Content-Range':`bytes */${size}`}});
  const headers = new Headers(response.headers);
  headers.delete('Content-Encoding'); headers.set('Content-Range',`bytes ${start}-${end}/${size}`);
  headers.set('Content-Length',String(end-start+1)); headers.set('Accept-Ranges','bytes');
  return new Response(bytes.slice(start,end+1),{status:206,statusText:'Partial Content',headers});
}
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (url.origin !== BASE.origin || event.request.method !== 'GET') return;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    url.search = ''; url.hash = '';
    if (url.pathname === BASE.pathname) url.pathname += 'index.html';
    const response = await cache.match(url.href);
    if (response) return event.request.headers.has('Range') ? ranged(response,event.request.headers.get('Range')) : response;
    try { return await fetch(event.request); }
    catch (_) { return new Response('Материал ещё не сохранён. Вернитесь на главную и нажмите «Сохранить всё для поездки» при подключённом интернете.',{status:503,headers:{'Content-Type':'text/plain; charset=utf-8'}}); }
  })());
});
