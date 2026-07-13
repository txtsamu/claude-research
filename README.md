# claude-research

Working notes from Claude Code sessions on the homelab — deployment write-ups, investigations, and troubleshooting logs. Written primarily so a *future* session (human or AI) can pick up context fast without re-deriving it.

## Structure

Flat, no folders. Research says metadata beats hierarchy for a collection this size — a deep PARA/Zettelkasten-style folder tree is overkill for a few dozen docs and just adds navigation cost. Each file has YAML frontmatter instead:

```yaml
---
type: how-to | troubleshooting | investigation
tags: [topic, service, tech]
created: YYYY-MM-DD
last_verified: YYYY-MM-DD   # last time someone confirmed the content still matches reality
status: current | historical | blocked
---
```

- **`type`** (loosely [Diataxis](https://diataxis.fr/)-flavored, adapted for a solo engineering log rather than product docs):
  - `how-to` — did X, here's the exact steps, reusable as a recipe
  - `troubleshooting` — something broke, here's the diagnosis + fix
  - `investigation` — explored whether X was possible / worth doing; may end in "no" or "not yet"
- **`status`** — `current` (believed accurate), `historical` (superseded but kept for context), `blocked` (investigation stalled on an external constraint)
- **`last_verified`** matters more than `created` for infra docs — treat anything not re-verified in a while as a *snapshot*, not live state. Specific values (IPs, ports, versions) can drift.

When adding a new doc: same flat layout, same frontmatter block, descriptive kebab-case filename (`service-what-happened.md`), one topic per file — don't bundle unrelated work into one doc just because it happened the same day.

## Index

### How-to / deployment

| Doc | Tags | Last verified |
|---|---|---|
| [local-lan-domains-caddy-pihole-setup.md](local-lan-domains-caddy-pihole-setup.md) | caddy, pihole, dns, https, podman, mikrotik, brave | 2026-07-13 |
| [oneterm-podman-quadlet-deploy.md](oneterm-podman-quadlet-deploy.md) | oneterm, podman, quadlet, systemd | 2026-06-26 |
| [oneterm-dark-mode.md](oneterm-dark-mode.md) | oneterm, frontend, vue | 2026-06-26 |
| [cekping-agent-podman-quadlet-deploy.md](cekping-agent-podman-quadlet-deploy.md) | podman, quadlet, systemd | 2026-07-11 |
| [llama-server-gemma4-qat-mtp-swap.md](llama-server-gemma4-qat-mtp-swap.md) | llama-server, gemma4, mtp, qat | 2026-06-24 |

### Troubleshooting

| Doc | Tags | Last verified |
|---|---|---|
| [llama-server-rocm-mtp-tuning.md](llama-server-rocm-mtp-tuning.md) | llama-server, rocm, gpu, mtp | 2026-07-01 |

### Investigations

| Doc | Tags | Status |
|---|---|---|
| [llama-server-dspark-gemma4-draft-investigation.md](llama-server-dspark-gemma4-draft-investigation.md) | llama-server, gemma4, dspark | blocked — upstream Qwen3-only, no Gemma4 support yet |

## Secrets policy

Never commit real credentials, tokens, or passwords — use placeholders (`<MIKROTIK_PASSWORD>`, `<CLOUDFLARE_API_TOKEN>`, etc.) and point to where the real value actually lives (usually a Hermes skill reference file kept out of this repo). See the "Notes on secrets" section in any doc that touches credentials for the established convention.
