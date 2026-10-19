// Shared state, DOM helpers, local storage and the API client.
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let A = null, RID = null, FILES = {}, VIEW = 'tour', chatMsgs = [], pins = [], LLM = false;
const ROLE_COLORS = {route:'#e0739b',service:'#9b8cff',model:'#f2b84b',migration:'#d49a4b',ui:'#4fc5c0',cli:'#6aa8ff',logic:'#7f8ea6',util:'#a3adbd',test:'#4fc58b',config:'#8c7a5b',ci:'#b0875a',docs:'#5f6b7d',generated:'#555e6e',example:'#6d7f6a',other:'#444c5a'};
const store = { get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d } catch { return d } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)) } catch {} } };

async function api(path, body) {
  const r = await fetch(path, body ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)} : {});
  const j = await r.json().catch(() => ({error: r.statusText}));
  if (!r.ok || j.error) throw new Error(j.error || r.status);
  return j;
}
