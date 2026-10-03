const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { parseSlide, formatTime, mount } = require('../dist/deck.js');

test('hash links are bounded and malformed links return to the beginning', () => {
  for (const [hash, expected] of [['#1', 0], ['#7', 6], ['#99', 6], ['#0', 0], ['#bad', 0], ['', 0]]) {
    assert.equal(parseSlide(hash, 7), expected);
  }
});
test('clock formats seconds without negative or fractional values', () => {
  assert.equal(formatTime(300), '05:00');
  assert.equal(formatTime(61), '01:01');
  assert.equal(formatTime(-5), '00:00');
  assert.equal(formatTime(3.7), '00:03');
});

function fixture(hash = '#1') {
  const node = (extra = {}) => ({ hidden: false, disabled: false, textContent: '', style: {}, dataset: {}, attrs: {},
    setAttribute(k, v) { this.attrs[k] = String(v); }, focus() { this.focused = true; }, ...extra });
  const slides = Array.from({ length: 7 }, (_, i) => node({ id: String(i + 1), dataset: { title: 'Slide ' + i, time: '40 s' },
    querySelector: () => ({ textContent: 'Nota ' + i }) }));
  const links = slides.map((_, i) => node({ getAttribute: () => '#' + (i + 1) }));
  const ids = Object.fromEntries(['prev', 'next', 'counter', 'progress', 'notes', 'notes-toggle', 'notes-text', 'slide-time',
    'timer', 'timer-toggle', 'timer-reset', 'fullscreen', 'status'].map(id => [id, node()]));
  const events = {};
  const doc = { querySelectorAll: selector => selector === '[data-slide]' ? slides : links,
    getElementById: id => ids[id], addEventListener: (k, fn) => { events[k] = fn; },
    documentElement: { requestFullscreen: async () => { doc.fullscreenElement = {}; } },
    exitFullscreen: async () => { doc.fullscreenElement = null; } };
  let now = 0;
  const win = { location: { hash }, addEventListener: (k, fn) => { events[k] = fn; },
    setInterval(fn) { win.tick = fn; return 1; }, clearInterval() { win.cleared = true; } };
  mount(doc, win, () => now);
  const key = (k, tag = 'BODY') => { let prevented = false; events.keydown({ key: k, target: { tagName: tag, isContentEditable: false },
    altKey: false, ctrlKey: false, metaKey: false, preventDefault() { prevented = true; } }); return prevented; };
  return { ids, slides, links, doc, win, events, key, advance(ms) { now += ms; win.tick?.(); } };
}
test('navigation renders exactly one slide, bounds buttons, and exposes current slide', () => {
  const f = fixture();
  assert.equal(f.slides.filter(s => !s.hidden).length, 1);
  assert.equal(f.ids.prev.disabled, true);
  f.ids.next.onclick(); assert.equal(f.win.location.hash, '2');
  f.events.hashchange(); assert.equal(f.ids.counter.textContent, '02 / 07');
  assert.equal(f.links[1].attrs['aria-current'], 'step');
  assert.equal(f.ids['notes-text'].textContent, 'Nota 1');
  f.key('End'); f.events.hashchange(); assert.equal(f.ids.next.disabled, true);
  f.key('Home'); f.events.hashchange(); assert.equal(f.ids.prev.disabled, true);
  f.key('ArrowRight'); f.events.hashchange();
  f.key('ArrowLeft'); f.events.hashchange();
  f.key('PageDown'); f.events.hashchange(); f.key('PageUp'); f.events.hashchange();
  f.key(' '); f.events.hashchange();
  assert.equal(f.key('ArrowRight', 'BUTTON'), false);
  assert.equal(f.key('ArrowRight', 'INPUT'), false);
  assert.equal(f.key('Escape'), false);
});
test('notes can be shown and hidden by button or keyboard', () => {
  const f = fixture(); assert.equal(f.ids.notes.hidden, true);
  f.ids['notes-toggle'].onclick(); assert.equal(f.ids.notes.hidden, false);
  assert.equal(f.ids['notes-toggle'].attrs['aria-expanded'], 'true');
  f.key('n'); assert.equal(f.ids.notes.hidden, true);
});
test('timer starts on request, pauses without drift, resets and stops at five minutes', () => {
  const f = fixture(); assert.equal(f.ids.timer.textContent, '05:00');
  f.ids['timer-toggle'].onclick(); f.advance(61000); assert.equal(f.ids.timer.textContent, '03:59');
  f.ids['timer-toggle'].onclick(); f.advance(10000); assert.equal(f.ids.timer.textContent, '03:59');
  f.ids['timer-toggle'].onclick(); f.advance(239000); assert.equal(f.ids.timer.textContent, '00:00');
  assert.equal(f.ids['timer-toggle'].textContent, 'Reiniciar');
  f.ids['timer-toggle'].onclick(); assert.equal(f.ids.timer.textContent, '05:00');
  f.ids['timer-reset'].onclick(); assert.equal(f.ids.timer.textContent, '05:00');
});
test('fullscreen enters, exits and reports unsupported or rejected requests', async () => {
  const f = fixture(); await f.ids.fullscreen.onclick(); assert.ok(f.doc.fullscreenElement);
  await f.ids.fullscreen.onclick(); assert.equal(f.doc.fullscreenElement, null);
  f.doc.documentElement.requestFullscreen = undefined;
  await f.ids.fullscreen.onclick(); assert.match(f.ids.status.textContent, /pantalla completa/i);
  f.doc.documentElement.requestFullscreen = async () => { throw Error('denied'); };
  await f.ids.fullscreen.onclick(); assert.match(f.ids.status.textContent, /pantalla completa/i);
});
test('content is offline, seven slides total exactly five minutes, and P2/P3 and limitations are documented', () => {
  const html = fs.readFileSync(path.join(__dirname, '../dist/index.html'), 'utf8');
  const times = [...html.matchAll(/data-seconds="(\d+)"/g)].map(m => Number(m[1]));
  assert.equal(times.length, 7); assert.equal(times.reduce((a, b) => a + b, 0), 300);
  assert.match(html, /P2/); assert.match(html, /P3/); assert.match(html, /96,47/);
  assert.match(html, /sin golden/i); assert.match(html, /seis diferencias/i);
  assert.match(html, /438\.854,31/); assert.match(html, /430\.565,81/); assert.match(html, /8\.288,50/);
  assert.doesNotMatch(html, /(?:src|href)="https?:\/\//);
  for (const asset of ['deck.js', 'style.css']) assert.ok(fs.existsSync(path.join(__dirname, '../dist', asset)));
});
