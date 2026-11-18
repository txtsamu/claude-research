---
type: how-to
tags: [odoo, browse, browser-automation, pdf, payroll, opencode]
created: 2026-11-18
last_verified: 2026-11-18
status: current
---

# Bulk downloading Odoo payslip PDFs with browse

How to pull every payslip PDF out of a self-hosted Odoo 17 instance from an agent session, using the `browse` browser bridge instead of screen-clicking the list view.

## Context

- Host: personal Fedora workstation, user `moo`.
- Target: Odoo 17 at `erp.btech.id`, model `bt_payslips.payslip`, custom module report `bt_payslip.report_bt_payslip`.
- Browser: Brave on Fedora, already signed in to the ERP.
- Tool: `browse` 0.1.5 installed via `curl -fsSL https://opencode.ai/browse/install | bash`; relay on `127.0.0.1:19988`, extension `0.0.17`.

## What worked

1. Installed browse. The installer added it to `~/.config/opencode/opencode.json` and paired the Brave extension automatically. `tools.browse.status` confirmed `connected: true`.
2. Opened the payslip list action URL directly (`/web#action=325&model=bt_payslips.payslip&view_type=list...`).
3. The list was grouped by year and collapsed. Group headers are `tr.o_group_header` with a `th.o_group_name` cell, not `td`. Expand them with a small `eval` that clicks `.o_group_caret.fa-caret-right` parents.
4. Selecting all records: clicking `thead .o_list_record_selector input` selected every row and produced a `39 terpilih` banner plus a `Cetak` dropdown in the control panel. The per-row action menu is a `span.dropdown-item.o_menu_item` inside `.o-dropdown--menu`.
5. The bulk print in this deployment runs a wizard (`action=328`) that renders `/report/html/bt_payslip.report_bt_payslip/<ids>` inside an iframe. That HTML view is not a file.
6. Real PDFs come from the per-record report route:

   `/report/pdf/bt_payslip.report_bt_payslip/<comma-separated-ids>?context=<urlencoded ctx>`

   Fetching that with the page's own session cookies returns `application/pdf` (all ids merged into one document).

## Getting the bytes onto disk

Chrome blocked both obvious routes:

- Script-initiated downloads: first blob download saved, the second was silently dropped by the multiple-downloads guard.
- `POST` to a local helper on `127.0.0.1` from a public HTTPS origin: `TypeError: Failed to fetch` (Private Network Access).

The route that did work is `browse execute`, whose sandbox exposes `files.write(name, data)` inside `files.roots` (`/tmp` here, under `/tmp/opencode-browser-files-<pid>-<rand>`):

1. In the page, `fetch` the report URL, convert to base64 with a chunked `String.fromCharCode` loop, stash it on `window.__pdfb64`.
2. Fetch it back in 32 KB slices with `window.__pdfb64.slice(off, off+CHUNK)`.
3. `files.write("slip-<id>.b64", b64)` per slip.
4. Decode with Python/`base64` on the shell side and name files from the record's month field.

Merge per-slip files into one archive with `pdfunite` (poppler-utils) in chronological order.

## Fixing the signature block that spilled to page 2

20 of the 39 slips overflowed: the template's signature area pushed the names and titles (and in March, the signature image) onto a second, almost empty A4 page, even though page 1 still had 8 to 11 cm of unused space at the bottom.

Because the Odoo paperformat is server-side, the fix was local post-processing with PyMuPDF:

1. Render page 1 at 72 dpi and find the last row containing ink (threshold 250 in grayscale). That row is the true content bottom, including images, which `pdftotext` bbox ignores.
2. Rasterize each extra page the same way and group its ink rows into bands, splitting wherever there is more than 8 blank rows. This separates the signature image from the name/title text so the dead vertical gap between them disappears.
3. Draw page 1 onto a fresh A4 page at 1:1, then `show_pdf_page(target, src, n, clip=band)` each band below the content bottom with a 6 pt gap.
4. Rebuild the merged document.

Result: 39 of 39 slips are one page, text content identical to the originals (`get_text` compared after whitespace normalization), lowest ink at y 40 to 56 pt from the bottom edge. The untrimmed originals are kept at `/tmp/opencode/original-payslips/`.

Note that PyMuPDF page coordinates use a top-left origin with y growing downward, unlike raw PDF user space. Computing clip rectangles with `height - y` mirrors them, and the bands land as blank or garbled strips.

## Gotchas

- A single `browse.eval` result above roughly 100 KB comes back truncated, which silently breaks `JSON.parse`. Chunk anything binary.
- `browse execute --code '...'` and `--timeoutMs ...` need `=` (`--code=...`), otherwise the CLI reports "needs a value".
- Odoo 17 list rows carry no `data-id`; get id to label mapping through `/web/dataset/call_kw/bt_payslips.payslip/read` with `["bulan_slip"]`. Field `name`, `date_from` and `date_to` do not exist on this custom model.
- Record ids are not chronological: in the 2026 group February sorts before January. Sort by the month label, not by id.
- `/root/home/moo/...` is not writable for uid 1000. Confirm the intended path before creating directories.
- Each payslip PDF is ~128 KB (embedded fonts), page count 1 or 2 depending on the month.

## Verification

- `pdfinfo` on a sample reports A4, `%PDF-` header confirmed for all 39 files.
- `pdftotext -layout` shows the right month string, company header and salary components in each file.
- Merged document: `pdfunite` output reports 39 pages, 4.8 MB.
- File count in the destination directory: 39 slips plus 1 merged file.

## Not verified

- Whether the wizard's HTML view has an official "download all" button that Odoo would serve as a zip; the per-record route was faster to automate.
- Behaviour on another Odoo major version; `/report/pdf/<report>/<ids>` is stable across 14 to 17, but the wizard action id (`328`) is deployment specific.

## Related

- [[agentmemory-shared-mcp-multi-host-setup]]
- [[opencode-subagent-depth-and-recommended-setting-2026-11-17]]
- [[prisma-access-browser-fedora43-install-2026-11-13]]
