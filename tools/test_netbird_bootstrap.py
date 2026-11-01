#!/usr/bin/env python3
"""Ensure NetBird bootstrap removes conflicting legacy source before APT."""
from __future__ import annotations

import pathlib
import unittest

PLAYBOOK = pathlib.Path(__file__).resolve().parents[1] / "deploy/platform/bootstrap.yml"


class NetBirdBootstrapTests(unittest.TestCase):
    def test_legacy_source_is_removed_before_any_apt_operation(self):
        text = PLAYBOOK.read_text(encoding="utf-8")
        remove_source = text.index("Remove the previous Billie-managed NetBird source before APT tasks")
        first_apt = text.index("ansible.builtin.apt:")
        self.assertLess(remove_source, first_apt)
        self.assertIn("path: /etc/apt/sources.list.d/netbird.list", text)

    def test_bootstrap_uses_dearmored_official_keyring_consistently(self):
        text = PLAYBOOK.read_text(encoding="utf-8")
        self.assertIn("gpg\n          - --dearmor", text)
        self.assertIn("/usr/share/keyrings/netbird-archive-keyring.gpg", text)
        self.assertIn("signed-by=/usr/share/keyrings/netbird-archive-keyring.gpg", text)
        self.assertNotIn("signed-by=/usr/share/keyrings/netbird-archive-keyring.asc", text)


if __name__ == "__main__":
    unittest.main()
