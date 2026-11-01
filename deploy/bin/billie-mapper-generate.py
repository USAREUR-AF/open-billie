#!/usr/bin/env python3
"""Generate a reviewable mapper plan from Billie JSON or protobuf schemas."""

from __future__ import annotations

import argparse
import json
import shutil
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def fail(message: str, code: int = 2) -> int:
    print(f"billie mapper generate: {message}", file=sys.stderr)
    return code


def is_billie_schema(document: Any) -> bool:
    fields = document.get("fields") if isinstance(document, dict) else None
    return isinstance(fields, list) and bool(fields) and all(
        isinstance(field, dict) and "name" in field and "offset" in field and "type" in field
        for field in fields
    )


def billie_schema_files(schema: Path) -> list[Path]:
    files = [schema] if schema.is_file() else sorted(schema.rglob("*.json"))
    matched = []
    for path in files:
        try:
            if path.stat().st_size > 4 * 1024 * 1024:
                continue
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if is_billie_schema(document):
            matched.append(path)
    return matched


def json_messages(schema: Path) -> list[dict[str, Any]]:
    messages = []
    files = billie_schema_files(schema)
    if schema.is_file() and not files:
        raise ValueError(f"{schema} is not a Billie JSON byte-offset decode schema")
    for path in files:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            if schema.is_file():
                raise ValueError(f"cannot read schema JSON {path}: {exc}") from exc
            continue
        if not is_billie_schema(document):
            continue
        message_name = document.get("messageName", path.stem)
        fields = []
        for field in document["fields"]:
            source = {key: field[key] for key in (
                "name", "type", "offset", "units", "scale", "values", "validIf", "bits", "length"
            ) if key in field}
            fields.append({
                "sourcePath": field["name"],
                "sourceType": field["type"],
                "cardinality": "repeated" if field.get("count") or field.get("repeat") else "single",
                "source": source,
            })
        message_id = document.get("messageId")
        if message_id is None:
            match = re.fullmatch(r"msg_(\d+)", path.stem, flags=re.IGNORECASE)
            message_id = int(match.group(1)) if match else None
        messages.append({
            "name": message_name,
            "messageId": message_id,
            "schemaFile": str(path),
            "fields": fields,
        })
    if not messages:
        raise ValueError(f"no Billie JSON byte-offset schemas found under {schema}")
    common_headers = [message for message in messages if message["name"].casefold() == "header"]
    body_messages = [message for message in messages if message["name"].casefold() != "header"]
    if common_headers and body_messages:
        shared_fields = [field for header in common_headers for field in header["fields"]]
        for message in body_messages:
            body_names = {field["sourcePath"] for field in message["fields"]}
            message["fields"] = [
                *[field for field in shared_fields if field["sourcePath"] not in body_names],
                *message["fields"],
            ]
    return body_messages or messages


def protobuf_messages(schema: Path, proto_paths: list[Path]) -> list[dict[str, Any]]:
    protoc = shutil.which("protoc")
    if not protoc:
        raise ValueError("protobuf input requires protoc; install protobuf-compiler and retry")
    try:
        from google.protobuf import descriptor_pb2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ValueError("protobuf input requires Python protobuf descriptors; install python3-protobuf") from exc

    files = [schema] if schema.is_file() else sorted(schema.rglob("*.proto"))
    if not files or any(path.suffix != ".proto" for path in files):
        raise ValueError(f"no .proto schemas found under {schema}")
    include_roots = [path.expanduser().resolve() for path in proto_paths]
    if not include_roots:
        include_roots = [schema.resolve() if schema.is_dir() else schema.resolve().parent]
    relative_files = []
    for path in files:
        resolved = path.resolve()
        matching = next((root for root in include_roots if resolved == root or root in resolved.parents), None)
        if matching is None:
            raise ValueError(f"{path} is outside the configured --proto-path roots")
        relative_files.append((matching, resolved.relative_to(matching).as_posix()))

    with tempfile.TemporaryDirectory(prefix="billie-proto-descriptor-") as temporary:
        descriptor_file = Path(temporary) / "schema.pb"
        command = [protoc, "--include_imports", f"--descriptor_set_out={descriptor_file}"]
        command.extend(f"--proto_path={root}" for root in include_roots)
        command.extend(relative for _, relative in relative_files)
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise ValueError(f"protoc failed: {detail or 'unknown compiler error'}")
        descriptor_set = descriptor_pb2.FileDescriptorSet()
        descriptor_set.ParseFromString(descriptor_file.read_bytes())

    type_names = {
        descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE: "double",
        descriptor_pb2.FieldDescriptorProto.TYPE_FLOAT: "float",
        descriptor_pb2.FieldDescriptorProto.TYPE_INT64: "int64",
        descriptor_pb2.FieldDescriptorProto.TYPE_UINT64: "uint64",
        descriptor_pb2.FieldDescriptorProto.TYPE_INT32: "int32",
        descriptor_pb2.FieldDescriptorProto.TYPE_FIXED64: "fixed64",
        descriptor_pb2.FieldDescriptorProto.TYPE_FIXED32: "fixed32",
        descriptor_pb2.FieldDescriptorProto.TYPE_BOOL: "bool",
        descriptor_pb2.FieldDescriptorProto.TYPE_STRING: "string",
        descriptor_pb2.FieldDescriptorProto.TYPE_GROUP: "group",
        descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE: "message",
        descriptor_pb2.FieldDescriptorProto.TYPE_BYTES: "bytes",
        descriptor_pb2.FieldDescriptorProto.TYPE_UINT32: "uint32",
        descriptor_pb2.FieldDescriptorProto.TYPE_ENUM: "enum",
        descriptor_pb2.FieldDescriptorProto.TYPE_SFIXED32: "sfixed32",
        descriptor_pb2.FieldDescriptorProto.TYPE_SFIXED64: "sfixed64",
        descriptor_pb2.FieldDescriptorProto.TYPE_SINT32: "sint32",
        descriptor_pb2.FieldDescriptorProto.TYPE_SINT64: "sint64",
    }
    label_names = {
        descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL: "optional",
        descriptor_pb2.FieldDescriptorProto.LABEL_REQUIRED: "required",
        descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED: "repeated",
    }
    enums: dict[str, dict[int, str]] = {}
    selected_files = {relative for _, relative in relative_files}

    def collect_enums(enum_list: Any, prefix: str) -> None:
        for enum in enum_list:
            name = f".{prefix}.{enum.name}" if prefix else f".{enum.name}"
            enums[name] = {value.number: value.name for value in enum.value}

    def collect_nested_enums(message_list: Any, prefix: str) -> None:
        for message in message_list:
            name = f"{prefix}.{message.name}" if prefix else message.name
            collect_enums(message.enum_type, name)
            collect_nested_enums(message.nested_type, name)

    for file in descriptor_set.file:
        prefix = file.package
        collect_enums(file.enum_type, prefix)
        collect_nested_enums(file.message_type, prefix)
    messages: list[dict[str, Any]] = []

    def visit(message: Any, prefix: str, source_file: str) -> None:
        full_name = f"{prefix}.{message.name}" if prefix else message.name
        fields = []
        for field in message.field:
            source_type = type_names[field.type]
            source = {
                "name": field.name,
                "fieldNumber": field.number,
                "protobufType": source_type,
                "cardinality": label_names[field.label],
            }
            if field.type_name:
                source["typeName"] = field.type_name
            if field.HasField("oneof_index"):
                source["oneof"] = message.oneof_decl[field.oneof_index].name
            if field.type == descriptor_pb2.FieldDescriptorProto.TYPE_ENUM:
                source["enumValues"] = enums.get(field.type_name, {})
            fields.append({
                "sourcePath": field.name,
                "sourceType": source_type,
                "cardinality": label_names[field.label],
                "source": {"messageName": full_name, **source},
            })
        messages.append({"name": full_name, "messageId": None, "schemaFile": source_file, "fields": fields})
        for nested in message.nested_type:
            visit(nested, full_name, source_file)

    for file in descriptor_set.file:
        if file.name not in selected_files:
            continue
        prefix = file.package
        for message in file.message_type:
            visit(message, prefix, file.name)
    if not messages:
        raise ValueError("protobuf descriptor contains no message declarations")
    return messages


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="billie mapper generate",
        description="Create an Open Billie mapping plan and mapping-contract files from local decode schemas.",
    )
    parser.add_argument("--schema", required=True, type=Path, help="schema file or directory")
    parser.add_argument("--format", choices=("auto", "billie-json", "protobuf"), default="auto")
    parser.add_argument("--source-protocol", help="source protocol ID; inferred from a nearby kid manifest when available")
    parser.add_argument("--target", required=True, help="target encoder or output format name")
    parser.add_argument("--target-message", help="target message name; defaults to each source message name")
    parser.add_argument("--output", type=Path, default=Path("mapper-plan.json"))
    parser.add_argument("--mappings-dir", type=Path, help="directory for mapping-contract JSON files")
    parser.add_argument("--proto-path", action="append", type=Path, default=[], help="protobuf import root; may repeat")
    parser.add_argument("--interactive", action="store_true", help="prompt for target fields discovered in the schema")
    parser.add_argument("--enable-direct", action="store_true", help="enable selected direct copies with no conversion")
    parser.add_argument("--force", action="store_true", help="replace an existing output file")
    args = parser.parse_args()

    schema = args.schema.expanduser().resolve()
    if not schema.exists():
        return fail(f"schema path does not exist: {schema}", 1)
    if not (schema.is_file() or schema.is_dir()):
        return fail("schema path must be a file or directory", 1)
    output = args.output.expanduser().resolve()
    if output.exists() and not args.force:
        return fail(f"output already exists: {output}; pass --force to replace it", 1)
    mappings_dir = (args.mappings_dir or output.parent / f"{output.stem}.maps").expanduser().resolve()
    if mappings_dir.exists() and any(mappings_dir.iterdir()) and not args.force:
        return fail(f"mapping output directory is not empty: {mappings_dir}; pass --force to replace generated files", 1)
    if not args.target.strip():
        return fail("--target must name an encoder or output format", 1)
    if args.interactive and not sys.stdin.isatty():
        return fail("--interactive requires a terminal; rerun without it or provide mappings in the generated plan", 1)

    input_format = args.format
    if input_format == "auto":
        if schema.is_file():
            input_format = "protobuf" if schema.suffix == ".proto" else "billie-json"
        else:
            has_proto = any(schema.rglob("*.proto"))
            has_json = bool(billie_schema_files(schema))
            if has_proto == has_json:
                return fail("schema format is ambiguous or unsupported; specify --format billie-json or protobuf", 1)
            input_format = "protobuf" if has_proto else "billie-json"

    try:
        if input_format == "billie-json":
            messages = json_messages(schema)
            format_name = "billie-json-byte-offset/v1"
        else:
            messages = protobuf_messages(schema, args.proto_path)
            format_name = "protobuf-descriptor/v1"
    except (OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        return fail(str(exc), 1)

    source_protocol = args.source_protocol
    if not source_protocol:
        for parent in (schema.parent, *schema.parents):
            manifest = parent / "billie-kid.yaml"
            if not manifest.is_file():
                continue
            try:
                import yaml

                source_protocol = str(yaml.safe_load(manifest.read_text(encoding="utf-8"))["metadata"]["id"])
            except (ImportError, OSError, KeyError, TypeError, ValueError):
                pass
            if source_protocol:
                break
    if not source_protocol:
        return fail("cannot infer source protocol; pass --source-protocol <id>", 1)

    field_count = 0
    for message in messages:
        for field in message["fields"]:
            field_count += 1
            field["targetField"] = None
            field["conversion"] = {"kind": "TODO", "notes": "Review source units and target semantics."}
            field["status"] = "unmapped"
            if args.interactive:
                print(f"{field['sourcePath']} ({field['sourceType']})")
                target_field = input("  Target field name (blank leaves unresolved): ").strip()
                if target_field:
                    field["targetField"] = target_field
                    field["status"] = "needs_conversion_review"

    generated_files = []
    for message in messages:
        message_id = message.get("messageId")
        map_doc = {
            "mapVersion": 1,
            "source": {
                "protocol": source_protocol,
                "message": message["name"],
                **({"messageId": message_id} if message_id is not None else {}),
            },
            "target": {"protocol": args.target, "message": args.target_message or message["name"]},
            "direction": "inbound",
            "enabled": True,
            "preserveRaw": True,
            "mappings": [],
            "unmapped": [],
            "generatedBy": "billie mapper generate",
        }
        for field in message["fields"]:
            target_field = field["targetField"]
            if not target_field and args.enable_direct and not args.interactive:
                target_field = field["sourcePath"]
                field["targetField"] = target_field
                field["status"] = "direct_copy_review_required"
            if target_field:
                if args.enable_direct:
                    field["status"] = "direct_copy_review_required"
                map_doc["mappings"].append({
                    "from": field["sourcePath"],
                    "to": target_field,
                    "enabled": bool(args.enable_direct),
                    "notes": "Generated from schema; review semantics and conversions.",
                })
                if not args.enable_direct:
                    map_doc["unmapped"].append({
                        "from": field["sourcePath"],
                        "reason": "target selected but binding is disabled until direct-copy review",
                    })
            else:
                map_doc["unmapped"].append({
                    "from": field["sourcePath"],
                    "reason": "target mapping not specified",
                })
        safe_name = re.sub(r"[^a-z0-9]+", "_", message["name"].casefold()).strip("_") or "message"
        file_stem = f"msg_{message_id}_{safe_name}" if message_id is not None else safe_name
        file_stem += "_" + re.sub(r"[^a-z0-9]+", "_", args.target.casefold()).strip("_")
        mapping_file = f"{file_stem}.json"
        generated_files.append({"message": message["name"], "path": mapping_file, "document": map_doc})

    plan = {
        "apiVersion": "billie.dev/mapper-plan/v1",
        "source": {"format": format_name, "schemaPath": str(schema)},
        "sourceProtocol": source_protocol,
        "target": {"encoder": args.target},
        "messages": messages,
        "mappingFiles": [item["path"] for item in generated_files],
        "mappingsDirectory": str(mappings_dir),
        "summary": {
            "messageCount": len(messages),
            "fieldCount": field_count,
            "mappedFieldCount": 0,
            "unmappedFieldCount": field_count,
            "unresolvedFieldCount": field_count,
        },
    }
    target_fields = sum(
        1 for message in messages for field in message["fields"] if field["targetField"]
    )
    plan["summary"]["mappedFieldCount"] = target_fields
    plan["summary"]["unmappedFieldCount"] = field_count - target_fields

    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        mappings_dir.mkdir(parents=True, exist_ok=True)
        for item in generated_files:
            (mappings_dir / item["path"]).write_text(
                json.dumps(item["document"], indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        output.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as exc:
        return fail(f"cannot write {output}: {exc}", 1)

    print(f"Mapper scaffold created: {output}")
    print(f"Mapping-contract files: {mappings_dir}")
    print(f"Source format: {format_name}; target: {args.target}")
    print(f"Messages: {len(messages)}; fields: {field_count}; target fields selected: {target_fields}; unresolved: {field_count}")
    if args.enable_direct:
        print("Direct copies are enabled; verify target semantics before using them in a running kid.")
    else:
        print("Mapping-contract files are loadable but contain disabled bindings until reviewed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
