"""Domain entities found in code: HTTP routes, data models, CLI commands, UI components."""

import posixpath
import re

ROUTE_RX = [
    ('py', re.compile(r'@\w+\.(route|get|post|put|delete|patch|api_route|websocket)\(\s*[\'"]([^\'"]*)[\'"]', re.I)),
    (
        'js',
        re.compile(
            r'\b(?:app|router|server|api|fastify|\w*[rR]outer|r)\.(get|post|put|delete|patch|all|options)\(\s*[\'"`]([^\'"`]+)[\'"`]'
        ),
    ),
    (
        'java',
        re.compile(r'@(Get|Post|Put|Delete|Patch|Request)Mapping\(\s*(?:value\s*=\s*|path\s*=\s*)?\{?\s*"([^"]*)"'),
    ),
    ('go', re.compile(r'\.(GET|POST|PUT|DELETE|PATCH|Get|Post|Put|Delete|Patch|HandleFunc|Handle)\(\s*"([^"]+)"')),
    ('django', re.compile(r'\b(path|re_path)\(\s*r?[\'"]([^\'"]*)[\'"]')),
    ('rails', re.compile(r'^\s*(get|post|put|patch|delete|resources|resource)\s+[\'":]([\w/:\-]+)', re.M)),
    (
        'rust',
        re.compile(
            r'#\[(get|post|put|delete|patch)\(\s*"([^"]+)"|\.route\(\s*"([^"]+)"\s*,\s*(get|post|put|delete|patch)'
        ),
    ),
]
LANG_ROUTE = {
    'Python': ['py', 'django'],
    'JavaScript': ['js'],
    'TypeScript': ['js'],
    'Java': ['java'],
    'Kotlin': ['java'],
    'Go': ['go'],
    'Ruby': ['rails'],
    'Rust': ['rust'],
}


def extract_entities(files):
    routes, models, commands, components = [], [], [], []
    for f in files:
        t = f.get('_text')
        if not t or f['role'] == 'test':
            continue
        lang, path = f['lang'], f['path']
        for key in LANG_ROUTE.get(lang, []):
            if key == 'django' and not path.endswith('urls.py'):
                continue
            if key == 'rails' and not path.endswith('routes.rb'):
                continue
            for m in dict(ROUTE_RX)[key].finditer(t):
                g = [x for x in m.groups() if x is not None]
                if key == 'rust' and m.group(3):
                    method, rpath = m.group(4), m.group(3)
                else:
                    method, rpath = g[0], g[1] if len(g) > 1 else ''
                if key == 'js' and not rpath.startswith('/') and rpath != '*':
                    continue
                if method.lower() in ('handlefunc', 'handle', 'route', 'path', 're_path', 'request', 'api_route'):
                    method = 'ANY'
                routes.append(
                    {'method': method.upper(), 'path': rpath, 'file': path, 'line': t.count('\n', 0, m.start()) + 1}
                )
        # file-based routes (Next/Nuxt/SvelteKit)
        m = re.match(
            r'^(?:src/)?(?:pages|app|routes)/(.+?)(?:/(?:page|route|index|\+page|\+server|\+page\.server))?\.(tsx?|jsx?|vue|svelte)$',
            path,
        )
        if m and lang in ('TypeScript', 'JavaScript', 'Vue', 'Svelte'):
            rp = '/' + re.sub(r'(^|/)(index|page|route|\+page|\+server)$', '', m.group(1))
            kind = (
                'API'
                if '/api/' in path or path.endswith(('route.ts', 'route.js', '+server.ts', '+server.js'))
                else 'PAGE'
            )
            routes.append({'method': kind, 'path': rp.rstrip('/') or '/', 'file': path, 'line': 1})
        # models
        if lang == 'Python':
            for m in re.finditer(r'^class\s+(\w+)\(([^)]*)\)', t, re.M):
                bases = m.group(2)
                if 'table=True' in bases or (
                    re.search(r'\b(Base|db\.Model|models\.Model|DeclarativeBase|Document|Model)\b', bases)
                    and 'SQLModel' not in bases
                ):
                    models.append(
                        {'name': m.group(1), 'kind': 'table', 'file': path, 'line': t.count('\n', 0, m.start()) + 1}
                    )
                elif (
                    re.search(r'\b(BaseModel|SQLModel|Schema|TypedDict)\b', bases)
                    or re.search(r'\w(Base|Create|Update|Public)$', bases.strip())
                    or 'dataclass' in t[max(0, m.start() - 40) : m.start()]
                ):
                    models.append(
                        {'name': m.group(1), 'kind': 'schema', 'file': path, 'line': t.count('\n', 0, m.start()) + 1}
                    )
        elif path.endswith('.prisma'):
            for m in re.finditer(r'^model\s+(\w+)\s*\{', t, re.M):
                models.append(
                    {'name': m.group(1), 'kind': 'table', 'file': path, 'line': t.count('\n', 0, m.start()) + 1}
                )
        elif lang == 'SQL':
            for m in re.finditer(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`"\[]?([\w.]+)', t, re.I):
                models.append(
                    {'name': m.group(1), 'kind': 'table', 'file': path, 'line': t.count('\n', 0, m.start()) + 1}
                )
        elif lang in ('TypeScript', 'JavaScript', 'Java', 'Kotlin'):
            for m in re.finditer(
                r'@(Entity|Table|Document)\b[^\n]*\n(?:\s*@[^\n]*\n)*\s*(?:export\s+)?(?:public\s+)?(?:data\s+)?class\s+(\w+)',
                t,
            ):
                models.append(
                    {'name': m.group(2), 'kind': 'table', 'file': path, 'line': t.count('\n', 0, m.start()) + 1}
                )
            for m in re.finditer(r'(?:mongoose\.)?model\(\s*[\'"](\w+)[\'"]|sequelize\.define\(\s*[\'"](\w+)', t):
                models.append(
                    {
                        'name': m.group(1) or m.group(2),
                        'kind': 'table',
                        'file': path,
                        'line': t.count('\n', 0, m.start()) + 1,
                    }
                )
            if lang == 'TypeScript' and f['role'] == 'model':
                for m in re.finditer(r'^export\s+(?:interface|type)\s+(\w+)', t, re.M):
                    models.append(
                        {'name': m.group(1), 'kind': 'schema', 'file': path, 'line': t.count('\n', 0, m.start()) + 1}
                    )
        elif lang == 'Go':
            for m in re.finditer(r'^type\s+(\w+)\s+struct\s*\{[^}]*(gorm|db:"|json:")', t, re.M | re.S):
                models.append(
                    {
                        'name': m.group(1),
                        'kind': 'table' if m.group(2) != 'json:"' else 'schema',
                        'file': path,
                        'line': t.count('\n', 0, m.start()) + 1,
                    }
                )
        elif lang == 'Rust':
            for m in re.finditer(
                r'#\[derive\([^)]*(Queryable|Insertable|FromRow|Serialize|Deserialize)[^)]*\)\]\s*(?:#\[[^\]]*\]\s*)*pub\s+struct\s+(\w+)',
                t,
            ):
                models.append(
                    {
                        'name': m.group(2),
                        'kind': 'table' if m.group(1) in ('Queryable', 'Insertable', 'FromRow') else 'schema',
                        'file': path,
                        'line': t.count('\n', 0, m.start()) + 1,
                    }
                )
        # commands
        if lang == 'Python':
            for m in re.finditer(r'@[\w.]*command\(([^)]*)\)\s*\n(?:\s*@[^\n]+\n)*\s*(?:async\s+)?def\s+(\w+)', t):
                nm = re.search(r'[\'"]([\w-]+)[\'"]', m.group(1))
                commands.append(
                    {
                        'name': nm.group(1) if nm else m.group(2).replace('_', '-'),
                        'kind': 'command',
                        'file': path,
                        'line': t.count('\n', 0, m.start()) + 1,
                    }
                )
            for m in re.finditer(r'add_parser\(\s*[\'"]([\w-]+)', t):
                commands.append(
                    {'name': m.group(1), 'kind': 'command', 'file': path, 'line': t.count('\n', 0, m.start()) + 1}
                )
            for m in re.finditer(r'(?:add_argument|click\.option|typer\.Option)\(\s*[\'"](--?[\w-]+)', t):
                commands.append(
                    {'name': m.group(1), 'kind': 'option', 'file': path, 'line': t.count('\n', 0, m.start()) + 1}
                )
        elif lang == 'Go':
            for m in re.finditer(r'Use:\s*"([^"]+)"', t):
                commands.append(
                    {
                        'name': m.group(1).split()[0],
                        'kind': 'command',
                        'file': path,
                        'line': t.count('\n', 0, m.start()) + 1,
                    }
                )
            for m in re.finditer(r'Flags\(\)\.\w+(?:P|Var|VarP)?\(\s*(?:&[\w.]+,\s*)?"([\w-]+)"', t):
                commands.append(
                    {'name': '--' + m.group(1), 'kind': 'option', 'file': path, 'line': t.count('\n', 0, m.start()) + 1}
                )
        elif lang in ('JavaScript', 'TypeScript'):
            for m in re.finditer(r'\.command\(\s*[\'"]([^\'"]+)[\'"]', t):
                commands.append(
                    {
                        'name': m.group(1).split()[0],
                        'kind': 'command',
                        'file': path,
                        'line': t.count('\n', 0, m.start()) + 1,
                    }
                )
            for m in re.finditer(r'\.option\(\s*[\'"](-[^\'"]+)[\'"]', t):
                commands.append(
                    {
                        'name': m.group(1).split(',')[-1].strip().split()[0],
                        'kind': 'option',
                        'file': path,
                        'line': t.count('\n', 0, m.start()) + 1,
                    }
                )
        elif lang == 'Rust':
            for m in re.finditer(r'#\[(?:arg|clap)\([^)]*long[^)]*\)\]\s*(?:pub\s+)?(\w+)', t):
                commands.append(
                    {
                        'name': '--' + m.group(1).replace('_', '-'),
                        'kind': 'option',
                        'file': path,
                        'line': t.count('\n', 0, m.start()) + 1,
                    }
                )
            for m in re.finditer(r'#\[derive\([^)]*Subcommand[^)]*\)\]\s*(?:pub\s+)?enum\s+(\w+)', t):
                commands.append(
                    {'name': m.group(1), 'kind': 'command', 'file': path, 'line': t.count('\n', 0, m.start()) + 1}
                )
        # components
        if lang in ('Vue', 'Svelte') or path.endswith(('.tsx', '.jsx')):
            base = posixpath.basename(path).rsplit('.', 1)[0]
            hooks = re.findall(r'(?:function|const)\s+(use[A-Z]\w*)', t)
            components.append(
                {
                    'name': base,
                    'file': path,
                    'loc': f['loc'],
                    'hooks': hooks[:5],
                    'uses_state': bool(re.search(r'useState|useReducer|ref\(|reactive\(|\$state|writable\(', t)),
                }
            )
    return {
        'routes': routes[:400],
        'models': models[:300],
        'commands': commands[:300],
        'components': sorted(components, key=lambda c: -c['loc'])[:300],
    }
