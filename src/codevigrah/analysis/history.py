"""Git history: churn, authors, recency and co-change coupling."""

import os
import subprocess
from collections import Counter, defaultdict


def git_history(root, paths, max_commits=2000):
    try:
        out = subprocess.run(
            [
                'git',
                '-C',
                root,
                'log',
                '--no-merges',
                '--name-only',
                f'-n{max_commits}',
                '--pretty=format:@@%H|%at|%ae|%s',
            ],
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    commits = []
    cur = None
    for line in out.stdout.splitlines():
        if line.startswith('@@'):
            h, ts, ae, subj = (line[2:].split('|', 3) + ['', '', '', ''])[:4]
            cur = {'h': h[:10], 'ts': int(ts or 0), 'a': ae, 's': subj, 'files': []}
            commits.append(cur)
        elif line.strip() and cur is not None:
            cur['files'].append(line.strip())
    pathset = set(paths)
    churn, authors, last, first = Counter(), defaultdict(set), {}, {}
    pair = Counter()
    for c in commits:
        fs = [f for f in c['files'] if f in pathset]
        for f in fs:
            churn[f] += 1
            authors[f].add(c['a'])
            last.setdefault(f, c['ts'])
            first[f] = c['ts']
        if 1 < len(fs) <= 25:
            fs = sorted(fs)
            for i in range(len(fs)):
                for j in range(i + 1, len(fs)):
                    pair[(fs[i], fs[j])] += 1
    coupling = []
    for (a, b), n in pair.items():
        if n >= 3:
            coupling.append({'a': a, 'b': b, 'n': n, 'score': round(n / min(churn[a], churn[b]), 2)})
    coupling.sort(key=lambda x: (-x['score'] * min(x['n'], 10), -x['n']))
    all_auth = Counter(c['a'] for c in commits)
    recent = [{'h': c['h'], 'ts': c['ts'], 's': c['s'][:120], 'n': len(c['files'])} for c in commits[:40]]
    return {
        'commits': len(commits),
        'churn': churn,
        'authors': authors,
        'last': last,
        'first': first,
        'coupling': coupling[:300],
        'authors_total': len(all_auth),
        'top_author_share': round(all_auth.most_common(1)[0][1] / len(commits), 2) if commits else 0,
        'span_days': round((commits[0]['ts'] - commits[-1]['ts']) / 86400) if commits else 0,
        'recent': recent,
    }
