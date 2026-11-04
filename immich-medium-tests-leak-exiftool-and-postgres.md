---
type: troubleshooting
tags: [immich, vitest, exiftool, exiftool-vendored, testcontainers, ryuk, podman, memory, orphan-processes, fedora]
created: 2026-11-05
last_verified: 2026-11-05
status: current
---

# Immich medium tests leak exiftool processes (11 GB RAM) and Postgres containers

Repo `~/immich`, branch `effect-v4` (fork `txtsamu/immich`, remote `fork`). Fixed in commits `71183f6cf` (exiftool) and `a34176ec3` (Postgres), both pushed and part of PR #1.

## Symptom

The desktop (61 GB RAM, Fedora/COSMIC) showed 33 GB used, 1.9 GB free and 6.2 of 8 GB swap in use. No single big process explained it.

## Time estimate

All figures are measurements from this session.

| Step | Time |
|---|---|
| Diagnosis (process survey, tracing the parent) | ~5 min |
| Two metadata medium specs (reproduce / verify) | 7 s |
| Full medium suite (60 files, 577 tests) | 11 s |
| Whole fix, including verification | ~15 min |

## Diagnosis

1. Free vs. per-process view. `ps` RSS over-counts shared pages, so sum PSS per command name instead:

   ```bash
   python3 - <<'E'
   import os,collections
   a=collections.Counter();n=collections.Counter()
   for p in os.listdir('/proc'):
       if not p.isdigit(): continue
       try:
           c=open(f'/proc/{p}/comm').read().strip()
           for l in open(f'/proc/{p}/smaps_rollup'):
               if l.startswith('Pss:'): a[c]+=int(l.split()[1]); n[c]+=1
       except Exception: pass
   for k,v in a.most_common(14): print(f"{v/1024:8.0f} MB {n[k]:3d}  {k}")
   E
   ```

   Top entry: **581 `perl` processes, 11.1 GB** (about 19 MB each). Firefox came second at ~7.9 GB.

2. Who owns them. Group the perl processes by parent PID (read `/proc/<pid>/stat` field 4) and print the cmdline:

   - Parent of all 581 was PID 1 (orphans).
   - Command line: `perl .../node_modules/.pnpm/exiftool-vendored.pl@13.59.0/.../bin/exiftool -stay_open True -@ -`.
   - So they are `exiftool-vendored` batch-cluster workers from `~/immich`, whose Node parent had exited.

3. Killed only those (matching comm `perl`, parent PID 1, cmdline containing `exiftool-vendored`, own uid): used memory went 33 GB to 21 GB, available 28 GB to 40 GB.

4. Find which code creates them. `server/src/repositories/metadata.repository.ts` builds `new ExifTool({...})` in `MetadataRepo.make`; a `teardown()` exists (`exiftool.end()`) but test code never called it. `media.repository.ts` and `server-info.repository.ts` use the library's global `exiftool` singleton.

5. Reproduce on the smallest set that uses a real `MetadataRepository`:

   ```bash
   cd ~/immich/server
   export NODE24=1; . ~/sessions/2026-10-28-immich-env-tests/env.sh   # podman/testcontainers env + node 24
   pnpm exec vitest run --config test/vitest.config.medium.mjs \
     test/medium/specs/repositories/metadata.repository.spec.ts \
     test/medium/specs/services/metadata.service.spec.ts
   pgrep -fc '^perl .*exiftool-vendored'     # 19 orphans left after 12 tests
   ```

## Root cause

- Every `newMediumService(...)` call with `MetadataRepository` in `real: [...]` creates its own `ExifTool` pool, and one test file calls `setup()` many times.
- Nothing ended the pools. Vitest tears workers down without running exit hooks, so the `-stay_open` perl children are re-parented to PID 1 and live on after the run.
- Each test run therefore added a batch of ~19 MB perl processes; repeated runs and reruns over days accumulated 581 of them.

## Fix 1: end ExifTool pools after every medium spec file (`71183f6cf`)

In `server/test/medium.factory.ts`:

- A module-level `Set<MetadataRepository>`; `MediumTestContext.get()` adds every real `MetadataRepository` it creates.
- `export const teardownMediumTestResources = async () => {...}` ends all of them with `repository.teardown()` plus the global singleton `exiftool.end()`, via `Promise.allSettled`.

New `server/test/medium/setup.ts`:

```ts
import { teardownMediumTestResources } from 'test/medium.factory.js';

afterAll(async () => {
  await teardownMediumTestResources();
});
```

`server/test/vitest.config.medium.mjs`: `setupFiles: ['test/setup.ts', 'test/medium/setup.ts']`. No production code changed.

Result: same two specs leave **0** orphans (was 19); full medium suite 60 files / 577 tests pass, 0 orphans afterwards.

## Fix 2: stop the Postgres container in globalSetup (`a34176ec3`)

`server/test/medium/globalSetup.ts` starts a `ghcr.io/immich-app/postgres:14-vectorchord0.4.3` container and never stopped it. Normally Testcontainers' Ryuk reaper cleans up, but the podman env disables it (`TESTCONTAINERS_RYUK_DISABLED=true`), so every run left a container up. `podman ps` showed 8 of them (5 six days old).

The fix is to return a teardown function from `globalSetup` (vitest runs it after the suite):

```ts
  return async () => {
    await postgresContainer.stop();
  };
```

Verified: container count was 8 before a full run and 8 after, so the run's own container was started and stopped.

## Cleaning up what was already leaked

```bash
# exiftool orphans (parent PID 1, cmdline has exiftool-vendored)
pkill -f '^perl .*exiftool-vendored'
# old test Postgres containers (the auto-mode classifier blocked this when I ran it; the containers were gone at the next check)
podman ps -aq --filter ancestor=ghcr.io/immich-app/postgres:14-vectorchord0.4.3 | xargs -r podman rm -f -v
```

After cleanup: 21 GB used, 40 GB available, swap 2.5 of 8 GB (pages return from swap only when touched, `sudo swapoff -a && sudo swapon -a` forces it).

## Gotchas and dead ends

- `pkill -f 'perl.*exiftool-vendored.*stay_open'` run from inside a Bash tool call also matches the calling shell (its own command line contains the pattern) and kills it (exit 144). Anchor the pattern with `^perl ` so it only matches the real processes.
- `ps` RSS sums double-count shared memory (Firefox content processes); use PSS from `smaps_rollup` for totals.
- Firefox, Telegram, VS Code and the nine `claude` sessions were large but normal; the leak was the only thing that did not belong.
- Unit tests (`test/vitest.config.mjs`) use mocked repositories and do not spawn exiftool; only the medium suite (and e2e) were relevant.
