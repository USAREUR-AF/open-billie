"""Decode OETF hex and print translated records, one JSON line per output record.

    python -m billie_oetf 4f455446011046...                  # every target with a map
    python -m billie_oetf --to cot 4f455446011046...         # one target
    echo 4f455446... | python -m billie_oetf --to sapient    # or hex on stdin
"""

import argparse
import json
import sys

from . import Mapper, OetfDecoder

TARGETS = ("asterix-cat062", "cot", "sapient")


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m billie_oetf")
    ap.add_argument("--to", choices=(*TARGETS, "all"), default="all")
    ap.add_argument("hex", nargs="*")
    args = ap.parse_args()
    hexes = args.hex or [line.strip() for line in sys.stdin if line.strip()]
    targets = TARGETS if args.to == "all" else (args.to,)

    decoder, mapper = OetfDecoder(), Mapper()
    for h in hexes:
        for rec in decoder.feed(bytes.fromhex(h)):
            for target in targets:
                for out in mapper.translate("oetf", rec, target):
                    print(json.dumps({"source": rec.message_name, "target": target, "fields": out["fields"]}))
    for e in decoder.get_recent_errors():
        print(f"framing: {e.reason}: {e.detail}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
