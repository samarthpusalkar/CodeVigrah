"""Static analysis of a repository (no AI, no network): structure, import graph, git history, domain and rules."""

from .pipeline import SCHEMA, analyze, brief

__all__ = ['SCHEMA', 'analyze', 'brief']
