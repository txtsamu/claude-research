---
type: how-to
tags: [hermes, openwebui, podman, quadlet, sqlite, debugging]
created: 2026-07-19
last_verified: 2026-07-23
status: current
---

# Connecting Hermes Agent to Open WebUI (podman) — Setup + Debugging

**Host:** homelab (podman, systemd, rootful quadlets in `/etc/containers/systemd/`)
**Goal:** Expose the local Hermes Agent as an OpenAI-compatible model inside Open WebUI, then debug two follow-on issues: a broken new connection and a "why don't I see all the models" question.

---

## 1. Environment discovered before changing anything

Both Hermes and Open WebUI were already running as systemd-managed podman quadlets on this host — not a fresh install:

- `hermes-gateway.service` — already running (handles the Telegram bot integration too). Its API server config lives in `/root/.hermes/config.yaml` (via `hermes config set`) and gets materialized into `/root/.hermes/.env`.
- Open WebUI runs as a podman **pod** (`openwebui`), managed by quadlet files: `/etc/containers/systemd/openwebui.pod`, `openwebui-app.container`, `openwebui-data.volume`. Data (including its sqlite DB) persists in the `openwebui-data.volume`.

**Stale red herring:** `/root/.hermes/scripts/setup-openwebui-hermes-automated.sh`, `configure-openwebui-mcp.sh`, and `openwebui-credentials.txt` referenced a nonexistent "cybr node" at `192.168.50.40` with hardcoded SSH creds. This was leftover cruft from an unrelated/earlier session and had nothing to do with the actual local setup (openwebui-app running locally on port 8080). Ignored it rather than trusting it.

---

## 2. Enabling the Hermes API server

```bash
hermes config get API_SERVER_ENABLED   # was already true — set weeks earlier
hermes config env-path                 # /root/.hermes/.env
```

`hermes config show`/`set` writes to `config.yaml`; the actual runtime `.env` is generated from it. On this host the `.env` already had a working `API_SERVER_KEY` from an earlier session, but `config.yaml` had drifted out of sync (a stray `hermes config set API_SERVER_KEY <new-value>` created a mismatch). **Fix:** always check which key is actually live before generating a new one:

```bash
grep API_SERVER_KEY /root/.hermes/.env      # source of truth for the *running* process
curl -s -H "Authorization: Bearer <key-from-.env>" http://127.0.0.1:8642/v1/models
```

If it returns the model list, that's the real key — sync `config.yaml` to match it with `hermes config set API_SERVER_KEY <that-value>` rather than restarting the gateway with a new one.

Hermes API server listens on `0.0.0.0:8642` (not just loopback), which matters for step 3.

---

## 3. Podman networking: reaching the host from inside the pod

Open WebUI's container needs to reach Hermes running on the host. Podman (rootless or with a custom bridge network) provides a host-gateway alias:

```bash
podman exec openwebui-app getent hosts host.containers.internal
# 172.20.0.1  host.containers.internal host.docker.internal
```

Both `host.containers.internal` (podman-native) and `host.docker.internal` (docker-compat alias) resolve — so docs written for Docker Desktop's `host.docker.internal` translate directly to podman without changes.

---

## 4. Wiring the quadlet — and the gotcha that broke the restart

Added to `/etc/containers/systemd/openwebui-app.container`:

```ini
Environment=OPENAI_API_BASE_URL=http://host.containers.internal:8642/v1
Environment=OPENAI_API_KEY=<hermes-api-server-key>
```

**Gotcha:** `systemctl restart openwebui-app.service` alone fails:

```
openwebui-app.service: Bound to unit openwebui-pod.service, but unit isn't active.
Dependency failed for Open WebUI.
```

The app container is `BindsTo=` the pod's infra container. Restarting the app service stops the pod (since it's bound), but doesn't bring the pod back up automatically. Fix: always start the pod first, then the app:

```bash
systemctl daemon-reload
systemctl start openwebui-pod.service
sleep 2
systemctl start openwebui-app.service
```

Verified connectivity from inside the container:

```bash
podman exec openwebui-app curl -s -H "Authorization: Bearer <key>" http://host.containers.internal:8642/v1/models
# {"object": "list", "data": [{"id": "hermes-agent", ...}]}
```

---

## 5. Why the model still didn't show up in the dropdown

Even with correct env vars and a confirmed-reachable endpoint, `hermes-agent` did not appear in the Open WebUI model picker.

**Root cause:** `OPENAI_API_BASE_URL` / `OPENAI_API_KEY` (singular) are legacy *seed* env vars — Open WebUI only applies them when initializing a **brand-new** database. This instance had been running for 5+ days already with 3 OpenAI-compatible connections already persisted in its sqlite DB, so the env vars were silently ignored on every subsequent boot. This is a known/reported behavior, not specific to this setup (see sources).

Open WebUI stores connections as JSON-encoded lists in a `config` key/value table, not a single settings blob:

```python
import sqlite3, json
con = sqlite3.connect('/app/backend/data/webui.db')
cur = con.cursor()
for k in ['openai.enable', 'openai.api_base_urls', 'openai.api_keys', 'openai.api_configs']:
    cur.execute('SELECT value FROM config WHERE key=?', (k,))
    print(k, cur.fetchone()[0])
```

`api_base_urls`, `api_keys`, and `api_configs` are three **parallel arrays/dicts keyed by index** — connection *N* is `api_base_urls[N]` + `api_keys[N]` + `api_configs[str(N)]`. Fix: append to all three in lockstep, then restart (config is read into app state at startup, so a live DB edit needs a restart to take effect):

```python
urls = get('openai.api_base_urls'); urls.append('http://host.containers.internal:8642/v1')
keys = get('openai.api_keys');      keys.append('<hermes-key>')
configs = get('openai.api_configs')
configs[str(len(urls) - 1)] = {
    'enable': True, 'tags': [], 'prefix_id': '', 'model_ids': [],
    'connection_type': 'external', 'auth_type': 'bearer'
}
# UPDATE config SET value=?, updated_at=? WHERE key=? for each of the three keys
```

Then the pod/app restart dance from step 4. Confirmed via `podman exec openwebui-app curl ... /v1/models` returning `hermes-agent`, and the model appeared in the UI dropdown after logging in.

**Takeaway:** when an OpenAI-compatible connection env var "isn't working" on Open WebUI, check whether the DB already has connections persisted before assuming the env var itself is broken — on an already-initialized instance, the only reliable way to add a connection is via the Admin Settings UI or a direct DB/API write, not env vars.

---

## 6. "OpenAI: Network Problem" adding a jatevo.ai connection

Added a 4th connection (jatevo.ai) the same way (direct DB insert into the three arrays above). Open WebUI immediately errored with a generic **"OpenAI: Network Problem"** toast when testing/loading the connection.

This error string is a catch-all — it fires for *any* failure to fetch `/models` from the configured base URL, not just genuine network outages (confirmed via GitHub issues, see sources). Debugging approach: reproduce the exact call the backend makes, from inside the container, using the exact stored value.

```bash
podman exec openwebui-app python3 -c "... print stored openai.api_base_urls ..."
# ['https://api.deepseek.com', ..., 'https://api.jatevo.ai/v1 ']   <-- trailing space!
```

**Root cause:** the base URL was saved with a **trailing space** (`"https://api.jatevo.ai/v1 "`), almost certainly from a copy-paste. Reproduced the exact failure directly:

```bash
podman exec openwebui-app curl -m 5 "https://api.jatevo.ai/v1 /models"   # HTTP:000 (fails)
podman exec openwebui-app curl -m 5 "https://api.jatevo.ai/v1/models"    # HTTP:401 (reaches server, just needs auth)
```

That HTTP 000 → 401 delta is what confirmed the diagnosis before touching anything. Fix: strip whitespace from all stored `api_base_urls` entries in the DB (not just the new one — good hygiene to check all of them), then restart:

```python
urls = [u.strip() for u in get('openai.api_base_urls')]
```

Also noted along the way: `api.jatevo.ai` resolves to IPv6 (Cloudflare) addresses first, and this host/container has no working IPv6 route (`curl -6` timed out). Not the actual cause here since curl/httpx fall back to the IPv4 A record fine, but worth knowing if a *different* provider ever fails with a clean URL — check `getent ahostsv4` vs plain `getent hosts` to rule out IPv6-only resolution as a factor.

After the fix, `curl -H "Authorization: Bearer <key>" https://api.jatevo.ai/v1/models` returned real data and the connection worked in the UI.

---

## 7. "Why do I only see 3 GPT models, jatevo.ai has way more?"

Not a bug at all. Open WebUI just renders whatever the provider's `/v1/models` returns for the given key — and jatevo.ai's raw response for this key was genuinely only 3 models:

```json
{"object":"list","data":[{"id":"gpt-5.6-sol"},{"id":"gpt-5.5"},{"id":"gpt-5.4-mini"}]}
```

Checked jatevo.ai's own site: they advertise a much larger catalog (GLM 5.2, Kimi K3, Kimi K2.7 Code, Qwen 3.7 Max, NVIDIA Nemotron, Cerebras Gemma/GLM variants, etc.) across a three-tier access model:

- **Playground** — free, no key
- **Builder** — wallet-scoped "$JTVO-backed" API key (this account's tier)
- **Network** — reserved capacity / private pools

Per their docs, "wallet holdings unlock daily request capacity while application keys stay scoped and revocable" — i.e., the open-source models are gated behind wallet balance/tier, not exposed to a bare Builder key. Nothing to fix on the Open WebUI or Hermes side; would need to check the jatevo.ai dashboard/wallet to unlock the rest.

**Takeaway:** when a provider's model list looks short in Open WebUI, curl the provider's `/v1/models` directly with the same key before assuming Open WebUI is filtering something — it isn't; there's no client-side filtering on that list by default.

---

## Useful commands (recap)

```bash
# Inspect/patch Open WebUI's persisted OpenAI connections directly
podman exec openwebui-app python3 -c "
import sqlite3, json
con = sqlite3.connect('/app/backend/data/webui.db')
cur = con.cursor()
cur.execute(\"SELECT value FROM config WHERE key='openai.api_base_urls'\")
print(cur.fetchone()[0])
"

# Restart the pod correctly (bound-unit gotcha)
systemctl start openwebui-pod.service && sleep 2 && systemctl start openwebui-app.service

# Sanity-check a provider from inside the container with the exact stored value
podman exec openwebui-app curl -s -H "Authorization: Bearer <key>" "<base_url>/models"
```

---

## Sources

- [OpenAI-Compatible / Open WebUI docs](https://docs.openwebui.com/getting-started/quick-start/connect-a-provider/starting-with-openai-compatible/)
- [Connection Errors / Open WebUI troubleshooting](https://docs.openwebui.com/troubleshooting/connection-error/)
- [Custom OpenAI API Endpoints Do Not Load — open-webui#1826](https://github.com/open-webui/open-webui/issues/1826)
- [Custom models not visible in models list — open-webui#14543](https://github.com/open-webui/open-webui/issues/14543)
- [Potential Issues in API Base URL & Key Resolution Logic — open-webui#19684](https://github.com/open-webui/open-webui/discussions/19684)
- [connecting to api.minimaxi.com "OpenAI: Network Problem" — open-webui#21230](https://github.com/open-webui/open-webui/issues/21230)
- [OpenAI: Network Problem — open-webui#7910](https://github.com/open-webui/open-webui/discussions/7910)
