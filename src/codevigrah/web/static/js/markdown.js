// A small Markdown renderer. Everything is escaped; repository paths become links to the inspector.
function fileRef(raw) {
  const m = raw.match(/^([\w./@+\-\[\]()]+?)(?::(\d+))?(?:-\d+)?$/);
  if (m && !FILES[m[1]] && BASE[m[1]]) return `<a data-path="${esc(BASE[m[1]])}" data-line="${m[2]||''}"><code>${esc(raw)}</code></a>`;
  if (m && FILES[m[1]]) return `<a data-path="${esc(m[1])}" data-line="${m[2]||''}"><code>${esc(raw)}</code></a>`;
  return `<code>${esc(raw)}</code>`;
}
function inline(t) {
  const parts = String(t).split(/(`[^`]+`)/g);
  return parts.map(p => {
    if (p.startsWith('`') && p.endsWith('`') && p.length > 1) return fileRef(p.slice(1, -1));
    let s = esc(p);
    s = s.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>').replace(/(^|[\s(])\*([^*\s][^*]*)\*/g, '$1<i>$2</i>').replace(/(^|\s)_([^_]+)_(?=\s|$|[.,;:)])/g, '$1<i>$2</i>');
    s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    return linkPaths(s, true);
  }).join('');
}
let BASE = {};  // unambiguous file name -> path
function linkPaths(s, escaped) {
  // s is already-escaped HTML text; wrap known repo paths (and unambiguous bare file names) in links
  s = s.replace(/(^|[\s(,;])([\w\-]+\.[a-z]{1,5})(?::(\d+)(?:-\d+)?)?(?=[\s),.;:]|$)/gi, (m, pre, name, ln) =>
    BASE[name] ? `${pre}<a data-path="${esc(BASE[name])}" data-line="${ln||''}">${m.slice(pre.length)}</a>` : m);
  return s.replace(/(^|[\s(,;:])([\w.\-@+\[\]]+(?:\/[\w.\-@+\[\]()]+)+\.\w+)(?::(\d+))?/g, (m, pre, p, ln) =>
    FILES[p] ? `${pre}<a data-path="${p}" data-line="${ln||''}">${p}${ln ? ':' + ln : ''}</a>` : m);
}
function md(src) {
  const L = String(src || '').split('\n'); const out = []; let i = 0;
  while (i < L.length) {
    let l = L[i];
    if (/^```/.test(l)) { const lang = l.slice(3).trim().toLowerCase(); const buf = []; i++; while (i < L.length && !/^```/.test(L[i])) buf.push(L[i++]); i++;
      const code = `<pre><code>${esc(buf.join('\n'))}</code></pre>`;
      out.push(lang === 'mermaid' ? `<div class="diagram" data-src="${esc(buf.join('\n'))}">${code}</div>` : code); continue; }
    const h = l.match(/^(#{1,4})\s+(.*)/); if (h) { out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); i++; continue; }
    if (/^\s*\|/.test(l)) { const rows = []; while (i < L.length && /^\s*\|/.test(L[i])) rows.push(L[i++]);
      const cells = r => r.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim());
      let html = '<table>'; rows.forEach((r, k) => { if (/^\s*\|?\s*:?-{2,}/.test(r)) return; const tag = k === 0 ? 'th' : 'td'; html += '<tr>' + cells(r).map(c => `<${tag}>${inline(c)}</${tag}>`).join('') + '</tr>'; });
      out.push(html + '</table>'); continue; }
    if (/^\s*([-*]|\d+\.)\s+/.test(l)) { const ordered = /^\s*\d+\./.test(l); const items = []; const start = ordered ? parseInt(l) || 1 : 1;
      const isItem = x => /^\s*([-*]|\d+\.)\s+/.test(x) && /^\s*\d+\./.test(x) === ordered;
      while (i < L.length) {
        if (!L[i].trim()) { let j = i; while (j < L.length && !L[j].trim()) j++;
          if (j < L.length && isItem(L[j])) { i = j; continue; }
          if (j < L.length && items.length && /^\s{2,}\S/.test(L[j]) && !/^\s*```/.test(L[j]) && !/^\s*([-*]|\d+\.)\s+/.test(L[j])) {  // indented paragraph belongs to the item
            const para = []; while (j < L.length && /^\s{2,}\S/.test(L[j])) para.push(L[j++].trim());
            items[items.length - 1] = items[items.length - 1].replace(/<\/li>$/, `<p>${inline(para.join(' '))}</p></li>`); i = j; continue; }
          break; }
        if (!isItem(L[i])) break;
        let it = L[i++].replace(/^\s*([-*]|\d+\.)\s+/, ''); const cb = it.match(/^\[( |x)\]\s*/i);
        items.push(cb ? `<li style="list-style:none"><input type="checkbox" disabled ${cb[1] !== ' ' ? 'checked' : ''}> ${inline(it.slice(cb[0].length))}</li>` : `<li>${inline(it)}</li>`);
        while (i < L.length && /^\s{2,}\S/.test(L[i]) && !/^\s*([-*]|\d+\.)\s+/.test(L[i])) items[items.length - 1] = items[items.length - 1].replace(/<\/li>$/, ' ' + inline(L[i++].trim()) + '</li>'); }
      out.push(ordered ? `<ol start="${start}">${items.join('')}</ol>` : `<ul>${items.join('')}</ul>`); continue; }
    if (/^\s*>/.test(l)) { const buf = []; while (i < L.length && /^\s*>/.test(L[i])) buf.push(L[i++].replace(/^\s*>\s?/, ''));
      const body = md(buf.join('\n')); out.push(/^\s*\*\*A[:.]/.test(buf[0]) ? `<details><summary>Show answer</summary>${body}</details>` : `<blockquote>${body}</blockquote>`); continue; }
    if (!l.trim()) { i++; continue; }
    const buf = []; while (i < L.length && L[i].trim() && !/^(#{1,4}\s|```|\s*\||\s*>|\s*([-*]|\d+\.)\s+)/.test(L[i])) buf.push(L[i++]);
    out.push(`<p>${inline(buf.join(' '))}</p>`);
  }
  return `<div class="md">${out.join('')}</div>`;
}
