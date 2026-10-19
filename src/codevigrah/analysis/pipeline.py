"""The analysis pipeline: scan -> roles -> modules -> symbols -> imports -> graph -> git -> domain -> rules.

Produces one JSON-serialisable dict. No repository code is ever executed: Python is parsed with `ast`,
other languages with regular expressions.
"""

import json
import posixpath
import re
import time
from collections import Counter, defaultdict

from .. import knowledge as K
from .domains import detect_domains
from .entities import extract_entities
from .graph import pagerank, pct_rank, tarjan
from .history import git_history
from .imports import Resolver
from .manifests import collect_deps
from .rules import Corpus, eval_concepts, eval_decisions, eval_probes
from .scan import module_of, role_of, scan
from .symbols import BRANCH_RX, file_doc, generic_symbols, py_symbols, readme_parts

# Bump when the analysis output gains or changes fields; older saved analyses are then re-run automatically.
SCHEMA = 1


def analyze(root, meta, log=print):
    t0 = time.time()
    files, truncated = scan(root, log)
    for f in files:
        f['role'] = role_of(f['path'], f['lang'], f['_text'])
        head = (f['_text'] or '')[:600]
        if re.search(r'\.(gen|generated|pb|g)\.\w+$|_pb2\.py$|(^|/)generated/', f['path']) or re.search(
            r'(auto-?generated|do not edit|code generated .* do not edit|@generated)', head, re.I
        ):
            f['role'] = 'generated'
    # modules: split any module that is too big (by LOC share or file count) one directory level deeper
    code_files = [f for f in files if f['code']]
    total_code_loc = sum(f['loc'] for f in code_files) or 1
    extra = {}  # module prefix -> extra depth

    def assign(f):
        m = module_of(f['path'])
        while m in extra:
            nm = module_of(f['path'], extra[m])
            if nm == m:
                break
            m = nm
        return m

    for _ in range(4):
        for f in files:
            f['module'] = assign(f)
        loc, cnt = Counter(), Counter()
        for f in code_files:
            loc[f['module']] += f['loc']
            cnt[f['module']] += 1
        changed = False
        for m in list(loc):
            if m == '(root)' or m in extra:
                continue
            if loc[m] / total_code_loc > 0.25 or cnt[m] > 40:
                depth = (
                    len(m.split('/'))
                    - len(module_of(next(f['path'] for f in code_files if f['module'] == m)).split('/'))
                    + 1
                )
                children = {module_of(f['path'], depth) for f in code_files if f['module'] == m}
                if len(children) >= 2:
                    extra[m] = depth
                    changed = True
        if not changed:
            break
    for f in files:
        f['module'] = assign(f)
    # symbols + complexity
    for f in files:
        t = f['_text']
        f['sym'], f['cx'] = [], 0
        f['doc'] = file_doc(t, f['lang']) if t and f['code'] else ''
        if not t or not f['code']:
            continue
        if f['lang'] == 'Python':
            s, cx = py_symbols(t)
            if s is not None:
                f['sym'], f['cx'] = s, cx
                continue
        f['sym'] = generic_symbols(t, f['lang'] in ('JavaScript', 'TypeScript', 'Vue', 'Svelte'))
        f['cx'] = 1 + len(BRANCH_RX.findall(t))
    log('symbols and complexity done')
    # imports
    paths = [f['path'] for f in files]
    res = Resolver(paths)
    res.load_aliases(files)
    gomod = next((f for f in files if f['path'] == 'go.mod' and f['_text']), None)
    if gomod:
        m = re.search(r'^module\s+(\S+)', gomod['_text'], re.M)
        res.go_module = m.group(1) if m else None
    idx = {p: i for i, p in enumerate(paths)}
    edges = set()
    ext_counter = Counter()
    for f in files:
        f['ext'] = []
        if not f['code'] or not f['_text']:
            continue
        internal, ext = res.imports(f, f['_text'])
        for p in internal:
            if p in idx:
                edges.add((idx[f['path']], idx[p]))
        f['ext'] = sorted(ext)[:30]
        ext_counter.update(ext)
    edges = sorted(edges)
    log(f'import graph: {len(edges)} internal edges')
    n = len(files)
    fanin, fanout = Counter(), Counter()
    for a, b in edges:
        fanout[a] += 1
        fanin[b] += 1
    pr = pagerank(n, edges) if n else []
    comps = [c for c in tarjan(n, edges) if len(c) > 1]
    in_cycle = {i for c in comps for i in c}
    # tests mapping

    def stem(p):
        return re.sub(
            r'^(test_)|(_test|\.test|\.spec|_spec|tests?)$', '', posixpath.basename(p).rsplit('.', 1)[0].lower()
        )

    by_stem = defaultdict(list)
    for i, f in enumerate(files):
        if f['code'] and f['role'] != 'test':
            by_stem[stem(f['path'])].append(i)
    tested_by = defaultdict(set)
    for i, f in enumerate(files):
        if f['role'] == 'test':
            for j in by_stem.get(stem(f['path']), []):
                tested_by[j].add(i)
    for a, b in edges:
        if files[a]['role'] == 'test' and files[b]['role'] != 'test':
            tested_by[b].add(a)
    # git
    hist = git_history(root, paths)
    if hist:
        log(f'git history: {hist["commits"]} commits, {hist["authors_total"]} authors')
    # risk
    ci = [i for i, f in enumerate(files) if f['code'] and f['role'] not in ('test', 'example', 'generated')]
    if ci:
        r_fin = pct_rank([fanin[i] for i in ci])
        r_ch = pct_rank([(hist['churn'].get(files[i]['path'], 0) if hist else 0) for i in ci])
        r_cx = pct_rank([files[i]['cx'] for i in ci])
        r_loc = pct_rank([files[i]['loc'] for i in ci])
        for k, i in enumerate(ci):
            f = files[i]
            parts = [
                ('depended on by many files', 30 * r_fin[k]),
                ('changes often', 25 * r_ch[k] if hist else 0),
                ('branch-heavy (complex)', 20 * r_cx[k]),
                ('large', 10 * r_loc[k]),
                ('in an import cycle', 8 if i in in_cycle else 0),
                ('no tests found', 7 if not tested_by.get(i) else 0),
            ]
            f['risk'] = round(sum(v for _, v in parts))
            f['risk_why'] = [w for w, v in sorted(parts, key=lambda x: -x[1]) if v >= 5][:4]
    # assemble per-file output
    out_files = []
    for i, f in enumerate(files):
        o = {
            'path': f['path'],
            'lang': f['lang'],
            'role': f['role'],
            'module': f['module'],
            'loc': f['loc'],
            'code': f['code'],
            'cx': f['cx'],
            'sym': f['sym'][:60],
            'doc': f.get('doc', ''),
            'fanin': fanin[i],
            'fanout': fanout[i],
            'pr': round(pr[i] * n, 3) if n else 0,
            'cycle': i in in_cycle,
            'tests': sorted(files[j]['path'] for j in tested_by.get(i, ()))[:6],
            'ext': f['ext'],
            'risk': f.get('risk', 0),
            'risk_why': f.get('risk_why', []),
        }
        if hist:
            o['churn'] = hist['churn'].get(f['path'], 0)
            o['authors'] = len(hist['authors'].get(f['path'], ()))
            o['last'] = hist['last'].get(f['path'], 0)
        out_files.append(o)
    # modules
    mods = defaultdict(lambda: {'files': 0, 'loc': 0, 'code_files': 0, 'roles': Counter(), 'langs': Counter()})
    for f in out_files:
        m = mods[f['module']]
        m['files'] += 1
        m['loc'] += f['loc'] if f['code'] else 0
        m['code_files'] += f['code']
        m['roles'][f['role']] += 1
        if f['code']:
            m['langs'][f['lang']] += f['loc']
    medges = Counter()
    for a, b in edges:
        ma, mb = files[a]['module'], files[b]['module']
        if ma != mb:
            medges[(ma, mb)] += 1
    mnames = sorted(m for m in mods if mods[m]['code_files'])
    mi = {m: k for k, m in enumerate(mnames)}
    mcomps = tarjan(len(mnames), [(mi[a], mi[b]) for (a, b) in medges if a in mi and b in mi])
    comp_of = {}
    for k, c in enumerate(mcomps):
        for v in c:
            comp_of[v] = k
    cadj = defaultdict(set)
    for a, b in medges:
        if a in mi and b in mi and comp_of[mi[a]] != comp_of[mi[b]]:
            cadj[comp_of[mi[a]]].add(comp_of[mi[b]])
    level = {}

    def lvl(c):
        if c in level:
            return level[c]
        stack = [(c, iter(cadj[c]))]
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                stack.pop()
                level[node] = 1 + max((level[x] for x in cadj[node]), default=-1)
            elif nxt not in level:
                stack.append((nxt, iter(cadj[nxt])))
        return level[c]

    for c in range(len(mcomps)):
        lvl(c)
    modules = []
    for m in mnames:
        d = mods[m]
        mf = sorted((f for f in out_files if f['module'] == m and f['code']), key=lambda f: -(f['pr'] + f['fanin']))
        modules.append(
            {
                'id': m,
                'files': d['files'],
                'code_files': d['code_files'],
                'loc': d['loc'],
                'level': level.get(comp_of[mi[m]], 0),
                'cyclic': len(mcomps[comp_of[mi[m]]]) > 1,
                'roles': dict(d['roles'].most_common(5)),
                'lang': d['langs'].most_common(1)[0][0] if d['langs'] else '',
                'fanin': sum(w for (a, b), w in medges.items() if b == m),
                'fanout': sum(w for (a, b), w in medges.items() if a == m),
                'top': [f['path'] for f in mf[:5]],
                'churn': sum(f.get('churn', 0) for f in mf),
            }
        )
    # aggregate
    langs_loc = Counter()
    for f in out_files:
        if f['code']:
            langs_loc[f['lang']] += f['loc']
    corpus = Corpus(files)
    deps, manifests = collect_deps(files)
    entities = extract_entities(files)
    domains, frameworks = detect_domains(files, deps, corpus, entities, langs_loc)
    log(f'domains: {", ".join(d["key"] for d in domains[:3])}')
    decisions = eval_decisions(deps, corpus, files, langs_loc, domains)
    concepts = eval_concepts(deps, corpus, files, langs_loc, domains)
    probes = eval_probes(corpus, files, domains, deps, entities)
    # structural probes
    roles = Counter(f['role'] for f in out_files)
    tcode = sum(f['loc'] for f in out_files if f['role'] == 'test')
    scode = sum(f['loc'] for f in out_files if f['code'] and f['role'] != 'test') or 1
    probes.insert(
        0,
        {
            'id': 'tests',
            'title': 'Test coverage (by volume)',
            'flagged': tcode / scode < 0.15,
            'why': 'Without tests, every change must be verified by hand and refactors are risky.',
            'hard': 'Adding tests late needs seams (injectable dependencies) that the code may not have; the first tests often require refactoring.',
            'evidence': [f'test LOC / source LOC = {round(tcode / scode, 2)}', f'{roles.get("test", 0)} test files'],
            'domains': ['all'],
        },
    )
    if comps:
        probes.insert(
            1,
            {
                'id': 'cycles',
                'title': 'Import cycles',
                'flagged': True,
                'why': 'Modules in a cycle cannot be understood, tested or changed in isolation.',
                'hard': 'Breaking a cycle means introducing an interface or moving shared code, which changes many import sites at once.',
                'evidence': [
                    ' -> '.join(files[i]['path'] for i in c[:5]) + (' ...' if len(c) > 5 else '')
                    for c in sorted(comps, key=len, reverse=True)[:4]
                ],
                'domains': ['all'],
            },
        )
    god = [f for f in out_files if f['code'] and f['loc'] > 800 and f['fanin'] >= 5]
    if god:
        probes.insert(
            1,
            {
                'id': 'god-files',
                'title': 'Large, heavily-depended-on files',
                'flagged': True,
                'why': 'Big files that many others import concentrate risk: every change there has a wide blast radius.',
                'hard': 'Splitting them changes import paths across the codebase and needs careful behaviour-preserving moves.',
                'evidence': [
                    f'{f["path"]} ({f["loc"]} LOC, {f["fanin"]} dependents)'
                    for f in sorted(god, key=lambda f: -f['fanin'])[:5]
                ],
                'domains': ['all'],
            },
        )
    # entry points
    entries = []
    for f in out_files:
        p, t = f['path'], files[idx[f['path']]]['_text'] or ''
        name = posixpath.basename(p)
        if f['role'] in ('test', 'example') or not f['code']:
            continue
        if (
            name
            in (
                '__main__.py',
                'main.go',
                'main.rs',
                'manage.py',
                'wsgi.py',
                'asgi.py',
                'server.js',
                'server.ts',
                'app.py',
                'main.py',
                'index.js',
                'index.ts',
                'main.ts',
                'main.tsx',
                'main.js',
                'cli.py',
                'cli.js',
                'cli.ts',
                'Program.cs',
                'Main.java',
                'App.tsx',
                'App.vue',
            )
            and p.count('/') <= 3
        ):
            entries.append({'path': p, 'why': 'conventional entry file name'})
        elif (
            re.search(
                r'if __name__ == [\'"]__main__[\'"]|public static void main\(|^func main\(\)|^fn main\(\)', t, re.M
            )
            and f['fanin'] == 0
        ):
            entries.append({'path': p, 'why': 'defines main and nothing imports it'})
    pkg = next((f for f in files if f['path'] == 'package.json' and f['_text']), None)
    if pkg:
        try:
            j = json.loads(pkg['_text'])
            for k in ('main', 'module'):
                if isinstance(j.get(k), str):
                    entries.insert(0, {'path': j[k].lstrip('./'), 'why': f'package.json "{k}"'})
            b = j.get('bin')
            for v in b.values() if isinstance(b, dict) else [b] if isinstance(b, str) else []:
                entries.insert(0, {'path': v.lstrip('./'), 'why': 'package.json "bin"'})
            if j.get('scripts'):
                meta['scripts'] = {k: v for k, v in list(j['scripts'].items())[:20]}
        except ValueError:
            pass
    pyproj = next((f for f in files if f['path'] == 'pyproject.toml' and f['_text']), None)
    if pyproj:
        sec = re.search(r'\[(?:project\.scripts|tool\.poetry\.scripts)\]([^\[]*)', pyproj['_text'])
        if sec:
            for m in re.finditer(r'^\s*([\w-]+)\s*=\s*"([\w.]+):', sec.group(1), re.M):
                r = res._py_abs(m.group(2), 'x')
                entries.insert(0, {'path': r or m.group(2), 'why': f'console script "{m.group(1)}"'})
    seen = set()
    entries = [e for e in entries if not (e['path'] in seen or seen.add(e['path']))][:15]
    readme = next((f for f in files if re.match(r'readme(\.\w+)?$', f['path'].lower()) and f['_text']), None)
    stats = {
        'files': len(files),
        'code_files': len(code_files),
        'loc': sum(langs_loc.values()),
        'langs': dict(langs_loc.most_common()),
        'roles': dict(roles.most_common()),
        'edges': len(edges),
        'modules': len(modules),
        'cycles': len(comps),
        'test_ratio': round(tcode / scode, 2),
        'ext_imports': ext_counter.most_common(25),
    }
    analysis = {
        'meta': meta | {'analyzed_at': int(time.time()), 'seconds': round(time.time() - t0, 1), 'schema': SCHEMA},
        'stats': stats,
        'truncated': truncated,
        'domains': domains,
        'frameworks': frameworks,
        'deps': sorted(deps - {'__workspaces__'})[:400],
        'manifests': manifests,
        'entries': entries,
        'files': out_files,
        'edges': [list(e) for e in edges],
        'modules': modules,
        'module_edges': [{'s': a, 't': b, 'w': w} for (a, b), w in medges.most_common()],
        'cycles': [[files[i]['path'] for i in c] for c in sorted(comps, key=len, reverse=True)[:20]],
        'entities': entities,
        'decisions': decisions,
        'concepts': concepts,
        'probes': probes,
        'git': (
            {k: hist[k] for k in ('commits', 'authors_total', 'top_author_share', 'span_days', 'coupling', 'recent')}
            if hist
            else None
        ),
        'readme': (readme['_text'][:6000] if readme else ''),
        'domain_info': {d['key']: K.DOMAINS[d['key']] for d in domains[:3]},
        'recipes': [{k: r[k] for k in ('key', 'title', 'chain', 'notes', 'domains')} for r in K.RECIPES],
    }
    analysis['readme_intro'], analysis['readme_usage'] = readme_parts(analysis['readme'])
    analysis['brief'] = brief(analysis)
    log(f'analysis complete in {analysis["meta"]["seconds"]}s')
    return analysis


def brief(a):
    """Plain-language summary: what it is (from the README), what kind of code, where to start."""
    s = a['stats']
    name = a['meta'].get('name', 'This repository')
    langs = list(s['langs'])
    main_lang = langs[0] if langs else 'code'
    d = a['domains'][0]
    src = [f for f in a['files'] if f['code'] and f['role'] not in ('test', 'example', 'generated', 'ci')]
    src_loc = sum(f['loc'] for f in src)
    size = 'tiny' if src_loc < 1500 else 'small' if src_loc < 8000 else 'medium-sized' if src_loc < 40000 else 'large'
    parts = []
    if a.get('readme_intro'):
        parts.append(f'**{name}**, in its own words: _{a["readme_intro"]}_')
    else:
        parts.append(f'**{name}** has no README description, so this summary comes from the code alone.')
    kind = {
        'backend': 'backend service',
        'frontend': 'frontend app',
        'cli': 'command-line tool',
        'database': 'database engine',
        'compiler': 'compiler/interpreter',
        'ml': 'ML/data project',
        'library': 'library',
        'infra': 'infrastructure project',
        'network': 'networking tool',
        'mobile': 'mobile app',
        'desktop': 'desktop app',
        'game': 'game',
    }.get(d['key'], 'project')
    fw = [x for x in a['frameworks'] if x not in ('NumPy',)][:4]
    parts.append(
        f"In code terms it's a {size} {kind} written mostly in {main_lang} (about {src_loc:,} lines of source in {len(src)} files)"
        + (f', built on {", ".join(fw)}.' if fw else '.')
    )
    core = sorted(src, key=lambda f: -(f['fanin'] * 2 + f['pr']))[:3]
    if a['entries']:
        e = a['entries'][0]['path']
        others = ', '.join(f'`{f["path"]}`' for f in core if f['path'] != e)
        parts.append(
            f'Execution starts in `{e}`' + (f'; the pieces everything else leans on are {others}.' if core else '.')
        )
    elif core:
        central = ', '.join(f'`{f["path"]}`' for f in core)
        parts.append(f"There's no single entry point (typical for a library); the central pieces are {central}.")
    if a['git']:
        g = a['git']
        who = 'mostly one main author' if g['top_author_share'] > 0.5 else f'{g["authors_total"]} contributors'
        yrs = round(g['span_days'] / 365)
        span = (
            f'about {yrs} years'
            if yrs > 1
            else 'about a year'
            if yrs == 1
            else f'{max(1, round(g["span_days"] / 30))} months'
        )
        parts.append(f'The sampled history covers {span} of work by {who}.')
    return ' '.join(parts)
