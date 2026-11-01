"""Executes the shared OETF map files (``mappings/**/*.json``) in Python.

This is the subset of the Open Billie translator mapping contract the OETF maps
(CAT-062, CoT, SAPIENT) use: ``repeats``, ``availableIf``, dotted/piped
``from``, brace multi-``to``, literal ``value``, the parametric conversions
``scale``/``offset``/``scaleOffset``/``lookup`` and the named ones in
:data:`CONVERSIONS`. Semantics — presentation stripping, JS rounding, JS
``Date`` truncation — match the TS engine so the conformance vectors pass
exactly.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from . import paths
from .decoder import DecodedRecord
from .parser import js_str

_LABELLED = re.compile(r"\((-?\d+(?:\.\d+)?)\)\s*\Z")
_UNITS = re.compile(r"\A(-?\d+(?:\.\d+)?)\s+\S+\Z")
_LOOKUP_KEY = re.compile(r"\((-?\d+)\)\s*\Z")


def _num(s: str) -> int | float:
    f = float(s)
    return int(f) if f.is_integer() and abs(f) < 2**53 else f


def strip_presentation(v: Any) -> Any:
    """``"Label (3)"`` → 3, ``"152.4 m"`` → 152.4, anything else unchanged."""
    if not isinstance(v, str):
        return v
    m = _LABELLED.search(v) or _UNITS.search(v)
    return _num(m.group(1)) if m else v


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _js_number(v: Any) -> float:
    """JS ``Number(v)`` for the inputs the time conversions accept."""
    if _is_num(v):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return math.nan


def _epoch_micros_to_cat062_tod(v: Any, _lookups: dict) -> Any:
    us = _js_number(v)
    if not math.isfinite(us):
        return v
    total_ms = us / 1000
    day_ms = math.fmod(math.fmod(total_ms, 86_400_000) + 86_400_000, 86_400_000)
    return math.floor(day_ms * 0.128 + 0.5)  # JS Math.round


def _scale(n: float) -> Callable[[Any, dict], Any]:
    return lambda v, _l: v * n if _is_num(v) else v


def _offset(n: float) -> Callable[[Any, dict], Any]:
    return lambda v, _l: v + n if _is_num(v) else v


def _scale_offset(s: float, o: float) -> Callable[[Any, dict], Any]:
    return lambda v, _l: v * s + o if _is_num(v) else v


def _lookup(table: str) -> Callable[[Any, dict], Any]:
    def run(v: Any, lookups: dict) -> Any:
        t = lookups.get(table)
        if t is None:
            return v
        key = v if isinstance(v, str) else js_str(v)
        m = _LOOKUP_KEY.search(key)
        label = t.get(m.group(1) if m else key)
        return v if label is None else label
    return run


def _epoch_micros_to_iso8601(v: Any, _lookups: dict) -> Any:
    us = _js_number(v)
    if not math.isfinite(us):
        return v
    ms = math.trunc(us / 1000)  # JS Date truncates its time value to whole ms
    d = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=ms)
    return f"{d:%Y-%m-%dT%H:%M:%S}.{d.microsecond // 1000:03d}Z"


def _epoch_micros_to_proto_timestamp(v: Any, _lookups: dict) -> Any:
    us = _js_number(v)
    if not math.isfinite(us):
        return v
    seconds = math.floor(us / 1_000_000)
    return {"seconds": seconds, "nanos": (us - seconds * 1_000_000) * 1_000}


def _uint_to_string(v: Any, _lookups: dict) -> Any:
    if _is_num(v):
        return js_str(math.trunc(v))
    return v if isinstance(v, str) else str(v)


def _number_to_string(v: Any, _lookups: dict) -> Any:
    return js_str(v) if _is_num(v) else v


def _negate(v: Any, _lookups: dict) -> Any:
    return -v if _is_num(v) else v


def _as_num(v: Any) -> float:
    """JS ``asNum``: numbers pass, strings yield their leading decimal, else NaN."""
    if _is_num(v):
        return v
    if isinstance(v, str):
        m = re.match(r"(-?\d+(?:\.\d+)?)", v)
        if m:
            return float(m.group(1))
    return math.nan


def _pair(v: Any) -> tuple[float, float] | None:
    if not isinstance(v, list) or len(v) != 2:
        return None
    x, y = (_as_num(a) for a in v)
    return None if math.isnan(x) or math.isnan(y) else (x, y)


def _speed_from_vxy(v: Any, _lookups: dict) -> Any:
    xy = _pair(v)
    return v if xy is None else math.sqrt(xy[0] * xy[0] + xy[1] * xy[1])


_RAD2DEG = 180 / math.pi


def _heading_from_vxy(v: Any, _lookups: dict) -> Any:
    xy = _pair(v)
    if xy is None:
        return v
    vx, vy = xy  # east, north
    if vx == 0 and vy == 0:
        return 0
    deg = math.fmod(math.atan2(vx, vy) * _RAD2DEG + 360, 360)
    return math.fmod(math.floor(deg + 0.5), 360)


def _to_canonical_identifier(scheme: str) -> Callable[[Any, dict], Any]:
    def convert(value: Any, _lookups: dict) -> Any:
        if _is_num(value):
            text = js_str(value)
        elif isinstance(value, str):
            text = value
        else:
            return None
        return [{"scheme": scheme, "value": text}]

    return convert


def _to_boolean(value: Any, _lookups: dict) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    return None


CONVERSIONS: dict[str, Callable[[Any, dict], Any]] = {
    "epochMicrosToCat062TimeOfDay": _epoch_micros_to_cat062_tod,
    "epochMicrosToIso8601": _epoch_micros_to_iso8601,
    "epochMicrosToProtoTimestamp": _epoch_micros_to_proto_timestamp,
    "uintToString": _uint_to_string,
    "toBoolean": _to_boolean,
    "numberToString": _number_to_string,
    "negate": _negate,
    "speedMsFromVxy": _speed_from_vxy,
    "headingDegFromVxy": _heading_from_vxy,
}


def _resolve(spec: str) -> Callable[[Any, dict], Any]:
    if spec in CONVERSIONS:
        return CONVERSIONS[spec]
    name, _, rest = spec.partition(":")
    args = rest.split(":") if rest else []
    if name == "scale" and len(args) == 1:
        return _scale(float(args[0]))
    if name == "offset" and len(args) == 1:
        return _offset(float(args[0]))
    if name == "scaleOffset" and len(args) == 2:
        return _scale_offset(float(args[0]), float(args[1]))
    if name == "lookup" and len(args) == 1:
        return _lookup(args[0])
    if name == "toCanonicalIdentifier" and len(args) == 1:
        return _to_canonical_identifier(args[0])
    raise ValueError(f"Unsupported conversion: {spec}")


def _step_spec(step: Any) -> str | None:
    """``{conversion, params}`` → registry spec string, as the TS engine's ``buildSpec``."""
    if isinstance(step, str):
        return step
    name = step.get("conversion")
    if not name or ":" in name:
        return name
    params = step.get("params")
    if params and len(params) == 1:
        (v,) = params.values()
        if not isinstance(v, (dict, list)) and v is not None:
            return f"{name}:{js_str(v) if _is_num(v) else v}"
    return name


def _targets(to: str) -> list[str]:
    brace = to.find("{")
    if brace < 0:
        return [to]
    close = to.find("}")
    inner = to[brace + 1:close if close >= 0 else None]
    return [to[:brace] + s.strip() for s in inner.split(",")]


def _read(obj: dict[str, Any], path: str) -> Any:
    if path in obj:
        return obj[path]
    cur: Any = obj
    for p in path.split("."):
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return None
    return cur


def _write(obj: dict[str, Any], path: str, value: Any) -> None:
    *parents, leaf = path.split(".")
    cur = obj
    for p in parents:
        if not isinstance(cur.get(p), dict):
            cur[p] = {}
        cur = cur[p]
    cur[leaf] = value


def _idx(name: str, n: int | None) -> str:
    return name if n is None else name.replace("{n}", str(n))


class Binding:
    def __init__(self, m: dict[str, Any]) -> None:
        self.inputs = [s for s in str(m.get("from") or "").split("|") if s]
        self.literal = m.get("value") if not self.inputs else None
        self.is_literal = "value" in m and not self.inputs
        self.outputs = _targets(m["to"])
        self.enabled = m.get("enabled", True)
        self.available_if = m.get("availableIf")
        via = m.get("via") if isinstance(m.get("via"), list) else ([m["conversion"]] if m.get("conversion") else [])
        specs = [_step_spec(s) for s in via]
        self.via = [_resolve(s) for s in specs if s and s != "none"]


class MapDoc:
    def __init__(self, doc: dict[str, Any]) -> None:
        self.source = doc["source"]
        self.target = doc["target"]
        self.enabled = doc.get("enabled", True)
        self.preserve_raw = doc.get("preserveRaw", True)
        self.repeats = doc.get("repeats")
        self.bindings = [Binding(m) for m in doc.get("mappings", [])]


class Mapper:
    """Load every map + lookup table once; translate decoded records to target field dicts."""

    def __init__(self, mappings_dir: Path | str | None = None, lookup_dirs: list[Path | str] | None = None) -> None:
        self.lookups: dict[str, dict[str, str]] = {}
        for d in lookup_dirs or [paths.LOOKUPS_DIR]:
            for p in sorted(Path(d).glob("*.json")):
                if not p.name.startswith("_"):
                    self.lookups[p.stem] = json.loads(p.read_text("utf-8"))
        self.maps: dict[tuple[str, str, str], MapDoc] = {}
        for p in sorted(Path(mappings_dir or paths.MAPPINGS_DIR).rglob("*.json")):
            if p.name.startswith("_"):
                continue
            doc = MapDoc(json.loads(p.read_text("utf-8")))
            self.maps[(doc.source["protocol"], doc.source["message"], doc.target["protocol"])] = doc

    def has_mapping(self, protocol: str, message: str, target: str) -> bool:
        return (protocol, message, target) in self.maps

    def translate(self, protocol: str, record: DecodedRecord, target: str) -> list[dict[str, Any]]:
        """Return ``[{messageName, fields, meta?}]`` — one per repeat index, or ``[]`` with no map."""
        m = self.maps.get((protocol, record.message_name, target))
        if m is None:
            return []
        if not m.repeats:
            return [self._one(m, record, None)]
        count = self._count(_read(record.fields, m.repeats["field"]), m.repeats.get("max"))
        return [self._one(m, record, n) for n in range(count)]

    @staticmethod
    def _count(raw: Any, max_: int | None) -> int:
        v = strip_presentation(raw)
        n = 0
        if _is_num(v):
            n = max(0, math.floor(v))
        elif isinstance(v, str):
            m = re.match(r"\s*([+-]?\d+)", v)
            n = max(0, int(m.group(1))) if m else 0
        return min(n, max_) if isinstance(max_, int) else n

    def _one(self, m: MapDoc, record: DecodedRecord, n: int | None) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for b in m.bindings:
            if not b.enabled:
                continue
            if b.available_if:
                got = strip_presentation(_read(record.fields, _idx(b.available_if["field"], n)))
                if got != b.available_if["equals"]:
                    continue
            if b.is_literal:
                vals = [b.literal]
            else:
                raws = [strip_presentation(_read(record.fields, _idx(i, n))) for i in b.inputs]
                if any(r is None for r in raws):
                    continue
                cur: Any = raws if len(raws) > 1 else raws[0]
                for step in b.via:
                    cur = step(cur, self.lookups)
                    if cur is None:
                        break
                if cur is None:
                    continue
                if len(b.outputs) > 1:
                    if not isinstance(cur, list):
                        continue
                    vals = cur
                else:
                    vals = [cur]
            for path, val in zip(b.outputs, vals):
                if val is not None:
                    _write(out, path, val)
        result: dict[str, Any] = {"messageName": m.target["message"], "fields": out}
        if m.preserve_raw:
            result["meta"] = {"raw": {"messageName": m.source["message"], "fields": record.fields}}
        return result
