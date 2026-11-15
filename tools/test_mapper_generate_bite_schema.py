#!/usr/bin/env python3
"""Mapper-plan generation from the JSON Schema that `bite schema` prints."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD_SCHEMA = ROOT / "kids/examples/weather-station-bite/schemas/weather-station.records.schema.json"
GENERATOR = ROOT / "deploy/bin/billie-mapper-generate.py"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class BiteSchemaMapperGenerationTests(unittest.TestCase):
    def generate(self, directory: Path, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable, str(GENERATOR), "--schema", str(RECORD_SCHEMA), "--format", "bite-schema",
                "--source-protocol", "weather-station-bite", "--target", "billie-canonical",
                "--output", str(directory / "mapper-plan.json"), "--mappings-dir", str(directory / "generated"),
                *extra,
            ],
            capture_output=True, text=True, check=False,
        )

    def test_plan_lists_every_message_and_field_of_the_dictionary(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            result = self.generate(directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Source format: bite-json-schema/v1; target: billie-canonical", result.stdout)
            plan = load(directory / "mapper-plan.json")
            self.assertEqual(plan["source"]["format"], "bite-json-schema/v1")
            self.assertEqual(plan["summary"]["messageCount"], 3)
            messages = {message["name"]: message for message in plan["messages"]}
            self.assertEqual(sorted(messages), ["Heartbeat", "Observation", "Position"])
            position = messages["Position"]
            self.assertEqual(position["schemaId"], "weather-station/WX/Position")
            # Fields come in wire order, from the bit ranges.
            self.assertEqual(
                [field["sourcePath"] for field in position["fields"]],
                ["message_type", "message_length", "station_id", "latitude", "longitude", "altitude"],
            )
            latitude = position["fields"][3]
            self.assertEqual(latitude["sourceType"], "number")
            self.assertEqual(latitude["source"]["bits"], [56, 120])
            self.assertEqual(latitude["source"]["units"], "deg")
            self.assertEqual(position["fields"][2]["sourceType"], "string")
            mode = next(field for field in messages["Heartbeat"]["fields"] if field["sourcePath"] == "mode")
            self.assertEqual(mode["source"]["values"], ["Calibrating", "Idle", "Sampling"])

            mapping = load(directory / "generated" / "position_billie_canonical.json")
            self.assertEqual(mapping["source"], {"protocol": "weather-station-bite", "message": "Position"})
            self.assertEqual(mapping["mappings"], [])
            self.assertEqual(len(mapping["unmapped"]), 6)

    def test_other_json_is_rejected_as_not_a_bite_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            not_a_schema = directory / "input.json"
            not_a_schema.write_text(json.dumps({"fields": [{"name": "a", "offset": 0, "type": "uint8"}]}), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable, str(GENERATOR), "--schema", str(not_a_schema), "--format", "bite-schema",
                    "--source-protocol", "x", "--target", "billie-canonical", "--output", str(directory / "plan.json"),
                ],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("no bite JSON Schema", result.stderr)


if __name__ == "__main__":
    unittest.main()
