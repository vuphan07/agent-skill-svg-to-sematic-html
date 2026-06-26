#!/usr/bin/env python3
"""Serve a folder over localhost so you can view the SVG exports (and the
generated HTML) as rendered images in a browser.

Usage:
    python serve.py [DIR=svg-input] [PORT=5501]

Then open http://localhost:PORT/ and click a file. Use this to eyeball the
source SVGs, or point it at html-output/ to eyeball generated pages.
For automated section-by-section comparison, prefer batch_check.py instead.
"""
import sys, os, http.server, socketserver, functools

def main():
    directory = sys.argv[1] if len(sys.argv) > 1 else "svg-input"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 5501
    directory = os.path.abspath(directory)
    if not os.path.isdir(directory):
        print(f"[error] not a directory: {directory}"); sys.exit(1)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"[ok] serving {directory}")
        print(f"     http://localhost:{port}/   (Ctrl+C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[stopped]")

if __name__ == "__main__":
    main()
