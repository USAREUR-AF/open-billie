import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).parents[1]
OPS_PATH = ROOT / "deploy/bin/billie-kid-ops.py"
SPEC = importlib.util.spec_from_file_location("billie_kid_ops", OPS_PATH)
OPS = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(OPS)


class KidOutputFormatTests(unittest.TestCase):
    def test_shared_encoder_formats_are_accepted(self):
        outputs = [
            {"format": "cot"},
            {"format": "asterix-cat062"},
            {"format": "sapient"},
        ]
        self.assertEqual(OPS.unsupported_output_formats(outputs), [])

    def test_unknown_output_formats_are_reported(self):
        outputs = [{"format": "cot"}, {"format": "unknown-format"}]
        self.assertEqual(OPS.unsupported_output_formats(outputs), ["unknown-format"])

    def test_translator_registry_adds_and_revokes_kid_output_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            registry_path = pathlib.Path(directory) / "translator" / "kids.json"
            policy = {
                "uid": 1001,
                "outputs": [{"name": "tracks-cot", "format": "cot", "profile": None}],
            }
            OPS.update_translator_registry("oetf", policy, registry_path)
            document = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertEqual(document["schema"], "billie.translator.registry.v1")
            self.assertEqual(document["kids"]["oetf"], policy)

            OPS.update_translator_registry("other-kid", {"uid": 1002, "outputs": []}, registry_path)
            OPS.update_translator_registry("oetf", None, registry_path)
            document = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertNotIn("oetf", document["kids"])
            self.assertIn("other-kid", document["kids"])

    def test_netavark_forward_verification_matches_full_listener_tuple(self):
        rules = (
            "-A NETAVARK-DN-test -d 192.0.2.20/32 -p tcp -m tcp --dport 3401 "
            "-j DNAT --to-destination 10.88.0.42:5100"
        )
        self.assertTrue(OPS.netavark_listener_forward_present(rules, "192.0.2.20", 3401, "tcp", "10.88.0.42", 5100))
        cni_rules = rules.replace("NETAVARK-DN-", "CNI-DN-")
        self.assertTrue(OPS.netavark_listener_forward_present(cni_rules, "192.0.2.20", 3401, "tcp", "10.88.0.42", 5100))
        self.assertFalse(OPS.netavark_listener_forward_present(rules, "192.0.2.20", 3401, "tcp", "10.88.0.41", 5100))
        self.assertFalse(OPS.netavark_listener_forward_present(rules, "192.0.2.20", 3402, "tcp", "10.88.0.42", 5100))
        self.assertFalse(OPS.netavark_listener_forward_present(rules, "192.0.2.20", 3401, "udp", "10.88.0.42", 5100))

    def test_activation_cleans_before_start_then_verifies_forward(self):
        calls = []
        with (
            patch.object(OPS, "cleanup_orphaned_port_forwards", side_effect=lambda *args: calls.append("cleanup") or []),
            patch.object(OPS, "run", side_effect=lambda command, **kwargs: calls.append("start") or __import__("subprocess").CompletedProcess(command, 0, "", "")),
            patch.object(OPS, "verify_listener_port_forward", side_effect=lambda *args: calls.append("verify")),
            patch.object(OPS.shutil, "which", return_value="/usr/sbin/iptables"),
        ):
            OPS.start_kid_service_with_verified_forward(
                "billie-kid-oetf.service", "billie-kid-oetf", "192.0.2.20", 3401, "tcp", 5100
            )
        self.assertEqual(calls, ["cleanup", "start", "verify"])

    def test_inactive_ufw_cleans_previous_billie_rules_before_replacing_config(self):
        removed = []
        with (
            patch.object(OPS.shutil, "which", return_value="/usr/sbin/ufw"),
            patch.object(OPS, "run", return_value=__import__("subprocess").CompletedProcess([], 0, "Status: inactive", "")),
            patch.object(OPS, "remove_existing_listener_firewall", side_effect=lambda kid_id: removed.append(kid_id)),
        ):
            result = OPS.configure_listener_firewall("oetf", "udp", __import__("ipaddress").IPv4Address("192.0.2.20"), 3401, None, 5100)
        self.assertEqual(result, {"managed": False, "rules": []})
        self.assertEqual(removed, ["oetf"])

    def test_kid_unit_waits_for_translator_socket_and_cleans_container(self):
        unit = OPS.render_kid_systemd_unit(
            "oetf", "0.1.4", pathlib.PurePosixPath("/run/billie/translator.sock"),
            pathlib.PurePosixPath("/opt/billie/kids/oetf/run-kid.sh"), "billie-kid-oetf", "billie",
        )
        self.assertIn("StartLimitBurst=3", unit)
        self.assertIn("PartOf=billie-translator.service", unit)
        self.assertIn("ExecStartPre=/usr/bin/test -S /run/billie/translator.sock", unit)
        self.assertIn("ExecStopPost=/usr/bin/podman rm --force --ignore billie-kid-oetf", unit)
        self.assertIn("TimeoutStopSec=30", unit)

    def test_kid_unit_cleans_stale_forwards_before_every_start(self):
        unit = OPS.render_kid_systemd_unit(
            "q53-res", "0.1.1", pathlib.PurePosixPath("/run/billie/translator.sock"),
            pathlib.PurePosixPath("/opt/billie/kids/q53-res/run-kid.sh"), "billie-kid-q53-res", "billie",
            pathlib.PurePosixPath("/opt/billie/bin/billie-kid-ops.py"),
        )
        prestart = "ExecStartPre=/usr/bin/python3 /opt/billie/bin/billie-kid-ops.py prestart q53-res"
        self.assertIn(prestart, unit)
        self.assertLess(unit.index("ExecStartPre=/usr/bin/test -S"), unit.index(prestart))
        self.assertLess(unit.index(prestart), unit.index("ExecStart=/usr/bin/bash"))

    def test_prestart_removes_the_old_container_then_cleans_this_listener(self):
        calls = []
        with (
            patch.object(OPS, "require_root"),
            patch.object(OPS, "remove_stale_container", side_effect=lambda kid: calls.append(("rm", kid))),
            patch.object(OPS, "listener_binding", return_value=("127.0.0.1", 40532, "udp", 40532)),
            patch.object(OPS, "cleanup_orphaned_port_forwards", side_effect=lambda *a: calls.append(("clean",) + a) or []),
        ):
            self.assertEqual(OPS.prestart("q53-res"), 0)
        self.assertEqual(calls, [("rm", "q53-res"), ("clean", "127.0.0.1", 40532, "udp")])

    def test_prestart_fails_when_stale_forwards_remain(self):
        with (
            patch.object(OPS, "require_root"),
            patch.object(OPS, "remove_stale_container"),
            patch.object(OPS, "listener_binding", return_value=("127.0.0.1", 40532, "udp", 40532)),
            patch.object(OPS, "cleanup_orphaned_port_forwards", return_value=["could not remove stale Netavark rule"]),
            patch.object(OPS.shutil, "which", return_value="/usr/sbin/iptables"),
        ):
            self.assertEqual(OPS.prestart("q53-res"), 1)

    # The NAT table seen on a node after `billie cat062 source set` restarted the
    # translator and the kid: the rule to the removed container is first.
    STALE_NAT = (
        "-A NETAVARK-DN-1 -d 127.0.0.1/32 -p udp -m udp --dport 40532 -j DNAT --to-destination 10.88.0.10:40532\n"
        "-A NETAVARK-DN-1 -d 127.0.0.1/32 -p udp -m udp --dport 40532 -j DNAT --to-destination 10.88.0.11:40532\n"
        "-A NETAVARK-DN-1 -d 127.0.0.1/32 -p tcp -m tcp --dport 40532 -j DNAT --to-destination 10.88.0.10:40532\n"
    )

    def test_forward_targets_are_listed_in_rule_order_for_one_listener(self):
        self.assertEqual(
            OPS.listener_forward_targets(self.STALE_NAT, "127.0.0.1", 40532, "udp"),
            ["10.88.0.10:40532", "10.88.0.11:40532"],
        )

    def test_a_rule_to_a_removed_container_is_a_mismatch(self):
        targets = OPS.listener_forward_targets(self.STALE_NAT, "127.0.0.1", 40532, "udp")
        problem = OPS.forward_mismatch(targets, {"10.88.0.11"}, 40532)
        self.assertIn("10.88.0.10:40532", problem)
        self.assertIsNone(OPS.forward_mismatch(["10.88.0.11:40532"], {"10.88.0.11"}, 40532))
        self.assertIn("no DNAT rule", OPS.forward_mismatch([], {"10.88.0.11"}, 40532))
        self.assertIn("not running", OPS.forward_mismatch(["10.88.0.11:40532"], set(), 40532))

    def test_status_reports_the_mismatch_and_the_repair(self):
        completed = __import__("subprocess").CompletedProcess
        with tempfile.TemporaryDirectory() as directory:
            listener = pathlib.Path(directory) / "q53-res" / "listener.json"
            listener.parent.mkdir()
            listener.write_text("{}", encoding="utf-8")
            with (
                patch.object(OPS, "listener_binding", return_value=("127.0.0.1", 40532, "udp", 40532)),
                patch.object(OPS.shutil, "which", return_value="/usr/sbin/iptables"),
                patch.object(OPS, "run", return_value=completed([], 0, self.STALE_NAT, "")),
                patch.object(OPS, "container_ipv4_addresses", return_value={"10.88.0.11"}),
                patch("builtins.print") as printed,
            ):
                self.assertEqual(OPS.check_listener_forward("q53-res", pathlib.Path(directory)), 1)
        output = "\n".join(str(call.args[0]) for call in printed.call_args_list)
        self.assertIn("MISMATCH", output)
        self.assertIn("billie kid activate q53-res", output)

    def test_stale_container_removal_ignores_already_removed_container(self):
        with patch.object(OPS, "run") as run:
            OPS.remove_stale_container("oetf")
        run.assert_called_once_with(["podman", "rm", "--force", "--ignore", "billie-kid-oetf"], check=False)

    def test_activation_state_is_written_atomically_with_root_only_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            state_dir = pathlib.Path(directory) / "state"
            state = {"schema": "billie.kid.activation.v1", "version": "0.1.1"}
            with patch.object(OPS, "activation_state_dir", return_value=state_dir), patch.object(OPS.os, "chown"):
                OPS.write_activation_state("oetf", "active", state)
                self.assertEqual(OPS.read_activation_state("oetf", "active"), state)
            self.assertEqual((state_dir / "active.json").stat().st_mode & 0o777, 0o600)

    def test_upgrade_activates_requested_installed_version(self):
        active = {"schema": "billie.kid.activation.v1", "version": "0.1.1"}
        with (
            patch.object(OPS, "require_root"),
            patch.object(OPS, "read_activation_state", return_value=active),
            patch.object(OPS, "installed_package") as installed,
            patch.object(OPS, "run", return_value=__import__("subprocess").CompletedProcess([], 0, "", "")),
            patch.object(OPS, "activation_snapshot", return_value={"version": "0.1.1"}),
            patch.object(OPS, "activate") as activate,
        ):
            OPS.upgrade("oetf", "0.1.2", None, pathlib.Path("/run/billie"), "billie")
        installed.assert_called_once_with("oetf", "0.1.2")
        activate.assert_called_once_with("oetf", "0.1.2", None, pathlib.Path("/run/billie"), "billie")

    def test_failed_upgrade_restores_and_restarts_previous_version(self):
        active = {"schema": "billie.kid.activation.v1", "version": "0.1.1"}
        prior_snapshot = {"schema": "billie.kid.activation.v1", "version": "0.1.1"}
        with (
            patch.object(OPS, "require_root"),
            patch.object(OPS, "read_activation_state", return_value=active),
            patch.object(OPS, "installed_package"),
            patch.object(OPS, "run", return_value=__import__("subprocess").CompletedProcess([], 0, "", "")),
            patch.object(OPS, "activation_snapshot", return_value=prior_snapshot),
            patch.object(OPS, "restore_activation_snapshot") as restore,
            patch.object(OPS, "activate", side_effect=[SystemExit(2), None]) as activate,
        ):
            with self.assertRaises(SystemExit):
                OPS.upgrade("oetf", "0.1.2", None, pathlib.Path("/run/billie"), "billie")
        restore.assert_called_once_with("oetf", prior_snapshot)
        self.assertEqual(activate.call_args_list[1].args, ("oetf", "0.1.1", None, pathlib.Path("/run/billie"), "billie"))

    def test_rollback_restores_saved_version_and_switches_deployment(self):
        active = {"schema": "billie.kid.activation.v1", "version": "0.2.0"}
        previous = {"schema": "billie.kid.activation.v1", "version": "0.1.0", "runtimeDir": "/run/billie"}
        snapshot = {"schema": "billie.kid.activation.v1", "version": "0.2.0"}
        with (
            patch.object(OPS, "require_root"),
            patch.object(OPS, "read_activation_state", side_effect=[previous, active]),
            patch.object(OPS, "installed_package"),
            patch.object(OPS, "activation_snapshot", return_value=snapshot),
            patch.object(OPS, "restore_activation_snapshot") as restore,
            patch.object(OPS, "activate") as activate,
        ):
            OPS.rollback("oetf", pathlib.Path("/run/billie"), "billie")
        restore.assert_called_once_with("oetf", previous)
        activate.assert_called_once_with("oetf", "0.1.0", None, pathlib.Path("/run/billie"), "billie")


if __name__ == "__main__":
    unittest.main()
