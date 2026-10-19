"""Walk a repository, read text files and classify each one (language, role, module).

Nothing is executed: files are only read, and binary or oversized files are skipped.
"""

import os
import posixpath
import re

SKIP_DIRS = {
    '.git',
    'node_modules',
    'vendor',
    'dist',
    'build',
    'out',
    'target',
    '__pycache__',
    '.venv',
    'venv',
    '.tox',
    '.mypy_cache',
    '.pytest_cache',
    '.next',
    '.nuxt',
    '.idea',
    '.vscode',
    'coverage',
    '.gradle',
    'bower_components',
    'site-packages',
    '.cache',
    '.turbo',
    '.svelte-kit',
    'Pods',
    'third_party',
    '_build',
    '.eggs',
    'htmlcov',
    '.ruff_cache',
    'storybook-static',
    '.terraform',
}
SKIP_FILES = {
    'package-lock.json',
    'yarn.lock',
    'pnpm-lock.yaml',
    'poetry.lock',
    'Cargo.lock',
    'go.sum',
    'composer.lock',
    'Gemfile.lock',
    'uv.lock',
    'Pipfile.lock',
    'bun.lockb',
}
CODE = {
    '.py': 'Python',
    '.pyi': 'Python',
    '.js': 'JavaScript',
    '.jsx': 'JavaScript',
    '.mjs': 'JavaScript',
    '.cjs': 'JavaScript',
    '.ts': 'TypeScript',
    '.tsx': 'TypeScript',
    '.mts': 'TypeScript',
    '.go': 'Go',
    '.rs': 'Rust',
    '.java': 'Java',
    '.kt': 'Kotlin',
    '.kts': 'Kotlin',
    '.scala': 'Scala',
    '.rb': 'Ruby',
    '.php': 'PHP',
    '.c': 'C',
    '.h': 'C',
    '.cc': 'C++',
    '.cpp': 'C++',
    '.cxx': 'C++',
    '.hpp': 'C++',
    '.hh': 'C++',
    '.cs': 'C#',
    '.swift': 'Swift',
    '.vue': 'Vue',
    '.svelte': 'Svelte',
    '.sql': 'SQL',
    '.sh': 'Shell',
    '.bash': 'Shell',
    '.lua': 'Lua',
    '.dart': 'Dart',
    '.ex': 'Elixir',
    '.exs': 'Elixir',
    '.erl': 'Erlang',
    '.hs': 'Haskell',
    '.ml': 'OCaml',
    '.clj': 'Clojure',
    '.zig': 'Zig',
    '.nim': 'Nim',
    '.r': 'R',
    '.jl': 'Julia',
    '.m': 'Objective-C',
    '.pl': 'Perl',
}
TEXT = {
    '.md',
    '.rst',
    '.txt',
    '.json',
    '.yml',
    '.yaml',
    '.toml',
    '.ini',
    '.cfg',
    '.conf',
    '.html',
    '.htm',
    '.css',
    '.scss',
    '.sass',
    '.less',
    '.prisma',
    '.proto',
    '.graphql',
    '.gql',
    '.xml',
    '.gradle',
    '.tf',
    '.hcl',
    '.mk',
    '.env',
    '.properties',
    '.lock',
    '.mod',
    '.work',
    '.dockerfile',
    '.tpl',
    '.j2',
    '.ejs',
    '.hbs',
    '.erb',
}
NAMED_TEXT = {
    'Dockerfile',
    'Makefile',
    'Gemfile',
    'Rakefile',
    'Procfile',
    'Jenkinsfile',
    'LICENSE',
    'Justfile',
    'CMakeLists.txt',
    'Vagrantfile',
    'go.mod',
    'go.work',
    '.gitignore',
    '.dockerignore',
    '.env.example',
}
MAX_FILES = 6000
MAX_BYTES = 400_000
MAX_TOTAL = 40_000_000
GENERIC_DIRS = {
    'src',
    'lib',
    'app',
    'source',
    'internal',
    'pkg',
    'packages',
    'apps',
    'cmd',
    'crates',
    'services',
    'modules',
    'libs',
    'projects',
    'components',
}


def _read(full, size):
    if size > MAX_BYTES:
        return None
    try:
        with open(full, 'rb') as fh:
            raw = fh.read()
    except OSError:
        return None
    if b'\x00' in raw[:4096]:
        return None
    return raw.decode('utf-8', errors='replace')


def role_of(path, lang, text):
    p = path.lower()
    name = posixpath.basename(p)
    parts = p.split('/')
    if re.search(r'(^|/)(tests?|__tests__|spec|specs|testing|e2e|cypress)/', p) or re.match(
        r'(test_.*\.py|.*_test\.(py|go|rb|exs?)|.*\.(test|spec)\.\w+|.*tests?\.(java|kt|cs|swift))$', name
    ):
        return 'test'
    if re.search(r'(^|/)(examples?|samples?|demos?|benchmarks?|benches|fixtures|playground|sandbox)/', p):
        return 'example'
    if re.search(r'(^|/)(migrations?|alembic|db/migrate|versions)/', p):
        return 'migration'
    if name.endswith(('.md', '.rst', '.txt')) or parts[0] in ('docs', 'doc', 'documentation') or name == 'license':
        return 'docs'
    if (
        p.startswith(('.github/', '.gitlab', '.circleci/'))
        or name in ('dockerfile', 'makefile', 'jenkinsfile', 'procfile', 'justfile', 'cmakelists.txt')
        or name.endswith(('.tf', '.hcl'))
        or re.match(r'(docker-)?compose.*\.ya?ml$', name)
        or parts[0] in ('deploy', 'k8s', 'helm', 'infra', 'terraform', 'ci', 'scripts')
    ):
        return 'ci'
    if name.endswith(('.prisma', '.sql', '.proto', '.graphql', '.gql')):
        return 'model'
    if (
        name.endswith(
            (
                '.json',
                '.yml',
                '.yaml',
                '.toml',
                '.ini',
                '.cfg',
                '.conf',
                '.env',
                '.properties',
                '.gradle',
                '.xml',
                '.lock',
                '.mod',
            )
        )
        or re.search(r'(^|/)(config|configs|settings|conf)(/|\.py$|\.ts$|\.js$)', p)
        or name.startswith(('.', 'setup.', 'tsconfig', 'vite.config', 'webpack.config', 'babel.config', 'jest.config'))
    ):
        return 'config'
    if (
        lang in ('Vue', 'Svelte')
        or name.endswith(
            ('.tsx', '.jsx', '.html', '.htm', '.css', '.scss', '.sass', '.less', '.ejs', '.hbs', '.erb', '.j2')
        )
        or re.search(r'(^|/)(components?|pages|views|templates|layouts|screens|widgets|ui|styles|public|static)/', p)
    ):
        if not re.search(r'(^|/)(views)\.py$', p):
            return 'ui'
    if re.search(r'(^|/)(routes?|routers?|controllers?|handlers?|endpoints?|api|resolvers?)(/|\.\w+$)', p) or name in (
        'urls.py',
        'views.py',
    ):
        return 'route'
    if re.search(r'(^|/)(models?|schemas?|entities|entity|domain|dto|types?)(/|\.\w+$)', p):
        return 'model'
    if re.search(r'(^|/)(cmd|cli|commands?|bin)(/|\.\w+$)', p) or name in ('__main__.py', 'main.go', 'main.rs'):
        return 'cli'
    if re.search(
        r'(^|/)(services?|usecases?|use_cases|core|domain|logic|business|managers?|repositories|repository|stores?)(/|\.\w+$)',
        p,
    ):
        return 'service'
    if re.search(r'(^|/)(utils?|helpers?|common|shared|tools|misc)(/|\.\w+$)', p):
        return 'util'
    if text and lang in CODE.values():
        if re.search(
            r'@\w+\.(route|get|post|put|delete|patch)\(|\b(app|router)\.(get|post|put|delete|patch)\(\s*[\'"`]/', text
        ):
            return 'route'
        if re.search(r'^class \w+\((\w+\.)?(Model|Base|SQLModel|DeclarativeBase|BaseModel)\)', text, re.M):
            return 'model'
    return 'logic' if lang in CODE.values() else 'other'


def module_of(path, depth_extra=0):
    parts = path.split('/')[:-1]
    if not parts:
        return '(root)'
    n = 2 if (parts[0] in GENERIC_DIRS and len(parts) > 1) else 1
    n += depth_extra
    return '/'.join(parts[:n])


def scan(root, log):
    files = []
    total = 0
    truncated = False
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in SKIP_DIRS
            and not d.endswith('.egg-info')
            and not (d.startswith('.') and d not in ('.github', '.circleci', '.gitlab'))
        )
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, '/')
        rel_dir = '' if rel_dir == '.' else rel_dir
        for fn in sorted(filenames):
            if fn in SKIP_FILES or fn.endswith(('.min.js', '.min.css', '.map', '.snap', '.d.ts.map')):
                continue
            ext = os.path.splitext(fn)[1].lower()
            if ext not in CODE and ext not in TEXT and fn not in NAMED_TEXT and not fn.startswith('Dockerfile'):
                continue
            full = os.path.join(dirpath, fn)
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if not os.path.isfile(full) or os.path.islink(full):
                continue
            if len(files) >= MAX_FILES:
                truncated = True
                break
            path = f'{rel_dir}/{fn}' if rel_dir else fn
            text = _read(full, st.st_size) if total < MAX_TOTAL else None
            if text is None and st.st_size <= MAX_BYTES and total < MAX_TOTAL:
                continue  # binary
            if text:
                total += len(text)
            lang = CODE.get(ext) or ('Dockerfile' if fn.startswith('Dockerfile') else ext.lstrip('.').upper() or fn)
            code = ext in CODE and ext not in ('.sql',)
            loc = text.count('\n') + (1 if text and not text.endswith('\n') else 0) if text else 0
            files.append({'path': path, 'lang': lang, 'code': code, 'loc': loc, 'size': st.st_size, '_text': text})
        if truncated:
            break
    log(f'scanned {len(files)} files ({total // 1024} KB of text){" [truncated]" if truncated else ""}')
    return files, truncated
