"""BM25 retrieval over paths/symbols/content + graph expansion for change localisation."""

import math
import os
import re
from collections import Counter, defaultdict

from . import knowledge as K

STOP = set(
    """a an the and or of to in on for with without from by is are be been was were it its this that these those as at
into not no do does did can could should would will shall may might must when where which who whom what why how than then
there here so if else get set use using used make new add adds added fix fixes fixed support supports issue feature
want need like also just more most some any all each every one two i we you they he she our your their my me us them
file files code repo should able allow allows instead currently way work works working""".split()
)


def split_ident(s):
    s = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', s)
    s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', s)
    return [t.lower() for t in re.findall(r'[A-Za-z][A-Za-z0-9]*', s)]


def stem(t):
    for suf in ('ization', 'ations', 'ation', 'ments', 'ment', 'ingly', 'ings', 'ing', 'ies', 'ers', 'ed', 'es', 's'):
        if t.endswith(suf) and len(t) - len(suf) >= 3:
            return t[: -len(suf)] + ('y' if suf == 'ies' else '')
    return t


def tokens(s):
    return [stem(t) for t in split_ident(s) if len(t) > 1 and t not in STOP]


class Index:
    def __init__(self, analysis, root):
        self.a = analysis
        self.root = root
        self.files = analysis['files']
        self.pos = {f['path']: i for i, f in enumerate(self.files)}
        self.tf = []
        self.df = Counter()
        self.lens = []
        self.path_tok = []
        self.sym_tok = []
        for f in self.files:
            pt = Counter(tokens(f['path']))
            st = Counter(t for s in f['sym'] for t in tokens(s[0]))
            ct = Counter()
            if f['code'] or f['role'] in ('docs', 'config', 'model', 'ui'):
                txt = self.read(f['path'], 120_000)
                if txt:
                    ct = Counter(tokens(txt))
            tf = Counter()
            for t, c in pt.items():
                tf[t] += 4 * c
            for t, c in st.items():
                tf[t] += 2 * min(c, 5)
            for t, c in ct.items():
                tf[t] += min(c, 12)
            self.tf.append(tf)
            self.path_tok.append(pt)
            self.sym_tok.append(st)
            self.lens.append(sum(tf.values()) or 1)
            self.df.update(tf.keys())
        self.avg = sum(self.lens) / max(len(self.lens), 1)
        ent = analysis['entities']
        self.nouns = (
            {t for m in ent['models'] for t in tokens(m['name'])}
            | {t for r in ent['routes'] for t in tokens(r['path'])}
            | {t for c in ent['commands'] if c['kind'] == 'command' for t in tokens(c['name'])}
        )
        self.nouns -= {'base', 'create', 'update', 'public', 'id', 'api', 'me'}
        self.n = len(self.files)
        self.out = defaultdict(set)
        self.inc = defaultdict(set)
        for a, b in analysis['edges']:
            self.out[a].add(b)
            self.inc[b].add(a)
        self.co = defaultdict(list)
        for c in (analysis.get('git') or {}).get('coupling', []):
            self.co[c['a']].append((c['b'], c['score'], c['n']))
            self.co[c['b']].append((c['a'], c['score'], c['n']))

    def read(self, path, limit=200_000):
        full = os.path.realpath(os.path.join(self.root, path))
        if not full.startswith(os.path.realpath(self.root) + os.sep):
            return None
        try:
            with open(full, 'rb') as fh:
                raw = fh.read(limit)
        except OSError:
            return None
        if b'\x00' in raw[:4096]:
            return None
        return raw.decode('utf-8', errors='replace')

    def search(self, query, k=25, roles=None):
        q = Counter(tokens(query))
        # quoted identifiers / paths the user typed literally get a boost
        for lit in re.findall(r'[\w./-]*[._/][\w./-]+|`([^`]+)`', query):
            if lit:
                q.update({t: 2 for t in tokens(lit)})
        for t in q:
            if t in self.nouns:
                q[t] += 2  # domain entity (model/route/command name) — the thing the issue is about
        scores = []
        idfs = {t: math.log(1 + (self.n - self.df[t] + 0.5) / (self.df[t] + 0.5)) for t in q}
        idf_total = sum(idfs.values()) or 1
        for i, tf in enumerate(self.tf):
            f = self.files[i]
            if roles and f['role'] not in roles:
                continue
            s, why, covered = 0.0, [], 0.0
            for t, qc in q.items():
                c = tf.get(t)
                if not c:
                    continue
                idf = idfs[t]
                covered += idf
                s += qc * idf * (c * 2.2) / (c + 1.2 * (0.25 + 0.75 * self.lens[i] / self.avg))
                if self.path_tok[i].get(t):
                    s += qc * idf * 1.5  # a concept named in the path is strong evidence of ownership
                if self.path_tok[i].get(t):
                    why.append(f'path:{t}')
                elif self.sym_tok[i].get(t):
                    why.append(f'symbol:{t}')
            if s > 0:
                s *= 0.35 + 0.65 * covered / idf_total  # favour files that match more of the query's rare terms
                if f['role'] == 'test':
                    s *= 0.6
                elif f['role'] in ('docs', 'other', 'generated', 'migration', 'example'):
                    s *= 0.5
                s *= 1 + 0.08 * math.log1p(f['fanin'])
                scores.append((s, i, why))
        scores.sort(reverse=True)
        return scores[:k]

    def matched_symbols(self, i, query, limit=6):
        q = set(tokens(query))
        out = []
        for name, kind, line in self.files[i]['sym']:
            if q & set(tokens(name)):
                out.append({'name': name, 'kind': kind, 'line': line})
        return out[:limit]

    # ------------------------------------------------------------------ change localisation
    def locate(self, issue, k=8):
        hits = self.search(issue, k=40)
        recipe = pick_recipe(issue, [d['key'] for d in self.a['domains'][:2]])
        primary = []
        for s, i, why in hits:
            f = self.files[i]
            if f['role'] in ('test', 'docs', 'other', 'example') or len(primary) >= k:
                continue
            primary.append(
                {
                    'path': f['path'],
                    'score': round(s, 2),
                    'role': f['role'],
                    'module': f['module'],
                    'why': sorted(set(why))[:6],
                    'symbols': self.matched_symbols(i, issue),
                    'fanin': f['fanin'],
                    'risk': f['risk'],
                    'risk_why': f['risk_why'],
                    'tests': f['tests'],
                    'loc': f['loc'],
                }
            )
        top = primary[0]['score'] if primary else 1
        for p in primary:
            p['confidence'] = round(min(1.0, p['score'] / top), 2)
        seeds = [self.pos[p['path']] for p in primary[:4]]
        seedset = set(self.pos[p['path']] for p in primary)
        ripple = {}
        for i in seeds:
            for j in self.inc[i]:
                if j in seedset or self.files[j]['role'] == 'test':
                    continue
                r = ripple.setdefault(
                    j, {'path': self.files[j]['path'], 'reasons': [], 'fanin': self.files[j]['fanin']}
                )
                r['reasons'].append(f'imports {self.files[i]["path"]}')
            for other, _score, n in self.co.get(self.files[i]['path'], [])[:6]:
                j = self.pos.get(other)
                if j is None or j in seedset:
                    continue
                r = ripple.setdefault(j, {'path': other, 'reasons': [], 'fanin': self.files[j]['fanin']})
                r['reasons'].append(f'changed together with {self.files[i]["path"]} in {n} commits')
        co_tests = [r['path'] for r in ripple.values() if self.files[self.pos[r['path']]]['role'] == 'test']
        ripple = sorted(
            (r for r in ripple.values() if self.files[self.pos[r['path']]]['role'] not in ('test', 'docs')),
            key=lambda r: (-len(r['reasons']), -r['fanin']),
        )[:12]
        tests = []
        for p in primary:
            tests += p['tests']
        test_hits = [self.files[i]['path'] for s, i, w in hits if self.files[i]['role'] == 'test']
        tests = list(dict.fromkeys(tests + co_tests + test_hits))[:8]
        # role chain -> best file per role
        chain = []
        role_hits = defaultdict(list)
        for _s, i, _why in hits:
            role_hits[self.files[i]['role']].append(self.files[i]['path'])
        for role in recipe['chain']:
            cands = role_hits.get(role, [])[:3]
            if not cands and role != 'test':
                rh = self.search(issue, k=3, roles=[role])
                cands = [self.files[i]['path'] for _, i, _ in rh]
            if role == 'test':
                cands = tests[:3]
            if role == 'migration':
                migs = [
                    f
                    for f in self.files
                    if f['role'] == 'migration' and f['code'] and re.search(r'\d', f['path'].rsplit('/', 1)[-1])
                ]
                if migs:
                    latest = max(migs, key=lambda f: f.get('last', 0) or 0)
                    cands = [
                        f'(new migration in {latest["path"].rsplit("/", 1)[0]}/ — model it on {latest["path"].rsplit("/", 1)[-1]})'
                    ]
                else:
                    cands = []
            chain.append({'role': role, 'files': cands})
        hints = []
        gen = [p['path'] for p in primary if p['role'] == 'generated'] + [
            r['path'] for r in ripple if self.files[self.pos[r['path']]]['role'] == 'generated'
        ]
        if gen:
            hints.append(
                f'`{gen[0]}` is generated code: change its source (schema/spec/generator) and regenerate rather than editing it by hand.'
            )
        for p in primary[:3]:
            if p['fanin'] >= 8:
                hints.append(
                    f'`{p["path"]}` has {p["fanin"]} dependents: change its interface carefully, or add new behaviour beside it.'
                )
            if not p['tests']:
                hints.append(
                    f'`{p["path"]}` has no associated tests: write a characterisation test before changing it.'
                )
            f = self.files[self.pos[p['path']]]
            if f['cycle']:
                hints.append(
                    f'`{p["path"]}` is in an import cycle: edits may require touching the other files in the cycle.'
                )
        return {
            'recipe': {k2: recipe[k2] for k2 in ('key', 'title', 'chain', 'notes')},
            'primary': primary,
            'ripple': ripple,
            'tests': tests,
            'chain': chain,
            'hints': hints[:6],
        }

    # ------------------------------------------------------------------ LLM context
    def repo_map(self, budget=9000):
        """Aider-style map: most central files with their top-level symbols."""
        files = sorted(
            (f for f in self.files if f['code'] and f['role'] != 'test'), key=lambda f: -(f['pr'] + 0.5 * f['fanin'])
        )
        lines, used = [], 0
        for f in files:
            syms = ', '.join(s[0] for s in f['sym'] if s[1] != 'method')[:220]
            line = f'{f["path"]} [{f["role"]}, {f["loc"]} LOC, fan-in {f["fanin"]}]' + (f': {syms}' if syms else '')
            if used + len(line) > budget:
                break
            lines.append(line)
            used += len(line)
        return '\n'.join(lines)

    def snippets(self, query, k=6, per=2400):
        out = []
        for _s, i, _why in self.search(query, k=k):
            f = self.files[i]
            txt = self.read(f['path']) or ''
            if not txt:
                continue
            q = set(tokens(query))
            lines = txt.splitlines()
            best, bl = 0, 0
            for li in range(0, len(lines), 10):
                win = ' '.join(lines[li : li + 40])
                sc = len(q & set(tokens(win)))
                if sc > bl:
                    best, bl = li, sc
            start = max(0, best - 5)
            chunk = '\n'.join(f'{start + n + 1:5} {l}' for n, l in enumerate(lines[start : start + 70]))
            out.append({'path': f['path'], 'start': start + 1, 'text': chunk[:per]})
        return out

    def overview_text(self):
        a = self.a
        parts = [
            a['brief'].replace('**', ''),
            'Domains: '
            + '; '.join(f'{d["label"]} (score {d["score"]}: {", ".join(d["evidence"][:3])})' for d in a['domains'][:3]),
            'Frameworks: ' + ', '.join(a['frameworks'][:20]),
            'Entry points: ' + ', '.join(e['path'] for e in a['entries'][:8]),
            'Modules (level 0 = foundation): '
            + '; '.join(
                f'{m["id"]} L{m["level"]} {m["loc"]}LOC' for m in sorted(a['modules'], key=lambda m: -m['loc'])[:25]
            ),
            'Design decisions detected: ' + '; '.join(d['title'] for d in a['decisions']),
            'Flagged shortcomings: ' + '; '.join(p['title'] for p in a['probes'] if p['flagged']),
        ]
        ent = a['entities']
        if ent['routes']:
            parts.append('Routes: ' + '; '.join(f'{r["method"]} {r["path"]} ({r["file"]})' for r in ent['routes'][:40]))
        if ent['models']:
            parts.append('Models: ' + '; '.join(f'{m["name"]} ({m["file"]})' for m in ent['models'][:40]))
        if ent['commands']:
            parts.append('CLI: ' + '; '.join(f'{c["name"]} ({c["file"]})' for c in ent['commands'][:40]))
        return '\n'.join(parts)

    def llm_context(self, question, extra_paths=(), k=5):
        """Context packed for an AI prompt: overview, repo map, retrieved excerpts and pinned files.

        Returns (markdown text, list of source paths used)."""
        parts = [
            '## Repository overview',
            self.overview_text(),
            '',
            '## Repo map (most central files and their symbols)',
            self.repo_map(),
        ]
        snips = self.snippets(question, k=k)
        for p in extra_paths:
            t = self.read(p, 30000)
            if t:
                numbered = '\n'.join(f'{n + 1:5} {line}' for n, line in enumerate(t.splitlines()[:400]))
                snips.insert(0, {'path': p, 'start': 1, 'text': numbered[:14000]})
        parts.append('\n## Relevant source excerpts')
        for s in snips:
            parts.append(f'### {s["path"]} (from line {s["start"]})\n```\n{s["text"]}\n```')
        return '\n'.join(parts), [s['path'] for s in snips]


def pick_recipe(issue, domains):
    text = issue.lower()
    best, bs = K.RECIPES[-1], 0
    for r in K.RECIPES[:-1]:
        n = len(re.findall(r['trigger'], text))
        if not n:
            continue
        n += 3 if domains and domains[0] in r['domains'] else 1.5 if set(r['domains']) & set(domains) else 0
        if n > bs:
            best, bs = r, n
    return best
