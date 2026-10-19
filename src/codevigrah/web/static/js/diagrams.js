// Mermaid diagrams, rendered in the browser and loaded on first use.
let mermaidReady = null, diagramSeq = 0;
function loadMermaid() {
  if (!mermaidReady) mermaidReady = new Promise((res, rej) => { const sc = document.createElement('script');
    sc.src = 'https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js'; sc.integrity = 'sha384-WmdflGW9aGfoBdHc4rRyWzYuAjEmDwMdGdiPNacbwfGKxBW/SO6guzuQ76qjnSlr'; sc.crossOrigin = 'anonymous'; sc.onload = () => res(window.mermaid); sc.onerror = rej; document.head.appendChild(sc); });
  return mermaidReady;
}
async function renderDiagrams(root) {
  const blocks = [...root.querySelectorAll('.diagram:not([data-done])')]; if (!blocks.length) return;
  blocks.forEach(b => b.dataset.done = '1');
  let mm; try { mm = await loadMermaid(); } catch { return; }
  const light = document.documentElement.dataset.theme === 'light';
  mm.initialize({ startOnLoad: false, securityLevel: 'strict', theme: light ? 'default' : 'dark', fontFamily: 'system-ui, sans-serif' });
  const byBase = {}; Object.keys(FILES).forEach(p => { const b = p.split('/').pop(); byBase[b] = byBase[b] === undefined ? p : null; });
  for (const b of blocks) {
    try {
      let src = b.dataset.src;
      if (/^\s*sequenceDiagram/.test(src)) src = src.replace(/^(\s*[^:\n]+?(?:->>|-->>|->|-->|-x|--x|-\)|--\))[^:\n]+:\s*)"(.*)"\s*$/gm, '$1$2');
      const { svg } = await mm.render('mmd' + (++diagramSeq), src);
      b.innerHTML = svg;
      // make file names inside the diagram clickable
      b.querySelectorAll('text, .nodeLabel, .messageText, .actor, tspan').forEach(t => {
        const txt = (t.textContent || '').trim().replace(/[`'"]/g, ''); const p = FILES[txt] ? txt : byBase[txt];
        if (p && !t.querySelector('tspan')) { t.classList.add('clickable'); t.style.cursor = 'pointer'; t.addEventListener('click', ev => { ev.stopPropagation(); openFile(p); }); }
      });
    } catch (e) { document.querySelectorAll('#dmmd' + diagramSeq).forEach(x => x.remove()); }  // leave the text version visible
  }
}
new MutationObserver(() => { renderDiagrams(document.body); }).observe(document.body, { childList: true, subtree: true });
