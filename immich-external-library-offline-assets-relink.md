---
type: investigation
tags: [immich, external-library, offline-assets, trash, nestjs, effect, kysely]
created: 2026-10-29
last_verified: 2026-10-29
status: current
---

# Why Immich trashes moved external-library files, and relinking them instead

Question: when a file in an external library is moved or renamed, why does its asset go offline and into the trash instead of just getting a new path? Answer: by design, because external assets are identified by their path. Fixed in the fork (`effect-v4` commit `4bde5bc5a`) by relinking on a size + mtime + type match.

## Why it happens (code in `server/src/services/library.service.ts`)

- `processEntity` gives every external asset `checksum = sha1("path:<assetPath>")` with `checksumAlgorithm = sha1-path`. Identity is the path; file content is never hashed.
- `handleSyncAssets` calls `checkExistingAsset`; a missing file returns `OFFLINE`, which runs `updateAll(ids, { isOffline: true, deletedAt: new Date() })`. That is the trash. `detectOfflineExternalAssets` (asset.repository.ts) does the same when import paths or exclusion patterns change.
- `handleQueueSyncFiles` crawls the disk and `filterNewExternalAssetPaths` keeps every path with no asset at that path, so the moved file is imported as a brand-new asset.
- The watcher sees a rename as unlink + add; unlink queues `LibraryRemoveAsset`, which deletes the asset outright.
- An offline asset only comes back when a file reappears at the *same* path (`CHECK_OFFLINE`).
- Upstream baseline `166e93559` has the same logic, so neither the AI strip nor the Effect rewrite caused it.

Reproduced on a live instance: library with `old/photo.jpg`, scan, `mv` to `new/photo.jpg`, scan. DB then has `new/photo.jpg` (online) and `old/photo.jpg` (`isOffline=t`, `deletedAt` set), both `sha1-path`. Albums, favourites and tags stay on the trashed row.

## The fix

When `handleSyncFiles` is about to import new paths, `relinkMovedAssets` first looks for assets that moved:

1. Build a signature per new file: `(mtime, size, type)` from the `stat` that `processEntity` already does. Skip signatures shared by more than one new file in the batch.
2. `AssetRepository.findExternalRelinkCandidates(libraryId, signatures)` (new, in chunks of 500) returns external assets of that library, status not `Deleted`, whose `asset.fileModifiedAt`, `asset_exif.fileSizeInByte` and `asset.type` match. Offline or not, trashed or not.
3. `stat` each candidate's old path; keep only the ones whose file is gone. A candidate that still exists is a copy, not a move.
4. For each signature with exactly one new file and exactly one missing candidate, `asset.update({ id, originalPath, originalFileName, checksum, isOffline: false, deletedAt: null })`. If the candidate had `status = Trashed` (trashed by the user) `deletedAt` is left alone so it stays in the trash.
5. A failed update (for example a unique-constraint hit) logs a warning and that file is imported normally. Relinked ids get the same post-sync jobs as imports (`SidecarCheck`, then metadata).

Works in either order of the two scan jobs: the old asset may still be online (missing from disk but not yet offlined) or already offline+trashed.

Why size + mtime: `mv` keeps mtime and size, and exif `fileSizeInByte` is stored from `stat.size` at metadata extraction. Not a content hash on purpose; hashing every file in a large library on scan is the expensive thing external libraries avoid.

Files changed: `asset.repository.ts` (query + `ExternalFileSignature` type), `library.service.ts`, `library.service.spec.ts` (6 new tests), `test/repositories/asset.repository.mock.ts`, regenerated `src/queries/asset.repository.sql` (`node dist/bin/sync-sql.js` against a migrated DB), and a new "Moved and renamed files" section in `docs/docs/features/libraries.md`.

## Verification

- Unit suite: 2133 pass, 3 fail (same Node 22 `mkdtempDisposable`/media environmental failures as before the change). `tsc` and eslint clean on the changed files.
- Live (server built from the branch, empty library `ext2`, 4 JPEGs with distinct mtimes, metadata extracted first; commands: `mv`, `cp -p`, then `POST /api/libraries/<id>/scan`):

| Action | Result |
|---|---|
| rename in place (`p1.jpg` to `renamed.jpg`) | same asset id, new path, online; album membership kept |
| move to another dir (`p2.jpg`) | same id, new path; favourite kept |
| rename + move (`p3.jpg` to `b/moved-and-renamed.jpg`) | same id, new path |
| `cp -p` of `p4.jpg` | original untouched, copy imported as a separate asset |
| offline-first order: exclusion `**/c/**`, `mv p4.jpg c/`, scan (p4 goes offline+trashed), remove exclusion, scan | same id relinked to `c/p4.jpg`, `isOffline=f`, trash flag cleared |

## Not covered / limitations

- Library watcher: unlink still deletes the asset immediately, so a move seen by the watcher still creates a new asset. Fixing it means turning unlink into "mark offline" instead of remove, which changes what watcher-detected deletions look like (they would sit in the trash like scan-detected ones).
- Ambiguous cases are imported as new assets: several missing assets or several new files with identical size + mtime + type (for example burst copies made with `cp -p`).
- A move that changes mtime (plain `cp` + `rm`, or tools that touch files) is not matched.
- Assets with no exif row yet (metadata extraction not finished) have no size to match.
- Assets already split before this change (an offline trashed row plus a new row) are not merged.
- Medium tests (real Postgres) were not run for the new query; it was exercised only through the live instance above.
