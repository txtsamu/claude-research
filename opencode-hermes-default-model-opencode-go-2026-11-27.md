---
type: how-to
tags: [opencode, hermes, model, default, opencode-go, deepseek, config, nixos, home, fedora]
created: 2026-11-27
last_verified: 2026-11-27
status: current
---

# Point OpenCode and the Hermes agent at the same default model (OpenCode Go)

Goal: the local OpenCode on `fedora` and the Hermes agent on `home` (192.168.50.200, NixOS) should both default to the model this session was actually running: `deepseek-v4.1-flash` through the OpenCode Go provider.

Result: OpenCode's `~/.config/opencode/opencode.json` now says `"model": "opencode-go/deepseek-v4.1-flash"`, and Hermes' `/root/.hermes/config.yaml` now uses `provider: opencode-go`, `default: deepseek-v4.1-flash`, `base_url: https://opencode.ai/zen/go/v1`. The gateway was restarted and reports the new model. A raw chat completion with the stored key returned HTTP 200.

## Time estimate

About 6 minutes of wall clock, measured from the local config backup at 13:21:54 to the final verification at roughly 13:27. Nothing builds or downloads. The only wait over a minute is the gateway restart plus 8 seconds of settle time; most of the rest was reading Hermes' source to confirm the exact config keys its model picker writes.

## 1. Find the model actually in use by OpenCode

The config file is the authority for the *default*, but the model the current session runs can differ. The session's model is visible in the state store:

```sh
cat ~/.local/state/opencode/*.json | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["recent"][0])'
# {'providerID': 'opencode-go', 'modelID': 'deepseek-v4.1-flash'}
```

Meanwhile `~/.config/opencode/opencode.json` still had the old Orvix default:

```json
"model": "orvix/deepseek-v4.1-flash-uncensored"
```

That mismatch is the whole reason for this doc: the file said Orvix, the running session used OpenCode Go.

## 2. Change the OpenCode default

Back up first, then replace the one line:

```sh
cp ~/.config/opencode/opencode.json ~/.config/opencode/opencode.json.bak-pre-model-default-$(date +%Y%m%d-%H%M%S)
```

Edit `model` to:

```json
"model": "opencode-go/deepseek-v4.1-flash"
```

Validate the file, since a stray comma here breaks startup:

```sh
python3 -c "import json;json.load(open('/home/moo/.config/opencode/opencode.json'));print('valid json')"
```

OpenCode reads this at startup, so existing sessions keep their model until restarted; new sessions pick it up. To switch the current TUI session, use `/models`.

## 3. Confirm how Hermes stores its model

Hermes on `home` runs as **root** from a systemd unit (`HERMES_HOME=/root/.hermes`), so `moo`'s `~/.hermes` is the wrong tree. The live values:

```sh
ssh moo@home 'sudo -n sed -n "1,8p" /root/.hermes/config.yaml'
```

```yaml
model:
  context_length: 1000000
  default: orvix/deepseek-v4.1-flash
  provider: orvix
  base_url: https://api.orvix.id/v1
```

The relevant endpoint and credential were already there. A provider registry lookup shows Hermes ships a built-in `opencode-go` provider, and the credential pool holds the key under `/root/.hermes/auth.json`:

```sh
ssh moo@home 'sudo -n python3 -c "
import json
d=json.load(open(\"/root/.hermes/auth.json\"))
e=dict(d[\"credential_pool\"][\"opencode-go\"][0]); e.pop(\"secret_fingerprint\",None)
print(json.dumps(e,indent=2))
"'
```

```json
{
  "label": "OPENCODE_GO_API_KEY",
  "auth_type": "api_key",
  "source": "env:OPENCODE_GO_API_KEY",
  "base_url": "https://opencode.ai/zen/go/v1"
}
```

The key itself lives in `/root/.hermes/.env` as `OPENCODE_GO_API_KEY=...`.

## 4. Prove the model exists on that endpoint

List the models the Go relay actually serves, from the host so the key never lands in a shell argument on the client:

```sh
ssh moo@home "sudo -n bash -s" <<'SCRIPT'
KEY=$(grep '^OPENCODE_GO_API_KEY=' /root/.hermes/.env | cut -d= -f2-)
curl -s https://opencode.ai/zen/go/v1/models -H "Authorization: Bearer $KEY" \
  | python3 -c 'import sys,json; print([m["id"] for m in json.load(sys.stdin)["data"]])'
SCRIPT
```

`deepseek-v4.1-flash` is in that list (display name "DeepSeek V4.1 Flash 1017"). Do not assume the provider prefix survives into the API request: Hermes' `normalize_opencode_model_id()` strips `opencode-go/` and sends the bare slug, which is why the config default is the bare `deepseek-v4.1-flash` and not `opencode-go/deepseek-v4.1-flash`.

## 5. Write the four model keys with Hermes' own tool

`hermes model` is interactive only, so use `hermes config set` for the non-interactive path. Mirror exactly what the model picker persists (`model_setup_flows_common.py::_persist_model`): default, provider, base_url, api_mode.

```sh
ssh moo@home 'for kv in "model.default deepseek-v4.1-flash" "model.provider opencode-go" "model.base_url https://opencode.ai/zen/go/v1" "model.api_mode chat_completions"; do set -- $kv; sudo -n /opt/hermes-venv/bin/python /opt/hermes-source/hermes_cli/main.py config set "$1" "$2"; done'
```

Each write prints a confirmation, e.g. `✓ Set model.default = deepseek-v4.1-flash in /root/.hermes/config.yaml`.

Watch for this warning, which shows why the order matters:

```text
⚠ model.base_url (https://api.orvix.id/v1) was set under orvix and still applies to opencode-go — requests go there.
```

A stale `base_url` silently points the new provider at the old API host. Set it in the same batch.

Verify:

```sh
ssh moo@home 'sudo -n /opt/hermes-venv/bin/python /opt/hermes-source/hermes_cli/main.py config get model'
```

```yaml
context_length: 1000000
default: deepseek-v4.1-flash
provider: opencode-go
base_url: https://opencode.ai/zen/go/v1
api_mode: chat_completions
```

## 6. Restart the gateway

The running gateway process was four days old and held the old model in memory. No active sessions were listed, so a restart was safe:

```sh
ssh moo@home 'sudo -n cat /root/.hermes/runtime/active_sessions.json'
# {"entries": []}
```

The documented command fails on this host:

```sh
ssh moo@home 'sudo -n /opt/hermes-venv/bin/python /opt/hermes-source/hermes_cli/main.py gateway restart --system'
# OSError: [Errno 30] Read-only file system: '/etc/systemd/system/hermes-gateway.service'
```

`--system` first tries to refresh the unit file, and `/etc/systemd/system` is read-only here. Restart the already-loaded unit directly instead:

```sh
ssh moo@home 'sudo -n systemctl restart hermes-gateway && echo RESTART_OK; sleep 8; systemctl is-active hermes-gateway'
# RESTART_OK
# active
```

The journal prints one scary line during the switch, `hermes-gateway.service: Failed with result 'exit-code'`; that belongs to the stop half of the restart. The new process then logs `☤ Hermes Gateway Starting...` and stays `active`. Confirm with a fresh MainPID.

## 7. Verify

Agent-level view:

```sh
ssh moo@home 'sudo -n /opt/hermes-venv/bin/python /opt/hermes-source/hermes_cli/main.py status' | grep -i -E "model|provider|gateway"
# Model:        deepseek-v4.1-flash
# Provider:     OpenCode Go
# Gateway:      ✓ running
```

Wire-level check. The Go endpoint rejects plain requests with `MissingSessionID`, so include a session header:

```sh
ssh moo@home "sudo -n bash -s" <<'SCRIPT'
KEY=$(grep '^OPENCODE_GO_API_KEY=' /root/.hermes/.env | cut -d= -f2-)
curl -s -o /tmp/oc.json -w 'HTTP %{http_code}\n' https://opencode.ai/zen/go/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -H "x-opencode-session: 00000000-0000-4000-8000-000000000000" \
  -d '{"model":"deepseek-v4.1-flash","messages":[{"role":"user","content":"say ok"}],"max_tokens":5}'
head -c 200 /tmp/oc.json; rm -f /tmp/oc.json
SCRIPT
```

```text
HTTP 200
{"id":"gw-...","object":"chat.completion","model":"deepseek-v4.1-flash",...}
```

## Gotchas

- The OpenCode config default and the model a session actually runs are separate. Check the state store before "syncing" anything.
- Hermes on `home` is not `moo`'s agent. Everything lives under `/root/.hermes`, so every read needs `sudo -n` and a `bash -c` wrapper when globbing (the `moo` shell cannot expand `/root/*` patterns itself).
- `hermes config set model.provider` warns rather than fixes a stale `model.base_url`. Always set base_url in the same batch.
- `hermes gateway restart --system` cannot rewrite the unit on this host (read-only `/etc/systemd/system`). Use `systemctl restart hermes-gateway`.
- The OpenCode Go relay requires an `x-opencode-session` header on chat completions. A bare curl gets HTTP 400 `MissingSessionID`.
- `providers.orvix` and `fallback_providers` in the Hermes config were left untouched. They are dormant while the default points at opencode-go, but a fallback turn can still use DeepSeek direct.

## What was not verified

- No full agent turn was run through the restarted gateway (no Telegram/Discord message round trip). Verification stops at `hermes status` plus a direct HTTP 200 from the same endpoint and key.
- The gateway's rendered systemd unit still carries whatever content existed before this session; only the process was restarted, not the unit. The outdated-unit warning from `gateway status` remains until the host is writable or the unit is reinstalled.
- OpenCode's behavior in an already-running TUI was not tested; only fresh-start loading is assumed.

## References

- [OpenCode Go docs](https://opencode.ai/v2/docs/console/go/) — endpoint, and the `x-opencode-session` requirement surfaced by the API error.
- [Hermes model catalog reference](https://hermes-agent.nousresearch.com/docs/reference/model-catalog) — provider/model catalog the local `model_catalog` config points at.
- [opencode-orvix-provider-from-hermes-agent-2026-11-22.md](opencode-orvix-provider-from-hermes-agent-2026-11-22.md) — the earlier, now superseded setup that pointed OpenCode at Orvix.
