#!/usr/bin/env python3
"""Checks for carrier-independent Open Billie sensor network configuration."""
from __future__ import annotations

import importlib.util
import ipaddress
import pathlib
import unittest

ROOT = pathlib.Path(__file__).parents[1]
MODULE_PATH = ROOT / "deploy" / "bin" / "billie-network.py"
SPEC = importlib.util.spec_from_file_location("billie_network", MODULE_PATH)
NETWORK = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(NETWORK)


class SensorNetplanTests(unittest.TestCase):
    def test_static_sensor_address_is_configured_without_carrier_or_gateway(self):
        config = NETWORK.render_netplan_config("eth0", ipaddress.ip_interface("192.0.2.20/24"))
        self.assertIn("ignore-carrier: true", config)
        self.assertIn("optional: true", config)
        self.assertIn("addresses:\n        - 192.0.2.20/24", config)
        self.assertIn("dhcp4: false", config)
        self.assertIn("dhcp6: false", config)
        self.assertNotIn("gateway", config)
        self.assertNotIn("nameserver", config)


if __name__ == "__main__":
    unittest.main()
