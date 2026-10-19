"""Resolve import statements to files inside the repository, per language."""

import ast
import json
import posixpath
import re
import sys
from collections import defaultdict

JS_IMPORT = re.compile(
    r"""(?:import\s+(?:[\w*{}\s,$]+\s+from\s+)?|export\s+(?:\*|\{[^}]*\})\s+from\s+|require\(\s*|import\(\s*)['"]([^'"]+)['"]"""
)
GO_IMPORT_BLOCK = re.compile(r'import\s*\(([^)]*)\)', re.S)
GO_IMPORT_ONE = re.compile(r'import\s+(?:\w+\s+)?"([^"]+)"')
JAVA_IMPORT = re.compile(r'^\s*import\s+(?:static\s+)?([\w.]+)(?:\.\*)?\s*;?', re.M)
C_INCLUDE = re.compile(r'^\s*#\s*include\s+"([^"]+)"', re.M)
RUST_MOD = re.compile(r'^\s*(?:pub(?:\([^)]*\))?\s+)?mod\s+(\w+)\s*;', re.M)
RUST_USE = re.compile(r'^\s*(?:pub\s+)?use\s+(crate|super|self)::([\w:]+)', re.M)
RUBY_REQ = re.compile(r"""^\s*require(_relative)?\s*\(?\s*['"]([^'"]+)['"]""", re.M)
JS_EXTS = ['.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.mts', '.vue', '.svelte', '.json']
STDLIB = set(getattr(sys, 'stdlib_module_names', ()))


class Resolver:
    def __init__(self, paths):
        self.paths = set(paths)
        self.py = defaultdict(set)
        self.suffix = defaultdict(set)
        for p in paths:
            if p.endswith('.py'):
                parts = p[:-3].split('/')
                if parts[-1] == '__init__':
                    parts = parts[:-1]
                for i in range(len(parts)):
                    self.py['.'.join(parts[i:])].add(p)
            noext = p.rsplit('.', 1)[0]
            segs = noext.split('/')
            for i in range(len(segs)):
                self.suffix['/'.join(segs[i:])].add(p)
            segs = p.split('/')
            for i in range(len(segs)):
                self.suffix['/'.join(segs[i:]) + '\0'].add(p)  # with extension
        self.go_module = None
        self.dir_files = defaultdict(list)
        for p in paths:
            self.dir_files[posixpath.dirname(p)].append(p)

    @staticmethod
    def _closest(cands, src):
        if not cands:
            return None
        if len(cands) == 1:
            return next(iter(cands))
        sd = src.split('/')

        def shared(c):
            cd, n = c.split('/'), 0
            while n < min(len(sd), len(cd)) and sd[n] == cd[n]:
                n += 1
            return n

        scored = sorted(((shared(c), -len(c), c) for c in cands), reverse=True)
        if scored[0][:2] == scored[1][:2]:
            return None  # genuinely ambiguous
        return scored[0][2]

    def python(self, src, text):
        out, ext = set(), set()
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError, RecursionError):
            return out, ext
        pkg = posixpath.dirname(src)
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    r = self._py_abs(a.name, src)
                    (out.add(r) if r else ext.add(a.name.split('.')[0]))
            elif isinstance(n, ast.ImportFrom):
                if n.level:
                    base = pkg
                    for _ in range(n.level - 1):
                        base = posixpath.dirname(base)
                    mod = (n.module or '').replace('.', '/')
                    basepath = posixpath.join(base, mod) if mod else base
                    hit = False
                    for a in n.names:
                        for c in (f'{basepath}/{a.name}.py', f'{basepath}/{a.name}/__init__.py'):
                            if c in self.paths:
                                out.add(c)
                                hit = True
                    if not hit or n.module:
                        for c in (f'{basepath}.py', f'{basepath}/__init__.py'):
                            if c.lstrip('/') in self.paths:
                                out.add(c.lstrip('/'))
                elif n.module:
                    got = False
                    for a in n.names:
                        r = self._py_abs(f'{n.module}.{a.name}', src, exact_tail=True)
                        if r:
                            out.add(r)
                            got = True
                    r = self._py_abs(n.module, src)
                    if r:
                        out.add(r)
                        got = True
                    if not got:
                        ext.add(n.module.split('.')[0])
        out.discard(src)
        return out, ext

    def _py_abs(self, dotted, src, exact_tail=False):
        if dotted.split('.')[0] in STDLIB:
            return None
        segs = dotted.split('.')
        rng = [len(segs)] if exact_tail else range(len(segs), 0, -1)
        for i in rng:
            r = self._closest(self.py.get('.'.join(segs[:i])), src)
            if r:
                return r
        return None

    def js(self, src, text):
        out, ext = set(), set()
        for m in JS_IMPORT.finditer(text):
            spec = m.group(1)
            if spec.startswith('.'):
                base = posixpath.normpath(posixpath.join(posixpath.dirname(src), spec))
                r = self._js_try(base)
            elif self._alias(src, spec) is not False:
                r = self._alias(src, spec)
            elif spec.startswith(('@/', '~/', '#/', '$lib/')):
                rest = spec.split('/', 1)[1]
                root = self._pkg_root(src)
                pre = f'{root}/' if root else ''
                r = (
                    self._js_try(f'{pre}src/{rest}')
                    or self._js_try(f'{pre}{rest}')
                    or (self._js_try(f'{pre}src/lib/{rest}') if spec.startswith('$lib') else None)
                )
            else:
                name = '/'.join(spec.split('/')[:2]) if spec.startswith('@') else spec.split('/')[0]
                if name.startswith('node:'):
                    continue
                ext.add(name)
                continue
            if r and r != src:
                out.add(r)
        return out, ext

    def load_aliases(self, files):
        """tsconfig/jsconfig compilerOptions.paths, keyed by the directory holding the config."""
        self.aliases = {}
        self.pkg_roots = {
            posixpath.dirname(f['path']) for f in files if posixpath.basename(f['path']) == 'package.json'
        }
        self.crates = {}
        for f in files:
            if posixpath.basename(f['path']) == 'Cargo.toml' and f.get('_text'):
                d = posixpath.dirname(f['path'])
                src = posixpath.join(d, 'src') if d else 'src'
                for sec in ('package', 'lib'):
                    m = re.search(r'^\[' + sec + r'\][^\[]*?^name\s*=\s*"([^"]+)"', f['_text'], re.M | re.S)
                    if m:
                        self.crates[m.group(1).replace('-', '_')] = src
        for f in files:
            if not re.match(r'(ts|js)config(\.\w+)?\.json$', posixpath.basename(f['path'])) or not f.get('_text'):
                continue
            txt = re.sub(r'(?<![:"\w])//[^\n]*|/\*.*?\*/', '', f['_text'], flags=re.S)
            txt = re.sub(r',(\s*[}\]])', r'\1', txt)
            try:
                co = json.loads(txt).get('compilerOptions') or {}
            except ValueError:
                continue
            d = posixpath.dirname(f['path'])
            base = posixpath.normpath(posixpath.join(d, co.get('baseUrl', '.')))
            for k, targets in (co.get('paths') or {}).items():
                pre = k.rstrip('*')
                outs = [
                    posixpath.normpath(posixpath.join(base, t.rstrip('*'))).lstrip('./') if t.rstrip('*') else base
                    for t in targets
                ]
                self.aliases.setdefault(d, []).append((pre, outs))

    def _pkg_root(self, src):
        d = posixpath.dirname(src)
        while d:
            if d in getattr(self, 'pkg_roots', ()):
                return d
            d = posixpath.dirname(d)
        return ''

    def _alias(self, src, spec):
        d = posixpath.dirname(src)
        while True:
            for pre, outs in getattr(self, 'aliases', {}).get(d, []):
                if pre and spec.startswith(pre):
                    rest = spec[len(pre) :]
                    for o in outs:
                        o = '' if o in ('.', '') else o
                        r = self._js_try(posixpath.join(o, rest) if o else rest)
                        if r:
                            return r
                    return None
            if not d:
                return False
            d = posixpath.dirname(d)

    def _js_try(self, base):
        cands = [base] + [base + e for e in JS_EXTS] + [f'{base}/index{e}' for e in JS_EXTS]
        if base.endswith(('.js', '.jsx', '.mjs')):
            stem = base.rsplit('.', 1)[0]
            cands += [stem + e for e in ('.ts', '.tsx', '.mts')]
        for c in cands:
            if c in self.paths:
                return c
        return None

    def go(self, src, text):
        out, ext = set(), set()
        specs = []
        for b in GO_IMPORT_BLOCK.findall(text):
            specs += re.findall(r'"([^"]+)"', b)
        specs += GO_IMPORT_ONE.findall(text)
        for s in specs:
            if self.go_module and s.startswith(self.go_module):
                d = s[len(self.go_module) :].strip('/')
                files = [f for f in self.dir_files.get(d, []) if f.endswith('.go') and not f.endswith('_test.go')]
                out.update(files[:6])
            elif '.' in s.split('/')[0]:
                last = s.rstrip('/').split('/')
                if re.fullmatch(r'v\d+', last[-1]) and len(last) > 1:
                    last = last[:-1]
                ext.add(last[-1])
        out.discard(src)
        return out, ext

    def java(self, src, text):
        out, ext = set(), set()
        for imp in JAVA_IMPORT.findall(text):
            rel = imp.replace('.', '/')
            r = self._closest(self.suffix.get(rel), src)
            if r:
                out.add(r)
            else:
                ext.add('.'.join(imp.split('.')[:2]))
        out.discard(src)
        return out, ext

    def c(self, src, text):
        out = set()
        for inc in C_INCLUDE.findall(text):
            rel = posixpath.normpath(posixpath.join(posixpath.dirname(src), inc))
            if rel in self.paths:
                out.add(rel)
            else:
                r = self._closest(self.suffix.get(inc + '\0'), src)
                if r:
                    out.add(r)
        out.discard(src)
        return out, set()

    def rust(self, src, text):
        out, ext = set(), set()
        d = posixpath.dirname(src)
        stem = posixpath.basename(src)[:-3]
        mdir = d if stem in ('mod', 'lib', 'main') else posixpath.join(d, stem)
        for m in RUST_MOD.findall(text):
            for c in (f'{mdir}/{m}.rs', f'{mdir}/{m}/mod.rs'):
                if c.lstrip('/') in self.paths:
                    out.add(c.lstrip('/'))
        root = d
        while root and not any(posixpath.join(root, x) in self.paths for x in ('lib.rs', 'main.rs')):
            root = posixpath.dirname(root)
        uses = RUST_USE.findall(text)
        crate_names = getattr(self, 'crates', {})
        for m in re.finditer(r'^\s*(?:pub\s+)?use\s+(\w+)::(\{[^;]*\}|[\w:]+)', text, re.M):
            if m.group(1) in crate_names:
                for part in re.findall(r'\w+(?:::\w+)*', m.group(2)):
                    uses.append(('@' + m.group(1), part))
        for kind, path in uses:
            segs = [s for s in path.split('::') if s and s[0].islower()]
            if kind.startswith('@'):
                base = crate_names[kind[1:]]
            else:
                base = root if kind == 'crate' else (posixpath.dirname(mdir) if kind == 'super' else mdir)
            for i in range(len(segs), 0, -1):
                p = posixpath.join(base, *segs[:i])
                hit = next((c for c in (p + '.rs', p + '/mod.rs') if c.lstrip('/') in self.paths), None)
                if hit:
                    out.add(hit.lstrip('/'))
                    break
        for m in re.findall(r'^\s*use\s+(\w+)::', text, re.M):
            if m not in ('crate', 'super', 'self', 'std', 'core', 'alloc') and m not in crate_names:
                ext.add(m)
        out.discard(src)
        return out, ext

    def ruby(self, src, text):
        out, ext = set(), set()
        for rel, spec in RUBY_REQ.findall(text):
            if rel:
                c = posixpath.normpath(posixpath.join(posixpath.dirname(src), spec))
                c = c if c.endswith('.rb') else c + '.rb'
                if c in self.paths:
                    out.add(c)
            else:
                r = self._closest(self.suffix.get(spec), src)
                (out.add(r) if r else ext.add(spec.split('/')[0]))
        out.discard(src)
        return out, ext

    def imports(self, f, text):
        lang = f['lang']
        if lang == 'Python':
            return self.python(f['path'], text)
        if lang in ('JavaScript', 'TypeScript', 'Vue', 'Svelte'):
            return self.js(f['path'], text)
        if lang == 'Go':
            return self.go(f['path'], text)
        if lang in ('Java', 'Kotlin', 'Scala'):
            return self.java(f['path'], text)
        if lang in ('C', 'C++', 'Objective-C'):
            return self.c(f['path'], text)
        if lang == 'Rust':
            return self.rust(f['path'], text)
        if lang == 'Ruby':
            return self.ruby(f['path'], text)
        return set(), set()
