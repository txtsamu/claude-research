---
type: how-to
tags: [truenas, music, flac, mutagen, metadata, dedupe, romaji, nfs]
created: 2026-10-22
last_verified: 2026-10-22
status: current
---

# Music library on TrueNAS: duplicate scan, tag cleanup, romaji titles

Host: `moo@192.168.50.10` (TrueNAS SCALE 25.10, dataset `data/photos`). The share is NFS-mounted on fedora at `~/nfs_photos` (`music/`, `music-archives/`). The NAS has no ffprobe/mutagen, so all tag work was run from fedora against the NFS mount.

## 1. Duplicate scan (read-only)

No dedupe tools on the NAS. Size-group, then sha256 each group, in Python over `music/` + `music-archives/` (~29 GB, ~7 min):

```bash
ssh moo@192.168.50.10 'cd /mnt/data/photos && python3 -' <<'PY'
import os,hashlib,collections
by=collections.defaultdict(list)
for r in ("music","music-archives"):
    for dp,_,fs in os.walk(r):
        for f in fs:
            p=os.path.join(dp,f); by[os.path.getsize(p)].append(p)
# for each size bucket with >1 file: sha256 each file, report groups with identical hashes
PY
```

Result: 254 dup groups, ~1.7 GB. The real ones were 8 archives (7 .zip + 1 .rar) in `music/` that were byte-identical to the copies in `music-archives/`; the rest were `.thumbnails/*.jpg` noise. Re-verified each with `cmp -s` and deleted the 8 from `music/` only (user approved).

## 2. Tag survey (mutagen, easy mode)

```bash
cd ~/nfs_photos/music && python3 -I - <<'PY'
import os
from mutagen import File
# File(p, easy=True) per .flac/.mp3; count missing title/artist/album/albumartist/tracknumber/date/genre
PY
```

820 flac/mp3 readable. Missing: albumartist 243, genre 113, date 60. Gotchas found:

- `.dsf` files store ID3 (TIT2/TPE1...). `easy=True` returns nothing for them, so they look untagged but are not. Use `File(p)` and `m.tags["TIT2"]`.
- `Telegram/SAMSONS - Bukan Diriku.flac` is really an MP3 (starts with `ID3`); mutagen's FLAC loader fails on it. Not renamed, only reported.
- `au_uu_SzH34yR2.mp3` is an empty/0-second junk file.
- `Telegram/` is a flat dump of ~500 tracks across 200+ albums.

## 3. Fixes applied

1. Tag backup first: `~/music-tag-backup/tags-2026-10-22.json` (all easy tags) and `dsf-titles-2026-10-22.json`.
2. `albumartist` filled from `artist` for groups where one (folder, album) has exactly one distinct artist: 211 files / 96 albums. 32 files in 7 ambiguous groups (compilations such as "POP SEBLAY", "ALL OUT") were skipped on purpose.
3. 52 flac/mp3 titles + 2 dsf titles in Japanese/Korean converted to Latin. Machine romanization was tried first (`pip install pykakasi hangul-romanize` in a venv) and rejected: it mis-segments ("Wonazotte", "Kanashimi Gatomaranai", "Kake Ru", particle は as "Ha"). Final titles were written by hand (Hepburn without macrons, particles wa/o/e, Revised Romanization for Korean) and cross-checked online (references below).
4. Cross-check changes: `もしも命が描けたら` -> "Moshimo Inochi ga Kaketara", `アドレナ` -> "Adrena", and the Ride On Time album tracks use the album's official titles (Someday, The Door Into Summer, Clouds, Kissing Goodnight).
5. Gotcha: `pip download` run with cwd on the NFS dir dropped 4 wheel files into `music/`; removed. Run pip from the scratchpad/venv.

## Not verified / left alone

Yiruma's Korean titles (English names not found), "Suki da" / "Mister" / "Seventeen" track membership of THE BOOK 3 (sources conflict), Moonglow "Ai o Egaite -Let's Kiss The Sun-" and "Sunshine -Ai no Kin'iro-", the DSF `スパークル` (no tags) and `上白石萌音` (an artist name used as the title).

## Tool recommendations (from search; no rigorous benchmarks found)

- Exact duplicates: jdupes/fdupes (byte compare), czkawka (also has a similar-music mode), dupeGuru (tag/fuzzy filename modes).
- Audio-fingerprint duplicates: Similarity, or commercial Audio Dedupe.
- Tagging: MusicBrainz Picard (GUI, album-level) or beets (CLI, scripted), both MusicBrainz-based.

## References

- [The Book (Yoasobi EP)](https://en.wikipedia.org/wiki/The_Book_(Yoasobi_EP)), [The Book 3](https://en.wikipedia.org/wiki/The_Book_3), [The Book For,](https://en.wikipedia.org/wiki/The_Book_For,)
- [THE BOOK 2 tracklist (breezewiki)](https://breezewiki.discard.no/jpop/wiki/THE_BOOK_2), [THE BOOK (Singapore Airlines)](https://krisworld.singaporeair.com/ife/krisworlddigital/audio/thebook_album.html)
- [Ride on Time (album)](https://en.wikipedia.org/wiki/Ride_on_Time_(album)), [Tatsuro Yamashita - Spacy](https://insheepsclothinghifi.com/album/tatsuro-yamashita-spacy/), [Moonglow](https://en.wikipedia.org/wiki/Moonglow_(Tatsuro_Yamashita_album))
- [Timely!!](https://en.wikipedia.org/wiki/Timely!!), [Kanashimi ga Tomaranai (Generasia)](https://www.generasia.com/wiki/Kanashimi_ga_Tomaranai)
- [Gee (EP)](https://en.wikipedia.org/wiki/Gee_(EP)), [Gee (Generasia)](https://www.generasia.com/wiki/Gee)
- Dedupe tools: [dupeGuru alternatives](https://alternativeto.net/software/dupeguru), [jdupes alternatives](https://alternativeto.net/software/fdupes-jody), [best duplicate song finders](https://www.mindgems.com/article/best-duplicate-song-finder/)
- Taggers: [beets vs picard](https://www.libhunt.com/compare-beets-vs-picard), [MusicBrainz Picard alternatives](https://www.alternativeto.net/software/musicbrainz-picard/)
