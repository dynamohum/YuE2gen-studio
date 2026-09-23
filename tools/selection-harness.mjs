// Asserts who owns the left column after each way of changing it.
//
// Written after three faults came from the same place: four fields
// (editorTakeId, editorSourceId, leftTakeId, planTakeId) that drifted apart, so a
// cover was rendered from another recording's score and a new plan was never
// shown.  They are one object now, and this is what keeps them one.
//
//   node tools/selection-harness.mjs
//
// It runs offline: the DOM is stubbed and fetch is answered from a fixture, so it
// needs no server, no engine and no library.

import fs from 'node:fs';
import vm from 'node:vm';

const here = new URL('../app/static/app.js', import.meta.url);
const src = fs.readFileSync(here, 'utf8');

function makeEl(id) {
  const el = { id, value: '', textContent: '', innerHTML: '', className: '', checked: false, disabled: false,
    open: false, files: [], selectionStart: 0, selectionEnd: 0, style: {}, dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener(t, fn) { (el._h[t] = el._h[t] || []).push(fn); },
    dispatchEvent(t) { (el._h[t.type] || []).forEach((f) => f(t)); return true; },
    closest() { return null; }, scrollIntoView() {}, focus() {}, setAttribute() {},
    getContext() { return { clearRect() {}, fillRect() {}, fillStyle: '', measureText: () => ({ width: 10 }) }; },
    getBoundingClientRect() { return { left: 0, width: 600, top: 0, height: 44 }; },
    clientWidth: 600, width: 600, height: 44, _h: {}, querySelectorAll() { return []; },
    querySelector() { return null; } };
  return el;
}
const els = new Map();
const document = {
  getElementById(id) { if (!els.has(id)) els.set(id, makeEl(id)); return els.get(id); },
  querySelector(s) { if (!els.has(s)) els.set(s, makeEl(s)); return els.get(s); },
  querySelectorAll() { return []; }, addEventListener() {}, body: { style: {} }
};

const LONG = (name) => 'X:1\nT:' + name + '\nM:4/4\nL:1/16\nQ:1/4=100\nK:C\n% intro\n"C"z8|"C"z8|"C"z8|"C"z8|\n';
const SOURCE_A = { id: 'srcA', title: 'A recording', transcribe_state: 'done', has_score: 1, abc: LONG('recording') };
const SOURCE_B = { id: 'srcB', title: 'Another recording', transcribe_state: 'none', has_score: 0, abc: '' };
const SONG = { id: 't1', title: 'A song', kind: 'song', status: 'done', source_id: null,
               abc: LONG('song'), style: 'folk', lyrics: '[Verse]\nwords', mode: 'full', seed: 1, max_duration: 60 };
const COVER = { id: 'c1', title: 'A cover', kind: 'cover', status: 'done', source_id: 'srcA',
                abc: LONG('cover'), style: 'folk', lyrics: '[Verse]\nwords', mode: 'full', seed: 2, max_duration: 60 };

const routes = {
  '/api/sources/srcA': SOURCE_A,
  '/api/sources/srcB': SOURCE_B,
  '/api/takes/t1': Object.assign({}, SONG, { abc: LONG('brand-new-plan'), status: 'planned' })
};

const store = new Map();
const ctx = {
  document, console,
  navigator: { mediaSession: { setActionHandler() {} }, clipboard: { writeText: async () => {} } },
  ABCJS: { renderAbc() {} },
  marked: { parse: (text) => text },
  localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)) },
  window: { devicePixelRatio: 1, addEventListener() {}, requestAnimationFrame: () => 0, cancelAnimationFrame() {} },
  fetch: async (path, options) => {
    const clean = path.split('?')[0];
    const answer = (body) => ({ ok: true, status: 200, json: async () => body,
                                text: async () => JSON.stringify(body), headers: { get: () => 'application/json' } });
    if (routes[clean]) { return answer(routes[clean]); }
    // The page loads these on start; the test only cares about the selection.
    if (clean === '/api/sources') { return answer(ctx.State.sources); }
    if (clean === '/api/takes') { return answer(ctx.State.takes); }
    if (clean === '/api/spaces') { return answer([{ id: 'default', title: 'Default', take_count: 0 }]); }
    if (clean === '/api/state') { return answer({ engine: { online: true, queue: {} }, current: null, options: {} }); }
    // Lists the page paints on start, which this test does not exercise.
    if (/^\/api\/(identities|personas|stem-sets|lyrics|takes\/)/.test(clean)) { return answer([]); }
    return answer({});
  },
  setTimeout, clearTimeout, Event: class { constructor(t) { this.type = t; } },
  setInterval: () => 0, clearInterval: () => 0, confirm: () => true,
  requestAnimationFrame: () => 0, cancelAnimationFrame: () => 0
};
ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(src, ctx, { filename: 'app.js' });

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failures = 0;

function check(label, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (!ok) { failures += 1; }
  console.log((ok ? 'ok   ' : 'FAIL ') + label.padEnd(46) + JSON.stringify(actual)
    + (ok ? '' : '   expected ' + JSON.stringify(expected)));
}
const sel = () => ({ formTakeId: ctx.Selection.formTakeId, boxKind: ctx.Selection.boxKind,
                     boxId: ctx.Selection.boxId, awaiting: ctx.Selection.awaiting });

// The page loads its lists and restores its form on start; let that settle before
// driving it, or the select it rebuilds takes the value set here with it.
await sleep(400);
ctx.State.sources = [SOURCE_A, SOURCE_B];
ctx.State.takes = [SONG, COVER];
ctx.setMode('cover');

// 1. a recording whose score is in the box
$('source-select').value = 'srcA';
check('the recording is chosen', ctx.currentSource() ? ctx.currentSource().id : 'none', 'srcA');
ctx.paintSource();
await sleep(200);
check('a transcribed recording owns the box', sel(),
  { formTakeId: null, boxKind: 'source', boxId: 'srcA', awaiting: null });
check('  and its score is in the box', String($('abc').value).slice(0, 3), 'X:1');

// 2. choosing a recording with no score empties the box rather than keeping it
$('source-select').value = 'srcB';
ctx.paintSource();
await sleep(60);
check('an untranscribed one empties the box', sel(),
  { formTakeId: null, boxKind: 'none', boxId: null, awaiting: null });
check('  and nothing is left of the last score', String($('abc').value), '');

// 3. a take owns the box, and the form, when its card is clicked
ctx.selectTake(SONG);
check('a card click gives the take the box', sel(),
  { formTakeId: 't1', boxKind: 'take', boxId: 't1', awaiting: null });

// 4. choosing a recording that take did not come from lets go of it
$('source-select').value = 'srcB';
$('source-select').dispatchEvent({ type: 'change' });
await sleep(60);
check('another recording drops the take', sel(),
  { formTakeId: null, boxKind: 'none', boxId: null, awaiting: null });

// 5. a cover take keeps its own score while its recording is the chosen one
$('source-select').value = 'srcA';
ctx.paintSource();
await sleep(60);
ctx.selectTake(COVER);
check('a cover take owns the box', sel(),
  { formTakeId: 'c1', boxKind: 'take', boxId: 'c1', awaiting: null });
$('source-select').dispatchEvent({ type: 'change' });
await sleep(60);
check('  and keeps it while its recording stands', sel(),
  { formTakeId: 'c1', boxKind: 'take', boxId: 'c1', awaiting: null });

// 6. a new plan owns nothing until it lands, then the take owns the box
ctx.awaitNewPlan('t1');
check('a plan in flight owns nothing', sel(),
  { formTakeId: 't1', boxKind: 'none', boxId: null, awaiting: 't1' });
check('  and the box is emptied for it', String($('abc').value), '');
await ctx.watchPlan();
check('the plan lands in the box', sel(),
  { formTakeId: 't1', boxKind: 'take', boxId: 't1', awaiting: null });
check('  with the new score', String($('abc').value).indexOf('brand-new-plan') > 0, true);

// 7. a fresh start releases everything
ctx.startFresh();
check('a fresh start releases the column', sel(),
  { formTakeId: null, boxKind: 'none', boxId: null, awaiting: null });

console.log(failures ? '\n' + failures + ' FAILED' : '\nall selection checks pass');
process.exit(failures ? 1 : 0);
