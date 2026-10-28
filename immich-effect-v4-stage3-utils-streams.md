---
type: how-to
tags: [immich, fork, effect, effect-ts, nestjs, streams, subagents, podman]
created: 2026-10-28
last_verified: 2026-10-28
status: current
---

# Immich fork: Effect v4 rewrite, stage 3 (utils, StorageCore, sync streams)

Follows [stage 1](immich-effect-v4-stage1-repositories.md) and [stage 2](immich-effect-v4-stage2-services.md). `~/immich`, branch `effect-v4`. Goal of stage 3: close the gaps stage 2 left, so services stop wrapping Promise code in `Effect.tryPromise`. Spec files, OpenAPI spec and generated `.sql` docs stay unchanged.

## What was done (two phases, parallel subagents with disjoint files)

**3a, make the Effect versions exist**
- `utils/asset.util.ts`: `addAssetsFx`, `removeAssetsFx` (bulk arg `IBulkAssetFx`), `getMyPartnerIdsFx`, `onBeforeLinkFx`, `onBeforeUnlinkFx`, `onAfterUnlinkFx`. `utils/tag.ts`: `upsertTagsFx`. `utils/profile-image.ts`: `generateProfileImageFx`. `utils/maintenance.ts`: `detectPriorInstallFx`. `utils/misc.ts`: `findOrFailFx(effect, entity)`. `services/shared/user-methods.ts`: `getCalendarHeatmapFx`. The Promise originals keep their signatures and delegate: `runPromise(xFx(effectOf(RepoTag, repo), ...))`.
- `cores/storage.core.ts`: `moveFileFx`, `moveAssetImageFx`, `moveAssetVideoFx`, `ensureFoldersFx`, `removeEmptyDirsFx`, `getVideoInterfacesFx`; Promise methods delegate. `ensureFolders` stays sync (callers use it synchronously and `runSync` fails on lifted async mocks).
- Repositories: `MapRepo.reverseGeocode` and `MapRepo.init` (country-name cache moved into the service closure; `MapRepo.layer(deps)` is now a function), `cleanupAuditTable` on all 12 `SyncRepo` groups, `PluginRepo.load/callMethod` (extism pool map in the service closure). Websocket gateway hooks and the telemetry prototype wrapper stay plain (Nest lifecycle/reflection).
- `src/effect/runtime.ts`: one shared `appRuntime = ManagedRuntime.make(Layer.empty)`; `runPromise`/`runSync` use it; `BaseModule.onModuleDestroy` calls `disposeAppRuntime()`. No layers yet, a hook for a future tracer/logger layer.
- ESLint: `unicorn/no-this-outside-of-class` off for `src/services/**` and `src/cores/**` (needed by `Effect.gen({ self: this }, ...)`).

**3b, use them**
- 17 services swapped `Effect.tryPromise` wrappers for the Fx versions (album, asset-media, asset, auth, map, memory, tag, search, timeline, user, user-admin, metadata, maintenance, transcoding, media, storage-template, workflow-execution).
- `sync.service.ts`: all `sync*V*` handlers return Effects; each cursor is consumed with `Stream.fromAsyncIterable(it, cause => cause).pipe(Stream.runForEach(f))` (one row at a time, `iterator.return()` in the scope finalizer on failure/interruption, same as `for await`); `await` count 131 to 5, direct repository calls 49 to 1. `send` stays a Promise function (its spec imports it and asserts it writes synchronously), `sendFx` wraps it. `onAuditTableCleanup` stays on the Promise adapter because a medium spec spies `BaseSync.prototype.auditCleanup`.

## Verification (from `server/`)

Same commands as stage 2:
```bash
pnpm exec tsc --noEmit && pnpm exec eslint "src/**/*.ts" "test/**/*.ts" --max-warnings 0 && pnpm exec prettier --check src test
rtk proxy pnpm exec vitest run --config test/vitest.config.mjs 2>&1 | grep -E "Test Files|Tests  "      # 3 failed | 2122 passed | 1 expected fail
# medium on podman (DOCKER_HOST/TESTCONTAINERS_* env as in stage 2)
rtk proxy pnpm exec vitest run --config test/vitest.config.medium.mjs test/medium/specs/sync   # 24 files, 132 tests pass
pnpm exec nest build && node dist/bin/sync-open-api.js ; git status --short open-api            # clean
# podman immich postgres + migrations:run + node dist/bin/sync-sql.js ; git status --short server/src/queries   # clean
```
Full medium run: 34 or 35 failures. The 34 are the usual environment ones (ffprobe/test-assets, plugin-core WASM not built, node 22). The 35th, `AssetService > delete > should delete a stacked primary asset (3 assets)`, is **flaky and not caused by the Effect work**: it fails about half the full-suite runs even at the end of stage 2 (`git checkout <commit> -- server`), passes 3/3 when its folder is run alone, and the query it depends on (`asset.job.repository.sql` `getForAssetDeletion`) has no `ORDER BY` for `stack.assets`, so `remainingStackAssetIds[0]` follows heap order.

## End-to-end smoke test (real Nest boot)

The unit and medium suites build services by hand and never exercise Nest DI, adapter `registerEffect` at construction, or `appRuntime` in a booted app. So the built server was run for real: podman Postgres (immich image, digest from `docker/docker-compose.yml`) + `valkey/valkey:9` pinned digest, geodata downloaded into an `IMMICH_BUILD_DATA` dir (geonames `admin1CodesASCII.txt`, `admin2Codes.txt`, `countryInfo.txt`, `cities500.zip` from download.geonames.org/export/dump, and `ne_10m_admin_0_countries.geojson` from nvkelso/natural-earth-vector v5.1.2), then `cd server && DB_*/REDIS_*/IMMICH_MEDIA_LOCATION/IMMICH_BUILD_DATA=... node dist/main.js`. Without the geodata files `MetadataService.init` fails (`/build/geodata/geodata-date.txt`), the same as upstream.
Verified with curl: `MapRepo.init` geodata import (229,275 records), admin sign-up + login, `users/me`, `server/about|features`, `system-config`, PNG upload (thumbnail 200, original 200, EXIF width + thumbhash extracted by the metadata job), timeline buckets, album create/get, metadata search, shared link, `POST /sync/stream`, trash / restore / force delete (deletion job ran, stats back to 0). No errors in the log except the expected plugin-core WASM warning and a transient schema-drift warning while the geodata import rebuilds indexes. Gotchas: `rtk curl` truncates bodies (use `rtk proxy curl` before JSON parsing); never `pkill -f "dist/main"`/`pgrep -f` from a shell whose own command line contains the pattern (exit 144), use a pid file.

## Gotchas

- Agents ran the medium suites on podman only after being given the exact env vars; without them they reported "no docker/postgres here" and skipped them. Put the `DOCKER_HOST=unix://$XDG_RUNTIME_DIR/podman/podman.sock TESTCONTAINERS_RYUK_DISABLED=true TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=...` line in the prompt.
- A unit run during someone else's half-written edit can show hundreds of failures (one agent saw 1437). Rerun before debugging.
- To bisect a medium-suite flake: `git stash -q && git checkout -q <commit> -- server`, run, then `git checkout -q HEAD -- server && git clean -fdq server/src server/test && git stash pop -q`.

## Left (stage 4, optional, not started)

Remove the Promise adapters and the mock-lifting `bridge.ts`, inject Effect services into Nest, and rewrite the 158 specs around Effect layers; controllers calling services as Effects. This removes the safety net that has kept every stage verifiable and gains no API change, so it needs an explicit go-ahead. Replacing Nest controllers with `HttpApi` is not recommended (OpenAPI output must stay identical).

## References

- Stage 1 and stage 2 write-ups above, `agent-patterns/effect-*.md` in the repo.
- Effect v4 migration guide: https://github.com/Effect-TS/effect-smol/blob/main/migration/v3-to-v4.md
- Effect 4.0.0 release: https://github.com/Effect-TS/effect/releases/tag/effect%404.0.0
