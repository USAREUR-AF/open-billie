import base64
import importlib.util
import json
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

    # The island's Zenoh REST plugin gives each payload as "value": base64 for
    # every encoding but JSON and plain text (see the comment on sample_body).
    # The bridge must forward the payload bytes, never the base64 text.

    def test_cot_xml_is_forwarded_as_xml_not_base64(self):
        cot = b'<event version="2.0" uid="J-5" type="a-u-A"><point lat="1" lon="2" hae="3" ce="4" le="5"/></event>'
        value = base64.b64encode(cot).decode("ascii")
        self.assertTrue(value.startswith("PGV2ZW50"))
        self.assertEqual(bridge.sample_body(value, "application/xml"), cot)
        self.assertEqual(bridge.sample_body(value, "text/xml"), cot)

    def test_json_object_is_reserialized(self):
        value = {"trackId": "7", "position": {"latitudeDeg": 1.5}}
        body = bridge.sample_body(value, "application/json")
        self.assertEqual(json.loads(body), value)
        # A JSON string payload arrives as a Python str and is written back as JSON.
        self.assertEqual(bridge.sample_body("hello", "application/json"), b'"hello"')

    def test_binary_sapient_and_cat062_are_decoded_from_base64(self):
        sapient = bytes(range(256))
        self.assertEqual(
            bridge.sample_body(base64.b64encode(sapient).decode("ascii"), "application/vnd.sapient.protobuf"),
            sapient,
        )
        cat062 = bytes.fromhex("3e001f9b0d1001075460100000000000000000ffce00110137810101000050")
        self.assertEqual(
            bridge.sample_body(base64.b64encode(cat062).decode("ascii"), "application/vnd.asterix.category-062"),
            cat062,
        )
        self.assertEqual(bridge.sample_body("AAEC", "application/octet-stream"), b"\x00\x01\x02")

    def test_plain_text_is_forwarded_as_text(self):
        self.assertEqual(bridge.sample_body("hello", "text/plain"), b"hello")
        self.assertEqual(bridge.sample_body("hello", "text/plain;charset=utf-8"), b"hello")
        # Valid base64 under text/plain is still text: the plugin sends text/plain as text.
        self.assertEqual(bridge.sample_body("AAEC", "text/plain"), b"AAEC")

    def test_text_that_is_not_base64_under_another_encoding_is_kept(self):
        self.assertEqual(bridge.sample_body("not-base64!", "application/octet-stream"), b"not-base64!")

    def test_an_empty_payload_is_empty(self):
        self.assertEqual(bridge.sample_body(None, "application/xml"), b"")


if __name__ == "__main__":
    unittest.main()
