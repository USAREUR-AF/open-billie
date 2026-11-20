#!/usr/bin/env python3
"""Write site/assets/hero-data.json, which the landing page's first screen plays.

    python3 site/hero-data/make.py

1. Reads a conformance vector of the synthetic OETF example kid.
2. Decodes its bytes and maps each track with the kid's own Python decoder and
   mapper (kids/examples/oetf/packages/oetf/python), as
   tools/generate-oetf-mapper-tracks.py does.
3. Encodes each canonical track with the real Rust translator
   (runtime/rust/translator), through the small program beside this file.

Needs Python 3 with PyYAML and a Rust toolchain. Everything is synthetic.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "kids/examples/oetf/packages/oetf"
VECTOR = PACKAGE / "shared/conformance/vectors/track_report_two_tracks.json"
OUT = ROOT / "site/assets/hero-data.json"
sys.path.insert(0, str(PACKAGE / "python/src"))

from billie_oetf import Mapper, OetfDecoder  # noqa: E402


def main() -> int:
    here = Path(__file__).resolve().parent
    subprocess.run(["cargo", "build", "-q", "--release"], cwd=here, check=True)
    encoder = here / "target/release/landing-hero-data"
    vector = json.loads(VECTOR.read_text(encoding="utf-8"))
    raw = bytes.fromhex("".join(vector["chunks"]))
    shared = PACKAGE / "shared"
    mapper = Mapper(mappings_dir=shared / "mappings", lookup_dirs=[shared / "lookups"])
    records = OetfDecoder().feed(raw)
    tracks = []
    for record in records:
        for translated in mapper.translate("oetf", record, "billie-canonical"):
            canonical = translated["fields"]
            request = {"apiVersion": "billie.dev/translation-v1", "kind": "TranslateRequest",
                       "requestId": "landing", "kid": "oetf",
                       "target": {"outputName": "tracks", "format": "cot"}, "record": canonical}
            encoded = subprocess.run([str(encoder)], input=json.dumps(request), capture_output=True,
                                     text=True, check=True).stdout
            tracks.append({"canonical": canonical, "outputs": json.loads(encoded)})
    doc = {"vector": VECTOR.relative_to(ROOT).as_posix(), "description": vector.get("description", ""),
           "frameHex": raw.hex(), "frameLength": len(raw), "tracks": tracks}
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT).as_posix()}: {len(raw)}-byte frame, {len(tracks)} tracks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
