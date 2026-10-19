"""Evaluate the knowledge-base rules (design decisions, concepts, shortcoming probes) against a repo."""

import posixpath
import re
from collections import Counter

from .. import knowledge as K


class Corpus:
    """All file texts with a cached grep."""

    def __init__(self, files):
        self.files = files
        self._cache = {}

    def grep(self, pattern, flags=re.I | re.M, langs=None, excl_roles=None, limit=6, only_code=False):
        key = (pattern, flags, tuple(langs or ()), tuple(excl_roles or ()), only_code)
        if key in self._cache:
            return self._cache[key]
        rx = re.compile(pattern, flags)
        count, hits = 0, []
        for f in self.files:
            t = f.get('_text')
            if not t:
                continue
            if langs and f['lang'] not in langs:
                continue
            if excl_roles and f['role'] in excl_roles:
                continue
            if only_code and not f['code']:
                continue
            for m in rx.finditer(t):
                count += 1
                if len(hits) < limit:
                    line = t.count('\n', 0, m.start()) + 1
                    s = t.rfind('\n', 0, m.start()) + 1
                    e = t.find('\n', m.end())
                    hits.append({'path': f['path'], 'line': line, 'snippet': t[s : e if e > 0 else None].strip()[:160]})
                if count > 500:
                    break
        res = {'count': count, 'hits': hits}
        self._cache[key] = res
        return res


def _rule_matches(when, deps, corpus, files, langs_loc, domains):
    if 'nodep' in when and deps & set(when['nodep']):
        return None
    ev = []
    if 'dep' in when:
        hit = sorted(deps & set(when['dep']))
        if hit:
            ev.append('deps: ' + ', '.join(hit[:4]))
    if 'grep' in when:
        g = corpus.grep(when['grep'], excl_roles=['docs', 'test', 'migration', 'generated'])
        if g['count'] >= when.get('min', 1):
            ev.append(f'{g["count"]} code matches')
            ev.extend(f'{h["path"]}:{h["line"]}' for h in g['hits'][:3])
    if 'file' in when:
        fh = [f['path'] for f in files if re.search(when['file'], f['path'])]
        if fh:
            ev.append('files: ' + ', '.join(fh[:3]))
    if 'dirs' in when:
        dirs = {posixpath.dirname(f['path']) + '/' for f in files if f['code']}
        ok = all(any(re.search(rx, d) for d in dirs) for rx in when['dirs'])
        if ok:
            ev.append('directory layout matches')
    if 'langshare' in when:
        lang, share = when['langshare']
        tot = sum(langs_loc.values()) or 1
        if langs_loc.get(lang, 0) / tot >= share:
            ev.append(f'{lang} is {round(100 * langs_loc[lang] / tot)}% of code')
    if 'domain' in when:
        if any(d['key'] in when['domain'] for d in domains[:2]):
            ev.append('domain')
    return ev or None


def eval_decisions(deps, corpus, files, langs_loc, domains):
    out = []
    for r in K.DECISIONS:
        ev = _rule_matches(r['when'], deps, corpus, files, langs_loc, domains)
        if ev:
            out.append({'id': r['id'], 'title': r['title'], 'why': r['why'], 'cost': r['cost'], 'evidence': ev[:5]})
    return out


def eval_concepts(deps, corpus, files, langs_loc, domains):
    out = []
    for c in K.CONCEPTS:
        ev = _rule_matches(c['trigger'], deps, corpus, files, langs_loc, domains)
        if not ev:
            continue
        examples = []
        if 'grep' in c['trigger']:
            examples = corpus.grep(c['trigger']['grep'], excl_roles=['docs'], limit=5)['hits']
        out.append(
            {k: c[k] for k in ('id', 'title', 'level', 'what', 'why', 'pitfalls')}
            | {'examples': examples, 'evidence': ev[:3]}
        )
    return out


def eval_probes(corpus, files, domains, deps, entities):
    top = domains[0]['score'] if domains else 0
    keys = {d['key'] for d in domains[:3] if d['score'] >= max(3, 0.4 * top)} | {'all'}
    roles = Counter(f['role'] for f in files)
    out = []
    for p in K.PROBES:
        if not keys & set(p['domains']):
            continue
        flagged, evidence = False, []
        if p['kind'] == 'present':
            g = corpus.grep(p['pattern'], langs=p.get('langs'), excl_roles=p.get('excl_roles'), only_code=True)
            if g['count'] >= p.get('min', 1):
                flagged, evidence = (
                    True,
                    [f'{g["count"]} occurrences'] + [f'{h["path"]}:{h["line"]}  {h["snippet"]}' for h in g['hits']],
                )
        elif p['kind'] == 'absent':
            g = corpus.grep(p['pattern'], only_code=True)
            if g['count'] == 0:
                flagged, evidence = True, ['no matches in source code']
        else:
            if p['id'] == 'no-migrations':
                tables = [m for m in entities['models'] if m['kind'] == 'table']
                if tables and not roles.get('migration') and 'django' not in deps:
                    flagged, evidence = True, [f'{len(tables)} table models, 0 migration files']
            elif p['id'] == 'no-ts':
                js = sum(f['loc'] for f in files if f['lang'] == 'JavaScript')
                ts = sum(f['loc'] for f in files if f['lang'] == 'TypeScript')
                if js > 2000 and ts < js * 0.1:
                    flagged, evidence = True, [f'{js} JS LOC vs {ts} TS LOC']
            elif p['id'] == 'no-changelog':
                if not any(
                    re.search(r'(^|/)(changelog|changes|history|news)(\.\w+)?$', f['path'].lower()) for f in files
                ):
                    flagged, evidence = True, ['no CHANGELOG file']
        out.append(
            {
                'id': p['id'],
                'title': p['title'],
                'flagged': flagged,
                'why': p['why'],
                'hard': p['hard'],
                'evidence': evidence[:7],
                'domains': p['domains'],
            }
        )
    # structural probes
    return out
