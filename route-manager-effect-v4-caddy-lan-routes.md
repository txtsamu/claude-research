---
type: how-to
tags: [effect-ts, effect-v4, caddy, nixos, home, k3s, technitium, dns, route-manager, systemd-path]
created: 2026-10-09
last_verified: 2026-10-09
status: current
---

# route-manager: Effect v4 web app that adds `*.lan` routes to Caddy (+ DNS)

Goal: a web app at `route.lan` where a new `name.lan` -> `host:port` route can be added in one form, instead of editing `home-nixos` `proxy.nix`, opening a PR, and adding a Technitium record by hand.

Code: private repo `txtsamu/route-manager` (local `~/route-manager`). Also pushed to the private Forgejo repo `samu/route-manager` (http://192.168.50.249:3500, public at git.ssamu.id) as remote `forgejo`; there is no automatic sync, so push both by hand (`git push origin main && git push forgejo main`). NixOS side: `txtsamu/home-nixos` PR #7. Runs as a Deployment on home's k3s (namespace `homelab`).

## Design decision: how routes reach Caddy

home's Caddy is NixOS-generated (`/etc/caddy/caddy_config`, rendered from `hosts/home/proxy.nix`). Research on Caddy's admin API (see References) gave this:

- Granular `POST .../routes` calls change the running config, and Caddy autosaves to `autosave.json`, but only `--resume` reads it back.
- NixOS's `ExecReload` is `caddy reload --config /etc/caddy/caddy_config --force`, which replaces the whole running config. So API-added routes disappear on every `nixos-rebuild` or reload.

Chosen instead (survives rebuilds, needs no admin-API access, no root in the app):

1. App owns `routes.json` (state) and `routes.caddy` (rendered Caddy sites) in `/data` = hostPath `/var/lib/route-manager`.
2. NixOS Caddyfile has `import /var/lib/route-manager/*.caddy` (glob, so a missing file is not an error).
3. systemd path unit `caddy-routes-reload` (`PathChanged=/var/lib/route-manager/routes.caddy`) runs `systemctl reload caddy.service`. The app writes the file **in place** (truncate+write, never rename) so the close-after-write event fires. A bad snippet makes the reload fail and Caddy keeps the old config.
4. App also calls the Technitium API to create/delete the A record.

Two safety rules baked in because the rendered text goes into a Caddyfile:
- Schema validation: name `^[a-z0-9]([a-z0-9-]{0,28}[a-z0-9])?$`, upstream `host:port` only (no scheme, space, brace, newline), port 1-65535. Tested with newline/brace injection attempts (all rejected, HTTP 400).
- `RESERVED_NAMES` env lists every site already in `proxy.nix`; a duplicate site address would make `caddy reload` fail.

## Why Effect v4, and what differs from v3

First attempt used Effect v3 (`effect@3.22`, `@effect/platform@0.97`); switched when asked for "Effect v4 stable" (`npm view effect dist-tags` -> `latest: 4.0.2`). v4 notes that cost time:

- `@effect/platform` is gone; HTTP lives in `effect/http` and `effect/http-api`. Only `@effect/platform-node@4.0.2` is a separate package. `FileSystem`, `Path`, `Semaphore` are exported from `effect` itself.
- The `effect` npm package ships its own docs: `node_modules/effect/ai-docs/src/**` (e.g. `51_http-server/10_basics.ts`, `50_http-client/10_basics.ts`) and `AGENTS.md`. These were the most reliable reference; third-party mirrors mix v3 and v4 names.
- API renames I hit: `Context.Tag` -> `Context.Service<Self, Shape>()("id")`; `Schema.pattern`/`filter` -> `Schema.check(Schema.isPattern(re))` / `Schema.makeFilter`; `Schema.Union([..])` takes an array; `Config.string` -> `Config.String` (also `Int`, `Redacted`); `Effect.catchAllCause` -> `Effect.catchCause`; errors set status inline: `Schema.TaggedError<X>()("X", {...}, { httpApiStatus: 409 })`; `HttpApiEndpoint.get("name", "/path", { success, error, params, payload })`; HTML responses via `Schema.String.pipe(HttpApiSchema.asText({ contentType: "text/html" }))`; serve with `HttpRouter.serve(HttpApiBuilder.layer(Api, { openapiPath })).pipe(Layer.provide(NodeHttpServer.layer(createServer, { port })))`.
- tsconfig: imports use `.ts` extensions, so `"rewriteRelativeImportExtensions": true` is needed for `tsc` to emit `.js` imports.
- npm dead ends: `npm i @effect/platform@^0.9` resolved to `0.9.0` (semver caret on 0.x) and hit ERESOLVE; `@effect/vitest@4.0.2` conflicted with v3 peers. Moot after the switch to v4, but pin exact versions when mixing 0.x packages.

## Steps run

```bash
# 1. scaffold + implement (src/: domain, caddy, config, dns, manager, api, handlers, ui, main)
cd ~/route-manager
npm i effect@4.0.2 @effect/platform-node@4.0.2 && npm i -D typescript tsx vitest @types/node@22
npx tsc --noEmit && npx vitest run          # 18 tests: renderer, validation/injection, manager add/remove/persist

# 2. run locally and poke the API
DATA_DIR=$(mktemp -d) PORT=18080 RESERVED_NAMES=dns,nas npx tsx src/main.ts &
curl -X POST localhost:18080/api/routes -H 'content-type: application/json' -d '{"name":"grafana","upstream":"192.168.50.20:3000"}'

# 3. image -> k3s containerd (no registry on this cluster)
podman build -t localhost/route-manager:0.1.0 .
podman save localhost/route-manager:0.1.0 | ssh home 'sudo k3s ctr images import -'

# 4. Technitium API token for the app (admin password lives in agenix on home; never printed)
ssh home 'PW=$(sudo sed -n "s/^DNS_SERVER_ADMIN_PASSWORD=//p" /run/agenix/technitium-admin-password)
  curl -s http://127.0.0.1:5380/api/user/createToken --data-urlencode user=admin --data-urlencode "pass=$PW" --data-urlencode tokenName=route-manager'
# -> kubectl -n homelab create secret generic route-manager --from-literal=TECHNITIUM_TOKEN=<token>

# 5. deploy
kubectl apply -f k8s/route-manager.yaml     # Service clusterIP pinned to 10.43.200.80

# 6. NixOS side (separate PR in txtsamu/home-nixos): route.lan upstream 10.43.200.80:80, extraConfig import,
#    tmpfiles dir, path unit + oneshot reload service. Merge after CI, then:
ssh home 'sudo nixos-rebuild switch --flake github:txtsamu/home-nixos#home --refresh'

# 7. one-time DNS record for route.lan itself (the app can only create records for routes it manages)
curl -H "Authorization: Bearer $TOKEN" -X POST http://192.168.50.200:5380/api/zones/records/add \
  --data-urlencode domain=route.lan --data-urlencode zone=lan --data-urlencode type=A \
  --data-urlencode ipAddress=192.168.50.200 --data-urlencode overwrite=true
```

(On home use `sudo k3s kubectl`; there is no standalone `kubectl`.)

## Verification (end to end)

```bash
curl -sk --resolve route.lan:443:192.168.50.200 -X POST https://route.lan/api/routes \
  -H 'content-type: application/json' -d '{"name":"rmtest","upstream":"192.168.50.200:5380"}'
# -> {"host":"rmtest.lan","dns":"created",...}
dig +short @192.168.50.200 rmtest.lan                      # 192.168.50.200
ssh home 'sudo cat /var/lib/route-manager/routes.caddy'    # rmtest.lan { tls internal / reverse_proxy ... }
# caddy-routes-reload.service ran at the same second as the write; https://rmtest.lan -> 200
curl -sk -X DELETE https://route.lan/api/routes/rmtest     # dns: "removed"; record and route gone
```

## Gotchas

- Forgejo repo creation: the token needed `write:user` as well as `write:repository` (`POST /api/v1/user/repos` returned 403 with `write:repository,read:user`). Push-to-create is disabled on this instance. Tokens were minted inside the pod with `su git -c "forgejo admin user generate-access-token --username samu --token-name <n> --scopes ... --raw"` (must run as `git`, not root) and used for a single push via `git -c http.extraHeader="Authorization: Basic ..."` so nothing was stored on disk. Two leftover tokens (`route-manager-sync`, `route-manager-sync2`) can be deleted in Forgejo under Settings > Applications.

- First `curl https://route.lan` failed with exit 6 even after the record existed: the local resolver had a cached NXDOMAIN. `resolvectl flush-caches` fixed it; `dig @192.168.50.200` and `curl --resolve` isolate Technitium/Caddy from the local cache.
- Auth (added later, image 0.2.0): `/api/routes` requires `Authorization: Bearer <API_TOKEN>`; the token is key `API_TOKEN` in Secret `route-manager`, read with `ssh home 'sudo k3s kubectl -n homelab get secret route-manager -o jsonpath="{.data.API_TOKEN}" | base64 -d'`. Implemented as an `HttpApiMiddleware.Service` with `HttpApiSecurity.bearer` (constant-time compare, app refuses to start without it). The UI page, `/healthz`, `/docs` are public. Pitfall hit while rolling it out: home has no `openssl`, so `NEW=$(openssl rand -hex 32)` produced an empty token, the new pod refused to start, and with `strategy: Recreate` the app was down until a real token was set (`tr -dc a-f0-9 </dev/urandom | head -c 64`). Check the length before patching the Secret.
- The Technitium token is an admin-user token (named `route-manager`, revocable from the Technitium UI). A dedicated limited user would be tighter.
- Any new NixOS-defined site must also be added to `RESERVED_NAMES` in `k8s/route-manager.yaml`.
- Suwayomi, SearXNG and crawl4ai were scaled to 0 earlier in the same session (unrelated); `mihon.lan` therefore 502s until Suwayomi is scaled back up.

## References

- Caddy community, [How to make sure dynamic configuration added via API are retained](https://caddy.community/t/how-to-make-sure-dynamic-configuration-added-via-api-are-retained/6810)
- Caddy community, [Autoload caddy configuration on system reboot](https://caddy.community/t/autoload-caddy-configuration-on-system-reboot/11544)
- [caddy-run man page](https://www.mankier.com/8/caddy-run) (`--resume` and autosave)
- Effect v4 docs shipped in the npm package (`node_modules/effect/ai-docs`, `AGENTS.md`); API reference: [HttpApiBuilder](https://effect.website/docs/v4/api/effect/unstable/httpapi/HttpApiBuilder), [v3 HttpApiBuilder](https://effect.website/docs/v3/api/platform/HttpApiBuilder) (for the v3 -> v4 differences)
- [Technitium DNS Server HTTP API docs](https://github.com/TechnitiumSoftware/DnsServer/blob/master/APIDOCS.md) (`user/createToken`, `zones/records/add|get|delete`)
