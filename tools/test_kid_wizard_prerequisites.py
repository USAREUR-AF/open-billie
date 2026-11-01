#!/usr/bin/env python3
"""Guard the workstation portability and fail-fast checks of the kid wizard."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class KidWizardPrerequisiteTests(unittest.TestCase):
    def test_kid_wizard_avoids_bash_four_only_features(self):
        script = (ROOT / "tools/deploy-kid.sh").read_text(encoding="utf-8")
        self.assertNotIn("mapfile", script)
        self.assertNotIn("readarray", script)
        self.assertNotIn("${transport^^}", script)

    def test_kid_wizard_checks_noninteractive_sudo_before_build(self):
        script = (ROOT / "tools/deploy-kid.sh").read_text(encoding="utf-8")
        sudo_check = script.index("sudo -n true")
        build_step = script.index("billie-kid-build.py")
        self.assertLess(sudo_check, build_step)
        self.assertIn("sudo -n billie kid install", script)
        self.assertIn("sudo -n billie kid configure", script)
        self.assertIn("sudo -n billie kid activate", script)

    def test_credential_prompt_expands_home_directory_paths(self):
        script = (ROOT / "tools/configure-node.sh").read_text(encoding="utf-8")
        self.assertIn("'~/'*) credential_dir=\"$HOME/${credential_dir#~/}\"", script)


if __name__ == "__main__":
    unittest.main()
