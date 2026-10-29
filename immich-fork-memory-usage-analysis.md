---
type: investigation
tags: [immich, memory, nodejs, sharp, exiftool, bullmq, postgres, podman, performance]
created: 2026-10-21
last_verified: 2026-10-29
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
# admin1CodesASCII.txt, admin2Codes.txt, ne_10m_admin_0_countries.geojson with at least one valid Polygon feature whose properties include ADMIN, ADM0_A3 and TYPE, because those columns are NOT NULL)
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
- `job.thumbnailGeneration.concurrency` 3 to 1: biggest win for the peak. **Applied 2026-10-28** as the new default in the fork (`strip-ai` commit `61f79d1f0`: `server/src/dtos/config.dto.ts`, the docs example, and the default hard-coded in `system-config.service.spec.ts`). Only the default changed, so an install that saved its own value in the admin job settings keeps it. **Re-measured 2026-10-29** (see the last section): job-process peak 807-811 MB down to 556-595 MB, whole-stack peak about 1.24 GB down to about 0.98 GB, at the cost of the burst taking 13 s instead of 5-7 s.
- `job.metadataExtraction.concurrency` 5 to 2: fewer exiftool processes (about 60 MB each). **Applied 2026-10-29** as the new default (`strip-ai` commit `9d54a2c08`, same three files). Same caveat: saved admin values are kept. Its effect was **not observable** in the re-measurement: the test files carry almost no metadata, so metadata extraction was over in a fraction of a second and at most one exiftool process (21 MB) was ever seen. The ~300 MB of exiftool children from the first measurement did not reproduce.
- A container memory limit (for example `mem_limit: 1g`) so a burst cannot grow unbounded. Not tested, may make a burst fail instead of just being slow.

Code changes, **not done**:
- Run the API inside the main process, or exclude one worker with `IMMICH_WORKERS_INCLUDE` / `IMMICH_WORKERS_EXCLUDE`, to save ~250 MB (loses the process isolation, and microservices-only mode needs the API elsewhere).
- Lower the Postgres pool `maxConnections`.
- Reject or downscale very large inputs instead of setting `limitInputPixels: false`.

The ML container itself was not measured here; this analysis only covers what remains after removing it.

## Cleanup

Containers `memtest-pg` and `memtest-redis` were removed, the test server killed, `server/dist` deleted, scratch images deleted.

## Re-measurement with the lowered defaults, and the whole stack (2026-10-29)

Question: what does the whole fork stack use, and what did lowering `thumbnailGeneration` 3 to 1 and `metadataExtraction` 5 to 2 actually save? Build under test: `effect-v4` at `9a530a06b` (strip-ai + Effect rewrite + the two concurrency defaults + external-library relink/watcher changes), built with `nest build` and run as `node dist/main.js` (not the image), node v22.22.2, 32 cores, **no mimalloc** (same caveat as above). Postgres (`ghcr.io/immich-app/postgres:14-vectorchord0.4.3-pgvectors0.2.0`) and Valkey 9 in podman, library watcher turned off for the runs.

### Whole stack, idle (live instance, a handful of assets)

| Component | Memory |
|---|---|
| main `immich` process (the job worker runs inside it) | ~320 MB |
| `immich-api` worker | ~255 MB |
| Postgres | ~78 MB |
| Valkey | ~6 MB |
| **Total** | **~660 MB** |

### Burst: 22 photos, 6000x4000 (24 MP), 4 uploads in parallel

Each run: set the two concurrencies through `PUT /api/system-config`, restart the server, wait 20 s, sample RSS of the main process, the `immich-api` child and all other descendants every 0.3 s while uploading and until every asset has a thumbnail and `metadataExtractedAt`, then 15 s more. "old" = thumbnails 3 / metadata 5, "new" = 1 / 2. Peak and final are RSS in MB.

| Run | Config | Time to process | Main process peak | API peak | Node + children peak | Node + children after (final) | Postgres | Valkey |
|---|---|---|---|---|---|---|---|---|
| old2 | 3 / 5 | 5 s | 807 | 272 | 1099 | 797 | 128 | 6 |
| old3 | 3 / 5 | 7 s | 811 | 288 | 1114 | 788 | 128 | 8 |
| new1 | 1 / 2 | 13 s | 595 | 278 | 894 | 744 | 106 | 7 |
| new2 | 1 / 2 | 13 s | 556 | 276 | 853 | 743 | 105 | 7 |
| new3 | 1 / 2 | 13 s | 567 | 267 | 855 | 753 | 114 | 7 |

- Job-process peak: ~809 MB with the old defaults, ~573 MB with the new ones (about -230 MB, -29%). Consistent with the first investigation (835 MB for the old defaults).
- Whole-stack peak (Node + children + Postgres + Valkey): about 1.24 GB old, about 0.98 GB new (about -260 MB, -21%).
- After the burst the job process stays above its idle ~320 MB (old ~490, new ~450): allocator retention, as before. Not proven to be a leak.
- Cost: the burst takes about 13 s instead of 5-7 s. On this 32-core box `sharp` was not the bottleneck at 3 concurrent; on a small server the extra time will be larger or smaller, not measured.
- An `old1` run exists but is excluded: its config step failed (server was down at the time), so its concurrency was whatever the previous aborted attempt had stored. It showed a 843 MB main-process peak, in line with old2/old3.
- Children (exiftool) never exceeded one 21 MB process, for both settings, so the metadata concurrency change shows no measurable effect here (see the note in the remediation list). A test with real photos carrying EXIF/XMP would be needed to measure it.
- Three runs per setting would be too few to quote a variance; the old and new groups do not overlap at all (old 807-811 vs new 556-595), so the thumbnail effect is not noise.

### Harness (kept in `~/sessions/2026-10-29-immich-effect-v4-live-test/burst/`)

Test image: `ffmpeg -loglevel error -y -f lavfi -i mandelbrot=size=6000x4000 -frames:v 1 -q:v 3 src.jpg` (about 2 MB); every run copies it 22 times and appends 64 random bytes so each upload has a different checksum. Admin user `admin@test.local`, Postgres on port 55434 and Valkey on 56391 (containers `livetest-pg` / `livetest-redis`), server on 22830 started by a `run.sh` that exports the `DB_*`, `REDIS_*`, `IMMICH_MEDIA_LOCATION`, `IMMICH_BUILD_DATA` (geodata stub as in the first section) and `IMMICH_PORT` variables and runs `node dist/main.js`.

`sampler.py`:

```python
#!/usr/bin/env python3
"""Samples RSS of the immich main process, its api worker and all their descendants every 0.3s.
usage: sampler.py <main_pid> <out.csv> <stopfile>"""
import os, sys, time
main = int(sys.argv[1]); out = sys.argv[2]; stop = sys.argv[3]

def procs():
    r = {}
    for d in os.listdir('/proc'):
        if not d.isdigit(): continue
        try:
            with open(f'/proc/{d}/stat') as f: s = f.read()
            comm = s[s.index('(')+1:s.rindex(')')]; rest = s[s.rindex(')')+2:].split()
            ppid = int(rest[1])
            with open(f'/proc/{d}/status') as f:
                rss = next(int(l.split()[1]) for l in f if l.startswith('VmRSS:'))
            r[int(d)] = (ppid, comm, rss)
        except Exception: pass
    return r

with open(out, 'w') as f:
    f.write('t,main_kb,api_kb,children_kb,nchildren\n')
    t0 = time.time()
    while not os.path.exists(stop):
        p = procs()
        m = p.get(main, (0,'',0))[2]
        api = sum(v[2] for k,v in p.items() if v[0]==main and v[1]=='immich-api')
        desc, frontier = set(), {main}
        while frontier:
            nxt = {k for k,v in p.items() if v[0] in frontier and k not in desc}
            desc |= nxt; frontier = nxt
        kids = [k for k in desc if p[k][1] != 'immich-api']
        f.write(f'{time.time()-t0:.1f},{m},{api},{sum(p[k][2] for k in kids)},{len(kids)}\n'); f.flush()
        time.sleep(0.3)
```

`run_burst.sh` (usage `./run_burst.sh <label> <thumbConcurrency> <metaConcurrency>`):

```bash
#!/bin/bash
# usage: run_burst.sh <label> <thumbConcurrency> <metaConcurrency> [count]
set -u
LABEL=$1; THUMB=$2; META=$3; N=${4:-22}
T=~/sessions/2026-10-29-immich-effect-v4-live-test; B=http://localhost:22830; D=$T/burst/$LABEL; mkdir -p $D
psq(){ podman exec livetest-pg psql -U postgres -d immich -At -c "$1"; }
tok(){ curl -s -X POST $B/api/auth/login -H 'Content-Type: application/json' -d '{"email":"admin@test.local","password":"livetest123"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["accessToken"])'; }
# 1. config: job concurrency, watcher off
TOK=$(tok)
curl -s "$B/api/system-config" -H "Authorization: Bearer $TOK" | python3 -c "
import sys,json;c=json.loads(sys.stdin.read(),strict=False)
c['job']['thumbnailGeneration']['concurrency']=$THUMB; c['job']['metadataExtraction']['concurrency']=$META
c['library']['watch']['enabled']=False
print(json.dumps(c))" > $D/cfg.json
curl -s -o /dev/null -w "config %{http_code}\n" -X PUT $B/api/system-config -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' -d @$D/cfg.json
# 2. restart server for a clean baseline
for pid in $(ss -ltnp | grep ':22830' | grep -o 'pid=[0-9]*' | cut -d= -f2); do kill $pid; done; sleep 4
nohup $T/run.sh > $D/server.log 2>&1 &
for i in $(seq 40); do curl -sf $B/api/server/ping >/dev/null && break; sleep 1; done
sleep 20
MAIN=$(ps -eo pid,comm | awk '$2=="immich"{print $1}' | head -1)
echo "main pid $MAIN"
# 3. images: N distinct 24 MP jpegs
for i in $(seq $N); do cp $T/burst/src.jpg $D/img$i.jpg; head -c 64 /dev/urandom >> $D/img$i.jpg; done
rm -f $D/stop; python3 $T/burst/sampler.py $MAIN $D/rss.csv $D/stop &
SP=$!; sleep 3
TOK=$(tok)
START=$(date +%s)
SINCE=$(psq "select now()")
ls $D/img*.jpg | xargs -P4 -I{} bash -c 'curl -s -o /dev/null -X POST '$B'/api/assets -H "Authorization: Bearer '$TOK'" -F deviceAssetId=$(basename {})-'$LABEL' -F deviceId=burst-'$LABEL' -F fileCreatedAt=2026-10-29T00:00:00.000Z -F fileModifiedAt=2026-10-29T00:00:00.000Z -F assetData=@{}'
echo "uploaded in $(( $(date +%s) - START ))s"
# 4. wait until every asset has a thumbnail and metadata
for i in $(seq 300); do
  DONE=$(psq "select count(*) from asset a join asset_job_status j on j.\"assetId\"=a.id where a.\"originalFileName\" like 'img%.jpg' and a.\"createdAt\" > '$SINCE' and j.\"metadataExtractedAt\" is not null and exists (select 1 from asset_file f where f.\"assetId\"=a.id and f.type='thumbnail')")
  [ "$DONE" = "$N" ] && break; sleep 2
done
echo "processed $DONE/$N after $(( $(date +%s) - START ))s"
sleep 15   # settle
touch $D/stop; wait $SP
python3 - $D/rss.csv <<'PY'
import csv,sys
rows=list(csv.DictReader(open(sys.argv[1])))
f=lambda k:[int(r[k]) for r in rows]
mb=lambda kb: round(kb/1024)
idle=rows[:8]
tot=[int(r['main_kb'])+int(r['api_kb'])+int(r['children_kb']) for r in rows]
print(f"idle:  main {mb(sum(map(int,[r['main_kb'] for r in idle]))/len(idle))} MB  api {mb(sum(map(int,[r['api_kb'] for r in idle]))/len(idle))} MB")
print(f"peak:  main {mb(max(f('main_kb')))} MB  api {mb(max(f('api_kb')))} MB  children {mb(max(f('children_kb')))} MB (max {max(f('nchildren'))} procs)  node+children total {mb(max(tot))} MB")
print(f"final: main {mb(f('main_kb')[-1])} MB  api {mb(f('api_kb')[-1])} MB  children {mb(f('children_kb')[-1])} MB  total {mb(tot[-1])} MB")
PY
echo "pg: $(podman stats --no-stream --format '{{.MemUsage}}' livetest-pg)  valkey: $(podman stats --no-stream --format '{{.MemUsage}}' livetest-redis)"
```

Gotchas hit while measuring:
- The first version identified the batch with a `deviceId` column on `asset`; this schema has none, so the "all processed" check never matched and the run sat for its 10-minute timeout. The script now selects the batch by `originalFileName like 'img%.jpg'` and `createdAt` after the start time.
- Starting a run right after killing the server makes the first config call fail (`config 000`). The queue now only runs after the server is up, and the table above only uses runs whose config call returned 200.
- Killing the server by port (`ss -ltnp | grep :22830`, then `kill <pid>`) rather than `pkill -f`, because `pkill -f` matches its own shell.

### Machine-level findings from the same session

- A hung `tsc --noEmit` (TypeScript 7.0.2 native `tsc`, started through `npm exec` on 2026-10-21 in the first strip session, 8 days elapsed, 2h44m CPU) held 2.8 GB RSS, the largest process on the machine. It ignored SIGTERM and needed SIGKILL. This, not the server, was the biggest memory user on the box. Cause of the hang not investigated.
- An orphaned `immich-api` (272 MB, parent pid 1) from the 2026-10-28 smoke test was still holding port 2283, pointing at databases that no longer existed. Killed.
- Build-time memory (`tsc`, `nest build`, `vite build`, image build) is still not measured anywhere in this repo.
