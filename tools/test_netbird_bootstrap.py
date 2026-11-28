#!/usr/bin/env python3
"""Check the NetBird bootstrap: the legacy source goes before APT runs, and the
repository signing key is installed only when it is the pinned key."""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

import yaml

PLAYBOOK = pathlib.Path(__file__).resolve().parents[1] / "deploy/platform/bootstrap.yml"
KEYRING = "/usr/share/keyrings/netbird-archive-keyring.gpg"


def play() -> dict:
    return yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))[0]


def leaf_tasks(tasks):
    for task in tasks or []:
        if "block" in task:
            yield from leaf_tasks(task["block"])
        else:
            yield task


def task_index(tasks: list[dict], name: str) -> int:
    names = [t.get("name") for t in tasks]
    if name not in names:
        raise AssertionError(f"bootstrap.yml has no task named {name!r}")
    return names.index(name)


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



class NetBirdSigningKeyPinTests(unittest.TestCase):
    """The key APT trusts for NetBird packages is checked against a pinned fingerprint."""

    def setUp(self):
        self.play = play()
        self.vars = self.play.get("vars") or {}
        self.top = self.play["tasks"]
        self.tasks = list(leaf_tasks(self.top))

    def test_fingerprint_is_pinned_in_full(self):
        fpr = str(self.vars.get("netbird_apt_key_fingerprint", ""))
        self.assertRegex(fpr, r"^[0-9A-F]{40}$")

    def test_every_download_is_checked(self):
        downloads = [t for t in self.tasks if "ansible.builtin.get_url" in t or "ansible.builtin.uri" in t]
        self.assertTrue(downloads)
        for task in downloads:
            args = task.get("ansible.builtin.get_url") or task.get("ansible.builtin.uri") or {}
            if args.get("checksum"):
                continue
            # The only download without a checksum is the signing key, which goes to a
            # holding path that the fingerprint check reads before anything trusts it.
            self.assertEqual(args.get("url"), "https://pkgs.netbird.io/debian/public.key", task.get("name"))
            self.assertEqual(args.get("dest"), "{{ netbird_apt_key_holding }}", task.get("name"))

    def test_key_is_held_checked_and_only_then_installed(self):
        holding = str(self.vars.get("netbird_apt_key_holding", ""))
        self.assertTrue(holding.startswith("/etc/apt/keyrings/") and holding.endswith(".unverified"), holding)
        fetch = task_index(self.tasks, "Download the NetBird repository signing key to a holding path")
        listing = task_index(self.tasks, "List the primary key fingerprints in the downloaded NetBird key")
        refuse = task_index(self.tasks, "Stop because the NetBird signing key does not match its pin")
        install = task_index(self.tasks, "Convert the verified NetBird signing key to the official APT keyring format")
        repo = task_index(self.tasks, "Configure the official NetBird APT repository")
        self.assertLess(fetch, listing)
        self.assertLess(listing, refuse)
        self.assertLess(refuse, install)
        self.assertLess(install, repo)
        argv = self.tasks[install]["ansible.builtin.command"]["argv"]
        self.assertEqual(argv[-1], "{{ netbird_apt_key_holding }}")
        self.assertIn(KEYRING, argv)
        # Nothing but the verified conversion writes the keyring APT trusts.
        for i, task in enumerate(self.tasks):
            if i != install and KEYRING in str(task.get("ansible.builtin.command", "")) + str(task.get("ansible.builtin.get_url", "")):
                self.fail(f"{task.get('name')!r} writes {KEYRING} without the fingerprint check")

    def test_anything_but_exactly_the_pinned_key_is_refused(self):
        block = self.top[task_index(self.top, "Refuse a NetBird signing key that is not the pinned one")]
        when = str(block.get("when", ""))
        self.assertIn("netbird_apt_key_listing.rc != 0", when)
        self.assertIn("netbird_apt_key_listing.stdout_lines != [netbird_apt_key_fingerprint]", when)
        inner = block["block"]
        self.assertEqual(inner[0]["ansible.builtin.file"]["state"], "absent")
        self.assertIn("ansible.builtin.fail", inner[-1])

    def listing_script(self) -> str:
        task = self.tasks[task_index(self.tasks, "List the primary key fingerprints in the downloaded NetBird key")]
        return task["ansible.builtin.shell"]

    def test_listing_prints_primary_keys_and_no_subkey(self):
        awk = re.search(r"awk -F: '([^']+)'", self.listing_script())
        self.assertIsNotNone(awk)
        one = ("pub:-:3072:1:AAAA:1::::::scESC:\nfpr:::::::::" + "A" * 40 + ":\nuid:-::::1::X::n:\n"
               "sub:-:3072:1:BBBB:1::::::e:\nfpr:::::::::" + "B" * 40 + ":\n")
        two = one + "pub:-:255:22:CCCC:1::::::scESC:\nfpr:::::::::" + "C" * 40 + ":\n"

        def primaries(text: str) -> list[str]:
            return subprocess.run(["awk", "-F:", awk.group(1)], input=text, capture_output=True, text=True, check=True).stdout.split()

        self.assertEqual(primaries(one), ["A" * 40])
        self.assertEqual(primaries(two), ["A" * 40, "C" * 40])

    @unittest.skipUnless(shutil.which("gpg") and shutil.which("bash"), "needs gpg and bash")
    def test_listing_reads_a_real_key_file(self):
        with tempfile.TemporaryDirectory() as home:
            env = {**os.environ, "GNUPGHOME": home}
            subprocess.run(["gpg", "--batch", "--passphrase", "", "--quick-gen-key", "Test <test@example.invalid>", "ed25519", "sign", "never"],
                           env=env, check=True, capture_output=True)
            fpr = subprocess.run(["gpg", "--batch", "--with-colons", "--list-keys"], env=env, check=True, capture_output=True, text=True).stdout
            fpr = [line.split(":")[9] for line in fpr.splitlines() if line.startswith("fpr:")][0]
            key = pathlib.Path(home) / "key.asc"
            key.write_bytes(subprocess.run(["gpg", "--batch", "--armor", "--export"], env=env, check=True, capture_output=True).stdout)
            script = self.listing_script().replace("{{ netbird_apt_key_holding | quote }}", str(key))
            self.assertNotIn("{{", script)
            out = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(out.stdout.split(), [fpr])


if __name__ == "__main__":
    unittest.main()
