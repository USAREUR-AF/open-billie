import importlib.util
import pathlib
import unittest

MODULE_PATH = pathlib.Path(__file__).parents[1] / "deploy" / "bin" / "billie-island-bridge.py"
SPEC = importlib.util.spec_from_file_location("billie_island_bridge", MODULE_PATH)
bridge = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(bridge)


class GoldenPathBridgeTests(unittest.TestCase):
    def test_prefix_requires_scoped_literal_key(self):
        self.assertTrue(bridge.validate_prefix("tenant/node-1"))
        self.assertFalse(bridge.validate_prefix(""))
        self.assertFalse(bridge.validate_prefix("tenant/**"))
        self.assertFalse(bridge.validate_prefix("../tenant"))

    def test_local_route_is_scoped_under_prefix(self):
        bridge.PREFIX = "tenant/node-1"
        self.assertEqual(
            bridge.fabric_key("billie/oetf/tracks-cot/cot"),
            "tenant/node-1/billie/oetf/tracks-cot/cot",
        )
        self.assertEqual(bridge.fabric_key("tenant/node-1/health"), "tenant/node-1/health")

    def test_rejects_internal_and_parent_path_keys(self):
        bridge.PREFIX = "tenant/node-1"
        self.assertIsNone(bridge.fabric_key("@/router"))
        self.assertIsNone(bridge.fabric_key("../outside"))
        self.assertIsNone(bridge.fabric_key("/absolute"))
        self.assertIsNone(bridge.fabric_key("billie/*/tracks/cot"))

    def test_body_decoding_preserves_binary_and_text(self):
        self.assertEqual(bridge.sample_body("hello", "text/plain"), b"hello")
        self.assertEqual(bridge.sample_body("AAEC", "application/octet-stream"), b"\x00\x01\x02")
        with self.assertRaises(Exception):
            bridge.sample_body("not-base64!", "application/octet-stream")


if __name__ == "__main__":
    unittest.main()
