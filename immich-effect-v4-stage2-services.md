---
type: how-to
tags: [immich, fork, effect, effect-ts, nestjs, services, subagents, vitest, podman]
created: 2026-10-21
last_verified: 2026-10-21
status: current
---

# Immich fork: Effect v4 rewrite, stage 2 (services)

Follows [immich-effect-v4-stage1-repositories.md](immich-effect-v4-stage1-repositories.md). In `~/immich`, branch `effect-v4` (off `strip-ai`, AI features stay removed). Stage 2 converts the Nest services in `server/src/services/` to run their repository-touching logic as Effects, **without** changing method signatures, any `*.spec.ts`, the generated OpenAPI spec, or the generated `.sql` docs.

## Design

- **Services keep their Promise-facing methods** (Nest controllers, `@OnEvent`/`@OnJob` handlers and other services call them unchanged). The body becomes `return runPromise(Effect.gen({ self: this }, function* () { ... }))` over `this.fx.<repo>.<method>(...)`.
- **`BaseService.fx`** (`server/src/effect/fx.ts`, generated from the BaseService constructor) exposes every repository as its stage 1 Effect service. `effectOf(RepoTag, adapter)` in `server/src/effect/bridge.ts` resolves it:
  - adapters register their Effect service in a `WeakMap` in their constructor (`registerEffect(this, service)`, no new instance fields), so production services call the Effect implementation directly;
  - when nothing is registered (vitest mocks in the 158 unit specs) the Promise methods are **lifted** (`Proxy` wrapping each function in `Effect.tryPromise`, recursively for nested groups like `access.asset`), so every existing spec and mock keeps working untouched;
  - when the adapter has an **own function property** (a `vi.spyOn(adapter, 'x')`) or a method the service lacks, that member is lifted from the adapter instead (`guard` in `bridge.ts`).
- **Effect.gen with `this` in v4**: `Effect.gen({ self: this }, function* () { this.x })` (v3's `Effect.gen(this, ...)` does not compile). `unicorn/no-this-outside-of-class` is turned off for `src/services/**` in `server/eslint.config.mjs`. `Effect.fn` doesn't keep generics, use `Effect.gen` + `withSpan` for generic helpers.
- Domain errors that were `throw new BadRequestException(...)` become `return yield* Effect.fail(new BadRequestException(...))`; `runPromise` (`src/effect/run.ts`) rethrows the original instance (`unwrap(Cause.squash(cause))`), so HTTP behavior is identical.
- Helpers first (one agent): `requireAccessFx`/`checkAccessFx` (`utils/access.ts`), `getConfigFx`/`updateConfigFx` (`utils/config.ts`), and `BaseService` `getConfigFx`, `updateConfigFx`, `requireAccessFx`, `checkAccessFx`, `isSetupAvailableFx`, `requireSetupAvailableFx`, `createUserFx`, `createLoginResponseFx`; the Promise versions delegate to them.

## Steps (in order)

1. Commit stage 1 (`git add -A && git commit`, no Claude co-author trailer per user rule).
2. Write `bridge.ts`, generate `fx.ts` (python over the BaseService constructor: prop name, `XRepository` adapter, `XRepo` service, file), add `protected get fx()` with a `WeakMap` memo (no instance field). Export the option types `fx.ts` needs (`TS4023 ... cannot be named`): `AssetExploreFieldOptions`, `AssetGetByChecksumOptions`, `AssetStatsOptions`, `GetByIdsRelations`, `LivePhotoSearchOptions` in `asset.repository.ts`.
3. Write `agent-patterns/effect-services.md` (the binding pattern), then 3 parallel agents: register 24 + 28 adapters, and the access/config helpers. Commit.
4. 7 parallel service agents with disjoint files (small services, mid-size, passkey/user/asset-media/album/transcoding, storage-template/notification/workflow-execution/asset, database-backup/media/integrity, auth/library, sync/metadata). All hit the account session limit (HTTP 429) at the same time; nothing had been written, so they were resumed with `SendMessage` after the limit lifted and completed.
5. Fix medium-suite regressions found only against a real DB:
   - `TypeError: Invalid value used as weak map key` in `lift`: medium tests construct services with only some repositories, but `createFx` evaluated all 53 eagerly. Made `fx.ts` fields lazy getters.
   - `library.service` medium spec (2 tests): the service now called `this.fx.storage.watch/walk` on the registered Effect service, bypassing `vi.spyOn(storage, 'watch'|'walk')` on the adapter. Added the `guard` proxy described above.
6. Dedupe the ~19 local copies of the "unwrap `{_tag, cause}`" helper into an export of `unwrap` from `run.ts` (one agent).

## Verification (from `server/`)

```bash
pnpm exec tsc --noEmit && pnpm exec eslint "src/**/*.ts" "test/**/*.ts" --max-warnings 0 && pnpm exec prettier --check src test
rtk proxy pnpm exec vitest run --config test/vitest.config.mjs 2>&1 | grep -E "Test Files|Tests  "     # 3 failed | 2122 passed | 1 expected fail
export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/podman/podman.sock TESTCONTAINERS_RYUK_DISABLED=true \
       TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=$XDG_RUNTIME_DIR/podman/podman.sock
rtk proxy pnpm exec vitest run --config test/vitest.config.medium.mjs 2>&1 | grep -E "Test Files|Tests  "   # 34 failed | 542 passed
pnpm exec nest build && node dist/bin/sync-open-api.js        # git status open-api: clean
# podman immich postgres (digest from docker/docker-compose.yml), migrations:run, then:
DB_HOSTNAME=localhost DB_PORT=55432 DB_USERNAME=postgres DB_PASSWORD=postgres DB_DATABASE_NAME=immich node dist/bin/sync-sql.js
git status --short server/src/queries                           # clean (365 queries)
```
Baselines: unit 3 failures = node 22 `mkdtempDisposable`; medium 34 = ffprobe/test-assets/plugin-core WASM/node 22 (same as before the Effect work). The medium suite exercises the real production path (registered Effect services against Postgres) and found both regressions above that the unit specs could not.

## Gotchas

- `rtk` hides vitest output and `server/.vitest/json/output.json` is wrong when runs overlap (it showed 1501 tests instead of 2126): use `rtk proxy pnpm exec vitest run ... | grep -E "Test Files|Tests  "`.
- Sync methods whose specs assert immediately after the call (`QueueService.onConfigUpdate/onBootstrap/onShutdown`, `DatabaseBackupService.onConfigUpdate`) stay sync: lifted mocks are async so `runSync` would break them.
- HLS service timing: the spec's `serverSend` mock replies on a microtask; with Effect hops the reply arrived before `pendingSessions.wait()` was registered. Fixed by registering the wait before the send.
- Lazy streams / cursors (`for await` over `batched(stream)`) were not wrapped in Effect streams; loops step the iterator by hand with `Effect.ensuring` calling `.return()` (or kept as plain loops with only the body converted).
- Behavior shifts accepted: `Promise.all` to `Effect.all(..., { concurrency: 'unbounded' })` interrupts sibling fibers on the first failure (the underlying promises are not cancelled; first error identical); `JobRepository.pause/resume/empty/clear` with a missing queue token reject instead of throwing synchronously.
- Partly converted on purpose: `api` (does not extend BaseService), `maintenance.detectPriorInstall`, per-type sync handlers (lazy DB streams), `workflow-execution` plugin host-call path and `pluginRepository.load/callMethod`, `transcoding` process/fs plumbing, `UserService.getCalendarHeatmap` (shared util takes the Promise repo). `workflow-execution` has no unit spec and its medium spec cannot pass here (plugin-core WASM not built), so it is checked only by tsc/eslint.

## Next

3. Effect versions of the remaining Promise utils (`addAssets`/`removeAssets`, `upsertTags`, `getCalendarHeatmap`, `reverseGeocode` on `MapRepo`, per-table `cleanupAuditTable` on `fx.sync`), convert the stream loops with `Stream`, then BullMQ/socket.io as Effect services and a shared `ManagedRuntime`. 4. Remove adapters whose last Promise consumer moved (needs the specs rewritten around Effect layers).

## References

- Effect `Effect.gen` / `Effect.fn` / `Context.Service` in the installed package: `server/node_modules/effect/dist/Effect.d.ts`, `Context.d.ts` (4.0.5), and the vendored `repos/effect/LLMS.md`.
- Effect v4 migration guide: https://github.com/Effect-TS/effect-smol/blob/main/migration/v3-to-v4.md
- Effect 4.0.0 release: https://github.com/Effect-TS/effect/releases/tag/effect%404.0.0
