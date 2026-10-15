"""Offline safeguards for the committed black-box suite, without importing the app."""

import unittest
from pathlib import Path

from ..run_all import discover
from ..scenarios import matches


class CaseTests(unittest.TestCase):
    def test_all_required_operations_are_discovered(self) -> None:
        root = Path(__file__).parent.parent / "cases"
        operations = discover(root)
        self.assertEqual(len(operations), 23)
        self.assertEqual(len({(row.method, row.path) for row in operations}), 23)
        self.assertIn(("POST", "/api/auth/login"), {(row.method, row.path) for row in operations})
        for path in root.rglob("*.py"):
            self.assertNotIn("campusclaw.", path.read_text())
            self.assertNotIn("TestClient", path.read_text())

    def test_openapi_schema_validation_rejects_invalid_values(self) -> None:
        document = {
            "components": {
                "schemas": {
                    "Synthetic": {
                        "type": "object",
                        "required": ["id", "state"],
                        "additionalProperties": False,
                        "properties": {
                            "id": {"type": "string", "format": "uuid"},
                            "state": {"enum": ["draft"]},
                        },
                    }
                }
            }
        }
        schema = {"$ref": "#/components/schemas/Synthetic"}
        valid = {"id": "00000000-0000-0000-0000-000000000001", "state": "draft"}
        self.assertTrue(matches(valid, schema, document))
        for invalid in (
            {**valid, "id": "invalid"},
            {**valid, "state": "published"},
            {**valid, "secret": "value"},
            {"id": valid["id"]},
        ):
            self.assertFalse(matches(invalid, schema, document))
        self.assertFalse(matches(True, {"type": "integer"}, {}))
        self.assertFalse(matches("x", {"type": "string", "minLength": 2}, {}))
        self.assertFalse(matches("2026-01-01", {"type": "string", "format": "date-time"}, {}))
        self.assertTrue(matches(None, {"anyOf": [{"type": "string"}, {"type": "null"}]}, {}))


if __name__ == "__main__":
    unittest.main()
