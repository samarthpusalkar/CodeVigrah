// File inspector drawer, opened by clicking any file path anywhere.
async function openFile(path, line) {
  const f = FILES[path]; if (!f) return;
  const dr = $('#drawer'); dr.classList.add('open');
  const imports = A.out[f.i].map(j => A.files[j].path), importedBy = A.inc[f.i].map(j => A.files[j].path);
  const co = A.git ? A.git.coupling.filter(c => c.a === path || c.b === path).slice(0, 8).map(c => ({ p: c.a === path ? c.b : c.a, n: c.n })) : [];
  dr.querySelector('.head').innerHTML = `<div style="display:flex;gap:8px;align-items:center"><b class="mono" style="flex:1;word-break:break-all">${esc(path)}</b><button class="ghost" id="dclose">✕</button></div>
    <div style="margin-top:6px">${roleChip(f.role)}<span class="chip">${esc(f.lang)}</span><span class="chip">module ${esc(f.module)}</span><span class="chip">${f.loc} LOC</span><span class="chip">risk ${f.risk}</span>${f.churn != null ? `<span class="chip">${f.churn} commits · ${f.authors} authors · last ${fmtDate(f.last)}</span>` : ''}${f.cycle ? '<span class="chip" style="border-color:var(--bad)">in cycle</span>' : ''}</div>
    <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap"><button id="dexp" ${LLM ? '' : 'disabled title="needs an AI provider (see Settings)"'}>Explain with AI</button><button class="ghost" id="dpin">Pin to chat</button><button class="ghost" id="dplan">Plan a change here</button></div>`;
  const sec = (t, list, fmt) => list.length ? `<details ${list.length < 12 ? 'open' : ''}><summary><b>${t}</b> <span class="muted">(${list.length})</span></summary><div class="small">${list.map(fmt).join('<br>')}</div></details>` : '';
  dr.querySelector('.body').innerHTML = `
    ${f.risk_why.length ? `<p class="small"><b>Why risky:</b> ${f.risk_why.map(esc).join(', ')}</p>` : ''}
    <div id="dai"></div>
    ${sec('Imported by (blast radius)', importedBy, p => fl(p))}${sec('Imports', imports, p => fl(p))}
    ${sec('Changes together with', co, c => fl(c.p) + ` <span class="muted">${c.n}×</span>`)}${sec('Tests', f.tests, p => fl(p))}
    ${f.ext.length ? `<p class="small"><b>External imports:</b> ${f.ext.map(esc).join(', ')}</p>` : ''}
    ${sec('Symbols', f.sym, s => `<a data-path="${esc(path)}" data-line="${s[2]}" class="mono">${esc(s[0])}</a> <span class="muted">${s[1]} · L${s[2]}</span>`)}
    <div class="code" id="dcode"><div style="padding:10px"><span class="spin"></span></div></div>`;
  $('#dclose').onclick = () => dr.classList.remove('open');
  $('#dpin').onclick = () => { if (!pins.includes(path)) pins.push(path); $('#dpin').textContent = 'Pinned ✓'; };
  $('#dplan').onclick = () => { dr.classList.remove('open'); show('planner'); $('#issue').value = `Change ${path}: `; $('#issue').focus(); };
  $('#dexp').onclick = async () => { $('#dai').innerHTML = '<div class="card"><span class="spin"></span> asking…</div>';
    try { const r = await api('/api/explain', { id: RID, path, ai: true }); $('#dai').innerHTML = `<div class="card">${r.ai ? '<a class="small" id="dlisten">▶ listen</a>' + md(r.ai) : esc(r.ai_error || 'no answer')}</div>`; const dl = $('#dlisten'); if (dl) dl.onclick = () => ttsStart($('#dai .md')); } catch (e) { $('#dai').innerHTML = `<div class="card flag">${esc(e.message)}</div>`; } };
  const { text } = await api(`/api/file?id=${encodeURIComponent(RID)}&path=${encodeURIComponent(path)}`);
  const lines = text.split('\n');
  $('#dcode').innerHTML = `<table>${lines.map((l, k) => `<tr id="L${k + 1}" class="${+line === k + 1 ? 'hl' : ''}"><td class="ln">${k + 1}</td><td>${esc(l)}</td></tr>`).join('')}</table>`;
  if (line) { const r = $('#dcode').querySelector('#L' + line); if (r) r.scrollIntoView({ block: 'center' }); }
}
document.addEventListener('click', e => {
  const a = e.target.closest('[data-path]'); if (a && A) { e.preventDefault(); const p = a.dataset.path, ln = a.dataset.line;
    if ($('#drawer').classList.contains('open') && $('#drawer .mono')?.textContent === p && ln) { const r = $('#dcode').querySelector('#L' + ln); if (r) { $('#dcode').querySelectorAll('tr.hl').forEach(x => x.classList.remove('hl')); r.classList.add('hl'); r.scrollIntoView({ block: 'center' }); } return; }
    openFile(p, ln); return; }
  const q = e.target.closest('[data-ask]'); if (q && A) { e.preventDefault(); chatSend(q.dataset.ask); }
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') { $('#drawer').classList.remove('open'); $('#settings').style.display = 'none'; } });
