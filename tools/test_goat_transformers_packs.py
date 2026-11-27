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
        self.assertEqual([line.split("  ", 1)[1] for line in lines], list(SYNC.copied_names(SYNC.DESTINATION, SYNC.PACKS)))
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
        names = set(SYNC.copied_names(SYNC.DESTINATION, SYNC.PACKS))
        self.assertEqual(present, names | {"COMMIT", "SHA256SUMS", "README.md"})
        # goat_path.rs embeds what build.rs generates from SHA256SUMS, and the commit.
        source = (ROOT / "runtime/rust/translator/src/goat_path.rs").read_text(encoding="utf-8")
        self.assertIn('include!(concat!(env!("OUT_DIR"), "/goat_transformers_embedded.rs"))', source)
        included = set(re.findall(r'include_str!\(\s*"\.\./goat-transformers/([^"]+)"\s*\)', source))
        self.assertEqual(included, {"COMMIT"})

    def test_every_module_an_embedded_pack_uses_is_embedded(self):
        self.assertEqual(SYNC.missing_modules(SYNC.DESTINATION), [])

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
        names = SYNC.copied_names(SYNC.XF_INGEST_DESTINATION, SYNC.XF_INGEST_PACKS)
        self.assertEqual([line.split("  ", 1)[1] for line in lines], list(names))
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
        self.assertEqual(present, set(names) | {"COMMIT", "SHA256SUMS"})

    def test_every_module_a_copied_pack_uses_is_copied(self):
        self.assertEqual(SYNC.missing_modules(SYNC.XF_INGEST_DESTINATION), [])


class UsedModuleTests(unittest.TestCase):
    """The model modules copied are those the packs use, found from the files."""

    def tree(self, files):
        import tempfile

        root = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, root)
        for name, text in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text, encoding="utf-8")
        return root

    def test_modules_are_core_and_the_closure_of_the_packs_uses(self):
        root = self.tree(
            {
                "packs/a/pack.def": "format a\nuses cot\nuses track\n",
                "packs/b/pack.def": "format b\nuses cat062\n",
                "model/core.def": "module core\n",
                "model/cot.def": "module cot\n",
                "model/track.def": "module track\n",
                "model/cat062.def": "module cat062\nuses track\n",
                "model/radar.def": "module radar\n",
            }
        )
        self.assertEqual(
            SYNC.copied_names(root, ("b", "a")),
            ("NOTICE", "model/cat062.def", "model/core.def", "model/cot.def", "model/track.def",
             "packs/a/pack.def", "packs/b/pack.def"),
        )

    def test_a_module_a_pack_uses_and_the_copy_lacks_is_named(self):
        root = self.tree(
            {
                "packs/a/pack.def": "format a\nuses cot\nuses track\n",
                "model/core.def": "module core\n",
                "model/track.def": "module track\n",
            }
        )
        self.assertEqual(SYNC.missing_modules(root), ["packs/a/pack.def: uses cot, and model/cot.def is not copied"])


if __name__ == "__main__":
    unittest.main()
