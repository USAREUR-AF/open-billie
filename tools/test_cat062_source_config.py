#!/usr/bin/env python3
"""Focused tests for CAT062 per-source SAC/SIC configuration."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "deploy/bin/billie-cat062-sources.py"


class Cat062SourceConfigTests(unittest.TestCase):
    def run_cli(self, path: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), "--file", str(path), *args],
            check=False,
            text=True,
            capture_output=True,
        )

    def test_set_list_and_remove_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "cat062-sources.json"
            result = self.run_cli(config, "source", "set", "oetf", "sensor-a", "--sac", "4", "--sic", "20")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(config.read_text(encoding="utf-8")), {
                "kids": {"oetf": {"sources": {"sensor-a": {"sac": 4, "sic": 20}}}}
            })
            listed = self.run_cli(config, "source", "list")
            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertIn("oetf/sensor-a: SAC=4 SIC=20", listed.stdout)
            removed = self.run_cli(config, "source", "remove", "oetf", "sensor-a")
            self.assertEqual(removed.returncode, 0, removed.stderr)
            self.assertEqual(json.loads(config.read_text(encoding="utf-8")), {"kids": {}})

    def test_rejects_duplicate_pair_and_out_of_range_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "cat062-sources.json"
            self.assertEqual(self.run_cli(config, "source", "set", "oetf", "sensor-a", "--sac", "4", "--sic", "20").returncode, 0)
            duplicate = self.run_cli(config, "source", "set", "another-kid", "sensor-b", "--sac", "4", "--sic", "20")
            self.assertEqual(duplicate.returncode, 2)
            self.assertIn("shares SAC/SIC", duplicate.stderr)
            invalid = self.run_cli(config, "source", "set", "oetf", "sensor-b", "--sac", "256", "--sic", "21")
            self.assertEqual(invalid.returncode, 2)
            self.assertIn("0 to 255", invalid.stderr)

    def test_same_source_id_can_have_distinct_kid_assignments(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "cat062-sources.json"
            self.assertEqual(self.run_cli(config, "source", "set", "oetf", "sensor-a", "--sac", "4", "--sic", "20").returncode, 0)
            self.assertEqual(self.run_cli(config, "source", "set", "another-kid", "sensor-a", "--sac", "4", "--sic", "21").returncode, 0)
            listed = self.run_cli(config, "source", "list", "another-kid")
            self.assertIn("another-kid/sensor-a: SAC=4 SIC=21", listed.stdout)
            self.assertNotIn("oetf/sensor-a", listed.stdout)

    def test_legacy_global_source_map_can_be_explicitly_migrated(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "cat062-sources.json"
            config.write_text(json.dumps({"sources": {"sensor-a": {"sac": 4, "sic": 20}}}), encoding="utf-8")
            listed = self.run_cli(config, "source", "list")
            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertIn("legacy (all kids)/sensor-a", listed.stdout)
            migrated = self.run_cli(config, "source", "migrate", "oetf")
            self.assertEqual(migrated.returncode, 0, migrated.stderr)
            self.assertEqual(json.loads(config.read_text(encoding="utf-8")), {
                "kids": {"oetf": {"sources": {"sensor-a": {"sac": 4, "sic": 20}}}}
            })

    def test_legacy_global_source_map_requires_explicit_migration_before_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "cat062-sources.json"
            config.write_text(json.dumps({"sources": {"sensor-a": {"sac": 4, "sic": 20}}}), encoding="utf-8")
            result = self.run_cli(config, "source", "set", "oetf", "sensor-b", "--sac", "4", "--sic", "21")
            self.assertEqual(result.returncode, 2)
            self.assertIn("source migrate", result.stderr)

    def test_default_set_show_and_clear_preserves_source_assignments(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "cat062-sources.json"
            self.assertEqual(self.run_cli(config, "source", "set", "oetf", "sensor-a", "--sac", "4", "--sic", "20").returncode, 0)
            set_default = self.run_cli(config, "default", "set", "--sac", "9", "--sic", "9")
            self.assertEqual(set_default.returncode, 0, set_default.stderr)
            shown = self.run_cli(config, "default", "show")
            self.assertIn("SAC=9 SIC=9", shown.stdout)
            document = json.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(document["default"], {"sac": 9, "sic": 9})
            self.assertIn("oetf", document["kids"])
            cleared = self.run_cli(config, "default", "clear")
            self.assertEqual(cleared.returncode, 0, cleared.stderr)
            document = json.loads(config.read_text(encoding="utf-8"))
            self.assertNotIn("default", document)
            self.assertIn("oetf", document["kids"])

    def test_default_and_exact_assignment_must_not_share_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "cat062-sources.json"
            self.assertEqual(self.run_cli(config, "default", "set", "--sac", "4", "--sic", "20").returncode, 0)
            duplicate = self.run_cli(config, "source", "set", "oetf", "sensor-a", "--sac", "4", "--sic", "20")
            self.assertEqual(duplicate.returncode, 2)
            self.assertIn("shares SAC/SIC", duplicate.stderr)

    def test_migration_preserves_node_default(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "cat062-sources.json"
            config.write_text(json.dumps({"default": {"sac": 9, "sic": 9}, "sources": {"sensor-a": {"sac": 4, "sic": 20}}}), encoding="utf-8")
            migrated = self.run_cli(config, "source", "migrate", "oetf")
            self.assertEqual(migrated.returncode, 0, migrated.stderr)
            document = json.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(document["default"], {"sac": 9, "sic": 9})
            self.assertIn("oetf", document["kids"])

    def test_platform_release_allowlist_includes_cli_helper_and_service_map_path(self) -> None:
        builder = (ROOT / "tools/build-platform-release.sh").read_text(encoding="utf-8")
        service = (ROOT / "deploy/platform/templates/billie-translator.service.j2").read_text(encoding="utf-8")
        self.assertIn('"$ROOT/deploy/bin/billie-cat062-sources.py"', builder)
        self.assertIn("BILLIE_CAT062_SOURCE_MAP={{ billie_etc_dir }}/translator/cat062-sources.json", service)


if __name__ == "__main__":
    unittest.main()
