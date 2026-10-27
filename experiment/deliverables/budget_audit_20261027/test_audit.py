"""Linux-only contract tests. Every counter/receipt here is SYNTHETIC TEST ONLY."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import unittest

BASE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("budget_audit", BASE / "audit.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def fake_identity():
    """Not a provider/model/tokenizer selection or real measurement."""
    return {"provider": "SYNTHETIC-TEST-ONLY", "model": "SYNTHETIC-TEST-ONLY",
            "model_revision": "test", "tokenizer": "fake-test-counter", "tokenizer_revision": "test",
            "tokenizer_sha256": "0" * 64, "adapter_sha256": "1" * 64,
            "model_tokenizer_binding": "synthetic-test-fixture-only", "provenance": "unit-test-only",
            "counting_scope": audit.SCOPE, "exactness_declaration": audit.DECLARATION, "test_only": True}


class AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if platform.system() != "Linux":
            raise RuntimeError("tests must execute in pinned Linux container")
        cls.rows = audit.response_inventory(json.loads((BASE / "patch_summary.json").read_bytes()))

    def receipt(self):
        return {"schema_version": 1, "kind": "external-exact-token-counts", "caps": list(audit.CAPS),
                "identity": fake_identity(),
                "counts": [{"response_id": k, "response_sha256": v["response_sha256"], "exact_tokens": i}
                           for i, (k, v) in enumerate(self.rows.items())]}

    def test_exact_public_dimensions(self):
        self.assertEqual(len(self.rows), 9)
        self.assertEqual(self.rows["beam/replace_entire_region"]["utf8_bytes"], 19761)
        self.assertEqual(self.rows["tree/local_decision"]["lines"], 5)

    def test_hash_mismatch_rejected(self):
        receipt = self.receipt()
        receipt["counts"][0]["response_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            audit.import_receipt(receipt, self.rows, fake_identity())

    def test_boolean_and_other_noninteger_counts_rejected(self):
        for value in (True, False, -1, 1.5, "2", None):
            with self.subTest(value=value):
                receipt = self.receipt()
                receipt["counts"][0]["exact_tokens"] = value
                with self.assertRaises(ValueError):
                    audit.import_receipt(receipt, self.rows, fake_identity())

    def test_missing_identity_rejected(self):
        for key in fake_identity():
            with self.subTest(key=key):
                selected = fake_identity()
                del selected[key]
                with self.assertRaises(ValueError):
                    audit.import_receipt(self.receipt(), self.rows, selected)

    def test_identity_disagreement_rejected(self):
        selected = fake_identity()
        selected["model"] = "other-synthetic-fixture"
        with self.assertRaisesRegex(ValueError, "selected identity"):
            audit.import_receipt(self.receipt(), self.rows, selected)

    def test_omitted_and_duplicate_receipt_responses_rejected(self):
        for mode in ("omit", "duplicate", "unknown"):
            receipt = self.receipt()
            if mode == "omit":
                receipt["counts"].pop()
            elif mode == "duplicate":
                receipt["counts"].append(copy.deepcopy(receipt["counts"][0]))
            else:
                receipt["counts"][0]["response_id"] = "unknown"
            with self.assertRaises(ValueError):
                audit.import_receipt(receipt, self.rows, fake_identity())

    def test_omitted_source_response_rejected(self):
        summary = json.loads((BASE / "patch_summary.json").read_bytes())
        summary["examples"].pop()
        with self.assertRaisesRegex(ValueError, "omitted public"):
            audit.response_inventory(summary)

    def test_budget_binding(self):
        receipt = self.receipt()
        receipt["caps"] = [2048]
        with self.assertRaisesRegex(ValueError, "budget caps"):
            audit.import_receipt(receipt, self.rows, fake_identity())

    def test_fitting_and_overflow_boundaries(self):
        # Generic integer budget arithmetic, not token measurements of real files.
        for cap in audit.CAPS:
            self.assertEqual(audit.classify_cap(cap - 1, cap), "fits")
            self.assertEqual(audit.classify_cap(cap, cap), "fits")
            self.assertEqual(audit.classify_cap(cap + 1, cap), "overflow")

    def test_synthetic_receipt_never_claims_real_measurement(self):
        measured = audit.import_receipt(self.receipt(), self.rows, fake_identity())
        result = audit.build_report(self.rows, measured)
        self.assertEqual(result["status"], "blocked_unmeasured")
        self.assertIsNone(result["measurement"])
        self.assertTrue(result["synthetic_measurement_ignored"])
        self.assertTrue(all(x["exact_tokens"] is None for x in result["responses"]))
        self.assertTrue(all(x["status"] == "unmeasured" for x in result["cap_assessments"].values()))

    def test_injected_fake_counter_is_test_only(self):
        # Fixed synthetic token IDs exercise the injection contract; no size-to-token conversion.
        measurement = audit.measure_local(self.rows, fake_identity(), lambda text: [7, 9])
        result = audit.build_report(self.rows, measurement)
        self.assertFalse(result["tokenizer_measured_locally"])
        self.assertEqual(result["status"], "blocked_unmeasured")
        self.assertTrue(all(x == 2 for x in measurement["counts"].values()))

    def test_invalid_local_token_ids_rejected(self):
        for value in (5, "123", [True], [-1], [1.5]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                audit.measure_local(self.rows, fake_identity(), lambda text: value)

    def test_proxy_declaration_rejected(self):
        selected = fake_identity()
        selected["exactness_declaration"] = "chars / 4"
        with self.assertRaisesRegex(ValueError, "proxy"):
            audit.measure_local(self.rows, selected, lambda text: [1])

    def test_unmeasured_has_no_fit_claim(self):
        result = audit.build_report(self.rows)
        self.assertEqual(result["status"], "blocked_unmeasured")
        self.assertTrue(all(row["exact_tokens"] is None for row in result["responses"]))
        self.assertEqual(result["model_requests"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
