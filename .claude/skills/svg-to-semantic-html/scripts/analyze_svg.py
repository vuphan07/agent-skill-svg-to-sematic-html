#!/usr/bin/env python3
"""Measure an SVG export so you can rebuild it as semantic HTML/CSS.

Usage:
    python analyze_svg.py INPUT.(html|svg) [--json out.json]

Prints three things and (optionally) dumps them to JSON:
  1. DESIGN TOKENS  - fill colors, font-sizes, line-gaps, corner radii, the
     drop-shadow recipe (read from <defs> filters), and the canvas size.
  2. SPINE          - every visible block top-to-bottom with its left x, visual
     top/bottom (baseline-adjusted for text) and the GAP to the previous block.
  3. LINE BREAKS    - the hard line breaks (tspans) inside every multi-line text.

Geometry notes:
  - Transforms are accumulated as a full 2D affine matrix, so translate + scale +
    matrix() are handled correctly. rotate()/skew is applied to point positions
    too, but element WIDTH/HEIGHT are scaled by the matrix column magnitudes
    (correct for translate+scale); a one-time warning is printed if a real
    rotation/skew is detected, since axis-aligned sizes then become approximate.
  - SVG text y is the BASELINE. Visual top approx = baseline-0.82*fs, bottom =
    baseline+0.22*fs (Segoe-UI-like). tspans positioned via absolute x/y OR
    relative dx/dy are both resolved.
  - SVG text usually carries NO font-weight => it is REGULAR (400). Do not bold it.
"""
import sys, re, json, math
import xml.etree.ElementTree as ET
from collections import Counter

SVG = "http://www.w3.org/2000/svg"
NS = {"svg": SVG}
ASC, DESC = 0.82, 0.22
IDENT = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
_warned_rot = [False]


def q(t):
    return t.split("}")[1] if "}" in t else t


def load(path):
    txt = open(path, encoding="utf-8").read().replace("\r\n", "\n")
    if "<svg" in txt:
        txt = txt[txt.find("<svg"): txt.rfind("</svg>") + 6]
    return ET.fromstring(txt)


# ---- affine transform helpers ------------------------------------------------
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
        if not n and fn != "":
            continue
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
        print("[warn] rotation/skew detected -> element width/height are approximate "
              "(positions are still exact).", file=sys.stderr)
    return math.hypot(a, b), math.hypot(c, d), rot


# ---- shadow (scanned from <defs>, independent of the spine walk) -------------
def extract_shadow(root):
    for el in root.iter():
        if q(el.tag) != "filter":
            continue
        fo = el.find("svg:feOffset", NS)
        fb = el.find("svg:feGaussianBlur", NS)
        ff = el.find("svg:feFlood", NS)
        if fo is None and fb is None:
            continue
        return {"dy": fo.get("dy") if fo is not None else None,
                "dx": fo.get("dx") if fo is not None else None,
                "blur": fb.get("stdDeviation") if fb is not None else None,
                "opacity": ff.get("flood-opacity") if ff is not None else None,
                "color": ff.get("flood-color") if ff is not None else None}
    return None


# ---- tspan positions (absolute x/y or relative dx/dy) ------------------------
def tspan_points(el):
    sps = el.findall("svg:tspan", NS)
    pts, px, py = [], 0.0, 0.0
    for s in sps:
        xa, ya = s.get("x"), s.get("y")
        dxa, dya = s.get("dx"), s.get("dy")
        px = float(xa) if xa not in (None, "") else px + (float(dxa) if dxa else 0.0)
        py = float(ya) if ya not in (None, "") else py + (float(dya) if dya else 0.0)
        pts.append((px, py, (s.text or "")))
    return pts


def analyze(root):
    blocks, breaks = [], []
    fills, sizes, gaps, radii = Counter(), Counter(), Counter(), Counter()

    def walk(el, M):
        t = q(el.tag)
        if t == "defs":
            return
        M = mat_mul(M, parse_transform(el.get("transform")))
        if t == "text":
            pts = tspan_points(el)
            if not pts:
                return
            fs = float(el.get("font-size", 16))
            _, sy, _ = scales(M)
            fse = fs * sy
            if el.get("fill"):
                fills[el.get("fill")] += 1
            sizes[round(fse, 1)] += 1
            P = [apply_pt(M, x, y) for x, y, _ in pts]
            xmin = min(p[0] for p in P)
            fbsl = P[0][1]; lbsl = P[-1][1]
            lg = round(P[1][1] - P[0][1], 1) if len(P) > 1 else None
            if lg:
                gaps[lg] += 1
            lines = [t.strip() for _, _, t in pts]
            if len(lines) > 1:
                breaks.append({"text": " ".join(l for l in lines if l)[:60],
                               "lines": lines, "fs": round(fse, 1)})
            blocks.append({"type": "text", "x": round(xmin, 1),
                           "top": round(fbsl - ASC * fse, 1), "bottom": round(lbsl + DESC * fse, 1),
                           "fs": round(fse, 1), "lg": lg, "label": (lines[0] if lines else "")[:34]})
            return
        if t in ("rect", "image"):
            if (el.get("opacity") or "1").strip() in ("0", "0.0", "0.00"):
                return
            sx, sy, _ = scales(M)
            X, Y = apply_pt(M, float(el.get("x", 0) or 0), float(el.get("y", 0) or 0))
            w = float(el.get("width", 0) or 0) * sx
            h = float(el.get("height", 0) or 0) * sy
            if (el.get("fill") or "").startswith("#"):
                fills[el.get("fill")] += 1
            if el.get("rx"):
                radii[el.get("rx")] += 1
            blocks.append({"type": t, "x": round(X, 1), "top": round(Y, 1), "bottom": round(Y + h, 1),
                           "w": round(w, 1), "h": round(h, 1), "rx": el.get("rx"),
                           "fill": el.get("fill"), "label": (el.get("id") or "")[:22]})
            return
        if t == "line":
            x1, y1 = apply_pt(M, float(el.get("x1", 0) or 0), float(el.get("y1", 0) or 0))
            x2, y2 = apply_pt(M, float(el.get("x2", 0) or 0), float(el.get("y2", 0) or 0))
            kind = "H" if abs(y1 - y2) < .5 else ("V" if abs(x1 - x2) < .5 else "D")
            blocks.append({"type": "line", "kind": kind, "x": round(min(x1, x2), 1),
                           "top": round(min(y1, y2), 1), "bottom": round(max(y1, y2), 1),
                           "stroke": el.get("stroke"), "opacity": el.get("opacity"), "label": "line"})
            return
        # container (svg, g, a, switch, symbol, ...) -> recurse
        for ch in el:
            walk(ch, M)

    walk(root, IDENT)
    blocks.sort(key=lambda b: b["top"])
    cw = float(root.get("width") or 393)
    bg = background_layers(blocks, cw)
    tokens = {"canvas": {"w": root.get("width"), "h": root.get("height")},
              "colors": [c for c, _ in fills.most_common()],
              "font_sizes": sorted(sizes), "line_gaps": sorted(gaps),
              "radii": sorted(radii, key=lambda r: float(r)), "shadow": extract_shadow(root)}
    return tokens, blocks, breaks, bg


def background_layers(blocks, cw):
    """Detect FULL-BLEED layers: rect/image at x~=0 spanning ~full canvas width.
    These are page/section backgrounds (gradients, tint panels) that sit BEHIND
    the foreground content overlapping their y-span — NOT linear-flow blocks.
    Missing this is why a hero gradient gets wrongly clipped to a short element:
    it must be attached to the page/section that the following content overlaps.
    Returns each layer with its y-span + the foreground blocks it bleeds behind."""
    def full(b):
        return b["type"] in ("rect", "image") and b.get("w", 0) >= cw * 0.95 and b["x"] <= cw * 0.03
    layers = []
    for b in blocks:
        if not full(b):
            continue
        top, bot = b["top"], b["bottom"]
        behind = [fb for fb in blocks if fb is not b and not full(fb) and top - 1 <= fb["top"] < bot]
        layers.append({"label": b.get("label") or b["type"], "type": b["type"],
                       "top": top, "bottom": bot, "h": round(bot - top, 1),
                       "fill": b.get("fill"), "rx": b.get("rx"),
                       "behind_count": len(behind),
                       "behind_span": [behind[0]["top"], behind[-1]["bottom"]] if behind else None})
    return layers


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    inp = sys.argv[1]
    out_json = sys.argv[sys.argv.index("--json") + 1] if "--json" in sys.argv else None
    tokens, blocks, breaks, bg = analyze(load(inp))

    print("=" * 64, "\nDESIGN TOKENS\n" + "=" * 64)
    print(json.dumps(tokens, ensure_ascii=False, indent=2))

    print("\n" + "=" * 64, "\nFULL-BLEED LAYERS (page/section backgrounds — attach to the\n"
          "PAGE/SECTION they bleed behind, NOT to a short hero element)\n" + "=" * 64)
    if not bg:
        print("  (none)")
    for L in bg:
        b = f"behind {L['behind_count']} block(s) y{L['behind_span']}" if L["behind_span"] else "(no fg behind)"
        print(f"  {L['top']:>5.0f}-{L['bottom']:<5.0f} h={L['h']:<6} {L['type']:<5} "
              f"fill={L['fill']} rx={L['rx']}  {b}  {L['label']}")

    print("\n" + "=" * 64, "\nSPINE (top -> bottom)   GAP = margin to put before this block\n" + "=" * 64)
    print(f"{'top':>7}{'bot':>7}{'gap':>6}{'x':>6}  detail")
    prev = None
    for b in blocks:
        gap = "" if prev is None else f"{b['top'] - prev:6.0f}"
        extra = (f"fs={b.get('fs')} lg={b.get('lg')}" if b["type"] == "text" else
                 (f"{b['type']} {b.get('w','')}x{b.get('h','')} rx={b.get('rx')}"
                  if b["type"] in ("rect", "image") else f"{b['type']} {b.get('kind','')}"))
        print(f"{b['top']:7.0f}{b['bottom']:7.0f}{gap:>6}{b['x']:6.0f}  {extra}  {b['label']}")
        prev = b["bottom"]

    print("\n" + "=" * 64, "\nLINE BREAKS (rebuild with <br>)\n" + "=" * 64)
    for br in breaks:
        print(f"fs={br['fs']:>5}  " + "  |  ".join(l for l in br["lines"]))

    if out_json:
        json.dump({"tokens": tokens, "spine": blocks, "breaks": breaks, "bg_layers": bg},
                  open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"\n[ok] dumped JSON -> {out_json}", file=sys.stderr)


if __name__ == "__main__":
    main()
