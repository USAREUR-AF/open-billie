import importlib.util
from pathlib import Path
import unittest

MODULE_PATH = Path(__file__).resolve().with_name("check_public_boundary.py")
SPEC = importlib.util.spec_from_file_location("public_boundary", MODULE_PATH)
assert SPEC and SPEC.loader
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class PublicBoundaryTests(unittest.TestCase):
    def test_private_key_material_is_reported(self):
        marker = b"-----BEGIN " + b"PRIVATE KEY-----"
        self.assertIn("private key or certificate material", CHECK.content_findings(marker))

    def test_personal_checkout_path_is_reported(self):
        workstation_path = "C:" + "\\Users\\" + "someone" + "\\Desktop\\Projects\\repo"
        self.assertIn("personal workstation path", CHECK.content_findings(workstation_path.encode()))
        self.assertIn("personal workstation path", CHECK.path_findings(workstation_path + "\\file.py"))

    def test_capture_artifact_path_is_reported(self):
        self.assertIn("credential or packet-capture path", CHECK.path_findings("captures/session" + ".pcapng"))

    def test_documentation_address_is_allowed(self):
        self.assertNotIn("deployment-specific IP literal", CHECK.content_findings(b"192.0.2.20"))

    def test_dotted_subnet_mask_is_not_treated_as_a_node_address(self):
        self.assertNotIn("deployment-specific IP literal", CHECK.content_findings(b"255.255.255.0"))

    def test_private_address_is_reported_without_echoing_it(self):
        private_address = b"10.1" + b".2.3"
        self.assertIn("deployment-specific IP literal", CHECK.content_findings(private_address))

    def test_public_address_is_allowed(self):
        self.assertNotIn("deployment-specific IP literal", CHECK.content_findings(b"8.8.8.8"))

    def test_internal_downstream_product_name_is_reported(self):
        internal_name = b"pan" + b"oscope"
        self.assertIn("internal downstream product name", CHECK.content_findings(internal_name))


if __name__ == "__main__":
    unittest.main()
