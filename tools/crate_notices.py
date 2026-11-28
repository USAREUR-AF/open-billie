#!/usr/bin/env python3
"""Write the licence notices of the crates a shipped Rust binary is built from.

    crate_notices.py <Cargo.toml> <package> <notices file>          write it
    crate_notices.py <Cargo.toml> <package> <notices file> --check  exit 1 when it is not current

The crates are every normal and build dependency of <package> on Linux amd64 and
arm64, from the lockfile (`cargo metadata --locked`, which fetches the locked
sources). For each third-party crate the file names its version, its licence
expression and its source, then holds the licence files the crate itself ships
(LICENSE*, LICENCE*, COPYING*, UNLICENSE*, NOTICE*), verbatim. A text several
crates ship is written once, with the crates it covers. The same lockfile always
gives the same file.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

TARGETS = ("x86_64-unknown-linux-gnu", "aarch64-unknown-linux-gnu")
PREFIXES = ("license", "licence", "copying", "unlicense", "notice")


def metadata(manifest: Path, target: str) -> dict:
    out = subprocess.run(
        ["cargo", "metadata", "--locked", "--format-version", "1", "--manifest-path", str(manifest), "--filter-platform", target],
        check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(out)


def crates(manifest: Path, package: str) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for target in TARGETS:
        m = metadata(manifest, target)
        by_id = {p["id"]: p for p in m["packages"]}
        nodes = {n["id"]: n for n in m["resolve"]["nodes"]}
        roots = [p["id"] for p in m["packages"] if p["name"] == package and p["source"] is None]
        if len(roots) != 1:
            sys.exit(f"crate notices: {manifest} has no local package {package}")
        todo, seen = list(roots), set()
        while todo:
            i = todo.pop()
            if i in seen:
                continue
            seen.add(i)
            for dep in nodes[i]["deps"]:
                if any(k["kind"] in (None, "build") for k in dep["dep_kinds"]):
                    todo.append(dep["pkg"])
        for i in seen:
            p = by_id[i]
            if p["source"] is not None:
                found[f'{p["name"]} {p["version"]}'] = p
    return found


def licence_files(d: Path) -> list[Path]:
    return sorted(f for f in d.iterdir() if f.is_file() and f.name.lower().startswith(PREFIXES))


def source_name(p: dict) -> str:
    s = p["source"]
    if s.startswith("registry+"):
        return "crates.io"
    if s.startswith("git+"):
        url, _, rev = s[len("git+"):].partition("#")
        return f"{url.split('?')[0]} at {rev}"
    return s


def render(manifest: Path, package: str) -> str:
    found = crates(manifest, package)
    texts: dict[str, list[str]] = {}
    lines = [
        f"Third-party crates in {package}",
        "",
        f"Written by tools/crate_notices.py from {manifest.as_posix()} and its lockfile; do not edit.",
        "Each crate below is compiled into the binary or used to build it. Its licence",
        "files follow, verbatim; a text several crates ship is given once.",
        "",
    ]
    for key in sorted(found):
        p = found[key]
        root = Path(p["manifest_path"]).parent
        files = licence_files(root)
        where = ""
        if not files and p["source"].startswith("git+"):
            # A crate in a subdirectory of a git repository: the licence is at the checkout's root.
            up = root
            while not files and "checkouts" in up.parent.parts and up.parent.parent.name != "checkouts":
                up = up.parent
                files = licence_files(up)
            where = "  (licence files from its repository's root)" if files and up != root else ""
        lines.append(f"{key}  {p.get('license') or 'no licence expression'}  {source_name(p)}{where}")
        if not files:
            lines.append("  (the crate ships no licence file)")
        for f in files:
            text = f.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").strip("\n") + "\n"
            texts.setdefault(text, []).append(f"{key} {f.name}")
    for n, (text, owners) in enumerate(texts.items(), 1):
        lines += ["", "=" * 78, f"Text {n}, shipped by: " + ", ".join(owners), "=" * 78, "", text.rstrip("\n")]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("manifest", type=Path)
    ap.add_argument("package")
    ap.add_argument("notices", type=Path)
    ap.add_argument("--check", action="store_true", help="exit 1 when the notices file is not current")
    a = ap.parse_args()
    text = render(a.manifest, a.package)
    if a.check:
        if not a.notices.is_file() or a.notices.read_text(encoding="utf-8") != text:
            print(f"crate notices: {a.notices} is not current; run tools/crate_notices.py {a.manifest} {a.package} {a.notices}", file=sys.stderr)
            return 1
        print(f"crate notices: {a.notices} is current")
        return 0
    a.notices.write_text(text, encoding="utf-8")
    print(f"crate notices: wrote {a.notices}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
