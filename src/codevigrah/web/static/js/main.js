// Wire up the header and start the app (loaded last).
$('#go').onclick = () => analyze(false); $('#refresh').onclick = () => analyze(true);
$('#src').onkeydown = e => { if (e.key === 'Enter') analyze(false); };
$('#recent').onchange = e => { if (e.target.value) open(e.target.value); };
$('#setbtn').onclick = () => { $('#settings').style.display = 'flex'; };
$('#setclose').onclick = () => { $('#settings').style.display = 'none'; };
$('#setsave').onclick = async () => {
  const name = $('#provider').value, body = {};
  if (name === 'auto' || name === 'off') body.order = name;
  else {
    const p = SETTINGS.providers.find(x => x.name === name);
    Object.assign(body, { provider: name, model: $('#model').value });
    if (p.fields.includes('base_url')) body.base_url = $('#pbase').value;
    if ($('#key').value) body.api_key = $('#key').value;
    body.order = $('#fallback').checked ? [name, ...SETTINGS.providers.map(x => x.name).filter(n => n !== name)].join(',') : name;
  }
  try { await api('/api/settings', body); } catch (e) { alert(e.message); return; }
  $('#key').value = ''; $('#settings').style.display = 'none'; await refreshSettings(); if (A) show(VIEW);
};
const applyTheme = t => { if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme; };
applyTheme(store.get('theme', ''));
$('#themebtn').onclick = () => { const t = document.documentElement.dataset.theme === 'light' ? '' : 'light'; store.set('theme', t); applyTheme(t); if (A) show(VIEW); };
window.addEventListener('resize', () => { if (A && ['arch', 'map', 'graph'].includes(VIEW)) { clearTimeout(window._rz); window._rz = setTimeout(() => show(VIEW), 250); } });
renderNav(); refreshSettings(); loadRecent();
if (location.hash.length > 1) { const [rid, v, ch] = location.hash.slice(1).split('/'); if (v) VIEW = v; if (ch) { TOUR.key = ch; TOUR.rid = decodeURIComponent(rid); } open(decodeURIComponent(rid)).catch(() => {}); }
