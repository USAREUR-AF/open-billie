#!/usr/bin/env python3
"""Focused checks for Billie teardown's Netavark cleanup."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "deploy" / "bin" / "billie-teardown.py"
spec = importlib.util.spec_from_file_location("billie_teardown", MODULE_PATH)
assert spec and spec.loader
teardown = importlib.util.module_from_spec(spec)
spec.loader.exec_module(teardown)


class NetavarkTeardownTests(unittest.TestCase):
    def make_rules(self, target: str = "10.88.1.218:5100"):
        return [
            ("NETAVARK-DN-test", ["-d", "192.0.2.20/32", "-p", "udp", "-m", "udp", "--dport", "5100", "-j", "DNAT", "--to-destination", target]),
            ("NETAVARK-DN-test", ["-s", "10.88.0.0/16", "-d", "192.0.2.20/32", "-p", "udp", "-m", "udp", "--dport", "5100", "-j", "NETAVARK-HOSTPORT-SETMARK"]),
            ("NETAVARK-DN-test", ["-s", "127.0.0.1/32", "-d", "192.0.2.20/32", "-p", "udp", "-m", "udp", "--dport", "5100", "-j", "NETAVARK-HOSTPORT-SETMARK"]),
            ("NETAVARK-HOSTPORT-DNAT", ["-p", "udp", "-m", "udp", "--dport", "5100", "-m", "comment", "--comment", "dnat name: podman id: old", "-j", "NETAVARK-DN-test"]),
        ]

    def fake_runner(self, rules, container_ips=()):
        chains = {chain for chain, _rule in rules if chain.startswith("NETAVARK-DN-")}

        def fake_run(args, *, check=True):
            if args[0] == "/usr/bin/podman" and args[1:] == ["ps", "--all", "--quiet"]:
                ids = "container-id\n" if container_ips else ""
                return subprocess.CompletedProcess(args, 0, ids, "")
            if args[0] == "/usr/bin/podman" and args[1] == "inspect":
                networks = {"bridge": {"IPAddress": next(iter(container_ips))}}
                data = [{"NetworkSettings": {"Networks": networks}}]
                return subprocess.CompletedProcess(args, 0, json.dumps(data), "")
            if args[:4] == ["/usr/bin/iptables", "-t", "nat", "-S"]:
                lines = ["-N " + chain for chain in sorted(chains)]
                lines.extend("-A " + chain + " " + teardown.shlex.join(rule) for chain, rule in rules)
                return subprocess.CompletedProcess(args, 0, "\n".join(lines) + "\n", "")
            if args[:4] == ["/usr/bin/iptables", "-t", "nat", "-D"]:
                chain, rule = args[4], args[5:]
                try:
                    rules.remove((chain, rule))
                except ValueError:
                    return subprocess.CompletedProcess(args, 1, "", "rule not found")
                return subprocess.CompletedProcess(args, 0, "", "")
            if args[:4] == ["/usr/bin/iptables", "-t", "nat", "-X"]:
                chains.discard(args[4])
                return subprocess.CompletedProcess(args, 0, "", "")
            raise AssertionError(f"unexpected command: {args}")

        return fake_run

    def run_cleanup(self, rules, bindings, container_ips=(), *, all_orphaned=True):
        with patch.object(teardown.shutil, "which", side_effect=lambda name: f"/usr/bin/{name}"), patch.object(teardown, "run", side_effect=self.fake_runner(rules, container_ips)):
            return teardown.remove_stale_netavark_forwards(bindings, "/usr/bin/podman", all_orphaned=all_orphaned)

    def test_removes_stale_exact_listener_and_orphan_dispatch(self):
        rules = self.make_rules()
        self.assertEqual(self.run_cleanup(rules, {("192.0.2.20", 5100, "udp")}), [])
        self.assertEqual(rules, [])

    def test_preserves_forward_to_an_existing_container(self):
        rules = self.make_rules()
        self.assertEqual(self.run_cleanup(rules, {("192.0.2.20", 5100, "udp")}, {"10.88.1.218"}), [])
        self.assertEqual(len(rules), 4)

    def test_removes_stale_rules_when_listener_metadata_is_gone(self):
        rules = self.make_rules()
        self.assertEqual(self.run_cleanup(rules, set()), [])
        self.assertEqual(rules, [])

    def test_scoped_cleanup_leaves_other_orphaned_listener_untouched(self):
        rules = self.make_rules()
        other = [
            ("NETAVARK-DN-other", ["-d", "198.51.100.21/32", "-p", "tcp", "-m", "tcp", "--dport", "5200", "-j", "DNAT", "--to-destination", "10.88.1.219:5100"]),
            ("NETAVARK-DN-other", ["-s", "10.88.0.0/16", "-d", "198.51.100.21/32", "-p", "tcp", "-m", "tcp", "--dport", "5200", "-j", "NETAVARK-HOSTPORT-SETMARK"]),
            ("NETAVARK-HOSTPORT-DNAT", ["-p", "tcp", "-m", "tcp", "--dport", "5200", "-m", "comment", "--comment", "dnat name: other id: old", "-j", "NETAVARK-DN-other"]),
        ]
        rules.extend(other)
        self.assertEqual(
            self.run_cleanup(rules, {("192.0.2.20", 5100, "udp")}, all_orphaned=False),
            [],
        )
        self.assertEqual(rules, other)

    def test_parses_quadlet_publish_port(self):
        self.assertEqual(teardown._parse_quadlet_publish_port("127.0.0.1:7447:7447/tcp"), ("127.0.0.1", 7447, "tcp"))
        self.assertEqual(teardown._parse_quadlet_publish_port("192.0.2.20:5100:5100/udp"), ("192.0.2.20", 5100, "udp"))
        self.assertIsNone(teardown._parse_quadlet_publish_port("0.0.0.0:70000:80/tcp"))

    def test_does_not_match_other_bindings_or_ports(self):
        chain, rule = self.make_rules()[0]
        self.assertFalse(teardown._matches_netavark_dnat(chain, rule, "198.51.100.21", 5100, "udp"))
        self.assertFalse(teardown._matches_netavark_dnat(chain, rule, "192.0.2.20", 5101, "udp"))
        self.assertFalse(teardown._matches_netavark_dnat(chain, rule, "192.0.2.20", 5100, "tcp"))


if __name__ == "__main__":
    unittest.main()
