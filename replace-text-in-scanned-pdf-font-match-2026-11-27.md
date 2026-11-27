---
type: how-to
tags: [pdf, scanning, imagemagick, poppler, fonts, image-editing]
created: 2026-11-27
last_verified: 2026-11-27
status: current
---

# Replacing a text line in a scanned PDF without wrecking the page

A 4-page official letter/invoice bundle arrived as a **scanned image PDF** (no text layer, 200 dpi JPEGs, letterhead + wet stamp + signature). Two address lines had to change and the last page had to go. The pages could not be re-typed: the stamp and signature were part of the same raster, and re-creating the letterhead would never match.

The method below patches the raster in place: white out the line, redraw it in the matched typeface, leave everything else byte-identical.

Applies to any image-only PDF where one or two lines need changing and the page has a plain white background near the edit.

## Time estimate

| Step | Time | Basis |
|---|---|---|
| Render pages at native dpi, confirm no text layer | < 1 min | measured |
| Measure line boxes (rows/columns, baseline, cap height) | ~2 min | measured |
| Identify the typeface by cap-height + ink-width probing | ~3 min (the slow part) | measured |
| Patch, re-render, pixel-diff audit | ~3 min | measured |
| Assemble final PDF, verify untouched pages | ~1 min | measured |
| **Total** | **~10 min** | measured, 18:42 → 18:52 |

No build/compile steps, so wall-clock is mostly the font hunt.

## 1. Confirm it is a scan, and get the native resolution

```bash
pdfinfo "input.pdf"
pdfimages -list "input.pdf"
```

`pdfimages -list` is the important one. It tells you the real pixel dimensions and ppi of every page image:

```
page   num  type   width height color comp bpc  enc interp  object ID x-ppi y-ppi size ratio
   1     0 image    1653  2338  rgb     3   8  jpeg   no         9  0   200   200  344K 3.0%
```

**Edit at the native ppi (`200` here), not higher.** Rendering a 200 dpi scan at 300 dpi only upsamples a blurry source and inflates the file.

If `pdftotext` returns nothing, there is no text layer and no shortcut: this is a raster patch job.

## 2. Measure the lines you are replacing

Render two pages at native dpi and find ink bands with numpy. Row bands give you top/bottom of each line; per-glyph column runs give you the left edge, the baseline and the cap height.

```bash
pdftoppm -png -r 200 -f 1 -l 2 input.pdf nat
```

```python
from PIL import Image
import numpy as np
im = np.array(Image.open('nat-1.png').convert('L'))
a = im[y0:y1, x0:x1] < 140
rows = a.sum(1)
# contiguous non-zero row runs = text lines
```

Then per line, split on empty columns to get glyph boxes. The useful numbers:

- **baseline** = bottom of a capital (`Y`, `P`, `K`), ignoring descenders
- **cap height** = baseline − top of that capital
- **ink left edge** = first dark column
- **ink right edge** = last dark column (tells you the new string must not run into anything)

Measured example, 300 dpi scan: `Yth. …` had cap height 34 px, baseline 915, ink from x=301. Second line cap 33, baseline 974.5 → **line spacing ≈ 59.5 px ≈ 14.3 pt**, which is Word's single-spaced 12 pt look. At 200 dpi those halve to cap 22, baseline 610.

A separate smaller block on page 2 had cap 25 px at 300 dpi (≈ 8.5 pt), so **each page needs its own size**, do not assume one font size for the document.

## 3. Identify the typeface empirically

Do not trust "it looks like Arial". Probe it: render the exact string in every bold candidate on the box, binary-search the size until rendered cap height equals the measured cap height, then compare **ink width**.

```python
from PIL import Image, ImageDraw, ImageFont
import numpy as np

def ink(fontpath, size, text):
    f = ImageFont.truetype(fontpath, size)
    img = Image.new('L', (3000, 300), 255)
    ImageDraw.Draw(img).text((50, 50), text, font=f, fill=0)
    a = np.array(img) < 128
    ys, xs = np.where(a)
    return xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
```

Score against the measured pair `(ink width, cap height)`. Results for this document (target = 417 px wide, 33 px cap):

```
NimbusSans-Bold.otf      sz45 cap33 w407/417   <- winner
FreeSansBold.ttf         sz45 cap33 w412/417
DroidSans-Bold.ttf       sz46 cap33 w415/417
LiberationSans-Bold.ttf  sz47 cap33 w428/417
DejaVuSans-Bold.ttf      sz45 cap33 w485/417
LiberationSansNarrow-Bold sz48 cap33 w358/417
```

`NimbusSans-Bold` (URW's Helvetica clone, at `/usr/share/fonts/urw-base35/`) matched within ~2%. Liberation Sans is the Arial-metric clone, and it was 3% too wide, which is exactly the kind of gap that makes a patch look "off" when the neighbouring line sits right below it.

Check the second string too, not just one. Here page 2 gave `353/351` for Nimbus at cap 25, which confirmed it.

## 4. White out and redraw

Keep it stupid simple:

```python
from PIL import Image, ImageDraw, ImageFont, ImageFilter

INK = (20, 18, 18)   # sampled from the scan's glyph cores, not pure black

img = Image.open('nat-1.png').convert('RGB')
ImageDraw.Draw(img).rectangle([185, 580, 820, 620], fill=(255, 255, 255))

f = ImageFont.truetype('/usr/share/fonts/urw-base35/NimbusSans-Bold.otf', 30)
lsb = f.getbbox(text, anchor='ls')[0]          # left side bearing
layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
ImageDraw.Draw(layer).text((ink_x - lsb, baseline_y), text, font=f,
                           fill=INK + (255,), anchor='ls')
layer = layer.filter(ImageFilter.GaussianBlur(0.4))   # match scan softness
img.paste(Image.alpha_composite(img.convert('RGBA'), layer).convert('RGB'), (0, 0))
```

Details that matter:

- **`anchor='ls'` = left + baseline**, which is the only sane way to land text on a measured baseline. Then subtract the glyph's left side bearing so *ink* starts at the measured x, not the font origin.
- **Blur the text layer by ~0.4 px.** A crisp vector glyph dropped into a JPEG scan reads as obviously pasted when zoomed.
- **Sample the ink colour** from the original (here `(20,18,18)`, slightly warm), not `(0,0,0)`.
- **White fill is safe only on a clean scan.** This one had pure `255` paper around the block; a paper-textured scan needs a background patch plus matched noise instead.

## 5. Audit the diff before shipping

Re-render the edited page at native dpi and diff it against the untouched render. Anything outside the intended boxes is a mistake.

```python
A = np.array(Image.open('nat-1.png').convert('L')).astype(int)
B = np.array(Image.open('edited-1.png').convert('L')).astype(int)
d = np.abs(A - B) > 18
ys, xs = np.where(d)
```

This caught a real bug: **`ImageDraw.rectangle` includes both endpoints**, so `[185, 466, 780, 500]` cleared row 500 and chewed the top of the line *below*. The audit reported 28 stray dark pixels at exactly `y=500`, and the original band for the next line started at `y=499.3` at 200 dpi. Fixed by ending the box at 496. Without the audit that mean-spirited one-row nibble ships silently.

Result after the fix: changed pixels confined to `rows 472–496`, zero outside.

## 6. Assemble without re-encoding the pages you did not touch

Trap: `magick a.png b.png c.jpg out.pdf` **re-encodes the JPEG**. Page 3 came back with **271,641 pixels differing by more than 6/255** and max diff 236, purely from ImageMagick's JPEG round-trip. It also loses the original JPEG stream and changes the file size.

Correct way, using poppler's `pdfseparate` / `pdfunite` so the untouched page keeps its original stream:

```bash
magick -density 200 -units PixelsPerInch edited-1.png edited-2.png -compress zip pages12.pdf
pdfseparate -f 3 -l 3 input.pdf page3.pdf
pdfunite pages12.pdf page3.pdf out.pdf
```

Verify the untouched page really is untouched:

```bash
pdftoppm -png -r 200 -f 3 -l 3 input.pdf orig3
pdftoppm -png -r 200 -f 3 -l 3 out.pdf new3
```

```
page3 max diff: 0   pixels >6: 0
```

`-compress zip` on the PNG pages keeps the patched pages lossless (Flate). Final file 2.6 MB against a 1.2 MB original, which is the cost of lossless page images.

Also useful: `pdfinfo` the output and check `Pages` and `Page size` are what you expect (A4, 595×841). A one-page drop is easy to get wrong when splicing.

## Gotchas

- **Never overwrite the source file.** Write a new one and say so; the original is the only authentic copy.
- **A patched scan is no longer a faithful copy.** It should not be presented to a third party (bank, auditor, insurer) as the issuing body's original. Keep the caveat in the hand-over message.
- **Cap-height matching beats "looks like the same font".** Two clones of the same design differ enough in width to be visible on the line below.
- **Line spacing is tight.** At 200 dpi a 8.5 pt block had only ~6 px between one line's descenders and the next line's cap tops, which is why the off-by-one rectangle mattered.
- **Pillow's text anchor `'s'` is the baseline**, not the descender. Verify with a probe render (`80 - ys.min()` = cap height) rather than trusting memory; my first probe used the wrong origin and reported a cap height of 32 px for a 30 px font, which is impossible.
- **`pdfseparate`/`pdfunite` come with poppler-utils**, same package as `pdftoppm`/`pdfimages`, so they are already there on any box that can read the scan.

## What was not verified

- Web search for URW/Nimbus-Sans-to-Helvetica metric documentation was unavailable during the session (search tool returned an error), so the font identification is **purely empirical** from ink width and cap height, not from a metrics reference. The match is strong (2% on one string, 0.6% on the other) but it is an inference.
- The patched pages are lossless Flate PNGs, so they are heavier than the source JPEGs; no attempt was made to tune output size.
- Only the two edited pages were diffed. Page 3 was verified pixel-identical; nothing else in the bundle was re-checked because nothing else was rebuilt.

## References

No external sources were used. The method is derived from direct measurement of the source file (`pdfinfo`, `pdfimages`, `pdftoppm`) and local font probing.

Related: [[kt02h20-generic-31b2-1052-crossflash-ja11-v21-2026-11-27]] (another "work on a file you cannot natively parse" job).
