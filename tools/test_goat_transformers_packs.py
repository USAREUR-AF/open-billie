import hashlib
import importlib.util
from pathlib import Path
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = Path(__file__).resolve().with_name("sync_goat_transformers_packs.py")
SPEC = importlib.util.spec_from_file_location("sync_goat_transformers_packs", MODULE_PATH)
assert SPEC and SPEC.loader
SYNC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SYNC)


class GoatTransformersPackTests(unittest.TestCase):
    """Offline checks. Comparing the copy with the goat-transformers commit
    itself is `sync_goat_transformers_packs.py --check`, which needs the
    checkout Cargo makes."""

    def test_crate_lockfile_and_embedded_files_name_one_commit(self):
        revision = SYNC.pinned_revision()
        self.assertEqual((SYNC.DESTINATION / "COMMIT").read_text(encoding="ascii"), revision + "\n")
        lock = (ROOT / "runtime/rust/Cargo.lock").read_text(encoding="utf-8")
        sources = re.findall(r'name = "goat-transformers"\nversion = "[^"]+"\nsource = "([^"]+)"', lock)
        self.assertEqual(
            sources,
            [f"git+https://github.com/USAREUR-AF/goat-transformers?rev={revision}#{revision}"],
        )

    def test_embedded_files_match_their_recorded_digests(self):
        lines = (SYNC.DESTINATION / "SHA256SUMS").read_text(encoding="ascii").splitlines()
        self.assertEqual([line.split("  ", 1)[1] for line in lines], list(SYNC.FILES))
        for line in lines:
            digest, relative = line.split("  ", 1)
            with self.subTest(file=relative):
                self.assertEqual(hashlib.sha256((SYNC.DESTINATION / relative).read_bytes()).hexdigest(), digest)

    def test_no_unlisted_file_is_embedded(self):
        present = {
            path.relative_to(SYNC.DESTINATION).as_posix()
            for path in SYNC.DESTINATION.rglob("*")
            if path.is_file()
        }
        self.assertEqual(present, set(SYNC.FILES) | {"COMMIT", "SHA256SUMS", "README.md"})
        source = (ROOT / "runtime/rust/translator/src/goat_path.rs").read_text(encoding="utf-8")
        included = set(re.findall(r'include_str!\(\s*"\.\./goat-transformers/([^"]+)"\s*\)', source))
        self.assertEqual(included, (set(SYNC.FILES) - {"NOTICE"}) | {"COMMIT"})

    def test_comparison_inputs_match_the_oetf_conformance_vectors(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/generate-oetf-mapper-tracks.py"), "--check"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class XfIngestPackTests(unittest.TestCase):
    """The xf-ingest kid's copy: offline checks, as above. The comparison with
    the commit itself is `sync_goat_transformers_packs.py --target xf-ingest --check`."""

    def test_crate_lockfile_and_copied_files_name_one_commit(self):
        revision = SYNC.pinned_revision_inline(SYNC.XF_INGEST_MANIFEST, SYNC.XF_INGEST_CRATE)
        self.assertEqual((SYNC.XF_INGEST_DESTINATION / "COMMIT").read_text(encoding="ascii"), revision + "\n")
        manifest = SYNC.XF_INGEST_MANIFEST.read_text(encoding="utf-8")
        self.assertEqual(set(re.findall(r'rev = "([0-9a-f]{40})"', manifest)), {revision})
        lock = (ROOT / "kids/xf-ingest/Cargo.lock").read_text(encoding="utf-8")
        sources = set(re.findall(r'source = "(git\+https://github.com/USAREUR-AF/goat-transformers[^"]*)"', lock))
        self.assertEqual(sources, {f"git+https://github.com/USAREUR-AF/goat-transformers?rev={revision}#{revision}"})

    def test_copied_files_match_their_recorded_digests_and_nothing_else_is_copied(self):
        lines = (SYNC.XF_INGEST_DESTINATION / "SHA256SUMS").read_text(encoding="ascii").splitlines()
        self.assertEqual([line.split("  ", 1)[1] for line in lines], list(SYNC.XF_INGEST_FILES))
        for line in lines:
            digest, relative = line.split("  ", 1)
            with self.subTest(file=relative):
                data = (SYNC.XF_INGEST_DESTINATION / relative).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), digest)
        present = {
            path.relative_to(SYNC.XF_INGEST_DESTINATION).as_posix()
            for path in SYNC.XF_INGEST_DESTINATION.rglob("*")
            if path.is_file()
        }
        self.assertEqual(present, set(SYNC.XF_INGEST_FILES) | {"COMMIT", "SHA256SUMS"})


if __name__ == "__main__":
    unittest.main()
