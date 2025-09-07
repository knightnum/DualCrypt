#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DualCrypt.py

Developer: Knightnum Limited
Website: https://knightnum.online
Created: 2025
Description: Batch tool to obfuscate HTML with basic protection.
"""

import argparse
import base64
import re
from pathlib import Path
from urllib.parse import quote

# ---------- Constants ----------
PROTECT_JS = (
    "<script>"
    "document.addEventListener('contextmenu',function(e){e.preventDefault();});"
    "document.addEventListener('keydown',function(e){var k=(e.key||'').toLowerCase();"
    "if((e.ctrlKey&&k==='u')||(e.ctrlKey&&e.shiftKey&&k==='i')||e.key==='F12'){e.preventDefault();}});"
    "</script>"
)

WRAP_TEMPLATE = (
    '<!DOCTYPE html>\n'
    '<html lang="th">\n<head>\n'
    '<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    '{title}\n{favicons}\n{protect}\n'
    '</head>\n<body>\n'
    '<script>{payload}</script>\n'
    '<noscript>กรุณาเปิดใช้งาน JavaScript</noscript>\n'
    '</body>\n</html>\n'
)

# ---------- Helpers ----------
def extract_head_bits(html: str):
    m = re.search(r'<head\b[^>]*>(.*?)</head>', html, flags=re.IGNORECASE | re.DOTALL)
    title = "<title>Protected App</title>"
    if m:
        head = m.group(1)
        mtitle = re.search(r'<title\b[^>]*>.*?</title>', head, flags=re.IGNORECASE | re.DOTALL)
        if mtitle:
            title = mtitle.group(0)
    favicons = (
        '<link rel="icon" type="image/png" href="icon.png">\n'
        '<link rel="apple-touch-icon" href="icon.png">\n'
        '<link rel="manifest" href="icon.png">'
    )
    return title, favicons

def light_minify(html: str) -> str:
    html = re.sub(r'>\s+<', '><', html)
    html = re.sub(r'\s{2,}', ' ', html)
    return html

def process_file(src_path: Path, out_path: Path, *, mode: str, minify: bool, protect: bool):
    original = src_path.read_text(encoding="utf-8", errors="ignore")
    title, favicons = extract_head_bits(original)
    html_for_payload = original if not minify is False else light_minify(original)

    if mode == "base64":
        b64 = base64.b64encode(html_for_payload.encode("utf-8")).decode("ascii")
        payload = f"document.write(atob('{b64}'));"
    elif mode == "dual":
        percent = quote(html_for_payload)
        b64 = base64.b64encode(percent.encode("utf-8")).decode("ascii")
        payload = f"document.write(unescape(atob('{b64}')));"
    else:  # percent
        encoded = quote(html_for_payload)
        payload = f"document.write(unescape('{encoded}'));"

    protect_block = PROTECT_JS if protect else ""
    wrapped = WRAP_TEMPLATE.format(
        title=title or "<title>Protected App</title>",
        favicons=favicons or "",
        protect=protect_block,
        payload=payload,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(wrapped, encoding="utf-8")

def run_cli(args):
    src_dir = Path(args.src)
    dst_dir = Path(args.dst)
    if not src_dir.exists():
        raise SystemExit(f"Source directory not found: {src_dir}")

    files = list(src_dir.glob(args.glob))
    if not files:
        print("No files matched pattern", args.glob)
        return

    count = 0
    for f in files:
        out = dst_dir / f.relative_to(src_dir)
        mode = args.mode or ("base64" if args.use_base64 else "percent")
        process_file(
            f,
            out,
            mode=mode,
            minify=(not args.no_minify),
            protect=(not args.no_protect),
        )
        count += 1
    print(f"Done. Processed {count} files into {dst_dir}")

# ---------- Interactive ----------
def _prompt_yes_no(msg, default=True):
    d = "Y/n" if default else "y/N"
    while True:
        ans = input(f"{msg} [{d}]: ").strip().lower()
        if ans == "": return default
        if ans in ("y", "yes"): return True
        if ans in ("n", "no"): return False
        print("Please answer y or n.")

def interactive_main():
    print("=" * 60)
    print(" DualCrypt — Interactive Mode")
    print(" Developer: Knightnum Limited")
    print(" Website:   https://knightnum.online")
    print("=" * 60)
    src = input("Source directory [src]: ").strip() or "src"
    dst = input("Destination directory [dist]: ").strip() or "dist"

    print("\nChoose encoding method:")
    print("  1) Percent-encode (unescape)   [default]")
    print("  2) Base64 (atob)")
    print("  3) Dual (Base64 + Percent)")
    enc_choice = input("Enter 1, 2 or 3 [1]: ").strip() or "1"

    if enc_choice == "2":
        mode = "base64"
    elif enc_choice == "3":
        mode = "dual"
    else:
        mode = "percent"

    minify = _prompt_yes_no("Enable light minify?", default=True)
    protect = _prompt_yes_no("Inject protection (right-click / Ctrl+U / F12)?", default=True)

    print("\nSummary:")
    print(f"  src = {src}")
    print(f"  dst = {dst}")
    print(f"  encoding = {mode}")
    print(f"  minify = {minify}")
    print(f"  protection = {protect}")

    if not _prompt_yes_no("Proceed?", default=True):
        print("Canceled.")
        return

    class Args: pass
    a = Args()
    a.src = src
    a.dst = dst
    a.glob = "**/*.html"
    a.mode = mode
    a.use_base64 = False
    a.no_minify = (not minify)
    a.no_protect = (not protect)
    run_cli(a)

# ---------- Main ----------
def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--interactive", action="store_true", help="Run with interactive menu")
    ap.add_argument("--src", help="Source directory containing HTML files")
    ap.add_argument("--dst", help="Destination directory for protected files")
    ap.add_argument("--no-minify", action="store_true", help="Disable light minification")
    ap.add_argument("--no-protect", action="store_true", help="Do not inject the protection script")
    ap.add_argument("--glob", default="**/*.html", help="Glob pattern to include (default: **/*.html)")
    ap.add_argument("--use-base64", action="store_true", help="(Deprecated) Use Base64 encoding")
    ap.add_argument("--mode", choices=["percent", "base64", "dual"], help="Encoding mode")
    args = ap.parse_args()

    if args.interactive or (not args.src and not args.dst):
        try:
            interactive_main()
            return
        except KeyboardInterrupt:
            print("\nCanceled.")
            return

    if not args.src or not args.dst:
        ap.error("the following arguments are required: --src, --dst")

    run_cli(args)

if __name__ == "__main__":
    main()
