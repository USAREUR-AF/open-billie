#!/usr/bin/env python3
"""Check the landing page in site/ against the tree and the recorded data.

    python3 site/build.py

Fails when a number the page states differs from what it is measured from, when
the code shown faintly behind the first screen is no longer in the translator,
or when the validator session on the page differs from site/captures/validate.txt.
Also copies the drawn figure from docs/figures/ into site/assets/, so the page
does not keep a second copy of it.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


def measured():
    data = json.loads((SITE / "assets/hero-data.json").read_text())
    first = {o["format"]: o for o in data["tracks"][0]["outputs"]}
    request_rs = (ROOT / "runtime/rust/translator/src/request.rs").read_text()
    variants = re.search(r"pub enum EncoderFormat \{(.*?)\}", request_rs, re.S).group(1)
    return {
        # site/assets/hero-data.json, written by site/hero-data/make.py
        "frame-bytes": str(data["frameLength"]),
        "tracks": str(len(data["tracks"])),
        "cot-bytes": str(first["cot"]["length"]),
        "cat062-bytes": str(first["asterix-cat062"]["length"]),
        # variants of `pub enum EncoderFormat` in runtime/rust/translator/src/request.rs
        "formats": str(len(re.findall(r"^\s*\w+,", variants, re.M))),
        # ls kids/examples/oetf/Containerfile*  (one per decoder runtime)
        "runtimes": str(len(list((ROOT / "kids/examples/oetf").glob("Containerfile*")))),
    }


def unescape(s):
    return s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&amp;", "&")


def check():
    page = (SITE / "index.html").read_text()
    errors = []
    want = measured()
    for key, value in want.items():
        found = re.findall(rf'data-n="{key}">([^<]*)<', page)
        if not found:
            errors.append(f"{key}: the page does not state it")
        errors += [f"{key}: the page says {f}, measured {value}" for f in found if f.strip() != value]
    code = unescape(re.search(r'<pre class="bgcode"[^>]*>(.*?)</pre>', page, re.S).group(1))
    if code.strip("\n") not in (ROOT / "runtime/rust/translator/src/cot.rs").read_text():
        errors.append("the code behind the first screen is no longer in runtime/rust/translator/src/cot.rs")
    # the page wraps each line in <span class="ln">, and each word with a hyphen or slash in <span class="w">
    term = re.search(r'<pre class="term" id="validate"[^>]*>(.*?)</pre>', page, re.S).group(1)
    term = unescape(re.sub(r"<[^>]+>", "", term))
    if term.rstrip("\n") != (SITE / "captures/validate.txt").read_text().rstrip("\n"):
        errors.append("the validator session on the page differs from site/captures/validate.txt")
    for e in errors:
        print("site check:", e, file=sys.stderr)
    if not errors:
        print("site check: " + ", ".join(f"{k}={v}" for k, v in want.items()))
    return not errors


def copy():
    for name in ("open-billie-node-light.svg", "open-billie-node-dark.svg"):
        shutil.copyfile(ROOT / "docs/figures" / name, SITE / "assets" / name)


if __name__ == "__main__":
    copy()
    ok = check()
    # no command box cut off at 1440 or 390 px, no output box at 1440 (headless Chrome)
    fit = subprocess.run([sys.executable, str(SITE / "fitcheck.py"), str(SITE), "index.html"]).returncode == 0
    sys.exit(0 if ok and fit else 1)
