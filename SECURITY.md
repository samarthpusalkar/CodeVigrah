# Security policy

## Reporting a vulnerability

Please do not open a public issue. Use **"Report a vulnerability"** on this repository's **Security** tab (GitHub private
vulnerability reporting). You should get a reply within a week. Fixes are released as soon as possible and credited unless you
prefer otherwise.

Only the latest release is supported.

## Security model

CodeVigrah analyses code written by strangers and may be exposed to strangers on the web, so it defends both ways.

**Analysed repositories are untrusted.**

* Nothing from a repository is executed. Python is parsed with `ast`; other languages are read with regular expressions.
* `git clone` runs with hooks disabled, symlinks checked out as plain files, no submodules, no LFS, and `file://` transport
  disabled. Only `https://` URLs on GitHub, GitLab, Bitbucket and Codeberg are accepted, and the URL is passed after `--`.
* File reads are confined to the repository root (no `..`, no symlink escapes).
* AI prompts mark repository text as data, not instructions. Claude Code runs with read-only tools; shell, edit and web tools are
  blocked. AI output can still be wrong or misleading: treat it as a colleague's opinion, not a fact.
* Everything shown in the browser is HTML-escaped, and the Content Security Policy blocks inline and third-party scripts except two
  pinned CDN files with integrity hashes.

**Visitors are untrusted** (public mode).

* AI settings cannot be changed over HTTP, local folders cannot be analysed or listed, and AI requests and analyses are rate-limited
  per client IP. Clones over `CODEVIGRAH_MAX_REPO_MB` are deleted.
* Request bodies are limited to 1 MB. Unexpected errors show visitors a generic message; the details go to the server log.
* API keys are read from the environment only and are never sent to the browser, logged, or written to disk.

**The browser is untrusted** (cross-site attacks against a local instance).

* POST requests must be `application/json` and same-origin (`Origin` and `Sec-Fetch-Site` are checked), which blocks cross-site
  request forgery from other websites.
* A server bound to localhost only answers requests whose `Host` header is a localhost name, which blocks DNS-rebinding attacks.
  Set `CODEVIGRAH_ALLOWED_HOSTS` when serving under a domain.

## Known limitations

* Python's `http.server` is not hardened for direct exposure to the internet. Put a reverse proxy or tunnel with HTTPS in front
  (see [docs/deployment.md](docs/deployment.md)).
* On a LAN without `--public`, anyone who can reach the port can change the AI provider settings.
* Rate limits are kept in memory and reset when the server restarts.
