#!/usr/bin/env python3
"""Batch section-by-section check: for every source in svg-input/, compare its
matching generated file in html-output/ (same base name) and write side-by-side
comparison strips.

Usage:
    python batch_check.py [--input svg-input] [--output html-output]
                          [--compare compare] [--width 393] [--band 1000]

For each svg-input/<name>.(html|svg):
  - looks for html-output/<name>.html (or <name>/index.html)
  - renders both to PNG and stitches section strips into compare/<name>/
  - reports matched / missing / extra files and the page-height delta
    (a big delta usually means a missing font, not a layout bug -- see SKILL.md)

Requires Node + puppeteer (for render_compare.js) and Pillow (for stitch.py).
Set CHROME_PATH to reuse an existing Chrome/Chromium. NODE_PATH may be needed
if puppeteer is not installed in the default location.
"""
import sys, os, subprocess, argparse
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
RENDER = os.path.join(HERE, "render_compare.js")
STITCH = os.path.join(HERE, "stitch.py")
VISUAL_DIFF = os.path.join(HERE, "visual_diff.py")


def find_output(out_dir, base):
    for cand in (f"{base}.html", os.path.join(base, "index.html")):
        p = os.path.join(out_dir, cand)
        if os.path.isfile(p):
            return p
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="svg-input")
    ap.add_argument("--output", default="html-output")
    ap.add_argument("--compare", default="compare")
    ap.add_argument("--width", default="393")
    ap.add_argument("--band", default="1000")
    ap.add_argument("--ai", action="store_true",
                    help="interpret flagged diff crops with Gemini (vendored gemini_vision.py)")
    a = ap.parse_args()

    if not os.path.isdir(a.input):
        print(f"[error] input dir not found: {a.input}"); sys.exit(1)
    os.makedirs(a.compare, exist_ok=True)

    sources = sorted(f for f in os.listdir(a.input)
                     if f.lower().endswith((".html", ".svg")))
    matched, missing = [], []
    for f in sources:
        base = os.path.splitext(f)[0]
        src = os.path.join(a.input, f)
        out = find_output(a.output, base)
        if not out:
            missing.append(base); continue
        cmp_dir = os.path.join(a.compare, base)
        os.makedirs(cmp_dir, exist_ok=True)
        print(f"\n=== {base} ===")
        r = subprocess.run(["node", RENDER, src, out, cmp_dir, a.width, a.band],
                           env=os.environ.copy())
        if r.returncode != 0:
            print(f"[warn] render failed for {base}"); continue
        subprocess.run([sys.executable, STITCH, cmp_dir, a.band], env=os.environ.copy())
        # deterministic visual regression (+ optional Gemini interpretation)
        if os.path.isfile(VISUAL_DIFF):
            vcmd = [sys.executable, VISUAL_DIFF,
                    os.path.join(cmp_dir, "original.png"),
                    os.path.join(cmp_dir, "candidate.png"), "--out", cmp_dir]
            if a.ai:
                vcmd.append("--ai")
            subprocess.run(vcmd, env=os.environ.copy())
        try:
            ho = Image.open(os.path.join(cmp_dir, "original.png")).height
            hc = Image.open(os.path.join(cmp_dir, "candidate.png")).height
            tag = "" if abs(ho - hc) < 40 else "  <-- height delta (check font!)"
            print(f"[ok] {base}: original {ho}px vs candidate {hc}px (delta {hc-ho:+d}){tag}")
        except Exception:
            pass
        matched.append(base)

    extra = [os.path.splitext(f)[0] for f in os.listdir(a.output)
             if f.lower().endswith(".html")] if os.path.isdir(a.output) else []
    extra = [e for e in extra if e not in matched and e != "index"]

    print("\n" + "=" * 50)
    print(f"matched : {len(matched)}  -> compare/<name>/compare_*.png")
    if missing:
        print(f"MISSING output for: {', '.join(missing)}")
    if extra:
        print(f"output with no source: {', '.join(extra)}")
    print("Open compare/<name>/compare_*.png — source (left) vs generated (right).")


if __name__ == "__main__":
    main()
