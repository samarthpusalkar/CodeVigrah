# Running and hosting CodeVigrah

## Three ways to run it

| Mode | Command | Who can reach it | What changes |
|---|---|---|---|
| Private (default) | `./run.sh` | only this machine | everything enabled, including local folders |
| Your network | `./run.sh --host 0.0.0.0` | devices on your LAN | local folders off (unless `--allow-local-paths`); anyone on the LAN can change AI settings |
| Public | `./run.sh --host 0.0.0.0 --public` | the internet, behind HTTPS | AI settings locked, local folders refused, rate limits on |

## As a service on a Raspberry Pi (or any Linux box)

```bash
git clone https://github.com/samarthpusalkar/CodeVigrah.git ~/codevigrah
cp ~/codevigrah/.env.example ~/codevigrah/.env  # then edit it
nano ~/codevigrah/deploy/codevigrah.service     # set User, paths and flags
sudo cp ~/codevigrah/deploy/codevigrah.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now codevigrah
journalctl -u codevigrah -f                     # logs
```

To update: `git -C ~/codevigrah pull && sudo systemctl restart codevigrah`. Analyses saved by an older version are re-run
automatically from the clone on disk the first time they are opened.

## With Docker

```bash
cp .env.example .env              # add your AI keys
docker compose up -d --build      # serves on 127.0.0.1:8765, data in the codevigrah-data volume
```

`compose.yaml` turns on public mode and trusts the reverse proxy's `X-Forwarded-For` header. The image contains git and the
Anthropic SDK, and runs as an unprivileged user. Claude Code is not included: a hosted instance should use an API provider or
your own Ollama.

## Putting it on your own domain

You need HTTPS in front of CodeVigrah. Pick one:

### Option A: Cloudflare Tunnel (good for a Pi at home)

No open ports on your router, and HTTPS is handled for you. You need your domain's DNS on Cloudflare (the free plan is enough).

```bash
cloudflared tunnel login
cloudflared tunnel create codevigrah
cloudflared tunnel route dns codevigrah codevigrah.example.com
cloudflared tunnel run --url http://127.0.0.1:8765 codevigrah     # or install it as a service: cloudflared service install
```

Cloudflare's proxy gives up on a request after about 100 seconds. A slow first-time AI answer (likely with a local model) can
show an error even though CodeVigrah finishes it in the background and caches it; opening the chapter again shows the result.

### Option B: Caddy on a server with a public IP

Point the domain's DNS at the server, then use [`deploy/Caddyfile.example`](../deploy/Caddyfile.example). Caddy fetches and renews
the certificate automatically.

### Either way, set

```bash
CODEVIGRAH_PUBLIC=1
CODEVIGRAH_ALLOWED_HOSTS=codevigrah.example.com  # requests for any other Host header are refused
CODEVIGRAH_TRUST_PROXY=1                         # so rate limits see the visitor's IP, not the proxy's
```

Keep CodeVigrah itself listening on `127.0.0.1` (or the Docker port bound to `127.0.0.1`) so the only way in is through the proxy.

## Before you open it to the public

* **AI costs.** Visitors use *your* provider and your money or quota. The defaults allow 30 AI requests and 10 analyses per visitor
  IP per hour (`CODEVIGRAH_RATE_AI_PER_HOUR`, `CODEVIGRAH_RATE_ANALYZE_PER_HOUR`). A local Ollama model or a free Groq tier keeps
  costs at zero. Cached tour chapters and quizzes are shared by everyone, so popular repositories cost nothing after the first visit.
* **Disk.** Each analysed repository is cloned into the workspace. `CODEVIGRAH_MAX_REPO_MB` rejects big ones. Clean up old ones
  from time to time, e.g. a cron job that deletes workspace folders not modified for 30 days.
* **CPU.** `CODEVIGRAH_MAX_JOBS` limits how many analyses run at once; the rest wait in a queue.
* **Shared results.** In public mode every visitor sees the list of analysed repositories. Local folders are never listed.
* **Terms.** Check that your AI provider's terms allow serving other people with your account.

## Letting visitors bring their own key (not built yet)

A natural next step for a public site: each visitor pastes their own API key, which stays in their browser and is sent with each
request, so nobody spends your quota. The provider layer already separates configuration from use, which makes this a
contained change. Contributions are welcome.
