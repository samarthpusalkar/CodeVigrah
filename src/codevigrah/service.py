"""Application services shared by the web server and the command line."""

from __future__ import annotations

from collections.abc import Callable

from .analysis import analyze
from .config import Settings
from .sources import display_name, fetch, head_commit, is_local, repo_id_for, version_stamp
from .workspace import Workspace


def analyze_source(
    ws: Workspace, settings: Settings, source: str, refresh: bool = False, log: Callable[[str], None] = print
) -> tuple[str, dict]:
    """Clone (or update) ``source`` if needed, analyse it and save the result. Returns (repo id, analysis).

    ``source`` must already be normalised with :func:`codevigrah.sources.normalise`.
    """
    rid = repo_id_for(source)
    ws.repo_dir(rid).mkdir(parents=True, exist_ok=True)
    if is_local(source):
        root = source
    else:
        root = str(ws.clone_dir(rid))
        fetch(
            source, ws.clone_dir(rid), refresh=refresh, depth=settings.clone_depth, max_mb=settings.max_repo_mb, log=log
        )
    meta = {
        'id': rid,
        'name': display_name(source),
        'source': source,
        'commit': head_commit(root) or 'n/a',
        'root': root,
    }
    log('analysing')
    a = analyze(root, meta, log)
    if is_local(source):
        # A local folder can change without a new commit; stamp it by content so cached AI chapters are not reused.
        a['meta']['commit'] = version_stamp(root, [f['path'] for f in a['files']])
    ws.save_analysis(rid, a)
    return rid, a
