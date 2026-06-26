#!/usr/bin/env python3
"""Auto-transpile an SVG export into a PIXEL-PERFECT (absolutely-positioned) HTML draft.

Usage:
    python transpile_flat.py INPUT.(html|svg) OUTDIR

Produces OUTDIR/index.html + OUTDIR/assets/. Every SVG primitive becomes an
absolutely-positioned element:
    rect  -> <div>            (bg color / REAL gradient / pattern-image, border-radius, box-shadow)
    text  -> <span> per tspan (baseline-positioned; font-size/letter-spacing/fill preserved)
    line  -> <div>            (H/V) or tiny inline <svg> (diagonal)
    image -> <img>
    path/circle/diagonal icon groups -> small inline <svg> (kept exact)

Transforms are accumulated as a full affine matrix (translate + scale + matrix()
handled exactly; rotation/skew warns and falls back to position-only). Linear
gradients are read from <defs> (real stops + direction). This is NOT semantic and
NOT responsive; use as a faithful reference. For a real page see
references/semantic-rebuild.md.
"""
import sys, os, re, base64, hashlib, math
import xml.etree.ElementTree as ET

SVG = "http://www.w3.org/2000/svg"
XLINK = "http://www.w3.org/1999/xlink"
NS = {"svg": SVG, "xlink": XLINK}
IDENT = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
_warned_rot = [False]


def q(t):
    return t.split("}")[1] if "}" in t else t


def href(el):
    return el.get(f"{{{XLINK}}}href") or el.get("href")


def load(path):
    txt = open(path, encoding="utf-8").read().replace("\r\n", "\n")
    if "<svg" in txt:
        txt = txt[txt.find("<svg"): txt.rfind("</svg>") + 6]
    return ET.fromstring(txt)


# ---- affine transforms -------------------------------------------------------
def mat_mul(A, B):
    a1, b1, c1, d1, e1, f1 = A
    a2, b2, c2, d2, e2, f2 = B
    return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2,
            a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1)


def parse_transform(s):
    M = IDENT
    if not s:
        return M
    for fn, a in re.findall(r"(\w+)\s*\(([^)]*)\)", s):
        n = [float(x) for x in re.split(r"[ ,]+", a.strip()) if x != ""]
        if fn == "translate":
            M = mat_mul(M, (1, 0, 0, 1, n[0], n[1] if len(n) > 1 else 0))
        elif fn == "scale":
            sx = n[0]; sy = n[1] if len(n) > 1 else sx
            M = mat_mul(M, (sx, 0, 0, sy, 0, 0))
        elif fn == "rotate":
            ang = math.radians(n[0]); cs, sn = math.cos(ang), math.sin(ang)
            if len(n) >= 3:
                M = mat_mul(M, (1, 0, 0, 1, n[1], n[2]))
                M = mat_mul(M, (cs, sn, -sn, cs, 0, 0))
                M = mat_mul(M, (1, 0, 0, 1, -n[1], -n[2]))
            else:
                M = mat_mul(M, (cs, sn, -sn, cs, 0, 0))
        elif fn == "matrix" and len(n) == 6:
            M = mat_mul(M, tuple(n))
        elif fn == "skewX" and n:
            M = mat_mul(M, (1, 0, math.tan(math.radians(n[0])), 1, 0, 0))
        elif fn == "skewY" and n:
            M = mat_mul(M, (1, math.tan(math.radians(n[0])), 0, 1, 0, 0))
    return M


def apply_pt(M, x, y):
    a, b, c, d, e, f = M
    return (a * x + c * y + e, b * x + d * y + f)


def scales(M):
    a, b, c, d, _, _ = M
    rot = abs(b) > 1e-6 or abs(c) > 1e-6
    if rot and not _warned_rot[0]:
        _warned_rot[0] = True
        print("[warn] rotation/skew detected -> emitting position+size only "
              "(no rotation in CSS for this element).", file=sys.stderr)
    return math.hypot(a, b), math.hypot(c, d), rot


# ---- colour / gradient -------------------------------------------------------
def hex_rgba(col, op):
    if op is None:
        return col
    c = (col or "").strip()
    if c.startswith("#"):
        h = c[1:]
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        if len(h) >= 6:
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return f"rgba({r},{g},{b},{op})"
    return c


def gradient_css(grad):
    stops, x1, y1, x2, y2 = grad
    # direction from the gradient vector (objectBoundingBox or userSpace both ok for axis)
    fx1 = float(x1) if x1 not in (None, "") else 0.0
    fy1 = float(y1) if y1 not in (None, "") else 0.0
    fx2 = float(x2) if x2 not in (None, "") else 0.0
    fy2 = float(y2) if y2 not in (None, "") else 1.0
    dx, dy = fx2 - fx1, fy2 - fy1
    if abs(dy) >= abs(dx):
        direction = "to bottom" if dy >= 0 else "to top"
    else:
        direction = "to right" if dx >= 0 else "to left"
    parts = []
    for off, col, op in stops:
        o = off if off not in (None, "") else "0"
        if o.endswith("%"):
            pct = o
        else:
            try:
                pct = f"{float(o) * 100:.0f}%"
            except ValueError:
                pct = "0%"
        parts.append(f"{hex_rgba(col or '#000', op)} {pct}")
    if not parts:
        parts = ["rgba(255,255,255,0) 0%", "#fbfbfb 100%"]
    return f"linear-gradient({direction},{','.join(parts)})"


def main():
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    inp, outdir = sys.argv[1], sys.argv[2]
    os.makedirs(os.path.join(outdir, "assets"), exist_ok=True)
    root = load(inp)
    W = float(root.get("width") or 0); H = float(root.get("height") or 0)

    hash_file, counter = {}, [0]

    def save(uri):
        m = re.match(r"data:image/([\w.+-]+);base64,(.*)", uri or "", re.S)
        if not m:
            return None
        ext = {"svg+xml": "svg", "jpeg": "jpg"}.get(m.group(1), m.group(1))
        raw = base64.b64decode(m.group(2)); h = hashlib.md5(raw).hexdigest()
        if h in hash_file:
            return hash_file[h]
        counter[0] += 1; fn = f"assets/img{counter[0]}.{ext}"
        open(os.path.join(outdir, fn), "wb").write(raw); hash_file[h] = fn
        return fn

    defs = root.find("svg:defs", NS)
    pat, standalone, grads = {}, {}, {}
    SHADOW = None
    # gradients + shadow from defs (anywhere)
    for c in root.iter():
        tag = q(c.tag)
        if tag == "linearGradient":
            grads[c.get("id")] = ([(s.get("offset"), s.get("stop-color"), s.get("stop-opacity"))
                                   for s in c.findall("svg:stop", NS)],
                                  c.get("x1"), c.get("y1"), c.get("x2"), c.get("y2"))
        elif tag == "filter" and SHADOW is None:
            fo = c.find("svg:feOffset", NS); fb = c.find("svg:feGaussianBlur", NS); ff = c.find("svg:feFlood", NS)
            if fo is not None or fb is not None:
                dy = float(fo.get("dy") or 0) if fo is not None else 0
                blur = float(fb.get("stdDeviation") or 0) if fb is not None else 0
                op = ff.get("flood-opacity") if ff is not None else "0.16"
                SHADOW = f"0px {dy:.0f}px {blur*2:.0f}px rgba(0,0,0,{op})"
    if defs is not None:
        for c in defs:
            if q(c.tag) == "image" and href(c) and (href(c) or "").startswith("data:"):
                standalone[c.get("id")] = save(href(c))
        for c in defs:
            if q(c.tag) == "pattern":
                img = c.find("svg:image", NS); use = c.find("svg:use", NS)
                if img is not None and href(img):
                    pat[c.get("id")] = (save(href(img)), "stretch")
                elif use is not None:
                    pat[c.get("id")] = (standalone.get((href(use) or "").lstrip("#")), "cover")
    if SHADOW is None:
        SHADOW = "0px 3px 6px rgba(0,0,0,0.161)"

    out = []

    def esc(t):
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def fillcss(fill):
        if not fill or fill == "none":
            return None
        m = re.match(r"url\(#([^)]+)\)", fill)
        if m:
            rid = m.group(1)
            if rid in grads:
                return ("grad", rid)
            if rid in pat:
                return ("img", pat[rid])
            if "gradient" in rid:
                return ("grad", None)
            return None
        return ("color", fill)

    def inner_xml(el):
        s = ET.tostring(el, encoding="unicode")
        return (s.replace("ns0:", "").replace("xmlns:ns0", "xmlns")
                 .replace("ns1:", "xlink:").replace("xmlns:ns1", "xmlns:xlink"))

    def has_vector(el):
        for d in el.iter():
            t = q(d.tag)
            if t in ("path", "circle"):
                return True
            if t == "line":
                x1 = float(d.get("x1", 0) or 0); y1 = float(d.get("y1", 0) or 0)
                x2 = float(d.get("x2", 0) or 0); y2 = float(d.get("y2", 0) or 0)
                if abs(y1 - y2) > .5 and abs(x1 - x2) > .5:
                    return True
        return False

    def is_icon(el):
        """Pure-vector group/element (icon): has path/circle/diagonal line and NO
        text/image descendants. Prevents collapsing the whole content group."""
        if not has_vector(el):
            return False
        for d in el.iter():
            if q(d.tag) in ("text", "image"):
                return False
        return True

    def emit_icon(el, Mparent):
        # position the inline <svg> at the PARENT origin and serialize el WITH its
        # own transform, so el's transform is applied exactly once.
        X, Y = apply_pt(Mparent, 0, 0)
        out.append(f'<svg class="ic" style="left:{X:.2f}px;top:{Y:.2f}px;width:1px;height:1px;'
                   f'overflow:visible" xmlns="{SVG}" xmlns:xlink="{XLINK}">{inner_xml(el)}</svg>')

    def walk(el, M, shadow):
        t = q(el.tag)
        if t == "defs":
            return
        Mself = mat_mul(M, parse_transform(el.get("transform")))
        if t == "g":
            sh = SHADOW if el.get("filter") else shadow
            if is_icon(el):
                emit_icon(el, M); return          # M = parent; el keeps its transform
            for ch in el:
                walk(ch, Mself, sh)
            return
        if t == "rect":
            if (el.get("opacity") or "1").strip() in ("0", "0.0", "0.00"):
                return
            sx, sy, _ = scales(Mself)
            X, Y = apply_pt(Mself, float(el.get("x", 0) or 0), float(el.get("y", 0) or 0))
            w = float(el.get("width", 0) or 0) * sx
            h = float(el.get("height", 0) or 0) * sy
            sty = [f"left:{X:.2f}px", f"top:{Y:.2f}px", f"width:{w:.2f}px", f"height:{h:.2f}px"]
            if el.get("rx"):
                sty.append(f"border-radius:{float(el.get('rx')) * sx:.2f}px")
            if el.get("opacity"):
                sty.append(f"opacity:{el.get('opacity')}")
            if shadow:
                sty.append(f"box-shadow:{shadow}")
            fc = fillcss(el.get("fill"))
            if fc:
                k, v = fc
                if k == "color":
                    sty.append(f"background:{v}")
                elif k == "grad":
                    sty.append("background:" + (gradient_css(grads[v]) if v in grads
                               else "linear-gradient(to bottom,rgba(255,255,255,0),#fbfbfb)"))
                elif k == "img" and v[0]:
                    sty.append(f"background-image:url({v[0]})")
                    sty.append("background-size:" + ("cover" if v[1] == "cover" else "100% 100%"))
                    sty.append("background-repeat:no-repeat")
            out.append(f'<div class="r" style="{";".join(sty)}"></div>')
            return
        if t == "image":
            fn = save(href(el))
            sx, sy, _ = scales(Mself)
            X, Y = apply_pt(Mself, float(el.get("x", 0) or 0), float(el.get("y", 0) or 0))
            w = float(el.get("width", 0) or 0) * sx
            h = float(el.get("height", 0) or 0) * sy
            sty = [f"left:{X:.2f}px", f"top:{Y:.2f}px", f"width:{w:.2f}px", f"height:{h:.2f}px", "object-fit:cover"]
            if el.get("opacity"):
                sty.append(f"opacity:{el.get('opacity')}")
            out.append(f'<img class="im" src="{fn}" style="{";".join(sty)}" alt="">')
            return
        if t == "text":
            fs = el.get("font-size", "16"); fill = el.get("fill", "#000")
            ls = el.get("letter-spacing"); fw = el.get("font-weight", "400")
            _, sy, _ = scales(Mself)
            fse = float(fs) * sy
            fam = "'Segoe UI',system-ui,-apple-system,Roboto,sans-serif"
            base = [f"font-size:{fse:.2f}px", f"font-family:{fam}", f"color:{fill}",
                    f"font-weight:{fw}", "line-height:1", "white-space:nowrap", "transform:translateY(-0.82em)"]
            if ls:
                base.append(f"letter-spacing:{ls}")
            px = py = 0.0
            for sp in el.findall("svg:tspan", NS):
                xa, ya, dxa, dya = sp.get("x"), sp.get("y"), sp.get("dx"), sp.get("dy")
                px = float(xa) if xa not in (None, "") else px + (float(dxa) if dxa else 0.0)
                py = float(ya) if ya not in (None, "") else py + (float(dya) if dya else 0.0)
                X, Y = apply_pt(Mself, px, py)
                out.append(f'<span class="t" style="left:{X:.2f}px;top:{Y:.2f}px;'
                           f'{";".join(base)}">{esc(sp.text or "")}</span>')
            return
        if t == "line":
            x1, y1 = apply_pt(Mself, float(el.get("x1", 0) or 0), float(el.get("y1", 0) or 0))
            x2, y2 = apply_pt(Mself, float(el.get("x2", 0) or 0), float(el.get("y2", 0) or 0))
            sw = float(el.get("stroke-width", 1) or 1); stroke = el.get("stroke", "#000")
            com = [f"background:{stroke}"]
            if el.get("opacity"):
                com.append(f"opacity:{el.get('opacity')}")
            if abs(y1 - y2) < .5:
                out.append(f'<div class="r" style="left:{min(x1,x2):.2f}px;top:{y1-sw/2:.2f}px;'
                           f'width:{abs(x2-x1):.2f}px;height:{sw:.2f}px;{";".join(com)}"></div>')
            elif abs(x1 - x2) < .5:
                out.append(f'<div class="r" style="left:{x1-sw/2:.2f}px;top:{min(y1,y2):.2f}px;'
                           f'width:{sw:.2f}px;height:{abs(y2-y1):.2f}px;{";".join(com)}"></div>')
            else:
                mnx, mny = min(x1, x2), min(y1, y2); w = abs(x2 - x1) or 1; h = abs(y2 - y1) or 1
                out.append(f'<svg class="ic" style="left:{mnx:.2f}px;top:{mny:.2f}px;width:{w:.2f}px;'
                           f'height:{h:.2f}px;overflow:visible" viewBox="0 0 {w} {h}">'
                           f'<line x1="{x1-mnx:.2f}" y1="{y1-mny:.2f}" x2="{x2-mnx:.2f}" y2="{y2-mny:.2f}" '
                           f'stroke="{stroke}" stroke-width="{sw}"/></svg>')
            return
        if t in ("path", "circle"):
            emit_icon(el, M); return          # M = parent
        # generic container (svg, a, switch, ...)
        for ch in el:
            walk(ch, Mself, shadow)

    walk(root, IDENT, None)

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Flat draft</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:#e9e9e9;display:flex;justify-content:center;}}
.stage{{position:relative;width:{W:.0f}px;height:{H:.0f}px;background:#fbfbfb;overflow:hidden;}}
.stage .r,.stage .im,.stage .t,.stage .ic{{position:absolute;}}
.stage .im,.stage .t{{display:block;}}
</style></head><body>
<div class="stage">
{chr(10).join(out)}
</div></body></html>"""
    open(os.path.join(outdir, "index.html"), "w", encoding="utf-8").write(html)
    print(f"[ok] {len(out)} elements, {counter[0]} images -> {outdir}/index.html", file=sys.stderr)


if __name__ == "__main__":
    main()
