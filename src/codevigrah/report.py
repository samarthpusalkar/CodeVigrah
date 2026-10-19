"""Markdown report built from an analysis (no LLM needed); the LLM can add a narrative on top."""

import time


def md_report(a, narrative=''):
    s, m = a['stats'], a['meta']
    L = [
        f'# {m.get("name", "Repository")}: codebase report',
        '',
        f'_Source: {m.get("source", "")} · commit {m.get("commit", "?")} · generated {time.strftime("%Y-%m-%d %H:%M")}_',
        '',
        '## Brief',
        '',
        a['brief'],
        '',
    ]
    if narrative:
        L += ['## Architecture narrative (AI)', '', narrative.strip(), '']
    L += [
        '## At a glance',
        '',
        '| Metric | Value |',
        '|---|---|',
        f'| Code files | {s["code_files"]} |',
        f'| Lines of code | {s["loc"]:,} |',
        f'| Languages | {", ".join(f"{k} {v:,}" for k, v in list(s["langs"].items())[:5])} |',
        f'| Modules | {s["modules"]} |',
        f'| Internal import edges | {s["edges"]} |',
        f'| Import cycles | {s["cycles"]} |',
        f'| Test LOC / source LOC | {s["test_ratio"]} |',
    ]
    if a['git']:
        g = a['git']
        L += [
            f'| Commits sampled | {g["commits"]} over {g["span_days"]} days |',
            f'| Authors | {g["authors_total"]} (top author {int(g["top_author_share"] * 100)}%) |',
        ]
    L += ['', '## Domain', '']
    for d in a['domains'][:3]:
        L.append(f'- **{d["label"]}** (score {d["score"]}): {"; ".join(d["evidence"])}')
    d0 = a['domains'][0]['key']
    info = a['domain_info'].get(d0)
    if info:
        L += ['', f'**Mental model.** {info["model"]}', '']
    L += ['## Entry points', ''] + [f'- `{e["path"]}`: {e["why"]}' for e in a['entries'][:10]] + ['']
    L += [
        '## Architecture: modules by layer',
        '',
        'Level 0 modules depend on nothing internal (foundation); higher levels build on lower ones.',
        '',
        '| Module | Level | LOC | Fan-in | Fan-out | Key files |',
        '|---|---|---|---|---|---|',
    ]
    for mo in sorted(a['modules'], key=lambda x: (x['level'], -x['loc']))[:40]:
        L.append(
            f'| `{mo["id"]}`{" (cycle)" if mo["cyclic"] else ""} | {mo["level"]} | {mo["loc"]:,} | {mo["fanin"]} | {mo["fanout"]} | {", ".join("`" + p.split("/")[-1] + "`" for p in mo["top"][:3])} |'
        )
    L += ['', '## Design decisions and the costs they impose', '']
    for dc in a['decisions']:
        L += [
            f'### {dc["title"]}',
            f'- **Why:** {dc["why"]}',
            f'- **Cost you inherit:** {dc["cost"]}',
            f'- _Evidence: {"; ".join(dc["evidence"][:3])}_',
            '',
        ]
    ent = a['entities']
    if ent['routes']:
        L += (
            ['## Routes', '', '| Method | Path | File |', '|---|---|---|']
            + [f'| {r["method"]} | `{r["path"]}` | `{r["file"]}:{r["line"]}` |' for r in ent['routes'][:60]]
            + ['']
        )
    if ent['models']:
        L += (
            ['## Data models', '']
            + [f'- `{x["name"]}` ({x["kind"]}) in `{x["file"]}:{x["line"]}`' for x in ent['models'][:60]]
            + ['']
        )
    if ent['commands']:
        L += (
            ['## CLI surface', '']
            + [f'- `{x["name"]}` ({x["kind"]}) in `{x["file"]}:{x["line"]}`' for x in ent['commands'][:60]]
            + ['']
        )
    L += [
        '## Hotspots (where changes are riskiest)',
        '',
        '| File | Risk | Why | Fan-in | LOC |',
        '|---|---|---|---|---|',
    ]
    hot = sorted((f for f in a['files'] if f['code'] and f['role'] != 'test'), key=lambda f: -f['risk'])[:15]
    L += [f'| `{f["path"]}` | {f["risk"]} | {", ".join(f["risk_why"])} | {f["fanin"]} | {f["loc"]} |' for f in hot] + [
        ''
    ]
    L += ['## Shortcomings and why they are hard to patch', '']
    for p in a['probes']:
        if p['flagged']:
            L += (
                [f'### {p["title"]}', f'- {p["why"]}', f'- **Why it is hard to fix:** {p["hard"]}']
                + [f'  - `{e}`' for e in p['evidence'][:4]]
                + ['']
            )
    if info:
        L += ['## Hard problems in this domain', ''] + [f'- **{t}.** {x}' for t, x in info['hard']] + ['']
        L += ['## Questions to answer while reading', ''] + [f'- [ ] {q}' for q in info['questions']] + ['']
    if a['concepts']:
        L += ['## Concepts to learn from this repo', '']
        for c in a['concepts']:
            ex = ', '.join(f'`{h["path"]}:{h["line"]}`' for h in c['examples'][:3])
            L += [
                f'- **{c["title"]}** ({c["level"]}): {c["what"]} _Pitfall:_ {c["pitfalls"]}'
                + (f' See {ex}.' if ex else '')
            ]
        L.append('')
    if a['git'] and a['git']['coupling']:
        L += (
            ['## Hidden coupling (files that change together)', '']
            + [f'- `{c["a"]}` <-> `{c["b"]}`: {c["n"]} shared commits' for c in a['git']['coupling'][:12]]
            + ['']
        )
    L += ['## Suggested reading order', '']
    order = [e['path'] for e in a['entries'][:2]]
    order += [
        f['path']
        for f in sorted(
            (f for f in a['files'] if f['code'] and f['role'] != 'test'), key=lambda f: -(f['pr'] + f['fanin'])
        )[:8]
    ]
    for i, p in enumerate(dict.fromkeys(order), 1):
        L.append(f'{i}. `{p}`')
    return '\n'.join(L) + '\n'
