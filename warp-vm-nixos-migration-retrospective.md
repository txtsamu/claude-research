---
type: investigation
tags: [nixos, warp-vm, migration, retrospective, k3s, kubernetes, proxmox, cloudflare, metallb, hermes, technitium, caddy, evomem, lessons-learned]
created: 2026-09-10
last_verified: 2026-09-10
status: current
---

# warp-vm → NixOS migration: retrospective

The migration itself is documented ticket-by-ticket in [[warp-vm-nixos-migration-plan]] (20 tickets, T1-T20, tracked as txtsamu/claude-research#9-#28) — that doc is the log of *what happened*. This one is *what we'd do differently*, written the same day the migration finished so the lessons are fresh, not reconstructed later from memory.

Every finding below actually happened during this migration and is cross-referenced to the ticket/incident it came from. None of this is generic best-practice advice — it's specific to mistakes made and caught in this exact project.

## 1. A whole class of bugs came from "stale references outside the thing you're editing"

The single most repeated bug pattern across the entire migration, appearing in at least five different forms:

- **Caddy upstreams** (T14-T16, then again a bigger version in T19): migrating an app's backend IP and updating *one* Caddy instance (whichever one you're looking at) while a second, still-authoritative Caddy instance (or your own flake's not-yet-deployed config) keeps the old IP. T14-T16 broke live `.lan` traffic for real users this way before it was caught. `home`'s own `proxy.nix` carried pre-migration IPs for every app all the way to T19 because nobody had reason to open it after T4.
- **A third-party app's own config file, entirely outside the NixOS flake** (post-T19 incident): `hermes-gateway`'s `/root/.hermes/config.yaml` hardcoded `crawl4ai`'s pre-migration LoadBalancer IP. Nobody thought to check it because it's not part of the flake at all — it's Hermes' own runtime state, copied wholesale from `warp-vm` in T8 and never revisited.
- **A cloud provider's tunnel ingress config** (post-T19 incident, the `.ssamu.id` fix): 14 real production hostnames were routed through `warp-vm`'s *original* pre-T5 Cloudflare Tunnel. T5 created a new tunnel and verified it worked — with one throwaway test hostname — and never touched the 14 real ones, because they live in Cloudflare's dashboard/API, not in any file this migration was tracking.
- **The Kubernetes Node object itself** (post-T19 incident, the biggest one): changing `home`'s interface IP via `nixos-rebuild switch` doesn't retroactively update the IP kubelet already registered with the API server. Nothing about *editing NixOS config* touches that - it needs an explicit `systemctl restart k3s`.
- **Proxmox's own cloud-init VM config** (T19, caught by the user, not by me): `qm config`'s `ipconfig0` field kept the temp IP even after NixOS's own static network config was updated and applied. Two completely different systems (cloud-init's boot-time config vs. NixOS's runtime config) both think they own "this VM's IP," and only one of them was updated.

**The pattern**: any config that (a) lives outside the repo you're actively editing, (b) was populated once at initial setup and never touched again, or (c) is managed by a *different system* than the one you're changing, is invisible to "did I update the thing I'm working on" and needs its own explicit checklist entry.

**What we'd do differently**: before any cutover/IP-change ticket, grep for the *literal old IP/hostname string* across every surface that isn't the flake itself — `/root/.hermes/`, any other app's `/opt/*` install, the DNS provider's dashboard/API, the cloud provider's own VM metadata (cloud-init), and the orchestrator's own state (`kubectl get node -o wide`) — not just the NixOS config and the one reverse proxy you remembered.

## 2. Every network topology change on a k3s/MetalLB host needs `systemctl restart k3s`, full stop

This was the single largest post-migration incident (found and fixed the same day as T19, hours after close). MetalLB's speaker binds its memberlist protocol to whatever IP the Node object reports as `InternalIP`. `nixos-rebuild switch` changing the interface's actual IP does **not** trigger kubelet to re-register — the Node object silently kept reporting the *old* IP. MetalLB's speaker then failed to bind at all (`cannot assign requested address`), which broke every LoadBalancer IP announcement (took down every migrated `.lan` app) and cascaded into unrelated platform pods (Fleet, cert-manager, capi, rancher-turtles) CrashLoopBackOff-ing, because they depend on webhooks/leader-election that route through the cluster network in ways sensitive to a speaker outage.

The fix was one command (`systemctl restart k3s`) and resolved everything within a minute. The bug was **not** in the fix — it was in not treating "restart k3s" as a mandatory step of the IP-change ticket itself, the same way `--refresh` on `nixos-rebuild switch` became a standing habit after T2.

**What we'd do differently**: on any host running k3s, an IP/interface change is not "edit config, `nixos-rebuild switch`, done" — it's "edit config, `nixos-rebuild switch`, `systemctl restart k3s`, verify `kubectl get node -o wide` shows the new IP, *then* verify the app layer." Write this into the plan doc's own risk section next time, not just discover it live.

## 3. "Verified" needs to mean the *specific* thing the ticket cares about, not a nearby proxy for it

Every ticket in this migration was checked with a real functional test, not just "systemctl status active" — that discipline held throughout and caught real bugs (T9's camofox needed an actual browser snapshot, T10 needed a real Telegram command completing a real scrape, T12 needed a live Nagios query showing real check results). But it slipped in one specific way:

- **T5's Cloudflare Tunnel verification tested a throwaway hostname it created for the purpose** (`home-t5-test.ssamu.id`), not any of the 14 real production hostnames the tunnel was actually supposed to carry. The throwaway test passing gave real, honest confidence that *the tunnel mechanism itself* worked — but it accidentally became a stand-in for "the tunnel is fully migrated," which was false. The gap sat invisible for a full day until the *real* hostnames' backing tunnel died in T19's collateral cleanup and a user reported it.

**What we'd do differently**: when a ticket's job is "migrate N routes," verifying 1 of them (even a purpose-built, well-designed test route) is a test of the *mechanism*, not a completion check for the *ticket*. Enumerate every real route the ticket is responsible for up front (here: query the DNS zone / dashboard for the actual list) and check that list off explicitly, the same discipline already used for "12 real apps with live data verified."

## 4. Big cutovers can uncover live, uninventoried production workloads — budget for that

T1's initial inventory of `warp-vm` was thorough (DNS, Caddy, the app list, the MCP trio, tiktok-bot, camofox) and mostly accurate. But T19's cutover — which required actually enumerating everything still running on `warp-vm`'s original k3s cluster before taking its IP away — turned up `cekping-agent`, a real, continuously-running ping/uptime-check client reporting to an external server, created 2026-09-06, that had simply never made it into any prior inventory pass. It wasn't hidden or obscure; it just wasn't looked for, because nothing in T1-T18 required enumerating *every* pod on `warp-vm`'s cluster, only the ones already known to matter.

Caught in time because the cutover ticket forced a full `kubectl get pods -A` sweep as a side effect of needing to know what would break — not because of a dedicated audit step.

**What we'd do differently**: any ticket that will take a shared host/cluster offline should include an explicit "list everything still alive on it, not just what we already planned to migrate" step, run *before* the point of no return, not discovered mid-cutover. Cheap to do (one `kubectl get pods -A` / `systemctl list-units --state=running`), expensive to skip.

## 5. NixOS-FHS dynamic-linking is a recurring tax on anything not built by nixpkgs itself

This bit five separate times across the migration, each one individually small but adding up to a real, repeated cost:

| Where | What broke | Fix |
|---|---|---|
| T9 (camofox-browser) | Camoufox + bundled Node addons, dynamically linked for generic Linux | Wrap `ExecStart` in `pkgs.steam-run` |
| T11 (headroom-proxy) | onnxruntime/magika compiled wheel needs `libstdc++.so.6` at an FHS path | `LD_LIBRARY_PATH = "${pkgs.stdenv.cc.cc.lib}/lib"` (narrower than steam-run — just one missing shared lib, not a whole foreign binary) |
| Post-T19 incident | Hermes' own bundled Node binary (`/root/.hermes/node/bin/node`), invoked directly by `hermes-gateway`'s MCP subprocess spawning | Point the config at plain `node` instead, resolving via `PATH` to nixpkgs' `nodejs_22` (already wired into the systemd unit's PATH by T8, just not used by this one config entry) |
| Post-T19 incident | Hermes' own bundled `uv` binary, needed one-off to install missing Python deps | Wrap the one-off invocation in `steam-run` |
| (Not hit, but by design) | T12's checkmk agent controller binary | Confirmed **statically linked** via `ldd` *before* writing any NixOS module for it — zero wrapping needed |

**What we'd do differently**: whenever a migrated service ships its own vendored/downloaded binaries (not built by nixpkgs), check with `ldd <binary>` up front whether it's static or dynamic. Static → no special handling needed (T12). Dynamic → decide between `steam-run` (heavy, but handles anything, including a whole foreign browser) and a narrower `LD_LIBRARY_PATH` fix (light, but only fixes the specific missing library) *before* writing the module, rather than discovering the crash at runtime and patching reactively each time.

## 6. Hand-rolling a service's NixOS packaging vs. using its official module is a real, worth-stating-explicitly tradeoff

T3/T4/T5 (Technitium, Caddy, cloudflared) all used real, current, first-class `nixpkgs` modules (`services.technitium-dns-server`, `services.caddy`, `services.cloudflared`) — genuinely declarative, no hand-rolling, and they never generated a single bug across the whole migration. T8 (the Hermes MCP trio) instead hand-copied `/opt/hermes-venv` + `/opt/hermes-source` from `warp-vm` and wrote custom systemd units, because at the time that seemed like the pragmatic path.

It later turned out `hermes-agent` **does** ship an official NixOS flake module (`NousResearch/hermes-agent`'s `nix/nixosModules.nix`, confirmed real by fetching the actual `flake.nix`) that builds every Python dependency as a proper Nix derivation via `uv2nix` and auto-wraps bundled binaries into PATH — which would have prevented essentially every bug in §5's Hermes rows, and the missing-`messaging`-extras bug (Telegram/Discord/Slack all silently non-functional until patched post-incident) outright, since that module has a declarative `extraDependencyGroups = [ "messaging" ]` option for exactly this.

Decision made after finding this (2026-09-10, confirmed with the user): **don't re-architect T8 onto the official module.** The current hand-patched setup works, and Hermes' own docs call NixOS "Tier 2, best-effort" and recommend Docker/an FHS environment for production instead — so this isn't a mistake unique to this migration, it's the tradeoff the upstream project itself expects on this platform. Recorded as a deliberate, informed choice, not an oversight.

**What we'd do differently**: before hand-rolling a NixOS packaging approach for any third-party service, spend five minutes checking whether it ships its own flake/module first (`<project>/flake.nix`, a `nix-setup` or `nixos` page in its docs, a search for `services.<name>` in nixpkgs). If one exists and is reasonably maintained, it's very likely to save exactly the class of bugs in §5, even if (per Hermes' own caveat) it's not the vendor's most battle-tested path.

## 7. Secrets and credentials handling — the misses were both about *finding* a valid one, not storing one insecurely

Two separate incidents where a credential was needed mid-task and the found one didn't work:

- **Cloudflare API token, first attempt** (mid-`.ssamu.id` investigation): a token found via `evomem_search` was truncated mid-string by the search snippet itself, producing a token that failed with a confusing `Invalid request headers` / `Invalid format for Authorization header` error rather than a clean "wrong token" message — costly to debug because the error didn't point at truncation.
- **Cloudflare API token, second attempt**: the user's own first paste of a token (also matching one already visible in `hermes-gateway`'s `config.yaml`) came back a clean `Invalid API Token` — genuinely revoked/rotated, not a transcription error. Confirmed via a bypass of the usual command wrapper (`rtk proxy curl`) to rule out shell-escaping before concluding it was really invalid.

Neither incident involved committing a real secret anywhere (this repo's secrets policy held throughout) — both were about *locating a currently-valid* one when several stale copies existed in different places (an old evomem-indexed session, a live but possibly-outdated app config, a freshly dashboard-generated one).

**What we'd do differently**: when a search tool returns a credential-shaped string, treat it as *possibly truncated by the search snippet* and verify its length/shape before use, rather than assuming a search hit is a complete value. When a token fails, verify with the simplest possible call (`/user/tokens/verify`) via a raw, unfiltered path before concluding the credential itself is bad — a wrapped/filtered command's own quirks are a more common cause of "invalid" than the token being generated wrong.

## What actually went right (worth repeating, not just what to fix)

- **Real functional verification, not "service is active," as a standing bar** for every one of 20 tickets — this is *why* every bug above was caught at all, either during its own ticket or shortly after.
- **Never batching cutovers**: T14-T18 (and the retrospective policy after T14's Caddy miss) enforced "migrate one app, verify, stop the old copy, *then* move to the next" — the one deliberate exception (batching all of T19's "stop everything on `warp-vm`" in one pass) is exactly where the biggest incident came from, which is itself evidence for the rule.
- **Distinguishing pre-existing/out-of-scope breakage from migration-caused regressions at every step** (jellyfin/grafana/bastion/px2/rancher.lan's original backend, syncyomi) rather than either silently ignoring them or scope-creeping into fixing everything found along the way.
- **Asking before hard-to-reverse or outward-facing actions** (the warp/home naming decision, the cekping-agent discovery, the `shutdown -h now` approval, the dangling-DNS-records-or-not choice before deleting the dead tunnel) rather than guessing at what the user would want on a real production system.
