// Dependency graph: force-directed file graph with module filter and neighbourhood focus.
VIEWS.graph = m => {
  const mods = [...new Set(A.files.filter(f => f.code).map(f => f.module))].sort();
  m.innerHTML = `<div class="card"><div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><h3 style="margin:0">File dependency graph</h3>
    <select id="gmod"><option value="">All modules</option>${mods.map(x => `<option>${esc(x)}</option>`).join('')}</select>
    <select id="gmax"><option>150</option><option selected>300</option><option>600</option></select><span class="small muted">most central files</span>
    <label class="small"><input type="checkbox" id="gtest"> include tests</label><input id="gfind" placeholder="highlight file…" style="width:180px"></div>
    <p class="small muted">Node size = number of dependents. Colour = module. Arrows point to the imported file. Click a node to focus its neighbourhood and open it; drag to rearrange; scroll to zoom.</p><div id="gsvg"></div></div>`;
  const draw = () => drawGraph($('#gsvg'), $('#gmod').value, +$('#gmax').value, $('#gtest').checked);
  ['gmod', 'gmax', 'gtest'].forEach(id => $('#' + id).onchange = draw); draw();
};
let GRAPH = null;
function drawGraph(el, mod, max, tests) {
  el.innerHTML = '';
  let fs = A.files.filter(f => f.code && (tests || f.role !== 'test') && (!mod || f.module === mod || A.out[f.i].some(j => A.files[j].module === mod) || A.inc[f.i].some(j => A.files[j].module === mod && !mod)));
  if (mod) fs = A.files.filter(f => f.code && (tests || f.role !== 'test') && (f.module === mod || A.out[f.i].concat(A.inc[f.i]).some(j => A.files[j].module === mod)));
  fs = fs.sort((a, b) => (b.pr + b.fanin + b.fanout * .3) - (a.pr + a.fanin + a.fanout * .3)).slice(0, max);
  const keep = new Set(fs.map(f => f.i));
  const nodes = fs.map(f => ({ id: f.i, f })), links = A.edges.filter(([a, b]) => keep.has(a) && keep.has(b)).map(([a, b]) => ({ source: a, target: b }));
  const W = el.clientWidth || 900, H = Math.max(520, innerHeight - 230);
  const svg = d3.select(el).append('svg').attr('width', W).attr('height', H), g = svg.append('g');
  svg.call(d3.zoom().scaleExtent([.1, 6]).on('zoom', e => g.attr('transform', e.transform)));
  svg.append('defs').append('marker').attr('id', 'ga').attr('viewBox', '0 0 10 10').attr('refX', 18).attr('refY', 5).attr('markerWidth', 5).attr('markerHeight', 5).attr('orient', 'auto').append('path').attr('d', 'M0,0L10,5L0,10z').attr('fill', 'var(--muted)');
  const mc = d3.scaleOrdinal(d3.schemeTableau10.concat(d3.schemeSet3));
  const r = d => 3 + Math.sqrt(d.f.fanin) * 2.2;
  const link = g.append('g').attr('stroke', 'var(--muted)').attr('stroke-opacity', .25).selectAll('line').data(links).join('line').attr('marker-end', 'url(#ga)');
  const node = g.append('g').selectAll('circle').data(nodes).join('circle').attr('r', r).attr('fill', d => mc(d.f.module)).attr('stroke', d => d.f.cycle ? 'var(--bad)' : 'var(--panel)').attr('stroke-width', 1.5).style('cursor', 'pointer');
  const label = g.append('g').selectAll('text').data(nodes.filter(d => d.f.fanin >= 4 || nodes.length < 60)).join('text').style('font-size', '9.5px').style('pointer-events', 'none').attr('dx', 8).attr('dy', 3).text(d => d.f.path.split('/').pop());
  const sim = d3.forceSimulation(nodes).force('link', d3.forceLink(links).id(d => d.id).distance(45).strength(.25)).force('charge', d3.forceManyBody().strength(-70))
    .force('center', d3.forceCenter(W / 2, H / 2)).force('collide', d3.forceCollide(d => r(d) + 2)).alphaDecay(.04)
    .on('tick', () => { link.attr('x1', d => d.source.x).attr('y1', d => d.source.y).attr('x2', d => d.target.x).attr('y2', d => d.target.y);
      node.attr('cx', d => d.x).attr('cy', d => d.y); label.attr('x', d => d.x).attr('y', d => d.y); });
  node.call(d3.drag().on('start', (e, d) => { if (!e.active) sim.alphaTarget(.2).restart(); d.fx = d.x; d.fy = d.y; }).on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; }).on('end', (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = d.fy = null; }));
  const focus = id => { const nb = new Set([id, ...A.out[id], ...A.inc[id]]);
    node.attr('opacity', d => id == null || nb.has(d.id) ? 1 : .12); label.attr('opacity', d => id == null || nb.has(d.id) ? 1 : .1);
    link.attr('stroke-opacity', d => id == null ? .25 : (d.source.id === id || d.target.id === id ? .9 : .03)).attr('stroke', d => id != null && d.source.id === id ? 'var(--accent)' : id != null && d.target.id === id ? 'var(--warn)' : 'var(--muted)'); };
  node.on('mousemove', (e, d) => showTip(e, `<b>${esc(d.f.path)}</b><br>${esc(d.f.module)} · ${d.f.fanin} dependents · imports ${d.f.fanout}<br><span style="color:var(--accent)">blue</span>=imports, <span style="color:var(--warn)">amber</span>=imported by`))
    .on('mouseleave', hideTip).on('click', (e, d) => { focus(d.id); openFile(d.f.path); });
  svg.on('dblclick.zoom', null).on('click', e => { if (e.target.tagName === 'svg') focus(null); });
  $('#gfind').oninput = e => { const q = e.target.value.toLowerCase(); node.attr('stroke', d => q && d.f.path.toLowerCase().includes(q) ? 'var(--accent)' : d.f.cycle ? 'var(--bad)' : 'var(--panel)').attr('stroke-width', d => q && d.f.path.toLowerCase().includes(q) ? 4 : 1.5); };
}
