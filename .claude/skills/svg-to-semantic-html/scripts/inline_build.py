#!/usr/bin/env python3
"""Inline the build into a SINGLE self-contained .html — `<style>` and `<script>`
live inside the HTML (no separate style.css to ship/link).

Why: the deliverable for these pages is usually one file you can open/email/paste
anywhere. We develop with a separate style.css (easier to edit + the verify loop),
then inline it for delivery. JS is already written inline in index.html, so this
mainly folds style.css into a <style> tag; with --embed-assets it also turns the
images into base64 data-URIs (fully portable, larger file).

Usage:
  python inline_build.py BUILD_DIR [--out FILE] [--embed-assets]

  BUILD_DIR        a folder holding index.html (+ style.css, assets/)
  --out FILE       output path (default: BUILD_DIR/<dirname>.html)
  --embed-assets   also base64-inline assets/*.png|jpg|svg|woff2 (default: keep links)

Stdlib only. Idempotent: re-running just rebuilds the single file.
"""
import os, re, sys, argparse, base64, mimetypes

LINK_RE = re.compile(r'<link\b[^>]*rel=["\']stylesheet["\'][^>]*>', re.I)


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def inline_css(html, css):
    """Replace the stylesheet <link> with an inline <style>. If no link is found
    (already inlined), inject the <style> before </head>."""
    style = "<style>\n" + css.strip() + "\n</style>"
    if LINK_RE.search(html):
        return LINK_RE.sub(style, html, count=1)
    if "</head>" in html:
        return html.replace("</head>", style + "\n</head>", 1)
    return style + "\n" + html


def embed_assets(html, build_dir):
    """Turn url(assets/x) and src="assets/x" references into base64 data-URIs."""
    adir = os.path.join(build_dir, "assets")
    if not os.path.isdir(adir):
        return html
    for name in os.listdir(adir):
        rel = "assets/" + name
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        with open(os.path.join(adir, name), "rb") as f:
            uri = f"data:{mime};base64," + base64.b64encode(f.read()).decode()
        html = html.replace(f"url({rel})", f"url({uri})")
        html = html.replace(f'src="{rel}"', f'src="{uri}"')
    return html


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("build_dir")
    ap.add_argument("--out")
    ap.add_argument("--embed-assets", action="store_true")
    a = ap.parse_args()

    index = os.path.join(a.build_dir, "index.html")
    css = os.path.join(a.build_dir, "style.css")
    if not os.path.isfile(index):
        sys.exit(f"[inline_build] no index.html in {a.build_dir}")

    html = read(index)
    if os.path.isfile(css):
        html = inline_css(html, read(css))
    else:
        print("[inline_build] no style.css (already inline?) — leaving HTML as-is")
    if a.embed_assets:
        html = embed_assets(html, a.build_dir)

    out = a.out or os.path.join(a.build_dir, os.path.basename(os.path.normpath(a.build_dir)) + ".html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)

    left = html.count('href="style.css"') + html.count('url(assets/') * (1 if a.embed_assets else 0)
    print(f"[inline_build] wrote {out}  ({len(html)/1024:.0f} KB)  "
          f"style inlined={'yes' if os.path.isfile(css) else 'n/a'}, "
          f"assets={'base64' if a.embed_assets else 'linked'}")
    if a.embed_assets and 'url(assets/' in html:
        print("[warn] some url(assets/...) not embedded — check filenames")


if __name__ == "__main__":
    main()
