// Drives the real app.js against a running deployment, with a stub DOM.
//
// Written to find a bug where a finished job reloaded the source list and
// overwrote the score plan that had just landed, leaving "Render this score"
// with nothing to act on.  It reproduced that in one run, which reading the
// code had failed to do three times.
//
//   APP=http://127.0.0.1:8090 node tools/ui-harness.mjs
//
// It creates real takes.  Delete them afterwards.

import fs from 'node:fs';
import vm from 'node:vm';
const APP = process.env.APP || 'http://127.0.0.1:8090';
const src = fs.readFileSync(new URL('../app/static/app.js', import.meta.url), 'utf8');
function makeEl(id) {
  const el = { id, value: '', textContent: '', innerHTML: '', className: '', checked: false, disabled: false,
    open: false, files: [], selectionStart: 0, selectionEnd: 0, style: {}, dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener(t, fn) { (el._h[t] = el._h[t] || []).push(fn); }, dispatchEvent() { return true; },
    closest() { return null; }, scrollIntoView() {}, focus() {},
    getContext() { return { clearRect() {}, fillRect() {}, fillStyle: '' }; },
    getBoundingClientRect() { return { left: 0, width: 600 }; }, clientWidth: 600, width: 600, height: 44, _h: {} };
  return el;
}
const els = new Map();
const document = { getElementById(id) { if (!els.has(id)) els.set(id, makeEl(id)); return els.get(id); },
  querySelector(s) { if (!els.has(s)) els.set(s, makeEl(s)); return els.get(s); },
  querySelectorAll() { return []; }, addEventListener() {}, body: { style: {} } };
const store = new Map();
const ctx = { document, console,
  localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)) },
  window: { devicePixelRatio: 1, addEventListener() {}, requestAnimationFrame: () => 0, cancelAnimationFrame() {} },
  fetch: (u, o) => fetch(u.startsWith('http') ? u : APP + u, o),
  setTimeout, clearTimeout, Event: class { constructor(t) { this.type = t; } },
  setInterval: () => 0, confirm: () => true, requestAnimationFrame: () => 0, cancelAnimationFrame: () => 0 };
ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(src, ctx, { filename: 'app.js' });
const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

ctx.setMode('song');
$('title').value = 'Harness click-through';
$('style').value = 'late 1960s psychedelic';
$('lyrics').value = '[Verse]\nOne pill makes you larger\nAnd one pill makes you small\n[Chorus]\nGo ask Alice';
await ctx.doPlan();
const id = ctx.State.planTakeId;
for (let i = 0; i < 15; i++) {
  await sleep(4000);
  await ctx.watchPlan();
  if (String($('abc').value).length > 50) break;
}
console.log('STEP plan landed   : abc=' + String($('abc').value).length, 'editorTake=' + ctx.takeIdInEditor(), 'render disabled=' + $('render-take').disabled);

await ctx.doRenderTake();
console.log('STEP render clicked: status text =', JSON.stringify($('render-status').textContent));
let status = '?';
for (let i = 0; i < 40; i++) {
  await sleep(5000);
  const t = await (await fetch(APP + '/api/takes/' + id)).json();
  status = t.status;
  if (status === 'done' || status === 'failed') { console.log('STEP render:', status, 'duration=', t.duration, 'audio=', t.has_audio, (t.error || '')); break; }
}
console.log('TAKE_ID', id);
