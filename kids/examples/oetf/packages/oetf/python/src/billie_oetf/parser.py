"""Schema-driven byte reader for OETF frames.

A port of the TypeScript ``parser.ts``. It reads the same ``schemas/*.json``
files and must produce identical ``fields`` dicts, including the presentation
strings (``"Small UAS (3)"``, ``"152.4 m"``), so numbers are stringified
with JavaScript's ``Number.prototype.toString`` rules (see :func:`js_str`).
"""

from __future__ import annotations

import struct
from decimal import Decimal
from typing import Any

# struct format char, size, is_bigint (decoded to a decimal string like JS bigint)
_TYPES: dict[str, tuple[str, int, bool]] = {
    "uint8": ("B", 1, False), "int8": ("b", 1, False),
    "uint16": ("H", 2, False), "int16": ("h", 2, False),
    "uint32": ("I", 4, False), "int32": ("i", 4, False), "real32": ("f", 4, False),
    "uint64": ("Q", 8, True), "real64": ("d", 8, False),
}
_UINT48 = 6


def js_str(x: int | float) -> str:
    """Stringify a number exactly as JavaScript's ``String(n)`` does."""
    if isinstance(x, bool):
        x = int(x)
    if isinstance(x, int):
        return str(x)
    if x != x:
        return "NaN"
    if x in (float("inf"), float("-inf")):
        return "Infinity" if x > 0 else "-Infinity"
    if x.is_integer() and abs(x) < 1e21:
        return str(int(x))
    r = repr(x)  # shortest round-trip digits, same as JS
    if "e" not in r:
        return r
    mantissa, exp = r.split("e")
    e = int(exp)
    if -7 < e < 21:
        return format(Decimal(r), "f")
    return f"{mantissa}e{'+' if e > 0 else '-'}{abs(e)}"


def _read(frame: bytes, offset: int, typ: str, little: bool) -> int | float | str:
    order = "<" if little else ">"
    if typ == "uint48":
        b = frame[offset:offset + _UINT48]
        return int.from_bytes(b, "little" if little else "big")
    fmt, _, bigint = _TYPES[typ]
    (v,) = struct.unpack_from(order + fmt, frame, offset)
    return str(v) if bigint else v


def _size(typ: str) -> int:
    return _UINT48 if typ == "uint48" else _TYPES[typ][1]


def parse(frame: bytes, schema: dict[str, Any], little_endian: bool = True) -> dict[str, Any]:
    """Decode every field in ``schema`` from ``frame``. Mirrors ``MessageParser.parse``."""
    result: dict[str, Any] = {}
    raw_bits: dict[str, dict[str, int]] = {}
    raw_fields: dict[str, int | float] = {}

    for field in schema["fields"]:
        name = field["name"]
        valid_if = field.get("validIf")
        if valid_if:
            if "bit" in valid_if:
                parent = raw_bits.get(valid_if["field"])
                if not parent or parent.get(valid_if["bit"]) != 1:
                    result[name] = "(invalid)"
                    continue
            elif "minCount" in valid_if:
                count = raw_fields.get(valid_if["field"])
                if count is None or count < valid_if["minCount"]:
                    result[name] = "(not present)"
                    continue

        if field["offset"] + _size(field["type"]) > len(frame):
            result[name] = "(beyond message)"
            continue

        value = _read(frame, field["offset"], field["type"], little_endian)

        if field.get("bits"):
            whole = int(value)
            bits: dict[str, Any] = {}
            by_name: dict[str, int] = {}
            for b in field["bits"]:
                raw = (whole >> b["bitStart"]) & ((1 << b["length"]) - 1)
                by_name[b["name"]] = raw
                resolved: Any = raw
                if b.get("values") and str(raw) in b["values"]:
                    resolved = f"{b['values'][str(raw)]} ({raw})"
                elif b.get("valuesBy"):
                    vb = b["valuesBy"]
                    names = vb["field"] if isinstance(vb["field"], list) else [vb["field"]]
                    ctx = ".".join(str(by_name.get(n)) for n in names)
                    sub = vb["map"].get(ctx)
                    if sub and str(raw) in sub:
                        resolved = f"{sub[str(raw)]} ({raw})"
                bits[b["name"]] = resolved
            bits["_raw"] = whole
            raw_bits[name] = by_name
            result[name] = bits
            continue

        num: Any = value
        if not isinstance(value, str):
            raw_fields[name] = value
            if "scale" in field:
                num = value * field["scale"]
        values = field.get("values")
        key = num if isinstance(num, str) else js_str(num)
        if values and key in values:
            result[name] = f"{values[key]} ({key})"
        elif field.get("units"):
            result[name] = f"{key} {field['units']}"
        else:
            result[name] = num
    return result
