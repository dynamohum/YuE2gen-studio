'use strict';

/* What the left column is about. One object, and only setSelection may write it.
   Four separate fields used to say this (editorTakeId, editorSourceId, leftTakeId,
   planTakeId) and they drifted apart three times: a cover was rendered from another
   recording's score, a new plan was never shown, and a card's score was credited to
   a recording that had never been transcribed. Reads go through the helpers below.

     formTakeId  the take the form describes, and whose card is highlighted
     boxKind     who owns the score in the box: 'none', 'take' or 'source'
     boxId       that take's or recording's id
     awaiting    a take whose plan is being written; it owns nothing until it lands */
var Selection = { formTakeId: null, boxKind: 'none', boxId: null, awaiting: null };

function setSelection(next) {
  Selection = {
    formTakeId: next.formTakeId || null,
    boxKind: next.boxKind || 'none',
    boxId: next.boxId || null,
    awaiting: next.awaiting || null
  };
  syncEditor();
  paintTakes();          // the highlight follows the form
  setScoreActions();     // so do Render and Replan
  saveForm();
}

/* Used when restoring the form on a reload, before the painters are ready. */
function restoreSelection(saved) {
  Selection = { formTakeId: null, boxKind: 'none', boxId: null, awaiting: null };
  if (saved && saved.boxKind && saved.boxId) { Selection.boxKind = saved.boxKind; Selection.boxId = saved.boxId; }
  if (saved && saved.formTakeId) { Selection.formTakeId = saved.formTakeId; }
  if (saved && saved.awaiting) { Selection.awaiting = saved.awaiting; }
}

function selectedTakeId() { return Selection.formTakeId; }
function scoreTakeId() { return Selection.boxKind === 'take' ? Selection.boxId : null; }
function awaitingPlanId() { return Selection.awaiting; }

/* Is the score in the box this recording's? A cover take's transcribed score came
   from its recording, so the take owns the box while the recording still matches. */
function boxShowsSource(sourceId) {
  if (!sourceId) { return false; }
  if (Selection.boxKind === 'source') { return Selection.boxId === sourceId; }
  if (Selection.boxKind === 'take') {
    var take = takeById(Selection.boxId);
    return Boolean(take && take.source_id === sourceId);
  }
  return false;
}

var State = { sources: [], takes: [], options: {}, filter: 'all', playing: null, busy: false, mode: 'cover',
  layout: 'compact',
  takesRaw: '', takesTotal: 0, takeLimit: 300, takesAt: 0, paintedAt: 0, draft: null, audition: null,
  formEdited: false, spaces: [], spaceId: 'default', moveTakeId: null };
var LAYOUT_KEY = 'yue2.layout';
var SPACE_KEY = 'yue2.space';

function applyLayout(mode) {
  State.layout = mode === 'comfy' ? 'comfy' : 'compact';
  var wide = State.layout === 'comfy';
  $('takes').classList.toggle('comfy', wide);
  var button = $('layout-toggle');
  button.textContent = wide ? 'Comfy' : 'Compact';
  button.title = wide
    ? 'Wide cards, full titles and prompts. Click for compact.'
    : 'Compact cards, three across. Click for wide.';
  try { localStorage.setItem(LAYOUT_KEY, State.layout); } catch (err) { /* private mode */ }
}

function loadLayout() {
  var saved = null;
  try { saved = localStorage.getItem(LAYOUT_KEY); } catch (err) { saved = null; }
  applyLayout(saved === 'comfy' ? 'comfy' : 'compact');
}

function $(id) { return document.getElementById(id); }
function esc(text) {
  return String(text == null ? '' : text)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function secs(value) {
  if (!value && value !== 0) { return '--:--'; }
  var total = Math.round(value);
  var m = Math.floor(total / 60);
  var s = total % 60;
  return m + ':' + (s < 10 ? '0' : '') + s;
}
function age(ts) {
  var d = Math.floor(Date.now() / 1000 - ts);
  if (d < 60) { return 'just now'; }
  if (d < 3600) { return Math.floor(d / 60) + ' min ago'; }
  if (d < 86400) { return Math.floor(d / 3600) + ' h ago'; }
  return Math.floor(d / 86400) + ' d ago';
}
function initials(text) {
  var clean = String(text || '?').trim();
  return clean ? clean[0].toUpperCase() : '?';
}

async function api(path, options) {
  var response = await fetch(path, options);
  if (!response.ok) {
    var detail = await response.text();
    try {
      var parsed = JSON.parse(detail);
      if (typeof parsed.detail === 'string') { detail = parsed.detail; }
      else if (Array.isArray(parsed.detail)) {
        detail = parsed.detail.map(function (item) { return (item.loc || []).slice(-1)[0] + ': ' + item.msg; }).join('; ');
      }
    } catch (err) { /* plain text */ }
    throw new Error(String(detail).slice(0, 300));
  }
  var type = response.headers.get('content-type') || '';
  return type.indexOf('application/json') >= 0 ? response.json() : response.text();
}

/* ------------------------------------------------------------------ state */
async function pollState() {
  try {
    var data = await api('/api/state');
    var pill = $('engine-pill');
    var engine = data.engine;
    State.options = data.options || {};
    if (engine.online && engine.compat && engine.compat.ok) {
      pill.className = 'pill pill-on';
      pill.textContent = 'Engine ready' + (engine.gpu ? ' \u00b7 ' + Math.round(engine.gpu.vram_free / 1073741824) + ' GB free' : '');
    } else if (engine.online) {
      pill.className = 'pill pill-off';
      pill.textContent = 'Engine incompatible: ' + ((engine.compat.missing || []).join(', ') || (engine.compat.notes || []).join('; '));
    } else {
      pill.className = 'pill pill-off';
      pill.textContent = 'Engine offline';
    }
    State.stemsOptions = data.stems || State.stemsOptions || {};
    if (data.settings) { adoptSettings(data.settings); }
    if (data.version) { $('app-version').textContent = 'v' + data.version; }
    paintOptions();
    paintJob(data.current, data.queue || [], data.options);
    watchPlan();
  } catch (err) {
    $('engine-pill').className = 'pill pill-off';
    $('engine-pill').textContent = 'App unreachable';
  }
}

/* How the render reads the score.  The same six the server knows, by id. */
var INTERPRETATIONS = {
  standard: { name: 'Standard', hint: 'YuE2\u2019s usual reading of the score.' },
  tight: { name: 'Tight', hint: 'More controlled and polished.' },
  loose: { name: 'Loose', hint: 'Rougher and more spontaneous.' },
  settled: { name: 'Settled', hint: 'Free to repeat a figure and sit in a groove.' },
  restless: { name: 'Restless', hint: 'Keeps the parts moving and avoids repeating itself.' },
  wide: { name: 'Wide', hint: 'Reaches for less obvious sounds.' }
};

function paintInterpretation() {
  var item = INTERPRETATIONS[$('interpretation').value] || INTERPRETATIONS.standard;
  $('interpretation-hint').textContent = item.hint;
}

function paintOptions() {
  paintHarmony();
  paintInterpretation();
  var canInst = State.options.instrumental_available !== false;
  $('create-inst').disabled = !canInst;
  $('create-inst').title = canInst ? '' : 'The engine has no instrumental LoRA. Run scripts/fetch-models.sh, then restart the engine.';
  var canWrite = State.options.lyrics_available !== false;
  $('lyrics-write').disabled = !canWrite;
  $('lyrics-write').title = canWrite ? 'Draft lyrics from a short description'
    : 'The engine has no lyric writer. Run scripts/fetch-models.sh, then restart the engine.';
  var canRealaudio = State.options.realaudio !== false;
  $('realaudio').disabled = !canRealaudio;
  if (!canRealaudio) {
    $('realaudio').checked = false;
    $('realaudio-field').title = 'The engine has no Realaudio LoRA. Run scripts/fetch-models.sh, then restart the engine.';
  } else {
    var tip = 'Applies Mothersuperior v9 real-audio decoder LoRA for studio-grade acoustic clarity, frequency separation, and clean lead vocals.';
    $('realaudio-field').title = tip;
    var raw = null;
    try { raw = localStorage.getItem(FORM_KEY); } catch (e) {}
    if (!raw || raw.indexOf('"realaudio"') === -1) {
      $('realaudio').checked = true;
    }
  }
  paintStyleLoras();
  var styleNode = $('style');
  var busy = document.activeElement === styleNode;
  if (!styleNode.value && !styleNode.dataset.touched && !busy && State.options.default_style) {
    styleNode.value = State.options.default_style;
  }
}

/* The style LoRA picker: whatever the engine can load, minus the two the app
   applies itself.  A file tells us which halves it holds, so a strength that
   would do nothing is not offered. */
var LORA_KINDS = { both: 'score and sound', planner: 'score only', decoder: 'sound only',
  other: 'not a YuE2 LoRA', unknown: '' };

/* Every LoRA that belongs to one of the Identities.  Those have a control of
   their own, where both of their strengths now live, so offering them here as
   well would be the same file in two places with two sets of settings. */
function identityLoraNames() {
  var names = {};
  (IDENTITIES_LIST || []).forEach(function (identity) {
    getIdentityLoRAs(identity).forEach(function (name) { names[name] = true; });
  });
  return names;
}

function loraCatalogue() {
  var mine = identityLoraNames();
  return (State.options.loras || []).filter(function (item) {
    return item && !item.reserved && item.kind !== 'other' && !mine[item.name];
  });
}

function loraKind(name) {
  var found = loraCatalogue().filter(function (item) { return item.name === name; })[0];
  return found ? found.kind : 'unknown';
}

/* A collection grows into dozens, and authors already name a set for what it
   is: mltnt_roots, chnsn_cabaret, slider-metal.  The word in front is the
   family, so the list groups itself without anything being hard-coded here.
   A family of one is no help to anyone, so those gather under Other. */
function loraFamily(name) {
  var head = name.replace(/\.safetensors$/i, '').split(/[-_]/)[0];
  return head.length > 1 ? head.toLowerCase() : 'other';
}

/* A named family is the set its author published, so two prefixes that share a
   name share a group: qwwl and drksf are one repository and belong together.
   Only the unnamed fall back to the word in the file name, and a lone one of
   those has nothing to head a group with. */
function loraGroupKey(item) {
  return item.family || loraFamily(item.name);
}

function loraGroups(list) {
  var counts = {};
  list.forEach(function (item) {
    var key = loraGroupKey(item);
    counts[key] = (counts[key] || 0) + 1;
  });
  var groups = {};
  list.forEach(function (item) {
    var key = loraGroupKey(item);
    if (!item.family && counts[key] < 2) { key = 'other'; }
    (groups[key] = groups[key] || []).push(item);
  });
  return groups;
}

function paintStyleLoras() {
  var select = $('style-lora');
  if (!select) { return; }
  var list = loraCatalogue();
  $('style-lora-field').classList.toggle('hidden', !list.length);
  if (!list.length) { return; }
  var chosen = select.value;
  var groups = loraGroups(list);
  var names = Object.keys(groups).sort(function (a, b) {
    if (a === 'other') { return 1; }
    if (b === 'other') { return -1; }
    return a.localeCompare(b);
  });
  var option = function (item) {
    var note = LORA_KINDS[item.kind] ? ' \u2014 ' + LORA_KINDS[item.kind] : '';
    // The author's own name for it beats a file name every time.
    var label = item.title || loraShortLabel(item.name);
    // On the option itself, so the list can be read before anything is chosen.
    var tip = [item.trigger ? 'Trigger: ' + item.trigger : '', plainNote(item.note), item.name]
      .filter(Boolean).join('\n\n');
    return '<option value="' + esc(item.name) + '" title="' + esc(tip) + '">' +
      esc(label) + esc(note) + '</option>';
  };
  select.innerHTML = '<option value="">None</option>' + names.map(function (family) {
    var inner = groups[family].map(option).join('');
    // One group and nothing to compare it with: the heading is noise.
    if (names.length < 2) { return inner; }
    // A named family is already its heading; an unnamed one is a bare file-name
    // prefix, and Other is a bag of odds and ends that must not borrow a name
    // from whichever of them happens to be first.
    var heading = family === 'other' ? 'Other'
      : (groups[family][0].family ? family : family.charAt(0).toUpperCase() + family.slice(1));
    return '<optgroup label="' + esc(heading) + '">' + inner + '</optgroup>';
  }).join('');
  // A remembered name waits here only until the list it names exists, and is
  // then spent.  Left in place it outlives the choice: the state poll repaints
  // this picker every couple of seconds, and would put the old LoRA back every
  // time None was chosen.
  if (!chosen && select.dataset.wanted) { chosen = select.dataset.wanted; }
  delete select.dataset.wanted;
  if (chosen) { select.value = chosen; }
  paintStyleLoraStrengths();
}

/* A note is written for a web page, so it arrives with emphasis and code
   marks in it.  Nothing here renders those, and a stray asterisk reads as a
   mistake, so they come out. */
function plainNote(text) {
  return String(text || '')
    .replace(/\*\*/g, '').replace(/`/g, '')
    // A blank line is a paragraph and is kept; a single wrap is not and is not.
    .replace(/[ \t]*\n[ \t]*\n\s*/g, '\u0001')
    .replace(/\s*\n\s*/g, ' ')
    .replace(/\u0001/g, '\n')
    .trim();
}

/* The file name is what the engine wants, but not what anyone wants to read. */
function loraLabel(name) {
  return name.replace(/\.safetensors$/i, '').replace(/[_-]+/g, ' ');
}

/* Inside a family the shared word is already the heading above it. */
function loraShortLabel(name) {
  var label = loraLabel(name);
  var family = loraFamily(name);
  var head = label.split(' ')[0];
  return (head.toLowerCase() === family && label.indexOf(' ') > 0) ? label.slice(head.length + 1) : label;
}

/* A file name says nothing about what a LoRA does, so whatever its author
   wrote is shown under the picker, and the trigger word is shown as something
   to click, because it has to reach the style box to do anything. */
function paintStyleLoraNote() {
  var item = loraChosen();
  var hint = $('style-lora-hint');
  if (!item) {
    hint.innerHTML = 'Planner shapes the score, Sound shapes the audio.';
    return;
  }
  var parts = [];
  if (item.trigger) {
    parts.push(styleHas($('style').value, item.trigger)
      ? 'Trigger word <b>' + esc(item.trigger) + '</b> is in the style.'
      : '<b>' + esc(item.trigger) + '</b> goes in the style when you render.');
  }
  if (item.note) { parts.push(esc(plainNote(item.note)).replace(/\n/g, '<br>')); }
  hint.innerHTML = parts.join('<br>') || 'Planner shapes the score, Sound shapes the audio.';
}

function paintStyleLoraStrengths() {
  paintStyleLoraNote();
  var name = $('style-lora').value;
  var kind = name ? loraKind(name) : '';
  $('style-lora-strengths').classList.toggle('hidden', !name);
  if (!name) { return; }
  // A strength for a half the file does not hold is a control that lies.
  var hasPlanner = kind === 'both' || kind === 'planner' || kind === 'unknown';
  var hasSound = kind === 'both' || kind === 'decoder' || kind === 'unknown';
  $('style-lora-clip').disabled = !hasPlanner;
  $('style-lora-model').disabled = !hasSound;
  $('style-lora-clip-read').textContent = hasPlanner ? Number($('style-lora-clip').value).toFixed(2) : 'not in this file';
  $('style-lora-model-read').textContent = hasSound ? Number($('style-lora-model').value).toFixed(2) : 'not in this file';
}

/* Adds the chosen LoRA to a request body, or nothing at all when none is
   chosen.  A strength whose half is missing from the file is sent as zero. */
/* A LoRA trained on captions that begin with its trigger does very little
   without it, and the app knows which word it needs, so the app puts it there.
   Choosing a different LoRA takes the old word out again; one already typed is
   left where it is. */
function applyLoraTrigger(trigger) {
  var style = $('style');
  var text = style.value;
  var previous = State.loraTrigger;
  if (previous && previous !== trigger && styleHas(text, previous)) {
    text = tidyStyle(text.replace(new RegExp('\\s*,?\\s*' + previous + '\\b', 'i'), ''));
  }
  if (trigger && !styleHas(text, trigger)) {
    text = tidyStyle(trigger + (text ? ', ' + text : ''));
  }
  State.loraTrigger = trigger || null;
  if (text !== style.value) {
    style.value = text;
    style.dataset.touched = '1';
    saveForm();
  }
}

/* Put a take's LoRA back in the picker.  Its style already carries the trigger
   word, so the word is remembered rather than inserted: nothing about the text
   changes, but choosing a different LoRA can still take the old one out. */
function showStyleLora(take) {
  var select = $('style-lora');
  if (!select) { return; }
  select.value = take.style_lora || '';
  select.dataset.wanted = take.style_lora || '';
  if (take.style_lora) {
    $('style-lora-model').value = take.style_lora_model === undefined ? 1 : take.style_lora_model;
    $('style-lora-clip').value = take.style_lora_clip === undefined ? 1 : take.style_lora_clip;
  }
  var item = loraChosen();
  State.loraTrigger = (item && item.trigger) || null;
  paintStyleLoraStrengths();
  saveForm();
}

function loraChosen() {
  var select = $('style-lora');
  if (!select || !select.value) { return null; }
  return loraCatalogue().filter(function (entry) { return entry.name === select.value; })[0] || null;
}

/* An Identity's LoRA holds a voice and, usually, a planner half as well. The
   voice is what it has always applied; this is the other half, off by default,
   so nothing rendered before this sounds different now. */
function vocalPlanner() {
  var slider = $('vocal-planner');
  var wrap = $('vocal-planner-wrap');
  if (!slider || !wrap || wrap.classList.contains('hidden')) { return 0; }
  return parseFloat(slider.value) || 0;
}

function withStyleLora(data) {
  var select = $('style-lora');
  if (!select || !select.value) { return data; }
  var item = loraChosen();
  if (item && item.trigger) {
    // A style typed or restored without it would render as if no LoRA were on.
    applyLoraTrigger(item.trigger);
    if (typeof data.style === 'string') { data.style = $('style').value; }
  }
  data.style_lora = select.value;
  data.style_lora_model = $('style-lora-model').disabled ? 0 : parseFloat($('style-lora-model').value);
  data.style_lora_clip = $('style-lora-clip').disabled ? 0 : parseFloat($('style-lora-clip').value);
  return data;
}

/* The form survives a reload. Nothing here is precious, but losing a verse is annoying. */
var FORM_KEY = 'yue2.form.v1';
var FORM_FIELDS = ['title', 'style', 'lyrics', 'mode', 'seed', 'interpretation', 'max-duration', 'variety', 'harmony'];

function saveForm() {
  try {
    var data = {};
    FORM_FIELDS.forEach(function (id) { data[id] = $(id).value; });
    data.auto_render = $('auto-render').checked;
    data.seed_fixed = $('seed-fixed').checked;
    data.realaudio = $('realaudio').checked;
    data.source = $('source-select') ? $('source-select').value : '';
    data.style_lora = $('style-lora') ? $('style-lora').value : '';
    data.style_lora_model = $('style-lora-model') ? $('style-lora-model').value : '1';
    data.style_lora_clip = $('style-lora-clip') ? $('style-lora-clip').value : '1';
    var idSel = $('vocal-identity') || $('vocal-persona');
    var loraSel = $('vocal-identity-lora') || $('vocal-persona-lora');
    data.vocal_planner = $('vocal-planner') ? $('vocal-planner').value : '0';
    data.vocal_identity = idSel ? idSel.value : '';
    data.vocal_identity_lora = (loraSel && !loraSel.classList.contains('hidden')) ? loraSel.value : '';
    data.vocal_persona = data.vocal_identity;
    data.vocal_persona_lora = data.vocal_identity_lora;
    data.left_take = selectedTakeId() || '';
    data.box_kind = Selection.boxKind;
    data.box_id = Selection.boxId || '';
    data.awaiting = awaitingPlanId() || '';
    data.structure = { kind: STRUCTURE.kind, sections: STRUCTURE.sections };
    data.feel = FEEL.value;
    localStorage.setItem(FORM_KEY, JSON.stringify(data));
  } catch (err) { /* private mode, or storage full. Not worth a message. */ }
}

function loadForm() {
  var raw;
  try { raw = localStorage.getItem(FORM_KEY); } catch (err) { return; }
  if (!raw) { return; }
  var data;
  try { data = JSON.parse(raw); } catch (err) { return; }
  FORM_FIELDS.forEach(function (id) {
    if (typeof data[id] === 'string' && data[id]) { $(id).value = data[id]; }
  });
  paintVocals();
  if (typeof data.auto_render === 'boolean') { $('auto-render').checked = data.auto_render; }
  if (typeof data.seed_fixed === 'boolean') { $('seed-fixed').checked = data.seed_fixed; }
  if (typeof data.realaudio === 'boolean') { $('realaudio').checked = data.realaudio; }
  else { $('realaudio').checked = true; }
  // The list arrives from the server, so the name is held until it exists.
  if (typeof data.source === 'string') { State.wantedSource = data.source; }
  if (data.vocal_planner !== undefined && $('vocal-planner')) {
    $('vocal-planner').value = data.vocal_planner;
  }
  if ($('style-lora')) {
    if (data.style_lora_model) { $('style-lora-model').value = data.style_lora_model; }
    if (data.style_lora_clip) { $('style-lora-clip').value = data.style_lora_clip; }
    // The list arrives with the options, so the name is held until it can be set.
    $('style-lora').dataset.wanted = data.style_lora || '';
  }
  if (typeof data.vocal_identity === 'string') { State.savedVocalIdentity = data.vocal_identity; }
  else if (typeof data.vocal_persona === 'string') { State.savedVocalIdentity = data.vocal_persona; }
  if (typeof data.vocal_identity_lora === 'string') { State.savedVocalIdentityLora = data.vocal_identity_lora; }
  else if (typeof data.vocal_persona_lora === 'string') { State.savedVocalIdentityLora = data.vocal_persona_lora; }
  if (data.style) { $('style').dataset.touched = '1'; }
  restoreSelection({ formTakeId: data.left_take || null, boxKind: data.box_kind || 'none',
                     boxId: data.box_id || null, awaiting: data.awaiting || null });
  if (FEELS[data.feel]) { FEEL.value = data.feel; }
  if (data.structure && Array.isArray(data.structure.sections)) {
    STRUCTURE.kind = ['free', 'sections', 'timed'].indexOf(data.structure.kind) >= 0 ? data.structure.kind : 'free';
    STRUCTURE.sections = data.structure.sections.filter(function (item) {
      return item && SECTIONS.indexOf(item.name) >= 0;
    }).map(function (item) { return { name: item.name, seconds: Math.max(4, Math.min(180, Number(item.seconds) || 20)) }; });
  }
}

/* A title from the first real lyric line. Section tags and genre tags do not count. */
function guessTitle(lyrics) {
  var lines = String(lyrics || '').split('\n');
  for (var i = 0; i < lines.length; i++) {
    var text = lines[i].trim();
    if (!text) { continue; }
    if (text.charAt(0) === '[' || text.charAt(0) === '(' || text.charAt(0) === '#') { continue; }
    return text.slice(0, 60);
  }
  return '';
}

/* ------------------------------------------------------------ lyrics editor */
function lyricsStats(text) {
  var lines = String(text || '').split('\n');
  var words = String(text || '').trim() ? String(text).trim().split(/\s+/).length : 0;
  return { lines: lines.length, words: words, chars: String(text || '').length };
}

function updateLyricsCount() {
  var stats = lyricsStats($('lyrics-big').value);
  $('lyrics-count').textContent = stats.words + ' words \u00b7 ' + stats.lines + ' lines \u00b7 ' + stats.chars + ' characters';
}

/* The score gets the same full size editor as the lyrics, for long ABC. */
function updateScoreCount() {
  var text = $('score-big').value;
  var bars = text.split('\n').length;
  $('score-count').textContent = text.length + ' characters, ' + bars + ' lines';
}

/* Three ways to read the score: the chord chart, real staves, and the lyrics
   with each section's chords. The lyrics view stops at the section on purpose:
   measured words per melody note runs from 0.41 to 1.25 between sections, so a
   word-by-word alignment would drift. */
/* Undo for the score text. A global chord replace cannot be undone by the browser,
   because setting .value directly drops its own history. Kept per editing session and
   reset when a different score is loaded. Typing runs coalesce; a replace does not. */
var SCORE_HISTORY_LIMIT = 120;
var scoreStack = { items: [], index: -1, at: 0, applying: false };

function pushScoreHistory(text) {
  if (scoreStack.applying) { return; }
  var now = Date.now();
  var top = scoreStack.items[scoreStack.index];
  if (top === text) { return; }
  // Coalesce a typing run, but never the entry the editor opened on, and never
  // when there is a redo tail to cut off.
  var atTip = scoreStack.index === scoreStack.items.length - 1;
  var smallEdit = atTip && scoreStack.index > 0 && typeof top === 'string' &&
                  Math.abs(top.length - text.length) <= 3 && now - scoreStack.at < 900;
  if (smallEdit) {
    scoreStack.items[scoreStack.index] = text;
  } else {
    scoreStack.items = scoreStack.items.slice(0, scoreStack.index + 1);
    scoreStack.items.push(text);
    if (scoreStack.items.length > SCORE_HISTORY_LIMIT) { scoreStack.items.shift(); }
    scoreStack.index = scoreStack.items.length - 1;
  }
  scoreStack.at = now;
  paintScoreHistory();
}

function scoreReset(text) {
  scoreStack.items = [text];
  scoreStack.index = 0;
  scoreStack.at = Date.now();
  paintScoreHistory();
}

function paintScoreHistory() {
  if ($('score-undo')) { $('score-undo').disabled = scoreStack.index <= 0; }
  if ($('score-redo')) { $('score-redo').disabled = scoreStack.index >= scoreStack.items.length - 1; }
}

function applyScoreHistory() {
  var text = scoreStack.items[scoreStack.index];
  scoreStack.applying = true;
  $('abc').value = text;
  $('score-big').value = text;
  $('abc').dispatchEvent(new Event('input'));
  scoreStack.applying = false;
  scoreStack.at = Date.now();
  paintScoreHistory();
}

function undoScore() {
  if (scoreStack.index <= 0) { return; }
  scoreStack.index -= 1;
  applyScoreHistory();
}

function redoScore() {
  if (scoreStack.index >= scoreStack.items.length - 1) { return; }
  scoreStack.index += 1;
  applyScoreHistory();
}

var SCORE_VIEW_KEY = 'yue2.scoreview';

function scoreView() {
  return State.scoreView || 'chart';
}

function abcSections(abc) {
  var sections = [];
  var current = null;
  var voice = null;
  (abc || '').split('\n').forEach(function (raw) {
    var line = raw.trim();
    if (!line) { return; }
    if (line.charAt(0) === '%') {
      current = { name: line.replace(/^%\s*/, ''), bars: [] };
      sections.push(current);
      return;
    }
    var v = line.match(/^V:\s*(\S+)/);
    if (v) { voice = v[1]; return; }
    if (!current) { current = { name: 'song', bars: [] }; sections.push(current); }
    if (voice !== 'Vocal' && voice !== 'Ins') { return; }
    line.split('|').forEach(function (chunk) {
      if (!chunk.trim()) { return; }
      var chords = chunk.match(/"([^"]+)"/g);
      current.bars.push(chords ? chords.map(function (c) { return c.replace(/"/g, ''); }) : []);
    });
  });
  return sections;
}

function sectionChords(section) {
  var out = [];
  section.bars.forEach(function (bar) {
    bar.forEach(function (chord) {
      if (out[out.length - 1] !== chord) { out.push(chord); }
    });
  });
  return out;
}

function renderNotationView() {
  var host = $('notation-big');
  var abc = ($('score-big').value || '').trim();
  if (!abc || typeof ABCJS === 'undefined') {
    host.innerHTML = '<p class="hint">No score yet.</p>';
    return;
  }
  // Rebuild the header: our own title, the score's own musical settings.
  var body = abc.split('\n').filter(function (line) {
    return !/^[XTM LQK]:/.test(line.trim());
  }).join('\n');
  var pick = function (key, fallback) {
    var m = abc.match(new RegExp('^' + key + ':\\s*(.*)$', 'm'));
    return m ? m[1] : fallback;
  };
  var full = 'X:1\nT:' + ($('title').value || 'Score') + '\n' +
    'M:' + pick('M', '4/4') + '\nL:' + pick('L', '1/8') + '\n' +
    'Q:' + pick('Q', '1/4=100') + '\nK:' + pick('K', 'C') + '\n' + body;
  try {
    // No responsive mode: abcjs then positions the SVG in the flow, so it scrolls
    // inside its pane instead of painting over the editor.
    ABCJS.renderAbc('notation-big', full, {
      scale: 1.15, staffwidth: 980,
      foregroundColor: '#f4f4f7', staffColor: '#9b9ba8'
    });
  } catch (err) {
    host.innerHTML = '<p class="hint">This score will not render as notation.</p>';
  }
}

/* An instrumental's third view: each section of the plan with its chords.  The
   lyrics box is hidden in this mode and may hold another take's words. */
function renderSectionsView() {
  var sections = abcSections($('score-big').value || '');
  $('score-view-note').textContent = 'Sections as the plan names them, with the chords of their bars.';
  $('lyrics-view').innerHTML = sections.length ? sections.map(function (section) {
    var chords = sectionChords(section);
    return '<div class="lyric-section"><span class="lyric-head">' + esc(section.name) + '</span>' +
      (chords.length ? '<span class="lyric-chords">' + esc(chords.join('  ')) + '</span>' : '') + '</div>';
  }).join('') : '<p class="hint">No sections in this score yet.</p>';
}

function renderLyricsView() {
  if (State.mode === 'inst') { renderSectionsView(); return; }
  var host = $('lyrics-view');
  var lyrics = ($('lyrics-big').value || $('lyrics').value || '').trim();
  if (!lyrics) {
    host.innerHTML = '<p class="hint">No lyrics yet.</p>';
    return;
  }
  var sections = abcSections($('score-big').value || '');
  var out = [];
  var current = null;
  lyrics.split('\n').forEach(function (raw) {
    var line = raw.trim();
    if (!line) { return; }
    var tag = line.match(/^\[(.+)\]$/);
    if (tag) {
      current = tag[1];
      var key = current.toLowerCase().replace(/\s*\d+$/, '');
      var match = null;
      for (var i = 0; i < sections.length; i++) {
        var name = sections[i].name.toLowerCase();
        if (name === key || name === current.toLowerCase()) { match = sections[i]; }
      }
      var chords = match ? sectionChords(match) : [];
      out.push('<div class="lyric-section"><span class="lyric-head">' + esc(current) + '</span>' +
        (chords.length ? '<span class="lyric-chords">' + esc(chords.join('  ')) + '</span>' : '') + '</div>');
      return;
    }
    out.push('<div class="lyric-line">' + esc(line) + '</div>');
  });
  $('score-view-note').textContent =
    'Chords are per section, from the bars of that section. The model does not place words on notes, so no word level alignment is claimed.';
  host.innerHTML = out.join('');
}

function paintScoreView() {
  var view = scoreView();
  $('score-views').querySelector('[data-view="lyrics"]').textContent = State.mode === 'inst' ? 'Sections' : 'Lyrics';
  Array.prototype.forEach.call(document.querySelectorAll('#score-views .chip'), function (chip) {
    chip.classList.toggle('active', chip.dataset.view === view);
  });
  ['chart', 'notation', 'lyrics'].forEach(function (name) {
    var box = $('view-' + name);
    if (box) { box.classList.toggle('hidden', name !== view); }
  });
  if (view === 'chart') {
    $('chart-big').textContent = chordChart($('score-big').value || '') || '';
    $('score-view-note').textContent = '';
  } else if (view === 'notation') {
    $('score-view-note').textContent = 'Drawn from the ABC with abcjs. It follows your edits.';
    renderNotationView();
  } else {
    renderLyricsView();
  }
}

function setScoreView(name) {
  State.scoreView = name;
  try { localStorage.setItem(SCORE_VIEW_KEY, name); } catch (err) { /* private mode */ }
  paintScoreView();
}

function openScoreEditor(view) {
  $('score-big').value = $('abc').value;
  if (scoreStack.items[scoreStack.index] !== $('abc').value) { scoreReset($('abc').value); }
  if (view) { State.scoreView = view; }
  paintScoreView();
  updateScoreCount();
  $('score-modal').classList.remove('hidden');
  document.body.style.overflow = 'hidden';
  setTimeout(function () { $('score-big').focus(); }, 30);
}

function closeScoreEditor() {
  $('score-modal').classList.add('hidden');
  document.body.style.overflow = '';
  $('abc').focus();
}

function syncScoreFromBig() {
  $('abc').value = $('score-big').value;
  // Fire the event the small box would, so the chart, the length and the save all run.
  $('abc').dispatchEvent(new Event('input'));
  paintScoreView();
  updateScoreCount();
}

function openLyricsEditor() {
  $('lyrics-big').value = $('lyrics').value;
  updateLyricsCount();
  $('lyrics-modal').classList.remove('hidden');
  document.body.style.overflow = 'hidden';
  setTimeout(function () { $('lyrics-big').focus(); }, 30);
}

function closeLyricsEditor() {
  $('lyrics-modal').classList.add('hidden');
  document.body.style.overflow = '';
  $('lyrics').focus();
}

function syncLyricsFromBig() {
  $('lyrics').value = $('lyrics-big').value;
  // Fire the same event the small box would, so saving and the title hint still run.
  $('lyrics').dispatchEvent(new Event('input'));
  updateLyricsCount();
}

function insertTag(tag) {
  var box = $('lyrics-big');
  var text = box.value;
  var start = box.selectionStart;
  var before = text.slice(0, start);
  var prefix = (!before || before.endsWith('\n')) ? '' : '\n';
  var insert = prefix + tag + '\n';
  box.value = before + insert + text.slice(start);
  box.selectionStart = box.selectionEnd = start + insert.length;
  box.focus();
  syncLyricsFromBig();
}

function refreshTitleHint() {
  // An instrumental has no words to borrow a title from.
  if (State.mode === 'inst') { $('title').placeholder = 'Name the piece, or leave blank'; return; }
  var guess = guessTitle($('lyrics').value);
  $('title').placeholder = guess ? 'Leave blank to use: ' + guess : 'Leave blank and the first lyric line is used';
}

var JOB_KINDS = { render: 'Render', plan: 'Score plan', transcribe: 'Transcription', lyrics: 'Lyrics', text: 'Text generation', other: 'Engine job' };

function queueWhat(item) {
  var kind = '<span class="q-kind">' + esc(JOB_KINDS[item.kind] || 'Engine job') + '</span>';
  if (item.outside) {
    return kind + ' <span class="q-outside">from outside the app' + (item.client ? ' (' + esc(item.client) + ')' : '') + '</span>';
  }
  if (!item.title) {
    return kind + ' <span class="q-outside">' + esc(item.note || 'from the app') + '</span>';
  }
  return kind + ' \u00b7 ' + esc(item.title);
}

function queueWhen(item) {
  if (item.state === 'running') { return 'running ' + secs(item.seconds || 0); }
  if (item.state === 'pending') { return 'sent' + (item.seconds ? ', waiting ' + secs(item.seconds) : ''); }
  return 'queued in the app';
}

/* The card shows the job the GPU is on, whoever sent it, and lists what follows.
   The engine shares live progress only with the app that sent a job, so a job from
   outside the app gets a time estimate instead of a stage. */
function paintJob(current, queue, options) {
  var card = $('job-card');
  if (!current && !queue.length) {
    if (State.busy) { State.busy = false; loadTakes(); loadSources(); }
    card.className = 'job hidden';
    return;
  }
  if (current) { State.busy = true; }
  card.className = 'job';
  var head = queue[0] && queue[0].state === 'running' ? queue[0] : null;
  var mineRunning = current && head && !head.outside && head.id === current.id;
  var titles = { render: 'Rendering your song', plan: 'Writing the score plan', transcribe: 'Transcribing the recording',
    lyrics: 'Writing lyrics' };
  // Only the render has an average, measured from this machine's own history.
  // The others show the time they have taken and claim nothing about the rest.
  var average = function (kind) {
    return kind === 'render' ? (options.avg_render_seconds || 0) : 0;
  };
  var rest = queue;
  $('job-stop').style.display = current ? '' : 'none';
  if (current && (mineRunning || !head)) {
    rest = head ? queue.slice(1) : queue.filter(function (item) { return item.id !== current.id; });
    $('job-title').textContent = (titles[current.kind] || 'Working') + (head && head.title ? ': ' + head.title : '');
    var avg = average(current.kind);
    var eta = avg > 0 ? Math.max(0, avg - (current.elapsed || 0)) : 0;
    $('job-time').textContent = secs(current.elapsed) + (eta ? ' / about ' + secs(avg) : '');
    $('job-bar').style.width = Math.max(3, Math.round((current.progress || 0) * 100)) + '%';
    var label = head ? (current.label || 'Starting') : 'Waiting for the engine';
    if (current.value && current.max) { label += ' \u00b7 ' + current.value + '/' + current.max; }
    $('job-stage').textContent = label;
  } else if (head) {
    rest = queue.slice(1);
    $('job-title').textContent = head.outside
      ? 'Engine busy: ' + (JOB_KINDS[head.kind] || 'Engine job').toLowerCase() + ' from outside the app'
      : (titles[head.kind] || 'Working') + (head.title ? ': ' + head.title : '');
    var guess = average(head.kind);
    $('job-time').textContent = secs(head.seconds || 0) + (guess ? ' / about ' + secs(guess) : '');
    $('job-bar').style.width = (guess ? Math.max(3, Math.min(95, Math.round(100 * (head.seconds || 0) / guess))) : 3) + '%';
    $('job-stage').textContent = head.outside
      ? 'Sent by ' + (head.client || 'another program') + '. Its progress is estimated from your average ' + (JOB_KINDS[head.kind] || 'job').toLowerCase() + ' time.'
      : (head.note || 'Working');
  } else {
    $('job-title').textContent = 'Queued';
    $('job-time').textContent = '';
    $('job-bar').style.width = '0%';
    $('job-stage').textContent = 'Waiting for the engine';
  }
  $('job-next').classList.toggle('hidden', !rest.length);
  var html = rest.map(function (item) {
    return '<li><span class="q-what">' + queueWhat(item) + '</span><span class="q-when">' + esc(queueWhen(item)) + '</span></li>';
  }).join('');
  if ($('job-queue').dataset.html !== html) {
    $('job-queue').innerHTML = html;
    $('job-queue').dataset.html = html;
  }
}

/* --------------------------------------------------------------- sources */
async function loadSources() {
  State.sources = await api('/api/sources');
  var select = $('source-select');
  var previous = select.value;
  select.innerHTML = '<option value="">Choose a recording\u2026</option>' + State.sources.map(function (source) {
    var mark = source.has_score ? ' \u2713 score' : '';
    return '<option value="' + source.id + '">' + esc(source.title) + mark + '</option>';
  }).join('');
  if (previous) { select.value = previous; }
  // Spent on use, like the LoRA picker's: left in place it would put the
  // remembered recording back every time another was chosen.
  if (!select.value && State.wantedSource) { select.value = State.wantedSource; }
  State.wantedSource = null;
  // A first visit has nothing to remember, and the newest recording is the one
  // most likely wanted.
  if (!select.value && State.sources.length) { select.value = State.sources[0].id; }
  paintSource();
}

function currentSource() {
  var id = $('source-select').value;
  for (var i = 0; i < State.sources.length; i++) { if (State.sources[i].id === id) { return State.sources[i]; } }
  return null;
}

function paintSource() {
  var source = currentSource();
  var status = $('source-status');
  var badge = $('score-badge');
  paintHearButton();
  paintAudition();
  if (!source) {
    status.textContent = '';
    status.className = 'status';
    badge.textContent = 'no score';
    badge.className = 'badge';
    return;
  }
  badge.className = 'badge' + (source.has_score ? ' ok' : '');
  badge.textContent = source.has_score ? 'score ready' : 'no score';
  var map = { none: 'Not transcribed yet.', queued: 'Queued for transcription.', running: 'Transcribing\u2026', done: 'Transcribed. The score is ready to edit.', failed: 'Transcription failed: ' + (source.transcribe_error || 'unknown error') };
  status.textContent = map[source.transcribe_state] || '';
  status.className = 'status' + (source.transcribe_state === 'failed' ? ' bad' : (source.transcribe_state === 'done' ? ' good' : ''));
  // The box must hold this recording's score or nothing. Comparing ids matters:
  // this tested whether editorSourceId was set at all, so choosing a second
  // recording left the first one's score in the box, and a cover of the second was
  // rendered from the first one's melody.
  if (State.mode === 'cover' && !scoreTakeId() && !boxShowsSource(source.id)) {
    if (source.transcribe_state === 'done') {
      loadScore();
    } else if ($('abc').value.trim()) {
      $('abc').value = '';
      scoreBaseline('');
      setSelection({ formTakeId: Selection.formTakeId });
      setChart('');
      syncEditor();
    }
  }
}

async function deleteSource() {
  var source = currentSource();
  if (!source) { return; }
  var covers = source.take_count ? ' Its ' + source.take_count + ' cover take(s) keep their audio and score, but cannot be rendered again from it.' : '';
  if (!confirm('Delete the recording \u201c' + source.title + '\u201d and its stems?' + covers)) { return; }
  try {
    await api('/api/sources/' + source.id, { method: 'DELETE' });
  } catch (err) {
    $('source-status').textContent = 'Could not delete: ' + err.message;
    $('source-status').className = 'status bad';
    return;
  }
  $('source-select').value = '';
  // The box held this recording's score, or a cover take's copy of it.
  if (boxShowsSource(source.id)) {
    $('abc').value = '';
    scoreBaseline('');
    setChart('');
  }
  claimEditorFor(null);
  await loadSources();
}

async function loadScore() {
  var source = currentSource();
  if (!source) { return; }
  // A take in the editor outranks a source transcription.  Without this guard a
  // finished job (paintJob reloads the sources) overwrites the plan that just
  // landed, and the render button then has nothing to point at.
  if (scoreTakeId()) { return; }
  // Already showing this recording's score: leave the box alone, edits and all.
  // This is the same mistake as in paintSource below it: the test was whether
  // editorSourceId was set, not whether it named THIS recording, so a cover of a
  // second recording was rendered from the first one's melody.
  if (boxShowsSource(source.id)) { return; }
  var selected = selectedTakeId();
  var full = await api('/api/sources/' + source.id);
  // Selecting a cover take switches to cover mode, which starts this load, and the
  // take is loaded into the column before the score arrives.  The take wins.  Going
  // on here cleared leftTakeId, and the next card click then took the take's own
  // words for an unsaved draft.
  if (scoreTakeId() || selectedTakeId() !== selected || currentSource() !== source) { return; }
  $('abc').value = full.abc || '';
  scoreBaseline(full.abc || '');
  // The recording owns the box now, empty score and all, so this does not fetch again.
  setSelection({ formTakeId: null, boxKind: 'source', boxId: source.id });
  setChart('');
}

/* ------------------------------------------------------------------ vocal ---
   YuE2 has no vocal parameter: the model reads a [Tags] block, which is the style
   field, and a [Lyrics] block. So these chips edit the style text itself. That way
   the take stores the choice and a re-render reproduces it. */
var VOCAL_SEX = [
  { value: 'any', label: 'Any', phrase: '' },
  { value: 'female', label: 'Female', phrase: 'female vocal' },
  { value: 'male', label: 'Male', phrase: 'male vocal' },
  { value: 'duet', label: 'Duet', phrase: 'duet, male and female voices' }
];
var VOCAL_TONE = ['breathy', 'raspy', 'powerful', 'soft', 'deep', 'youthful', 'airy', 'gritty'];

function styleHas(text, word) {
  return new RegExp('\\b' + word + '\\b', 'i').test(text);
}

function tidyStyle(text) {
  return text
    .replace(/\s*,\s*,+/g, ', ')
    .replace(/^[\s,]+/, '')
    .replace(/[\s,]+$/, '')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

function currentVocalSex() {
  var style = $('style').value;
  if (/\bduet\b/i.test(style)) { return 'duet'; }
  if (styleHas(style, 'female')) { return 'female'; }
  if (styleHas(style, 'male')) { return 'male'; }
  return 'any';
}

function setVocalSex(value) {
  var option = VOCAL_SEX.filter(function (item) { return item.value === value; })[0] || VOCAL_SEX[0];
  var style = $('style').value
    .replace(/\s*,?\s*(male|female)\s+(vocal|vocals|voice|voices)\b/gi, '')
    .replace(/\s*,?\s*duet\b[^,]*/gi, '');
  style = tidyStyle(style);
  if (option.phrase) { style = style ? style + ', ' + option.phrase : option.phrase; }
  $('style').value = style;
  paintVocals();
}

function toggleVocalTone(word) {
  var style = $('style').value;
  if (styleHas(style, word)) {
    style = style.replace(new RegExp('\\s*,?\\s*' + word + '\\b', 'i'), '');
  } else {
    style = style ? style + ', ' + word : word;
  }
  $('style').value = tidyStyle(style);
  paintVocals();
}

function paintVocals() {
  var sex = currentVocalSex();
  var style = $('style').value;
  $('vocal-sex').innerHTML = VOCAL_SEX.map(function (item) {
    return '<button class="chip' + (item.value === sex ? ' active' : '') + '" data-sex="' + item.value + '">' +
      esc(item.label) + '</button>';
  }).join('');
  $('vocal-tone').innerHTML = VOCAL_TONE.map(function (word) {
    return '<button class="chip' + (styleHas(style, word) ? ' active' : '') + '" data-tone="' + word + '">' +
      esc(word) + '</button>';
  }).join('');
}

var IDENTITIES_LIST = [];
var PERSONAS_LIST = IDENTITIES_LIST;

async function loadVocalIdentities(preferredId, preferredLora) {
  try {
    IDENTITIES_LIST = await api('/api/identities');
  } catch (err) {
    IDENTITIES_LIST = [];
  }
  PERSONAS_LIST = IDENTITIES_LIST;
  var targetId = preferredId !== undefined ? preferredId : (State.savedVocalIdentity || State.savedVocalPersona || '');
  var targetLora = preferredLora !== undefined ? preferredLora : (State.savedVocalIdentityLora || State.savedVocalPersonaLora || '');
  paintVocalIdentitySelect(targetId, targetLora);
}

var loadVocalPersonas = loadVocalIdentities;

function identityName(id) {
  if (!id) { return null; }
  for (var i = 0; i < IDENTITIES_LIST.length; i++) {
    if (IDENTITIES_LIST[i].id === id) { return IDENTITIES_LIST[i].name; }
  }
  return null;
}

var personaName = identityName;

function getIdentityLoRAs(identity) {
  if (!identity) { return []; }
  // The engine's list became a catalogue of entries when the style picker was
  // added; this one only ever wanted the names.
  var allLoras = ((State.options && State.options.loras) || []).map(function (item) {
    return typeof item === 'string' ? item : item.name;
  });
  var trigger = (identity.trigger_word || '').toLowerCase();
  var name = (identity.name || '').toLowerCase().replace(/[^a-z0-9]/g, '');
  var matches = allLoras.filter(function (l) {
    var lower = l.toLowerCase();
    return (trigger && lower.indexOf(trigger) !== -1) || (name && lower.indexOf(name) !== -1);
  });
  matches.sort(function (a, b) {
    var aBest = a.indexOf('_best') !== -1;
    var bBest = b.indexOf('_best') !== -1;
    if (aBest && !bBest) { return -1; }
    if (!aBest && bBest) { return 1; }
    var aStep = (a.match(/step(\d+)/) || [])[1];
    var bStep = (b.match(/step(\d+)/) || [])[1];
    if (aStep && bStep) { return parseInt(bStep, 10) - parseInt(aStep, 10); }
    return a.localeCompare(b);
  });
  return matches;
}

var getPersonaLoRAs = getIdentityLoRAs;

function paintVocalIdentitySelect(currentId, currentLora) {
  var sel = $('vocal-identity') || $('vocal-persona');
  if (!sel) { return; }
  var chosenId = currentId !== undefined ? currentId : sel.value;
  var options = ['<option value="">None (Stock Voice)</option>'];
  IDENTITIES_LIST.forEach(function (p) {
    var label = p.name + ' (' + p.trigger_word + ')';
    options.push('<option value="' + esc(p.id) + '"' + (p.id === chosenId ? ' selected' : '') + '>' + esc(label) + '</option>');
  });
  sel.innerHTML = options.join('');
  if (chosenId) { sel.value = chosenId; }
  updateIdentityLoraSelect(currentLora);
}

var paintVocalPersonaSelect = paintVocalIdentitySelect;

function paintVocalPlanner(value) {
  var wrap = $('vocal-planner-wrap');
  var slider = $('vocal-planner');
  if (!wrap || !slider) { return; }
  var loraSel = $('vocal-identity-lora') || $('vocal-persona-lora');
  var showing = Boolean(loraSel && !loraSel.classList.contains('hidden') && loraSel.value);
  wrap.classList.toggle('hidden', !showing);
  if (value !== undefined && value !== null) { slider.value = value; }
  $('vocal-planner-read').textContent = Number(slider.value).toFixed(2);
}

function updateIdentityLoraSelect(currentLora) {
  var sel = $('vocal-identity') || $('vocal-persona');
  var loraSel = $('vocal-identity-lora') || $('vocal-persona-lora');
  if (!sel || !loraSel) { return; }
  var identity = IDENTITIES_LIST.filter(function (p) { return p.id === sel.value; })[0];
  if (!identity) {
    loraSel.classList.add('hidden');
    loraSel.innerHTML = '';
    paintVocalPlanner();
    return;
  }
  var loras = getIdentityLoRAs(identity);
  if (!loras.length) {
    loraSel.classList.add('hidden');
    loraSel.innerHTML = '';
    paintVocalPlanner();
    return;
  }
  var chosenLora = currentLora || identity.lora || loras[0];
  var opts = loras.map(function (l) {
    var label = l;
    if (l.indexOf('_best') !== -1) {
      label = 'Best';
    } else {
      var m = l.match(/step(\d+)/i);
      if (m) { label = 'Step ' + m[1]; }
    }
    return '<option value="' + esc(l) + '"' + (l === chosenLora ? ' selected' : '') + '>' + esc(label) + '</option>';
  });
  loraSel.innerHTML = opts.join('');
  loraSel.value = chosenLora;
  loraSel.classList.remove('hidden');
  paintVocalPlanner();
  // The picker must not offer what now belongs to this control.
  paintStyleLoras();
}

var updatePersonaLoraSelect = updateIdentityLoraSelect;

function onVocalIdentityChange() {
  var sel = $('vocal-identity') || $('vocal-persona');
  var p = IDENTITIES_LIST.filter(function (item) { return item.id === sel.value; })[0];
  updateIdentityLoraSelect();
  saveForm();
  if (!p) { return; }
  if (p.trigger_word) {
    var style = $('style').value;
    var tw = p.trigger_word.toLowerCase();
    if (!styleHas(style, tw)) {
      style = style ? tw + ', ' + style : tw;
      $('style').value = tidyStyle(style);
      $('style').dataset.touched = '1';
      paintVocals();
    }
  }
  if (p.voice && (p.voice === 'male' || p.voice === 'female') && currentVocalSex() === 'any') {
    setVocalSex(p.voice);
  }
}

var onVocalPersonaChange = onVocalIdentityChange;

/* ---------------------------------------------------------------- settings */
function setting(key, fallback) {
  var value = (State.settings || {})[key];
  return value === undefined || value === null || value === '' ? fallback : value;
}

function paintSettings() {
  var list = State.settingSpec || [];
  $('settings-list').innerHTML = list.map(function (item) {
    var control;
    if (item.type === 'select') {
      control = '<select data-key="' + esc(item.key) + '">' + item.options.map(function (option) {
        return '<option value="' + esc(option.value) + '"' +
          (option.value === item.value ? ' selected' : '') + '>' + esc(option.label) + '</option>';
      }).join('') + '</select>';
    } else {
      control = '<input type="text" spellcheck="false" data-key="' + esc(item.key) + '" value="' + esc(item.value) + '">';
    }
    return '<div class="setting-row">' +
      '<div class="setting-text">' +
        '<div class="setting-label">' + esc(item.label) + '</div>' +
        '<div class="setting-help">' + esc(item.help || '') + '</div>' +
      '</div>' +
      '<div class="setting-control">' + control + '<span class="saved" data-saved="' + esc(item.key) + '"></span></div>' +
    '</div>';
  }).join('');
}

async function saveSetting(input) {
  var key = input.dataset.key;
  var mark = $('settings-list').querySelector('[data-saved="' + key + '"]');
  try {
    var data = await api('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: key, value: input.value })
    });
    adoptSettings(data.settings);
    if (mark) {
      mark.textContent = 'saved';
      setTimeout(function () { if (mark) { mark.textContent = ''; } }, 1800);
    }
  } catch (err) {
    if (mark) { mark.textContent = err.message; mark.style.color = 'var(--bad)'; }
  }
}

function adoptSettings(spec) {
  State.settingSpec = spec || [];
  var values = {};
  State.settingSpec.forEach(function (item) { values[item.key] = item.value; });
  State.settings = values;
}

function openBrandMenu() {
  var menu = $('brand-menu');
  if (menu) { menu.classList.remove('hidden'); }
  var brand = $('brand');
  if (brand) { brand.setAttribute('aria-expanded', 'true'); }
}

function closeBrandMenu() {
  var menu = $('brand-menu');
  if (menu) { menu.classList.add('hidden'); }
  var brand = $('brand');
  if (brand) { brand.setAttribute('aria-expanded', 'false'); }
}

function toggleBrandMenu() {
  var menu = $('brand-menu');
  if (!menu) { return; }
  if (menu.classList.contains('hidden')) {
    openBrandMenu();
  } else {
    closeBrandMenu();
  }
}

function openSettings() {
  closeBrandMenu();
  paintSettings();
  $('settings-note').textContent = '';
  $('settings-modal').classList.remove('hidden');
  document.body.style.overflow = 'hidden';
}

function closeSettings() {
  $('settings-modal').classList.add('hidden');
  document.body.style.overflow = '';
}

/* ------------------------------------------------ lyrics from a recording */
/* Separating a vocal and listening to it takes minutes, so it is asked for, runs
   in the CPU lane beside stems, and shows how far along it is. A recording keeps
   what was heard, so asking twice costs nothing. */
var HEAR = { id: null, timer: 0 };

function paintHearButton() {
  var button = $('source-lyrics');
  if (!button) { return; }
  var source = currentSource();
  button.disabled = !source;
  // The label stays an instruction. "Lyrics heard" read as a status, and a
  // status is not something anyone thinks to press.
  button.title = !source ? 'Choose a recording first'
    : source.has_lyrics ? 'These words were heard in this recording earlier: put them in the box'
    : 'Separate the vocal from this recording and write down what it sings. English recordings only: '
      + 'Whisper hears nothing else, and would write down nonsense.';
}

/* Auditioning the recording itself, through the player at the foot of the page.
   It is not a take, so it owns no score and no card. */
function playRecording() {
  var source = currentSource();
  if (!source) { return; }
  var audio = $('audio');
  if (State.audition === source.id && !audio.paused) {
    audio.pause();
    State.audition = null;
    paintAudition();
    return;
  }
  var url = '/api/sources/' + source.id + '/audio';
  State.loadedId = null;      // a recording is not a take, so Play must not resume one
  State.playing = null;
  State.audition = source.id;
  State.playRequestedAt = Date.now();
  audio.src = url;
  audio.play().catch(function () {});
  $('np-title').textContent = source.title;
  $('np-meta').textContent = 'the recording being covered';
  $('np-cover').className = 'np-cover grad-cover';
  updateMediaSession({ title: source.title, style: 'the recording being covered' });
  loadWave(url, '/api/sources/' + source.id + '/peaks');
  paintTakes();
  paintAudition();
}

function paintAudition() {
  var button = $('audition');
  if (!button) { return; }
  var source = currentSource();
  var playing = Boolean(source && State.audition === source.id && !$('audio').paused);
  button.disabled = !source;
  button.title = !source ? 'Choose a recording first'
    : 'Play this recording through the player, to hear what you are covering';
  button.classList.toggle('on', playing);
}

function paintHearJob(state) {
  var box = $('lyrics-hear-job');
  var running = state && (state.state === 'queued' || state.state === 'running');
  box.classList.toggle('hidden', !running);
  box.classList.remove('bad');
  if (!running) { return; }
  $('lyrics-hear-bar').style.width = Math.round((state.progress || 0) * 100) + '%';
  $('lyrics-hear-stage').textContent = state.stage || 'Waiting';
}

/* A job that fails says so where the bar was, not only in the status line at the
   far end of the panel: a bar that stops at nought reads as a hang. */
function showHearError(message) {
  clearInterval(HEAR.timer);
  HEAR.timer = 0;
  HEAR.id = null;
  var box = $('lyrics-hear-job');
  box.classList.remove('hidden');
  box.classList.add('bad');
  $('lyrics-hear-bar').style.width = '100%';
  $('lyrics-hear-stage').textContent = message;
  paintHearButton();
  paintAudition();
}

function useHeardLyrics(text) {
  var box = $('lyrics');
  if (box.value.trim() && box.value.trim() !== text.trim()) {
    if (!confirm('Replace the lyrics in the box with the words heard in the recording?')) { return; }
  }
  box.value = text;
  State.formEdited = true;
  saveForm();
  refreshTitleHint();
}

async function pollHear(id) {
  var state;
  try {
    state = await api('/api/sources/' + id + '/lyrics');
  } catch (err) {
    showHearError('Lost touch with the job: ' + err.message);
    return;
  }
  paintHearJob(state);
  if (state.state === 'done') {
    stopHearPoll();
    if (state.lyrics) { useHeardLyrics(state.lyrics); }
    statusLine('Wrote down what the recording sings. Read it before you plan.', 'good');
    loadSources();
  } else if (state.state === 'failed') {
    showHearError(state.error === 'cancelled' ? 'Stopped.' : 'Could not hear the words: ' + (state.error || 'unknown'));
  }
}

function stopHearPoll() {
  clearInterval(HEAR.timer);
  HEAR.timer = 0;
  HEAR.id = null;
  paintHearJob(null);
  paintHearButton();
  paintAudition();
}

async function hearLyrics() {
  var source = currentSource();
  if (!source) { return; }
  // Already written down: nothing to run.
  var state = await api('/api/sources/' + source.id + '/lyrics');
  if (state.state === 'done' && state.lyrics) {
    useHeardLyrics(state.lyrics);
    statusLine('These words were heard in the recording earlier.', 'good');
    return;
  }
  await api('/api/sources/' + source.id + '/lyrics', { method: 'POST' });
  HEAR.id = source.id;
  paintHearJob({ state: 'queued', progress: 0, stage: 'Waiting' });
  clearInterval(HEAR.timer);
  HEAR.timer = setInterval(function () { pollHear(source.id); }, 1500);
}

/* ------------------------------------------------------------------- stems */
/* Builds the model and format lists, then the stem checkboxes for the chosen model.
   Preferred values come from Settings when the sheet opens, and are left alone when
   the user changes the model by hand. The lists must exist before a value is set on
   them, or the assignment is silently dropped. */
function paintStemChoices(preferred) {
  var options = State.stemsOptions || {};
  var models = options.models || [];
  var select = $('stems-model');
  var formatSelect = $('stems-format');
  var firstFill = select.dataset.filled !== '1';
  if (firstFill) {
    select.innerHTML = models.map(function (m) {
      return '<option value="' + esc(m.id) + '">' + esc(m.label) + '</option>';
    }).join('');
    formatSelect.innerHTML = (options.formats || ['wav']).map(function (f) {
      return '<option value="' + esc(f) + '">' + (f === 'mp3' ? 'mp3, 320 kbps' : esc(f)) + '</option>';
    }).join('');
    select.dataset.filled = '1';
  }
  if (preferred && preferred.model) {
    select.value = preferred.model;
  } else if (firstFill) {
    select.value = setting('stems.model', options.default_model || 'htdemucs');
  }
  if (preferred && preferred.format) {
    formatSelect.value = preferred.format;
  } else if (firstFill) {
    formatSelect.value = setting('stems.format', options.default_format || 'wav');
  }
  var chosen = null;
  for (var i = 0; i < models.length; i++) { if (models[i].id === select.value) { chosen = models[i]; } }
  if (!chosen) { chosen = models[0] || { stems: [] }; }
  var all = [];
  models.forEach(function (m) { m.stems.forEach(function (s) { if (all.indexOf(s) < 0) { all.push(s); } }); });
  $('stems-list').innerHTML = all.map(function (name) {
    var on = chosen.stems.indexOf(name) >= 0;
    return '<label class="stem-choice' + (on ? '' : ' off') + '">' +
      '<input type="checkbox" value="' + esc(name) + '"' + (on ? ' checked' : ' disabled') + '> ' + esc(name) + '</label>';
  }).join('');
}

/* target: { kind: 'take' | 'source', id, title } */
function openStemsModal(target) {
  var options = State.stemsOptions || {};
  if (!options.available) {
    statusLine('Stem separation is not available in this container.', 'bad');
    return;
  }
  State.stemsTarget = target;
  $('stems-heading').textContent = 'Extract stems: ' + target.title;
  // Settings decide what a new run starts with; the sheet can still override.
  $('stems-dir').value = setting('stems.folder', options.default_dir || '/data/stems');
  paintStemChoices({
    model: setting('stems.model', options.default_model || 'htdemucs'),
    format: setting('stems.format', options.default_format || 'wav')
  });
  var estimate = options.avg_seconds
    ? 'The last run took ' + Math.round(options.avg_seconds) + ' seconds.'
    : 'A four minute song takes about three minutes.';
  $('stems-note').textContent = 'Runs on this machine on ' + (options.threads || 4) + ' CPU threads, so the GPU stays free for renders. ' + estimate;
  $('stems-modal').classList.remove('hidden');
  document.body.style.overflow = 'hidden';
}

function closeStemsModal() {
  $('stems-modal').classList.add('hidden');
  document.body.style.overflow = '';
  State.stemsTarget = null;
}

async function runStems() {
  var target = State.stemsTarget;
  if (!target) { return; }
  var wanted = Array.prototype.slice.call($('stems-list').querySelectorAll('input:checked'))
    .map(function (box) { return box.value; });
  if (!wanted.length) {
    $('stems-note').textContent = 'Choose at least one stem.';
    return;
  }
  $('stems-run').disabled = true;
  try {
    var base = target.kind === 'source' ? '/api/sources/' : '/api/takes/';
    await api(base + target.id + '/stems', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: $('stems-model').value,
        stems: wanted,
        format: $('stems-format').value,
        save_dir: $('stems-dir').value
      })
    });
    closeStemsModal();
    loadTakes();
  } catch (err) {
    $('stems-note').textContent = 'Could not start: ' + err.message;
  } finally {
    $('stems-run').disabled = false;
  }
}

function playStem(setId, file) {
  var audio = $('audio');
  State.loadedId = null;   // a stem is not a take, so Play must not resume a take
  State.playing = null;
  State.audition = null;
  wave.kind = null;        // and it gets the neutral tone
  audio.src = '/api/stem-sets/' + setId + '/' + encodeURIComponent(file);
  audio.play().catch(function () {});
  $('np-title').textContent = file.replace(/\.[a-z0-9]+$/i, '');
  $('np-meta').textContent = 'stem from take ' + setId;
  $('np-cover').className = 'np-cover grad-cover';
  loadWave(audio.src, '/api/stem-sets/' + setId + '/' + encodeURIComponent(file) + '/peaks');
}

/* ------------------------------------------------------ song mode and plans */
function statusLine(message, kind) {
  var node = $('render-status');
  node.textContent = message;
  node.className = 'status' + (kind ? ' ' + kind : '');
}

/* ---------------------------------------------------------------- harmony ---
   How predictable the chords of a score plan are. Each step is a setting of the
   engine's yue2_harmony node; the server holds the mapping, and these are only the
   words. Songs from a prompt only: a cover takes its chords from the recording. */
var HARMONY_WORDS = ['Familiar', 'Varied', 'Colourful', 'Adventurous', 'Outside'];
var HARMONY_HINTS = [
  'YuE2\u2019s own chords. Often one four-chord loop for the whole song.',
  'Avoids repeating the same chords. Stays in the key.',
  'Verse and chorus get different progressions, with richer chords.',
  'Keeps the harmony moving, and borrows chords from outside the key.',
  'Adventurous, and reaches further outside the key.'
];

function harmonyStep() {
  var step = parseInt($('harmony').value, 10);
  return isNaN(step) ? 0 : Math.max(0, Math.min(HARMONY_WORDS.length - 1, step));
}

function paintHarmony() {
  var available = State.options.harmony_available !== false;
  var step = harmonyStep();
  $('harmony').disabled = !available;
  $('harmony-word').textContent = HARMONY_WORDS[step];
  $('harmony-hint').textContent = available
    ? HARMONY_HINTS[step]
    : 'The engine has no harmony node. Rebuild the engine to use this.';
}

function setMode(mode) {
  State.mode = mode;
  Array.prototype.forEach.call(document.querySelectorAll('.modes .mode'), function (button) {
    button.classList.toggle('active', button.dataset.mode === mode);
  });
  var cover = mode === 'cover';
  var inst = mode === 'inst';
  var show = function (id, on) { $(id).style.display = on ? '' : 'none'; };
  show('cover-only', cover);
  show('lyrics-write', mode === 'song');
  // It acts on a recording, so it lives with the recording's own buttons, which
  // the whole cover-only block already shows and hides.
  show('auto-wrap', !cover);
  // Both steer the score writer, which a cover never uses: its score is the transcription.
  show('harmony-field', !cover);
  show('variety-field', !cover);
  show('plan-actions', !cover);
  // An instrumental has no words and no voice; its structure takes the lyrics' place.
  show('lyrics-field', !inst);
  show('vocal-field', !inst);
  show('structure-field', inst);
  show('mode-field', !inst);
  $('headline').textContent = cover ? 'Cover a song' : (inst ? 'Write an instrumental' : 'Write a song');
  $('sub').textContent = cover
    ? 'Your own recording in. A new arrangement, new vocals, and an editable score out.'
    : inst ? 'Style and structure in. YuE2 writes the melody and the chords, then plays it with no vocal.'
    : 'Style and lyrics in. YuE2 writes the melody and the chords, then sings it.';
  $('score-label').textContent = cover ? 'Score' : 'Score plan';
  show('create-cover', cover);
  show('create-song', mode === 'song');
  show('create-inst', inst);
  $('start-fresh').textContent = cover ? 'New cover' : (inst ? 'New instrumental' : 'New song');
  refreshTitleHint();
  paintPresets();
  if (inst) { paintStructure(); paintFeel(); }
  $('source-status').textContent = '';
  var ownedByTake = Boolean(takeIdInEditor());
  if (cover) {
    claimEditorFor(null);
    $('score-badge').textContent = 'no score';
    $('score-badge').className = 'badge';
    paintSource();
  } else if (!ownedByTake) {
    // The editor held a transcription of an uploaded recording. A song must not reuse it.
    $('abc').value = '';
    setSelection({});
    $('score-badge').textContent = 'no plan yet';
    $('score-badge').className = 'badge';
    setChart('');
    statusLine('Write a score plan to start a song from scratch.');
  }
}

/* The working score and the take it belongs to survive a reload, so the render
   button still knows what it is rendering. */
function saveWorkingScore() {
  try {
    localStorage.setItem('yue2.abc', $('abc').value);
    localStorage.setItem('yue2.take', takeIdInEditor() || '');
  } catch (err) { /* private mode */ }
}

function loadWorkingScore() {
  var abc = null;
  var id = null;
  try {
    abc = localStorage.getItem('yue2.abc');
    id = localStorage.getItem('yue2.take');
  } catch (err) { return; }
  if (abc) { $('abc').value = abc; scoreBaseline(abc); }
  if (id) {
    // The box holds this take's score, and the form describes it.
    restoreSelection({ formTakeId: id, boxKind: 'take', boxId: id });
  }
}

/* Say why the buttons are unusable instead of doing nothing when clicked. */
/* The Save score button says when there is something to save, and says so when it
   has saved. The baseline is the text the editor last loaded or saved, so a plan
   that arrives from the engine counts as already saved. */
function scoreBaseline(text) {
  State.savedAbc = text || '';
  paintScoreDirty();
}

function scoreIsDirty() {
  if (!State.savedAbc) { return false; }
  return ($('abc').value || '') !== State.savedAbc;
}

function paintScoreDirty() {
  var button = $('save-score');
  if (!button || button.dataset.confirming === '1') { return; }
  var dirty = scoreIsDirty();
  button.classList.toggle('needs-save', dirty);
  button.textContent = dirty ? 'Save score' : 'Saved';
  button.title = dirty ? 'This score has changes that are not saved yet'
                       : 'No changes since the last save';
  button.disabled = !dirty;
}

function confirmScoreSaved() {
  var button = $('save-score');
  button.dataset.confirming = '1';
  button.classList.remove('needs-save');
  button.textContent = 'Saved';
  button.disabled = true;
  setTimeout(function () {
    delete button.dataset.confirming;
    paintScoreDirty();
  }, 1600);
}

function setScoreActions() {
  var enabled = Boolean(takeIdInEditor());
  ['render-take', 'reroll'].forEach(function (name) {
    var node = $(name);
    node.disabled = !enabled;
    node.style.opacity = enabled ? '' : '0.45';
    node.style.cursor = enabled ? '' : 'not-allowed';
  });
  $('score-note').textContent = enabled
    ? 'Render this score makes audio from the score above, keeping its melody and chords. Write a new plan asks YuE2 for a different melody, same words.'
    : 'Nothing to render yet. Write a score plan, or press Score on a take in the library.';
}

function syncEditor() {
  saveWorkingScore();
  setScoreActions();
}

/* Which take owns the score currently in the box.  A take we are still waiting on
   does NOT own it: there is nothing to render until its score arrives. */
function takeIdInEditor() {
  return scoreTakeId() || '';
}

function claimEditorFor(takeId) {
  setSelection({ formTakeId: takeId || null, boxKind: takeId ? 'take' : 'none', boxId: takeId || null });
}

function stopAwaiting() {
  if (!Selection.awaiting) { return; }
  setSelection({ formTakeId: Selection.formTakeId, boxKind: Selection.boxKind, boxId: Selection.boxId });
}

async function watchPlan() {
  var waiting = awaitingPlanId();
  if (!waiting) { return; }
  var take;
  try {
    take = await api('/api/takes/' + waiting);
  } catch (err) {
    stopAwaiting();
    return;
  }
  if (take.abc && take.abc.length > 50 && scoreTakeId() !== take.id) {
    $('abc').value = take.abc;
    scoreBaseline(take.abc);
    // The plan is here, so the take owns the box from now on.
    setSelection({ formTakeId: take.id, boxKind: 'take', boxId: take.id });
    $('score-badge').textContent = 'plan ready';
    $('score-badge').className = 'badge ok';
    $('score-box').open = true;
    setChart(chordChart(take.abc));
    showPlanLength(take.abc);
    statusLine('Plan ready. Edit it, or press render.', 'good');
    loadTakes();
    return;
  }
  if (take.status === 'failed') {
    statusLine('Plan failed: ' + (take.error || 'unknown error'), 'bad');
    stopAwaiting();
    loadTakes();
  } else if (take.status === 'planned' || take.status === 'done') {
    // It finished between two polls: if the box never received the plan, it is
    // still on the take, and the call above will have filled it.
    stopAwaiting();
    loadTakes();
  }
}

async function doPlan() {
  if (!$('lyrics').value.trim()) {
    statusLine('Write some lyrics first. The planner needs words to shape the melody.', 'bad');
    return;
  }
  var seed = parseInt($('seed').value, 10);
  if (!($('seed-fixed').checked) || isNaN(seed)) {
    seed = Math.floor(Math.random() * 4294967295);
    $('seed').value = seed;
  }
  statusLine('Queued…');
  try {
    var identitySel = $('vocal-identity') || $('vocal-persona');
    var idVal = identitySel ? identitySel.value : null;
    var loraSel = $('vocal-identity-lora') || $('vocal-persona-lora');
    var vLora = (idVal && loraSel && !loraSel.classList.contains('hidden')) ? loraSel.value : null;
    var take = await api('/api/songs', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(withStyleLora({
        title: $('title').value.trim() || guessTitle($('lyrics').value),
        style: $('style').value,
        lyrics: $('lyrics').value,
        seed: seed,
        interpretation: $('interpretation').value,
        max_duration: parseFloat($('max-duration').value) || 360,
        auto_render: $('auto-render').checked,
        variety: $('variety').value,
        harmony: harmonyStep(),
        space_id: State.spaceId,
        realaudio: $('realaudio').checked,
        identity_id: idVal || null,
        persona_id: idVal || null,
        voice_lora: vLora || null,
        voice_lora_clip: vocalPlanner()
      }))
    });
    setSelection({ formTakeId: take.id, boxKind: 'none', boxId: null, awaiting: take.id });
    statusLine('Writing the score plan…');
    loadTakes();
  } catch (err) {
    statusLine('Could not start: ' + err.message, 'bad');
  }
}

async function doRenderTake() {
  var id = takeIdInEditor();
  if (!id) {
    statusLine('Nothing to render yet. Write a score plan first.', 'bad');
    $('score-note').textContent = 'Nothing to render yet. Write a score plan, or press Score on a take in the library.';
    return;
  }
  try {
    await api('/api/takes/' + id + '/score', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ abc: $('abc').value })
    });
    // The Interpretation menu applies to this render.
    var identitySel = $('vocal-identity') || $('vocal-persona');
    var idVal = identitySel ? identitySel.value : null;
    var loraSel = $('vocal-identity-lora') || $('vocal-persona-lora');
    var vLora = (idVal && loraSel && !loraSel.classList.contains('hidden')) ? loraSel.value : null;
    await api('/api/takes/' + id + '/render', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        interpretation: $('interpretation').value,
        realaudio: $('realaudio').checked,
        identity_id: idVal || null,
        persona_id: idVal || null,
        voice_lora: vLora || null,
        voice_lora_clip: vocalPlanner()
      })
    });
    setSelection({ formTakeId: takeIdInEditor() || selectedTakeId(), boxKind: 'take', boxId: takeIdInEditor() || selectedTakeId() });
    statusLine('Rendering…');
    loadTakes();
  } catch (err) {
    statusLine('Could not render: ' + err.message, 'bad');
  }
}

/* A new plan is on its way for this take.  The old score leaves the box and the
   take gives up the editor, so watchPlan loads the new plan when it lands instead
   of treating the old one as current. */
function awaitNewPlan(id) {
  $('abc').value = '';
  scoreBaseline('');
  // The take is what the form describes, but it owns nothing until the plan lands.
  setSelection({ formTakeId: id, boxKind: 'none', boxId: null, awaiting: id });
  $('score-badge').textContent = 'writing a new plan';
  $('score-badge').className = 'badge';
  setChart('');
  showPlanLength('');
}

async function doReroll() {
  var id = takeIdInEditor();
  if (!id) { statusLine('Nothing to replan yet.', 'bad'); setScoreActions(); return; }
  try {
    // The slider and the variety menu apply to the new plan.
    await api('/api/takes/' + id + '/replan', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ harmony: harmonyStep(), variety: $('variety').value })
    });
    awaitNewPlan(id);
    statusLine('Writing a new plan for the same words\u2026');
    loadTakes();
  } catch (err) {
    statusLine('Could not replan: ' + err.message, 'bad');
  }
}

/* ------------------------------------------------------------------ takes */
async function loadTakes() {
  var space = State.spaceId;
  var url = '/api/takes?limit=' + State.takeLimit + '&space_id=' + encodeURIComponent(space) +
    (State.filter === 'favourite' ? '&favourite=true' : '');
  var response = await fetch(url, { cache: 'no-cache' });   // revalidates: unchanged is a 304
  if (!response.ok) { return; }
  var text = await response.text();
  // The space changed while this was on its way: the answer belongs to the old one.
  if (space !== State.spaceId) { return; }
  if (text !== State.takesRaw) { loadSpaces(); }   // the counts in the menu may have moved
  State.takesAt = Date.now();
  State.takesTotal = parseInt(response.headers.get('X-Total-Count') || '0', 10) || 0;
  // Nothing new: leave the cards alone, so hover, focus and the play pulse survive.
  // Repaint once a minute anyway, so "2 min ago" keeps moving.
  if (text === State.takesRaw && Date.now() - State.paintedAt < 60000) { return; }
  State.takesRaw = text;
  State.takes = JSON.parse(text);
  paintTakes();
  noticeSinging();
}

/* An instrumental that came out singing is worth interrupting for once: the
   render has just been paid for, and the answer is a click away. Only for one
   that finished a moment ago, only once per take, and never over another open
   window. Anything older is left to say so on its card. */
function noticeSinging() {
  if (!State.sungSeen) { State.sungSeen = {}; }
  var now = Date.now() / 1000;
  for (var i = 0; i < State.takes.length; i++) {
    var take = State.takes[i];
    if (take.kind !== 'instrumental' || take.status !== 'done') { continue; }
    if (!(take.vocal_check >= 0.1) || State.sungSeen[take.id]) { continue; }
    State.sungSeen[take.id] = true;
    if (now - (take.finished_at || 0) > 300) { continue; }        // not fresh
    if (document.querySelector('.modal:not(.hidden)')) { continue; }
    openSungWarning(take);
    return;
  }
}

/* ----------------------------------------------------------------- spaces
   Each take lives in one space. Which space is on show is this browser's choice. */
async function loadSpaces() {
  var spaces = await api('/api/spaces');
  State.spaces = spaces;
  if (!spaces.some(function (space) { return space.id === State.spaceId; })) {
    showSpace('default');   // deleted elsewhere, or never existed here
  }
  paintSpaces();
}

function currentSpace() {
  return State.spaces.filter(function (space) { return space.id === State.spaceId; })[0] || null;
}

function paintSpaces() {
  var select = $('space');
  var html = State.spaces.map(function (space) {
    return '<option value="' + esc(space.id) + '">' + esc(space.name) + ' (' + space.takes + ')</option>';
  }).join('');
  if (select.dataset.html !== html) {
    select.innerHTML = html;
    select.dataset.html = html;
  }
  select.value = State.spaceId;
  $('space-delete').disabled = State.spaceId === 'default';
  var space = currentSpace();
  $('takes-heading').textContent = space ? space.name : 'Your takes';
}

function showSpace(id) {
  if (id === State.spaceId) { return; }
  State.spaceId = id;
  try { localStorage.setItem(SPACE_KEY, id); } catch (err) { /* private mode */ }
  State.takes = [];
  State.takesRaw = '';
  State.takesTotal = 0;
  State.takeLimit = 300;
  paintSpaces();
  paintTakes();
  loadTakes();
}

function loadSpaceChoice() {
  try { State.spaceId = localStorage.getItem(SPACE_KEY) || 'default'; } catch (err) { State.spaceId = 'default'; }
}

async function newSpace() {
  var name = prompt('Name the new space');
  if (name === null || !name.trim()) { return; }
  try {
    var space = await api('/api/spaces', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name })
    });
    State.spaces.push(space);
    showSpace(space.id);
    await loadSpaces();
    statusLine('New space ' + space.name + '. Takes you create now land here.', 'good');
  } catch (err) {
    statusLine('Could not create the space: ' + err.message, 'bad');
  }
}

async function renameSpace() {
  var space = currentSpace();
  if (!space) { return; }
  var name = prompt('Rename the space', space.name);
  if (name === null || !name.trim() || name.trim() === space.name) { return; }
  try {
    await api('/api/spaces/' + space.id, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name })
    });
    await loadSpaces();
  } catch (err) {
    statusLine('Could not rename the space: ' + err.message, 'bad');
  }
}

async function deleteSpace() {
  var space = currentSpace();
  if (!space || space.id === 'default') { return; }
  var held = space.takes ? ' Its ' + space.takes + ' take' + (space.takes === 1 ? '' : 's') + ' move to Default.' : '';
  if (!confirm('Delete the space \u201c' + space.name + '\u201d?' + held)) { return; }
  try {
    await api('/api/spaces/' + space.id, { method: 'DELETE' });
    showSpace('default');
    await loadSpaces();
  } catch (err) {
    statusLine('Could not delete the space: ' + err.message, 'bad');
  }
}

function openMoveModal(take) {
  State.moveTakeId = take.id;
  $('move-heading').textContent = 'Move \u201c' + take.title + '\u201d to';
  $('move-name').value = '';
  $('move-status').textContent = '';
  $('move-list').innerHTML = State.spaces.map(function (space) {
    var here = space.id === take.space_id;
    return '<button class="ghost" data-space="' + esc(space.id) + '"' + (here ? ' disabled' : '') + '>' +
      '<span>' + esc(space.name) + '</span><span class="muted">' +
      (here ? 'here now' : space.takes + ' take' + (space.takes === 1 ? '' : 's')) + '</span></button>';
  }).join('');
  $('move-modal').classList.remove('hidden');
}

function closeMoveModal() {
  State.moveTakeId = null;
  $('move-modal').classList.add('hidden');
}

async function moveTake(spaceId) {
  var id = State.moveTakeId;
  if (!id) { return; }
  var moved = await api('/api/takes/' + id + '/move', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ space_id: spaceId })
  });
  closeMoveModal();
  statusLine('Moved to ' + moved.name + '.', 'good');
  loadTakes();
  loadSpaces();
}

/* Style presets: songs name a voice, instrumentals name the lead instrument. */
var PRESETS = {
  vocal: [
    'English, warm indie rock, expressive male vocal, guitars, bass, drums, 110 BPM',
    'English, soulful jazz-pop, expressive male vocal, Rhodes, upright bass, brushed drums, 88 BPM',
    'English, synthwave, female vocal, analog pads, gated drums, 100 BPM',
    'English, acoustic ballad, intimate vocal, fingerpicked guitar, strings',
    'English, heavy rock, gritty male vocal, distorted guitars, driving drums'
  ],
  inst: [
    'cinematic, ambient, piano, strings, slow build, 70 BPM',
    'lo-fi hip hop, Rhodes, vinyl crackle, mellow drums, 85 BPM',
    'surf rock, twangy lead guitar, spring reverb, driving drums, 160 BPM',
    'synthwave, analog synth lead, arpeggios, gated drums, 110 BPM',
    'jazz trio, piano, upright bass, brushed drums, swing, 120 BPM'
  ]
};

function paintPresets() {
  var list = State.mode === 'inst' ? PRESETS.inst : PRESETS.vocal;
  var html = list.map(function (text) {
    var label = State.mode === 'inst' ? text.split(',')[0] : (text.split(',')[1] || text);
    return '<button class="chip" data-preset="' + esc(text) + '">' + esc(label.trim()) + '</button>';
  }).join('');
  if ($('presets').dataset.html !== html) { $('presets').innerHTML = html; $('presets').dataset.html = html; }
}

/* ------------------------------------------------------ instrumental structure
   What goes into the lyrics slot for an instrumental: [instrumental], a list of
   section tags, or tags with times.  The LoRA only knows these six sections. */
var SECTIONS = ['intro', 'verse', 'pre-chorus', 'chorus', 'bridge', 'outro'];
/* How firmly the instrumental LoRA holds the model: Steady at full strength, Varied a little looser. */
/* There was a Feel control here, loosening the instrumental LoRA for more
   movement between sections. Measured at real song lengths, any loosening let
   the vocal back in, so it is gone: instrumentals always render at full
   strength. Takes made while it existed keep their saved feel, which now
   renders the same as Steady. */
var FEELS = { steady: 'Sticks to its loop: repetitive and laid-back.' };
var FEEL = { value: 'steady' };

function paintFeel() {}
var SECTION_SECONDS = { intro: 15, verse: 30, 'pre-chorus': 15, chorus: 25, bridge: 20, outro: 15 };
var STRUCTURE = {
  kind: 'free',
  sections: ['intro', 'verse', 'chorus', 'verse', 'chorus', 'bridge', 'chorus', 'outro'].map(function (name) {
    return { name: name, seconds: SECTION_SECONDS[name] };
  })
};

function clock(total) {
  var m = Math.floor(total / 60);
  var s = Math.round(total % 60);
  return m + ':' + (s < 10 ? '0' : '') + s;
}

function structureText() {
  if (STRUCTURE.kind === 'free') { return '[instrumental]'; }
  var at = 0;
  return STRUCTURE.sections.map(function (item) {
    if (STRUCTURE.kind === 'sections') { return '[' + item.name + ']'; }
    var tag = '[' + item.name + ' ' + clock(at) + '-' + clock(at + item.seconds) + ']';
    at += item.seconds;
    return tag;
  }).join('\n');
}

/* An instrumental take's structure back into the builder: '[instrumental]', tags, or
   tags with times.  Lengths come from the times when there are any. */
function loadStructure(text) {
  var lines = String(text || '').split('\n').map(function (line) { return line.trim(); }).filter(Boolean);
  var parsed = [];
  var timed = false;
  lines.forEach(function (line) {
    var m = /^\[([a-z-]+)(?:\s+(\d+):(\d\d)-(\d+):(\d\d))?\]$/.exec(line);
    if (!m || SECTIONS.indexOf(m[1]) < 0) { return; }
    var seconds = SECTION_SECONDS[m[1]];
    if (m[2] !== undefined) {
      timed = true;
      seconds = (Number(m[4]) * 60 + Number(m[5])) - (Number(m[2]) * 60 + Number(m[3]));
    }
    parsed.push({ name: m[1], seconds: seconds });
  });
  if (parsed.length) {
    STRUCTURE.sections = parsed;
    STRUCTURE.kind = timed ? 'timed' : 'sections';
  } else {
    STRUCTURE.kind = 'free';
  }
  paintStructure();
}

async function doInstrumental() {
  if (STRUCTURE.kind !== 'free' && !STRUCTURE.sections.length) {
    statusLine('Add at least one section, or choose Let YuE2 decide.', 'bad');
    return;
  }
  var seed = parseInt($('seed').value, 10);
  if (!($('seed-fixed').checked) || isNaN(seed)) {
    seed = Math.floor(Math.random() * 4294967295);
    $('seed').value = seed;
  }
  statusLine('Queued\u2026');
  try {
    var take = await api('/api/instrumentals', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(withStyleLora({
        title: $('title').value.trim(),
        style: $('style').value,
        structure: structureText(),
        seed: seed,
        interpretation: $('interpretation').value,
        feel: FEEL.value,
        max_duration: parseFloat($('max-duration').value) || 360,
        auto_render: $('auto-render').checked,
        variety: $('variety').value,
        harmony: harmonyStep(),
        space_id: State.spaceId,
        realaudio: $('realaudio').checked
      }))
    });
    setSelection({ formTakeId: take.id, boxKind: 'none', boxId: null, awaiting: take.id });
    statusLine('Writing the score plan\u2026');
    loadTakes();
  } catch (err) {
    statusLine('Could not start: ' + err.message, 'bad');
  }
}

function paintStructure() {
  Array.prototype.forEach.call(document.querySelectorAll('#structure-kind button'), function (button) {
    button.classList.toggle('active', button.dataset.kind === STRUCTURE.kind);
  });
  var body = $('structure-body');
  var total = STRUCTURE.sections.reduce(function (sum, item) { return sum + item.seconds; }, 0);
  var cap = parseFloat($('max-duration').value) || 360;
  $('structure-total').textContent = STRUCTURE.kind === 'timed' ? clock(total) + ' in all' + (total > cap ? ', longer than the length cap' : '') : '';
  $('structure-total').classList.toggle('over', STRUCTURE.kind === 'timed' && total > cap);
  if (STRUCTURE.kind === 'free') {
    body.innerHTML = '<p class="struct-note">YuE2 chooses the sections and how long each one runs.</p>';
  } else {
    var at = 0;
    var rows = STRUCTURE.sections.map(function (item, index) {
      var options = SECTIONS.map(function (name) {
        return '<option value="' + name + '"' + (name === item.name ? ' selected' : '') + '>' + name + '</option>';
      }).join('');
      var timed = '';
      if (STRUCTURE.kind === 'timed') {
        timed = '<input type="number" min="4" max="180" step="1" value="' + item.seconds + '" data-row="' + index + '" data-field="seconds" title="Seconds">' +
          '<span class="struct-time">' + clock(at) + '\u2013' + clock(at + item.seconds) + '</span>';
        at += item.seconds;
      }
      return '<li class="struct-row"><select data-row="' + index + '" data-field="name">' + options + '</select>' + timed +
        '<button class="struct-btn" data-row="' + index + '" data-move="-1" title="Move up">\u2191</button>' +
        '<button class="struct-btn" data-row="' + index + '" data-move="1" title="Move down">\u2193</button>' +
        '<button class="struct-btn" data-row="' + index + '" data-remove="1" title="Remove">\u00d7</button></li>';
    }).join('');
    var adds = SECTIONS.map(function (name) {
      return '<button class="chip" data-add="' + name + '">+ ' + name + '</button>';
    }).join('');
    body.innerHTML = '<ol class="struct-list">' + rows + '</ol><div class="struct-add">' + adds + '</div>' +
      (STRUCTURE.kind === 'sections' ? '<p class="struct-note">YuE2 chooses how long each section runs.</p>' : '');
  }
  $('structure-preview').textContent = structureText().replace(/\n/g, ' ');
  saveForm();
}

function wireStructure() {
  $('structure-kind').addEventListener('click', function (event) {
    var button = event.target.closest('[data-kind]');
    if (!button) { return; }
    STRUCTURE.kind = button.dataset.kind;
    paintStructure();
  });
  $('structure-body').addEventListener('click', function (event) {
    var button = event.target.closest('button');
    if (!button) { return; }
    var list = STRUCTURE.sections;
    if (button.dataset.add) {
      list.push({ name: button.dataset.add, seconds: SECTION_SECONDS[button.dataset.add] });
    } else if (button.dataset.remove) {
      list.splice(Number(button.dataset.row), 1);
    } else if (button.dataset.move) {
      var from = Number(button.dataset.row);
      var to = from + Number(button.dataset.move);
      if (to < 0 || to >= list.length) { return; }
      list.splice(to, 0, list.splice(from, 1)[0]);
    }
    paintStructure();
  });
  $('structure-body').addEventListener('change', function (event) {
    var field = event.target.dataset.field;
    if (!field) { return; }
    var item = STRUCTURE.sections[Number(event.target.dataset.row)];
    if (field === 'name') { item.name = event.target.value; }
    if (field === 'seconds') { item.seconds = Math.max(4, Math.min(180, Math.round(Number(event.target.value) || 0))); }
    paintStructure();
  });
  $('max-duration').addEventListener('input', function () { if (State.mode === 'inst') { paintStructure(); } });
  $('create-inst').addEventListener('click', doInstrumental);
}

/* ---------------------------------------------------------------- variations
   The same score and seed, rendered in other interpretations, each as a new take. */
var VARIATIONS = { take: null };

function openVariations(take) {
  VARIATIONS.take = take;
  $('variations-heading').textContent = 'Variations of \u201c' + take.title + '\u201d';
  var own = INTERPRETATIONS[take.interpretation] ? take.interpretation : 'standard';
  $('variations-list').innerHTML = Object.keys(INTERPRETATIONS).filter(function (key) { return key !== own; })
    .map(function (key) {
      return '<label><input type="checkbox" value="' + key + '" checked><strong>' + INTERPRETATIONS[key].name +
        '</strong><span class="muted">' + esc(INTERPRETATIONS[key].hint) + '</span></label>';
    }).join('');
  $('variations-status').textContent = '';
  paintVariationsEstimate();
  $('variations-modal').classList.remove('hidden');
}

function closeVariations() {
  VARIATIONS.take = null;
  $('variations-modal').classList.add('hidden');
}

function chosenVariations() {
  return Array.prototype.map.call(document.querySelectorAll('#variations-list input:checked'), function (box) { return box.value; });
}

function paintVariationsEstimate() {
  var count = chosenVariations().length;
  var average = State.options.avg_render_seconds || 0;
  $('variations-go').disabled = !count;
  $('variations-go').textContent = count === 1 ? 'Render 1 variation' : 'Render ' + count + ' variations';
  $('variations-estimate').textContent = count && average ? 'about ' + Math.max(1, Math.round(count * average / 60)) + ' min of rendering' : '';
}

async function doVariations() {
  var take = VARIATIONS.take;
  var chosen = chosenVariations();
  if (!take || !chosen.length) { return; }
  try {
    var reply = await api('/api/takes/' + take.id + '/variations', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ interpretations: chosen })
    });
    closeVariations();
    statusLine('Queued ' + reply.created.length + ' variation' + (reply.created.length === 1 ? '' : 's') + ' of ' + take.title +
      '. Each appears as its own take when it finishes.', 'good');
    loadTakes();
  } catch (err) {
    $('variations-status').textContent = 'Could not queue: ' + err.message;
    $('variations-status').className = 'status bad';
  }
}

/* ------------------------------------------------------------------ lyrics
   A draft from a short brief, written on the engine.  It lands in the lyrics box
   even if this window was closed while it was being written. */
var WRITE = { id: null, timer: null };

function openWrite() {
  $('write-modal').classList.remove('hidden');
  if (!WRITE.id) { $('write-status').textContent = ''; }
  $('write-brief').focus();
}

function closeWrite() {
  $('write-modal').classList.add('hidden');
}

function setWriting(on) {
  $('write-go').disabled = on;
  $('write-stop').classList.toggle('hidden', !on);
}

function writeStatus(text, tone) {
  $('write-status').textContent = text;
  $('write-status').className = 'status' + (tone ? ' ' + tone : '');
}

async function doWrite() {
  var brief = $('write-brief').value.trim();
  if (!brief) { writeStatus('Say in a few words what the song is about.', 'bad'); $('write-brief').focus(); return; }
  if ($('lyrics').value.trim() && !confirm('The draft will replace the lyrics in the box. Write it?')) { return; }
  try {
    var draft = await api('/api/lyrics', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ brief: brief, style: $('style').value, structure: $('write-structure').value })
    });
    WRITE.id = draft.id;
    setWriting(true);
    writeStatus('Waiting for the engine\u2026 You can close this window: the words land in the lyrics box.');
    clearTimeout(WRITE.timer);
    WRITE.timer = setTimeout(pollWrite, 1500);
  } catch (err) {
    writeStatus('Could not start: ' + err.message, 'bad');
  }
}

async function pollWrite() {
  if (!WRITE.id) { return; }
  var draft;
  try {
    draft = await api('/api/lyrics/' + WRITE.id);
  } catch (err) {
    WRITE.id = null;
    setWriting(false);
    writeStatus('Lost the draft: ' + err.message, 'bad');
    return;
  }
  if (draft.status === 'done' || draft.status === 'failed') {
    WRITE.id = null;
    setWriting(false);
    if (draft.status === 'done') { landDraft(draft); }
    else { writeStatus(draft.error === 'cancelled' ? 'Stopped.' : 'Could not write the lyrics: ' + draft.error, 'bad'); }
    return;
  }
  writeStatus(draft.status === 'running' ? 'Writing\u2026'
    : 'Waiting for the engine\u2026 You can close this window: the words land in the lyrics box.');
  WRITE.timer = setTimeout(pollWrite, 2000);
}

function landDraft(draft) {
  $('lyrics').value = draft.lyrics;
  if (!$('title').value.trim() && draft.title) { $('title').value = draft.title; }
  State.formEdited = true;
  $('lyrics').dispatchEvent(new Event('input'));
  saveForm();
  closeWrite();
  writeStatus('');
  statusLine('Draft lyrics are in the box. Read them and make them yours, then Write score plan.', 'good');
}

async function stopWrite() {
  if (!WRITE.id) { return; }
  try { await api('/api/lyrics/' + WRITE.id + '/cancel', { method: 'POST' }); } catch (err) { /* the poll reports it */ }
}

/* ---------------------------------------------------------------- identities
   One singer's songs, prepared for training a voice.  The folder is only read;
   the app keeps its own copies, and the review happens here, song by song. */
var IDENTITY = { view: 'list', id: null, data: null, open: {}, timer: null, browse: null };
var PERSONA = IDENTITY;
var STEP_NAMES = [['vocals_state', 'Vocal'], ['score_state', 'Key & tempo'], ['lyrics_state', 'Lyrics'], ['style_state', 'Style']];
var STEP_MARKS = { none: '', queued: '· queued', running: '…', done: '✓', failed: '✕' };

function getIdentityModal() { return $('identities-modal') || $('personas-modal'); }
function getIdentityHeading() { return $('identities-heading') || $('personas-heading'); }
function getIdentityBack() { return $('identities-back') || $('personas-back'); }
function getIdentityClose() { return $('identities-close') || $('personas-close'); }
function getIdentityBody() { return $('identities-body') || $('personas-body'); }

function openIdentities() {
  closeBrandMenu();
  var modal = getIdentityModal();
  if (modal) { modal.classList.remove('hidden'); }
  document.body.style.overflow = 'hidden';
  showIdentityList();
}
var openPersonas = openIdentities;

function closeIdentities() {
  var modal = getIdentityModal();
  if (modal) { modal.classList.add('hidden'); }
  document.body.style.overflow = '';
  clearTimeout(IDENTITY.timer);
  IDENTITY.timer = null;
  loadVocalIdentities();
}
var closePersonas = closeIdentities;

async function showIdentityList() {
  IDENTITY.view = 'list';
  IDENTITY.id = null;
  clearTimeout(IDENTITY.timer);
  var heading = getIdentityHeading();
  if (heading) { heading.textContent = 'Identities'; }
  var back = getIdentityBack();
  if (back) { back.classList.add('hidden'); }
  var list = [];
  try { list = await api('/api/identities'); } catch (err) {
    try { list = await api('/api/personas'); } catch (e) { list = []; }
  }
  var body = getIdentityBody();
  if (!body) { return; }
  body.innerHTML =
    '<p class="identity-intro persona-intro">An identity is one singer’s voice, prepared from their songs. Point at a folder of songs: ' +
    'the app separates each vocal, finds its key and tempo, and drafts its lyrics for you to check. The result is a ' +
    'training set. Only use your own voice, or a singer who has given you permission.</p>' +
    '<button id="identity-new" class="ghost">New identity</button>' +
    '<div class="identity-cards persona-cards">' + list.map(function (item) {
      return '<div class="identity-card persona-card" data-identity="' + esc(item.id) + '" data-persona="' + esc(item.id) + '"><strong>' + esc(item.name) + '</strong>' +
        '<span class="muted">trigger <code>' + esc(item.trigger_word) + '</code> · ' + (item.included || 0) + ' of ' +
        (item.songs || 0) + ' songs' + (item.exported_at ? ' · exported' : '') + '</span></div>';
    }).join('') + '</div>';
}
var showPersonaList = showIdentityList;

function triggerFrom(name) {
  return String(name || '').toLowerCase().replace(/[^a-z0-9]/g, '').slice(0, 24);
}

async function showIdentityNew() {
  IDENTITY.view = 'new';
  var heading = getIdentityHeading();
  if (heading) { heading.textContent = 'New identity'; }
  var back = getIdentityBack();
  if (back) { back.classList.remove('hidden'); }
  var body = getIdentityBody();
  if (!body) { return; }
  body.innerHTML =
    '<div class="identity-form persona-form">' +
      '<div class="field"><label for="pn-name">Name</label><input id="pn-name" type="text" maxlength="80" placeholder="Paul Shields"></div>' +
      '<div class="field"><label for="pn-trigger">Trigger word</label><input id="pn-trigger" type="text" maxlength="40" placeholder="paulshields">' +
        '<div class="hint">Starts every style caption, so a trained model knows when to use this voice. Letters and digits only.</div></div>' +
      '<div class="field"><label for="pn-voice">Voice</label><select id="pn-voice"><option value="male">male</option>' +
        '<option value="female">female</option><option value="">not stated</option></select></div>' +
      '<div class="field"><label for="pn-desc">The sound, for every song</label><input id="pn-desc" type="text" maxlength="400" ' +
        'placeholder="pop rock, electric guitars, bass, drums">' +
        '<div class="hint">Goes into each caption, with each song’s own key and tempo.</div></div>' +
      '<div class="field wide"><label>Folder of songs</label><div id="pn-folder" class="folder-pick"></div>' +
        '<div class="hint">Only read: nothing in it is changed.</div></div>' +
      '<label class="check wide"><input id="pn-consent" type="checkbox"> These recordings are my own voice, or the singer has given me permission to train on them.</label>' +
      '<div class="wide row" style="margin-top:10px"><button id="pn-scan" class="ghost">Scan the folder</button>' +
        '<span id="pn-status" class="status"></span></div>' +
    '</div>';
  $('pn-name').addEventListener('input', function () {
    if (!$('pn-trigger').dataset.touched) { $('pn-trigger').value = triggerFrom($('pn-name').value); }
  });
  $('pn-trigger').addEventListener('input', function () { $('pn-trigger').dataset.touched = '1'; });
  browseFolder(null);
  $('pn-name').focus();
}
var showPersonaNew = showIdentityNew;

async function browseFolder(path) {
  var host = $('pn-folder');
  try {
    var data = await api('/api/import/browse' + (path ? '?path=' + encodeURIComponent(path) : ''));
    IDENTITY.browse = data;
    var html = data.path ? '<div class="here">' + esc(data.path) + ' · ' + data.songs + ' song' + (data.songs === 1 ? '' : 's') + ' here</div>' : '';
    if (data.parent) { html += '<button data-folder="' + esc(data.parent) + '">← up</button>'; }
    html += data.folders.map(function (folder) {
      return '<button data-folder="' + esc(folder) + '">▸ ' + esc(folder.split('/').pop() || folder) + '</button>';
    }).join('');
    if (!data.path && !data.folders.length) { html = '<div class="here">No import folders are mounted. See the README.</div>'; }
    host.innerHTML = html;
  } catch (err) {
    host.innerHTML = '<div class="here">' + esc(err.message) + '</div>';
  }
}

async function scanNewIdentity() {
  var status = $('pn-status');
  var folder = IDENTITY.browse && IDENTITY.browse.path;
  if (!folder) { status.textContent = 'Open the folder that holds the songs.'; status.className = 'status bad'; return; }
  if (!$('pn-consent').checked) { status.textContent = 'Confirm that the voice is yours, or that you have permission.'; status.className = 'status bad'; return; }
  status.textContent = 'Scanning…';
  status.className = 'status';
  $('pn-scan').disabled = true;
  try {
    var made = await api('/api/identities', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: $('pn-name').value.trim() || 'My voice', trigger_word: $('pn-trigger').value || triggerFrom($('pn-name').value) || 'myvoice',
        voice: $('pn-voice').value, description: $('pn-desc').value, folder: folder, consent: true })
    });
    showIdentity(made.id, made);
  } catch (err) {
    status.textContent = err.message;
    status.className = 'status bad';
    $('pn-scan').disabled = false;
  }
}
var scanNewPersona = scanNewIdentity;

function stepChips(song) {
  return STEP_NAMES.map(function (step) {
    var state = song[step[0]] || 'none';
    return '<span class="step ' + state + '">' + step[1] + (STEP_MARKS[state] ? ' ' + STEP_MARKS[state] : '') + '</span>';
  }).join('');
}

function identitySummary(data) {
  var sum = data.summary;
  return '<span><strong>' + sum.included + '</strong> of ' + sum.songs + ' songs included · ' + sum.minutes + ' min</span>' +
    '<span>' + sum.analysed + ' analysed · ' + sum.checked + ' lyrics checked</span>' +
    '<span class="muted">trigger <code>' + esc(data.trigger_word) + '</code> · ' + esc(data.voice || 'voice not stated') +
    ' · ' + esc(data.description || 'no description') + '</span>';
}
var personaSummary = identitySummary;

function songRow(song) {
  var detail = IDENTITY.open[song.id]
    ? '<tr class="identity-detail persona-detail" data-detail="' + song.id + '"><td colspan="5">' + songDetail(song) + '</td></tr>' : '';
  return '<tr data-song="' + song.id + '"' + (song.include ? '' : ' class="off"') + '>' +
    '<td><input type="checkbox" data-include="' + song.id + '"' + (song.include ? ' checked' : '') + ' title="Include in the training set"></td>' +
    '<td>' + esc(song.title) + '<span class="file">' + esc(song.file) + '</span>' +
      (song.flag ? '<span class="flag">' + esc(song.flag) + '</span>' : '') + '</td>' +
    '<td>' + secs(song.duration) + '</td>' +
    '<td data-steps="' + song.id + '">' + stepChips(song) + '<div class="muted" data-keytempo="' + song.id + '">' +
      esc([song.key, song.tempo ? song.tempo + ' BPM' : ''].filter(Boolean).join(', ')) + '</div></td>' +
    '<td><button class="link" data-open="' + song.id + '">' + (IDENTITY.open[song.id] ? 'Close' : 'Review') + '</button></td>' +
  '</tr>' + detail;
}

function songDetail(song) {
  var base = '/api/identities/' + IDENTITY.id + '/songs/' + song.id + '/audio';
  var players = song.stored_path
    ? '<div class="muted">Your recording</div><audio controls preload="none" src="' + base + '?which=original"></audio>' +
      (song.vocals_state === 'done' ? '<div class="muted">The separated vocal</div><audio controls preload="none" src="' + base + '?which=vocals"></audio>' : '')
    : '<p class="muted">Press Analyse to copy this song in.</p>';
  return '<div class="grid"><div>' +
      '<div class="label-row"><label>Lyrics' + (song.lyrics_state === 'done' && !song.lyrics_checked ? ' <span class="muted">(a draft: correct it)</span>' : '') +
      '</label><label class="check"><input type="checkbox" data-checked="' + song.id + '"' + (song.lyrics_checked ? ' checked' : '') + '> checked</label></div>' +
      '<textarea data-lyrics="' + song.id + '" spellcheck="false" placeholder="[Verse]&#10;...">' + esc(song.lyrics || '') + '</textarea>' +
      '<div class="row" style="margin-top:6px"><button class="ghost" data-save="' + song.id + '">Save</button>' +
      '<span class="status" data-saved="' + song.id + '"></span></div>' +
    '</div><div>' + players +
      '<div class="field" style="margin:10px 0 0"><label for="pd-' + song.id + '">This song\u2019s sound</label>' +
      '<input id="pd-' + song.id + '" type="text" maxlength="400" data-description="' + song.id + '" value="' + esc(song.description || '') + '" ' +
      'placeholder="' + esc((IDENTITY.data && IDENTITY.data.description) || 'the identity\u2019s description') + '">' +
      '<div class="hint">Only where it differs from the rest, say stripped back or acoustic. Blank uses the identity\u2019s. Saved with Save.</div></div>' +
      '<div class="muted" style="margin-top:8px">Style caption</div><div class="caption" data-caption="' + song.id + '">' + esc(song.caption) + '</div>' +
      (song.style_hint ? '<div class="muted" style="margin-top:8px">What Gemma heard (a suggestion only)</div><div class="caption">' + esc(song.style_hint) + '</div>' : '') +
      (song.error ? '<div class="status bad" style="margin-top:8px">' + esc(song.error) + '</div>' : '') +
    '</div></div>';
}

async function showIdentity(id, preloaded) {
  IDENTITY.view = 'identity';
  IDENTITY.id = id;
  IDENTITY.open = {};
  var back = getIdentityBack();
  if (back) { back.classList.remove('hidden'); }
  var data = preloaded || await api('/api/identities/' + id);
  IDENTITY.data = data;
  var heading = getIdentityHeading();
  if (heading) { heading.textContent = data.name; }
  var body = getIdentityBody();
  if (!body) { return; }
  body.innerHTML =
    '<div id="identity-summary" class="identity-summary persona-summary">' + identitySummary(data) + '</div>' +
    '<div id="identity-edit" class="identity-form persona-form hidden"></div>' +
    '<div class="identity-actions persona-actions">' +
      '<button id="identity-edit-open" class="ghost">Edit</button>' +
      '<button id="identity-analyse" class="ghost">Analyse</button>' +
      '<button id="identity-export" class="ghost">Export training set</button>' +
      '<button id="identity-delete" class="ghost">Delete identity</button>' +
      '<span id="identity-status" class="status"></span>' +
    '</div>' +
    '<p class="hint">Analyse separates each included song’s vocal, finds its key, tempo and sections with SheetSage, ' +
    'and drafts its lyrics with Whisper, tagged by section. The first song also downloads Whisper, about 1.6 GB. ' +
    'Drafts get most words right, not all: open each song with Review, correct it against the recording, and tick checked.</p>' +
    '<table class="identity-songs persona-songs"><thead><tr><th></th><th>Song</th><th>Length</th><th>Progress</th><th></th></tr></thead>' +
    '<tbody id="identity-rows">' + data.songs.map(songRow).join('') + '</tbody></table>' +
    '<div id="identity-export-result" class="identity-export persona-export"></div>';
  pollIdentity();
}
var showPersona = showIdentity;

/* Keeps the table current without touching what is being typed: only the progress,
   key and tempo, and a lyrics draft that lands in a box nobody has edited. */
async function pollIdentity() {
  clearTimeout(IDENTITY.timer);
  var modal = getIdentityModal();
  if (IDENTITY.view !== 'identity' || (modal && modal.classList.contains('hidden'))) { return; }
  var data;
  try { data = await api('/api/identities/' + IDENTITY.id); } catch (err) { data = null; }
  if (data && IDENTITY.view === 'identity' && data.id === IDENTITY.id) {
    IDENTITY.data = data;
    var sumEl = $('identity-summary') || $('persona-summary');
    if (sumEl) { sumEl.innerHTML = identitySummary(data); }
    data.songs.forEach(function (song) {
      var steps = document.querySelector('[data-steps="' + song.id + '"]');
      if (steps) {
        steps.innerHTML = stepChips(song) + '<div class="muted" data-keytempo="' + song.id + '">' +
          esc([song.key, song.tempo ? song.tempo + ' BPM' : ''].filter(Boolean).join(', ')) + '</div>';
      }
      var box = document.querySelector('[data-lyrics="' + song.id + '"]');
      if (box && !box.dataset.edited && document.activeElement !== box && box.value !== (song.lyrics || '')) { box.value = song.lyrics || ''; }
      var cap = document.querySelector('[data-caption="' + song.id + '"]');
      if (cap) { cap.textContent = song.caption; }
    });
  }
  IDENTITY.timer = setTimeout(pollIdentity, data && data.busy ? 3000 : 8000);
}
var pollPersona = pollIdentity;

/* The identity's own settings.  Changing the description or trigger word changes every
   caption that has no song description of its own; export again afterwards. */
function openIdentityEdit() {
  var data = IDENTITY.data;
  var box = $('identity-edit') || $('persona-edit');
  if (!box) { return; }
  box.innerHTML =
    '<div class="field"><label for="pe-name">Name</label><input id="pe-name" type="text" maxlength="80" value="' + esc(data.name) + '"></div>' +
    '<div class="field"><label for="pe-trigger">Trigger word</label><input id="pe-trigger" type="text" maxlength="40" value="' + esc(data.trigger_word) + '"></div>' +
    '<div class="field"><label for="pe-voice">Voice</label><select id="pe-voice"><option value="male">male</option>' +
      '<option value="female">female</option><option value="">not stated</option></select></div>' +
    '<div class="field"><label for="pe-desc">The sound, for every song</label><input id="pe-desc" type="text" maxlength="400" ' +
      'value="' + esc(data.description || '') + '" placeholder="pop rock, electric guitars, bass, drums"></div>' +
    '<div class="wide row"><button id="pe-save" class="ghost">Save</button><button id="pe-cancel" class="ghost">Cancel</button>' +
      '<span id="pe-status" class="status"></span></div>';
  $('pe-voice').value = data.voice || '';
  box.classList.remove('hidden');
  $('pe-desc').focus();
}
var openPersonaEdit = openIdentityEdit;

async function saveIdentityEdit() {
  try {
    var data = await api('/api/identities/' + IDENTITY.id, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: $('pe-name').value.trim() || IDENTITY.data.name, trigger_word: $('pe-trigger').value,
        voice: $('pe-voice').value, description: $('pe-desc').value })
    });
    IDENTITY.data = data;
    var heading = getIdentityHeading();
    if (heading) { heading.textContent = data.name; }
    var editBox = $('identity-edit') || $('persona-edit');
    if (editBox) { editBox.classList.add('hidden'); }
    var status = $('identity-status') || $('persona-status');
    if (status) {
      status.textContent = IDENTITY.data.exported_at ? 'Saved. Export again to update the training set.' : 'Saved.';
      status.className = 'status good';
    }
    pollIdentity();
  } catch (err) {
    $('pe-status').textContent = err.message;
    $('pe-status').className = 'status bad';
  }
}
var savePersonaEdit = saveIdentityEdit;

function identitySong(id) {
  return ((IDENTITY.data && IDENTITY.data.songs) || []).filter(function (song) { return song.id === id; })[0] || null;
}
var personaSong = identitySong;

async function identityClick(event) {
  var target = event.target;
  var card = target.closest('[data-identity]') || target.closest('[data-persona]');
  if (card) { showIdentity(card.dataset.identity || card.dataset.persona); return; }
  if (target.closest('#identity-new') || target.closest('#persona-new')) { showIdentityNew(); return; }
  var folder = target.closest('[data-folder]');
  if (folder) { browseFolder(folder.dataset.folder); return; }
  if (target.closest('#pn-scan')) { scanNewIdentity(); return; }
  var open = target.closest('[data-open]');
  if (open) {
    IDENTITY.open[open.dataset.open] = !IDENTITY.open[open.dataset.open];
    var rows = $('identity-rows') || $('persona-rows');
    if (rows) { rows.innerHTML = IDENTITY.data.songs.map(songRow).join(''); }
    return;
  }
  var save = target.closest('[data-save]');
  if (save) {
    var sid = save.dataset.save;
    var box = document.querySelector('[data-lyrics="' + sid + '"]');
    var note = document.querySelector('[data-saved="' + sid + '"]');
    try {
      var sound = document.querySelector('[data-description="' + sid + '"]');
      await api('/api/identities/' + IDENTITY.id + '/songs/' + sid, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lyrics: box.value, description: sound ? sound.value : undefined })
      });
      delete box.dataset.edited;
      note.textContent = 'Saved.';
      pollIdentity();
      note.className = 'status good';
    } catch (err) { note.textContent = err.message; note.className = 'status bad'; }
    return;
  }
  if (target.closest('#identity-edit-open') || target.closest('#persona-edit-open')) { openIdentityEdit(); return; }
  if (target.closest('#pe-cancel')) {
    var editBox = $('identity-edit') || $('persona-edit');
    if (editBox) { editBox.classList.add('hidden'); }
    return;
  }
  if (target.closest('#pe-save')) { saveIdentityEdit(); return; }
  var status = $('identity-status') || $('persona-status');
  if (target.closest('#identity-analyse') || target.closest('#persona-analyse')) {
    try {
      var queued = await api('/api/identities/' + IDENTITY.id + '/analyse', { method: 'POST' });
      if (status) {
        status.textContent = queued.queued ? 'Queued ' + queued.queued + ' step' + (queued.queued === 1 ? '' : 's') + '. It carries on if you close this window.'
          : 'Nothing left to analyse.';
        status.className = 'status good';
      }
      pollIdentity();
    } catch (err) { if (status) { status.textContent = err.message; status.className = 'status bad'; } }
    return;
  }
  if (target.closest('#identity-export') || target.closest('#persona-export')) {
    if (status) {
      status.textContent = 'Writing the training set…';
      status.className = 'status';
    }
    try {
      var out = await api('/api/identities/' + IDENTITY.id + '/export', { method: 'POST' });
      if (status) { status.textContent = ''; }
      var expRes = $('identity-export-result') || $('persona-export-result');
      if (expRes) {
        expRes.innerHTML = 'Wrote ' + out.written.length + ' song' + (out.written.length === 1 ? '' : 's') +
          ' to <code>' + esc(out.folder) + '</code>.' +
          (out.unchecked.length ? '<br><span class="status bad">Lyrics not checked yet: ' + esc(out.unchecked.join(', ')) + '</span>' : '') +
          (out.skipped.length ? '<br><span class="muted">Skipped, not analysed or no lyrics: ' + esc(out.skipped.join(', ')) + '</span>' : '');
      }
    } catch (err) { if (status) { status.textContent = err.message; status.className = 'status bad'; } }
    return;
  }
  if (target.closest('#identity-delete') || target.closest('#persona-delete')) {
    if (!confirm('Delete the identity “' + IDENTITY.data.name + '” and the app’s copies of its songs? The original folder is not touched.')) { return; }
    try {
      await api('/api/identities/' + IDENTITY.id, { method: 'DELETE' });
      showIdentityList();
    } catch (err) { if (status) { status.textContent = err.message; status.className = 'status bad'; } }
  }
}
var personaClick = identityClick;

async function identityChange(event) {
  var target = event.target;
  if (target.dataset.include) {
    await api('/api/identities/' + IDENTITY.id + '/songs/' + target.dataset.include, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ include: target.checked })
    });
    var song = identitySong(target.dataset.include);
    if (song) { song.include = target.checked ? 1 : 0; }
    target.closest('tr').classList.toggle('off', !target.checked);
    pollIdentity();
  }
  if (target.dataset.checked) {
    await api('/api/identities/' + IDENTITY.id + '/songs/' + target.dataset.checked, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ lyrics_checked: target.checked })
    });
    pollIdentity();
  }
}
var personaChange = identityChange;

/* Action tiles. Colour carries meaning: green acts, violet inspects, blue keeps,
   amber reworks, gold remembers, red removes. */
var ICONS = {
  play: '<path d="M8 5.4v13.2L19 12z" fill="currentColor" stroke="none"/>',
  pause: '<path d="M9 5.5v13M15 5.5v13" stroke-width="2.4" stroke-linecap="round"/>',
  render: '<path d="M12 3.5v11m0 0l-4-4m4 4l4-4M5 19.5h14"/>',
  score: '<circle cx="7" cy="17.6" r="2.2"/><circle cx="17" cy="15.6" r="2.2"/><path d="M9.2 17.6V6l10-2v11.4"/>',
  save: '<path d="M12 4v10m0 0l-4-4m4 4l4-4M5 19h14"/>',
  again: '<path d="M20 12a8 8 0 1 1-2.4-5.7"/><path d="M20 4.2v3.9h-3.9"/>',
  star: '<path d="M12 3.6l2.6 5.5 6.1.9-4.4 4.3 1 6-5.3-2.9-5.3 2.9 1-6L3.4 10l6-.9z"/>',
  check: '<path d="M20 6.5L9.5 17 4 11.5"/>',
  trash: '<path d="M4.5 7h15M9.5 7V4.8h5V7M6.5 7l1 12.2h9l1-12.2"/>',
  stems: '<path d="M12 3.2l8 4.2-8 4.2-8-4.2z"/><path d="M4 12.4l8 4.2 8-4.2"/><path d="M4 16.6l8 4.2 8-4.2"/>',
  move: '<path d="M3.5 7.5V18a1.5 1.5 0 0 0 1.5 1.5h14a1.5 1.5 0 0 0 1.5-1.5V9.5A1.5 1.5 0 0 0 19 8h-7l-2-2.5H5A1.5 1.5 0 0 0 3.5 7v.5"/><path d="M10 13.5h6m0 0l-2.5-2.5m2.5 2.5L13.5 16"/>',
  variations: '<path d="M12 3.5l1.9 5.1 5.1 1.9-5.1 1.9L12 17.5l-1.9-5.1L5 10.5l5.1-1.9z"/><path d="M18.5 15.2l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>',
  stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="1.6"/>'
};

function icon(name) {
  return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + ICONS[name] + '</svg>';
}

function tile(kind, iconName, label, attrs, title) {
  return '<button class="act ' + kind + '" ' + (attrs || '') + ' title="' + (title || label) + '">' +
    icon(iconName) + '<span>' + label + '</span></button>';
}

function downloadTile(take) {
  return '<a class="act save" href="/api/takes/' + take.id + '/audio" download' +
    ' title="Download the audio file" aria-label="Download the audio file">' +
    icon('save') + '<span>Save</span></a>';
}

function stemsBlock(take) {
  var sets = take.stem_sets || [];
  if (!sets.length) { return ''; }
  var rows = sets.map(function (set) {
    var busy = set.status === 'queued' || set.status === 'running';
    var remove = '<button class="stem-chip" data-act="stem-del" data-set="' + set.id + '" title="' +
      (busy ? 'Stop and delete these stems' : 'Delete these stems') + '">x</button>';
    if (set.status === 'done') {
      var chips = (set.files || []).map(function (file) {
        return '<button class="stem-chip" data-act="stem-play" data-set="' + set.id + '" data-file="' + esc(file.file) + '">' +
          esc(file.name) + '</button>';
      }).join('');
      return '<div class="stem-row"><span class="stem-label">stems</span>' + chips +
        '<a class="stem-chip" href="/api/stem-sets/' + set.id + '/zip" download>zip</a>' + remove + '</div>';
    }
    if (set.status === 'failed') {
      return '<div class="stem-row"><span class="stem-label" style="color:var(--bad)">stems failed: ' +
        esc((set.error || '').slice(0, 70)) + '</span>' + remove + '</div>';
    }
    var pct = Math.round((set.progress || 0) * 100);
    return '<div class="stem-row"><span class="stem-label">stems: ' + esc(set.stage || set.status) + ' ' + pct + '%</span>' + remove + '</div>';
  });
  return '<div class="take-stems">' + rows.join('') + '</div>';
}

/* Load a take into the left column: the matching mode, its title, style, lyrics,
   score and settings, and the highlight on its card. Every tile that acts on a
   take calls this first, so the panel always describes the take you just touched. */
function selectTake(take) {
  if (!take) { return; }
  if (take.id !== selectedTakeId() && formIsDraft()) { stashDraft(); }
  // Songs and instrumentals are both written from a prompt; only a cover has a recording.
  var isInst = take.kind === 'instrumental';
  var isSong = take.kind === 'song' || isInst;
  var hasScore = Boolean(take.abc && take.abc.length > 50);
  var planning = isSong && !hasScore && (take.status === 'queued' || take.status === 'running');
  setMode(isInst ? 'inst' : (isSong ? 'song' : 'cover'));
  if (!isSong && take.source_id) { $('source-select').value = take.source_id; }
  $('title').value = take.title;
  $('style').value = take.style || '';
  $('style').dataset.touched = '1';
  // An instrumental keeps its structure where a song keeps its lyrics.  The lyrics box
  // is left alone, so browsing instrumentals cannot wipe the words of a song.
  if (isInst) {
    loadStructure(take.lyrics);
    FEEL.value = FEELS[take.feel] ? take.feel : 'steady';
    paintFeel();
  } else {
    $('lyrics').value = take.lyrics || '';
  }
  $('abc').value = take.abc || '';
  scoreBaseline(take.abc || '');
  if (take.mode) { $('mode').value = take.mode; }
  if (isSong) {
    $('harmony').value = take.harmony || 0;
    if (take.variety) { $('variety').value = take.variety; }
    paintHarmony();
  }
  if (take.realaudio !== undefined) {
    $('realaudio').checked = Boolean(take.realaudio);
  }
  if (take.identity_id !== undefined || take.persona_id !== undefined) {
    paintVocalIdentitySelect((take.identity_id !== undefined ? take.identity_id : take.persona_id) || '', take.voice_lora || '');
    if (take.voice_lora_clip !== undefined) { paintVocalPlanner(take.voice_lora_clip); }
  }
  if (take.style_lora !== undefined) { showStyleLora(take); }
  $('interpretation').value = INTERPRETATIONS[take.interpretation] ? take.interpretation : 'standard';
  paintInterpretation();
  // The take owns the score in the box: its own for a song, its recording's
  // transcription for a cover, which boxShowsSource recognises by the take's
  // source_id. A plan still being written owns nothing until it lands.
  setSelection({
    formTakeId: take.id,
    boxKind: planning ? 'none' : 'take',
    boxId: planning ? null : take.id,
    awaiting: planning ? take.id : null
  });
  $('score-badge').textContent = take.abc
    ? (take.status === 'planned' ? 'plan ready' : 'saved score')
    : 'no plan yet';
  $('score-badge').className = take.abc ? 'badge ok' : 'badge';
  if (take.abc) { $('score-box').open = true; }
  setChart(chordChart(take.abc || ''));
  showPlanLength(take.abc || '');
  syncEditor();
  refreshTitleHint();
  paintSource();
  State.formEdited = false;
  saveForm();
  paintTakes();
}

/* One click on a card replaces the form.  If the form holds words that are not
   simply the take it already shows, keep them, so a click cannot lose a verse. */
function formIsDraft() {
  // Moving between takes must not look like an unsaved draft.  Only words the user
  // typed, or took back with Restore, count; loading a take or a recording clears it.
  if (!State.formEdited) { return false; }
  // A text box turns \r\n into \n, so compare text the way the box holds it.
  var same = function (a, b) { return String(a || '').replace(/\r\n?/g, '\n') === String(b || '').replace(/\r\n?/g, '\n'); };
  var title = $('title').value;
  var style = $('style').value;
  var lyrics = State.mode === 'inst' ? '' : $('lyrics').value;
  if (!lyrics.trim() && !title.trim()) { return false; }
  var shown = selectedTakeId() ? takeById(selectedTakeId()) : null;
  if (State.mode === 'inst') { return Boolean(shown) && (!same(title, shown.title) || !same(style, shown.style)); }
  if (!shown) { return Boolean(lyrics.trim()); }
  return !same(title, shown.title) || !same(style, shown.style) || !same(lyrics, shown.lyrics);
}

function stashDraft() {
  var next = { mode: State.mode, title: $('title').value, style: $('style').value, lyrics: $('lyrics').value };
  var current = State.draft;
  // The words may be stashed again on the next card click.  Only keep one copy, so
  // the bar does not churn through the same verse.
  if (current && current.title === next.title && current.style === next.style && current.lyrics === next.lyrics) { return; }
  State.draft = next;
  paintDraft();
}

function paintDraft() {
  var bar = $('draft-bar');
  if (!bar) { return; }
  bar.classList.toggle('hidden', !State.draft);
  if (State.draft) {
    var words = (State.draft.title || State.draft.lyrics || '').trim().split('\n')[0].slice(0, 40);
    $('draft-text').textContent = 'Your unsaved words were kept' + (words ? ': \u201c' + words + '\u201d' : '') + '.';
  }
}

function restoreDraft() {
  var draft = State.draft;
  if (!draft) { return; }
  setMode(draft.mode === 'song' ? 'song' : 'cover');
  setSelection({});
  $('title').value = draft.title || '';
  $('style').value = draft.style || '';
  $('lyrics').value = draft.lyrics || '';
  dismissDraft();
  paintVocals();
  refreshTitleHint();
  // The words are back in the form and nowhere else, so a later card click must
  // offer them again rather than drop them.
  State.formEdited = true;
  saveForm();
  paintTakes();
  statusLine('Your words are back.', 'good');
}

function dismissDraft() {
  State.draft = null;
  paintDraft();
}

/* Start a new song, or a new cover, from the take on show.  The words and the score
   go; the settings stay (style, vocal, Harmony, plan variety, length, interpretation,
   seed), so the next song can be in the same vein.  The loaded take lets go of the
   column, so Render and Replan cannot act on it by mistake.  A cover keeps its
   recording and goes back to that recording's own transcription. */
function startFresh() {
  var noun = { cover: 'cover', song: 'song', inst: 'instrumental' }[State.mode] || 'song';
  if (scoreIsDirty() && !confirm('The score has changes that are not saved. Start a new ' + noun + ' and discard them?')) {
    return;
  }
  if (formIsDraft()) { stashDraft(); }
  var cover = State.mode === 'cover';
  setSelection({});
  $('title').value = '';
  if (State.mode !== 'inst') { $('lyrics').value = ''; }   // an instrumental keeps its structure, like a setting
  $('abc').value = '';
  scoreBaseline('');
  setChart('');
  showPlanLength('');
  if (cover) {
    paintSource();   // loads the recording's transcription back into the box, if it has one
  } else {
    $('score-badge').textContent = 'no plan yet';
    $('score-badge').className = 'badge';
  }
  State.formEdited = false;
  refreshTitleHint();
  syncEditor();
  saveForm();
  paintTakes();
  statusLine(cover
    ? 'New cover. The recording stays selected: add a title and lyrics, then Create cover.'
    : State.mode === 'inst' ? 'New instrumental. Choose a style and a structure, then Write score plan.'
    : 'New song. Write a title, style and lyrics, then Write score plan.', 'good');
  $('title').focus();
}

function takeById(id) {
  return State.takes.filter(function (take) { return take.id === id; })[0] || null;
}

function paintTakes() {
  var list = State.takes.filter(function (take) {
    return State.filter === 'all' || (State.filter === 'favourite' && take.favourite);
  });
  State.paintedAt = Date.now();
  $('empty').style.display = list.length ? 'none' : 'block';
  var others = State.spaces.some(function (space) { return space.id !== State.spaceId && space.takes; });
  $('empty').textContent = State.filter === 'favourite' ? 'No starred takes in this space.'
    : others ? 'This space is empty. Create a take while it is on show, or move takes here with Move.'
    : 'Nothing yet. Load a recording, write some lyrics, and press create.';
  var more = State.takesTotal - State.takes.length;
  $('takes-more').classList.toggle('hidden', more <= 0);
  $('takes-more').textContent = 'Show ' + Math.min(more, 300) + ' more of ' + more + ' older takes';
  $('takes').innerHTML = list.map(function (take) {
    var status = take.status;
    var meta = [];
    meta.push(take.kind === 'song' ? 'from a prompt' : (take.kind === 'instrumental' ? 'instrumental' : 'cover'));
    if (take.duration) { meta.push(secs(take.duration)); }
    // The settings that shaped it come first, named, so a card can be read back
    // as the recipe that made it. Each appears only when it was not the default.
    var written = take.kind === 'song' || take.kind === 'instrumental';
    if (written && take.harmony) { meta.push('Harmony: ' + HARMONY_WORDS[take.harmony].toLowerCase()); }
    if (take.interpretation && take.interpretation !== 'standard' && INTERPRETATIONS[take.interpretation]) {
      meta.push('Interpretation: ' + INTERPRETATIONS[take.interpretation].name.toLowerCase());
    }
    if (written && take.variety && take.variety !== 'normal') { meta.push('Plan: ' + take.variety); }
    if (take.style_lora) {
      var strengths = [take.style_lora_clip, take.style_lora_model];
      var full = strengths.every(function (n) { return Number(n) === 1; });
      meta.push('Style: ' + loraLabel(take.style_lora) +
        (full ? '' : ' (' + strengths.map(function (n) { return Number(n).toFixed(2); }).join('/') + ')'));
    }
    if (take.realaudio) { meta.push('realaudio'); }
    if (take.identity_id || take.persona_id || take.voice_lora) {
      meta.push(identityName(take.identity_id || take.persona_id) || 'identity');
    }
    meta.push('seed ' + take.seed);
    meta.push(age(take.created_at));
    var live = '';
    if (status === 'running' && take.live) {
      live = '<div class="take-meta">' + esc(take.live.label || 'working') + ' \u00b7 ' + Math.round((take.live.progress || 0) * 100) + '%</div>';
    } else if (status === 'failed') {
      live = '<div class="take-status failed">' + esc((take.error || 'failed').slice(0, 120)) + '</div>';
    } else if (status === 'planned') {
      // An instrumental whose plan holds a vocal line is flagged before it is
      // rendered, so the warning arrives while it still saves you something.
      live = take.error
        ? '<button class="take-status sung" data-act="render" data-id="' + take.id + '">' + esc(take.error) + '</button>'
        : '<div class="take-status ready">plan ready</div>';
    } else if (status !== 'done') {
      live = '<div class="take-meta">' + esc(status === 'queued' ? 'waiting for the engine' : status) + '</div>';
    } else if (take.kind === 'instrumental' && take.vocal_check >= 0.1) {
      // The LoRA keeps the voice out on most seeds and not all. The finished
      // audio is checked, so a spoiled take says so rather than puzzling you.
      live = '<button class="take-status sung" data-act="sung" data-id="' + take.id + '">singing in ' +
        Math.round(take.vocal_check * 100) + '% of this instrumental</button>';
    }
    var id = ' data-id="' + take.id + '"';
    var actions = '';
    if (status === 'queued' || status === 'running') {
      actions += tile('del', 'stop', 'Cancel', 'data-act="cancel"' + id);
    }
    if (status === 'planned') {
      actions += tile('go', 'render', 'Render', 'data-act="render"' + id);
      actions += tile('again', 'again', 'Replan', 'data-act="replan"' + id);
    }
    if (status === 'failed') {
      // A failure leaves a dead end unless it can be retried. A take with a score
      // failed while rendering; one without failed while planning.
      if (take.abc && take.abc.length > 50) {
        actions += tile('go', 'render', 'Render', 'data-act="render"' + id);
      } else {
        actions += tile('again', 'again', 'Replan', 'data-act="replan"' + id);
      }
      // A restarted job leaves a take that often still holds its audio or its score.
      // Clear puts it back to whatever it reached, without another run.
      actions += tile('go', 'check', 'Clear', 'data-act="clear"' + id);
      // Again comes from the branches below when there is audio, and from here when
      // there is not, so a failed take never shows it twice.
      if (!take.has_audio) {
        actions += tile('again', 'again', 'Again', 'data-act="again"' + id);
      }
    }
    if (take.abc && take.abc.length > 50) {
      actions += tile('score', 'score', 'Score', 'data-act="open"' + id);
    }
    if (take.has_audio) {
      // Named carefully: `live` above already holds the status line for this card,
      // and var is function scoped, so reusing the name printed true or false there.
      var isLive = State.playing === take.id;
      actions += tile('play' + (isLive ? ' playing' : ''), isLive ? 'pause' : 'play',
                      isLive ? 'Pause' : 'Play', 'data-act="play"' + id);
      actions += downloadTile(take);
      actions += tile('stems', 'stems', 'Stems', 'data-act="stems"' + id);
      actions += tile('again', 'again', 'Again', 'data-act="again"' + id);
    }
    actions += tile('star' + (take.favourite ? ' on' : ''), 'star', 'Star', 'data-act="star"' + id,
                    take.favourite ? 'Starred. Click to remove the star.' : 'Star this take');
    actions += tile('del', 'trash', 'Delete', 'data-act="del"' + id);
    var classes = 'take';
    if (State.playing === take.id) { classes += ' playing'; }
    // The left column points at a take either through the editor, or through a
    // cover retake, where the score in the box belongs to the source.
    if ((selectedTakeId() || takeIdInEditor()) === take.id) {
      // tone-*, not song/cover: a plain .cover class belongs to the 46px tile.
      classes += ' editing ' + ({ song: 'tone-song', instrumental: 'tone-inst' }[take.kind] || 'tone-cover');
    }
    return '<article class="' + classes + '" data-id="' + take.id + '">' +
      '<div class="take-head">' +
        '<div class="cover ' + ({ song: 'grad-song', instrumental: 'grad-inst' }[take.kind] || 'grad-cover') + '">' + initials(take.title) + '</div>' +
        '<div class="take-headtext">' +
          '<div class="take-title" title="' + esc(take.title) + '">' + esc(take.title) + '</div>' +
          '<div class="take-meta" title="' + esc(meta.join(' \u00b7 ')) + '">' + esc(meta.join(' \u00b7 ')) + '</div>' +
        '</div>' +
        // Occasional, so small corner buttons rather than tiles in an already full row.
        '<div class="take-corner">' +
          (take.abc && take.abc.length > 50 && status !== 'queued' && status !== 'running'
            ? '<button class="take-move" data-act="variations"' + id + ' title="Variations: render this score in other interpretations"' +
              ' aria-label="Variations">' + icon('variations') + '</button>'
            : '') +
          '<button class="take-move" data-act="move"' + id + ' title="Move to another space" aria-label="Move to another space">' +
            icon('move') + '</button>' +
        '</div>' +
      '</div>' +
      '<div class="take-style">' + esc(take.style) + '</div>' +
      live +
      '<div class="take-actions">' + actions + '</div>' +
      stemsBlock(take) +
    '</article>';
  }).join('');
}

/* The play tile is a toggle. The active one pulses, shows a pause icon, and stops
   the audio when pressed again, so the live take is obvious at a glance. */
function togglePlay(id) {
  var audio = $('audio');
  if (State.playing === id && !audio.paused) {
    audio.pause();          // keeps currentTime, so Play resumes where it stopped
    State.playing = null;
    paintTakes();
    paintTransport();
    return;
  }
  playTake(id);
}

function playTake(id) {
  var take = State.takes.filter(function (t) { return t.id === id; })[0];
  if (!take) { return; }
  State.playing = id;
  State.audition = null;
  State.playRequestedAt = Date.now();
  wave.kind = take.kind;   // the waveform takes the colour of what is playing
  var audio = $('audio');
  var url = '/api/takes/' + id + '/audio';
  if (State.loadedId === id && audio.src) {
    // Same take: resume.  Assigning src again would reload the media and throw the
    // position away, which is what made Pause behave like Stop.
    if (audio.ended) { audio.currentTime = 0; }
    audio.play().catch(function () {});
  } else {
    State.loadedId = id;
    audio.src = url;
    audio.play().catch(function () {});
    loadWave(url, '/api/takes/' + id + '/peaks');
  }
  $('np-title').textContent = take.title;
  var position = takePosition(id);
  $('np-meta').textContent = (position ? 'take ' + position.index + ' of ' + position.total + ' \u00b7 ' : '') +
    (take.duration ? secs(take.duration) : take.style.slice(0, 60));
  $('np-cover').className = 'np-cover ' + ({ song: 'grad-song', instrumental: 'grad-inst' }[take.kind] || 'grad-cover');
  updateMediaSession(take);
  paintTransport();
  paintTakes();
}

/* ------------------------------------------------------------- transport ---
   The bar is the only way to control playback: the native audio element is
   hidden, so these buttons are it. Previous and next walk the library in the
   order the cards are shown. */
var SPEEDS = [0.75, 1, 1.25, 1.5];
var SPEED_LABELS = ['0.75x', '1.0x', '1.25x', '1.5x'];
var speedIndex = 1;

function playableTakes() {
  return State.takes.filter(function (take) { return take.has_audio; });
}

function currentTakeId() {
  return State.playing || State.loadedId || null;
}

function currentTake() {
  var id = currentTakeId();
  for (var i = 0; i < State.takes.length; i++) {
    if (State.takes[i].id === id) { return State.takes[i]; }
  }
  return null;
}

function takePosition(id) {
  var list = playableTakes();
  for (var i = 0; i < list.length; i++) {
    if (list[i].id === id) { return { index: i + 1, total: list.length }; }
  }
  return null;
}

function stepTake(delta) {
  var list = playableTakes();
  if (!list.length) { return; }
  var id = currentTakeId();
  var index = -1;
  for (var i = 0; i < list.length; i++) { if (list[i].id === id) { index = i; } }
  var next = index === -1 ? 0 : (index + delta + list.length) % list.length;
  playTake(list[next].id);
}

function nudge(seconds) {
  var audio = $('audio');
  if (!audio.duration || !isFinite(audio.duration)) { return; }
  audio.currentTime = Math.max(0, Math.min(audio.duration, audio.currentTime + seconds));
}

function updateTimes() {
  var audio = $('audio');
  $('t-now').textContent = secs(audio.currentTime || 0);
  $('t-total').textContent = (audio.duration && isFinite(audio.duration)) ? secs(audio.duration) : '--:--';
}

function paintTransport() {
  var audio = $('audio');
  // What is playing may be a stem rather than a take, and a stem deliberately
  // owns no take. The button follows the sound, so it shows Pause whenever
  // something is sounding.
  var playing = Boolean(audio.currentSrc || audio.src) && !audio.paused && !audio.ended;
  $('btn-play').innerHTML = playing
    ? '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M9 5h2.6v14H9zM13.4 5H16v14h-2.6z"/></svg>'
    : '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5.4v13.2L19 12z"/></svg>';
  $('btn-play').title = playing ? 'Pause' : 'Play';
  $('btn-play').setAttribute('aria-label', playing ? 'Pause' : 'Play');
  $('btn-repeat').classList.toggle('on', Boolean(audio.loop));
  var take = currentTake();
  $('btn-star').disabled = !take;
  $('btn-star').classList.toggle('on', Boolean(take && take.favourite));
  $('btn-prev').disabled = playableTakes().length < 2;
  $('btn-next').disabled = playableTakes().length < 2;
  $('btn-mute').classList.toggle('on', Boolean(audio.muted || audio.volume === 0));
}

function updateMediaSession(take) {
  if (!('mediaSession' in navigator) || typeof MediaMetadata === 'undefined') { return; }
  try {
    navigator.mediaSession.metadata = new MediaMetadata({
      title: take.title,
      artist: (take.style || '').split(',')[0],
      album: 'YuE2 Studio'
    });
  } catch (err) { /* older browsers */ }
}

/* ------------------------------------------------------------- waveform ---
   Drawn from the decoded audio. Click or drag anywhere to seek, and the played
   part fills in as the song runs. */
var audioCtx = null;
var wave = { peaks: null, ratio: 0, raf: null, seeking: false };
// One column per device pixel at draw time, sampled from a fixed 1024 column
// analysis, so a window resize does not re-decode the audio.
var WAVE_COLS = 1024;
var WAVE_HEIGHT = 56;

function waveCanvas() {
  var canvas = $('wave');
  var dpr = window.devicePixelRatio || 1;
  var width = Math.max(120, canvas.clientWidth || 600);
  var targetW = Math.round(width * dpr);
  var targetH = Math.round(WAVE_HEIGHT * dpr);
  if (canvas.width !== targetW || canvas.height !== targetH) {
    canvas.width = targetW;
    canvas.height = targetH;
  }
  return canvas;
}

function drawWave() {
  var canvas = waveCanvas();
  var ctx = canvas.getContext('2d');
  var w = canvas.width;
  var h = canvas.height;
  var dpr = window.devicePixelRatio || 1;
  ctx.clearRect(0, 0, w, h);
  if (!wave.peaks) { return; }

  // A mirrored envelope from the peak values, with an inner body from the RMS.
  // The outline shows transients, the body shows loudness, which is what makes a
  // thin or squashed mix visible before you listen to it.
  var columns = Math.max(1, Math.floor(w / dpr));
  var mid = h / 2;
  var amp = h * 0.46;
  var outline = new Path2D();
  var body = new Path2D();
  var i;
  var x;
  var p;
  var r;
  for (i = 0; i < columns; i++) {
    p = column(wave.peaks, i, columns) * amp;
    r = column(wave.rmss, i, columns) * amp;
    x = i * dpr;
    if (i === 0) {
      outline.moveTo(x, mid - p);
      body.moveTo(x, mid - r);
    } else {
      outline.lineTo(x, mid - p);
      body.lineTo(x, mid - r);
    }
  }
  for (i = columns - 1; i >= 0; i--) {
    p = column(wave.peaks, i, columns) * amp;
    r = column(wave.rmss, i, columns) * amp;
    x = i * dpr;
    outline.lineTo(x, mid + p);
    body.lineTo(x, mid + r);
  }
  outline.closePath();
  body.closePath();

  // The played part wears the take's own colour: blue for a song from a prompt,
  // pink for a cover. Stems and anything else keep the neutral violet.
  var tone = waveTone();
  function paint(played) {
    ctx.fillStyle = played ? tone.outline : 'rgba(255, 255, 255, 0.10)';
    ctx.fill(outline);
    ctx.fillStyle = played ? tone.body : 'rgba(255, 255, 255, 0.24)';
    ctx.fill(body);
  }

  paint(false);
  var head = Math.round(wave.ratio * w);
  ctx.save();
  ctx.beginPath();
  ctx.rect(0, 0, head, h);
  ctx.clip();
  paint(true);
  ctx.restore();

  // White, so the playhead stays visible on a pink waveform as well as a blue one.
  ctx.fillStyle = '#f4f4f7';
  ctx.fillRect(Math.max(0, Math.min(w - 2, head - 1)), 0, Math.max(2, 2 * dpr), h);
}

function waveTone() {
  if (wave.kind === 'song') { return { body: '#38bdf8', outline: 'rgba(56, 189, 248, 0.42)' }; }
  if (wave.kind === 'instrumental') { return { body: '#a3e635', outline: 'rgba(163, 230, 53, 0.42)' }; }
  if (wave.kind === 'cover') { return { body: '#ff4d94', outline: 'rgba(255, 77, 148, 0.42)' }; }
  return { body: '#a78bfa', outline: 'rgba(167, 139, 250, 0.45)' };
}

function normalise(values) {
  var max = 0;
  for (var i = 0; i < values.length; i++) { if (values[i] > max) { max = values[i]; } }
  if (!max) { return values; }
  return values.map(function (v) { return v / max; });
}

/* The server computes the waveform once and caches it.  Decoding the file here is
   the fallback, for a server that cannot. */
async function loadWave(url, peaksUrl) {
  wave.peaks = null;
  wave.rmss = null;
  wave.ratio = 0;
  wave.token = (wave.token || 0) + 1;
  var token = wave.token;
  drawWave();
  if (peaksUrl) {
    try {
      var cached = await api(peaksUrl);
      if (token !== wave.token) { return; }   // another take started meanwhile
      if (cached && cached.peaks && cached.peaks.length) {
        wave.peaks = cached.peaks;
        wave.rmss = cached.rms;
        drawWave();
        return;
      }
    } catch (err) { /* decode it here instead */ }
  }
  try {
    var response = await fetch(url);
    var buffer = await response.arrayBuffer();
    if (!audioCtx) { audioCtx = new (window.AudioContext || window.webkitAudioContext)(); }
    if (audioCtx.state === 'suspended') { audioCtx.resume(); }
    var decoded = await audioCtx.decodeAudioData(buffer.slice(0));
    var data = decoded.getChannelData(0);
    var per = Math.max(1, Math.floor(data.length / WAVE_COLS));
    var peaks = [];
    var rmss = [];
    for (var i = 0; i < WAVE_COLS; i++) {
      var start = i * per;
      var peak = 0;
      var sum = 0;
      var count = 0;
      for (var j = 0; j < per; j += 16) {
        var value = data[start + j] || 0;
        var magnitude = value < 0 ? -value : value;
        if (magnitude > peak) { peak = magnitude; }
        sum += value * value;
        count += 1;
      }
      peaks.push(peak);
      rmss.push(count ? Math.sqrt(sum / count) : 0);
    }
    if (token !== wave.token) { return; }
    wave.peaks = normalise(peaks);
    wave.rmss = normalise(rmss);
    drawWave();
  } catch (err) { /* the waveform is optional. The player still works. */ }
}

function column(values, index, columns) {
  if (!values) { return 0; }
  return values[Math.min(values.length - 1, Math.floor(index * values.length / columns))];
}

function syncWaveRatio() {
  var audio = $('audio');
  if (audio.duration && isFinite(audio.duration)) {
    wave.ratio = Math.max(0, Math.min(1, audio.currentTime / audio.duration));
  }
}

function waveLoop() {
  syncWaveRatio();
  drawWave();
  if (!$('audio').paused && !$('audio').ended) {
    wave.raf = requestAnimationFrame(waveLoop);
  } else {
    wave.raf = null;
  }
}

function startWaveLoop() {
  if (wave.raf === null) { wave.raf = requestAnimationFrame(waveLoop); }
}

function stopWaveLoop() {
  if (wave.raf !== null) { cancelAnimationFrame(wave.raf); wave.raf = null; }
  syncWaveRatio();
  drawWave();
}

function seekFromPointer(event) {
  var canvas = $('wave');
  var audio = $('audio');
  var rect = canvas.getBoundingClientRect();
  if (!rect.width || !audio.duration || !isFinite(audio.duration)) { return; }
  var ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
  audio.currentTime = ratio * audio.duration;
  wave.ratio = ratio;
  drawWave();
}

function wireTransport() {
  var audio = $('audio');
  $('btn-play').addEventListener('click', function () {
    // Pause whatever is sounding, take or stem. Starting something else while a
    // stem plays was the old behaviour and always surprising.
    if (!audio.paused && !audio.ended) {
      audio.pause();
      if (State.playing) { State.playing = null; paintTakes(); }
      paintTransport();
      return;
    }
    var id = currentTakeId();
    if (id) { togglePlay(id); return; }
    if (audio.src && !audio.ended) { audio.play().catch(function () {}); return; }
    var list = playableTakes();
    if (list.length) { playTake(list[0].id); }
  });
  $('btn-prev').addEventListener('click', function () { stepTake(-1); });
  $('btn-next').addEventListener('click', function () { stepTake(1); });
  $('btn-back').addEventListener('click', function () { nudge(-10); });
  $('btn-fwd').addEventListener('click', function () { nudge(10); });
  $('btn-repeat').addEventListener('click', function () {
    audio.loop = !audio.loop;
    paintTransport();
  });
  $('btn-speed').addEventListener('click', function () {
    speedIndex = (speedIndex + 1) % SPEEDS.length;
    audio.playbackRate = SPEEDS[speedIndex];
    $('btn-speed').textContent = SPEED_LABELS[speedIndex];
    $('btn-speed').classList.toggle('on', SPEEDS[speedIndex] !== 1);
  });
  $('btn-star').addEventListener('click', async function () {
    var take = currentTake();
    if (!take) { return; }
    try {
      await api('/api/takes/' + take.id + '/favourite?value=' + (take.favourite ? 'false' : 'true'), { method: 'POST' });
      take.favourite = take.favourite ? 0 : 1;
      paintTransport();
      loadTakes();
    } catch (err) { /* leave the star as it was */ }
  });
  $('btn-mute').addEventListener('click', function () {
    audio.muted = !audio.muted;
    paintTransport();
  });
  $('volume').addEventListener('input', function () {
    audio.volume = Number($('volume').value) / 100;
    audio.muted = false;
    try { localStorage.setItem('yue2.volume', $('volume').value); } catch (err) { /* private mode */ }
    paintTransport();
  });
  var saved = null;
  try { saved = localStorage.getItem('yue2.volume'); } catch (err) { saved = null; }
  if (saved !== null) {
    $('volume').value = saved;
    audio.volume = Number(saved) / 100;
  }

  if ('mediaSession' in navigator) {
    var handlers = {
      play: function () { var id = currentTakeId(); if (id && audio.paused) { togglePlay(id); } },
      pause: function () { var id = currentTakeId(); if (id && !audio.paused) { togglePlay(id); } },
      previoustrack: function () { stepTake(-1); },
      nexttrack: function () { stepTake(1); },
      seekbackward: function () { nudge(-10); },
      seekforward: function () { nudge(10); }
    };
    Object.keys(handlers).forEach(function (name) {
      try { navigator.mediaSession.setActionHandler(name, handlers[name]); } catch (err) { /* unsupported action */ }
    });
  }

  ['play', 'pause', 'ended', 'loadedmetadata', 'durationchange', 'seeking'].forEach(function (name) {
    audio.addEventListener(name, function () { updateTimes(); paintTransport(); paintAudition(); });
  });
  paintTransport();
}

function wireWave() {
  var canvas = $('wave');
  canvas.addEventListener('pointerdown', function (event) {
    wave.seeking = true;
    try { canvas.setPointerCapture(event.pointerId); } catch (err) { /* older browsers */ }
    seekFromPointer(event);
  });
  canvas.addEventListener('pointermove', function (event) {
    if (wave.seeking) { seekFromPointer(event); }
  });
  canvas.addEventListener('pointerup', function () { wave.seeking = false; });
  canvas.addEventListener('pointercancel', function () { wave.seeking = false; });
  window.addEventListener('resize', function () { drawWave(); });
  var audio = $('audio');
  audio.addEventListener('play', startWaveLoop);
  audio.addEventListener('playing', startWaveLoop);
  audio.addEventListener('pause', stopWaveLoop);
  audio.addEventListener('ended', function () {
    stopWaveLoop(); wave.ratio = 1; drawWave();
    State.playing = null; State.audition = null;
    paintTakes(); paintTransport(); paintAudition();
  });
  audio.addEventListener('pause', function () {
    // Ignore the pause that fires while a new track is being loaded.
    if (Date.now() - (State.playRequestedAt || 0) < 800) { return; }
    if (State.playing) { State.playing = null; paintTakes(); paintTransport(); }
    // A recording being auditioned stays loaded while paused, so the bar and the
    // space bar resume it rather than starting a take. Only the sound stops.
    paintAudition();
  });
  audio.addEventListener('seeking', function () { syncWaveRatio(); drawWave(); });
  audio.addEventListener('timeupdate', function () { syncWaveRatio(); drawWave(); });
}

/* ------------------------------------------------------------------- form */
async function uploadFile(file) {
  if (!file) { return; }
  $('source-status').textContent = 'Uploading ' + file.name + '\u2026';
  $('source-status').className = 'status';
  var form = new FormData();
  form.append('file', file);
  try {
    var source = await api('/api/sources', { method: 'POST', body: form });
    await loadSources();
    $('source-select').value = source.id;
    setSelection({ formTakeId: Selection.formTakeId });
    paintSource();
    $('source-status').textContent = source.duplicate ? 'That recording is already in the library.' : 'Uploaded. Transcribe it to get a score.';
    $('source-status').className = 'status good';
  } catch (err) {
    $('source-status').textContent = 'Upload failed: ' + err.message;
    $('source-status').className = 'status bad';
  }
}

async function doTranscribe() {
  var source = currentSource();
  if (!source) { $('source-status').textContent = 'Choose a recording first.'; return; }
  try {
    await api('/api/sources/' + source.id + '/transcribe', { method: 'POST' });
    source.transcribe_state = 'queued';
    paintSource();
  } catch (err) {
    $('source-status').textContent = 'Could not start: ' + err.message;
    $('source-status').className = 'status bad';
  }
}

async function doRender() {
  var source = currentSource();
  var status = $('render-status');
  if (!source) { status.textContent = 'Choose a recording first.'; status.className = 'status bad'; return; }
  // A cover follows the recording's own melody, so it needs a score: the one
  // transcribed from it, or one in the box. With neither, rendering used to go
  // ahead and the model wrote its own melody, which is not a cover and sounded
  // like a different song.
  if (!source.has_score && !$('abc').value.trim()) {
    status.textContent = 'This recording has not been transcribed, so there is no melody to cover. '
      + 'Press Transcribe first. For a melody YuE2 writes itself, use Song from a prompt.';
    status.className = 'status bad';
    return;
  }
  var seed = parseInt($('seed').value, 10);
  if (!($('seed-fixed').checked) || isNaN(seed)) {
    seed = Math.floor(Math.random() * 4294967295);
    $('seed').value = seed;
  }
  var identitySel = $('vocal-identity') || $('vocal-persona');
  var pId = identitySel ? identitySel.value : null;
  var loraSel = $('vocal-identity-lora') || $('vocal-persona-lora');
  var vLora = (pId && loraSel && !loraSel.classList.contains('hidden')) ? loraSel.value : null;
  var body = {
    source_id: source.id,
    title: $('title').value.trim() || guessTitle($('lyrics').value) || source.title,
    style: $('style').value,
    lyrics: $('lyrics').value,
    abc: $('abc').value,
    mode: $('mode').value,
    seed: seed,
    interpretation: $('interpretation').value,
    max_duration: parseFloat($('max-duration').value) || 360,
    space_id: State.spaceId,
    realaudio: $('realaudio').checked,
    identity_id: pId || null,
    persona_id: pId || null,
    voice_lora: vLora || null,
    voice_lora_clip: vocalPlanner()
  };
  withStyleLora(body);
  status.textContent = 'Queued\u2026';
  status.className = 'status';
  try {
    await api('/api/takes', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    status.textContent = '';
    loadTakes();
  } catch (err) {
    status.textContent = 'Could not queue: ' + err.message;
    status.className = 'status bad';
  }
}

/* The score itself decides the length: bars, meter and tempo. Measured against six
   finished renders, this lands within about 5 per cent, unless the cap cuts the song short. */
function planLength(abc) {
  if (!abc) { return null; }
  var meter = /^M:(\d+)\/(\d+)/m.exec(abc);
  var beats = meter ? parseInt(meter[1], 10) : 4;
  var tempo = /^Q:1\/4=(\d+)/m.exec(abc);
  var bpm = tempo ? parseInt(tempo[1], 10) : 120;
  var totals = {};
  var voice = null;
  abc.split('\n').forEach(function (raw) {
    var line = raw.trim();
    if (line.indexOf('V:') === 0) { voice = line.slice(2).trim().split(/\s+/)[0]; return; }
    if (!line || line.charAt(0) === '%' || /^[XTMLQK]:/.test(line) || !voice) { return; }
    totals[voice] = (totals[voice] || 0) + (line.split('|').length - 1);
  });
  var best = 0;
  Object.keys(totals).forEach(function (name) { if (totals[name] > best) { best = totals[name]; } });
  if (!best) { return null; }
  return { bars: best, bpm: bpm, seconds: best * beats * 60 / bpm };
}

/* The chart is a toggle. The button says what the next click will do. */
function setChart(text) {
  var hasChart = Boolean(text);
  $('chart').textContent = hasChart ? text : '';
  $('chord-chart').textContent = hasChart ? 'Hide chart' : 'Chord chart';
}

function showPlanLength(abc) {
  var node = $('plan-length');
  if (!node) { return; }
  var info = planLength(abc);
  if (!info) { node.textContent = ''; return; }
  var cap = parseFloat($('max-duration').value) || 360;
  var text = 'Score is ' + info.bars + ' bars at ' + info.bpm + ' BPM, so about ' + secs(info.seconds);
  if (info.seconds > cap) {
    text += '. Your cap of ' + secs(cap) + ' will cut it short.';
  } else {
    text += '. Cap ' + secs(cap) + ', so it will fit.';
  }
  node.textContent = text;
}

function chordChart(abc) {
  var section = 'song';
  var voice = null;
  var chart = {};
  var order = [];
  abc.split('\n').forEach(function (raw) {
    var line = raw.trim();
    if (line.charAt(0) === '%') { section = line.replace(/^%\s*/, '') || 'section'; return; }
    if (line.indexOf('V:') === 0) { voice = line.slice(2).trim().split(/\s+/)[0]; return; }
    if (!line || voice !== 'Vocal' || /^[XTM LQK]:/.test(line)) { return; }
    var last = null;
    line.split('|').forEach(function (bar) {
      if (!bar.trim()) { return; }
      // Any symbol that starts with a note: Cmaj7, Bm7b5, and slash chords such as C7/Bb.
      var found = bar.match(/"([A-G][#b]?[^"\s]*)"/g);
      // One bar can carry more than one chord, for example "F#"z8"E"z8. Keep every symbol.
      var list = found ? found.map(function (chord) { return chord.replace(/"/g, ''); })
                       : (last === null ? [] : [last]);
      list.forEach(function (chord) {
        if (!chart[section]) { chart[section] = []; order.push(section); }
        chart[section].push(chord);
        last = chord;
      });
    });
  });
  if (!order.length) {
    return State.mode !== 'cover'
      ? 'No chord symbols in this score. The plan may have come out broken: write a new plan, or choose a calmer Plan variety.'
      : 'No chord symbols in this score. Use full mode when you transcribe to get chords.';
  }
  var total = 0;
  var lines = order.map(function (name) {
    var bars = chart[name];
    total += bars.length;
    var folded = [];
    for (var i = 0; i < bars.length; i++) {
      var count = 1;
      while (i + 1 < bars.length && bars[i + 1] === bars[i]) { count += 1; i += 1; }
      folded.push(count > 1 ? bars[i] + ' x' + count : bars[i]);
    }
    var padded = (name + '            ').slice(0, 12);
    return padded + '| ' + folded.join('  ');
  });
  var distinct = {};
  order.forEach(function (name) { chart[name].forEach(function (chord) { distinct[chord] = 1; }); });
  lines.push('');
  lines.push(total + ' bars, ' + Object.keys(distinct).length + ' different chords. ' + (State.mode !== 'cover'
    ? 'A short loop that repeats all song is the model being lazy. Raise Harmony, or edit the symbols.'
    : 'These are the recording\u2019s chords. Edit the symbols, or render in melody mode to let YuE2 choose its own.'));
  return lines.join('\n');
}

/* ---- an instrumental that plans a vocal line ---------------------------- */
/* The instrumental LoRA writes the vocal part as rests. When it writes a melody
   there instead, the render often sings — not always, which is why this asks
   rather than refuses. */
function openSungWarning(take) {
  var rendered = take.status === 'done';
  State.sungTakeId = take.id;
  State.sungRendered = rendered;
  $('sung-title').textContent = rendered ? 'This instrumental has singing in it' : 'This plan may sing';
  if (rendered) {
    $('sung-text').textContent = 'There is singing in ' + Math.round((take.vocal_check || 0) * 100) + '% of it.';
  } else {
    // The same sentence is a status line on the card and the opening line here,
    // so it starts a sentence properly in the window.
    var why = take.error || 'The plan has a melody in the vocal part.';
    $('sung-text').textContent = why.charAt(0).toUpperCase() + why.slice(1) + '.';
  }
  $('sung-advice').textContent = rendered
    ? 'A new seed usually clears it. A new plan changes the music too.'
    : 'It may be fine. A new plan is quick, and uses a new seed.';
  $('sung-render').textContent = rendered ? 'New seed' : 'Render anyway';
  $('sung-variety').value = take.variety || 'normal';
  $('sung-modal').classList.remove('hidden');
}

function closeSungWarning() {
  State.sungTakeId = null;
  $('sung-modal').classList.add('hidden');
}

async function renderAnyway() {
  var id = State.sungTakeId;
  var reseed = State.sungRendered;     // a finished take is worth another seed
  closeSungWarning();
  if (!id) { return; }
  selectTake(takeById(id));
  await api('/api/takes/' + id + '/render', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ realaudio: $('realaudio').checked, reseed: reseed })
  });
  if (reseed) { statusLine('Rendering the same score again with a new seed\u2026'); }
  loadTakes();
}

async function replanInstead() {
  var id = State.sungTakeId;
  var variety = $('sung-variety').value;
  closeSungWarning();
  if (!id) { return; }
  selectTake(takeById(id));
  await api('/api/takes/' + id + '/replan', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ variety: variety })
  });
  awaitNewPlan(id);
  statusLine('Writing a new plan, with a new seed\u2026');
  loadTakes();
}

/* ------------------------------------------------------------------ wiring */
function wire() {
  paintPresets();
  $('presets').addEventListener('click', function (event) {
    var button = event.target.closest('[data-preset]');
    if (button) { $('style').value = button.dataset.preset; paintVocals(); }
  });
  $('vocal-sex').addEventListener('click', function (event) {
    var button = event.target.closest('[data-sex]');
    if (button) { setVocalSex(button.dataset.sex); }
  });
  $('vocal-tone').addEventListener('click', function (event) {
    var button = event.target.closest('[data-tone]');
    if (button) { toggleVocalTone(button.dataset.tone); }
  });
  var vocalIdSel = $('vocal-identity') || $('vocal-persona');
  if (vocalIdSel) { vocalIdSel.addEventListener('change', onVocalIdentityChange); }
  var vocalLoraSel = $('vocal-identity-lora') || $('vocal-persona-lora');
  if (vocalLoraSel) { vocalLoraSel.addEventListener('change', saveForm); }
  $('style').addEventListener('input', paintVocals);
  $('harmony').addEventListener('input', paintHarmony);

  $('browse').addEventListener('click', function () { $('file').click(); });
  $('file').addEventListener('change', function (event) { uploadFile(event.target.files[0]); });
  var drop = $('drop');
  drop.addEventListener('dragover', function (event) { event.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', function () { drop.classList.remove('over'); });
  drop.addEventListener('drop', function (event) {
    event.preventDefault();
    drop.classList.remove('over');
    if (event.dataTransfer.files.length) { uploadFile(event.dataTransfer.files[0]); }
  });

  $('source-select').addEventListener('change', function () {
    // Choosing a recording the box's take did not come from lets go of that take:
    // its words and its score are not this recording's, and covering one with the
    // other's score is how a render came out as a different song.
    if (scoreTakeId() && !boxShowsSource($('source-select').value)) { setSelection({}); }
    paintSource();
  });
  $('transcribe').addEventListener('click', doTranscribe);
  $('create-cover').addEventListener('click', doRender);
  $('create-song').addEventListener('click', doPlan);
  $('render-take').addEventListener('click', doRenderTake);
  $('sung-cancel').addEventListener('click', closeSungWarning);
  $('sung-render').addEventListener('click', renderAnyway);
  $('sung-replan').addEventListener('click', replanInstead);
  $('sung-modal').addEventListener('click', function (event) {
    if (event.target === $('sung-modal')) { closeSungWarning(); }
  });
  $('reroll').addEventListener('click', doReroll);
  document.querySelector('.modes').addEventListener('click', function (event) {
    var button = event.target.closest('[data-mode]');
    if (button) { setMode(button.dataset.mode); }
  });

  $('save-score').addEventListener('click', async function () {
    if (!scoreIsDirty()) { return; }
    var takeId = takeIdInEditor();
    var source = currentSource();
    var url = takeId ? '/api/takes/' + takeId + '/score'
                     : (State.mode === 'cover' && source ? '/api/sources/' + source.id + '/score' : '');
    if (!url) {
      statusLine(State.mode !== 'cover'
        ? 'A score plan is saved with its take. Write a score plan first.'
        : 'Choose a recording to save this score to.', 'bad');
      return;
    }
    try {
      await api(url, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ abc: $('abc').value })
      });
    } catch (err) {
      statusLine('Could not save the score: ' + err.message, 'bad');
      return;
    }
    scoreBaseline($('abc').value);
    confirmScoreSaved();
    statusLine('Score saved.', 'good');
    $('source-status').textContent = 'Score saved.';
    $('source-status').className = 'status good';
    loadSources();
    loadTakes();
  });

  $('do-replace').addEventListener('click', function () {
    var find = $('find-chord').value.trim();
    var replace = $('replace-chord').value.trim();
    if (!find) { statusLine('Type the chord to find first.', 'bad'); return; }
    var text = $('abc').value;
    var quoted = '"' + find + '"';
    var count = text.split(quoted).length - 1;
    if (!count) { statusLine('This score has no chord "' + find + '".', 'bad'); return; }
    $('abc').value = text.split(quoted).join('"' + replace + '"');
    setChart(chordChart($('abc').value));
    syncEditor();
    statusLine('Replaced ' + count + ' with "' + replace + '". Now save the score, then render.', 'good');
  });

  $('chord-chart').addEventListener('click', function () {
    if ($('chart').textContent) { setChart(''); return; }
    setChart(chordChart($('abc').value));
    showPlanLength($('abc').value);
  });

  $('dice').addEventListener('click', function () {
    $('seed').value = Math.floor(Math.random() * 4294967295);
    $('seed-fixed').checked = true;
  });

  $('layout-toggle').addEventListener('click', function () {
    applyLayout(State.layout === 'comfy' ? 'compact' : 'comfy');
  });

  document.querySelector('.filters').addEventListener('click', function (event) {
    var button = event.target.closest('[data-filter]');
    if (!button) { return; }
    State.filter = button.dataset.filter;
    Array.prototype.forEach.call(document.querySelectorAll('.filters .chip'), function (chip) { chip.classList.remove('active'); });
    button.classList.add('active');
    State.takesRaw = '';
    loadTakes();
  });
  $('takes-more').addEventListener('click', function () {
    State.takeLimit += 300;
    loadTakes();
  });

  $('takes').addEventListener('click', function (event) {
    // Save is an anchor, not a button, so the tile handler below never sees it.
    var link = event.target.closest('a.save[href^="/api/takes/"]');
    if (link) { selectTake(takeById(link.getAttribute('href').split('/')[3])); }
  });

  $('takes').addEventListener('click', function (event) {
    // Clicking anywhere on the card, except on a control inside it, makes that
    // take the one the left column describes.
    if (event.target.closest('button, a, input, select, textarea, label')) { return; }
    var card = event.target.closest('.take');
    if (card && card.dataset.id) { selectTake(takeById(card.dataset.id)); }
  });

  $('takes').addEventListener('click', function (event) {
    var button = event.target.closest('button[data-act]');
    if (!button) { return; }
    takeAction(button).catch(function (err) {
      statusLine('Could not ' + button.textContent.trim().toLowerCase() + ': ' + err.message, 'bad');
      loadTakes();
    });
  });
  $('source-delete').addEventListener('click', deleteSource);
  $('start-fresh').addEventListener('click', startFresh);
  var openBtn = $('identities-open') || $('personas-open');
  if (openBtn) { openBtn.addEventListener('click', openIdentities); }
  var closeBtn = $('identities-close') || $('personas-close');
  if (closeBtn) { closeBtn.addEventListener('click', closeIdentities); }
  var backBtn = $('identities-back') || $('personas-back');
  if (backBtn) { backBtn.addEventListener('click', showIdentityList); }
  var bodyEl = $('identities-body') || $('personas-body');
  if (bodyEl) {
    bodyEl.addEventListener('click', function (event) {
      identityClick(event).catch(function (err) { statusLine(err.message, 'bad'); });
    });
    bodyEl.addEventListener('change', function (event) {
      identityChange(event).catch(function (err) { statusLine(err.message, 'bad'); });
    });
    bodyEl.addEventListener('input', function (event) {
      if (event.target.dataset.lyrics) { event.target.dataset.edited = '1'; }
    });
  }
  wireStructure();
  $('interpretation').addEventListener('change', paintInterpretation);
  $('lyrics-write').addEventListener('click', openWrite);
  $('audition').addEventListener('click', function () { playRecording(); });
  $('source-lyrics').addEventListener('click', function () {
    hearLyrics().catch(function (err) { statusLine('Could not start: ' + err.message, 'bad'); });
  });
  $('lyrics-hear-stop').addEventListener('click', function () {
    var source = currentSource();
    if (!source) { return; }
    api('/api/sources/' + source.id + '/lyrics', { method: 'DELETE' })
      .then(stopHearPoll)
      .catch(function () { stopHearPoll(); });
  });
  $('write-close').addEventListener('click', closeWrite);
  $('write-go').addEventListener('click', doWrite);
  $('write-stop').addEventListener('click', stopWrite);
  $('write-modal').addEventListener('click', function (event) { if (event.target === $('write-modal')) { closeWrite(); } });
  $('variations-close').addEventListener('click', closeVariations);
  $('variations-go').addEventListener('click', doVariations);
  $('variations-list').addEventListener('change', paintVariationsEstimate);
  $('variations-modal').addEventListener('click', function (event) {
    if (event.target === $('variations-modal')) { closeVariations(); }
  });
  $('space').addEventListener('change', function () { showSpace($('space').value); });
  $('space-new').addEventListener('click', newSpace);
  $('space-rename').addEventListener('click', renameSpace);
  $('space-delete').addEventListener('click', deleteSpace);
  $('move-close').addEventListener('click', closeMoveModal);
  $('move-modal').addEventListener('click', function (event) {
    if (event.target === $('move-modal')) { closeMoveModal(); }
  });
  $('move-list').addEventListener('click', function (event) {
    var button = event.target.closest('button[data-space]');
    if (!button) { return; }
    moveTake(button.dataset.space).catch(function (err) { $('move-status').textContent = err.message; $('move-status').className = 'status bad'; });
  });
  async function createAndMove() {
    var name = $('move-name').value.trim();
    if (!name) { $('move-name').focus(); return; }
    try {
      var space = await api('/api/spaces', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name })
      });
      State.spaces.push(space);
      await moveTake(space.id);
    } catch (err) {
      $('move-status').textContent = err.message;
      $('move-status').className = 'status bad';
    }
  }
  $('move-create').addEventListener('click', createAndMove);
  $('move-name').addEventListener('keydown', function (event) { if (event.key === 'Enter') { createAndMove(); } });
  $('draft-restore').addEventListener('click', restoreDraft);
  $('draft-dismiss').addEventListener('click', dismissDraft);

  async function takeAction(button) {
    var id = button.dataset.id;
    var act = button.dataset.act;
    if (act === 'cancel') {
      await api('/api/takes/' + id + '/cancel', { method: 'POST' });
      loadTakes();
    }
    if (act === 'play') {
      selectTake(takeById(id));
      togglePlay(id);
    }
    if (act === 'star') {
      var take = State.takes.filter(function (t) { return t.id === id; })[0];
      await api('/api/takes/' + id + '/favourite?value=' + (take && take.favourite ? 'false' : 'true'), { method: 'POST' });
      loadTakes();
    }
    if (act === 'del') {
      if (confirm('Delete this take and its audio?')) {
        await api('/api/takes/' + id, { method: 'DELETE' });
        loadTakes();
      }
    }
    if (act === 'open') {
      var opened = takeById(id);
      if (!opened) { return; }
      selectTake(opened);
      statusLine('Showing the score for ' + opened.title + '.', 'good');
      $('score-box').scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    if (act === 'stems') {
      var stemTake = takeById(id);
      if (stemTake) {
        selectTake(stemTake);
        openStemsModal({ kind: 'take', id: stemTake.id, title: stemTake.title });
      }
    }
    if (act === 'stem-play') {
      playStem(button.dataset.set, button.dataset.file);
    }
    if (act === 'stem-del') {
      await api('/api/stem-sets/' + button.dataset.set, { method: 'DELETE' });
      loadTakes();
    }
    if (act === 'sung') {
      var spoiled = takeById(id);
      if (spoiled) { openSungWarning(spoiled); }
      return;
    }
    if (act === 'render') {
      var planned = takeById(id);
      // An instrumental whose plan holds a vocal line: say so before the render
      // is paid for, and let the choice be made with the facts in hand.
      if (planned && planned.kind === 'instrumental' && planned.status === 'planned' && planned.error) {
        openSungWarning(planned);
        return;
      }
      selectTake(takeById(id));
      await api('/api/takes/' + id + '/render', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ realaudio: $('realaudio').checked })
      });
      loadTakes();
    }
    if (act === 'clear') {
      try {
        var cleared = await api('/api/takes/' + id + '/clear', { method: 'POST' });
        statusLine('Cleared. The take is back to ' + (cleared.status === 'done' ? 'its audio.' : 'its score.'), 'good');
      } catch (err) {
        statusLine(err.message, 'bad');
      }
      loadTakes();
    }
    if (act === 'replan') {
      selectTake(takeById(id));
      await api('/api/takes/' + id + '/replan', { method: 'POST' });
      awaitNewPlan(id);
      statusLine('Writing a new plan for the same words\u2026');
      loadTakes();
    }
    if (act === 'variations') {
      var source = takeById(id);
      if (source) { openVariations(source); }
    }
    if (act === 'move') {
      var moving = takeById(id);
      if (moving) { openMoveModal(moving); }
    }
    if (act === 'again') {
      var previous = takeById(id);
      if (!previous) { return; }
      selectTake(previous);
      $('seed').value = Math.floor(Math.random() * 4294967295);
      $('seed-fixed').checked = true;
      var createButton = $({ song: 'create-song', instrumental: 'create-inst' }[previous.kind] || 'create-cover');
      if (createButton) { createButton.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
    }
  }

  $('job-stop').addEventListener('click', function () {
    api('/api/jobs/current/cancel', { method: 'POST' }).then(loadTakes).catch(function (err) {
      statusLine('Could not stop the job: ' + err.message, 'bad');
    });
  });

  wireWave();
  wireTransport();
  paintVocals();
  loadVocalIdentities();

  FORM_FIELDS.forEach(function (id) {
    $(id).addEventListener('input', function () {
      if (id === 'style') { $('style').dataset.touched = '1'; }
      saveForm();
    });
    $(id).addEventListener('change', saveForm);
  });
  $('auto-render').addEventListener('change', saveForm);
  $('seed-fixed').addEventListener('change', saveForm);
  $('realaudio').addEventListener('change', saveForm);
  $('vocal-planner').addEventListener('input', function () {
    paintVocalPlanner();
    saveForm();
  });
  $('style-lora').addEventListener('change', function () {
    var item = loraChosen();
    applyLoraTrigger(item && item.trigger);
    paintStyleLoraStrengths();
    saveForm();
  });
  ['style-lora-model', 'style-lora-clip'].forEach(function (id) {
    $(id).addEventListener('input', function () {
      $(id + '-read').textContent = Number($(id).value).toFixed(2);
      saveForm();
    });
  });
  $('lyrics').addEventListener('input', function () {
    State.formEdited = true;
    refreshTitleHint();
  });
  ['title', 'style'].forEach(function (id) {
    $(id).addEventListener('input', function () { State.formEdited = true; });
  });
  $('abc').addEventListener('input', function () {
    saveWorkingScore();
    pushScoreHistory($('abc').value);
    paintScoreDirty();
  });

  $('brand').addEventListener('click', function (event) {
    event.stopPropagation();
    toggleBrandMenu();
  });
  var menuIdentities = $('menu-identities');
  if (menuIdentities) {
    menuIdentities.addEventListener('click', function (event) {
      event.stopPropagation();
      openIdentities();
    });
  }
  var menuSettings = $('menu-settings');
  if (menuSettings) {
    menuSettings.addEventListener('click', function (event) {
      event.stopPropagation();
      openSettings();
    });
  }
  document.addEventListener('click', function (event) {
    if (!event.target.closest('.brand-wrap')) {
      closeBrandMenu();
    }
  });
  $('settings-close').addEventListener('click', closeSettings);
  $('settings-modal').addEventListener('click', function (event) {
    if (event.target === $('settings-modal')) { closeSettings(); }
  });
  $('settings-list').addEventListener('change', function (event) {
    if (event.target.dataset && event.target.dataset.key) { saveSetting(event.target); }
  });
  $('settings-list').addEventListener('blur', function (event) {
    if (event.target.dataset && event.target.dataset.key && event.target.tagName === 'INPUT') { saveSetting(event.target); }
  }, true);
  $('stems-close').addEventListener('click', closeStemsModal);
  $('stems-run').addEventListener('click', runStems);
  $('stems-model').addEventListener('change', paintStemChoices);
  $('stems-modal').addEventListener('click', function (event) {
    if (event.target === $('stems-modal')) { closeStemsModal(); }
  });
  $('lyrics-expand').addEventListener('click', openLyricsEditor);
  $('score-expand').addEventListener('click', function (event) {
    event.preventDefault();   // the Expand sits inside a summary, which toggles the box
    openScoreEditor();
  });
  try {
    var savedView = localStorage.getItem(SCORE_VIEW_KEY);
    if (savedView) { State.scoreView = savedView; }
  } catch (err) { /* private mode */ }
  $('score-close').addEventListener('click', closeScoreEditor);
  $('score-big').addEventListener('input', syncScoreFromBig);
  $('do-replace-big').addEventListener('click', function () {
    var find = $('find-chord-big').value.trim();
    var replace = $('replace-chord-big').value.trim();
    if (!find) { return; }
    var text = $('score-big').value;
    if (text.indexOf('"' + find + '"') === -1) { return; }
    scoreStack.at = 0;   // a replace is always its own step
    $('score-big').value = text.split('"' + find + '"').join('"' + replace + '"');
    syncScoreFromBig();
  });
  $('score-modal').addEventListener('click', function (event) {
    if (event.target === $('score-modal')) { closeScoreEditor(); }
  });
  $('score-views').addEventListener('click', function (event) {
    var chip = event.target.closest('[data-view]');
    if (chip) { setScoreView(chip.dataset.view); }
  });
  paintScoreDirty();
  $('score-undo').addEventListener('click', undoScore);
  $('score-redo').addEventListener('click', redoScore);
  paintScoreHistory();
  $('lyrics-close').addEventListener('click', closeLyricsEditor);
  $('lyrics-big').addEventListener('input', syncLyricsFromBig);
  $('lyrics-modal').addEventListener('click', function (event) {
    if (event.target === $('lyrics-modal')) { closeLyricsEditor(); }
  });
  document.querySelector('.modal-tools').addEventListener('click', function (event) {
    var button = event.target.closest('[data-tag]');
    if (button) { insertTag(button.dataset.tag); }
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && $('brand-menu') && !$('brand-menu').classList.contains('hidden')) { closeBrandMenu(); return; }
    if (event.key === 'Escape' && !$('sung-modal').classList.contains('hidden')) { closeSungWarning(); return; }
    if (event.key === 'Escape' && !$('move-modal').classList.contains('hidden')) { closeMoveModal(); return; }
    var idModal = $('identities-modal') || $('personas-modal');
    if (event.key === 'Escape' && idModal && !idModal.classList.contains('hidden')) { closeIdentities(); return; }
    if (event.key === 'Escape' && !$('write-modal').classList.contains('hidden')) { closeWrite(); return; }
    if (event.key === 'Escape' && !$('variations-modal').classList.contains('hidden')) { closeVariations(); return; }
    if (event.key === 'Escape' && !$('lyrics-modal').classList.contains('hidden')) { closeLyricsEditor(); return; }
    if (event.key === 'Escape' && !$('stems-modal').classList.contains('hidden')) { closeStemsModal(); return; }
    if (event.key === 'Escape' && !$('settings-modal').classList.contains('hidden')) { closeSettings(); return; }
    if (event.key === 'Escape' && !$('score-modal').classList.contains('hidden')) { closeScoreEditor(); return; }

    // Undo and redo of the score, from either box.
    var focus = document.activeElement;
    var inScore = focus === $('abc') || focus === $('score-big');
    if (inScore && (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'z') {
      event.preventDefault();
      if (event.shiftKey) { redoScore(); } else { undoScore(); }
      return;
    }
    if (inScore && (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'y') {
      event.preventDefault();
      redoScore();
      return;
    }

    // Playback shortcuts, but never while typing, and never through a window
    // that is open in front: space belongs to whatever the eye is on.
    var tag = (focus && focus.tagName) || '';
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') { return; }
    if (document.querySelector('.modal:not(.hidden)')) { return; }
    if (event.code === 'Space') { event.preventDefault(); $('btn-play').click(); }
    else if (event.key === 'ArrowLeft') { nudge(-5); }
    else if (event.key === 'ArrowRight') { nudge(5); }
    else if (event.key === 'ArrowUp') { event.preventDefault(); $('volume').value = Math.min(100, Number($('volume').value) + 5); $('volume').dispatchEvent(new Event('input')); }
    else if (event.key === 'ArrowDown') { event.preventDefault(); $('volume').value = Math.max(0, Number($('volume').value) - 5); $('volume').dispatchEvent(new Event('input')); }
  });
}

wire();
loadLayout();
loadSpaceChoice();
loadForm();
paintHarmony();
loadWorkingScore();
setScoreActions();
refreshTitleHint();
setMode('cover');
pollState();
loadSources();
loadSpaces().catch(function () { /* the takes poll retries */ });
loadTakes();

/* Polls never overlap, and stop while the tab is hidden. */
function every(ms, fn) {
  var running = false;
  setInterval(function () {
    if (running || document.hidden) { return; }
    running = true;
    Promise.resolve().then(fn).catch(function () { /* the next tick retries */ })
      .then(function () { running = false; });
  }, ms);
}
every(2000, pollState);
// Every 3 seconds while something is running, so progress on the cards moves;
// every 6 when idle.
every(3000, function () {
  var working = State.busy || State.takes.some(function (take) {
    return take.status === 'queued' || take.status === 'running' ||
      (take.stem_sets || []).some(function (set) { return set.status === 'queued' || set.status === 'running'; });
  });
  if (!working && Date.now() - State.takesAt < 6000) { return; }
  return loadTakes();
});
document.addEventListener('visibilitychange', function () {
  if (!document.hidden) { pollState(); loadTakes(); }
});
