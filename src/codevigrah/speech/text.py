"""Turn written Markdown into text that sounds right when spoken (no AI needed).

The page and the voice share one coordinate system: the **source line** where each block starts. ``markdown.js``
writes it into the page as ``data-ln``, and :func:`blocks` reports the same number, so whatever is spoken can
highlight the paragraph it came from, even when an AI has rewritten the words.
"""

from __future__ import annotations

import re

LIST = re.compile(r'^\s*([-*]|\d+\.)\s+')
BLOCK_START = re.compile(r'^(#{1,4}\s|```|\s*\||\s*>|\s*([-*]|\d+\.)\s+)')

# fmt: off
# How developers say file extensions. Anything else short and vowel-less is spelled out letter by letter.
EXTENSIONS = {
    'py': 'pie', 'js': 'J S', 'ts': 'T S', 'jsx': 'J S X', 'tsx': 'T S X', 'rs': 'R S', 'go': 'go', 'rb': 'R B',
    'md': 'M D', 'json': 'Jason', 'yaml': 'yammel', 'yml': 'yammel', 'toml': 'tom-ul', 'html': 'H T M L',
    'css': 'C S S', 'sh': 'S H', 'txt': 'text', 'sql': 'S Q L', 'cpp': 'C P P', 'hpp': 'H P P', 'kt': 'K T',
    'java': 'java', 'c': 'C', 'h': 'H', 'cs': 'C sharp', 'php': 'P H P', 'vue': 'view', 'lock': 'lock',
    'cfg': 'config', 'ini': 'I N I', 'env': 'env', 'xml': 'X M L', 'svg': 'S V G', 'proto': 'proto',
    'swift': 'swift', 'dart': 'dart', 'lua': 'lua', 'zig': 'zig', 'ex': 'E X', 'exs': 'E X S', 'scala': 'scala',
}
# Words text-to-speech engines get wrong (checked against espeak-ng, which both Kokoro and Piper use).
LEXICON = {
    'stdin': 'standard in', 'stdout': 'standard out', 'stderr': 'standard error', 'enum': 'ee-num',
    'enums': 'ee-nums', 'async': 'a-sync', 'serde': 'sir-dee', 'CLI': 'C L I', 'CLIs': 'C L Is', 'README': 'read me',
    'READMEs': 'read mes', 'src': 'source', 'kwargs': 'keyword args', 'regex': 'rejex', 'sudo': 'soo-doo',
    'nginx': 'engine X', 'kubectl': 'kube control', 'OAuth': 'oh-auth', 'GUI': 'gooey',
}
ABBREVIATIONS = [
    (r'\be\.g\.,?', 'for example,'), (r'\bi\.e\.,?', 'that is,'), (r'\betc\.', 'and so on.'), (r'\bvs\.?(?=\s)', 'versus'),
    (r'\ba\.k\.a\.', 'also known as'), (r'\bapprox\.', 'about'), (r'\bw/(?=\s)', 'with'), (r'\bcf\.', 'compare'),
]
SYMBOLS = [
    (r'\s*(?:->|→|=>|⇒|-->|—>)\s*', ' to '), (r'\s*(?:<-|←)\s*', ' from '), (r'\s*(?:<->|↔)\s*', ' and back '),
    (r'\s+[—–]\s+|—', ', '), (r'\s&&\s', ' and '), (r'\s\|\|\s', ' or '), (r'\s!=\s', ' is not '), (r'\s==\s', ' equals '),
    (r'\s>=\s', ' at least '), (r'\s<=\s', ' at most '), (r'≈|~(?=\d)', 'about '), (r'(\d)\s*%', r'\1 percent'),
    (r'(\d)\s*×', r'\1 times'), (r'\s&\s', ' and '), (r'(\w)\s*\+\s*(\w)', r'\1 plus \2'), (r'\s*[·•]\s*', ', '),
    (r'(?<!\w)(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}(?!\w)', ''),  # commit hashes mean nothing when heard
]
# fmt: on
HOST_PORT = re.compile(r'(?<![\d:])(\b[A-Za-z][\w.-]*)?\s?:(\d{2,5})\b(?!:)')  # localhost:8000, app :8000 (not 10:30)
DOMAIN = re.compile(r'\b([a-z][\w-]*)\.(com|org|net|io|dev|pub|app|ai|sh|local)\b')
URL = re.compile(r'https?://(?:www\.)?([\w.-]+)[^\s)]*')


# ---------------------------------------------------------------------------------------------- blocks
def blocks(md: str) -> list[dict]:
    """Split Markdown the way ``markdown.js`` renders it. Each block: ``ln`` (0-based start line), ``kind``
    (heading, para, item, code, diagram, quote, answer, table) and ``text``; headings add ``level``, code adds
    ``lang``, ordered list items add ``n``."""
    lines = str(md or '').split('\n')
    out: list[dict] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('```'):
            lang, start, buf = line[3:].strip().lower(), i, []
            i += 1
            while i < len(lines) and not lines[i].startswith('```'):
                buf.append(lines[i])
                i += 1
            i += 1
            kind = 'diagram' if lang == 'mermaid' else 'code'
            out.append({'ln': start, 'kind': kind, 'lang': lang, 'text': '\n'.join(buf)})
            continue
        h = re.match(r'^(#{1,4})\s+(.*)', line)
        if h:
            out.append({'ln': i, 'kind': 'heading', 'level': len(h.group(1)), 'text': h.group(2)})
            i += 1
            continue
        if re.match(r'^\s*\|', line):
            start, rows = i, []
            while i < len(lines) and re.match(r'^\s*\|', lines[i]):
                if not re.match(r'^\s*\|?\s*:?-{2,}', lines[i]):
                    rows.append([c.strip() for c in lines[i].strip().strip('|').split('|')])
                i += 1
            out.append({'ln': start, 'kind': 'table', 'rows': rows, 'text': '\n'.join(' | '.join(r) for r in rows)})
            continue
        if LIST.match(line):
            i = _list(lines, i, out)
            continue
        if re.match(r'^\s*>', line):
            start, buf = i, []
            while i < len(lines) and re.match(r'^\s*>', lines[i]):
                buf.append(re.sub(r'^\s*>\s?', '', lines[i]))
                i += 1
            kind = 'answer' if re.match(r'^\s*\*\*A[:.]', buf[0]) else 'quote'
            out.append({'ln': start, 'kind': kind, 'text': ' '.join(b.strip() for b in buf if b.strip())})
            continue
        if not line.strip():
            i += 1
            continue
        start, buf = i, []
        while i < len(lines) and lines[i].strip() and not BLOCK_START.match(lines[i]):
            buf.append(lines[i])
            i += 1
        out.append({'ln': start, 'kind': 'para', 'text': ' '.join(b.strip() for b in buf)})
    return out


def _list(lines: list[str], i: int, out: list[dict]) -> int:
    ordered = bool(re.match(r'^\s*\d+\.', lines[i]))

    def is_item(x: str) -> bool:
        return bool(LIST.match(x)) and bool(re.match(r'^\s*\d+\.', x)) == ordered

    while i < len(lines):
        if not lines[i].strip():
            j = i
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and is_item(lines[j]):
                i = j
                continue
            if j < len(lines) and out and re.match(r'^\s{2,}\S', lines[j]) and not LIST.match(lines[j]):
                while j < len(lines) and re.match(r'^\s{2,}\S', lines[j]):  # indented paragraph of the last item
                    out[-1]['text'] += ' ' + lines[j].strip()
                    j += 1
                i = j
                continue
            break
        if not is_item(lines[i]):
            break
        m = LIST.match(lines[i])
        item = {'ln': i, 'kind': 'item', 'text': re.sub(r'^\[( |x)\]\s*', '', lines[i][m.end() :], flags=re.I)}
        if ordered:
            item['n'] = int(m.group(1)[:-1])
        out.append(item)
        i += 1
        while i < len(lines) and re.match(r'^\s{2,}\S', lines[i]) and not LIST.match(lines[i]):
            item['text'] += ' ' + lines[i].strip()
            i += 1
    return i


# ---------------------------------------------------------------------------------------------- words
def say_file(name: str) -> str:
    """'server.rs' -> 'server dot R S'; 'README.md' -> 'read me dot M D'."""
    stem, dot, ext = name.rpartition('.')
    if not dot or not stem:
        return words(name)
    e = ext.lower()
    spoken = EXTENSIONS.get(e) or (' '.join(e.upper()) if len(e) <= 3 and not re.search(r'[aeiou]', e) else e)
    return f'{words(stem)} dot {spoken}'


def words(ident: str) -> str:
    """Identifiers as words: copy_bidirectional -> copy bidirectional, ClientMessage -> Client Message,
    Client::new -> Client new, llm -> L L M."""
    if '_' in ident and re.fullmatch(r'[A-Z0-9_]+', ident):
        ident = ident.lower()  # CONTROL_PORT -> control port
    s = re.sub(r'(?<=\w)\.(?=[A-Za-z])', ' dot ', ident)  # client.listen -> client dot listen
    s = re.sub(r'::|[_./\\]+', ' ', s)
    s = re.sub(r'(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])', ' ', s)
    out = []
    for w in s.split():
        if w in LEXICON:
            out.append(LEXICON[w])
        elif w.isupper() and len(w) > 4:
            out.append(w.lower())  # CONTROL_PORT -> control port; short ones (API, UUID) stay spelled
        elif len(w) <= 4 and w.isalpha() and w.islower() and not re.search(r'[aeiouy]', w):
            out.append(' '.join(w.upper()))  # 'llm', 'cwd', 'src' would otherwise be mumbled
        else:
            out.append(w)
    return ' '.join(out)


def say_code(code: str) -> str:
    """An inline code span, said the way a developer would read it aloud."""
    c = code.strip()
    m = re.fullmatch(r'([\w.\-@+\[\]()/]+?)(?::\d+(?:-\d+)?)?', c)
    if m and ('/' in c or re.search(r'\.[A-Za-z]{1,5}(?::\d+)?$', c)) and not c.startswith('.'):
        path = m.group(1).rstrip('/')
        name = path.rsplit('/', 1)[-1]
        return say_file(name) if '.' in name.strip('.') else words(name)
    c = HOST_PORT.sub(lambda h: f'{h.group(1) or ""} port {h.group(2)}', c)
    c = DOMAIN.sub(r'\1 dot \2', c)
    c = re.sub(r'^--?(?=\w)', '', c)  # --secret -> secret
    c = re.sub(r'\(\s*\)', '', c)  # listen() -> listen
    c = re.sub(r'[{}\[\]()<>"\'`;=,]+', ' ', c)
    return ' '.join(words(w) if re.search(r'[_A-Z:]|[a-z]\.[a-z]|^[a-z]{1,4}$', w) else w for w in c.split())


def speakable(text: str) -> str:
    """Markdown inline text -> plain, speakable sentences."""
    t = re.sub(r'`([^`]+)`', lambda m: say_code(m.group(1)), str(text))
    t = re.sub(r'!?\[([^\]]+)\]\([^)]*\)', r'\1', t)  # links and images -> their text
    t = URL.sub(lambda m: say_file(m.group(1)) if '.' in m.group(1) else m.group(1), t)
    t = re.sub(
        r'(?<![\w/])(?:[\w.\-@]+/)+([\w.\-@]+\.[A-Za-z]{1,5})(?::\d+(?:-\d+)?)?\b', lambda m: say_file(m.group(1)), t
    )
    t = re.sub(r'\b([\w\-]+\.(?:' + '|'.join(EXTENSIONS) + r'))(?::\d+(?:-\d+)?)?\b', lambda m: say_file(m.group(1)), t)
    t = HOST_PORT.sub(lambda h: f'{h.group(1) or ""} port {h.group(2)}', t)
    t = DOMAIN.sub(r'\1 dot \2', t)
    t = re.sub(r'(?<![\w-])--?(?=[a-z])', '', t)  # --to -> to
    t = re.sub(r'\b\w+(?:::\w+)+(?:\(\))?|\b[a-z][a-z0-9]*_\w+', lambda m: words(m.group(0).replace('()', '')), t)
    t = re.sub(r'\*\*|__|(?<!\w)[*_](?=\S)|(?<=\S)[*_](?!\w)', '', t)  # bold and italics
    for pat, rep in ABBREVIATIONS + SYMBOLS:
        t = re.sub(pat, rep, t, flags=re.I if pat.startswith(r'\b') else 0)
    t = re.sub(r'\s*\(([^()]*)\)', r', \1,', t)  # parentheses -> a spoken aside
    t = re.sub(r'[#|>`*]', ' ', t)
    t = re.sub(r'(?<=\w)/(?=\w)', ' ', t)  # client/server -> client server
    t = re.sub(r'\b(' + '|'.join(re.escape(k) for k in LEXICON) + r')\b', lambda m: LEXICON[m.group(1)], t)
    t = re.sub(r'\s+([,.;:!?])', r'\1', t)
    t = re.sub(r',\s*([,.;:!?])', r'\1', t)
    return re.sub(r'\s+', ' ', t).strip(' ,')


# ---------------------------------------------------------------------------------------------- diagrams
NODE = re.compile(r'([A-Za-z]\w*)\s*(?:\[\[?|\(\(?|\{\{?|>)\s*"?([^"\]\)\}]*)"?\s*(?:\]\]?|\)\)?|\}\}?)')
EDGE = re.compile(
    r'([A-Za-z]\w*)(?:\s*[\[({>][^\]})]*[\]})])?\s*(?:-->|---|-\.->|==>|--\s*"?([^-|"]+)"?\s*-->)\s*(?:\|"?([^|"]*)"?\|)?\s*([A-Za-z]\w*)'
)
MESSAGE = re.compile(r'^\s*([\w]+)\s*(?:-->>|->>|-->|->|--x|-x|--\)|-\))\s*([\w]+)\s*:\s*(.+)$')


def describe_diagram(src: str, limit: int = 10) -> str:
    """A Mermaid diagram in words: each arrow becomes a short sentence, like pointing at a whiteboard."""
    first = src.strip().split('\n', 1)[0].strip().lower()
    if first.startswith('sequencediagram'):
        names = {m.group(1): m.group(2) for m in re.finditer(r'participant\s+(\w+)\s+as\s+(.+)', src)}
        steps = []
        for line in src.split('\n'):
            m = MESSAGE.match(line)
            if m:
                a, b, msg = (
                    speakable(names.get(m.group(1), m.group(1))),
                    speakable(names.get(m.group(2), m.group(2))),
                    speakable(m.group(3).strip().strip('"')),
                )
                steps.append(f'{a} to itself: {msg}.' if a == b else f'{a} to {b}: {msg}.')
        if not steps:
            return 'There is a diagram on screen.'
        more = f' And {len(steps) - limit} more steps.' if len(steps) > limit else ''
        return f'The diagram shows the steps in order. {" ".join(steps[:limit])}{more}'
    if first.startswith(('flowchart', 'graph')):
        labels = {m.group(1): m.group(2).strip() for m in NODE.finditer(src) if m.group(2).strip()}
        edges = []
        for m in EDGE.finditer(src):
            a, b = speakable(labels.get(m.group(1), m.group(1))), speakable(labels.get(m.group(4), m.group(4)))
            label = (m.group(3) or m.group(2) or '').strip()
            edges.append(f'{a} to {b}: {speakable(label)}.' if label else f'{a} to {b}.')
        edges = list(dict.fromkeys(edges))
        if not edges:
            return 'There is a diagram on screen.'
        more = f' And {len(edges) - limit} more connections.' if len(edges) > limit else ''
        return f'The diagram shows {len(edges)} connections. {" ".join(edges[:limit])}{more}'
    return 'There is a diagram on screen.'


# ---------------------------------------------------------------------------------------------- whole blocks
def plain(block: dict) -> str:
    """What to say for one block when no AI listening script is available."""
    kind, text = block['kind'], block.get('text', '')
    if kind == 'heading':
        return speakable(text).rstrip('.:') + '.'
    if kind == 'diagram':
        return describe_diagram(text)
    if kind == 'code':
        what = {'': 'code', 'shell': 'command', 'bash': 'command', 'sh': 'command', 'console': 'command'}
        lang = block.get('lang', '')
        noun = what.get(lang) or f'{words(lang)} code'
        return f'There is a {noun} example on screen.'
    if kind == 'answer':
        return 'Think about it, then check the answer on screen.'
    if kind == 'table':
        rows = block.get('rows') or []
        if len(rows) < 2:
            return speakable(' '.join(rows[0])) + '.' if rows else ''
        head, body = rows[0], rows[1:]
        said = [
            ', '.join(f'{speakable(h)}: {speakable(c)}' for h, c in zip(head, r, strict=False) if c) + '.'
            for r in body[:8]
        ]
        more = f' And {len(body) - 8} more rows.' if len(body) > 8 else ''
        return f'A table with {len(body)} rows. ' + ' '.join(said) + more
    s = speakable(text)
    if kind == 'item' and block.get('n') is not None:
        s = f'{block["n"]}. {s}'
    return s if not s or s.rstrip('"\')').endswith(('.', '!', '?', ':')) else s + '.'


def chunks(text: str, target: int = 220, first: int | None = None) -> list[str]:
    """Split into sentence-sized parts. Short parts start playing sooner; whole sentences keep the intonation right.
    ``first`` caps the first part (split at a comma if possible), so the very first audio arrives quickly."""
    sentences = [s.strip() for s in re.split(r'(?<=[.!?:])["\')\]]*\s+(?=[A-Z0-9"\'(])', text) if s.strip()]
    out: list[str] = []
    for s in sentences:
        while len(s) > target + 60:  # a long sentence: break at a comma or a conjunction, never mid-phrase
            cut = max(s.rfind(', ', 60, target), s.rfind('; ', 60, target), s.rfind(' and ', 60, target))
            cut = cut if cut > 0 else s.rfind(' ', 60, target)
            if cut <= 0:
                break
            out.append(s[: cut + 1].strip())
            s = s[cut + 1 :].strip()
        if out and len(out[-1]) + len(s) < 90:
            out[-1] += ' ' + s  # very short sentences ("Step 1.") ride along with a neighbour
        else:
            out.append(s)
    if first and out and len(out[0]) > first + 30:
        head = out[0]
        cut = max(head.rfind(', ', 40, first), head.rfind(' and ', 40, first))
        if cut > 0:
            out[:1] = [head[: cut + 1].strip(), head[cut + 1 :].strip()]
    return out


def script(md: str) -> list[dict]:
    """The listening script without AI: one segment per block, in reading order."""
    return [{'ln': b['ln'], 'kind': b['kind'], 'text': t} for b in blocks(md) if (t := plain(b))]
