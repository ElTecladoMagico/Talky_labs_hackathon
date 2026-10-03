'use strict';
// Results slide: Play runs the CSS timeline (.playing) and counts numbers up, manim DecimalNumber style.
function smooth(p) { return p < 0.5 ? 2 * p * p : 1 - (-2 * p + 2) ** 2 / 2; }
function valueAt(el, t) {
  const p = Math.min(1, Math.max(0, (t - Number(el.dataset.d)) / Number(el.dataset.dur)));
  return (smooth(p) * Number(el.dataset.to)).toFixed(Number(el.dataset.dec));
}
function mountResults(doc, win) {
  const stage = doc.getElementById('manim');
  if (!stage) return;
  const play = doc.getElementById('play'), replay = doc.getElementById('replay');
  const counters = [...stage.querySelectorAll('[data-to]')];
  const end = Math.max(...counters.map(el => Number(el.dataset.d) + Number(el.dataset.dur)));
  const still = win.matchMedia && win.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let raf = 0;
  function reset() {
    win.cancelAnimationFrame(raf);
    stage.classList.remove('playing');
    play.hidden = false; replay.hidden = true;
  }
  function start() {
    reset();
    void stage.getBoundingClientRect(); // restart CSS animations
    stage.classList.add('playing');
    play.hidden = true; replay.hidden = false;
    const t0 = win.performance.now();
    const tick = now => {
      const t = still ? end : (now - t0) / 1000;
      counters.forEach(el => { el.textContent = valueAt(el, t); });
      if (t < end) raf = win.requestAnimationFrame(tick);
    };
    raf = win.requestAnimationFrame(tick);
  }
  play.addEventListener('click', start);
  replay.addEventListener('click', start);
  win.addEventListener('hashchange', reset);
}
if (typeof module !== 'undefined' && module.exports) module.exports = { smooth, valueAt };
else mountResults(document, window);
