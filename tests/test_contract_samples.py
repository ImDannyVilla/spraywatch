"""The contract's samples match the contract, and the code writes what the samples show."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import approval, db  # noqa: E402
from labels import extract, reader  # noqa: E402
from policy import policy as policy_loader  # noqa: E402

SAMPLES = ROOT / "contracts" / "samples"
CONTRACT = (ROOT / "contracts" / "README.md").read_text(encoding="utf-8")


class SamplesTest(unittest.TestCase):
    def test_the_label_reply_sample_validates_against_its_demo_label(self):
        data = json.loads((SAMPLES / "label-reply.json").read_text(encoding="utf-8"))
        source = extract.load(ROOT / "demo" / "labels" / "demofung-50wp.txt")
        label = reader.validate(data, source)
        self.assertTrue(all(fact.quote_verified for fact in label.facts))

    def test_the_queue_sample_has_the_contract_fields(self):
        data = json.loads((SAMPLES / "queue-change.json").read_text(encoding="utf-8"))
        self.assertEqual(data["schema"], approval.QUEUE_SCHEMA)
        for name in ("alert_id", "kind", "block_id", "from", "to", "reason", "spray_id", "label_id", "approver",
                     "approved_at"):
            self.assertIn(name, data)
            self.assertIn(f"`{name}`", CONTRACT)
        self.assertIn("harvest_id", data)

    def test_every_name_in_the_code_is_in_the_contract(self):
        for name in db.EVENT_KINDS + db.ALERT_KINDS + db.ALERT_STATES + db.LABEL_STATES + reader.PRODUCT_TYPES:
            self.assertIn(f"`{name}`", CONTRACT, name)
        for table in ("blocks", "labels", "label_facts", "sprays", "harvests", "crew_entries", "alerts", "events"):
            self.assertIn(f"| `{table}` |", CONTRACT, table)

    def test_every_column_is_in_the_contract(self):
        conn = db.connect(":memory:")
        for table in ("blocks", "labels", "label_facts", "sprays", "harvests", "crew_entries", "alerts", "events"):
            row = next(line for line in CONTRACT.splitlines() if line.startswith(f"| `{table}` |"))
            for column in conn.execute(f"PRAGMA table_info({table})"):
                self.assertIn(f"`{column['name']}`", row, f"{table}.{column['name']}")

    def test_the_policy_loads(self):
        policy = policy_loader.load()
        self.assertTrue(policy["approvers"])


if __name__ == "__main__":
    unittest.main()
