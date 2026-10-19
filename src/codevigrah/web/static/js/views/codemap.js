// Code map: treemap sized by lines of code, coloured by role, language, risk, churn, fan-in or age.
VIEWS.map = m => {
  m.innerHTML = `<div class="card"><div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><h3 style="margin:0">Code map</h3><span class="small muted">area = lines of code · colour =</span>
    <select id="tmcolor"><option value="role">role</option><option value="lang">language</option><option value="risk">change risk</option><option value="churn">churn (git)</option><option value="fanin">fan-in</option><option value="last">last modified</option></select>
    <label class="small"><input type="checkbox" id="tmcode" checked> code only</label><span id="tmleg" class="legend"></span></div><div id="tm" style="margin-top:10px"></div></div>`;
  const c = store.get('tmcolor', 'role'); $('#tmcolor').value = c;
  const draw = () => { store.set('tmcolor', $('#tmcolor').value); drawTreemap($('#tm'), $('#tmcolor').value, $('#tmcode').checked); };
  $('#tmcolor').onchange = draw; $('#tmcode').onchange = draw; draw();
};
function drawTreemap(el, metric, codeOnly) {
  el.innerHTML = '';
  const files = A.files.filter(f => f.loc > 0 && (!codeOnly || f.code));
  const root = { name: A.meta.name, children: [] }, dirs = { '': root };
  for (const f of files) { const parts = f.path.split('/'); let pref = '';
    for (let k = 0; k < parts.length - 1; k++) { const np = pref ? pref + '/' + parts[k] : parts[k];
      if (!dirs[np]) { dirs[np] = { name: parts[k], children: [] }; dirs[pref].children.push(dirs[np]); } pref = np; }
    dirs[pref].children.push({ name: parts.at(-1), f, value: f.loc }); }
  const W = el.clientWidth || 900, H = Math.max(480, innerHeight - 220);
  const h = d3.hierarchy(root).sum(d => d.value || 0).sort((a, b) => b.value - a.value);
  d3.treemap().size([W, H]).paddingOuter(2).paddingTop(d => d.depth && d.children ? 14 : 2).paddingInner(1).round(true)(h);
  let color, leg = '';
  if (metric === 'role') { color = f => ROLE_COLORS[f.role] || '#555'; leg = Object.entries(ROLE_COLORS).filter(([r]) => files.some(f => f.role === r)).map(([r, c]) => `<span><i style="background:${c}"></i>${r}</span>`).join(''); }
  else if (metric === 'lang') { color = f => langColor(f.lang); leg = [...new Set(files.map(f => f.lang))].slice(0, 8).map(l => `<span><i style="background:${langColor(l)}"></i>${esc(l)}</span>`).join(''); }
  else { const vals = files.map(f => f[metric] || 0).sort(d3.ascending); const q = d3.scaleQuantile().domain(vals).range(d3.range(0, 1.0001, .1));
    color = f => d3.interpolateYlOrRd(.08 + .9 * q(f[metric] || 0)); leg = `<span><i style="background:${d3.interpolateYlOrRd(.1)}"></i>low</span><span><i style="background:${d3.interpolateYlOrRd(.95)}"></i>high (percentile)</span>`;
    if (metric !== 'risk' && !A.git && metric !== 'fanin') leg = '<span class="muted">no git history</span>'; }
  $('#tmleg').innerHTML = leg;
  const svg = d3.select(el).append('svg').attr('width', W).attr('height', H).style('font-size', '10px');
  const dirsN = h.descendants().filter(d => d.children && d.depth);
  svg.selectAll('rect.d').data(dirsN).join('rect').attr('x', d => d.x0).attr('y', d => d.y0).attr('width', d => d.x1 - d.x0).attr('height', d => d.y1 - d.y0).attr('fill', 'var(--panel2)').attr('stroke', 'var(--line)');
  svg.selectAll('text.d').data(dirsN.filter(d => d.x1 - d.x0 > 40)).join('text').attr('x', d => d.x0 + 3).attr('y', d => d.y0 + 10).style('fill', 'var(--muted)').text(d => trunc(d.data.name + '/', (d.x1 - d.x0) / 6));
  const leaves = svg.selectAll('g.l').data(h.leaves()).join('g').attr('transform', d => `translate(${d.x0},${d.y0})`).style('cursor', 'pointer');
  leaves.append('rect').attr('width', d => Math.max(0, d.x1 - d.x0)).attr('height', d => Math.max(0, d.y1 - d.y0)).attr('fill', d => color(d.data.f)).attr('fill-opacity', .85);
  leaves.filter(d => d.x1 - d.x0 > 46 && d.y1 - d.y0 > 13).append('text').attr('x', 3).attr('y', 11).style('fill', '#111').text(d => trunc(d.data.name, (d.x1 - d.x0) / 6));
  leaves.on('mousemove', (e, d) => { const f = d.data.f; showTip(e, `<b>${esc(f.path)}</b><br>${esc(f.role)} · ${esc(f.lang)} · ${f.loc} LOC<br>fan-in ${f.fanin} · fan-out ${f.fanout} · risk ${f.risk}${f.churn != null ? ` · ${f.churn} commits` : ''}${f.risk_why.length ? '<br>' + f.risk_why.map(esc).join(', ') : ''}`); })
    .on('mouseleave', hideTip).on('click', (e, d) => openFile(d.data.f.path));
}
