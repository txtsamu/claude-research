---
type: investigation
tags: [immich, memory, nodejs, sharp, exiftool, bullmq, postgres, podman, performance]
created: 2026-10-21
last_verified: 2026-10-28
status: current
---

# Where the memory goes in the stripped Immich server (no ML)

Question: after removing all AI features (see [immich-strip-ai-machine-learning-fork.md](immich-strip-ai-machine-learning-fork.md)), why is memory still high? Answer: it is the Node server doing photo work, not Postgres or Valkey. Measured on the `strip-ai` branch (`ef74a43`).

## How it was measured

Test box: Fedora desktop, 32 cores, 62 GB RAM, node v22.22.2. Caveats up front, because they affect how far to trust the numbers:

- Ran `node dist/main.js` directly, **without** the `libmimalloc` `LD_PRELOAD` that `server/bin/start.sh` sets in the real image, and without `UV_THREADPOOL_SIZE` (start.sh sets it to the core count when > 4). Allocator behaviour after bursts, in particular, is probably worse here than in production.
- Synthetic load: 22 images, 6000x4000 (24 MP), ~0.75 MB JPEG each (ffmpeg `mandelbrot` source), empty library, no videos, no libraries/external scan, geodata stubbed with an empty cities file.
- Single run per scenario, no repeats.

Setup (all throwaway, removed afterwards):

```bash
cd ~/immich/server && pnpm exec nest build
# DB + cache, same images as docker/docker-compose.yml
podman run -d --name memtest-pg -e POSTGRES_PASSWORD=memtest -e POSTGRES_USER=postgres -e POSTGRES_DB=immich \
  -p 55433:5432 --shm-size=128m ghcr.io/immich-app/postgres:14-vectorchord0.4.3-pgvectors0.2.0@sha256:bcf63357191b76a916ae5eb93464d65c07511da41e3bf7a8416db519b40b1c23
podman run -d --name memtest-redis -p 56379:6379 docker.io/valkey/valkey:9@sha256:418652cfb58ef879d4978c33553735d7147016032d5aefaa14c828e611eb9dfd
# server needs a build/geodata dir or the metadata service fails init (geodata-date.txt, cities500.txt,
# admin1CodesASCII.txt, admin2Codes.txt, ne_10m_admin_0_countries.geojson with at least one valid Polygon feature)
DB_HOSTNAME=127.0.0.1 DB_PORT=55433 DB_USERNAME=postgres DB_PASSWORD=memtest DB_DATABASE_NAME=immich \
REDIS_HOSTNAME=127.0.0.1 REDIS_PORT=56379 IMMICH_MEDIA_LOCATION=<scratch>/data IMMICH_BUILD_DATA=<scratch>/build \
IMMICH_PORT=22830 NODE_ENV=production node dist/main.js
# admin + token
curl -X POST localhost:22830/api/auth/admin-sign-up -H 'Content-Type: application/json' -d '{"email":"a@a.com","password":"password123","name":"admin"}'
curl -X POST localhost:22830/api/auth/login -H 'Content-Type: application/json' -d '{"email":"a@a.com","password":"password123"}'
# upload (needs deviceAssetId, deviceId, fileCreatedAt, fileModifiedAt, assetData), 4 in parallel; append random bytes to each copy so the checksum differs
```

RSS was read from `/proc/<pid>/status` every 0.3 s for the API process, the main process, and their child processes (exiftool/perl). The main process holds the microservices (job) worker.

## Process model (why there are two big processes)

`server/src/main.ts` `Workers.startWorker`:

- `ImmichWorker.Api` is started with `child_process.fork` (shows up as process name `immich-api`).
- Every other worker (the microservices/job runner) is a `worker_thread` inside the main `immich` process.
- Defaults: `IMMICH_WORKERS_INCLUDE` = api + microservices (`config.repository.ts:181`). Each loads its own full NestJS module graph.

## Measurements

| Stage | API process | Main process (microservices) | Children (exiftool) |
|---|---|---|---|
| Idle after boot | ~245 MB | ~300 MB | none |
| After first burst of 22 photos | 258 MB | 504 MB | gone |
| Peak during second burst of 22 photos | 259 MB | **835 MB** | **~300 MB** |
| After second burst | 259 MB | 525 MB | gone |

- Total Node-side peak during a burst: ~1.39 GB.
- Postgres container: 72 MB idle, 122 MB after 44 assets. Valkey: 6 to 7 MB.
- The microservices process never went back to its 300 MB idle after work; it stayed ~200 MB higher. Not proven to be a leak (it was flat between the two post-burst readings, 504 to 525 MB), more likely allocator high-water retention, but the run did not use mimalloc so this is unconfirmed for the real image.

## Causes found in the code

1. Two full Node apps: ~550 MB before any work (measured above).
2. Whole-image raw decode: `MediaRepository.decodeImage` (`server/src/repositories/media.repository.ts:153`) does `.raw().toBuffer()`, one uncompressed buffer per image (~70 to 100 MB for 24 MP). `limitInputPixels: false` and `unlimited: true` are set (lines 230 and 234), so huge images are not rejected. `sharp.concurrency(0)` (line 70) uses all cores and `sharp.cache({ files: 0 })` only disables the file cache. Default `job.thumbnailGeneration.concurrency` is 3 (`dtos/config.dto.ts`), so up to 3 such decodes at once. This explains the +330 MB peak on the job process.
3. ExifTool: `MetadataRepository` (`metadata.repository.ts`) `setMaxProcs(concurrency)` with default `job.metadataExtraction.concurrency: 5`, about 60 MB per perl process. Matches the ~300 MB of children in the sample.
4. Smaller, not measured: Postgres pool is `maxConnections = 10` per process (`@immich/sql-tools` `createPostgres`); `JobRepository.startWorkers` creates one BullMQ `Worker` (with its own Redis connection) for each of the 14 queues; BullMQ `removeOnFail: false` (`config.repository.ts:286`) keeps failed jobs in Valkey forever; the timeline bucket query builds the whole bucket's JSON in Postgres (`jsonAgg`, `asset.repository.ts`); library scan pagination is 10,000 rows (`constants.ts`).
5. Not covered: video transcoding (ffmpeg defaults `threads: 0`, `preset: ultrafast`), library/external scans at scale, large RAW files, the web frontend.

## What to do about it

Settings only (Admin > Jobs, or the config file):
- `job.thumbnailGeneration.concurrency` 3 to 1: biggest win for the peak. **Applied 2026-10-28** as the new default in the fork (`strip-ai` commit `61f79d1f0`: `server/src/dtos/config.dto.ts`, the docs example, and the default hard-coded in `system-config.service.spec.ts`). Only the default changed, so an install that saved its own value in the admin job settings keeps it. Unit suite unchanged (2122 pass, same 3 Node 22 failures); the lower peak itself was **not re-measured**.
- `job.metadataExtraction.concurrency` 5 to 2: fewer exiftool processes.
- A container memory limit (for example `mem_limit: 1g`) so a burst cannot grow unbounded. Not tested, may make a burst fail instead of just being slow.

Code changes, **not done**:
- Run the API inside the main process, or exclude one worker with `IMMICH_WORKERS_INCLUDE` / `IMMICH_WORKERS_EXCLUDE`, to save ~250 MB (loses the process isolation, and microservices-only mode needs the API elsewhere).
- Lower the Postgres pool `maxConnections`.
- Reject or downscale very large inputs instead of setting `limitInputPixels: false`.

The ML container itself was not measured here; this analysis only covers what remains after removing it.

## Cleanup

Containers `memtest-pg` and `memtest-redis` were removed, the test server killed, `server/dist` deleted, scratch images deleted.
