// Read aloud with the Web Speech API: runs on the viewing device, not the server.
const TTS = { blocks: [], i: 0, chunks: [], c: 0, on: false, paused: false, onFinish: null, token: 0 };
const synth = window.speechSynthesis;
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
function ttsVoices() {
  const vs = synth ? synth.getVoices() : []; const sel = $('#tvoice'); if (!sel || !vs.length) return;
  const en = vs.filter(v => /^en/i.test(v.lang)), list = en.length ? en : vs;
  const saved = store.get('ttsvoice', ''); const pref = list.find(v => v.name === saved) || list.find(v => /natural|neural|google|samantha|premium|enhanced/i.test(v.name)) || list.find(v => v.default) || list[0];
  sel.innerHTML = list.map(v => `<option value="${esc(v.name)}" ${v === pref ? 'selected' : ''}>${esc(v.name.replace(/Microsoft |Google /, ''))} (${esc(v.lang)})</option>`).join('');
}
if (synth) { ttsVoices(); synth.onvoiceschanged = ttsVoices; }
function ttsStart(container, opts = {}) {
  if (!synth) { alert('This browser has no built-in speech. Try Chrome, Edge or Safari.'); return; }
  ttsStop(true);
  const els = [...container.querySelectorAll('h1, h2, h3, p, li, pre, .diagram, blockquote')]
    .filter(e => !e.closest('details') && !e.closest('.diagram pre') && !(e.tagName === 'PRE' && e.closest('.diagram')) && !(e.tagName === 'P' && e.closest('li, blockquote')) && speakText(e));
  if (!els.length) return;
  Object.assign(TTS, { blocks: els, i: opts.from || 0, on: true, paused: false, onFinish: opts.onFinish || null, token: TTS.token + 1 });
  $('#player').style.display = 'flex'; $('#tautowrap').style.display = opts.tour ? '' : 'none';
  $('#tplay').textContent = '⏸'; ttsBlock();
}
function ttsBlock() {
  document.querySelectorAll('.reading').forEach(x => x.classList.remove('reading'));
  if (TTS.i >= TTS.blocks.length) { const f = TTS.onFinish; ttsStop(); if (f) f(); return; }
  const el = TTS.blocks[TTS.i]; el.classList.add('reading'); el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  $('#tnow').textContent = (el.innerText || '').slice(0, 80);
  TTS.chunks = chunkText(speakText(el)); TTS.c = 0; ttsChunk(TTS.token);
}
function ttsChunk(token) {
  if (token !== TTS.token || !TTS.on) return;
  if (TTS.c >= TTS.chunks.length) { TTS.i++; setTimeout(() => token === TTS.token && ttsBlock(), 250); return; }
  const u = new SpeechSynthesisUtterance(TTS.chunks[TTS.c]);
  u.rate = +$('#trate').value || 1; const v = synth.getVoices().find(x => x.name === $('#tvoice').value); if (v) { u.voice = v; u.lang = v.lang; }
  if (/^H[123]$/.test(TTS.blocks[TTS.i].tagName)) u.pitch = 0.9;
  u.onend = () => { TTS.c++; ttsChunk(token); };
  u.onerror = e => { if (e.error !== 'interrupted' && e.error !== 'canceled') { TTS.c++; ttsChunk(token); } };
  synth.speak(u);
}
function ttsJump(d) { if (!TTS.on) return; TTS.token++; synth.cancel(); TTS.i = Math.max(0, Math.min(TTS.blocks.length, TTS.i + d)); TTS.paused = false; $('#tplay').textContent = '⏸'; ttsBlock(); }
function ttsStop(keepBar) { TTS.on = false; TTS.token++; if (synth) synth.cancel(); document.querySelectorAll('.reading').forEach(x => x.classList.remove('reading')); if (!keepBar) $('#player').style.display = 'none'; }
$('#tplay').onclick = () => { if (!TTS.on) return; if (TTS.paused) { synth.resume(); TTS.paused = false; $('#tplay').textContent = '⏸'; } else { synth.pause(); TTS.paused = true; $('#tplay').textContent = '▶'; } };
$('#tstop').onclick = () => ttsStop(); $('#tprev').onclick = () => ttsJump(-1); $('#tnext').onclick = () => ttsJump(1);
$('#trate').value = String(store.get('ttsrate', 1)); $('#trate').onchange = e => { store.set('ttsrate', +e.target.value); ttsJump(0); };
$('#tvoice').onchange = e => { store.set('ttsvoice', e.target.value); ttsJump(0); };
$('#tauto').checked = store.get('ttsauto', true); $('#tauto').onchange = e => store.set('ttsauto', e.target.checked);
// double-click any paragraph while listening to jump there
document.addEventListener('dblclick', e => { if (!TTS.on) return; const k = TTS.blocks.findIndex(b => b.contains(e.target)); if (k >= 0) { TTS.i = k - 0; ttsJump(0); } });
