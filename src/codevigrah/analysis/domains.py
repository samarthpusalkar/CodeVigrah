"""Classify what kind of project this is (backend, CLI, database engine, ...) with evidence."""

import posixpath
import re
from collections import Counter, defaultdict

from .. import knowledge as K


def detect_domains(files, deps, corpus, entities, langs_loc):
    score, ev = Counter(), defaultdict(list)
    frameworks = []
    for d in sorted(deps):
        sig = K.DEP_SIGNALS.get(d)
        if sig:
            dom, label = sig
            if label not in frameworks:
                frameworks.append(label)
            if dom == 'data':
                score['backend'] += 1
                ev['backend'].append(f'data library: {label}')
                continue
            w = 1 if label in ('NumPy', 'Rich', 'argparse', 'webpack', 'uvicorn', 'gunicorn') else 3
            score[dom] += w
            ev[dom].append(f'dependency: {label}')
    paths = [f['path'] for f in files]
    code_loc = sum(langs_loc.values()) or 1
    if entities['routes']:
        n = len([r for r in entities['routes'] if r['method'] != 'PAGE'])
        if n:
            score['backend'] += min(8, 2 + n // 3)
            ev['backend'].append(f'{n} HTTP routes detected')
    ui_loc = sum(f['loc'] for f in files if f['lang'] in ('Vue', 'Svelte') or f['path'].endswith(('.tsx', '.jsx')))
    if ui_loc:
        score['frontend'] += min(8, 1 + int(10 * ui_loc / code_loc))
        ev['frontend'].append(f'{ui_loc} LOC of component files (jsx/tsx/vue/svelte)')
    cmds = [c for c in entities['commands'] if c['kind'] == 'command']
    opts = [c for c in entities['commands'] if c['kind'] == 'option']
    if cmds or len(opts) >= 3:
        score['cli'] += min(8, 2 + len(cmds) // 2 + len(opts) // 5)
        ev['cli'].append(f'{len(cmds)} commands / {len(opts)} options declared')
    g = corpus.grep(r'(if __name__ == .__main__.|sys\.argv|os\.Args|process\.argv|std::env::args)', only_code=True)
    if g['count']:
        score['cli'] += 1
        ev['cli'].append(f'{g["count"]} argv/__main__ usages')
    if any(p.endswith(('bin/cli.js', 'bin/index.js')) or '/cmd/' in '/' + p for p in paths):
        score['cli'] += 2
        ev['cli'].append('cmd/ or bin/ entry directory')
    eng = sum(
        1
        for p in paths
        if re.search(
            r'(^|/|_)(btree|bplus|wal|pager|buffer_?pool|memtable|sstable|lsm|mvcc|planner|optimizer|executor|storage|txn|transaction|catalog|tuple|heap)[\w]*\.\w+$',
            p.lower(),
        )
    )
    if eng >= 3:
        score['database'] += 3 + eng
        ev['database'].append(f'{eng} storage-engine style files (btree/wal/pager/planner...)')
    g = corpus.grep(
        r'(\bbtree\b|b\+tree|leaf_node|internal_node|sstable|memtable|write.?ahead|\bwal\b|buffer.?pool|page_num|\bmvcc\b)',
        only_code=True,
    )
    if g['count'] >= 10:
        score['database'] += 4 + min(6, g['count'] // 20)
        ev['database'].append(f'{g["count"]} storage-engine terms in code (btree/wal/pages...)')
    g = corpus.grep(
        r'(TcpListener|TcpStream|UdpSocket|net\.Listen\(|net\.Dial|socket\.socket\(|net\.createServer|net\.createConnection|ServerSocket|asyncio\.start_server|open_connection\()',
        only_code=True,
    )
    if g['count'] >= 3 and not entities['routes']:
        score['network'] += 4 + min(4, g['count'] // 4)
        ev['network'].append(f'{g["count"]} raw socket/TCP usages, no HTTP routes')
    comp = sum(
        1
        for p in paths
        if re.search(
            r'(^|/)(lexer|scanner|tokenizer|parser|ast|codegen|compiler|interpreter|vm|bytecode|typecheck\w*|semantic)\.\w+$',
            p.lower(),
        )
    )
    if comp >= 2:
        score['compiler'] += 2 + 2 * comp
        ev['compiler'].append(f'{comp} lexer/parser/AST/codegen files')
    infra = sum(
        1 for p in paths if p.endswith(('.tf', '.hcl')) or re.search(r'(^|/)(helm|k8s|kubernetes|ansible|charts)/', p)
    )
    if infra >= 3:
        score['infra'] += 2 + infra // 3
        ev['infra'].append(f'{infra} infrastructure-as-code files')
    if any(p.endswith(('AndroidManifest.xml', 'Info.plist', 'pubspec.yaml')) for p in paths):
        score['mobile'] += 5
        ev['mobile'].append('mobile platform manifest')
    if any(p.endswith(('.ipynb',)) for p in paths):
        score['ml'] += 2
        ev['ml'].append('notebooks present')
    has_manifest = any(
        posixpath.basename(p) in ('setup.py', 'pyproject.toml', 'package.json', 'Cargo.toml', 'go.mod') for p in paths
    )
    strong = [d for d, s in score.items() if s >= 5]
    if has_manifest:
        score['library'] += 2 if strong else 5
        ev['library'].append('package manifest' + ('' if strong else ' with no dominant app framework'))
        if any(p.endswith(('__init__.py', 'lib.rs', 'index.ts', 'index.js')) and p.count('/') <= 2 for p in paths):
            score['library'] += 1
    out = []
    for d, s in score.most_common():
        if s <= 0 or d not in K.DOMAINS:
            continue
        out.append({'key': d, 'label': K.DOMAINS[d]['label'], 'score': s, 'evidence': ev[d][:6]})
    if not out:
        out = [{'key': 'library', 'label': K.DOMAINS['library']['label'], 'score': 1, 'evidence': ['fallback']}]
    return out, frameworks
