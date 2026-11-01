import importlib.util
import pathlib
import unittest
from types import SimpleNamespace

MODULE_PATH = pathlib.Path(__file__).parents[1] / "deploy" / "bin" / "billie-zenoh-config.py"
SPEC = importlib.util.spec_from_file_location("billie_zenoh_config", MODULE_PATH)
config = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(config)


class GoldenPathConfigTests(unittest.TestCase):
    def args(self, endpoint="tls/fabric.example.net:7447", prefix="tenant/node-1"):
        return SimpleNamespace(
            endpoint=endpoint,
            prefix=prefix,
            ca_file="unused-ca",
            client_cert_file="unused-cert",
            client_key_file="unused-key",
        )

    def test_requires_tls_endpoint_with_safe_host_syntax(self):
        for endpoint in ("tcp/fabric.example.net:7447", 'tls/fabric.example.net:7447";x'):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                config.configure(self.args(endpoint=endpoint))

    def test_requires_literal_non_path_prefix(self):
        for prefix in ("", "tenant/**", "../tenant", "tenant/../other", "tenant/./node"):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                config.configure(self.args(prefix=prefix))

    def test_rejects_out_of_range_port(self):
        with self.assertRaisesRegex(ValueError, "port"):
            config.configure(self.args(endpoint="tls/fabric.example.net:70000"))


if __name__ == "__main__":
    unittest.main()
