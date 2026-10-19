"""Symbols, branch complexity and a file's own description (docstring / header comment)."""

import ast
import re

GEN_SYM = re.compile(
    r'^\s*(?:export\s+|pub(?:\([^)]*\))?\s+|public\s+|private\s+|protected\s+|internal\s+|static\s+|async\s+|final\s+|abstract\s+|default\s+|override\s+|open\s+|data\s+|sealed\s+|unsafe\s+)*'
    r'(def|function|func|fn|class|struct|interface|enum|trait|type|object|fun|impl|module|record)\s+\*?(?:\([^)]*\)\s*)?([A-Za-z_]\w*)',
    re.M,
)
ASSIGN_SYM = re.compile(r'^\s*((?:[A-Za-z_$][\w$]*\.)+[A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?function\b', re.M)
METHOD_SYM = re.compile(
    r'^\s{2,}(?:static\s+|async\s+|get\s+|set\s+|public\s+|private\s+|protected\s+)*([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*(?::\s*[^{=]+)?\{',
    re.M,
)
JS_KW = {
    'if',
    'for',
    'while',
    'switch',
    'catch',
    'function',
    'return',
    'with',
    'else',
    'do',
    'try',
    'new',
    'typeof',
    'super',
    'constructor',
}
ARROW_SYM = re.compile(
    r'^\s*(?:export\s+)?(?:const|let)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_]\w*)\s*(?::[^=]+)?=>',
    re.M,
)
BRANCH_RX = re.compile(r'\b(if|elif|for|while|case|catch|except|switch|when)\b|&&|\|\||\?\?')


def py_symbols(text):
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None, None
    syms, cx = [], 1
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            syms.append([node.name, 'function', node.lineno])
        elif isinstance(node, ast.ClassDef):
            syms.append([node.name, 'class', node.lineno])
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and not (
                    sub.name.startswith('__') and sub.name != '__init__'
                ):
                    syms.append([f'{node.name}.{sub.name}', 'method', sub.lineno])
    for n in ast.walk(tree):
        if isinstance(
            n,
            (
                ast.If,
                ast.For,
                ast.While,
                ast.ExceptHandler,
                ast.IfExp,
                ast.comprehension,
                ast.AsyncFor,
                ast.With,
                ast.Match,
            ),
        ):
            cx += 1
        elif isinstance(n, ast.BoolOp):
            cx += len(n.values) - 1
    return syms, cx


def generic_symbols(text, js=False):
    syms = []
    for m in GEN_SYM.finditer(text):
        kw, name = m.group(1), m.group(2)
        if name in ('if', 'for', 'while', 'return', 'new'):
            continue
        kind = (
            'class'
            if kw in ('class', 'struct', 'interface', 'enum', 'trait', 'type', 'object', 'impl', 'module', 'record')
            else 'function'
        )
        syms.append([name, kind, text.count('\n', 0, m.start()) + 1])
    for m in ARROW_SYM.finditer(text):
        syms.append([m.group(1), 'function', text.count('\n', 0, m.start()) + 1])
    if js:
        for m in ASSIGN_SYM.finditer(text):
            syms.append([m.group(1), 'function', text.count('\n', 0, m.start()) + 1])
        for m in METHOD_SYM.finditer(text):
            if m.group(1) not in JS_KW:
                syms.append([m.group(1), 'method', text.count('\n', 0, m.start()) + 1])
    syms.sort(key=lambda s: s[2])
    return syms


LICENSE_RX = re.compile(r'(copyright|licen[cs]e|spdx|all rights reserved|eslint|@ts-|prettier|noqa|-\*- coding)', re.I)


def file_doc(text, lang):
    """First sentence(s) of a file's own description: module docstring, //! docs, package comment, header comment."""
    t = text[:5000]
    doc = ''
    if lang == 'Python':
        m = re.match(r'\s*(?:#[^\n]*\n\s*)*[rRuU]?("""|\'\'\')(.*?)\1', t, re.S)
        doc = m.group(2) if m else ''
    elif lang == 'Rust':
        doc = ' '.join(l.strip()[3:] for l in t.splitlines() if l.strip().startswith('//!'))
    elif lang == 'Go':
        m = re.search(r'((?:^//[^\n]*\n)+)package\s', t, re.M)
        doc = ' '.join(l[2:] for l in m.group(1).splitlines()) if m else ''
    else:
        m = re.match(r'\s*(?:#![^\n]*\n\s*)?(?:/\*\*?(.*?)\*/|((?:\s*(?://|#)[^\n]*\n)+))', t, re.S)
        if m:
            raw = m.group(1) or m.group(2) or ''
            doc = ' '.join(re.sub(r'^\s*(\*|//|#)\s?', '', l) for l in raw.splitlines())
    doc = re.sub(r'\s+', ' ', doc).strip()
    if not doc or LICENSE_RX.search(doc[:120]) or len(doc) < 12:
        return ''
    sents = re.split(r'(?<=[.!?])\s', doc)
    out = sents[0]
    if len(out) < 80 and len(sents) > 1:
        out += ' ' + sents[1]
    return out[:260]


def readme_parts(text):
    """(tagline paragraph, first usage code block) from a README."""
    if not text:
        return '', ''
    tag, usage = '', ''
    paras = re.split(r'\n\s*\n', re.sub(r'```.*?```', '\n\n', text, flags=re.S))
    for para in paras:
        q = para.strip()
        if (
            not q
            or q.startswith(('#', '!', '[!', '<', '|', '---', '===', '>'))
            or re.fullmatch(r'(\[!\[.*?\]\(.*?\)\]\(.*?\)\s*)+', q)
        ):
            continue
        q = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', q)
        q = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', q).strip()
        if len(q) > 40:
            tag = re.sub(r'\s+', ' ', q)[:500]
            break
    m = re.search(r'```(\w*)\n(.*?)```', text, re.S)
    if m:
        usage = m.group(2).strip()[:600]
    return tag, usage
