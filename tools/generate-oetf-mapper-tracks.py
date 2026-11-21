#!/usr/bin/env python3
"""Write the Canonical Track v2 records the OETF example produces from its conformance vectors.

The translator's encoder comparison test reads the result as inputs:
runtime/rust/translator/tests/fixtures/oetf-mapper-tracks.json. Each record is
what the synthetic OETF decoder and mapper emit for one track of one vector.

  python3 tools/generate-oetf-mapper-tracks.py            # rewrite the fixture
  python3 tools/generate-oetf-mapper-tracks.py --check    # exit 1 when it is out of date
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "kids" / "examples" / "oetf" / "packages" / "oetf"
FIXTURE = ROOT / "runtime" / "rust" / "translator" / "tests" / "fixtures" / "oetf-mapper-tracks.json"
sys.path.insert(0, str(PACKAGE / "python" / "src"))

from billie_oetf import Mapper, OetfDecoder  # noqa: E402


def render() -> str:
    shared = PACKAGE / "shared"
    mapper = Mapper(mappings_dir=shared / "mappings", lookup_dirs=[shared / "lookups"])
    tracks: dict[str, object] = {}
    for vector_path in sorted((shared / "conformance" / "vectors").glob("track_report_*.json")):
        vector = json.loads(vector_path.read_text(encoding="utf-8"))
        decoder = OetfDecoder()
        records = []
        for chunk in vector["chunks"]:
            records += decoder.feed(bytes.fromhex(chunk))
        index = 0
        for record in records:
            for translated in mapper.translate("oetf", record, "billie-canonical"):
                tracks[f"oetf-vector:{vector_path.stem}#{index}"] = translated["fields"]
                index += 1
    return json.dumps(tracks, indent=1) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="compare only; exit 1 when the fixture is out of date")
    arguments = parser.parse_args()
    rendered = render()
    if arguments.check:
        if not FIXTURE.is_file() or FIXTURE.read_text(encoding="utf-8") != rendered:
            print(f"{FIXTURE.relative_to(ROOT).as_posix()} is out of date; run tools/generate-oetf-mapper-tracks.py", file=sys.stderr)
            return 1
        return 0
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"Wrote {FIXTURE.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
