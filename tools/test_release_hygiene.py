import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().with_name("check_release_hygiene.py")
SPEC = importlib.util.spec_from_file_location("release_hygiene", MODULE_PATH)
assert SPEC and SPEC.loader
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class ReleaseHygieneTests(unittest.TestCase):
    def scan(self, files: dict[str, str]) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, contents in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(contents, encoding="utf-8")
            errors: list[str] = []
            with patch.object(CHECK, "ROOT", root):
                CHECK.check_container_bases(errors)
            return errors

    def test_accepts_exact_semver_distro_and_digest_pins(self):
        self.assertEqual(
            self.scan(
                {
                    "Containerfile": "FROM python:3.12.10-slim-bookworm\n",
                    "base.container.j2": "Image=docker.io/library/debian:12.12-slim\n",
                    "zenoh.container.j2": "Image={{ zenoh | default('docker.io/eclipse/zenoh@sha256:abc') }}\n",
                }
            ),
            [],
        )

    def test_rejects_floating_container_and_quadlet_tags(self):
        errors = self.scan(
            {
                "Containerfile": "FROM python:3.12-slim\n",
                "zenoh.container.j2": "Image=docker.io/eclipse/zenoh:latest\n",
            }
        )
        self.assertEqual(len(errors), 2)
        self.assertTrue(any("Containerfile" in error for error in errors))
        self.assertTrue(any("zenoh.container.j2" in error for error in errors))

    def test_rejects_quadlet_templates_without_a_pinned_default(self):
        errors = self.scan({"zenoh.container.j2": "Image={{ zenoh_image }}\n"})
        self.assertEqual(len(errors), 1)
        self.assertIn("explicit version default", errors[0])


if __name__ == "__main__":
    unittest.main()
