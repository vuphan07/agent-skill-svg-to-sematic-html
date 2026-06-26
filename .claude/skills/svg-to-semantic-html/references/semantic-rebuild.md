# Semantic rebuild guide

`transpile_flat.py` gives a pixel-perfect but flat (all `position:absolute`)
draft. To produce a **real, structured** page instead, use the analysis output
and rebuild by hand following the rules below. The flat draft and the
`analyze_svg.py` SPINE are your sources of truth for numbers.

## 1. Design tokens (from `analyze_svg.py` DESIGN TOKENS)

Turn the reported values into CSS variables, e.g.:

```css
:root{
  --red:#9d1c1b; --ink:#272825; --bg:#fbfbfb; --card:#fff;
  --line:rgba(39,40,37,.18);
  --shadow:0 3px 6px rgba(0,0,0,.161);     /* from shadow{dy,blur,opacity}: 0 {dy}px {2*blur}px rgba(0,0,0,{opacity}) */
  --font:"Segoe UI",system-ui,-apple-system,Roboto,sans-serif;
}
```

- `colors` -> backgrounds and text colors.
- `font_sizes` / `line_gaps` -> font-size + line-height per text role.
- `radii` -> border-radius (cards vs buttons vs inputs usually differ).
- `shadow` -> a single `box-shadow`; in these exports every filter is the same drop shadow.

## 2. Element mapping (SVG primitive -> HTML)

| SVG | HTML | Notes |
|-----|------|-------|
| `rect` (solid fill) | `<div>` / `<button>` / form field | `rx`->`border-radius`; wrapped in a `filter` group -> `box-shadow` |
| `rect` (fill `url(#linear-gradient)`) | element with CSS `linear-gradient` | direction from the gradient stops |
| `rect` (fill `url(#pattern-N)`) | `<div>` background-image OR `<img>` | pattern `preserveAspectRatio="none"` -> `background-size:100% 100%`; `<use slice>` -> `cover` |
| `image` | `<img>` (or div background) | extract with `extract_assets.py` |
| `text` + `tspan`s | `<p>`/`<span>` with `<br>` between tspans | **see weight + line-break rules below** |
| `line` H/V | `<div>` (1px) or `border` | separators, underlines, left accents |
| `line` diagonal, `path`, `circle` | small inline `<svg>` | icons: chevrons, ticks, social, hamburger |

## 3. Text rules (most common source of mismatch)

- **Weight:** SVG text usually has **no `font-weight`** => it is REGULAR (400).
  Do **not** use `<h1>`/`<h2>` defaults (they bold). Use plain `<p>` and set
  `font-weight:400` globally. Re-introduce weight only where the SVG specifies it.
- **Hard line breaks:** each `<text>` lists its lines as `<tspan>`s. Reproduce
  those breaks with `<br>` so wrapping matches the SVG no matter the font width.
  (`analyze_svg.py` prints every multi-line block under LINE BREAKS.)
- **Line-height:** set it to the measured `line-gap` in px (tspan y delta),
  e.g. fs 15 with gap 24 -> `line-height:24px`.
- **Letter-spacing:** copy the SVG `letter-spacing` verbatim (it is in `em`).
- **Indents:** the `x` column in the SPINE is the absolute left; subtract the
  section's left padding to get the indent.

## 4. Spacing in flow

The SPINE `gap` column = `top(current) - bottom(previous)`. Put that value as the
`margin-top` (or container `padding`) before each block. Because text top/bottom
are baseline-approximated, gaps are accurate to a few px; that is the right call
for a flowing (non-absolute) layout.

For a card: `padding-top = firstChild.top - rect.top`,
`padding-left = content.x - rect.x`, `padding-bottom = rect.bottom - lastChild.bottom`.

## 5. Things easy to miss (check against the flat draft / screenshots)

- Faint **accent lines** (low opacity `line`s) on the left of list items / steps.
- **Separators** between cards/FAQ items (full-width `line`s, opacity ~0.4).
- Small **chevrons / arrows** next to links and buttons (diagonal `line` pairs).
- Icon **identity and order** — verify each icon image maps to the right item
  (open the extracted `assets/imgN.png` and match by content, not by guess).
- Background **tint panels** behind a whole section (a full-width `rect`).

## 5b. Attributes `analyze_svg.py` does NOT report — grep the raw SVG

The token dump misses several per-element attributes that materially change the
look. Before finalizing CSS, grep the source for each and apply per element:

```bash
grep -oE 'letter-spacing="[^"]*"'      INPUT.html | sort | uniq -c   # per-role tracking
grep -oE 'opacity="[0-9.]+"'           INPUT.html | sort | uniq -c   # tint/veil/fade strengths
grep -oE 'fill="#[0-9a-f]{3,6}"'       INPUT.html | sort | uniq -c   # extra colours (e.g. #3d3d3d icons)
grep -oE 'stroke="#[0-9a-f]{3,6}"'     INPUT.html | sort | uniq -c   # icon line colours (often #000)
grep -nE 'fill="url\(#pattern'         INPUT.html                    # which rects are gradient/pattern fills
```

Verified gotchas from real exports:

1. **Per-element `letter-spacing`.** Headings frequently use a *tighter* track
   (`-0.06em`) than body (`-0.015em`). A global value makes big text look both
   too wide and too heavy. Set it per text role from the grep above.

2. **Tinted panels = gradient/pattern at reduced `opacity`.** A pink card is
   typically `fill="url(#pattern-N)" opacity="0.45"` — the gradient image blended
   45% onto the page colour, not the full-strength image. Reproduce with a veil:
   ```css
   background-image: linear-gradient(rgba(251,251,251,.55),rgba(251,251,251,.55)),
                     url(assets/grad.png);
   background-size: cover, cover;
   ```
   (white/bg-coloured veil at `1 - opacity`). Reusing the raw extracted gradient
   at full strength is the #1 cause of "panels look too saturated".

3. **Full-bleed hero gradient fades to the page colour.** Look for a rect with
   `fill="url(#linear-gradient)"` whose def is `#fff opacity 0 → #bg`; it overlays
   the hero image and fades its lower part into the page. Reproduce with a
   `linear-gradient(rgba(bg,0) Ypx, var(--bg) Y2px)` overlay (Y from the rect's
   `transform`), not a hard background cut.

4. **Segmented / toggle controls.** The *selected* segment is a separate inset
   rect — often `fill="#fff" opacity="0.8"` — floating on a darker **track**
   (itself a pattern/gradient rect). Read: (a) which side the inset pill sits on
   (its `transform` x; x≈left-padding ⇒ left segment is active), and (b) its
   colour. Don't assume the dark half is "active". Build it as a track with
   `padding` so the pill floats and the track shows around it:
   ```css
   .toggle{display:flex;padding:4px;border-radius:25px;
           background:linear-gradient(100deg,#6f6258,#2b2825);position:relative}
   .toggle::before{content:"";position:absolute;inset:4px 50% 4px 4px;
           background:rgba(255,255,255,.88);border-radius:25px}   /* inset pill, left */
   .toggle button{flex:1;z-index:1;background:none;border:none;color:#fff}
   .toggle button.active{color:#272825}
   ```

5. **Icon colour ≠ body ink.** Hamburger/chevron/`+` strokes are usually pure
   `#000` or a distinct gray (`#3d3d3d`), not the text `#272825`. Read it off the
   icon's own `<line>/<path>`.

6. **Reset native control chrome.** Mapping an icon/CTA to `<button>` without
   `background:none;border:none;padding:0` leaves the browser's default button
   box — a hamburger then renders as a boxed glyph instead of three clean lines.

7. **Make every inline icon self-contained (portability).** An inline `<svg>`
   sized/coloured only through a CSS class renders fine in a desktop browser but
   **disappears or collapses to the wrong place** when the file is opened in a
   less-capable target: print / Save-as-PDF, "export as image", paste into a
   design tool (Figma/XD), email/WebView, a strict XML/XHTML parser, or the
   packaged single-file build. Those targets drop or ignore CSS applied to inline
   SVG (and CSS borders / `::before` marks). So every inline `<svg>` must carry:
   - `xmlns="http://www.w3.org/2000/svg"` (required by XML/standalone contexts),
   - explicit `width` + `height` **attributes** (an unsized SVG defaults to
     300×150 or 0 and floats — this is what produces "stray icon in the middle"
     and "thin line through the section" artifacts), and
   - explicit `fill` / `stroke` colours (not `currentColor`).

   And draw small marks — **radio dot, checkbox, hamburger, chevron, plus,
   social** — as inline SVG with those attributes, not as a CSS-bordered
   `<span>` or a pseudo-element. Keep the CSS class too (convenience), but the
   icon must still be correct with the class stripped. Quick audit:
   ```bash
   # every <svg> should have xmlns + width + height
   grep -c '<svg'        out/index.html
   grep -c 'xmlns='      out/index.html      # must equal the count above
   grep -oE '<svg[^>]*'  out/index.html | grep -vE 'width=.*height=' # -> offenders
   grep -nE 'currentColor' out/index.html    # -> replace with explicit colour
   ```

8. **Reuse the SVG's own icon geometry — never hand-draw.** Every icon is a
   `<g id="Icon-N">` with the real `<path>`/`<line>`s inside (often wrapped in an
   invisible `<rect id="Area">` that gives the icon's box, e.g. 20×20 or 25×25).
   Copy the path's `d`, `fill`/`stroke` verbatim and **compose the transforms**:
   the net translate = parent-`<g>` translate + inner path translate. Example:
   ```
   <!-- source: <g translate(43 403.871)> <g translate(1.29 2.499)> <path translate(-4.526 -5.445) d="…" fill="#9d1c1b"> -->
   <!-- net translate = (1.29-4.526, 2.499-5.445) = (-3.236,-2.946); box = Area 20×20 -->
   <svg width="20" height="20" viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg">
     <path d="M3.236,3.236V22.655…Z" transform="translate(-3.236 -2.946)" fill="#9d1c1b"/>
   </svg>
   ```
   Map icons to uses by the group's `translate` y (it matches the SPINE row).
   The CTA/submit **arrow** is a white `<circle>` + a red chevron path, not a
   shafted arrow — copy it. Locate them all:
   ```bash
   grep -oE '<g id="(Icon[^"]*)"[^>]*translate\([^)]*\)' INPUT.html
   ```

9. **Lines = real elements with exact width, never `border`.** Every separator
   /accent/underline is its own SVG primitive with a fixed length. Borders take
   the host element's box width, so they overflow the design's content rule and
   can't do short fixed lengths. Reproduce each as an `<hr class="rule">` / inset
   `<span>` sized to the SVG value (in these exports full-width rules are all
   `<line x2="353" translate(20 Y)>` → 353px at x=20; link underlines are short,
   e.g. 61/67px). A vertical accent is a `<span>`/flex-child sized to the line's
   height (don't stretch it past the block).
   - **Audit ALL line forms — `<line>`, thin `<rect>`, and `<path>`:**
     ```bash
     # straight-line paths (vertical/horizontal rules drawn as a path)
     grep -oE '<path[^>]*d="M[0-9.,]+[VH][0-9.,]*"[^>]*>' INPUT.html
     ```
     Vertical accents frequently appear as `<path d="M0,253V0">`, which a
     `<line>`-only search misses — that is exactly how a per-item accent silently
     disappears. After building, **pixel-scan the rendered source** for the
     expected dark columns/rows to confirm none were dropped:
     ```python
     import numpy as np; from PIL import Image
     a=np.asarray(Image.open("out/cmp/original.png").convert("RGB")).mean(2)
     print([round(v,0) for v in a[Y0:Y1, X0:X1].mean(0)])  # a dip = a rule
     ```

10. **Interactive controls need behaviour, not just appearance.**
    - **Segmented toggle/tabs:** read the selected-pill rect — it is usually
      *flush* (full track height, ~half width, same `rx` as the track), NOT
      inset, often `fill="#fff" opacity="0.8"` on a darker `pattern`/gradient
      track. Build track + an absolutely-positioned `.knob`, and add JS to move
      the knob and swap the active label colour on click:
      ```js
      document.querySelectorAll('[data-toggle]').forEach(t=>{
        const b=t.querySelectorAll('button');
        b.forEach((x,i)=>x.onclick=()=>{b.forEach(y=>y.classList.remove('active'));
          x.classList.add('active'); t.classList.toggle('right', i===1);});
      });
      ```
    - **Radios/checkboxes:** use real `<input type="radio">` (styled with
      `appearance:none` + a `:checked` indicator) so they actually select.

11. **Block gaps come from the SPINE, not the eye.** The margin before an image
    /mockup block = `thisTop − prevBottom` (e.g. CTA button bottom 326 → first
    hero badge top 384 ⇒ 58px). Set it explicitly; a guessed offset is the usual
    cause of "the image hugs / drifts from the button above it".

## 6. Verify

Render and diff section by section:

```bash
node scripts/render_compare.js ORIGINAL.html out/index.html out/cmp
python scripts/stitch.py out/cmp 1000
# open out/cmp/compare_*.png — original on the left, your build on the right
```

The stitched strips are **downscaled** — good for gross layout, but they hide
the diffs that read as "still not quite right" (heading width/weight, gradient
saturation, toggle inset side, hamburger/chevron/icon shape & colour). For a
real check, crop the suspicious regions at **native resolution** and view
original-beside-candidate:

```python
from PIL import Image
o=Image.open("out/cmp/original.png"); c=Image.open("out/cmp/candidate.png")
def sbs(y0,y1,name):
    oc,cc=o.crop((0,y0,o.width,y1)),c.crop((0,y0,c.width,y1))
    cv=Image.new("RGB",(oc.width+cc.width+16,y1-y0),(255,0,255))
    cv.paste(oc,(0,0)); cv.paste(cc,(oc.width+16,0)); cv.save(name)
sbs(0,360,"out/cmp/z_header.png")     # then z_toggle, z_panel, z_footer …
```

Work the loop **region by region**: read the SVG attrs → predict the CSS →
render → zoom-compare → fix → repeat. Confirm each fix against the SVG source
**and** the screenshot, never just one. (Cumulative vertical drift of ~1–2% is
the expected flow-vs-absolute + font delta; chase per-section appearance, not
absolute Y.)

## 7. Font caveat (important)

These exports target **Segoe UI**. On a machine without it, the fallback is
wider, so lines wrap differently and the page gets taller — even when your CSS
is correct. Options: (a) test on a machine that has Segoe UI; (b) embed a
metric-compatible font (e.g. Microsoft **Selawik**, SIL OFL — build from
`github.com/microsoft/Selawik` or ship a licensed Segoe UI woff2) and reference
it first in the font stack. Keep `'Segoe UI'` first so real systems still match.
