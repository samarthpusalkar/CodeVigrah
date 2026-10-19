"""On-disk layout of the workspace: one folder per analysed repository.

<workspace>/<repo id>/
    repo/           the clone (absent for local folders)
    analysis.json   output of the analyzer
    tour/           AI-written tour chapters, cached per commit
    quiz/           AI-written skill checks, cached per commit
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

LOCAL_PREFIX = 'local__'


def safe_id(rid: str) -> str:
    """Repository ids are folder names; never let one escape the workspace."""
    rid = os.path.basename(str(rid or ''))
    return rid if re.fullmatch(r'[\w.\-]+', rid) and rid not in ('.', '..') else ''


class Workspace:
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def repo_dir(self, rid: str) -> Path:
        sid = safe_id(rid)
        if not sid:
            raise ValueError('invalid repository id')
        return self.root / sid

    def clone_dir(self, rid: str) -> Path:
        return self.repo_dir(rid) / 'repo'

    def analysis_path(self, rid: str) -> Path:
        return self.repo_dir(rid) / 'analysis.json'

    def save_analysis(self, rid: str, analysis: dict) -> None:
        """Write atomically so a crash mid-write never leaves a half-written analysis behind."""
        path = self.analysis_path(rid)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.analysis-', suffix='.json')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                json.dump(analysis, fh)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def load_analysis(self, rid: str) -> dict | None:
        try:
            path = self.analysis_path(rid)
        except ValueError:
            return None
        if not path.is_file():
            return None
        with open(path, encoding='utf-8') as fh:
            a = json.load(fh)
        if not str(a['meta'].get('source', '')).startswith('/'):
            # Clones live inside the workspace; derive the path so a moved workspace keeps working.
            a['meta']['root'] = str(self.clone_dir(rid))
        return a

    def list(self, include_local: bool = True) -> list[dict]:
        out = []
        for d in self.root.iterdir():
            p = d / 'analysis.json'
            if p.is_file() and (include_local or not d.name.startswith(LOCAL_PREFIX)):
                out.append({'id': d.name, 'mtime': int(p.stat().st_mtime)})
        return sorted(out, key=lambda x: -x['mtime'])
