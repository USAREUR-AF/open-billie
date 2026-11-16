#!/usr/bin/env python3
"""Copy or check the goat-transformers pack and model files the translator embeds.

The translator's optional goat-transformers encoder path embeds a fixed set of
pack and model definition files. They are copied from the goat-transformers
commit named by `rev` in runtime/rust/translator/Cargo.toml, the same commit
the Rust crate is built from.

  python3 tools/sync_goat_transformers_packs.py            # copy, rewrite COMMIT and SHA256SUMS
  python3 tools/sync_goat_transformers_packs.py --check    # exit 1 when the copy differs

The source is the checkout Cargo made of the pinned commit (found with
`cargo metadata --locked --all-features`). `--source <dir>` names another checkout of
goat-transformers; its HEAD must be the pinned commit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRANSLATOR_MANIFEST = ROOT / "runtime/rust/translator/Cargo.toml"
DESTINATION = ROOT / "runtime/rust/translator/goat-transformers"
CRATE = "goat-transformers"
# Paths in the goat-transformers repository, kept at the same relative paths
# under DESTINATION. Order is the order of SHA256SUMS.
FILES = (
    "NOTICE",
    "model/cat062.def",
    "model/core.def",
    "model/sapient.def",
    "model/track.def",
    "packs/asterix-cat062/pack.def",
    "packs/canonical-track-v2/pack.def",
    "packs/cot-xml/pack.def",
    "packs/sapient/pack.def",
)


def pinned_revision(manifest: Path = TRANSLATOR_MANIFEST) -> str:
    text = manifest.read_text(encoding="utf-8")
    section = re.search(r"^\[dependencies\.goat-transformers\]\n(.*?)(?=^\[|\Z)", text, re.MULTILINE | re.DOTALL)
    if not section:
        raise SystemExit(f"{manifest}: no [dependencies.goat-transformers] section")
    revision = re.search(r'^rev\s*=\s*"([0-9a-f]{40})"\s*$', section.group(1), re.MULTILINE)
    if not revision:
        raise SystemExit(f"{manifest}: goat-transformers must be pinned with a 40-character rev")
    return revision.group(1)


def cargo_checkout(revision: str) -> Path:
    try:
        output = subprocess.run(
            ["cargo", "metadata", "--locked", "--all-features", "--format-version", "1", "--manifest-path", str(TRANSLATOR_MANIFEST)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", "") or str(error)
        raise SystemExit(f"cargo metadata failed; pass --source <goat-transformers checkout>\n{detail}")
    for package in json.loads(output)["packages"]:
        source = package.get("source") or ""
        if package["name"] == CRATE and source.startswith("git+"):
            if not source.endswith("#" + revision):
                raise SystemExit(f"Cargo.lock resolves {CRATE} to {source}, not to rev {revision}")
            # <checkout>/engines/rust/Cargo.toml
            return Path(package["manifest_path"]).parents[2]
    raise SystemExit(f"cargo metadata lists no git package named {CRATE}")


def named_checkout(source: Path, revision: str) -> Path:
    head = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    if head != revision:
        raise SystemExit(f"{source} is at {head}; the pinned commit is {revision}")
    dirty = subprocess.run(
        ["git", "-C", str(source), "status", "--porcelain", "--", *FILES], check=True, capture_output=True, text=True
    ).stdout.strip()
    if dirty:
        raise SystemExit(f"{source} has local changes in the files to copy:\n{dirty}")
    return source


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def expected_files(source: Path, revision: str) -> dict[str, bytes]:
    files = {relative: (source / relative).read_bytes() for relative in FILES}
    files["COMMIT"] = f"{revision}\n".encode("ascii")
    sums = "".join(f"{sha256(files[relative])}  {relative}\n" for relative in FILES)
    files["SHA256SUMS"] = sums.encode("ascii")
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="compare only; exit 1 on any difference")
    parser.add_argument("--source", type=Path, help="a goat-transformers checkout at the pinned commit")
    arguments = parser.parse_args()

    revision = pinned_revision()
    source = named_checkout(arguments.source, revision) if arguments.source else cargo_checkout(revision)
    expected = expected_files(source, revision)

    if arguments.check:
        problems = []
        for relative, data in expected.items():
            path = DESTINATION / relative
            if not path.is_file():
                problems.append(f"missing: {relative}")
            elif path.read_bytes() != data:
                problems.append(f"differs from goat-transformers {revision[:12]}: {relative}")
        if problems:
            for problem in problems:
                print(f"goat-transformers packs: {problem}", file=sys.stderr)
            print("Run python3 tools/sync_goat_transformers_packs.py and commit the result.", file=sys.stderr)
            return 1
        print(f"Embedded goat-transformers files match commit {revision} ({len(FILES)} files).")
        return 0

    for relative, data in expected.items():
        path = DESTINATION / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print(f"Copied {len(FILES)} files from goat-transformers {revision} to {DESTINATION.relative_to(ROOT).as_posix()}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
