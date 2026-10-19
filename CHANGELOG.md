# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Read-aloud for the ear: a listening script instead of the page text. Without AI, rules turn paths, identifiers, symbols,
  code blocks, tables and Mermaid diagrams into speech; for tour chapters the AI writes a script for listening in the
  background, cached per commit. The page keeps the written text and highlights the paragraph being heard.
- Natural voices from a speech server (OpenAI-style `/v1/audio/speech`), cached per sentence, with the browser's voices as the
  fallback. `contrib/speech-server/` runs Kokoro and Piper on a Raspberry Pi 5. `CODEVIGRAH_TTS_*` settings, an optional
  background pre-voicing of tour chapters, and a per-visitor limit on fresh audio.
- The player shows the sentence being spoken, which script is used, and a switch to compare it with the plain reading.

## [0.1.0] - 2026-10-19

First public release.

### Added

- Guided tour, skill check, overview, architecture, code map, dependency graph, domain lens, design decisions, hotspots,
  concept cards, change planner, chat, Markdown report, file inspector and read-aloud.
- AI providers behind one interface with ordered fallback: Claude Code, Anthropic API (official SDK, streaming, server-side
  refusal fallback), Ollama, Groq and any OpenAI-compatible server. Providers that cannot open files get source excerpts.
- Settings dialog to choose the provider order, model, base URL and key.
- Public mode (`--public`): locked AI settings, no local folders, per-IP rate limits, repository size limit.
- Configuration through environment variables and `.env`, documented in `.env.example`.
- `codevigrah analyze` and `codevigrah report` commands; installable package with a `codevigrah` entry point.
- Dockerfile, Compose file, systemd unit and Caddy example; docs for AI providers, deployment and architecture.
- Test suite (unittest/pytest) with a fixture repository and a stub AI server; CI on Python 3.10–3.14.
- Analyses carry a schema version; ones saved by an older version are re-analysed automatically from the local clone.

### Changed

- Restructured into a `src/` package: the analyzer split into one module per stage, the knowledge base into one module per kind
  of rule, the server into routing, endpoints, app state and rate limiting, and the UI into a stylesheet and one script per feature.

### Fixed

- Python 3.10 and 3.11 support (an f-string needed 3.12).
- Opening the tour for an analysis saved by an older version failed in static mode.
- AI chapters cached for a local folder (no git, or uncommitted edits) were reused after the files changed; local folders
  are now stamped by a content fingerprint.
- Concurrent requests could crash while listing in-flight AI generations.

### Security

- Escaped a repository-controlled file path that could inject HTML into the page.
- Added a Content Security Policy and other security headers, Subresource Integrity for CDN scripts, CSRF and DNS-rebinding
  protection, request size limits, and removed server file paths from API responses.
