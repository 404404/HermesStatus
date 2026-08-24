import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class HardwareSchemaContractTests(unittest.TestCase):
    def test_filesystem_backing_ids_match_server_device_id_contract(self):
        schema = json.loads(
            (ROOT / "docs" / "migration" / "schema" / "agent-update-extension.schema.json").read_text(encoding="utf-8")
        )
        backing_ids = schema["$defs"]["filesystem"]["properties"]["backing_disk_ids"]
        self.assertEqual(
            backing_ids["items"]["pattern"],
            "^[A-Za-z0-9][A-Za-z0-9_.+-]*$",
        )


if __name__ == "__main__":
    unittest.main()
