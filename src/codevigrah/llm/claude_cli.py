"""Claude Code CLI in headless mode, run inside the analysed repo with read-only tools.

It opens files itself, so it needs less pasted context than API providers. It uses whatever account Claude Code
is logged into on this machine.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading

from .base import LLMError, Provider

READ_ONLY_TOOLS = 'Read,Grep,Glob'
BLOCKED_TOOLS = 'Bash,Write,Edit,WebFetch,WebSearch,NotebookEdit'


class ClaudeCodeProvider(Provider):
    name = 'claude-cli'
    label = 'Claude Code'
    reads_files = True
    fields = ('model',)

    def __init__(self, binary: str = 'claude', model: str = '', timeout: int = 420, concurrency: int = 2):
        self.binary = binary
        self.model = model
        self.timeout = timeout
        self._slots = threading.Semaphore(max(1, concurrency))  # low-power hosts: cap parallel CLI processes

    @property
    def path(self) -> str | None:
        return shutil.which(self.binary)

    def available(self) -> bool:
        return self.path is not None

    def problem(self) -> str:
        return '' if self.available() else f'`{self.binary}` was not found on PATH (install Claude Code and log in)'

    def complete(self, system: str, messages: list[dict], max_tokens: int = 3000, cwd: str | None = None) -> str:
        path = self.path
        if not path:
            raise LLMError(self.problem())
        if len(messages) == 1:
            prompt = messages[0]['content']
        else:
            convo = '\n\n'.join(f'[{m["role"].upper()}]\n{m["content"]}' for m in messages[:-1])
            prompt = f'Conversation so far:\n{convo}\n\n[USER — answer this]\n{messages[-1]["content"]}'
        cmd = [
            path,
            '-p',
            '--output-format',
            'json',
            '--tools',
            READ_ONLY_TOOLS,
            '--permission-mode',
            'dontAsk',
            '--disallowedTools',
            BLOCKED_TOOLS,
            '--append-system-prompt',
            system,
        ]
        if self.model:
            cmd += ['--model', self.model]
        with self._slots:
            try:
                p = subprocess.run(
                    cmd, input=prompt, capture_output=True, text=True, timeout=self.timeout, cwd=cwd or None
                )
            except subprocess.TimeoutExpired:
                raise LLMError(f'Claude Code timed out after {self.timeout}s') from None
            except OSError as e:
                raise LLMError(f'Claude Code could not start: {e}') from None
        try:
            d = json.loads(p.stdout)
        except ValueError:
            raise LLMError(f'Claude Code failed: {(p.stderr or p.stdout).strip()[-400:]}') from None
        if d.get('is_error'):
            raise LLMError(f'Claude Code error: {str(d.get("result"))[:400]}')
        return d.get('result', '')
