'use strict';
function parseSlide(hash, count) {
  const number = /^#\d+$/.test(hash) ? Number(hash.slice(1)) - 1 : 0;
  return Math.max(0, Math.min(count - 1, number));
}
function formatTime(seconds) {
  seconds = Math.max(0, Math.floor(seconds));
  return String(Math.floor(seconds / 60)).padStart(2, '0') + ':' + String(seconds % 60).padStart(2, '0');
}
function mount(doc, win, now = Date.now) {
  const slides = [...doc.querySelectorAll('[data-slide]')];
  const links = [...doc.querySelectorAll('[data-nav]')];
  const el = id => doc.getElementById(id);
  let index = 0, started = null, elapsed = 0, interval = null;
  function render() {
    index = parseSlide(win.location.hash, slides.length);
    slides.forEach((slide, i) => { slide.hidden = i !== index; });
    links.forEach((link, i) => { link.setAttribute('aria-current', i === index ? 'step' : 'false'); });
    el('counter').textContent = String(index + 1).padStart(2, '0') + ' / ' + String(slides.length).padStart(2, '0');
    el('progress').style.width = ((index + 1) / slides.length * 100) + '%';
    el('prev').disabled = index === 0;
    el('next').disabled = index === slides.length - 1;
    el('notes-text').textContent = slides[index].querySelector('.speaker-note').textContent;
    el('slide-time').textContent = slides[index].dataset.time;
  }
  function go(next) { win.location.hash = '#' + String(Math.max(0, Math.min(slides.length - 1, next)) + 1); render(); }
  function toggleNotes() {
    el('notes').hidden = !el('notes').hidden;
    el('notes-toggle').setAttribute('aria-expanded', !el('notes').hidden);
    el('notes-toggle').textContent = el('notes').hidden ? 'Mostrar guion' : 'Ocultar guion';
  }
  function stopTimer() {
    elapsed += Math.max(0, now() - started);
    started = null;
    win.clearInterval(interval);
    interval = null;
  }
  function updateTimer() {
    const used = elapsed + (started === null ? 0 : Math.max(0, now() - started));
    const remaining = Math.max(0, 300 - Math.floor(used / 1000));
    el('timer').textContent = formatTime(remaining);
    if (remaining === 0 && started !== null) stopTimer();
    el('timer-toggle').textContent = remaining === 0 ? 'Reiniciar' : started === null ? 'Iniciar' : 'Pausar';
  }
  function resetTimer() {
    if (started !== null) stopTimer();
    elapsed = 0;
    updateTimer();
  }
  el('prev').onclick = () => go(index - 1);
  el('next').onclick = () => go(index + 1);
  el('notes-toggle').onclick = toggleNotes;
  el('timer-toggle').onclick = () => {
    if (elapsed >= 300000) { resetTimer(); return; }
    if (started === null) { started = now(); interval = win.setInterval(updateTimer, 250); }
    else stopTimer();
    updateTimer();
  };
  el('timer-reset').onclick = resetTimer;
  el('fullscreen').onclick = async () => {
    try {
      if (doc.fullscreenElement) await doc.exitFullscreen();
      else await doc.documentElement.requestFullscreen();
    } catch { el('status').textContent = 'No se pudo activar la pantalla completa. Puedes usar la opción del navegador.'; }
  };
  doc.addEventListener('keydown', event => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.target.isContentEditable || /INPUT|TEXTAREA|SELECT/.test(event.target.tagName)) return;
    if (event.key === ' ' && /BUTTON|A/.test(event.target.tagName)) return;
    if (['ArrowRight', 'PageDown', ' '].includes(event.key)) go(index + 1);
    else if (['ArrowLeft', 'PageUp'].includes(event.key)) go(index - 1);
    else if (event.key === 'Home') go(0);
    else if (event.key === 'End') go(slides.length - 1);
    else if (event.key.toLowerCase() === 'n') toggleNotes();
    else return;
    event.preventDefault();
  });
  win.addEventListener('hashchange', render);
  el('notes').hidden = true;
  render();
  updateTimer();
}
if (typeof module !== 'undefined' && module.exports) module.exports = { parseSlide, formatTime, mount };
else mount(document, window);
