(() => {
  const kk = document.documentElement.lang === 'kk';
  const text = kk ? {play:'▶ Видеоны қосу', replay:'↻ Қайта ойнату', error:'Видео ашылмады. Төмендегі сілтемемен бөлек ашыңыз.', direct:'Видеоны бөлек ашу'} : {play:'▶ Запустить видео', replay:'↻ Повторить видео', error:'Видео не открылось. Откройте его отдельно по ссылке ниже.', direct:'Открыть видео отдельно'};
  document.querySelectorAll('video').forEach(video => {
    // file:// backups have a null origin and must not opt into CORS. The
    // hosted player uses CORS mode for service-worker media range responses.
    if (location.protocol !== 'file:') video.crossOrigin = 'anonymous';
    video.controls = true; video.muted = true; video.playsInline = true;
    const wrap = document.createElement('div'); wrap.className = 'video-wrap';
    video.replaceWith(wrap); wrap.append(video);
    const start = document.createElement('button'); start.className = 'video-start'; start.textContent = text.play;
    const status = document.createElement('p'); status.className = 'video-status'; status.setAttribute('role','status'); status.hidden = true;
    const direct = document.createElement('a'); direct.className = 'video-direct'; direct.href = 'assets/Sergek-Demo.mp4'; direct.textContent = text.direct; direct.target = '_blank'; direct.rel = 'noopener';
    wrap.append(start, status, direct);
    video.addEventListener('playing', () => { start.hidden = true; status.hidden = true; wrap.classList.add('playing'); });
    video.addEventListener('ended', () => { start.textContent = text.replay; start.hidden = false; wrap.classList.remove('playing'); });
    video.addEventListener('error', () => { start.hidden = false; status.textContent = text.error; status.hidden = false; wrap.classList.remove('playing'); });
    video.addEventListener('pause', () => { if (!video.ended) { start.textContent = video.currentTime ? '▶' : text.play; start.hidden = false; } });
    start.addEventListener('click', async () => {
      try {
        if (video.ended) video.currentTime = 0;
        await video.play();
      } catch (_) { status.textContent = text.error; status.hidden = false; start.hidden = false; }
    });
    video.retryPlayback = async (restart = false) => {
      if (restart && video.readyState > 0) video.currentTime = 0;
      try { await video.play(); } catch (_) { start.hidden = false; }
    };
  });
})();
