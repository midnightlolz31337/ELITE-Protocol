import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
class SchemaDraftTests(unittest.TestCase):
    def test_schema_documents_are_valid_json(self):
        files = sorted((ROOT / "schemas").glob("*.schema.json"))
        self.assertGreaterEqual(len(files), 3)
        for path in files:
            with self.subTest(path=path.name):
                schema = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(schema.get("$schema"), "https://json-schema.org/draft/2020-12/schema")
                self.assertEqual(schema.get("type"), "object")
                self.assertIn("properties", schema)
    def test_claim_separates_assessment_from_evidence_refs(self):
        schema = json.loads((ROOT / "schemas" / "claim.schema.json").read_text(encoding="utf-8"))
        self.assertIn("evidence_refs", schema["required"])
        self.assertIn("assessment", schema["required"])
if __name__ == "__main__":
    unittest.main()
