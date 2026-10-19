"""Read dependency manifests (package.json, pyproject.toml, go.mod, Cargo.toml, ...)."""

import json
import posixpath
import re


def collect_deps(files):
    deps, manifests = set(), []
    for f in files:
        name = posixpath.basename(f['path'])
        t = f.get('_text') or ''
        if not t or f['path'].count('/') > 3:
            continue
        if name in ('package.json', 'composer.json'):
            try:
                j = json.loads(t)
            except ValueError:
                continue
            manifests.append(f['path'])
            for k in ('dependencies', 'devDependencies', 'peerDependencies', 'require', 'require-dev'):
                deps.update(x.lower() for x in (j.get(k) or {}))
            if j.get('workspaces'):
                deps.add('__workspaces__')
        elif re.match(r'requirements.*\.txt$', name) or name == 'Pipfile':
            manifests.append(f['path'])
            for line in t.splitlines():
                m = re.match(r'\s*([A-Za-z][\w.\-]*)', line)
                if m and not line.strip().startswith(('#', '-')):
                    deps.add(m.group(1).lower().replace('_', '-'))
        elif name in ('pyproject.toml', 'setup.py', 'setup.cfg'):
            manifests.append(f['path'])
            for m in re.finditer(r'[\'"]([A-Za-z][A-Za-z0-9_.\-]+)\s*(?:\[[^\]]*\])?\s*(?:[<>=!~;,]|[\'"])', t):
                deps.add(m.group(1).lower().replace('_', '-'))
            for m in re.finditer(r'^([A-Za-z][\w\-]*)\s*=', t, re.M):
                deps.add(m.group(1).lower())
        elif name == 'go.mod':
            manifests.append(f['path'])
            for m in re.finditer(r'^\s*(?:require\s+)?([\w.\-]+(?:/[\w.\-]+)+)\s+v\d', t, re.M):
                segs = m.group(1).split('/')
                if re.fullmatch(r'v\d+', segs[-1]):
                    segs = segs[:-1]
                deps.add(segs[-1].lower())
                deps.add('/'.join(segs[-2:]).lower())
        elif name == 'Cargo.toml':
            manifests.append(f['path'])
            for m in re.finditer(r'^([A-Za-z][\w\-]*)\s*=', t, re.M):
                deps.add(m.group(1).lower())
            if '[workspace]' in t:
                deps.add('__workspaces__')
        elif name in ('pom.xml', 'build.gradle', 'build.gradle.kts'):
            manifests.append(f['path'])
            for m in re.finditer(r'<artifactId>([\w.\-]+)</artifactId>|[\'"][\w.\-]+:([\w.\-]+)(?::[^\'"]*)?[\'"]', t):
                deps.add((m.group(1) or m.group(2)).lower())
        elif name == 'Gemfile':
            manifests.append(f['path'])
            for m in re.finditer(r"""gem\s+['"]([\w\-]+)""", t):
                deps.add(m.group(1).lower())
        elif name == 'pubspec.yaml':
            manifests.append(f['path'])
            deps.add('flutter') if 'flutter' in t else None
        elif name == 'mix.exs':
            manifests.append(f['path'])
            for m in re.finditer(r'\{:(\w+),', t):
                deps.add(m.group(1).lower())
    return deps, manifests
