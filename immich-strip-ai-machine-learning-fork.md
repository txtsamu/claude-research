---
type: how-to
tags: [immich, fork, machine-learning, postgres, migration, pnpm, podman]
created: 2026-10-21
last_verified: 2026-10-21
status: current
---

# Stripping all AI / machine-learning features out of Immich (lean server fork)

Goal: run Immich without the `immich-machine-learning` container and without any model-driven feature, so the server is just server + Redis (Valkey) + Postgres.

Fork lives in `~/immich` on branch `strip-ai`, cloned shallow from `https://github.com/immich-app/immich.git` at `166e935` (2026-10-20, v3.3.0rc0). **Not committed or pushed anywhere** at the time of writing (408 files changed, +6.5k / -57.5k lines).

## What Immich's AI actually is

One Python service (`machine-learning/`, FastAPI + onnxruntime) called by the NestJS server through `MachineLearningRepository`. Three model tasks, five user-facing features:

| Feature | Model | Server pieces |
|---|---|---|
| Smart search | OpenCLIP / M-CLIP | `smart-info.service`, `search.service` (`searchSmart`), table `smart_search`, `clip_index` |
| Face detection | InsightFace | `person.service`, table `asset_face` |
| Facial recognition / People | InsightFace + clustering | `person`, `person_user`, `person_group`, `face_search`, `face_index`, cluster groups |
| OCR | RapidOCR (PaddleOCR) | `ocr.service`, tables `asset_ocr`, `ocr_search` |
| Duplicate detection | CLIP embeddings | `duplicate.service`, `asset.duplicateId` |

Things that were entangled with people and had to go too: birthday memories (`MemoryType.Birthday`), the EXIF face-tag import (`metadata.faces.import`), `user.clusterGroupId`, person/face/OCR sync entities, the people/face/OCR/duplicate API permissions, hidden-person filtering in memories, `asset_face` trigger on the `asset` table.

Not AI (kept): reverse geocoding, memories (on-this-day), metadata/EXIF extraction, thumbnails, video transcoding, tags, albums.

## Steps (in order)

Tooling: node 22 and no pnpm on the box; `npm i -g pnpm --prefix ~/.local` gives pnpm. The repo pins pnpm 11 / node 24, so a few unit tests that use `mkdtempDisposable` fail on node 22 (environmental, not the strip).

1. Clone and branch
   ```bash
   cd ~ && git clone --depth 1 https://github.com/immich-app/immich.git immich
   cd immich && git checkout -b strip-ai
   pnpm install --ignore-scripts
   # server tsc needs the workspace sdk packages built first
   (cd packages/sdk && pnpm run build) && (cd packages/plugin-sdk && pnpm run build)
   cd server && pnpm exec tsc --noEmit    # baseline: clean
   ```
2. Infra: `git rm -r machine-learning docker/hwaccel.ml.yml`; delete the `immich-machine-learning` service (and `model-cache` volume) from `docker/docker-compose{,.dev,.prod,.rootless}.yml`; remove it from `.devcontainer/*`, `mise.toml`, `renovate.json`, `.github/labeler.yml`, `CODEOWNERS`, `.dockerignore`, `packages/scripts/src/commands/release.ts`; in `.github/workflows/docker.yml` and `test.yml` delete the ML jobs (careful: the `&tag-rules` YAML anchor lived inside the ML build job and the `mirror` job aliases it, so the anchor has to move to the server job).
3. Server, driven by `tsc` errors (about 600 at first):
   - `git rm` the services, repositories, controllers, DTOs, tables, `.sql` query files and specs for person / face / ocr / duplicate / smart-info / cluster-group / machine-learning, plus `utils/editor.ts` (face/OCR crop-visibility) and `utils/duplicate*.ts`.
   - `enum.ts`: drop permissions, `QueueName`/`JobName` entries, `VectorIndex`, `SourceType`, `PersonPathType`, sync request/entity types, `ApiTag`s, `MemoryType.Birthday`, `NotificationType.ClusterGroupRequest`.
   - Fix registries (`controllers|services|repositories/index.ts`, `schema/index.ts`, `base.service.ts` constructor *and* the `create()` argument list, which is positional).
   - Strip AI from: `types.ts` job unions and `UserPreferences.people`, `database.ts` column lists, access repository/util, search DTO/service/repository (smart search, `personIds`, `hasPeople`, `ocr`, `withPeople`), sync DTO/repository/service, config DTO (`machineLearning`, `metadata.faces`, `nightlyTasks.clusterNewFaces`, ML job concurrencies), server features/config DTOs, asset/user/memory DTOs, storage core (person thumbnail paths), media service (person thumbnails, face visibility on edit), metadata service (tagged faces), queue/job/system-config services, integrity repo/service, cli service.
   - `vectorIndexQuery` was imported by `InitialMigration`; it is now inlined there (migrations must stay self-contained).
   - Database repository/service: removed vector reindex/prewarm/probes/dimension-size code but **kept** vector extension bootstrapping, because the old migrations still `CREATE EXTENSION vector/vchord`. So the Postgres image must still be the immich one with VectorChord.
4. New migration `server/src/schema/migrations/1792700000000-DropMachineLearning.ts`: drops the AI tables (CASCADE), `user.clusterGroupId`, `asset.duplicateId`, three `asset_job_status` columns, the asset trigger, 8 functions, enum types `sourcetype` and `person_user_role_enum`, deletes `birthday` memories and the `facial-recognition-state` system_metadata row, and deletes the matching `migration_overrides` rows (otherwise `schema-check` reports 27 stale overrides). `down()` is a no-op. A first version failed on an FK dependency order error until CASCADE was added.
5. Verify the DB in a throwaway container (rootful or rootless podman):
   ```bash
   podman run -d --name immich-pg -e POSTGRES_PASSWORD=<scratch> -p 55432:5432 \
     ghcr.io/immich-app/postgres:14-vectorchord0.4.3-pgvectors0.2.0@sha256:<digest from docker/docker-compose.yml>
   # fresh: run all migrations then check drift (DatabaseRepository.getSchemaDrift / immich-admin schema-check)
   # upgrade: migrate to the previous latest, seed person/face/embedding/duplicateId/birthday memory, then apply the new one
   pnpm run migrations:verify-order        # new migration passes ORDER check
   podman rm -f immich-pg
   ```
   Result: 104 migrations apply on an empty DB with zero drift; upgrade path with seeded AI rows applies and keeps only the non-AI data.
6. Regenerate generated files:
   ```bash
   cd server && pnpm exec nest build && node dist/bin/sync-open-api.js          # open-api/immich-openapi-specs.json
   cd .. && pnpm dlx oazapfts@7.5.0 --optimistic --argumentStyle=object --useEnumType --allSchemas \
       open-api/immich-openapi-specs.json packages/sdk/src/fetch-client.ts       # flags from mise.toml
   (cd packages/sdk && pnpm run build)
   # SQL docs: run server/dist/bin/sync-sql.js against the migrated DB
   ```
   `npx oazapfts@...` did not work here (wrapped by the shell hook), `pnpm dlx` did. The mobile Dart client (`mobile/openapi`) was **not** regenerated (no Flutter/Dart on the box).
7. Web (`web/`): remove people / duplicates / OCR / smart-search UI, `MachineLearningSettings.svelte`, AI queues in `JobSettings`/`queue.service`, birthday memory UI, face overlay and OCR bounding boxes in the asset viewer; drop the unused deps `@photo-sphere-viewer/markers-plugin` and `svelte-confetti`; `pnpm install --ignore-scripts` to refresh `pnpm-lock.yaml`.
8. Docs and e2e: deleted the feature pages (searching, facial recognition, ML hardware acceleration, duplicates, remote ML), ML env vars and config blocks; removed AI e2e specs and the ML env from e2e compose files.

## Verification results

- `server`: `tsc --noEmit` clean, `eslint "src/**/*.ts" "test/**/*.ts" --max-warnings 0` clean.
- Server unit tests: 2122 passed, 3 failed (`mkdtempDisposable` missing on node 22; repo wants node 24).
- Server medium tests (real Postgres via podman socket): 542 of 576 passed; the 34 failures are environmental (plugin-core WASM not built, `e2e/test-assets` missing, node 22).
- Web: `vitest run` 495 passed; `svelte-check` 7 errors, all typing errors in three spec files (`AssetViewerNavBar`, `Thumbnail`, `NumberRangeInput`) that look unrelated to the strip, but a clean-HEAD baseline was not run to prove it.
- The full stack was **not** started end to end (no browser/UI run, no real upload through the fork).

## Operational notes for deploying the fork

- Existing person/face thumbnails stay on disk under `thumbs/<userId>/`. After the DB tables are gone the integrity check reports them as untracked; delete them manually.
- Stored `machineLearning` / `metadata.faces` keys in the system config (DB or config file) are just logged as "Unknown keys" and ignored.
- Mobile app: left untouched; against this server its search, people and duplicates screens will not work.
- The Postgres image still needs pgvector/VectorChord because migration history was not rewritten.
- Build a server image from this tree (`server/Dockerfile`, context repo root) and drop the ML service from your compose file.

## References

- Immich repo: https://github.com/immich-app/immich
- Compose reference used for the DB image tag: `docker/docker-compose.yml` in the repo
