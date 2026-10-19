// Report: downloadable Markdown onboarding document.
VIEWS.report = m => {
  m.innerHTML = `<div class="card"><h3>Repository report</h3><p class="small muted">A readable onboarding document: brief, architecture by layer, design decisions with their costs, routes/models/commands, hotspots, shortcomings, concepts and a reading order.</p>
   <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><button id="gen">Generate</button><label class="small"><input type="checkbox" id="ainarr" ${LLM ? 'checked' : 'disabled'}> include AI architecture narrative</label>
   <button class="ghost" id="dl" disabled>Download .md</button><button class="ghost" id="replisten" disabled>▶ Listen</button><button class="ghost" id="cp" disabled>Copy markdown</button></div></div><div class="card" id="rep" style="display:none"></div>`;
  let mdText = '';
  $('#gen').onclick = async () => { $('#gen').disabled = true; $('#rep').style.display = 'block'; $('#rep').innerHTML = '<span class="spin"></span> generating…';
    try { mdText = (await api('/api/report', { id: RID, ai: $('#ainarr').checked })).markdown; $('#rep').innerHTML = md(mdText); $('#dl').disabled = $('#cp').disabled = $('#replisten').disabled = false; }
    catch (e) { $('#rep').innerHTML = esc(e.message); } $('#gen').disabled = false; };
  $('#dl').onclick = () => { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([mdText], { type: 'text/markdown' })); a.download = `${A.meta.name}-report.md`; a.click(); };
  $('#replisten').onclick = () => ttsStart($('#rep'));
  $('#cp').onclick = () => navigator.clipboard.writeText(mdText).then(() => { $('#cp').textContent = 'Copied'; });
};
