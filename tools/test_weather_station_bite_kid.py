#!/usr/bin/env python3
"""Checks for the dictionary-decoded example kid."""

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
KID = ROOT / "kids/examples/weather-station-bite"
RECORD_SCHEMA = KID / "schemas/weather-station.records.schema.json"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class WeatherStationBiteKidTests(unittest.TestCase):
    def test_kid_source_validates(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "deploy/bin/billie-kid-validate.py"), str(KID)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Valid kid source: weather-station-bite@0.1.0", result.stdout)
        # `billie kid build` validates the staged package with --strict, which
        # rejects every warning except the source manifest's placeholder image.
        warnings = [line for line in result.stdout.splitlines() if line.startswith("WARNING:")]
        self.assertEqual(warnings, ["WARNING: runtime.image is a development placeholder and is not deployable"])

    def test_vector_tracks_satisfy_the_translation_request_schema(self):
        request_schema = load(ROOT / "schemas/translation-request-v1.schema.json")
        track_schema = load(ROOT / "schemas/canonical-track-v2.schema.json")
        registry = Registry().with_resources(
            (schema["$id"], Resource.from_contents(schema)) for schema in (request_schema, track_schema)
        )
        validator = Draft202012Validator(request_schema, registry=registry)
        manifest = yaml.safe_load((KID / "billie-kid.yaml").read_text(encoding="utf-8"))
        sent = 0
        for path in sorted((KID / "tests/vectors").glob("*.json")):
            vector = load(path)
            if vector["track"] is None:
                continue
            for output in manifest["interfaces"]["outputs"]:
                request = {
                    "apiVersion": "billie.dev/translation-v1",
                    "kind": "TranslateRequest",
                    "requestId": f"vector-{vector['name']}",
                    "kid": manifest["metadata"]["id"],
                    "target": {"outputName": output["name"], "format": output["format"]},
                    "record": vector["track"],
                }
                errors = [error.message for error in validator.iter_errors(request)]
                self.assertEqual(errors, [], path.name)
                sent += 1
        self.assertGreater(sent, 0)

    def test_manifest_image_and_dictionary_agree(self):
        manifest = yaml.safe_load((KID / "billie-kid.yaml").read_text(encoding="utf-8"))
        containerfile = (KID / "Containerfile").read_text(encoding="utf-8")
        declared = [f"{item['name']}:{item['format']}" for item in manifest["interfaces"]["outputs"]]
        outputs = re.search(r"^ENV BITE_KID_OUTPUTS=(\S+)$", containerfile, re.MULTILINE)
        self.assertIsNotNone(outputs)
        self.assertEqual(outputs.group(1).split(","), declared)
        self.assertIn(f"ENV BITE_KID_ID={manifest['metadata']['id']}\n", containerfile)
        dictionary_port = load(KID / "schemas/weather-station/WX/metadata.json")["port"]
        self.assertEqual([item["port"] for item in manifest["interfaces"]["inputs"]], [dictionary_port])
        self.assertIn(f"ENV BILLIE_INPUT_PORT={dictionary_port}\n", containerfile)

    def test_every_field_of_a_mapped_message_has_a_recorded_decision(self):
        schemas = load(RECORD_SCHEMA)
        for path in sorted((KID / "mappings").rglob("*.json")):
            mapping = load(path)
            source = mapping["source"]
            fields = set(schemas[f"{source['interface']}/{source['message']}"]["properties"])
            bound = {item["from"] for item in mapping["mappings"] if "from" in item and not item["from"].startswith("$")}
            omitted = {item["from"] for item in mapping["unmapped"]}
            self.assertEqual(bound | omitted, fields, path.name)
            self.assertEqual(bound & omitted, set(), path.name)


if __name__ == "__main__":
    unittest.main()
