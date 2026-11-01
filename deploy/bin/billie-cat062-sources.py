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


def validate_document(
    value: object,
) -> tuple[dict[str, int] | None, dict[str, dict[str, dict[str, dict[str, int]]]]]:
    if not isinstance(value, dict) or value.keys() - {"default", "kids", "sources"}:
        raise ValueError("source map accepts only 'default', 'kids', and legacy 'sources' properties")
    if "kids" not in value and "sources" not in value and "default" not in value:
        raise ValueError("source map must configure a node default or contain a 'kids' property")
    if "kids" in value and not isinstance(value["kids"], dict):
        raise ValueError("source map 'kids' must be an object")
    kids: dict[str, dict[str, dict[str, dict[str, int]]]] = {}
    used: dict[tuple[int, int], str] = {}
    default: dict[str, int] | None = None

    def parse_pair(pair: object, label: str) -> dict[str, int]:
        if not isinstance(pair, dict) or set(pair) != {"sac", "sic"}:
            raise ValueError(f"'{label}' must contain only sac and sic")
        codes: dict[str, int] = {}
        for code_name in ("sac", "sic"):
            code = pair[code_name]
            if isinstance(code, bool) or not isinstance(code, int) or not 0 <= code <= 255:
                raise ValueError(f"'{label}' {code_name} must be an integer from 0 to 255")
            codes[code_name] = code
        pair_key = (codes["sac"], codes["sic"])
        if pair_key in used:
            raise ValueError(f"'{label}' shares SAC/SIC {pair_key[0]}/{pair_key[1]} with '{used[pair_key]}'")
        used[pair_key] = label
        return codes

    if "default" in value:
        default = parse_pair(value["default"], "node default")

    value_kids: dict[str, object] = value.get("kids", {})
    if "sources" in value:
        legacy_sources = value["sources"]
        if not isinstance(legacy_sources, dict):
            raise ValueError("legacy source map 'sources' must be an object")
        if "*" in value_kids:
            raise ValueError("legacy global 'sources' cannot be combined with a wildcard entry in 'kids'")
        value_kids = {**value_kids, "*": {"sources": legacy_sources}}

    for kid_id, kid_value in value_kids.items():
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
            label = f"legacy/{source_id}" if kid_id == "*" else f"{kid_id}/{source_id}"
            codes = parse_pair(pair, label)
            sources[source_id] = codes
        kids[kid_id] = {"sources": sources}
    return default, kids


def read_sources(path: Path) -> tuple[dict[str, int] | None, dict[str, dict[str, dict[str, dict[str, int]]]]]:
    if not path.exists():
        return None, {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and "sources" in value and isinstance(value["sources"], dict):
            print("Legacy global CAT062 source map detected; translator compatibility is retained. Use 'source migrate <kid>' to scope it.", file=sys.stderr)
        return validate_document(value)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        fail(f"cannot read valid source map at {path}: {exc}")


def write_sources(
    path: Path,
    default: dict[str, int] | None,
    kids: dict[str, dict[str, dict[str, dict[str, int]]]],
) -> None:
    document_value: dict[str, object] = {"kids": dict(sorted(kids.items()))}
    if default is not None:
        document_value["default"] = default
    document = json.dumps(document_value, indent=2) + "\n"
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
    domains = parser.add_subparsers(dest="domain", required=True)
    source = domains.add_parser("source", help="manage kid/source SAC/SIC assignments")
    actions = source.add_subparsers(dest="action", required=True)
    list_parser = actions.add_parser("list", help="list configured CAT062 identities")
    list_parser.add_argument("kid_id", nargs="?")
    set_parser = actions.add_parser("set", help="assign a unique SAC/SIC pair to a kid and sourceId")
    set_parser.add_argument("kid_id")
    set_parser.add_argument("source_id")
    set_parser.add_argument("--sac", type=int, required=True)
    set_parser.add_argument("--sic", type=int, required=True)
    remove_parser = actions.add_parser("remove", help="remove a kid/source assignment")
    remove_parser.add_argument("kid_id")
    remove_parser.add_argument("source_id")
    migrate_parser = actions.add_parser("migrate", help="scope a legacy global map to one kid")
    migrate_parser.add_argument("kid_id")

    default = domains.add_parser("default", help="manage the node-wide CAT062 fallback")
    default_actions = default.add_subparsers(dest="action", required=True)
    default_actions.add_parser("show", help="show the node default")
    default_set = default_actions.add_parser("set", help="set the node default SAC/SIC pair")
    default_set.add_argument("--sac", type=int, required=True)
    default_set.add_argument("--sic", type=int, required=True)
    default_actions.add_parser("clear", help="clear the node default")
    args = parser.parse_args()

    node_default, kids = read_sources(args.file)
    try:
        if args.domain == "default":
            if args.action == "show":
                if node_default is None:
                    print("No node CAT062 default is configured.")
                else:
                    print(f"Node default: SAC={node_default['sac']} SIC={node_default['sic']}")
                return 0
            if args.action == "set":
                updated_default, _ = validate_document({"default": {"sac": args.sac, "sic": args.sic}, "kids": kids})
                write_sources(args.file, updated_default, kids)
                print(f"Set node CAT062 default: SAC={args.sac} SIC={args.sic}")
                return 0
            if node_default is None:
                raise ValueError("no node CAT062 default is configured")
            write_sources(args.file, None, kids)
            print("Cleared node CAT062 default; kid/source assignments were preserved.")
            return 0

        if args.action == "list":
            if node_default is None:
                print("Node default: not configured")
            else:
                print(f"Node default: SAC={node_default['sac']} SIC={node_default['sic']}")
            if not kids:
                print("No kid/source SAC/SIC assignments are configured.")
            else:
                if "*" in kids:
                    print("Legacy assignments apply to all kids until migrated:")
                for kid_id, kid in sorted(kids.items()):
                    display_kid = "legacy (all kids)" if kid_id == "*" else kid_id
                    if args.kid_id and kid_id != args.kid_id:
                        continue
                    for source_id, codes in sorted(kid["sources"].items()):
                        print(f"{display_kid}/{source_id}: SAC={codes['sac']} SIC={codes['sic']}")
            if node_default is None and not kids:
                print("CAT062 requests without an exact assignment will be rejected.")
            return 0

        if args.action == "migrate":
            if not KID_ID.fullmatch(args.kid_id):
                raise ValueError("kid ID must contain lowercase letters/digits/hyphens, 1 to 63 characters")
            legacy = kids.pop("*", None)
            if legacy is None:
                raise ValueError("no legacy global map exists to migrate")
            if args.kid_id in kids:
                raise ValueError(f"kid '{args.kid_id}' already has scoped assignments; resolve them before migration")
            kids[args.kid_id] = legacy
            _, kids = validate_document({"default": node_default, "kids": kids} if node_default else {"kids": kids})
            write_sources(args.file, node_default, kids)
            print(f"Migrated legacy CAT062 assignments to kid '{args.kid_id}'. Other kids use exact assignments or the node default.")
            return 0

        if "*" in kids and args.action in {"set", "remove"}:
            raise ValueError("legacy global assignments are present; run 'sudo billie cat062 source migrate <kid>' before editing")

        if not KID_ID.fullmatch(args.kid_id):
            raise ValueError("kid ID must contain lowercase letters/digits/hyphens, 1 to 63 characters")
        if not args.source_id.strip() or len(args.source_id) > 128:
            raise ValueError("sourceId must contain 1 to 128 non-whitespace characters")
        if args.action == "set":
            updated = json.loads(json.dumps(kids))
            sources = updated.get(args.kid_id, {}).get("sources", {})
            sources[args.source_id] = {"sac": args.sac, "sic": args.sic}
            updated[args.kid_id] = {"sources": sources}
            _, kids = validate_document({"default": node_default, "kids": updated} if node_default else {"kids": updated})
            write_sources(args.file, node_default, kids)
            print(f"Assigned CAT062 source {args.kid_id}/{args.source_id}: SAC={args.sac} SIC={args.sic}")
            return 0

        if args.kid_id not in kids or args.source_id not in kids[args.kid_id]["sources"]:
            raise ValueError(f"no CAT062 source assignment exists for '{args.kid_id}/{args.source_id}'")
        del kids[args.kid_id]["sources"][args.source_id]
        if not kids[args.kid_id]["sources"]:
            del kids[args.kid_id]
        write_sources(args.file, node_default, kids)
        print(f"Removed CAT062 source assignment for {args.kid_id}/{args.source_id}")
        return 0
    except ValueError as exc:
        fail(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
