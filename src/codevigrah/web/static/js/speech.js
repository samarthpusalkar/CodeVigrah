// Read aloud. The server prepares what to say: a listening script split into segments, each tagged with the source
// line of the block it belongs to (data-ln in the page), so the highlight follows the voice. Natural voices are made by
// the speech server, one sentence at a time, when one is configured; otherwise this device's own voices speak.
const synth = window.speechSynthesis;
const TTS = { q: [], i: 0, p: 0, on: false, paused: false, held: false, mode: '', token: 0, run: 0, opts: {}, sid: null,
  source: '', container: null, audio: new Audio(), clips: new Map(), poll: null, upgrade: null };
const SILENCE = (() => {  // 0.1 s of silence: playing it inside the click "unlocks" audio on Safari and iOS
  const n = 800, b = new DataView(new ArrayBuffer(44 + n)), w = (o, s) => [...s].forEach((c, k) => b.setUint8(o + k, c.charCodeAt(0)));
  w(0, 'RIFF'); b.setUint32(4, 36 + n, true); w(8, 'WAVEfmt '); b.setUint32(16, 16, true); b.setUint16(20, 1, true); b.setUint16(22, 1, true);
  b.setUint32(24, 8000, true); b.setUint32(28, 8000, true); b.setUint16(32, 1, true); b.setUint16(34, 8, true); w(36, 'data'); b.setUint32(40, n, true);
  for (let k = 0; k < n; k++) b.setUint8(44 + k, 128);
  return URL.createObjectURL(new Blob([b.buffer], { type: 'audio/wav' }));
})();

// ------------------------------------------------------------------ voices
const serverVoices = () => (typeof SETTINGS !== 'undefined' && SETTINGS && SETTINGS.tts && SETTINGS.tts.available) ? SETTINGS.tts.voices : [];
function deviceVoices() { const vs = synth ? synth.getVoices() : []; const en = vs.filter(v => /^en/i.test(v.lang)); return en.length ? en : vs; }
const goodDevice = list => list.find(v => /natural|neural|google|samantha|premium|enhanced/i.test(v.name)) || list.find(v => v.default) || list[0];
function ttsVoices() {
  const sel = $('#tvoice'); if (!sel) return;
  const sv = serverVoices(), dv = deviceVoices(); let saved = store.get('ttsvoice', '');
  if (saved && !/^[sb]:/.test(saved)) saved = 'b:' + saved;  // saved before natural voices existed
  const opts = [...sv.map(v => 's:' + v.id), ...dv.map(v => 'b:' + v.name)];
  const g = goodDevice(dv), def = sv.length ? 's:' + (SETTINGS.tts.default || sv[0].id) : g ? 'b:' + g.name : '';
  const pick = opts.includes(saved) ? saved : def;
  const o = (v, label) => `<option value="${esc(v)}" ${v === pick ? 'selected' : ''}>${esc(label)}</option>`;
  sel.innerHTML = (sv.length ? `<optgroup label="Natural voices (made on the server)">${sv.map(v => o('s:' + v.id, v.label)).join('')}</optgroup>` : '')
    + (dv.length ? `<optgroup label="This device's voices">${dv.map(v => o('b:' + v.name, `${v.name.replace(/Microsoft |Google /, '')} (${v.lang})`)).join('')}</optgroup>` : '');
}
if (synth) { ttsVoices(); synth.onvoiceschanged = ttsVoices; }
function ttsVoice() { const v = $('#tvoice').value || ''; return v.startsWith('s:') ? { server: v.slice(2) } : { name: v.slice(2) }; }
const ttsRate = () => +$('#trate').value || 1;

// ------------------------------------------------------------------ what to say
// Fallback when the server cannot prepare a script: read the page itself, lightly cleaned.
function speakText(el) {
  if (el.classList.contains('diagram')) return 'There is a diagram here.';
  if (el.tagName === 'PRE') return 'There is a code example here.';
  let t = el.innerText || '';
  t = t.replace(/(?:[\w.\-@]+\/)+([\w.\-@]+)/g, '$1')        // paths -> file name
       .replace(/([\w)])\:\d+(?:-\d+)?\b/g, '$1')               // drop :line
       .replace(/::/g, ' ').replace(/\s*(->|→|=>)\s*/g, ' to ').replace(/[`*_#>|]/g, ' ')
       .replace(/\be\.g\./gi, 'for example').replace(/\bi\.e\./gi, 'that is').replace(/\s+/g, ' ').trim();
  return t;
}
function chunkText(t) {
  const out = []; t.split(/(?<=[.!?]["')\]]*)\s+/).forEach(sn => {
    sn = sn.trim(); while (sn.length > 220) { const k = sn.lastIndexOf(',', 220) > 80 ? sn.lastIndexOf(',', 220) + 1 : sn.lastIndexOf(' ', 220); out.push(sn.slice(0, k)); sn = sn.slice(k).trim(); }
    if (sn) out.push(sn); });
  return out;
}
function pageQueue(container) {
  return [...container.querySelectorAll('h1, h2, h3, p, li, pre, .diagram, blockquote')]
    .filter(e => !e.closest('details') && !e.closest('.diagram pre') && !(e.tagName === 'PRE' && e.closest('.diagram')) && !(e.tagName === 'P' && e.closest('li, blockquote')) && speakText(e))
    .map(e => ({ el: e, ln: +(e.dataset.ln || 0), kind: /^H\d$/.test(e.tagName) ? 'heading' : 'para', parts: chunkText(speakText(e)), seg: null }));
}
// Server segments -> queue items, each pointing at the block on the page it was written from.
function scriptQueue(r) {
  const els = [...TTS.container.querySelectorAll('[data-ln]')].filter(e => { const up = e.parentElement.closest('[data-ln]'); return !up || !TTS.container.contains(up); });
  const at = ln => { let best = null; for (const e of els) { if (+e.dataset.ln <= ln) best = e; else break; } return best || els[0] || null; };
  return r.segments.map((s, k) => ({ el: s.ln < 0 ? null : at(s.ln), ln: s.ln, kind: s.kind, parts: s.parts, seg: k })).filter(x => x.parts.length);
}
async function ttsPrepare(run) {
  const r = await api('/api/speech', { id: RID, ...TTS.opts.source, plain: !$('#tscript').checked });
  if (run !== TTS.run) return [];
  useScript(r);
  if (r.pending) ttsPoll(run, 0);
  return scriptQueue(r);
}
function useScript(r) {
  if (r.sid !== TTS.sid) { TTS.clips.forEach(pr => pr.then(u => URL.revokeObjectURL(u), () => {})); TTS.clips.clear(); }
  TTS.sid = r.sid; TTS.source = r.source; ttsLabel(r.pending);
}
// The AI listening script is still being written: check back, and switch to it at the next paragraph.
function ttsPoll(run, tries) {
  clearTimeout(TTS.poll); if (tries > 30) return;
  TTS.poll = setTimeout(async () => {
    if (run !== TTS.run) return;
    try { const r = await api('/api/speech', { id: RID, ...TTS.opts.source });
      if (run !== TTS.run) return;
      if (r.source === 'ai') TTS.upgrade = r; else if (r.pending) ttsPoll(run, tries + 1); else ttsLabel(false);
    } catch { ttsPoll(run, tries + 1); }
  }, 10000);
}
function applyUpgrade() {
  const r = TTS.upgrade; if (!r) return; TTS.upgrade = null;
  const last = TTS.q[TTS.i - 1], lastLn = last ? last.ln : -2;
  useScript(r); const q = scriptQueue(r), k = q.findIndex(x => x.ln > lastLn);
  TTS.q = q; TTS.i = k < 0 ? q.length : k; TTS.p = 0;
}

// ------------------------------------------------------------------ playing
async function ttsStart(container, opts = {}) {
  if (!container) return;
  if (!synth && !serverVoices().length) { alert('This browser has no built-in speech. Try Chrome, Edge or Safari.'); return; }
  ttsStop(true);
  const run = ++TTS.run;
  if (ttsVoice().server) { TTS.audio.src = SILENCE; TTS.audio.play().catch(() => {}); }
  Object.assign(TTS, { on: true, paused: false, held: false, opts, container, q: [], i: 0, p: 0, upgrade: null, source: '' });
  $('#player').style.display = 'flex'; $('#tautowrap').style.display = opts.tour ? '' : 'none'; $('#tscriptwrap').style.display = opts.source && opts.source.chapter ? '' : 'none';
  $('#tplay').textContent = '⏸'; ttsNow('Preparing…');
  let q = [];
  if (opts.source && RID) { try { q = await ttsPrepare(run); } catch { q = []; } }
  if (run !== TTS.run) return;
  if (!q.length) { q = pageQueue(container); TTS.sid = null; TTS.source = 'page'; ttsLabel(false); }
  if (!q.length) { ttsStop(); return; }
  TTS.q = q; TTS.i = 0;
  if (opts.fromLn != null) { const k = q.findIndex(x => x.ln >= opts.fromLn); TTS.i = k < 0 ? 0 : k; }
  ttsPlay(TTS.token);
}
function ttsPlay(token) {
  if (token !== TTS.token || !TTS.on) return;
  if (TTS.paused) { TTS.held = true; return; }
  const cur = TTS.q[TTS.i];
  if (cur && TTS.p >= cur.parts.length) {  // this block is done: a short pause, longer after a heading
    TTS.i++; TTS.p = 0; applyUpgrade();
    const gap = cur.kind === 'heading' || cur.kind === 'intro' ? 450 : cur.kind === 'item' ? 200 : 320;
    setTimeout(() => ttsPlay(token), gap / ttsRate()); return;
  }
  if (!cur) { const f = TTS.opts.onFinish; ttsStop(); if (f) f(); return; }
  if (TTS.p === 0) mark(cur);
  ttsNow(cur.parts[TTS.p]);
  const v = ttsVoice();
  if (v.server && cur.seg != null && TTS.sid) playServer(cur, token, v.server); else playDevice(cur, token, v.name);
}
const partDone = token => () => { if (token === TTS.token) { TTS.p++; ttsPlay(token); } };
function mark(it) {
  document.querySelectorAll('.reading').forEach(x => x.classList.remove('reading'));
  if (it.el) { it.el.classList.add('reading'); it.el.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
}
function clipUrl(seg, part, voice) { return `/api/speech/audio?id=${encodeURIComponent(RID)}&sid=${TTS.sid}&seg=${seg}&part=${part}&voice=${encodeURIComponent(voice)}`; }
async function fetchClip(seg, part, voice, retry = true) {
  const r = await fetch(clipUrl(seg, part, voice));
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    if (r.status === 404 && retry && /expired/.test(j.error || '')) {  // the server restarted and forgot the script
      await api('/api/speech', { id: RID, ...TTS.opts.source, plain: !$('#tscript').checked }); return fetchClip(seg, part, voice, false); }
    throw new Error(j.error || r.status);
  }
  return URL.createObjectURL(await r.blob());
}
function clip(it, p, voice) {  // one request per sentence and voice, shared by playing and prefetching
  const k = `${TTS.sid}|${voice}|${it.seg}|${p}`;
  if (!TTS.clips.has(k)) TTS.clips.set(k, fetchClip(it.seg, p, voice));
  return TTS.clips.get(k);
}
function prefetch(voice, n) {  // ask for the next sentences while this one plays, so there is no gap between them
  let i = TTS.i, p = TTS.p;
  for (let k = 0; k < n; k++) {
    p++; while (TTS.q[i] && p >= TTS.q[i].parts.length) { i++; p = 0; }
    const it = TTS.q[i]; if (!it || it.seg == null) return;
    clip(it, p, voice).catch(() => {});
  }
}
async function playServer(it, token, voice) {
  TTS.mode = 'server'; let url;
  try { url = await clip(it, TTS.p, voice); }
  catch (e) { if (token === TTS.token) { ttsLabel(false, `natural voice failed (${e.message}); using this device`); playDevice(it, token, ''); } return; }
  if (token !== TTS.token || !TTS.on) return;
  const a = TTS.audio;
  a.onended = partDone(token);
  a.onerror = () => { if (token === TTS.token) playDevice(it, token, ''); };
  a.src = url; a.playbackRate = ttsRate(); a.preservesPitch = true;
  prefetch(voice, 3);
  if (TTS.paused) return;
  a.play().catch(e => { if (e.name === 'NotAllowedError' && token === TTS.token) { TTS.paused = true; $('#tplay').textContent = '▶'; ttsNow('Press ▶ to start listening'); } });
}
function playDevice(it, token, name) {
  if (!synth) { partDone(token)(); return; }
  TTS.mode = 'device';
  const u = new SpeechSynthesisUtterance(it.parts[TTS.p]); u.rate = ttsRate();
  const vs = deviceVoices(), v = vs.find(x => x.name === name) || goodDevice(vs); if (v) { u.voice = v; u.lang = v.lang; }
  if (it.kind === 'heading') u.pitch = 0.9;
  u.onend = partDone(token);
  u.onerror = e => { if (e.error !== 'interrupted' && e.error !== 'canceled') partDone(token)(); };
  synth.speak(u);
}
function halt() { TTS.token++; if (synth) synth.cancel(); TTS.audio.onended = TTS.audio.onerror = null; TTS.audio.pause(); }
function ttsRestart() { if (!TTS.on) return; halt(); TTS.paused = TTS.held = false; $('#tplay').textContent = '⏸'; ttsPlay(TTS.token); }  // same sentence again
function ttsJump(d) { if (!TTS.on) return; TTS.i = Math.max(0, Math.min(TTS.q.length, TTS.i + d)); TTS.p = 0; ttsRestart(); }
function ttsStop(keepBar) {
  TTS.on = false; TTS.run++; halt(); clearTimeout(TTS.poll); TTS.paused = TTS.held = false;
  document.querySelectorAll('.reading').forEach(x => x.classList.remove('reading'));
  if (!keepBar) $('#player').style.display = 'none';
}
function ttsNow(t) { const n = $('#tnow'); n.textContent = t; n.title = t; }
function ttsLabel(pending, note) {
  const what = { ai: 'listening script (AI)', plain: pending ? 'plain reading (AI script on its way)' : 'plain reading', page: 'reading the page' }[TTS.source] || '';
  $('#tsrc').textContent = note || what;
}
$('#tplay').onclick = () => {
  if (!TTS.on) return;
  if (TTS.paused) {
    TTS.paused = false; $('#tplay').textContent = '⏸';
    if (TTS.held) { TTS.held = false; ttsPlay(TTS.token); } else if (TTS.mode === 'server') TTS.audio.play().catch(() => {}); else synth.resume();
  } else { TTS.paused = true; $('#tplay').textContent = '▶'; if (TTS.mode === 'server') TTS.audio.pause(); else if (synth) synth.pause(); }
};
$('#tstop').onclick = () => ttsStop(); $('#tprev').onclick = () => ttsJump(-1); $('#tnext').onclick = () => ttsJump(1);
$('#trate').value = String(store.get('ttsrate', 1));
$('#trate').onchange = e => { store.set('ttsrate', +e.target.value); if (TTS.mode === 'server') TTS.audio.playbackRate = ttsRate(); else ttsRestart(); };
$('#tvoice').onchange = e => { store.set('ttsvoice', e.target.value); ttsRestart(); };
$('#tauto').checked = store.get('ttsauto', true); $('#tauto').onchange = e => store.set('ttsauto', e.target.checked);
$('#tscript').checked = store.get('ttsscript', true);
$('#tscript').onchange = e => { store.set('ttsscript', e.target.checked); if (!TTS.on) return; const cur = TTS.q[TTS.i]; ttsStart(TTS.container, { ...TTS.opts, fromLn: cur ? cur.ln : null }); };
// double-click any paragraph while listening to jump there
document.addEventListener('dblclick', e => { if (!TTS.on) return; const k = TTS.q.findIndex(b => b.el && b.el.contains(e.target)); if (k >= 0) { TTS.i = k; TTS.p = 0; ttsRestart(); } });
