---
type: how-to
tags: [opencode, hermes, orvix, provider, model, api-key, config, fedora, home, nixos]
created: 2026-11-22
last_verified: 2026-11-22
status: historical
---

# Point OpenCode at Orvix using the Hermes agent's provider/model

> **Superseded 2026-11-27:** both OpenCode and Hermes now default to `opencode-go/deepseek-v4.1-flash`. See [opencode-hermes-default-model-opencode-go-2026-11-27.md](opencode-hermes-default-model-opencode-go-2026-11-27.md). The Orvix provider block still exists but is no longer the default; this page remains useful as the recipe for a custom OpenAI-compatible provider with a file-based key.

Goal: read the inference provider that the Hermes agent uses on `home` (192.168.50.200, NixOS), then make the local OpenCode on `fedora` use the same provider (`orvix`) and the same model (`deepseek-v4.1-flash-uncensored`) as its default.

Result: OpenCode v2.3.2 on `fedora` now defaults to `orvix/deepseek-v4.1-flash-uncensored` through `https://api.orvix.id/v1`, with the API key read from a local 0600 file. Verified with a real completion and a real bash tool call.

## Time estimate

About 5 minutes end to end (estimate, from the backup timestamp 11:48:57 to the last verification at 11:49:40). The slow parts were the two `opencode run` smoke tests, a few seconds each. Nothing here builds or downloads.

## 1. Find the real Hermes config

`home` runs Hermes as **root** from a systemd unit, not as `moo`. Running `hermes dump` as `moo` reports an empty agent:

```sh
ssh home '/opt/hermes-venv/bin/hermes dump'   # model: (not set), provider: (auto)
```

The live gateway uses `HERMES_HOME=/root/.hermes`:

```sh
ssh home 'systemctl cat hermes-gateway.service | grep -E "Environment=|ExecStart|User="'
# Environment=HERMES_HOME=/root/.hermes
# ExecStart=/opt/hermes-venv/bin/python -m hermes_cli.main gateway run
# User=root
```

So ask the root instance:

```sh
ssh home 'sudo -n env HOME=/root /opt/hermes-venv/bin/hermes dump | head -10'
```

```text
model:            orvix/deepseek-v4.1-flash-uncensored
provider:         orvix
```

The same values are in `/root/.hermes/config.yaml`:

```yaml
model:
  context_length: 1000000
  default: orvix/deepseek-v4.1-flash-uncensored
  provider: orvix
  base_url: https://api.orvix.id/v1
...
providers:
  orvix:
    base_url: https://api.orvix.id/v1
    key_env: ORVIX_API_KEY
    model: orvix/deepseek-v4.1-flash-uncensored
```

## 2. Extract the API key without printing it

The key lives in `/root/.hermes/.env` as `ORVIX_API_KEY=...` and is loaded by Hermes at runtime. Copy it straight into a local secret file (no echo, no trailing newline):

```sh
mkdir -p ~/.config/opencode/secrets
ssh home "sudo -n grep -m1 '^ORVIX_API_KEY=' /root/.hermes/.env | cut -d= -f2- | tr -d '\"'" > ~/.config/opencode/secrets/orvix-api-key
tr -d '\n' < ~/.config/opencode/secrets/orvix-api-key > /tmp/k && mv /tmp/k ~/.config/opencode/secrets/orvix-api-key
chmod 700 ~/.config/opencode/secrets && chmod 600 ~/.config/opencode/secrets/orvix-api-key
wc -c < ~/.config/opencode/secrets/orvix-api-key   # 566
```

The trailing-newline strip matters: OpenCode substitutes `{file:...}` verbatim, and a newline would land inside the `Authorization` header.

## 3. Check the upstream catalog and prove tool calling

List models with the key (run from `home` so the key never leaves the host in a shell arg):

```sh
ssh home "key=\$(sudo -n grep -m1 '^ORVIX_API_KEY=' /root/.hermes/.env | cut -d= -f2- | tr -d '\"'); \
  curl -s -H \"Authorization: Bearer \$key\" https://api.orvix.id/v1/models"
```

The target model appears, but with `"tools": false` in its capability block:

```json
{"id":"orvix/deepseek-v4.1-flash-uncensored","object":"model","owned_by":"orvix",
 "capabilities":{"vision":false,"reasoning_effort":false,"json_schema":false,
 "seed":false,"tools":false,"tool_choice":true,...},
 "min_tier":"pro","available":true}
```

Do not trust that flag alone. A direct tool-call request returns a proper `tool_calls` response, so the flag is metadata only:

```sh
ssh home "key=\$(sudo -n grep -m1 '^ORVIX_API_KEY=' /root/.hermes/.env | cut -d= -f2- | tr -d '\"'); \
  curl -s https://api.orvix.id/v1/chat/completions -H \"Authorization: Bearer \$key\" \
  -H 'Content-Type: application/json' \
  -d '{\"model\":\"orvix/deepseek-v4.1-flash-uncensored\",\"messages\":[{\"role\":\"user\",\"content\":\"Call the ping tool with value 7.\"}],\"tools\":[{\"type\":\"function\",\"function\":{\"name\":\"ping\",\"parameters\":{\"type\":\"object\",\"properties\":{\"value\":{\"type\":\"integer\"}},\"required\":[\"value\"]}}}],\"tool_choice\":\"auto\",\"max_tokens\":100}'"
```

```json
"tool_calls":[{"function":{"arguments":"{\"value\":7}","name":"ping"},"id":"call_...","type":"function"}]
```

## 4. Add the provider to OpenCode V2 config

OpenCode V2 uses `providers` (plural), keyed by provider ID, with `package`, `settings.baseURL`, and `settings.apiKey`. `provider` (singular) is the deprecated V1 shape. Backup first:

```sh
cp -a ~/.config/opencode/opencode.json ~/.config/opencode/opencode.json.bak-pre-orvix-$(date +%Y%m%d-%H%M%S)
```

Then add to `~/.config/opencode/opencode.json` (existing settings kept):

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "model": "orvix/deepseek-v4.1-flash-uncensored",
  "providers": {
    "orvix": {
      "name": "Orvix",
      "package": "@opencode/ai/providers/openai-compatible",
      "settings": {
        "baseURL": "https://api.orvix.id/v1",
        "apiKey": "{file:~/.config/opencode/secrets/orvix-api-key}"
      },
      "models": {
        "deepseek-v4.1-flash-uncensored": {
          "modelID": "orvix/deepseek-v4.1-flash-uncensored",
          "name": "DeepSeek V4.1 Flash Uncensored",
          "limit": { "context": 1000000, "output": 131072 },
          "capabilities": { "tools": true }
        }
      }
    }
  }
}
```

Why these fields:

- `modelID` sends the exact upstream ID Hermes sends (`orvix/deepseek-v4.1-flash-uncensored`), while the `models` key is the local alias.
- `limit.context: 1000000` came from Hermes' `model.context_length`; the API does not report context size.
- `limit.output: 131072` is the API's `max_output_tokens`.
- `capabilities.tools: true` overrides the misleading catalog flag.

## 5. Verify

Config load and model listing:

```sh
python3 -m json.tool ~/.config/opencode/opencode.json > /dev/null && echo "JSON OK"
opencode models | grep -i orvix
# orvix/deepseek-v4.1-flash-uncensored
```

Real completion through OpenCode:

```sh
opencode run --archived "Reply with exactly: OK"
# > build · deepseek-v4.1-flash-uncensored
# OK
```

Real tool call through OpenCode:

```sh
opencode run --archived "Use the bash tool to run: echo TOOLS_OK"
# $ echo TOOLS_OK
# TOOLS_OK
# The bash tool works.
```

Config changes apply without restarting the OpenCode service. New sessions pick up the default model; an already-running session keeps its model, change it from `/models`.

## Gotchas

- `hermes dump` as `moo` is misleading: the configured agent is the root one under `/root/.hermes`. Check `systemctl cat hermes-gateway.service` for `HERMES_HOME` and `User=`.
- `ORVIX_API_KEY` is not in the systemd unit environment and not in `/root/.hermes/auth.json`; Hermes loads it from `/root/.hermes/.env`.
- The Orvix `/v1/models` payload says `"tools": false` for `deepseek-v4.1-flash-uncensored` even though tool calls work. Do not disable `capabilities.tools` based on it.
- OpenCode V2 wants `providers` + `settings.apiKey`/`settings.baseURL`. Old guides with `provider` and `options.baseURL` are V1 and are marked deprecated in the schema.
- `{file:...}` insertion is literal; strip trailing newlines from the key file.
- The old `~/.config/opencode/opencode.json` had no `model` key, so the running default came from elsewhere (the OpenCode Go subscription). Adding `model` now overrides it globally.

## Not verified

- Context window of 1,000,000 was taken from Hermes config, not probed against the API.
- Whether an existing TUI session switches model after `/reload` (assumed no; use `/models`).
- Orvix pricing and rate limits are not configured in OpenCode, so cost reporting for this provider will show zero.

## References

- [OpenCode config](https://opencode.ai/docs/config)
- [OpenCode providers](https://opencode.ai/docs/providers)

## Related

- [[hermes-mcp-servers-audit-cloudflare-truenas-2026-11-10]]
- [[home-nixos-flake-lock-update-check-2026-11-06]]
- [[hermes-to-evonic-migration]]
