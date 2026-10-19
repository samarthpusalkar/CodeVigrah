"""Where a repository comes from: validate the user's input, derive an id, clone or update it safely.

Cloning never runs anything from the repository: hooks are disabled, symlinks are checked out as plain files,
submodules and LFS objects are skipped, and only https URLs on well-known hosts are accepted.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from .workspace import LOCAL_PREFIX

GIT_URL = re.compile(r'^https://(github\.com|gitlab\.com|bitbucket\.org|codeberg\.org)/[\w.\-]+/[\w.\-]+?(\.git)?/?$')
GIT_ENV = {'GIT_TERMINAL_PROMPT': '0', 'GIT_LFS_SKIP_SMUDGE': '1'}
GIT_SAFE = ['-c', 'core.hooksPath=/dev/null', '-c', 'core.symlinks=false', '-c', 'protocol.file.allow=never']


class SourceError(ValueError):
    """The input is not something CodeVigrah can analyse."""


def is_local(source: str) -> bool:
    return source.startswith('/')


def normalise(source: str, allow_local: bool = True) -> str:
    """Turn ``owner/repo``, a GitHub page URL or an absolute path into a canonical source string."""
    source = (source or '').strip()
    if re.fullmatch(r'[\w.\-]+/[\w.\-]+', source):
        source = f'https://github.com/{source}'
    m = re.match(r'^(https://github\.com/[\w.\-]+/[\w.\-]+?)(\.git)?(/(tree|blob)/.*)?/?$', source)
    if m:
        source = m.group(1)
    if is_local(source):
        if not allow_local:
            raise SourceError(
                'Local folders can only be analysed when CodeVigrah runs on this machine '
                '(start it with --allow-local-paths to enable this on a network).'
            )
        if not os.path.isdir(source):
            raise SourceError('Local path does not exist')
        return os.path.normpath(source)
    if not GIT_URL.match(source):
        raise SourceError('Use https://github.com/owner/repo, owner/repo, or an absolute local path')
    return source.rstrip('/')


def repo_id_for(source: str) -> str:
    if is_local(source):
        name = re.sub(r'[^\w.-]', '_', os.path.basename(source.rstrip('/')))
        return f'{LOCAL_PREFIX}{name}_{hashlib.sha1(source.encode()).hexdigest()[:6]}'
    owner, name = source.rstrip('/').removesuffix('.git').split('/')[-2:]
    return re.sub(r'[^\w.-]', '_', f'{owner}__{name}')


def display_name(source: str) -> str:
    return os.path.basename(source.rstrip('/')).removesuffix('.git')


def dir_size_mb(path: str | os.PathLike) -> float:
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
    return total / 1_000_000


def fetch(
    source: str,
    dest: Path,
    refresh: bool = False,
    depth: int = 1000,
    max_mb: int = 0,
    log: Callable[[str], None] = print,
) -> None:
    """Clone ``source`` into ``dest`` (or fast-forward it when ``refresh``). Raises RuntimeError on failure."""
    env = {**os.environ, **GIT_ENV}
    if (dest / '.git').is_dir():
        if refresh:
            log('fetching updates')
            subprocess.run(
                ['git', *GIT_SAFE, '-C', str(dest), 'pull', '--ff-only', '-q'],
                env=env,
                capture_output=True,
                timeout=300,
            )
        return
    shutil.rmtree(dest, ignore_errors=True)
    log(f'cloning {source} (last {depth} commits)')
    p = subprocess.run(
        [
            'git',
            *GIT_SAFE,
            'clone',
            '--depth',
            str(depth),
            '--single-branch',
            '--no-recurse-submodules',
            '-q',
            '--',
            source,
            str(dest),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
    )
    if p.returncode != 0:
        shutil.rmtree(dest, ignore_errors=True)
        raise RuntimeError('git clone failed: ' + p.stderr.strip()[-400:])
    if max_mb:
        size = dir_size_mb(dest)
        if size > max_mb:
            shutil.rmtree(dest, ignore_errors=True)
            raise RuntimeError(f"Repository is {size:.0f} MB, above this server's limit of {max_mb} MB")


def head_commit(root: str | os.PathLike) -> str:
    """Short hash of the checked-out commit, or '' when the folder is not a git repository."""
    p = subprocess.run(['git', '-C', str(root), 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else ''


def has_local_changes(root: str | os.PathLike) -> bool:
    p = subprocess.run(['git', '-C', str(root), 'status', '--porcelain'], capture_output=True, text=True)
    return p.returncode == 0 and bool(p.stdout.strip())


def content_fingerprint(root: str | os.PathLike, paths: list[str]) -> str:
    """Hash of the analysed files' names and contents: changes whenever any of them changes."""
    h = hashlib.sha1()
    for rel in sorted(paths):
        h.update(rel.encode() + b'\0')
        try:
            with open(os.path.join(root, rel), 'rb') as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b''):
                    h.update(chunk)
        except OSError:
            h.update(b'\1')
    return h.hexdigest()[:10]


def version_stamp(root: str | os.PathLike, paths: list[str]) -> str:
    """What cached AI output is keyed by: the commit for a clean git checkout, otherwise a content fingerprint
    (``snap-…`` for a folder without git, ``<commit>+…`` for a checkout with uncommitted changes)."""
    commit = head_commit(root)
    if commit and not has_local_changes(root):
        return commit
    fingerprint = content_fingerprint(root, paths)
    return f'{commit}+{fingerprint}' if commit else f'snap-{fingerprint}'
