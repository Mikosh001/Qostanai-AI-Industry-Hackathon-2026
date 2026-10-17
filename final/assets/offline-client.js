(() => {
  const host = document.querySelector('#offline-tools');
  if (!host) return;
  const button = host.querySelector('button');
  const status = host.querySelector('[role=status]');
  const meter = host.querySelector('progress');
  let worker, saving = false;
  const label = () => navigator.onLine ? 'Интернет подключён' : 'Сейчас без интернета';
  function show(message) { status.textContent = message; }
  function ask(type, onProgress) {
    worker = navigator.serviceWorker?.controller || worker;
    return new Promise((resolve, reject) => {
      const channel = new MessageChannel();
      const timeout = setTimeout(() => reject(new Error('Время ожидания истекло. Повторите сохранение при стабильном интернете.')), 900000);
      channel.port1.onmessage = ({data}) => {
        if (data.type === 'PROGRESS') { onProgress?.(data); return; }
        clearTimeout(timeout); channel.port1.close();
        if (data.error) reject(new Error(data.error)); else resolve(data);
      };
      worker.postMessage({type}, [channel.port2]);
    });
  }
  async function refresh() {
    if (saving || !worker) return;
    try {
      const state = await ask('STATUS');
      host.dataset.ready = String(state.ready);
      show(state.ready ? `Офлайн готово: ${state.count} файлов. ${label()}. Можно включать авиарежим и открывать этот адрес в том же браузере.` : `Сохраните материалы перед поездкой. ${label()}.`);
      button.textContent = state.ready ? 'Проверить офлайн-материалы' : 'Сохранить всё для поездки';
    } catch (error) { show(error.message); }
  }
  async function init() {
    if (location.protocol === 'file:') {
      const archive = host.querySelector('[data-local-archive]');
      if (archive) archive.hidden = false;
      show('Локальная папка работает без интернета. Храните START.html вместе с папкой assets и остальными материалами.');
      button.hidden = true; meter.hidden = true; return;
    }
    if (!('serviceWorker' in navigator)) {
      show('Этот просмотрщик не поддерживает офлайн-сохранение. Откройте сайт в Chrome, Edge или Safari либо скачайте ZIP и распакуйте.');
      button.hidden = true; return;
    }
    try {
      const registration = await navigator.serviceWorker.register('./sw.js', {updateViaCache:'none'});
      await navigator.serviceWorker.ready;
      worker = registration.active || navigator.serviceWorker.controller;
      if (!worker) throw new Error('Офлайн-модуль запускается. Обновите страницу.');
      button.disabled = false;
      await refresh();
    } catch (error) { show('Не удалось включить офлайн-сохранение. ' + error.message); }
  }
  button.addEventListener('click', async () => {
    if (!worker || saving) return;
    saving = true; button.disabled = true; meter.hidden = false; meter.value = 0;
    try {
      const state = await ask('SAVE', data => {
        meter.max = data.total; meter.value = data.done;
        show(`Сохраняем ${data.done} / ${data.total}: ${data.name}. Оставьте страницу открытой.`);
      });
      host.dataset.ready = 'true';
      show(`Офлайн готово: ${state.count} файлов, включая видео, обе презентации, речь и ответы. Откройте этот же адрес без интернета в том же браузере.`);
      button.textContent = 'Проверить офлайн-материалы';
      try { await navigator.storage?.persist?.(); } catch (_) {}
    } catch (error) {
      host.dataset.ready = 'false';
      show('Сохранение не завершено. ' + error.message);
      button.textContent = 'Повторить сохранение';
    } finally { saving = false; button.disabled = false; }
  });
  window.addEventListener('online', refresh); window.addEventListener('offline', refresh);
  if ('serviceWorker' in navigator) navigator.serviceWorker.addEventListener('controllerchange', () => {
    worker = navigator.serviceWorker.controller;
    refresh();
    document.querySelectorAll('video').forEach(video => {
      if (video.paused) video.load();
      else video.addEventListener('ended', () => video.load(), {once:true});
    });
  });
  init();
})();
