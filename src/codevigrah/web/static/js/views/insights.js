// Go deeper: domain lens, design decisions, hotspots and concept cards.
VIEWS.domain = m => {
  const doms = A.domains.slice(0, 3).filter(d => A.domain_info[d.key]);
  const cur = store.get('dom:' + RID, doms[0]?.key);
  const d = doms.find(x => x.key === cur) || doms[0]; if (!d) { m.innerHTML = '<div class="empty">No domain profile.</div>'; return; }
  const info = A.domain_info[d.key], ent = A.entities;
  const probes = A.probes.filter(p => p.domains.includes('all') || p.domains.includes(d.key)).sort((a, b) => b.flagged - a.flagged);
  const recipes = A.recipes.filter(r => r.domains.includes(d.key));
  const qs = store.get('qs:' + RID + d.key, {});
  let entHtml = '';
  if (d.key === 'backend' && ent.routes.length) entHtml += `<div class="card"><h3>API surface: ${ent.routes.length} routes</h3><table><tr><th>Method</th><th>Path</th><th>Handler file</th></tr>${ent.routes.slice(0, 120).map(r => `<tr><td><span class="chip">${esc(r.method)}</span></td><td class="mono">${esc(r.path)}</td><td>${fl(r.file, r.line)}</td></tr>`).join('')}</table></div>`;
  if (['backend', 'database', 'ml'].includes(d.key) && ent.models.length) entHtml += `<div class="card"><h3>Data model: ${ent.models.filter(x => x.kind === 'table').length} tables, ${ent.models.filter(x => x.kind === 'schema').length} schemas</h3>${ent.models.slice(0, 150).map(x => `<span class="chip" style="${x.kind === 'table' ? 'border-color:var(--warn)' : ''}"><a data-path="${esc(x.file)}" data-line="${x.line}">${esc(x.name)}</a></span>`).join('')}<p class="small muted">Amber outline = persisted table; others are request/response or validation schemas. Every table change implies a migration plus every schema that mirrors it.</p></div>`;
  if (d.key === 'cli' && ent.commands.length) entHtml += `<div class="card"><h3>CLI surface</h3>${ent.commands.slice(0, 150).map(c => `<span class="chip" style="${c.kind === 'command' ? 'border-color:var(--accent)' : ''}"><a data-path="${esc(c.file)}" data-line="${c.line}">${esc(c.name)}</a></span>`).join('')}<p class="small muted">Blue outline = command; others are options/flags. Each is a public contract with scripts in the wild.</p></div>`;
  if (d.key === 'frontend' && ent.components.length) entHtml += `<div class="card"><h3>Components (largest first)</h3><table><tr><th>Component</th><th>LOC</th><th>Local state</th><th>Hooks defined</th></tr>${ent.components.slice(0, 60).map(c => `<tr><td>${fl(c.file)}</td><td>${c.loc}</td><td>${c.uses_state ? '●' : ''}</td><td class="small">${c.hooks.map(esc).join(', ')}</td></tr>`).join('')}</table>
    ${ent.routes.filter(r => r.method === 'PAGE').length ? `<h3 style="margin-top:12px">File-based pages</h3>${ent.routes.filter(r => r.method === 'PAGE').map(r => `<span class="chip"><a data-path="${esc(r.file)}">${esc(r.path)}</a></span>`).join('')}` : ''}</div>`;
  m.innerHTML = `<div class="tabs">${doms.map(x => `<button data-dom="${x.key}" class="${x.key === d.key ? 'on' : ''}">${esc(x.label)}</button>`).join('')}</div>
   <div class="card"><h3>Mental model: ${esc(info.label)}</h3><p>${esc(info.model)}</p><p class="small muted">Evidence for this domain: ${d.evidence.map(esc).join(' · ')}</p></div>
   ${entHtml}
   <div class="card"><h3>Typical changes and the files they touch here</h3>${recipes.map(r => `<div style="margin-bottom:12px"><b>${esc(r.title)}</b><div class="small muted">${esc(r.notes)}</div><div class="chain" style="margin-top:6px">${r.chain.map((role, k) => { const ex = codeFilesByRole(role).slice(0, 3);
      return `${k ? '<span class="arrow">→</span>' : ''}<div class="step">${roleChip(role)}<div class="small" style="margin-top:4px">${ex.length ? ex.map(f => fl(f.path)).join('<br>') : '<span class="muted">none detected</span>'}</div></div>`; }).join('')}</div></div>`).join('') || '<span class="muted">No recipes for this domain.</span>'}</div>
   <div class="card"><h3>What is hard in this domain, and why</h3>${info.hard.map(([t, x]) => `<p><b>${esc(t)}.</b> ${esc(x)}</p>`).join('')}</div>
   <div class="card"><h3>Shortcomings detected in this repo</h3><p class="small muted">Heuristic checks. A flag is a lead to verify, not a verdict.</p>${probes.map(p => `<div class="card ${p.flagged ? 'flag' : 'ok'}" style="margin-bottom:8px"><b>${p.flagged ? '⚠' : '✓'} ${esc(p.title)}</b><div class="small">${esc(p.why)}</div>
      ${p.flagged ? `<div class="small" style="margin-top:4px"><b>Why it's hard to patch:</b> ${esc(p.hard)}</div><div class="small muted mono" style="margin-top:4px">${p.evidence.map(ev).join('<br>')}</div>` : ''}</div>`).join('')}</div>
   <div class="card"><h3>Questions an owner can answer</h3>${info.questions.map((q, k) => `<label style="display:block"><input type="checkbox" data-q="${k}" ${qs[k] ? 'checked' : ''}> ${esc(q)} <a class="small" data-ask="${esc(q)}">ask AI</a></label>`).join('')}</div>`;
  m.querySelectorAll('[data-dom]').forEach(b => b.onclick = () => { store.set('dom:' + RID, b.dataset.dom); show('domain'); });
  m.querySelectorAll('[data-q]').forEach(b => b.onchange = () => { qs[b.dataset.q] = b.checked; store.set('qs:' + RID + d.key, qs); });
};
const codeFilesByRole = role => A.files.filter(f => f.role === role && (f.code || role === 'migration')).sort((a, b) => (b.fanin + b.pr) - (a.fanin + a.pr));

VIEWS.decisions = m => {
  m.innerHTML = `<div class="card"><h3>Design decisions found in this repo</h3><p class="small muted">Each detected choice is explained as <b>why it was made</b> and <b>what it costs you</b> when you change things. These are the constraints any patch must respect.</p></div>
   ${A.decisions.map(d => `<div class="card"><h3>${esc(d.title)}</h3><p><b>Why:</b> ${esc(d.why)}</p><p><b>Cost you inherit:</b> ${esc(d.cost)}</p><div class="small muted">Evidence: ${d.evidence.map(ev).join(' · ')}</div>
   <div style="margin-top:6px"><a class="small" data-ask="${esc(`In this repo, show me concretely where the decision "${d.title}" shows up, why it fits this project, and which kinds of changes it makes harder.`)}">Explore in chat →</a></div></div>`).join('') || '<div class="empty">No known patterns recognised.</div>'}`;
};

VIEWS.hotspots = m => {
  let key = 'risk', dir = -1;
  const cols = [['path', 'File'], ['risk', 'Risk'], ['fanin', 'Fan-in'], ['churn', 'Commits'], ['authors', 'Authors'], ['cx', 'Branches'], ['loc', 'LOC'], ['tests', 'Tests']];
  const render = () => {
    const fs = codeFiles().slice().sort((a, b) => { const x = key === 'tests' ? a.tests.length : a[key] ?? 0, y = key === 'tests' ? b.tests.length : b[key] ?? 0; return (x > y ? 1 : x < y ? -1 : 0) * dir; }).slice(0, 150);
    const single = A.git ? codeFiles().filter(f => f.authors === 1 && f.churn >= 3).length : 0;
    m.innerHTML = `<div class="card"><h3>Hotspots: where change is riskiest</h3><p class="small muted">Risk combines dependents (blast radius), git churn (instability), branching (complexity), size, cycle membership and missing tests, ranked by percentile within this repo. High-risk + high-churn files are where bugs concentrate and where an owner must be most careful.${A.git ? ` ${single} frequently changed files have a single author (knowledge silos).` : ''}</p>
     <table><tr>${cols.map(([k, l]) => `<th data-k="${k}">${l}${k === key ? (dir < 0 ? ' ↓' : ' ↑') : ''}</th>`).join('')}<th>Why</th></tr>
     ${fs.map(f => `<tr><td>${fl(f.path)} ${roleChip(f.role)}${f.cycle ? ' <span class="chip" style="border-color:var(--bad)">cycle</span>' : ''}</td><td><b>${f.risk}</b></td><td>${f.fanin}</td><td>${f.churn ?? '–'}</td><td>${f.authors ?? '–'}</td><td>${f.cx}</td><td>${f.loc}</td><td>${f.tests.length || '<span style="color:var(--warn)">0</span>'}</td><td class="small muted" style="min-width:240px">${f.risk_why.map(esc).join(', ')}</td></tr>`).join('')}</table></div>`;
    m.querySelectorAll('th[data-k]').forEach(th => th.onclick = () => { if (key === th.dataset.k) dir = -dir; else { key = th.dataset.k; dir = key === 'path' ? 1 : -1; } render(); });
  };
  render();
};

VIEWS.learn = m => {
  m.innerHTML = `<div class="card"><h3>Concepts this repo can teach you</h3><p class="small muted">Picked from what the code actually uses. Each card links to real places in this repo; reading them with the concept in mind is the fastest way to build intuition.</p></div>
  <div class="grid">${A.concepts.map(c => `<div class="card"><h3>${esc(c.title)} <span class="chip">${esc(c.level)}</span></h3><p><b>What:</b> ${esc(c.what)}</p><p><b>Why it matters:</b> ${esc(c.why)}</p><p><b>Pitfall:</b> ${esc(c.pitfalls)}</p>
    ${c.examples.length ? `<div class="small"><b>See it here:</b><br>${c.examples.slice(0, 4).map(h => `${fl(h.path, h.line)} <span class="muted mono">${esc(h.snippet.slice(0, 70))}</span>`).join('<br>')}</div>` : ''}
    <div style="margin-top:8px"><a class="small" data-ask="${esc(`Teach me "${c.title}" using this repository: walk through the concrete code that uses it, explain why it's used here, and give me an exercise (a small change) to practise it.`)}">Teach me with this repo →</a></div></div>`).join('')}</div>`;
};
