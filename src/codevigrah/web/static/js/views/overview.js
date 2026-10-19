// At a glance: brief, languages, domain, entry points, history, README.
VIEWS.overview = m => {
  const s = A.stats, g = A.git;
  const langs = Object.entries(s.langs); const tot = s.loc || 1;
  const key = [...codeFiles()].sort((a, b) => (b.pr + b.fanin) - (a.pr + a.fanin)).slice(0, 10);
  m.innerHTML = `
  <div class="card"><h3>${esc(A.meta.name)} <span class="muted small mono">@ ${esc(A.meta.commit)}</span></h3>${md(A.brief)}
    ${A.truncated ? '<p class="small" style="color:var(--warn)">Repository is large; analysis was truncated to the first files scanned.</p>' : ''}</div>
  <div class="stats card">${[['Code files', s.code_files], ['Lines of code', s.loc.toLocaleString()], ['Modules', s.modules], ['Import edges', s.edges], ['Import cycles', s.cycles], ['Test/source LOC', s.test_ratio], g ? ['Commits sampled', g.commits] : null, g ? ['Authors', g.authors_total] : null].filter(Boolean).map(([k, v]) => `<div class="stat"><b>${v}</b><span>${k}</span></div>`).join('')}</div>
  <div class="grid">
    <div class="card"><h3>Languages</h3><div class="bar">${langs.map(([l, v]) => `<i style="width:${100 * v / tot}%;background:${langColor(l)}" title="${esc(l)} ${v}"></i>`).join('')}</div>
      <div class="legend">${langs.slice(0, 8).map(([l, v]) => `<span><i style="background:${langColor(l)}"></i>${esc(l)} ${Math.round(100 * v / tot)}%</span>`).join('')}</div>
      <h3 style="margin-top:14px">Frameworks & libraries</h3>${A.frameworks.map(f => `<span class="chip">${esc(f)}</span>`).join('') || '<span class="muted">none recognised</span>'}</div>
    <div class="card"><h3>Domain</h3>${A.domains.slice(0, 4).map((d, k) => `<div style="margin-bottom:8px"><b>${esc(d.label)}</b> <span class="chip">score ${d.score}</span>${k === 0 ? ' <span class="chip" style="border-color:var(--accent)">primary</span>' : ''}<div class="small muted">${d.evidence.map(esc).join(' · ')}</div></div>`).join('')}</div>
    <div class="card"><h3>Where execution starts</h3>${A.entries.map(e => `<div>${fl(e.path)} <span class="small muted">${esc(e.why)}</span></div>`).join('') || '<span class="muted">No obvious entry point (likely a library).</span>'}
      ${A.meta.scripts ? `<h3 style="margin-top:12px">package.json scripts</h3>${Object.entries(A.meta.scripts).map(([k, v]) => `<div class="small"><code>${esc(k)}</code> <span class="muted mono">${esc(v)}</span></div>`).join('')}` : ''}</div>
    <div class="card"><h3>Read these first <span class="small muted">(most depended-upon)</span></h3>${key.map(f => `<div>${fl(f.path)} <span class="small muted">${f.fanin} dependents · ${f.loc} LOC</span></div>`).join('')}</div>
  </div>
  ${g ? `<div class="card"><h3>Recent history</h3><table>${g.recent.slice(0, 12).map(c => `<tr><td class="mono small">${esc(c.h)}</td><td class="small muted">${fmtDate(c.ts)}</td><td>${esc(c.s)}</td><td class="small muted">${c.n} files</td></tr>`).join('')}</table></div>` : ''}
  ${A.readme ? `<details class="card"><summary><b>README</b></summary>${md(A.readme)}</details>` : ''}`;
};
