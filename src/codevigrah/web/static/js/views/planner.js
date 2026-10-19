// Change planner: which files an issue touches, what ripples, which tests, and an optional AI plan.
VIEWS.planner = m => {
  const ex = [];
  const tbl = A.entities.models.find(x => x.kind === 'table'); if (tbl) ex.push(`Add a new optional field "priority" to ${tbl.name} and expose it in the API`);
  const rt = A.entities.routes.find(r => r.method !== 'PAGE'); if (rt) ex.push(`Add pagination to ${rt.method} ${rt.path}`);
  const cmd = A.entities.commands.find(c => c.kind === 'command'); if (cmd) ex.push(`Add a --json output option to the ${cmd.name} command`);
  if (A.entities.components.length) ex.push(`Add a loading spinner and error message to ${A.entities.components[0].name}`);
  ex.push('Add rate limiting to authentication', 'Improve error messages when configuration is missing', 'Fix a crash when the input file is empty');
  const last = store.get('plan:' + RID, null);
  m.innerHTML = `<div class="card"><h3>Change planner</h3><p class="small muted">Describe an issue or feature. CodeVigrah finds the files that own the concept (path, symbol and content match), follows the import graph to what would break, adds files that historically change together, and maps it onto the domain's typical change chain.${LLM ? ' Tick "AI plan" for a full step-by-step plan.' : ' Set up an AI provider in Settings to get an AI-written plan as well.'}</p>
    <textarea id="issue" rows="3" style="width:100%" placeholder="e.g. Users should be able to archive projects instead of deleting them">${esc(last?.issue || '')}</textarea>
    <div style="display:flex;gap:10px;align-items:center;margin-top:8px;flex-wrap:wrap"><button id="loc">Locate changes</button><label class="small"><input type="checkbox" id="aiplan" ${LLM ? 'checked' : 'disabled'}> AI plan</label>
    <span class="small muted">Try:</span>${ex.slice(0, 5).map(x => `<a class="chip" data-ex="${esc(x)}">${esc(x)}</a>`).join('')}</div></div><div id="planout"></div>`;
  m.querySelectorAll('[data-ex]').forEach(a => a.onclick = () => { $('#issue').value = a.dataset.ex; });
  $('#loc').onclick = async () => {
    const issue = $('#issue').value.trim(); if (!issue) return;
    $('#planout').innerHTML = `<div class="card"><span class="spin"></span> Locating${$('#aiplan').checked ? ' and asking the AI for a plan (can take a minute)' : ''}…</div>`;
    try { const r = await api('/api/locate', { id: RID, issue, ai: $('#aiplan').checked }); store.set('plan:' + RID, { issue, r }); renderPlan(r, issue); }
    catch (e) { $('#planout').innerHTML = `<div class="card flag">${esc(e.message)}</div>`; }
  };
  if (last?.r) renderPlan(last.r, last.issue);
};
function renderPlan(r, issue) {
  $('#planout').innerHTML = `
  <div class="card"><h3>Change type: ${esc(r.recipe.title)}</h3><p class="small muted">${esc(r.recipe.notes)}</p>
    <div class="chain">${r.chain.map((c, k) => `${k ? '<span class="arrow">→</span>' : ''}<div class="step">${roleChip(c.role)}<div class="small" style="margin-top:4px">${c.files.length ? c.files.map(p => FILES[p] ? fl(p) : `<span class="muted">${esc(p)}</span>`).join('<br>') : '<span class="muted">none found</span>'}</div></div>`).join('')}</div></div>
  ${r.hints.length ? `<div class="card flag"><h3>Watch out</h3>${r.hints.map(h => `<div>${inline(h)}</div>`).join('')}</div>` : ''}
  ${r.ai_plan ? `<div class="card"><h3>AI change plan</h3>${md(r.ai_plan)}</div>` : ''}${r.ai_error ? `<div class="card flag">${esc(r.ai_error)}</div>` : ''}
  <div class="grid"><div class="card"><h3>Most likely files to edit</h3><table>${r.primary.map(p => `<tr><td>${fl(p.path)} ${roleChip(p.role)}<div class="small muted">${p.why.map(esc).join(' · ')}${p.symbols.length ? ' · symbols: ' + p.symbols.map(s => `<a data-path="${esc(p.path)}" data-line="${s.line}">${esc(s.name)}</a>`).join(', ') : ''}</div>
      <div class="small muted">${p.fanin} dependents · risk ${p.risk} · ${p.tests.length ? p.tests.length + ' test file(s)' : 'no tests'}</div></td><td><span class="conf"><i style="width:${p.confidence * 100}%"></i></span></td></tr>`).join('')}</table></div>
   <div class="card"><h3>Ripple: check these too</h3><p class="small muted">Files that import the top candidates (could break) or that historically change with them.</p>${r.ripple.map(x => `<div>${fl(x.path)}<div class="small muted">${x.reasons.slice(0, 2).map(ev).join('; ')}</div></div>`).join('') || '<span class="muted">Nothing obvious.</span>'}
   <h3 style="margin-top:12px">Tests to run / extend</h3>${r.tests.map(t => `<div>${fl(t)}</div>`).join('') || '<span style="color:var(--warn)">No related tests found: write one first.</span>'}</div></div>
  <div class="card"><a data-ask="${esc('I want to implement this change: ' + issue + '\nWalk me through it file by file, explain why each file is involved, and what makes it tricky in this codebase.')}">Discuss this change in chat →</a></div>`;
}
