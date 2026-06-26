#!/usr/bin/env python3
"""Deterministic visual regression between an SVG-export render and the rebuild.

Why this exists: eyeballing stitched strips (and asking an LLM "are these the
same?") repeatedly MISSES the diffs that actually matter here -- gradient
over-saturation, a missing rule/accent, wrong panel tint. Those are *measurable*,
so measure them. No row registration is used: the rebuild drifts vertically
(flow vs absolute + font), so instead of aligning rows we compare on
PROPORTIONALLY-RESAMPLED copies, which is robust to that drift.

  TINT  - resample BOTH full pages to (w_small x n_strips) with BOX and take the
          per-strip RGB distance. Text anti-aliasing/drift smears into noise that
          area-averaging absorbs, leaving gradient/tint/fill/large-structure
          differences (the class eyeballing misses).
  RULES - horizontal rules: a thin row darker than its vertical neighbourhood
          across ~full content width. vertical accents: a column darker than its
          horizontal neighbourhood with a long contiguous dark RUN (>= min_run),
          so short glyph stems are excluded but block accents are caught -- this
          works regardless of page height (a per-page-span test would miss them).
  output  diff_report.json (machine-readable) + annotated crop pairs per flagged
          band (compare/<>/diff/).
  --ai    OPTIONAL: send only the flagged crops to Gemini (vendored
          gemini_vision.py) for semantic labelling. Offline TINT+RULES is the
          default and the judge; the AI layer only interprets, never decides.

Usage:
  python visual_diff.py ORIGINAL.png CANDIDATE.png --out OUTDIR [--band 220] [--ai]

Exit code 0 always (a report, not a gate); read OUTDIR/diff_report.json.
Deps: numpy, Pillow. (No scikit-image.)
"""
import sys, os, json, argparse
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gemini_vision as gv          # vendored, self-contained; import is offline-safe


# ----------------------------------------------------------------------------- helpers
def load_rgb(path):
    return np.asarray(Image.open(path).convert("RGB")).astype(np.float32)


def to_gray(rgb):
    return rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)


def common_width(o, c):
    w = min(o.shape[1], c.shape[1])
    return o[:, :w], c[:, :w]


def strip_tint(o_rgb, c_rgb, n_strips, w_small=64):
    def grid(a):
        return np.asarray(
            Image.fromarray(a.astype(np.uint8)).resize((w_small, n_strips), Image.BOX)
        ).astype(np.float32)
    go, gc = grid(o_rgb), grid(c_rgb)
    return np.sqrt(((go - gc) ** 2).sum(axis=2)).mean(axis=1)


def _local_bg(profile, k):
    pad = np.pad(profile, k, mode="edge")
    return np.array([np.median(pad[i:i + 2 * k + 1]) for i in range(len(profile))])


def detect_h_rules(gray, x0, x1):
    """Horizontal rules: a thin row darker than its vertical neighbourhood across
    ~full content width (text never fills the width uniformly)."""
    seg = gray[:, x0:x1]
    row_mean = seg.mean(axis=1)
    local_bg = _local_bg(row_mean, 25)
    rules = []
    for i in range(len(row_mean)):
        if local_bg[i] - row_mean[i] < 3:
            continue
        if float(np.mean(seg[i] < (local_bg[i] - 2))) >= 0.80:
            rules.append(i)
    out, prev = [], -10
    for r in rules:
        if r - prev > 4:
            out.append(r)
        prev = r
    return out


def detect_v_accents(gray, x0, x1, min_run=50):
    """Vertical accents/rules: a column darker than its horizontal neighbourhood
    with a CONTIGUOUS dark run >= min_run px. Run-length (not page-span) is what
    lets short block accents (step bars, card borders) be detected while glyph
    stems -- always shorter than min_run -- are excluded. Returns x indices."""
    seg = gray[:, x0:x1]
    col_mean = seg.mean(axis=0)
    local_bg = _local_bg(col_mean, 15)
    cols = []
    for i in range(seg.shape[1]):
        if local_bg[i] - col_mean[i] < 1:
            continue
        dark = seg[:, i] < (local_bg[i] - 2)
        best = run = 0
        for v in dark:
            run = run + 1 if v else 0
            if run > best:
                best = run
        if best >= min_run:
            cols.append(i + x0)
    out, prev = [], -10
    for c in cols:
        if c - prev > 4:
            out.append(c)
        prev = c
    return out


def match_missing(a, b, tol):
    """How many of a have NO partner in b within tol."""
    return sum(1 for x in a if not any(abs(x - y) <= tol for y in b))


def side_by_side(O, C):
    h = max(O.shape[0], C.shape[0])
    def pad(a):
        out = np.full((h, a.shape[1], 3), 255, np.uint8)
        out[:a.shape[0]] = a.astype(np.uint8)
        return out
    gut = np.full((h, 10, 3), (255, 0, 255), np.uint8)
    return Image.fromarray(np.concatenate([pad(O), gut, pad(C)], axis=1))


# ----------------------------------------------------------------------------- main diff
def run(original, candidate, outdir, band_h, do_ai):
    os.makedirs(outdir, exist_ok=True)
    diffdir = os.path.join(outdir, "diff")
    os.makedirs(diffdir, exist_ok=True)

    o_rgb, c_rgb = common_width(load_rgb(original), load_rgb(candidate))
    W = o_rgb.shape[1]
    o_g, c_g = to_gray(o_rgb), to_gray(c_rgb)
    H, Hc = o_g.shape[0], c_g.shape[0]

    colmin = o_g.min(axis=0)
    fg = np.where(colmin < 245)[0]
    x0 = int(fg[0]) if len(fg) else 0
    x1 = int(fg[-1]) + 1 if len(fg) else W

    report = {"original": original, "candidate": candidate,
              "size": {"orig": [W, H], "cand": [W, Hc]},
              "height_delta": Hc - H, "content_x": [x0, x1], "bands": []}

    n_strips = max(8, H // band_h)
    tint = strip_tint(o_rgb, c_rgb, n_strips)

    # horizontal rules (map candidate rows to src scale), vertical accents (run-length)
    ho = detect_h_rules(o_g, x0, x1)
    hc = [int(r * H / Hc) for r in detect_h_rules(c_g, x0, x1)]
    vo = detect_v_accents(o_g, x0, x1)
    vc = detect_v_accents(c_g, x0, x1)
    h_tol = max(40, abs(Hc - H) + 20)
    rules_h_missing = [r for r in ho if not any(abs(r - q) <= h_tol for q in hc)]
    v_missing = match_missing(vo, vc, 10)
    report["rules"] = {"src_h": len(ho), "cand_h": len(hc), "h_missing_y": rules_h_missing,
                       "src_v": len(vo), "cand_v": len(vc), "v_missing": v_missing,
                       "src_v_x": vo, "cand_v_x": vc}

    for si in range(n_strips):
        y, yb = int(si * H / n_strips), int((si + 1) * H / n_strips)
        t = float(tint[si])
        sev, reasons = "ok", []
        if t > 24:
            sev = "high"; reasons.append(f"tintΔ {t:.0f}")
        elif t > 15:
            sev = "med"; reasons.append(f"tintΔ {t:.0f}")
        miss_here = [r for r in rules_h_missing if y <= r < yb]
        if miss_here:
            sev = "high"; reasons.append(f"missing h-rule @{miss_here}")
        entry = {"band": si, "src_y": [y, yb], "tint_delta": round(t, 1),
                 "severity": sev, "reasons": reasons}
        if sev != "ok":
            cy0, cy1 = int(y * Hc / H), int(yb * Hc / H)
            entry["crop"] = os.path.join(diffdir, f"band_{si:02d}.png")
            side_by_side(o_rgb[y:yb], c_rgb[cy0:cy1]).save(entry["crop"])
        report["bands"].append(entry)
    if v_missing:
        report["bands"].append({"band": "global", "src_y": [0, H], "severity": "high",
                                "reasons": [f"{v_missing} vertical accent(s) missing "
                                            f"(src x={vo} vs cand x={vc})"]})

    if do_ai:
        flagged = [b for b in report["bands"] if b.get("crop")]
        if not flagged:
            report["ai_note"] = "no flagged crops"
        elif not gv.available():
            report["ai_note"] = "gemini unavailable (pip install google-genai + GEMINI_API_KEY)"
        else:
            for b in flagged:
                b["ai"] = gemini_analyze(b["crop"])

    rp = os.path.join(outdir, "diff_report.json")
    json.dump(report, open(rp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print_summary(report, rp)
    return report


def print_summary(report, rp):
    r = report["rules"]
    print(f"\n[visual_diff] {len([b for b in report['bands'] if isinstance(b['band'], int)])} strips "
          f"| height Δ {report['height_delta']:+d}px "
          f"| rules src/cand h={r['src_h']}/{r['cand_h']} v={r['src_v']}/{r['cand_v']} "
          f"(v_missing={r['v_missing']})  ->  {rp}")
    bad = [b for b in report["bands"] if b["severity"] != "ok"]
    if not bad:
        print("  OK no flagged strips (deterministic diff clean)")
    for b in bad:
        td = f"tintΔ={b['tint_delta']}" if "tint_delta" in b else ""
        print(f"  [{b['severity'].upper():>4}] strip {str(b['band']):>6} y{b['src_y']} {td} :: {', '.join(b['reasons'])}")
    print()


# ----------------------------------------------------------------------------- AI layer
def gemini_analyze(crop_path):
    import re
    prompt = (
        "This image is ONE UI region: LEFT half = design source, RIGHT half = my "
        "HTML rebuild (magenta strip separates them). List ONLY the visual "
        "differences as a JSON array, no prose:\n"
        '[{"element":"","difference":"","severity":"high|med|low",'
        '"likely_css_or_svg_cause":""}]'
    )
    try:
        out = gv.analyze(crop_path, prompt)
        m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", out, re.S) or \
            re.search(r"(\[\s*\{.*\}\s*\])", out, re.S)
        if m:
            return json.loads(m.group(1))
        return {"raw": out[-800:], "note": "no JSON array parsed"}
    except Exception as ex:
        return {"error": str(ex)}


# ----------------------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("original"); ap.add_argument("candidate")
    ap.add_argument("--out", required=True)
    ap.add_argument("--band", type=int, default=220)
    ap.add_argument("--ai", action="store_true",
                    help="interpret flagged crops with Gemini (vendored gemini_vision.py)")
    a = ap.parse_args()
    run(a.original, a.candidate, a.out, a.band, a.ai)


if __name__ == "__main__":
    main()
