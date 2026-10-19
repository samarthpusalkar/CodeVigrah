// Skill check: leveled questions and "which files change" exercises, graded in the browser.
const QZ = { level: 1, data: {}, answers: {}, graded: {} };
const SCOPE_LABEL = { repo: 'This repo', language: 'Language features', design: 'System design & architecture', domain: 'Domain knowledge' };
const SKILL_LABEL = { purpose: 'Purpose', structure: 'Structure (where things live)', flow: 'Flow (how it works)', data: 'Data & state', design: 'Design trade-offs', 'change-impact': 'Change impact' };
const qStore = () => store.get('quiz:' + RID, { attempts: [] });
const pct = x => Math.round(100 * x);
const scoreColor = x => x >= .7 ? 'var(--good)' : x >= .4 ? 'var(--warn)' : 'var(--bad)';
function gradeQ(q, ans) {
  if (q.type === 'mcq') return ans === undefined ? 0 : (ans === q.answer ? 1 : 0);
  const S = new Set(ans || []), M = new Set(q.must), Y = new Set(q.maybe || []);
  const hits = [...S].filter(p => M.has(p)).length, wrong = [...S].filter(p => !M.has(p) && !Y.has(p)).length;
  return M.size ? Math.max(0, hits / (M.size + wrong)) : 0;
}
VIEWS.quiz = m => {
  m.innerHTML = `<div class="tour" style="max-width:900px">
   <h1 style="margin:0 0 4px;font-size:24px">Skill check</h1>
   <p class="muted" style="margin-top:0">Three levels that match how an owner's understanding grows. Each question is tagged by <b>skill</b> and by <b>scope</b> (this repo, the language, system design, or the domain), so your results show <i>what kind</i> of understanding to work on, not just a number. Some "which files change" exercises are real commits from the project's history.</p>
   <div class="tabs" id="qtabs"></div><div id="qbody"></div></div>`;
  quizTabs(); QZ.level === 'results' ? quizResults() : quizLevel(QZ.level);
};
function bestFor(level) { const at = qStore().attempts.filter(a => a.level === level); return at.length ? Math.max(...at.map(a => a.score)) : null; }
function quizTabs() {
  const t = $('#qtabs'); if (!t) return;
  t.innerHTML = [1, 2, 3].map(l => { const b = bestFor(l); return `<button data-ql="${l}" class="${QZ.level === l ? 'on' : ''}">${l}. ${['Reader', 'Contributor', 'Owner'][l - 1]}${b !== null ? ` · ${pct(b)}%` : ''}</button>`; }).join('')
    + `<button data-ql="results" class="${QZ.level === 'results' ? 'on' : ''}">Your results</button>`;
  t.querySelectorAll('[data-ql]').forEach(b => b.onclick = () => { QZ.level = b.dataset.ql === 'results' ? 'results' : +b.dataset.ql; quizTabs(); QZ.level === 'results' ? quizResults() : quizLevel(QZ.level); });
}
async function quizLevel(level, regenerate) {
  const body = $('#qbody'); if (!body) return;
  const key = RID + ':' + level;
  if (!QZ.data[key] || regenerate) {
    body.innerHTML = `<div class="card"><span class="spin"></span> ${LLM ? 'The AI is reading the code and writing level ' + level + ' questions… (about 1–2 minutes the first time; cached afterwards)' : 'Preparing questions…'}</div>`;
    try {
      const avoid = regenerate && QZ.data[key] ? QZ.data[key].questions.map(q => q.question || q.scenario).filter(Boolean) : [];
      QZ.data[key] = await api('/api/quiz', { id: RID, level, regenerate: !!regenerate, avoid });
    } catch (e) { body.innerHTML = `<div class="card flag">${esc(e.message)}</div>`; return; }
    QZ.answers[key] = {}; QZ.graded[key] = false;
    if (QZ.level !== level) return;
  }
  const D = QZ.data[key], A_ = QZ.answers[key] = QZ.answers[key] || {}, graded = QZ.graded[key];
  const qs = D.questions; let total = 0;
  const cards = qs.map((q, n) => {
    const sc = graded ? gradeQ(q, A_[q.id]) : null; total += sc || 0;
    const cls = graded ? (sc >= .99 ? 'right' : sc > 0 ? 'part' : 'wrong') : '';
    const tags = `<div class="tag">Q${n + 1} · ${esc(SKILL_LABEL[q.skill] || q.skill)} · ${esc(SCOPE_LABEL[q.scope] || q.scope)}${graded ? ' · concept: ' + esc(q.concept) : ''}${q.source === 'history' ? ' · from real history' : ''}</div>`;
    let inner;
    if (q.type === 'mcq') {
      inner = `<div style="margin:6px 0 4px;font-weight:600">${inline(q.question)}</div>` + q.choices.map((c, k) => {
        const picked = A_[q.id] === k, oc = graded ? (k === q.answer ? 'correct' : picked ? 'picked-wrong' : '') : '';
        return `<label class="opt ${oc}"><input type="radio" name="q${q.id}" data-q="${q.id}" value="${k}" ${picked ? 'checked' : ''} ${graded ? 'disabled' : ''}> ${inline(c)}</label>`; }).join('');
    } else {
      const sel = new Set(A_[q.id] || []), M = new Set(q.must), Y = new Set(q.maybe || []);
      inner = `<div style="margin:6px 0 4px;font-weight:600">Which files would you edit?</div><div style="margin-bottom:6px">${q.source === 'history' ? '<span class="chip">real commit</span> ' : ''}${inline(q.scenario)}</div>
        <div class="small muted" style="margin-bottom:4px">Tick every file that must change. ${graded ? '' : '<a data-hints="' + q.id + '">show file descriptions</a>'}</div>` +
        q.candidates.map(p => { const f = FILES[p] || {}; const on = sel.has(p);
          const st = graded ? (M.has(p) ? (on ? 'hit' : 'miss') : (on && !Y.has(p) ? 'extra' : '')) : '';
          const mark = graded ? (M.has(p) ? (on ? '✓ needed' : '◌ missed (needed)') : Y.has(p) ? (on ? '~ optional' : '~ optional (also reasonable)') : on ? '✗ not needed' : '') : '';
          return `<label class="fopt ${st}"><input type="checkbox" data-qf="${q.id}" value="${esc(p)}" ${on ? 'checked' : ''} ${graded ? 'disabled' : ''}>
            <span><span class="mono">${esc(p)}</span> ${mark ? `<b class="small">${mark}</b>` : ''}<span class="small muted hint-${q.id}" style="display:${graded ? 'block' : 'none'}">${esc(f.doc || '')}</span>
            ${graded && q.why && q.why[p] && q.source !== 'history' ? `<span class="small" style="display:block">${inline(q.why[p])}</span>` : ''}</span></label>`; }).join('');
    }
    const fb = graded ? `<div style="margin-top:10px"><b>${sc >= .99 ? '✓ Correct' : sc > 0 ? `◐ Partly right (${pct(sc)}%)` : '✗ Not quite'}</b>${md(q.explanation || '')}
      ${(q.refs || []).length ? `<div class="small">See: ${q.refs.map(r => fileRef(r)).join(' · ')}</div>` : ''}
      ${sc < .99 ? `<a class="small" data-ask="${esc(`I got this wrong in the skill check for this repo. Teach me the concept "${q.concept}" using this codebase, then check my understanding with one follow-up question.\n\nQuestion: ${q.question || q.scenario}`)}">Teach me “${esc(q.concept)}” →</a>` : ''}</div>` : '';
    return `<div class="card q ${cls}">${tags}${inner}${fb}</div>`;
  }).join('');
  const score = qs.length ? total / qs.length : 0;
  const head = `<div class="card"><b>Level ${level}: ${esc(D.info.name)}</b>. ${esc(D.info.goal)} <span class="muted small">${D.source === 'ai' ? 'Questions written by AI from the code.' : 'Static questions (enable AI for richer ones).'}${D.error ? ' AI failed: ' + esc(D.error) : ''}</span>
    ${graded ? `<div class="mrow" style="margin-top:10px"><span class="lab"><b>Your score</b></span><span class="meter"><i style="width:${pct(score)}%;background:${scoreColor(score)}"></i></span><span class="val"><b>${pct(score)}%</b></span></div>
      <div class="small">${score >= .7 ? `Passed: you've reached <b>${esc(D.info.name)}</b> level understanding.` : 'Not passed yet (70% needed). Read the explanations, revisit the tour, then retry.'}</div>` : ''}</div>`;
  const foot = graded
    ? `<div style="display:flex;gap:10px;flex-wrap:wrap;margin:10px 0 30px">${level < 3 ? `<button id="qnext">Level ${level + 1}: ${['', 'Contributor', 'Owner'][level]} →</button>` : ''}<button class="ghost" id="qres">See my results</button><button class="ghost" id="qretry">Retry same questions</button><button class="ghost" id="qnew">New questions</button></div>`
    : `<button class="next" id="qsubmit" style="margin-bottom:30px">Check my answers<span>${qs.length} questions · you can leave some blank</span></button>`;
  body.innerHTML = head + (qs.length ? cards : '<div class="card">No questions could be generated for this level.</div>') + foot;
  body.querySelectorAll('[data-q]').forEach(r => r.onchange = () => { A_[r.dataset.q] = +r.value; });
  body.querySelectorAll('[data-qf]').forEach(c => c.onchange = () => { const s2 = new Set(A_[c.dataset.qf] || []); c.checked ? s2.add(c.value) : s2.delete(c.value); A_[c.dataset.qf] = [...s2]; });
  body.querySelectorAll('[data-hints]').forEach(a => a.onclick = () => body.querySelectorAll('.hint-' + a.dataset.hints).forEach(x => x.style.display = 'block'));
  const on = (id, f) => { const e = $('#' + id); if (e) e.onclick = f; };
  on('qsubmit', () => { QZ.graded[key] = true;
    const results = qs.map(q => ({ id: q.id, level, type: q.type, skill: q.skill, scope: q.scope, concept: q.concept, score: gradeQ(q, A_[q.id]), refs: q.refs || q.must || [] }));
    const st = qStore(); st.attempts.push({ ts: Date.now(), level, source: D.source, score: results.reduce((x, r) => x + r.score, 0) / Math.max(1, results.length), results });
    st.attempts = st.attempts.slice(-60); store.set('quiz:' + RID, st); quizTabs(); quizLevel(level); $('#main').scrollTop = 0; });
  on('qnext', () => { QZ.level = level + 1; quizTabs(); quizLevel(level + 1); $('#main').scrollTop = 0; });
  on('qres', () => { QZ.level = 'results'; quizTabs(); quizResults(); });
  on('qretry', () => { QZ.answers[key] = {}; QZ.graded[key] = false; quizLevel(level); $('#main').scrollTop = 0; });
  on('qnew', () => quizLevel(level, true));
}
function quizResults() {
  const body = $('#qbody'); const st = qStore();
  if (!st.attempts.length) { body.innerHTML = '<div class="card">No attempts yet. Start with <a data-ql2="1">Level 1</a>.</div>'; body.querySelector('[data-ql2]').onclick = () => { QZ.level = 1; quizTabs(); quizLevel(1); }; return; }
  // latest answer per question wins; aggregate by scope / skill / concept
  const latest = {}; st.attempts.forEach(a => a.results.forEach(r => latest[r.id] = r));
  const rs = Object.values(latest);
  const agg = key => { const g = {}; rs.forEach(r => { (g[r[key]] = g[r[key]] || []).push(r.score); }); return Object.entries(g).map(([k, v]) => ({ k, n: v.length, s: v.reduce((a, b) => a + b, 0) / v.length })); };
  const bar = (label, s, n) => `<div class="mrow"><span class="lab">${label} <span class="muted small">(${n})</span></span><span class="meter"><i style="width:${pct(s)}%;background:${scoreColor(s)}"></i></span><span class="val">${pct(s)}%</span></div>`;
  const lvl = [1, 2, 3].map(l => { const x = rs.filter(r => r.level === l); return x.length ? x.reduce((a, r) => a + r.score, 0) / x.length : null; });
  const names = [['Reader', 'knows what it is and where things live'], ['Contributor', 'knows how it works inside'], ['Owner', 'predicts change impact and defends the design']];
  const reached = lvl.findIndex(x => x === null || x < .7); const title = reached === -1 ? 'Owner' : reached === 0 ? 'Getting started' : names[reached - 1][0];
  const concepts = agg('concept').sort((a, b) => a.s - b.s);
  const weak = concepts.filter(c => c.s < .7), strong = concepts.filter(c => c.s >= .7);
  const scopeAgg = agg('scope'), skillAgg = agg('skill');
  const weakestScope = scopeAgg.filter(x => x.n >= 2).sort((a, b) => a.s - b.s)[0];
  const learnFor = c => { const ws = c.toLowerCase().split(/[\s\-\/]+/).filter(w => w.length > 3); if (!ws.length) return null;
    let best = null, bs = 0; (A.concepts || []).forEach(x => { const t = x.title.toLowerCase(); const sc = ws.filter(w => t.includes(w.replace(/s$/, ''))).length / ws.length; if (sc > bs) { bs = sc; best = x; } });
    return bs >= 0.6 ? best : null; };
  body.innerHTML = `
   <div class="card"><h3 style="margin-top:0">Where you are: ${esc(title)}</h3>
     <div class="ladder">${names.map(([n, d], i) => `<div class="rung ${lvl[i] !== null && lvl[i] >= .7 ? 'pass' : ''}"><b>${i + 1}. ${n}</b><div class="small muted">${d}</div><div style="margin-top:6px">${lvl[i] === null ? '<span class="muted">not taken</span>' : `<b style="color:${scoreColor(lvl[i])}">${pct(lvl[i])}%</b>${lvl[i] >= .7 ? ' ✓' : ''}`}</div></div>`).join('')}</div>
     ${weakestScope && weakestScope.s < .7 ? `<p style="margin-bottom:0"><b>Biggest gap:</b> ${esc(SCOPE_LABEL[weakestScope.k] || weakestScope.k)} (${pct(weakestScope.s)}%). ${weakestScope.k === 'repo' ? 'Re-read tour chapters 2–3 and trace the flow yourself in the code.' : 'This is transferable knowledge: the "Teach me" links below will pay off beyond this repo.'}</p>` : ''}</div>
   <div class="grid">
     <div class="card"><h3>By kind of knowledge</h3>${['repo', 'language', 'design', 'domain'].map(k => scopeAgg.find(x => x.k === k)).filter(Boolean).map(x => bar(esc(SCOPE_LABEL[x.k] || x.k), x.s, x.n)).join('')}
       <p class="small muted">"This repo" means knowing this codebase. The other three are transferable: they make the <i>next</i> repo faster to learn.</p></div>
     <div class="card"><h3>By skill</h3>${skillAgg.sort((a, b) => SKILLS_ORDER(a.k) - SKILLS_ORDER(b.k)).map(x => bar(esc(SKILL_LABEL[x.k] || x.k), x.s, x.n)).join('')}</div>
   </div>
   <div class="card"><h3>Concepts to work on</h3>${weak.length ? weak.map(c => { const lc = learnFor(c.k); return `<div style="margin:8px 0;display:flex;gap:10px;align-items:center;flex-wrap:wrap"><span class="chip" style="border-color:${scoreColor(c.s)}">${pct(c.s)}%</span><b>${esc(c.k)}</b>
       <a class="small" data-ask="${esc(`Teach me the concept "${c.k}" using this repository's code. Start from what a beginner needs, show where it appears here (files and lines), explain why the project uses it, then give me one small exercise.`)}">Teach me with this repo →</a>${lc ? ` <a class="small" data-view-learn="1">Concept card: ${esc(lc.title)}</a>` : ''}</div>`; }).join('') : '<span class="muted">Nothing below 70%. Nice. Try the next level or "New questions".</span>'}</div>
   ${strong.length ? `<div class="card"><h3>Strong areas</h3>${strong.map(c => `<span class="chip" style="border-color:var(--good)">${esc(c.k)} · ${pct(c.s)}%</span>`).join('')}</div>` : ''}
   <div class="card"><h3>Progress over time</h3><table><tr><th>When</th><th>Level</th><th>Score</th><th>Questions</th></tr>${st.attempts.slice().reverse().slice(0, 15).map(a => `<tr><td class="small">${new Date(a.ts).toLocaleString()}</td><td>${a.level}. ${names[a.level - 1][0]}</td><td><b style="color:${scoreColor(a.score)}">${pct(a.score)}%</b></td><td class="small muted">${a.results.length} · ${a.source === 'ai' ? 'AI' : 'static'}</td></tr>`).join('')}</table>
     <a class="small" id="qreset">Reset my results for this repo</a></div>`;
  body.querySelectorAll('[data-view-learn]').forEach(a => a.onclick = () => show('learn'));
  $('#qreset').onclick = () => { if (confirm('Clear all skill-check results for this repo?')) { store.set('quiz:' + RID, { attempts: [] }); quizTabs(); quizResults(); } };
}
const SKILLS_ORDER = k => ['purpose', 'structure', 'flow', 'data', 'design', 'change-impact'].indexOf(k);
