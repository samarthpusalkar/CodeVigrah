# AI providers

CodeVigrah works without AI: the analysis, every view, the static tour and the static skill check come from the code alone.
An AI provider adds the written tour chapters, AI-written quizzes, chat, file explanations, change plans and the report narrative.

## How a provider is chosen

`CODEVIGRAH_AI_PROVIDERS` is an ordered list. The first **available** provider answers; if it fails (timeout, quota, network,
refusal), the next one takes over.

```bash
CODEVIGRAH_AI_PROVIDERS=auto                    # default: anthropic, claude-cli, ollama, groq, openai (those configured)
CODEVIGRAH_AI_PROVIDERS=ollama,groq,claude-cli  # local model first, then a free cloud tier, then Claude Code
CODEVIGRAH_AI_PROVIDERS=off                     # static mode
```

On a local instance you can also change this in **Settings**. On a public instance (`--public`) settings are locked, and
`auto` never uses Claude Code, because that would let visitors spend your personal Claude plan. List `claude-cli` explicitly if
you really want that.

Providers that can open files (Claude Code) get a compact prompt and read what they need. The others get source excerpts pasted
into the prompt, up to `CODEVIGRAH_AI_CONTEXT_CHARS` (default 60,000 characters, roughly 15,000 tokens).

| Provider | Reads files itself | Cost | Best for |
|---|---|---|---|
| `claude-cli` | yes | your Claude plan | the best tours on your own machine |
| `anthropic` | no | pay per token | servers, hosting |
| `ollama` | no | free, your hardware | privacy, unlimited use, a GPU at home |
| `groq` | no | free tier, then pay | a fast free fallback |
| `openai` | no | depends | any other OpenAI-compatible server |

## Claude Code

Install [Claude Code](https://code.claude.com) and log in once (`claude`). CodeVigrah runs it headless inside the analysed
repository with read-only tools (`Read`, `Grep`, `Glob`); shell, edit and web tools are blocked.

| Variable | Default | |
|---|---|---|
| `CODEVIGRAH_CLAUDE_BIN` | `claude` | path or name of the binary |
| `CODEVIGRAH_CLAUDE_MODEL` | Claude Code's default | e.g. `opus`, `sonnet` |
| `CODEVIGRAH_CLAUDE_TIMEOUT` | `420` | seconds per answer |
| `CODEVIGRAH_CLAUDE_CONCURRENCY` | `2` | parallel processes (keep low on a Pi) |

## Anthropic API

```bash
pip install "codevigrah[anthropic]"  # or: pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...  # https://console.anthropic.com
```

| Variable | Default | |
|---|---|---|
| `CODEVIGRAH_ANTHROPIC_MODEL` | `claude-opus-5-5` | any current Claude model id |
| `CODEVIGRAH_ANTHROPIC_EFFORT` | `high` | `low` … `max`; lower is cheaper and faster. Empty for models without effort control |
| `CODEVIGRAH_ANTHROPIC_FALLBACKS` | `1` | on supported models, a declined request is retried server-side on Anthropic's recommended fallback model |
| `CODEVIGRAH_ANTHROPIC_MAX_TOKENS` | `32000` | includes the model's thinking; answers are streamed |

## Ollama (local models)

1. Install [Ollama](https://ollama.com) and pull a model, e.g. `ollama pull qwen2.5-coder:14b`.
2. Give the model a context window large enough for the excerpts. Ollama's default is small, so set it on the machine running
   Ollama: `OLLAMA_CONTEXT_LENGTH=32768` (then restart Ollama).
3. Tell CodeVigrah which model to use:

```bash
CODEVIGRAH_OLLAMA_MODEL=qwen2.5-coder:14b
# CODEVIGRAH_OLLAMA_BASE_URL=http://localhost:11434/v1   (the default)
```

**Ollama on another machine.** A common setup is CodeVigrah on a small always-on box (like a Raspberry Pi) and Ollama on a desktop
with a GPU. On the GPU machine start Ollama with `OLLAMA_HOST=0.0.0.0` (and allow port 11434 through its firewall for your local
network only), then point CodeVigrah at it:

```bash
CODEVIGRAH_OLLAMA_BASE_URL=http://gpu-box.local:11434/v1
CODEVIGRAH_AI_PROVIDERS=ollama,groq     # use the GPU when it is on, Groq when it is off
```

**Which model?** Code-focused models in the 14B–20B range fit a 16 GB GPU at 4-bit quantisation and write decent tours, for
example `qwen2.5-coder:14b`. Bigger models write better chapters and quizzes. Check [ollama.com/library](https://ollama.com/library)
for current options, and compare a chapter from each with **Rewrite this chapter**.

Local generation is slower than the cloud; CodeVigrah allows 15 minutes per answer (`CODEVIGRAH_OLLAMA_TIMEOUT`) and sends one
request at a time (`CODEVIGRAH_OLLAMA_CONCURRENCY`).

## Groq

Create a key at [console.groq.com](https://console.groq.com), pick a model from their model list, then:

```bash
GROQ_API_KEY=gsk_...
CODEVIGRAH_GROQ_MODEL=<model id from console.groq.com>
```

The free tier has per-minute and per-day limits. When they are hit, CodeVigrah moves on to the next provider in the list.

## Any other OpenAI-compatible server

Anything that implements `POST /v1/chat/completions` works:

| Server | `CODEVIGRAH_OPENAI_BASE_URL` |
|---|---|
| LM Studio | `http://localhost:1234/v1` |
| llama.cpp server | `http://localhost:8080/v1` |
| vLLM | `http://localhost:8000/v1` |
| OpenRouter | `https://openrouter.ai/api/v1` |
| OpenAI | `https://api.openai.com/v1` |

Set `CODEVIGRAH_OPENAI_MODEL` and, if the server needs one, `CODEVIGRAH_OPENAI_API_KEY` (or `OPENAI_API_KEY`).

## Adding a provider

1. Write a class in `src/codevigrah/llm/` that subclasses `Provider` from `base.py`: implement `available()`, `problem()` and
   `complete()`, and raise `LLMError` on failure.
2. Register it in `providers_from_env()` and `AUTO_ORDER` in `src/codevigrah/llm/__init__.py`.
3. Add a test in `tests/test_llm.py` (see the stub server in `tests/helpers.py`) and document it here.

## What gets sent

Only when you use an AI feature: the analysis summary (file list, roles, detected domain), a map of central files and their
symbols, and the most relevant source excerpts. Repository text is marked as data, not instructions, in every prompt.
