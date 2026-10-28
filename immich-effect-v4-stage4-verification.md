---
type: how-to
tags: [immich, fork, effect, effect-ts, nestjs, testing, podman, subagents, docker-image]
created: 2026-10-28
last_verified: 2026-10-28
status: current
---

# Immich fork: Effect v4 rewrite, stage 4a and the full verification round

Follows [immich-effect-v4-stage3-utils-streams.md](immich-effect-v4-stage3-utils-streams.md). Repo `~/immich`, branch `effect-v4`, pushed to the fork `txtsamu/immich` (git remote `fork`; `origin` is upstream). Final state: commit `6eb7eda2d`.

## Result

| Check | Result |
|---|---|
| tsc, eslint, prettier | clean |
| Unit tests (node 24) | 100 files, 2130 pass, 1 intentional expected-fail, 0 fail |
| Medium tests (podman Postgres, node 24, ffprobe + test assets + plugin WASM) | 59 files, 576 pass, 0 fail |
| OpenAPI spec | unchanged |
| Real image from the unmodified `server/Dockerfile` (podman) | built (~10 min cold, 1.8 GB), every API check passed |

The earlier "34 environment failures" were all environment: no `fs.mkdtempDisposable` on node 22, missing e2e test assets, missing plugin-core WASM. With them supplied nothing fails, so no regression was hiding behind them.

## What was done, in order

1. **Stage 4a (the only safe slice of stage 4).** Deleting the Promise adapters is not possible: medium specs construct them (`new key(db)`) and ~45 controllers, guards, middleware, workers and CLI tools call them. What was possible: move the Proxy that turns Promise-based vitest mocks into Effect services out of production code. `src/effect/bridge.ts` lost `lift`; `effectOf` serves the registered service and, for unregistered objects, calls a hook set with `setEffectFallback` (throws if unset). `test/lift.ts` has the Proxy, `test/setup.ts` installs it, both vitest configs got `setupFiles: ['test/setup.ts']`. No spec edited.
2. **Pushed to a fork.** `gh repo fork immich-app/immich --clone=false --remote=false`, `git remote add fork https://github.com/txtsamu/immich.git`, `git push fork strip-ai effect-v4`, PR #1 `effect-v4` -> `strip-ai` inside the fork. (The fork is public because the upstream is; the auto-mode classifier blocked the first push until the user agreed.)
3. **Flaky medium test fixed.** `AssetService > delete > should delete a stacked primary asset (3 assets)` failed about half the runs: the `stack_asset` subquery in `getForAssetDeletion` (`src/repositories/asset-job.repository.ts`) had no `ORDER BY`, so which remaining asset became the new primary depended on heap order. Now `.orderBy('stack_asset.fileCreatedAt','asc').orderBy('stack_asset.createdAt','asc').orderBy('stack_asset.id','asc')`. Regenerate the SQL doc: run a podman `ghcr.io/immich-app/postgres:14-vectorchord0.4.3-pgvectors0.2.0@sha256:bcf63357...` on port 55432, then `DB_URL=postgres://postgres:postgres@127.0.0.1:55432/immich pnpm run migrations:run` (it needs `DB_URL`, not `DB_HOSTNAME`), `pnpm exec nest build`, `node dist/bin/sync-sql.js`; only `src/queries/asset.job.repository.sql` changes (+4 lines). 6/6 isolated runs passed.
4. **Four subagents in parallel** (image build, environment failures, podman cleanup, Promise-spot mop-up).
5. **Remaining Promise spots** (agent branch, fast-forward merged): `metadata.service.ts` uses the shared `unwrap(Cause.squash(cause))`; `sync.service.ts` `send` is now a real Effect (`sendFx`) with `send = runPromise(sendFx(...))` kept for the spec; `WebsocketRepository.handleConnection/handleDisconnect` run through `runPromise` with `Effect.catchCause` for the error path. Deliberately left: `onAuditTableCleanup` (a medium spec spies `BaseSync.prototype.auditCleanup`), the telemetry `wrapRepository` reflection wrapper, queue sync handlers, `DatabaseBackupService.onConfigUpdate`, `StorageCore.ensureFolders` (must stay sync).
6. **New spec** `src/repositories/websocket.repository.spec.ts` (5 tests), because the websocket hooks had no coverage. Gotcha: `Effect.tryPromise({ try })` needs a real Promise, so an automocked `emit` returning `undefined` must be `mockResolvedValue()`; `EventRepository` takes its logger as the 3rd constructor argument.

## Recipe: supply the missing test environment (node 22 host)

Everything lives in `~/sessions/2026-10-28-immich-env-tests/` (versions and sha256 come from `~/immich/mise.lock`):
- node 24.22.0 tarball extracted to `tools/node`; the system node stays 22. `NODE24=1 . env.sh` puts it on PATH.
- test assets: `git clone https://github.com/immich-app/test-assets`, check out the commit the `e2e/test-assets` gitlink pins (`6742055402de`), `cp -a` it into `~/immich/e2e/test-assets/` (matches the gitlink so `git status` stays clean). `server/test/medium.factory.ts:88` hard-codes that path.
- ffprobe: jellyfin-ffmpeg 7.1.3-6 (the build CI uses) in `tools/ffmpeg`, on PATH only for test runs.
- plugin-core WASM: prebuilt `extism-js` v1.7.0 plus binaryen `version_124` (`wasm-opt`) in `tools/bin`, then from `~/immich`: `PATH=$S/tools/node/bin:$S/tools/bin:$PATH pnpm --filter @immich/sdk --filter @immich/plugin-sdk --filter @immich/plugin-core build` (output is gitignored).
- run: `cd ~/immich/server; export NODE24=1; . ~/sessions/2026-10-28-immich-env-tests/env.sh; rtk proxy pnpm exec vitest run --config test/vitest.config.medium.mjs` (and `test/vitest.config.mjs` for unit). `env.sh` sets `DOCKER_HOST`, `TESTCONTAINERS_RYUK_DISABLED=true`, `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE`.
- cleanup: Ryuk is off, so every run leaves a Postgres container. `podman rm -fv $(podman ps -aq --filter label=org.testcontainers=true)` when no run is active. One cleanup removed 22 of them and freed ~19 GB.

## Recipe: build and drive the real image with podman

`~/sessions/2026-10-28-immich-image-build/README.md`: `git worktree add --detach <dir>/src effect-v4`, then `podman build --format docker -f server/Dockerfile -t localhost/immich-server-effectv4:<sha> --build-arg BUILD_ID=local-<sha> --build-arg BUILD_SOURCE_COMMIT=<sha> .` (base images carry the geodata; nothing to download). Run on a podman network with the pinned Postgres digest and `docker.io/valkey/valkey:9@sha256:418652cf...`, wait ~40 s for the geodata import, then drive the API with `rtk proxy curl` (`./run-stack.sh`, `./drive-api.sh && ./drive-api2.sh && ./drive-api3.sh`). Checked: ping/features/config, admin sign-up and login, PNG and MP4 upload with thumbnails/EXIF/thumbhash, transcode plus a 206 Range playback, duplicate upload, queues, timeline, albums, metadata search, shared link, `POST /sync/stream`, trash/restore/force delete, API keys, tags, memories, web UI served. Notes: the only log WARN is `Api:LegacyRouteConverter: Unsupported route path "/api/*"` (Express 5 path-to-regexp with the global prefix; not checked against upstream); `AssetsV1`/`AlbumAssetsV1`/`PartnerAssetsV1` sync types answer 400 "deprecated, use V2"; `/search/smart` is 404 because AI is stripped.

## Caveats

- The image was built from `0616c93fc`, before the Promise-spot mop-up; the websocket change is covered by the new unit spec, not by the image run.
- The image agent also ran `podman builder prune -f` / `podman image prune -f` and removed the base images its build pulled; it could not confirm that every pruned dangling image was its own.
- PR #1 is open on the fork; merging it was blocked by the auto-mode classifier ("merge without review"), so it is the user's call.
