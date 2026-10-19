"""The domain knowledge base. Everything here is plain data that the analyzer evaluates against a repo.

To extend CodeVigrah, add entries to the module that matches what you are adding:

* ``signals.py``   a dependency that identifies a framework or domain
* ``domains.py``   a new kind of project (mental model, hard problems, questions)
* ``recipes.py``   a typical change and the roles of the files it touches
* ``decisions.py`` a design choice with *why* it was made and the *cost* it imposes
* ``probes.py``    a shortcoming heuristic with *why* it matters and why it is *hard* to fix
* ``concepts.py``  a concept card linked to the lines of code that use it
"""

from .concepts import CONCEPTS
from .decisions import DECISIONS
from .domains import DOMAINS
from .probes import PROBES
from .recipes import RECIPES
from .signals import DEP_SIGNALS

__all__ = ['CONCEPTS', 'DECISIONS', 'DEP_SIGNALS', 'DOMAINS', 'PROBES', 'RECIPES']
