// Guided tour: six chapters that go progressively deeper.
let TOUR = { key: null, poll: null };
VIEWS.tour = m => {
  const key = TOUR.key && TOUR.rid === RID ? TOUR.key : store.get('tour:' + RID, 'what');
  TOUR.rid = RID; TOUR.key = key;
  m.innerHTML = `<div class="steps" id="steps"></div><div class="tour" id="tourbody"></div>`;
  loadChapter(key);
};
async function tourSteps() {
  if (VIEW !== 'tour') return;
  const st = await api('/api/tour_status', { id: RID }).catch(() => null); if (!st || VIEW !== 'tour') return;
  TOUR.chapters = st.chapters;
  $('#steps').innerHTML = st.chapters.map((c, k) => `<button data-ch="${c.key}" class="${c.key === TOUR.key ? 'on' : ''}"><span class="st">${st.ready.includes(c.key) ? '✓' : st.working.includes(c.key) ? '<span class="spin" style="width:10px;height:10px"></span>' : ''}</span><b>${k + 1}. ${esc(c.title)}</b>${esc(c.sub)}</button>`).join('');
  $('#steps').querySelectorAll('[data-ch]').forEach(b => b.onclick = () => loadChapter(b.dataset.ch));
  clearTimeout(TOUR.poll); if (st.working.length) TOUR.poll = setTimeout(tourSteps, 5000);
}
async function loadChapter(key, regenerate) {
  TOUR.key = key; store.set('tour:' + RID, key); tourSteps(); history.replaceState(null, '', '#' + encodeURIComponent(RID) + '/tour/' + key);
  const body = $('#tourbody'); if (!body) return;
  body.innerHTML = `<div class="card"><span class="spin"></span> ${LLM ? 'The AI is reading the code and writing this chapter… (usually 20–90 seconds on first view, instant afterwards)' : 'Assembling…'}</div>`;
  $('#main').scrollTop = 0;
  try {
    const r = await api('/api/tour', { id: RID, chapter: key, regenerate: !!regenerate });
    if (TOUR.key !== key || VIEW !== 'tour') return;
    const chs = r.chapters, k = chs.findIndex(c => c.key === key), ch = chs[k], nx = chs[k + 1], pv = chs[k - 1];
    body.innerHTML = `<h1 style="margin:0 0 4px;font-size:24px">${esc(ch.title)}</h1><div class="muted" style="margin-bottom:14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap"><button class="listen" id="listen">▶ Listen</button><span>${esc(ch.sub)} · ${r.source === 'ai' ? 'written by AI from the code' : 'static summary'}</span>${r.error ? ` <span style="color:var(--warn)">(AI failed: ${esc(r.error)})</span>` : ''}</div>
      <div id="chtext">
      ${md(r.markdown)}</div>
      ${nx ? `<button class="next" data-ch="${nx.key}">Next: ${esc(nx.title)} →<span>${esc(nx.sub)}</span></button>`
           : `<div class="card" style="margin-top:22px"><b>You've finished the tour.</b> Now <a data-view="quiz">take the Skill check</a> to see how much stuck and which concepts to work on, or try the <a data-view="planner">Change planner</a> with an issue of your own, or explore the <a data-view="arch">Architecture</a> view. It should read much more naturally now.</div>`}
      <div style="display:flex;gap:10px;margin-top:12px;flex-wrap:wrap" class="small">${pv ? `<a data-ch="${pv.key}">← ${esc(pv.title)}</a>` : ''}<span style="flex:1"></span>
        <a data-ask="${esc(`I'm reading the guided-tour chapter "${ch.title}" about this repo. Something I'd like to understand better: `)}" id="askch">Ask about this chapter</a>${r.source === 'ai' ? ' · <a id="regen">Rewrite this chapter</a>' : ''}</div>`;
    body.querySelectorAll('[data-ch]').forEach(b => b.onclick = () => loadChapter(b.dataset.ch));
    body.querySelectorAll('[data-view]').forEach(b => b.onclick = () => show(b.dataset.view));
    const rg = $('#regen'); if (rg) rg.onclick = () => loadChapter(key, true);
    const listen = () => ttsStart($('#chtext'), { tour: true, source: { chapter: key }, onFinish: () => { if (nx && $('#tauto').checked && VIEW === 'tour') loadChapter(nx.key).then(() => { if (TOUR.key === nx.key) listen2(); }); } });
    const listen2 = () => { const b = $('#listen'); if (b) b.click(); };
    $('#listen').onclick = listen;
    $('#askch').onclick = e => { e.stopPropagation(); show('chat'); $('#ask').value = e.target.dataset.ask; $('#ask').focus(); };
    tourSteps();
  } catch (e) { body.innerHTML = `<div class="card flag">${esc(e.message)}</div>`; }
}
