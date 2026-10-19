// Navigation, settings, starting an analysis and opening a repository; small view helpers.
const NAV = [['sep','Start here'],['tour','Guided tour'],['quiz','Skill check'],['sep','See it'],['overview','At a glance'],['arch','Architecture'],['map','Code map'],['graph','Dependency graph'],
  ['sep','Go deeper'],['domain','Domain lens'],['decisions','Design decisions'],['hotspots','Hotspots & risk'],['learn','Learn concepts'],
  ['sep','Act'],['planner','Change planner'],['chat','Ask the repo'],['report','Report']];
function renderNav() {
  $('#nav').innerHTML = NAV.map(([k, l]) => k === 'sep' ? `<div class="sep">${l}</div>` : `<button data-view="${k}" class="${VIEW === k ? 'on' : ''}">${l}</button>`).join('');
}
$('#nav').addEventListener('click', e => { const b = e.target.closest('[data-view]'); if (b) show(b.dataset.view); });

let SETTINGS = null;
const MODEL_HINT = { 'claude-cli': 'blank = Claude Code default, or e.g. opus / sonnet', anthropic: 'blank = claude-opus-5-5',
  ollama: 'e.g. qwen2.5-coder:14b (run `ollama list`)', groq: 'a model id from console.groq.com', openai: 'model id' };
async function refreshSettings() {
  const s = SETTINGS = await api('/api/settings'); LLM = s.ai;
  $('#llmstat').textContent = s.ai ? `AI: ${s.label}` : 'AI: off (static mode)';
  $('#llmstat').style.borderColor = s.ai ? 'var(--good)' : 'var(--line)';
  $('#src').placeholder = 'https://github.com/owner/repo · owner/repo' + (s.local_paths ? ' · /absolute/local/path' : '');
  $('#setver').textContent = 'CodeVigrah ' + s.version;
  $('#provlist').innerHTML = s.providers.map(p => `<div>${p.available ? '<b style="color:var(--good)">✓</b>' : '<span class="muted">·</span>'} <b>${esc(p.label)}</b> <span class="muted">${p.available ? esc(p.model || 'ready') : esc(p.problem)}</span></div>`).join('');
  $('#setnote').textContent = s.locked ? 'AI on this site is configured by the people who run it.'
    : 'Used for the guided tour, skill check, chat, file explanations, change plans and the report narrative. API keys stay in the server and are never sent back to the browser.';
  $('#setform').style.display = s.locked ? 'none' : ''; $('#setsave').style.display = s.locked ? 'none' : '';
  const order = ['auto', 'off'].includes(s.order) ? [s.order] : s.order.split(',').filter(Boolean);
  $('#provider').innerHTML = '<option value="auto">Automatic: first available, the rest as fallback</option><option value="off">Off (static mode, no AI)</option>' + s.providers.map(p => `<option value="${esc(p.name)}">${esc(p.label)}</option>`).join('');
  $('#provider').value = order[0] || 'auto'; $('#fallback').checked = order.length > 1;
  fillProvider(); ttsVoices();
}
function fillProvider() {
  const p = SETTINGS && SETTINGS.providers.find(x => x.name === $('#provider').value);
  $('#provfields').style.display = p ? '' : 'none'; $('#fbwrap').style.display = p ? '' : 'none'; if (!p) return;
  $('#provfields').querySelectorAll('[data-f]').forEach(el => { el.style.display = p.fields.includes(el.dataset.f) ? '' : 'none'; });
  $('#pbase').value = p.base_url || ''; $('#model').value = p.model || ''; $('#key').value = '';
  $('#model').placeholder = MODEL_HINT[p.name] || ''; $('#keystate').textContent = p.has_key ? '(a key is set; leave empty to keep it)' : '';
}
$('#provider').onchange = fillProvider;
async function loadRecent() {
  const r = await api('/api/repos');
  $('#recent').innerHTML = '<option value="">Recent…</option>' + r.map(x => `<option value="${esc(x.id)}">${esc(x.id.replace('__', '/'))}</option>`).join('');
}
// Only one analysis is shown at a time. JOB.run identifies it: a polling loop whose run is no longer current stops
// touching the page (pressing Enter twice, or starting another repo, used to leave two loops fighting over the log).
const JOB = { run: 0, source: '' };
function stopWatchingJob() { JOB.run++; JOB.source = ''; $('#go').disabled = $('#refresh').disabled = false; }
async function analyze(refresh) {
  const source = $('#src').value.trim(); if (!source || source === JOB.source) return;
  const run = ++JOB.run; JOB.source = source;
  $('#go').disabled = $('#refresh').disabled = true;
  $('#main').innerHTML = `<div class="card"><h3><span class="spin"></span> Analysing ${esc(source)}</h3><div class="log mono" id="joblog">starting…</div></div>`;
  try {
    const { job } = await api('/api/analyze', { source, refresh });
    let shown = 0, since = Date.now();
    while (run === JOB.run) {
      const j = await api('/api/job?id=' + job);
      const log = $('#joblog'); if (run !== JOB.run || !log) break;
      if (j.log.length > shown) {  // the log only grows: redraw it only when there is a new line
        shown = j.log.length; since = Date.now();
        log.innerHTML = j.log.map(esc).join('<br>') + ' <span class="muted" id="jobtick"></span>'; log.scrollTop = log.scrollHeight;
      }
      const secs = Math.round((Date.now() - since) / 1000), tick = $('#jobtick');
      if (tick) tick.textContent = secs >= 3 ? `· ${secs} s` : '';  // slow steps (cloning a big repo) visibly keep going
      if (j.status === 'done') { await open(j.repo); loadRecent(); break; }
      if (j.status === 'error') throw new Error(j.error);
      await new Promise(r => setTimeout(r, 900));
    }
  } catch (e) { if (run === JOB.run) $('#main').innerHTML = `<div class="card flag"><h3>Analysis failed</h3><p>${esc(e.message)}</p></div>`; }
  if (run === JOB.run) { JOB.source = ''; $('#go').disabled = $('#refresh').disabled = false; }
}
async function open(id) {
  A = await api('/api/analysis?id=' + encodeURIComponent(id)); RID = id; FILES = {};
  A.files.forEach((f, i) => { f.i = i; FILES[f.path] = f; }); BASE = {};
  A.files.forEach(f => { const b = f.path.split('/').pop(); BASE[b] = b in BASE ? null : f.path; });
  Object.keys(BASE).forEach(k => { if (!BASE[k] || !/\.[a-z]{1,5}$/i.test(k)) delete BASE[k]; });
  A.inc = A.files.map(() => []); A.out = A.files.map(() => []);
  A.edges.forEach(([a, b]) => { A.out[a].push(b); A.inc[b].push(a); });
  chatMsgs = store.get('chat:' + id, []); pins = [];
  $('#src').value = A.meta.source;
  renderNav(); show(VIEW);
}
function show(v) { if (VIEW !== v && TTS.on) ttsStop(); VIEW = v; renderNav(); if (!A) return; history.replaceState(null, '', '#' + encodeURIComponent(RID) + '/' + v); const m = $('#main'); m.scrollTop = 0; m.innerHTML = ''; (VIEWS[v] || VIEWS.overview)(m); }

const roleChip = r => `<span class="chip role" style="background:${ROLE_COLORS[r] || '#555'}">${esc(r)}</span>`;
const fl = (p, line) => `<a data-path="${esc(p)}" data-line="${line || ''}" class="mono">${esc(p)}${line ? ':' + line : ''}</a>`;
const ev = s => linkPaths(esc(s));
const fmtDate = ts => ts ? new Date(ts * 1000).toISOString().slice(0, 10) : '–';
const tip = $('#tip');
function showTip(e, html) { tip.innerHTML = html; tip.style.display = 'block'; tip.style.left = Math.min(e.clientX + 12, innerWidth - 370) + 'px'; tip.style.top = (e.clientY + 12) + 'px'; }
function hideTip() { tip.style.display = 'none'; }
const langColor = d3.scaleOrdinal(d3.schemeTableau10);
const codeFiles = () => A.files.filter(f => f.code && f.role !== 'test');

const VIEWS = {};  // view name -> function(main element) that renders it
