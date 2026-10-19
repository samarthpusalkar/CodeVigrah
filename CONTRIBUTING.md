# Contributing to CodeVigrah

Thanks for helping. Bug reports, ideas, new knowledge-base rules, providers and fixes are all welcome.

## Set up

```bash
git clone https://github.com/samarthpusalkar/CodeVigrah.git && cd CodeVigrah
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"  # add ,anthropic to work on the Anthropic provider
codevigrah               # or ./run.sh without installing anything
```

## Check your change

```bash
pytest                         # or, with no installs: PYTHONPATH=src python3 -m unittest discover -s tests
ruff check . && ruff format .  # lint and format (CI runs both)
```

CI runs the tests on Python 3.10 to 3.14. Please add a test for new behaviour. `tests/helpers.py` builds a small multi-language
git repository and a stub AI server, so tests never need the network or a real model.

For UI changes, run the app and click through the views you touched, in both themes (the ◐ button), and check the browser
console for errors.

## Ground rules

* **No new runtime dependencies in the core.** CodeVigrah runs on a Raspberry Pi with only Python and git. If something needs a
  library, make it an optional extra like `codevigrah[anthropic]` and keep a fallback.
* **Never execute code from an analysed repository**, and never add a git operation that could (hooks, submodules, filters).
* **Knowledge is data.** Rules in `src/codevigrah/knowledge/` must explain *why* and *what it costs*, and show evidence.
* **Escape everything** you put into the page (`esc()` or the Markdown renderer), and no inline `onclick` handlers.
* **Secrets come from the environment** and are never logged, returned by the API, or written to disk.

## Where things are

See [docs/architecture.md](docs/architecture.md): the layout, the analysis pipeline, and how to add a rule, a language, a
provider, an endpoint or a view.

## Pull requests

* Keep a pull request to one topic, with a short description of what changed and why.
* Add a line to the "Unreleased" section of [CHANGELOG.md](CHANGELOG.md) for anything a user would notice.
* Commit messages: a short imperative summary ("Add Ruby import resolution"), then details if needed.

## Reporting bugs

Open an issue with the repository you analysed (if public), what you expected, what happened, and the server log
(`CODEVIGRAH_LOG_LEVEL=DEBUG` gives more detail). For security problems, see [SECURITY.md](SECURITY.md) instead.
