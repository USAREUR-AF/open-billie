#!/usr/bin/env python3
"""Manage per-kid, per-source ASTERIX CAT062 SAC/SIC assignments."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import NoReturn


KID_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")


def fail(message: str, code: int = 2) -> NoReturn:
    print(f"billie cat062: {message}", file=sys.stderr)
    raise SystemExit(code)


def validate_document(value: object) -> dict[str, dict[str, dict[str, dict[str, int]]]]:
    if not isinstance(value, dict) or set(value) != {"kids"} or not isinstance(value["kids"], dict):
        raise ValueError("source map must contain only an object property named 'kids'")
    kids: dict[str, dict[str, dict[str, dict[str, int]]]] = {}
    used: dict[tuple[int, int], str] = {}
    for kid_id, kid_value in value["kids"].items():
        if not isinstance(kid_id, str) or (kid_id != "*" and not KID_ID.fullmatch(kid_id)):
            raise ValueError("kid IDs must be lowercase letters/digits/hyphens, 1 to 63 characters")
        if not isinstance(kid_value, dict) or set(kid_value) != {"sources"} or not isinstance(kid_value["sources"], dict):
            raise ValueError(f"kid '{kid_id}' must contain only an object property named 'sources'")
        sources: dict[str, dict[str, int]] = {}
        for source_id, pair in kid_value["sources"].items():
            if not isinstance(source_id, str) or not source_id.strip() or len(source_id) > 128:
                raise ValueError("source IDs must contain 1 to 128 non-whitespace characters")
            if not isinstance(pair, dict) or set(pair) != {"sac", "sic"}:
                raise ValueError(f"source '{kid_id}/{source_id}' must contain only sac and sic")
            codes: dict[str, int] = {}
            for code_name in ("sac", "sic"):
                code = pair[code_name]
                if isinstance(code, bool) or not isinstance(code, int) or not 0 <= code <= 255:
                    raise ValueError(f"source '{kid_id}/{source_id}' {code_name} must be an integer from 0 to 255")
                codes[code_name] = code
            pair_key = (codes["sac"], codes["sic"])
            if pair_key in used:
                raise ValueError(f"sources '{used[pair_key]}' and '{kid_id}/{source_id}' share SAC/SIC {pair_key[0]}/{pair_key[1]}")
            used[pair_key] = f"{kid_id}/{source_id}"
            sources[source_id] = codes
        kids[kid_id] = {"sources": sources}
    return kids


def read_sources(path: Path) -> dict[str, dict[str, dict[str, dict[str, int]]]]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and set(value) == {"sources"} and isinstance(value["sources"], dict):
            print("Legacy global CAT062 source map detected; translator compatibility is retained. Use 'source migrate <kid>' to scope it.", file=sys.stderr)
            value = {"kids": {"*": {"sources": value["sources"]}}}
        return validate_document(value)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        fail(f"cannot read valid source map at {path}: {exc}")


def write_sources(path: Path, kids: dict[str, dict[str, dict[str, dict[str, int]]]]) -> None:
    document = json.dumps({"kids": dict(sorted(kids.items()))}, indent=2) + "\n"
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(document)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == "posix":
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        if os.name == "posix":
            os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=Path("/etc/billie/translator/cat062-sources.json"))
    subparsers = parser.add_subparsers(dest="command", required=True)
    list_parser = subparsers.add_parser("list", help="list configured kid/source identities")
    list_parser.add_argument("kid_id", nargs="?")
    set_parser = subparsers.add_parser("set", help="assign a unique SAC/SIC pair to a kid and sourceId")
    set_parser.add_argument("kid_id")
    set_parser.add_argument("source_id")
    set_parser.add_argument("--sac", type=int, required=True)
    set_parser.add_argument("--sic", type=int, required=True)
    remove_parser = subparsers.add_parser("remove", help="remove a kid/source assignment")
    remove_parser.add_argument("kid_id")
    remove_parser.add_argument("source_id")
    migrate_parser = subparsers.add_parser("migrate", help="scope a legacy global map to one kid")
    migrate_parser.add_argument("kid_id")
    args = parser.parse_args()

    kids = read_sources(args.file)
    try:
        if args.command == "list":
            if not kids:
                print("No kid/source SAC/SIC map is configured; CAT062 uses the platform default.")
            else:
                if "*" in kids:
                    print("Legacy assignments apply to all kids until migrated:")
                for kid_id, kid in sorted(kids.items()):
                    display_kid = "legacy (all kids)" if kid_id == "*" else kid_id
                    if args.kid_id and kid_id != args.kid_id:
                        continue
                    for source_id, codes in sorted(kid["sources"].items()):
                        print(f"{display_kid}/{source_id}: SAC={codes['sac']} SIC={codes['sic']}")
            return 0

        if args.command == "migrate":
            if not KID_ID.fullmatch(args.kid_id):
                raise ValueError("kid ID must contain lowercase letters/digits/hyphens, 1 to 63 characters")
            legacy = kids.pop("*", None)
            if legacy is None:
                raise ValueError("no legacy global map exists to migrate")
            if args.kid_id in kids:
                raise ValueError(f"kid '{args.kid_id}' already has scoped assignments; resolve them before migration")
            kids[args.kid_id] = legacy
            kids = validate_document({"kids": kids})
            write_sources(args.file, kids)
            print(f"Migrated legacy CAT062 assignments to kid '{args.kid_id}'. Other kids now require their own source assignments or the platform default.")
            print("The running translator was restarted with the migrated source map.")
            return 0

        if "*" in kids:
            raise ValueError("legacy global assignments are present; run 'sudo billie cat062 source migrate <kid>' before editing")

        if not KID_ID.fullmatch(args.kid_id):
            raise ValueError("kid ID must contain lowercase letters/digits/hyphens, 1 to 63 characters")
        if not args.source_id.strip() or len(args.source_id) > 128:
            raise ValueError("sourceId must contain 1 to 128 non-whitespace characters")
        if args.command == "set":
            updated = json.loads(json.dumps(kids))
            sources = updated.get(args.kid_id, {}).get("sources", {})
            sources[args.source_id] = {"sac": args.sac, "sic": args.sic}
            updated[args.kid_id] = {"sources": sources}
            kids = validate_document({"kids": updated})
            write_sources(args.file, kids)
            print(f"Assigned CAT062 source {args.kid_id}/{args.source_id}: SAC={args.sac} SIC={args.sic}")
            print("The running translator was restarted with the new source map.")
            return 0

        if args.kid_id not in kids or args.source_id not in kids[args.kid_id]["sources"]:
            raise ValueError(f"no CAT062 source assignment exists for '{args.kid_id}/{args.source_id}'")
        del kids[args.kid_id]["sources"][args.source_id]
        if not kids[args.kid_id]["sources"]:
            del kids[args.kid_id]
        write_sources(args.file, kids)
        print(f"Removed CAT062 source assignment for {args.kid_id}/{args.source_id}")
        print("The running translator was restarted with the updated source map.")
        return 0
    except ValueError as exc:
        fail(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
