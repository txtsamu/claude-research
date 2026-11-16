---
type: how-to
tags: [docx, ooxml, python-docx, letterhead, kop-surat, word-header, libreoffice]
created: 2026-11-16
last_verified: 2026-11-16
status: current
---

# Moving a DOCX letterhead (kop surat) into a repeating page header

Session on `/home/moo/Documents/Surat Permohonan` (not a git repo). Files:
`KOP SURAT SMAN 50.docx` (the blank letterhead) and
`Surat Permohonan GBK.docx` (the request letter). Task: make the letter use the
kop surat.

## The surprise

The letter already carried the kop, byte for byte. Comparing the unpacked
`word/document.xml` of both files showed the whole block (logo anchor, five
centred text paragraphs, the thick-thin rule) was identical, down to the logo
PNG (`md5 92c5b84a2f39ef7e4cd6b6b726657c3e`). Only `w14:paraId`,
`wp14:editId` and the relationship ids differed (`rId4`/`rId5` in the kop file
vs `rId5`/`rId6` in the letter, because the letter also holds `image2.png`, the
signature + stamp photo, 336 KB).

So the literal request was already satisfied. What the user actually wanted was
the kop promoted out of the body into a real page header: locked at the top of
the sheet, repeating on page 2+, and no longer shoved around by body text.

## What was done

Worked on an unpacked copy in `/tmp/opencode/work`, then rezipped:

1. Sliced the body at the paragraph holding `Jakarta, 19 November 2025`. Everything
   before it (11,173 bytes, 7 paragraphs) is the kop.
2. Wrote `word/header1.xml`: `<?xml ...?><w:hdr ...>` plus that exact block, reusing
   the `w:document` root attribute string so every namespace prefix (`wps`, `mc`,
   `wp14`, `a14`, ...) is declared. `w:document` became `w:hdr`, nothing else.
3. Pointed the embeds at the header's own rels: `rId5` -> `rId1` (image1.png),
   `rId6` -> `rId2` (hdphoto1.wdp). A header part cannot borrow the document's
   relationship ids.
4. New `word/_rels/header1.xml.rels` with those two targets. Content types already
   had `png` and `wdp` defaults, so only an `<Override PartName="/word/header1.xml">`
   with the `...wordprocessingml.header+xml` type was needed.
5. `document.xml.rels`: `rId100` -> `header1.xml` (type `.../relationships/header`).
6. `<w:headerReference w:type="default" r:id="rId100"/>` as the first child of
   `<w:sectPr>`.
7. `w:header="142"` in `w:pgMar`, matching the existing `w:top="142"`. Those
   margins are already extreme (top 0.098", left 0.985", right 0.688", bottom
   0.7875"), inherited from the original template.

## Gotchas

- **`re.match` on document.xml fails silently.** The file opens with the XML
  declaration, so the root tag has to be found with `re.search`. Cost one rerun.
- **Vertical snap.** With `w:docGrid w:linePitch="360"` (18 pt), the first body
  paragraph landed 7 px higher once it started below the header instead of
  following the rule paragraph. Adding `<w:spacing w:before="100"/>` (5 pt) to
  the date paragraph restored the date line to y=174 px (was 175) and pushed the
  rest of the letter one grid step (7 px) lower. Everything still fits on one A4
  page with room under the signature.
- **Header height is implicit.** No `<w:height>` exists for headers; Word sizes
  the header to its content and pushes body text below it. Setting header
  distance equal to the top margin is what keeps the kop pinned to the sheet top.
- **[Content_Types].xml first.** `zip -Xr` walked the directory and put it last.
  Rebuilt with Python `zipfile` ordering that entry first, purely to match the
  OPC convention.
- **Unused relationships are legal.** The body no longer references `rId5`/`rId6`
  but they stayed in `document.xml.rels`; Word ignores orphans.

## Verification

`python3 .../docx/scripts/office/validate.py out.docx --original <letter>` needed
`defusedxml` (not installed, `pip install defusedxml`):

```
Paragraphs: 34 → 27 (-7)
All validations PASSED!
```

Repetition test: duplicated the body once inside a throwaway copy to force two
pages, rendered it, and page 2 showed the full kop on top. Rendered final layout
with `soffice --headless --convert-to pdf` + `pdftoppm -jpeg -r 100`, then read
the JPEGs and compared pixel rows against the original render.

Final file: 371,169 bytes, 27 zip entries, `zip.testzip()` clean, `word/header1.xml`
present, one A4 page (595.3 x 841.9 pt). Original kept as
`Surat Permohonan GBK - backup sebelum kop.docx`.

## Not verified

- Rendering inside Microsoft Word. Only LibreOffice 7.x was available, so header
  distance handling, `mc:AlternateContent` fallback for the rule shape, and the
  `a14:backgroundRemoval` on the logo are confirmed for LO only.
- Whether the received letter actually needs the kop on page 2 at all; it is one
  page today, the repetition is just a side effect of using a default header.

## Loose end

The letter is dated `Jakarta, 19 November 2025` with the event on
`Sabtu, 29 November 2025` (29 Nov 2025 was indeed a Saturday). The session ran on
2026-11-16, so the dates are a year stale. Left untouched, flagged to the user.

Related: [[docx-letterhead-extraction]], [[libreoffice-headless-docx-render]]
