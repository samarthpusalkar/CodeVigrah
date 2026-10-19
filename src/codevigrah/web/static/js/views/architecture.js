// Architecture: modules arranged by dependency level, the DSM matrix, cycles and hidden coupling.
function archUnits() {
  const realMods = A.modules.filter(x => x.loc > 0 && !/^(tests?|ci|docs?|examples?|scripts|benches|benchmarks)(\/|$)/.test(x.id));
  if (realMods.length >= 5) return { kind: 'module', units: realMods.map(x => ({ ...x, label: x.id.split('/').slice(-2).join('/'), desc: x.top.slice(0, 3).join(', ') })), edges: A.module_edges };
  // small repo: use source files as the units
  const fs = A.files.filter(f => f.code && !['test', 'example', 'generated', 'ci', 'docs'].includes(f.role));
  const ids = new Set(fs.map(f => f.i)), lvl = {};
  const level = (i, stack = new Set()) => { if (i in lvl) return lvl[i]; if (stack.has(i)) return 0; stack.add(i);
    const deps = A.out[i].filter(j => ids.has(j)); const v = deps.length ? 1 + Math.max(...deps.map(j => level(j, stack))) : 0; stack.delete(i); return lvl[i] = v; };
  fs.forEach(f => level(f.i));
  const edges = A.edges.filter(([a, b]) => ids.has(a) && ids.has(b)).map(([a, b]) => ({ s: A.files[a].path, t: A.files[b].path, w: 1 }));
  return { kind: 'file', edges, units: fs.map(f => ({ id: f.path, label: f.path.split('/').pop(), loc: f.loc, level: lvl[f.i], cyclic: f.cycle, lang: f.lang,
    fanin: A.inc[f.i].filter(j => ids.has(j)).length, fanout: A.out[f.i].filter(j => ids.has(j)).length, code_files: 1, roles: { [f.role]: 1 }, top: [f.path], desc: f.doc || f.role })) };
}
function archStory(U) {
  const u = U.units; if (!u.length) return '';
  const maxL = Math.max(...u.map(x => x.level)), top = u.filter(x => x.level === maxL), base = u.filter(x => x.level === 0 && x.fanin > 0).sort((a, b) => b.fanin - a.fanin);
  const name = x => `<b>${esc(x.label)}</b>`, w = U.kind === 'file' ? 'file' : 'module';
  let t = `<b>How to read this:</b> each box is a ${w}; an arrow from A to B means “A uses B”. Things at the <b>top</b> use the things below them; the <b>bottom row</b> is the foundation.`;
  t += `<br><b>In this repo:</b> ${top.slice(0, 3).map(name).join(', ')} ${top.length > 1 ? 'sit' : 'sits'} at the top: ${top.length > 1 ? 'they tie' : 'it ties'} the other pieces together, so ${top.length > 1 ? 'they are' : 'it is'} the safest to change and a good place to start reading.`;
  if (base.length) t += ` ${base.slice(0, 3).map(name).join(', ')} ${base.length > 1 ? 'are' : 'is'} the foundation (used by ${base[0].fanin}${base.length > 1 ? '+' : ''} other ${w}s): ${base.length > 1 ? 'they define' : 'it defines'} what the rest builds on, so a change there ripples upward. Read ${base.length > 1 ? 'them' : 'it'} to learn the core vocabulary.`;
  const cyc = u.filter(x => x.cyclic); if (cyc.length) t += ` Red borders mark ${cyc.length} ${w}s that depend on each other in a loop: you can't change one without considering the others.`;
  return `<div class="howto">${t}</div>`;
}
VIEWS.arch = m => {
  const U = archUnits();
  m.innerHTML = `<div class="card"><h3>Layered ${U.kind === 'file' ? 'file' : 'module'} view</h3>${archStory(U)}<p class="small muted">Hover a box to see only its connections and its description; click it for details.</p><div id="layers"></div></div>
  <div class="card" style="${U.kind === 'file' ? 'display:none' : ''}"><h3>Dependency structure matrix (DSM)</h3><p class="small muted">Row imports column (count of file-level imports). Modules ordered by level, foundation last. Cells <b>above</b> the diagonal are upward dependencies: layering violations or cycles, the places where architecture is under strain.</p><div id="dsm" style="overflow:auto"></div></div>
  <div class="grid"><div class="card"><h3>Import cycles</h3>${A.cycles.length ? A.cycles.slice(0, 8).map(c => `<div class="small" style="margin-bottom:6px">${c.slice(0, 8).map(p => fl(p)).join(' ↔ ')}${c.length > 8 ? ' …' : ''}</div>`).join('') : '<span class="muted">None. Every part can be understood bottom-up, starting from the foundation.</span>'}</div>
  <div class="card"><h3>Hidden coupling (change together in git)</h3><p class="small muted">Files that repeatedly change in the same commits, often without importing each other: implicit contracts.</p>${A.git && A.git.coupling.length ? A.git.coupling.slice(0, 14).map(c => `<div class="small">${fl(c.a)} ⇄ ${fl(c.b)} <span class="muted">${c.n}× (${Math.round(c.score * 100)}%)</span></div>`).join('') : '<span class="muted">No git history or no strong coupling.</span>'}</div></div>
  <div class="card" id="modfiles"></div>`;
  drawLayers($('#layers'), U); drawDSM($('#dsm'));
};
function drawLayers(el, U) {
  const mods = U.units; if (!mods.length) { el.innerHTML = '<p class="muted">No code modules.</p>'; return; }
  const W = el.clientWidth || 900, maxL = d3.max(mods, x => x.level), rowH = 92, H = (maxL + 1) * rowH + 20;
  const byL = d3.group(mods, x => x.level); const pos = {};
  const wScale = d3.scaleSqrt().domain([0, d3.max(mods, x => x.loc)]).range([50, 170]);
  for (const [lv, list] of byL) {
    list.sort((a, b) => b.loc - a.loc); const widths = list.map(x => wScale(x.loc)); const total = d3.sum(widths) + 10 * (list.length - 1);
    const scale = total > W - 20 ? (W - 20) / total : 1; let x = (W - total * scale) / 2;
    list.forEach((mm, k) => { const w = widths[k] * scale; pos[mm.id] = { x, y: (maxL - lv) * rowH + 14, w, h: 46, m: mm }; x += w + 10 * scale; });
  }
  const svg = d3.select(el).append('svg').attr('width', W).attr('height', H);
  svg.append('defs').append('marker').attr('id', 'ah').attr('viewBox', '0 0 10 10').attr('refX', 9).attr('refY', 5).attr('markerWidth', 6).attr('markerHeight', 6).attr('orient', 'auto').append('path').attr('d', 'M0,0L10,5L0,10z').attr('fill', 'var(--muted)');
  const maxW = d3.max(A.module_edges, e => e.w) || 1;
  const edges = U.edges.filter(e => pos[e.s] && pos[e.t]);
  const maxW2 = d3.max(edges, e => e.w) || 1;
  const lines = svg.append('g').selectAll('path').data(edges).join('path').attr('fill', 'none')
    .attr('stroke', e => pos[e.s].m.level <= pos[e.t].m.level ? 'var(--bad)' : 'var(--muted)').attr('stroke-opacity', .35)
    .attr('stroke-width', e => 0.8 + 3 * e.w / maxW2).attr('marker-end', 'url(#ah)')
    .attr('d', e => { const a = pos[e.s], b = pos[e.t]; const x1 = a.x + a.w / 2, y1 = a.y + a.h, x2 = b.x + b.w / 2, y2 = b.y;
      if (y2 <= y1) return `M${x1},${a.y + a.h / 2}C${x1 + 60},${a.y - 30} ${x2 + 60},${b.y - 30} ${x2},${b.y}`;
      return `M${x1},${y1}C${x1},${(y1 + y2) / 2} ${x2},${(y1 + y2) / 2} ${x2},${y2}`; });
  const g = svg.append('g').selectAll('g').data(Object.values(pos)).join('g').attr('transform', p => `translate(${p.x},${p.y})`).style('cursor', 'pointer');
  g.append('rect').attr('width', p => p.w).attr('height', p => p.h).attr('rx', 7).attr('fill', 'var(--panel2)')
    .attr('stroke', p => p.m.cyclic ? 'var(--bad)' : langColor(p.m.lang)).attr('stroke-width', 1.5);
  g.append('text').attr('x', 6).attr('y', 18).style('font-size', '12px').style('font-weight', 600).text(p => trunc(p.m.label, p.w / 7));
  g.append('text').attr('x', 6).attr('y', 35).style('font-size', '10.5px').style('fill', 'var(--muted)').text(p => trunc(`${p.m.loc} LOC · in ${p.m.fanin} · out ${p.m.fanout}`, p.w / 6));
  svg.selectAll('text.lv').data(d3.range(maxL + 1)).join('text').attr('x', 2).attr('y', l => (maxL - l) * rowH + 10).style('font-size', '10px').style('fill', 'var(--muted)').text(l => 'L' + l);
  g.on('mouseenter', (e, p) => { lines.attr('stroke-opacity', x => x.s === p.m.id || x.t === p.m.id ? .9 : .05);
      showTip(e, `<b>${esc(p.m.id)}</b><br>${esc(p.m.desc)}<br><span class="muted">${p.m.loc} LOC · used by ${p.m.fanin} · uses ${p.m.fanout}</span>`); })
   .on('mouseleave', () => { lines.attr('stroke-opacity', .35); hideTip(); })
   .on('click', (e, p) => U.kind === 'file' ? openFile(p.m.id) : moduleFiles(p.m));
}
const trunc = (s, n) => s.length > n ? s.slice(0, Math.max(3, n - 1)) + '…' : s;
function moduleFiles(mm) {
  const fs = A.files.filter(f => f.module === mm.id).sort((a, b) => b.fanin - a.fanin || b.loc - a.loc);
  const out = A.module_edges.filter(e => e.s === mm.id), inc = A.module_edges.filter(e => e.t === mm.id);
  $('#modfiles').innerHTML = `<h3>Module ${esc(mm.id)}</h3><p class="small muted">Depends on: ${out.map(e => esc(e.t) + ' (' + e.w + ')').join(', ') || 'nothing internal'}<br>Used by: ${inc.map(e => esc(e.s) + ' (' + e.w + ')').join(', ') || 'nothing'}</p>
   <table><tr><th>File</th><th>Role</th><th>LOC</th><th>Fan-in</th><th>Fan-out</th><th>Risk</th></tr>${fs.slice(0, 80).map(f => `<tr><td>${fl(f.path)}</td><td>${roleChip(f.role)}</td><td>${f.loc}</td><td>${f.fanin}</td><td>${f.fanout}</td><td>${f.risk}</td></tr>`).join('')}</table>`;
  $('#modfiles').scrollIntoView({ behavior: 'smooth' });
}
function drawDSM(el) {
  const mods = A.modules.filter(x => x.code_files).sort((a, b) => b.level - a.level || b.loc - a.loc).slice(0, 40);
  const idx = Object.fromEntries(mods.map((x, i) => [x.id, i])); const M = mods.map(() => mods.map(() => 0));
  A.module_edges.forEach(e => { if (e.s in idx && e.t in idx) M[idx[e.s]][idx[e.t]] = e.w; });
  const max = d3.max(M.flat()) || 1;
  el.innerHTML = `<table class="dsm"><tr><th></th>${mods.map((x, i) => `<th title="${esc(x.id)}">${i + 1}</th>`).join('')}</tr>${mods.map((x, i) => `<tr><th style="text-align:right">${i + 1}. ${esc(trunc(x.id, 36))} <span class="muted">L${x.level}</span></th>${M[i].map((v, j) => {
    const up = j < i && v; const bg = i === j ? 'var(--line)' : v ? (up ? `rgba(240,107,107,${.25 + .75 * v / max})` : `rgba(106,168,255,${.2 + .8 * v / max})`) : 'transparent';
    return `<td style="background:${bg}" title="${esc(x.id)} → ${esc(mods[j].id)}: ${v}">${v || ''}</td>`; }).join('')}</tr>`).join('')}</table>`;
}
