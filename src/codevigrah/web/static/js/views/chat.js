// Ask the repo: chat grounded in the analysis and retrieved source excerpts.
VIEWS.chat = m => {
  m.innerHTML = `<div class="card"><h3>Ask the repo</h3><p class="small muted">Answers are grounded in the analysis, a map of central files, and the most relevant source excerpts${pins.length ? ' plus pinned files' : ''}. ${LLM ? '' : '<b>No AI provider configured: answers fall back to file retrieval.</b>'}</p>
   ${pins.length ? `<div class="small">Pinned: ${pins.map(p => `<span class="chip">${esc(p)} <a data-unpin="${esc(p)}">×</a></span>`).join('')}</div>` : ''}</div>
   <div id="chatlog">${chatMsgs.map(msgHtml).join('') || '<div class="muted small" style="padding:10px">Try: “How does a request flow from entry to the database?” · “What would I need to change to support multi-tenancy?” · “Why is X split from Y?”</div>'}</div>
   <div style="display:flex;gap:8px;margin-top:10px;position:sticky;bottom:0;background:var(--bg);padding:8px 0"><textarea id="ask" rows="2" style="flex:1" placeholder="Ask anything about this codebase… (Enter to send, Shift+Enter for newline)"></textarea><div style="display:flex;flex-direction:column;gap:6px"><button id="send">Send</button><button class="ghost" id="clear">Clear</button></div></div>`;
  const send = async () => { const q = $('#ask').value.trim(); if (!q) return; $('#ask').value = ''; await chatSend(q); };
  $('#send').onclick = send; $('#ask').onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } };
  $('#clear').onclick = () => { chatMsgs = []; store.set('chat:' + RID, []); show('chat'); };
  m.querySelectorAll('[data-unpin]').forEach(a => a.onclick = () => { pins = pins.filter(p => p !== a.dataset.unpin); show('chat'); });
  m.scrollTop = m.scrollHeight;
};
const msgHtml = x => `<div class="msg ${x.role}">${x.role === 'assistant' ? '<a class="small listen-msg" style="float:right">▶ listen</a>' : ''}${x.role === 'user' ? esc(x.content).replace(/\n/g, '<br>') : md(x.content)}${x.sources?.length ? `<div class="small muted">context: ${x.sources.map(p => fl(p)).join(' · ')}</div>` : ''}</div>`;
async function chatSend(q) {
  if (VIEW !== 'chat') show('chat');
  chatMsgs.push({ role: 'user', content: q }); $('#chatlog').innerHTML = chatMsgs.map(msgHtml).join('') + '<div class="msg assistant"><span class="spin"></span> thinking…</div>';
  $('#main').scrollTop = $('#main').scrollHeight;
  try { const r = await api('/api/chat', { id: RID, messages: chatMsgs.map(({ role, content }) => ({ role, content })), pin: pins }); chatMsgs.push({ role: 'assistant', content: r.answer, sources: r.sources }); }
  catch (e) { chatMsgs.push({ role: 'assistant', content: '**Error:** ' + e.message }); }
  store.set('chat:' + RID, chatMsgs.slice(-40)); $('#chatlog').innerHTML = chatMsgs.map(msgHtml).join(''); $('#main').scrollTop = $('#main').scrollHeight;
}
document.addEventListener('click', e => { const a = e.target.closest('.listen-msg'); if (a) ttsStart(a.parentElement.querySelector('.md')); });
