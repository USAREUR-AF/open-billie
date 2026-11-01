"""Locations of the language-neutral OETF artifacts.

Schemas, maps and lookups are shared with the TypeScript and Rust packages —
there is exactly one copy, under ``packages/oetf/shared``. Set
``OETF_SHARED_DIR`` to point at a different ``shared`` directory (e.g. when
this package is installed outside the repo).
"""

import os
from pathlib import Path

SHARED_DIR = Path(os.environ.get("OETF_SHARED_DIR") or Path(__file__).resolve().parents[3] / "shared")
SCHEMAS_DIR = SHARED_DIR / "schemas"
MAPPINGS_DIR = SHARED_DIR / "mappings"
LOOKUPS_DIR = SHARED_DIR / "lookups"
