---
type: investigation
tags: [immich, external-library, offline-assets, trash, nestjs, effect, kysely]
created: 2026-10-29
last_verified: 2026-10-29
status: current
---

# Why Immich trashes moved external-library files, and relinking them instead

Question: when a file in an external library is moved or renamed, why does its asset go offline and into the trash instead of just getting a new path? Answer: by design, because external assets are identified by their path. Fixed in the fork (`effect-v4` commit `4bde5bc5a`) by relinking on a size + mtime + type match. Follow-up commit `9a530a06b` makes the file watcher take deleted files offline instead of removing them, and lets deleting from the trash remove the original files of offline assets (see the last section).

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

- Library watcher: fixed in the follow-up below (it used to delete the asset on unlink).
- Ambiguous cases are imported as new assets: several missing assets or several new files with identical size + mtime + type (for example burst copies made with `cp -p`).
- A move that changes mtime (plain `cp` + `rm`, or tools that touch files) is not matched.
- Assets with no exif row yet (metadata extraction not finished) have no size to match.
- Assets already split before this change (an offline trashed row plus a new row) are not merged.
- Medium tests (real Postgres) were not run for the relink query itself; it was exercised only through the live instance above.

## Follow-up (commit `9a530a06b`): watcher offline + deleting originals from the trash

Request: make the watcher take deleted files offline instead of removing them, and make the trash pages able to delete the original files to free storage (most files are in external libraries).

### What the code did before (checked first, because part of it already worked)

- Emptying the trash or force-deleting an **online** external asset already deleted the original file: `handleAssetDeletion` (asset.service.ts) pushes `asset.originalPath` into the `FileDelete` job when `deleteOnDisk` is true. Confirmed live: `DELETE /api/assets {force:false}`, `POST /api/trash/empty`, the file under the library was gone after a few seconds.
- It skipped the file when `asset.isOffline` (`deleteOnDisk = request && !asset.isOffline`). For an asset offlined by an exclusion pattern or import-path change the file is still on disk, so that storage was never freed.
- `Trash.empty` (trash.repository.ts) only turned `status = Trashed` into `Deleted`. A scan offlines an asset by setting `isOffline` + `deletedAt` and leaves `status = Active`, so "Empty trash" silently skipped every offline asset (they stay visible on the trash page).
- Watcher: `unlink` queued `LibraryRemoveAsset`, which called `asset.remove`. And watcher `add`/`change` queued `LibrarySyncFiles` straight into `createAll` with no check for an existing asset, which would hit the unique (owner, library, checksum) constraint for a path that now has an offline asset.

### Changes

1. `handleAssetRemoval` (job `LibraryRemoveAsset`, name kept so queued jobs still work): skip unknown or already-offline assets, `stat` the path and skip if the file is back (editors that save by replacing the file), otherwise `updateAll([id], { isOffline: true, deletedAt: now })`; an asset with `status = Trashed` only gets `isOffline: true`.
2. `handleSyncFiles`: `filterNewExternalAssetPaths` splits the batch into new paths and known paths. New helper `syncKnownFiles` brings a known offline asset back online (a user-trashed one stays trashed) and queues a metadata refresh when a known online file's mtime changed. The relink from the first change then handles a watcher rename (unlink marks offline, add relinks, in either order).
3. `IAssetDeleteJob.deleteOffline?: boolean`. `handleAssetDeletion` now uses `deleteOnDisk = request && (!asset.isOffline || deleteOffline)` and passes `deleteOffline` on to the live-photo motion part. `TrashService.handleEmptyTrash` (user emptied the trash or force-deleted selected items) sets it to true. The automatic expiry (`handleAssetDeletionCheck`) does not, on purpose: otherwise adding an exclusion pattern would delete those files from disk 30 days later without the user doing anything.
4. `Trash.empty` also takes `status = Active AND isOffline AND deletedAt IS NOT NULL`.
5. en.json: `empty_trash_confirmation` and `permanently_delete_assets_prompt` now say external library files are deleted from disk. Docs: watcher paragraph, relink section, new "Deleting from the trash" section in `docs/docs/features/libraries.md`.
6. Tests: 11 new unit tests (library, asset, trash services), one medium test (`test/medium/specs/repositories/trash.repository.spec.ts`, real Postgres; `TrashRepository` added to `test/medium.factory.ts`). Regenerated `src/queries/trash.repository.sql`.

### Verification

- Unit: 2144 pass, 3 fail (same Node 22 environmental). Medium (real Postgres via `DOCKER_HOST=unix:///run/user/1000/podman/podman.sock TESTCONTAINERS_RYUK_DISABLED=true`, `--config test/vitest.config.medium.mjs`): 576 pass, 1 fail (`mkdtempDisposable` on Node 22). Full eslint and `tsc` clean.
- Live, watcher enabled via `PUT /api/system-config` (`library.watch.enabled = true`, picked up without a restart):
  - `rm` of a watched file: row stays, `isOffline=t`, `deletedAt` set, status active.
  - File re-created at the same path: asset online again, `deletedAt` cleared, no duplicate.
  - `mv b/p4-copy.jpg b/watcher-renamed.jpg`: same asset id, new path, online.
  - Exclusion `**/c/**` then scan: `c/p4.jpg` goes offline but its file stays; `POST /api/trash/empty`: row removed and `c/p4.jpg` deleted from disk.

### Still open

- A watched move where the new file's mtime/size differ from the stored values is not matched (same limits as the scan relink).
- Offline assets that were already stuck in the trash before this change are removed by the next "Empty trash" (and their files too if still on disk), which is a visible change for existing installs.
- Web UI was rebuilt with the new texts but not clicked through in a browser.
