---
type: how-to
tags: [opencode, compaction, config, context-window, deepseek, opencode-go, fedora]
created: 2026-11-29
last_verified: 2026-11-29
status: current
---

# Set OpenCode auto-compaction to trigger at 200k context

Goal: make OpenCode compact a conversation automatically once it reaches
200,000 tokens of context, instead of waiting for the model's near-limit
default.

Result: `~/.config/opencode/opencode.json` now carries

```json
"compaction": {
  "auto": true,
  "keep": { "tokens": 15000 },
  "buffer": 800000
}
```

The active model is `opencode-go/deepseek-v4.1-flash`, whose catalog window is
1,000,000 tokens. The compaction buffer is the room kept **free**, not the point
where compaction starts, so the threshold is `1,000,000 - 800,000 = 200,000`.

## Time estimate

About 3 minutes of wall clock, measured from the first config read to the final
`/api/config` check. Nothing builds or downloads. Reading the OpenCode
compaction docs and confirming the model's window in the running service was
most of it.

## 1. Confirm the model window

The setting is relative to the model's window, so check the actual window rather
than assuming 200k. The running service reports the resolved model, including
`limit`:

```sh
opencode api get /api/model/default
```

Relevant excerpt:

```json
"id": "deepseek-v4.1-flash",
"providerID": "opencode-go",
"limit": { "context": 1000000, "output": 384000 }
```

The compaction window is the model's `limit.input`, capped at `limit.context`;
here only `context` is set, so the window is 1,000,000 tokens.

## 2. Understand the two knobs

From the OpenCode compaction docs:

| Field | Default | Behavior |
| --- | ---: | --- |
| `auto` | `true` | Compact automatically near the context limit |
| `keep.tokens` | `15000` | Recent conversation kept verbatim beside the summary |
| `buffer` | `"15%"` | Share of the model's window kept free; compacts once the conversation reaches the rest |

`buffer` accepts either a percentage (`"1%"` to `"99%"`, decimals ok) or an
integer token count. A percentage scales with every model's window, so `"80%"`
would compact at 20% full on every model, including the 102,400-token local
model. A token count is the literal way to say "200k": it is ignored for any
model whose window is not larger than the count, and the default 15% applies
there.

With a 1M window and `buffer: 800000`, the conversation reaches 200k and
compaction starts. `auto` is already the default, but it is written out to make
the intent explicit.

## 3. Apply the config

Edit `~/.config/opencode/opencode.json` and add the block at the top level:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "opencode-go/deepseek-v4.1-flash",
  "compaction": {
    "auto": true,
    "keep": { "tokens": 15000 },
    "buffer": 800000
  }
}
```

OpenCode watches its config files and reloads them live, so no restart and no
`opencode service restart` are needed.

## 4. Verify

Check the file still parses, since a stray comma breaks startup:

```sh
python3 -m json.tool ~/.config/opencode/opencode.json > /dev/null && echo "JSON ok"
# JSON ok
```

Check the running service accepted the block:

```sh
opencode api get /api/config 2>/dev/null \
  | grep -o '"compaction":{[^}]*}[^}]*}' | head -3
# "compaction":{"auto":true,"keep":{"tokens":15000},"buffer":800000}
```

The schema at <https://opencode.ai/config.json> confirms `buffer` is
`integer | Percent`, so the integer form above is valid.

## Gotchas

- `buffer` is free space, not the trigger point. `"15%"` on a 1M model compacts
  at 850k. To compact at 200k you set 800k of buffer, or `"80%"`.
- A token buffer larger than or equal to a model's window is ignored and the
  default 15% applies to that model. Consequence here: the local
  `ternary-bonsai-2.5-27b` (102,400-token window) compacts at roughly 87k, not
  at 20k, while `deepseek-v4.1-flash` compacts at 200k.
- Background compaction is on by default. On this window OpenCode starts
  writing a summary about 60k tokens before the threshold (around 140k) and
  swaps it in at 200k. A summary that is never used still costs tokens.
- `keep.tokens` defaults to 15k of recent conversation preserved beside the
  summary. Raising it leaves less room for new work under the same 200k
  threshold.
- The threshold is derived from the catalog window at runtime. If the provider
  changes `limit.context` or `limit.input`, the trigger point moves even though
  `buffer` did not change.
- Limit overrides replace one field at a time: if you later set `limit.context`
  without `limit.input`, the window stays at the catalog's input limit.

## What was not verified

- No session was driven to 140k or 200k tokens to watch the actual
  `session.compaction.*` events fire. Verification stops at the config being
  valid JSON and present in the service's effective config, plus the model
  window read from the service.
- The effect on an already-running session's next request was not measured
  beyond the live config reload.

## References

- [OpenCode compaction guide](https://opencode.ai/docs/compaction) — buffer
  semantics (free space, percentage vs token count, per-model behavior),
  background compaction, and the model window definition.
- [OpenCode config reference](https://opencode.ai/docs/config#compaction) —
  the `compaction` block example and live reload behavior.
- [OpenCode config schema](https://opencode.ai/config.json) — confirms
  `buffer` accepts an integer or a percentage.
