"""Command line: ``codevigrah`` (serve the web UI), ``codevigrah analyze SOURCE``, ``codevigrah report SOURCE``.

Flags override environment variables, which override built-in defaults.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__, llm, speech
from .config import Settings, load_dotenv


def _server_flags(p: argparse.ArgumentParser, default=None) -> None:
    p.add_argument('--host', default=default, help='address to listen on (default 127.0.0.1; 0.0.0.0 for your LAN)')
    p.add_argument('--port', type=int, default=default, help='port (default 8765)')
    p.add_argument('--workspace', default=default, help='where clones and analyses are stored (default ./workspace)')
    p.add_argument(
        '--public',
        action='store_true',
        default=default,
        help='host for other people: lock AI settings, disable local folders, enable rate limits',
    )
    p.add_argument(
        '--allow-local-paths',
        action='store_true',
        default=default,
        help='allow analysing local folders when listening on a network address (ignored with --public)',
    )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog='codevigrah', description='Understand any repository like its author.')
    ap.add_argument('--version', action='version', version=f'codevigrah {__version__}')
    ap.add_argument('--env-file', default='.env', help='read settings from this file if it exists (default .env)')
    _server_flags(ap)
    sub = ap.add_subparsers(dest='command')
    _server_flags(sub.add_parser('serve', help='run the web UI (the default)'), default=argparse.SUPPRESS)
    a = sub.add_parser('analyze', help='analyse a repository and print its brief')
    a.add_argument('source', help='owner/repo, a GitHub URL, or an absolute local path')
    a.add_argument('--refresh', action='store_true', help='pull the latest commits first')
    a.add_argument('--workspace', default=argparse.SUPPRESS)
    r = sub.add_parser('report', help='write a Markdown onboarding report')
    r.add_argument('source', help='owner/repo, a GitHub URL, or an absolute local path')
    r.add_argument('-o', '--output', help='file to write (default: print to stdout)')
    r.add_argument('--refresh', action='store_true', help='pull the latest commits first')
    r.add_argument('--workspace', default=argparse.SUPPRESS)
    return ap


def settings_from(args: argparse.Namespace) -> Settings:
    get = lambda name: getattr(args, name, None)  # noqa: E731
    return Settings.from_env(
        host=get('host'),
        port=get('port'),
        workspace=Path(get('workspace')) if get('workspace') else None,
        public=True if get('public') else None,
        allow_local_paths=True if get('allow_local_paths') else None,
    )


def serve(settings: Settings) -> int:
    from .web import Server

    srv = Server(settings)
    mode = 'public' if settings.public else 'private'
    print(
        f'CodeVigrah {__version__} on http://{settings.host}:{settings.port}  ({mode}; AI: {llm.describe() or "off"})',
        flush=True,
    )
    tts = speech.engine()
    if tts.base_url:
        voices = tts.voice_ids()
        status = f'{len(voices)} voices at {tts.base_url}' if voices else f'{tts.base_url} is not answering yet'
        print(f'  Read-aloud: natural voices, {status}', flush=True)
    if not settings.is_loopback and not settings.public:
        print(
            '  Listening on the network without --public: anyone who can reach this port can change AI settings.',
            flush=True,
        )
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


def analyze_cmd(
    settings: Settings, source: str, refresh: bool, report_to: str | None = None, as_report: bool = False
) -> int:
    from .report import md_report
    from .service import analyze_source
    from .sources import SourceError, normalise
    from .workspace import Workspace

    try:
        source = normalise(source, allow_local=True)
    except SourceError as e:
        print(f'error: {e}', file=sys.stderr)
        return 2
    say = lambda msg: print(msg, file=sys.stderr, flush=True)  # noqa: E731  progress goes to stderr, results to stdout
    try:
        rid, a = analyze_source(Workspace(settings.workspace), settings, source, refresh, say)
    except RuntimeError as e:
        print(f'error: {e}', file=sys.stderr)
        return 1
    if not as_report:
        print(a['brief'].replace('**', '').replace('_', ''))
        say(f'saved as {rid}; run `codevigrah` and pick it from Recent to explore')
        return 0
    text = md_report(a)
    if report_to:
        Path(report_to).write_text(text, encoding='utf-8')
        say(f'wrote {report_to}')
    else:
        sys.stdout.write(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv(args.env_file)
    settings = settings_from(args)
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )
    try:
        llm.configure(public=settings.public)
        speech.configure()
    except ValueError as e:
        print(f'error: {e}', file=sys.stderr)
        return 2
    if args.command == 'analyze':
        return analyze_cmd(settings, args.source, args.refresh)
    if args.command == 'report':
        return analyze_cmd(settings, args.source, args.refresh, args.output, as_report=True)
    return serve(settings)


if __name__ == '__main__':
    raise SystemExit(main())
