"""Graph algorithms on the file import graph: PageRank, Tarjan SCC (cycles), percentile ranks."""

from collections import defaultdict


def pagerank(n, edges, iters=40, d=0.85):
    out = defaultdict(list)
    for a, b in edges:
        out[a].append(b)
    pr = [1.0 / max(n, 1)] * n
    for _ in range(iters):
        nxt = [(1 - d) / n] * n
        dangling = sum(pr[i] for i in range(n) if not out[i])
        for i in range(n):
            if out[i]:
                share = d * pr[i] / len(out[i])
                for j in out[i]:
                    nxt[j] += share
        add = d * dangling / n
        pr = [x + add for x in nxt]
    return pr


def tarjan(n, edges):
    adj = defaultdict(list)
    for a, b in edges:
        adj[a].append(b)
    index, low, on, stack, comps = {}, {}, set(), [], []
    counter = 0
    for root in range(n):
        if root in index:
            continue
        work = [(root, 0)]
        while work:
            v, i = work.pop()
            if i == 0:
                index[v] = low[v] = counter
                counter += 1
                stack.append(v)
                on.add(v)
            recurse = False
            for k in range(i, len(adj[v])):
                w = adj[v][k]
                if w not in index:
                    work.append((v, k + 1))
                    work.append((w, 0))
                    recurse = True
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            if recurse:
                continue
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                comps.append(comp)
            if work:
                u = work[-1][0]
                low[u] = min(low[u], low[v])
    return comps


def pct_rank(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    r = [0.0] * len(values)
    n = max(len(values) - 1, 1)
    for rank, i in enumerate(order):
        r[i] = rank / n
    # ties -> same rank as first
    for k in range(1, len(order)):
        if values[order[k]] == values[order[k - 1]]:
            r[order[k]] = r[order[k - 1]]
    return r
