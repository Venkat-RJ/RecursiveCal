"""Lossless evidence storage tests, isolated from expensive physical rollouts."""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from recursivecal_lab.inquiry import digest
from research.physical_gate_v1.evidence import EvidenceStore, canonical_json_bytes, load_report


def fixture_report(identifier=1):
    # This is deliberately a storage fixture, not claimed physical evidence.
    # The full episode verifier is mocked only at the storage unit boundary.
    motion = {"trace": [{"time_s": 0.0, "value": 1}, {"time_s": 0.01, "value": 1.0}],
              "metrics": {"termination": "completed"}, "observations": [], "signed_zero": -0.0}
    report = {"schema_version": "recursivecal.physical-rl-episode/1", "fixture_identifier": identifier,
              "unicode_label": "temperature °C", "session": {"diagnostics": [{"action": "hold", **deepcopy(motion)}]},
              "verification": {"comparisons": [{"name": "open", "before": deepcopy(motion), "after": deepcopy(motion)},
                                                {"name": "close", "before": deepcopy(motion), "after": deepcopy(motion)}],
                               "passive_hold": {"static": {"holding_margin_Nm": 2.0}, "run": deepcopy(motion)},
                               "power_loss": deepcopy(motion)}, "hardware_validated": False}
    report["report_sha256"] = digest(report)
    return report


class EvidenceStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "evidence"
        self.store = EvidenceStore(self.root)

    def save_fixture(self, report):
        original = deepcopy(report)
        with patch("research.physical_gate_v1.evidence.verify_episode_report", return_value={"valid": True, "failures": []}) as check:
            relative = self.store.save(report)
        check.assert_called_once_with(original)
        self.assertEqual(report, original, "saving must not mutate the full original report")
        return relative

    def test_round_trip_preserves_all_fields_and_exact_json_types(self):
        original = fixture_report()
        relative = self.save_fixture(original)
        restored = load_report(self.root, relative)
        self.assertEqual(restored, original)
        self.assertEqual(canonical_json_bytes(restored), canonical_json_bytes(original))
        trace = restored["verification"]["comparisons"][0]["before"]["trace"]
        self.assertIs(type(trace[0]["value"]), int)
        self.assertIs(type(trace[1]["value"]), float)
        self.assertIn(b'"signed_zero":-0.0', canonical_json_bytes(restored))
        # Restored aliases are separate dictionaries, as in a normal JSON load.
        restored["verification"]["comparisons"][0]["before"]["trace"][0]["value"] = 7
        self.assertEqual(restored["verification"]["comparisons"][0]["after"]["trace"][0]["value"], 1)

    def test_shared_chunks_and_deterministic_files(self):
        first = self.save_fixture(fixture_report(1))
        before = {item["path"]: item for item in self.store.manifest()}
        packed = (self.root / first).read_bytes()
        self.assertEqual(self.save_fixture(fixture_report(1)), first)
        self.assertEqual((self.root / first).read_bytes(), packed)
        second = self.save_fixture(fixture_report(2))
        self.assertNotEqual(first, second)
        after = {item["path"]: item for item in self.store.manifest()}
        old_chunks = {name for name in before if name.startswith("chunks/")}
        new_chunks = {name for name in after if name.startswith("chunks/")}
        self.assertEqual(old_chunks, new_chunks)
        self.assertEqual(len(old_chunks), 3)  # shared motion, diagnostic, outer verification
        for name in old_chunks:
            self.assertEqual(before[name], after[name])
            raw = gzip.decompress((self.root / name).read_bytes())
            self.assertEqual(hashlib.sha256(raw).hexdigest(), Path(name).name.removesuffix(".json.gz"))
        self.assertEqual(load_report(self.root, second), fixture_report(2))

    def test_content_addresses_do_not_collapse_integer_and_float_json(self):
        integer_report = fixture_report()
        float_report = deepcopy(integer_report)
        float_report["verification"]["comparisons"][0]["before"]["trace"][0]["value"] = 1.0
        # The existing cross-language typed digest intentionally treats 1 and
        # 1.0 alike. Storage addresses must still preserve their distinct JSON.
        self.assertEqual(digest({k: v for k, v in float_report.items() if k != "report_sha256"}),
                         integer_report["report_sha256"])
        integer_path = self.save_fixture(integer_report)
        float_path = self.save_fixture(float_report)
        self.assertNotEqual(integer_path, float_path)
        self.assertEqual(canonical_json_bytes(load_report(self.root, integer_path)), canonical_json_bytes(integer_report))
        self.assertEqual(canonical_json_bytes(load_report(self.root, float_path)), canonical_json_bytes(float_report))

    def test_changed_chunk_is_rejected_before_report_use(self):
        relative = self.save_fixture(fixture_report())
        chunk = next((self.root / "chunks").glob("*.json.gz"))
        value = json.loads(gzip.decompress(chunk.read_bytes()))
        value["tampered"] = True
        chunk.write_bytes(gzip.compress(canonical_json_bytes(value), mtime=0))
        with self.assertRaisesRegex(ValueError, "chunk digest mismatch"):
            load_report(self.root, relative)

    def test_paths_and_reference_addresses_cannot_traverse(self):
        relative = self.save_fixture(fixture_report())
        for invalid in ("../outside.json.gz", "/tmp/outside.json.gz", "reports/../outside.json.gz", "reports\\outside.json.gz"):
            with self.subTest(path=invalid), self.assertRaises(ValueError):
                load_report(self.root, invalid)
        path = self.root / relative
        envelope = json.loads(gzip.decompress(path.read_bytes()))
        envelope["report"]["verification"] = {"$evidence_ref": "../outside"}
        path.write_bytes(gzip.compress(canonical_json_bytes(envelope), mtime=0))
        with self.assertRaisesRegex(ValueError, "invalid evidence reference"):
            load_report(self.root, relative)

    def test_symlink_escape_is_rejected(self):
        relative = self.save_fixture(fixture_report())
        envelope = json.loads(gzip.decompress((self.root / relative).read_bytes()))
        address = envelope["report"]["verification"]["$evidence_ref"]
        chunk = self.root / "chunks" / f"{address}.json.gz"
        outside = Path(self.temporary.name) / "outside.json.gz"
        outside.write_bytes(chunk.read_bytes())
        chunk.unlink()
        chunk.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "escapes its root"):
            load_report(self.root, relative)

    def test_invalid_full_report_and_digest_are_not_stored(self):
        report = fixture_report()
        with patch("research.physical_gate_v1.evidence.verify_episode_report", return_value={"valid": False, "failures": ["protocol"]}):
            with self.assertRaisesRegex(ValueError, "invalid full episode report"):
                self.store.save(report)
        self.assertEqual(self.store.manifest(), [])
        report["fixture_identifier"] = 9
        with self.assertRaisesRegex(ValueError, "original report digest mismatch"):
            self.store.save(report)
        self.assertEqual(self.store.manifest(), [])

    def test_loading_checks_original_digest_even_with_rehashed_envelope(self):
        original = fixture_report()
        relative = self.save_fixture(original)
        envelope = json.loads(gzip.decompress((self.root / relative).read_bytes()))
        changed = deepcopy(original)
        changed["fixture_identifier"] = 9
        envelope["report"]["fixture_identifier"] = 9
        # An attacker can recompute a storage content hash; that cannot excuse
        # a stale original report digest.
        address = hashlib.sha256(canonical_json_bytes(changed)).hexdigest()
        envelope["original_canonical_json_sha256"] = address
        altered_path = f"reports/{address}.json.gz"
        (self.root / altered_path).write_bytes(gzip.compress(canonical_json_bytes(envelope), mtime=0))
        with self.assertRaisesRegex(ValueError, "original report digest mismatch"):
            load_report(self.root, altered_path)


if __name__ == "__main__":
    unittest.main()
