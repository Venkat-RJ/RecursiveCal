"""Lossless, content-addressed storage for full physical RL episode evidence.

Every saved report is checked by the ordinary report verifier before splitting.
Chunk addresses hash strict canonical JSON bytes, not the report's typed digest.
Loading reconstructs the original report and verifies both kinds of digest.

Foreground verification, optionally including deterministic physical replay::

    python research/physical_gate_v1/evidence.py --root runs/evidence \
        --report reports/CONTENT_SHA256.json.gz --replay
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import gzip
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from recursivecal_lab.inquiry import digest  # noqa: E402
from recursivecal_lab.rl_environment import verify_episode_report  # noqa: E402

STORAGE_ID = "recursivecal.physical-gate-evidence/1"
REFERENCE_KEY = "$evidence_ref"
SHA_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
REPORT_PATTERN = re.compile(r"reports/([0-9a-f]{64})\.json\.gz\Z")
MAX_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_CHUNKS_PER_REPORT = 10_000
MAX_REFERENCE_DEPTH = 64


def canonical_json_bytes(value: Any) -> bytes:
    """Exact JSON representation: string keys, finite numbers and no coercions."""
    def check(item: Any) -> None:
        if item is None or isinstance(item, (str, bool)):
            return
        if type(item) is int:
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) is list:
            for child in item:
                check(child)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for child in item.values():
                check(child)
            return
        raise ValueError("evidence requires strict JSON values with finite numbers and string keys")

    try:
        check(value)
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (RecursionError, UnicodeError, OverflowError) as error:
        raise ValueError("evidence cannot be encoded as strict UTF-8 JSON") from error


def _strict_load(raw: bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key in evidence")
            result[key] = value
        return result

    def invalid_number(value):
        raise ValueError("nonfinite JSON number in evidence: " + value)

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid_number)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("invalid evidence JSON") from error
    if canonical_json_bytes(value) != raw:
        raise ValueError("evidence JSON bytes are not canonical")
    return value


def _safe_path(root: Path, relative: str | Path) -> Path:
    value = str(relative)
    parts = PurePosixPath(value)
    if (not value or "\\" in value or "\x00" in value or parts.is_absolute()
            or any(part in (".", "..") for part in value.split("/"))):
        raise ValueError("evidence path must be a relative path beneath its root")
    candidate = root / value
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("evidence path escapes its root")
    return candidate


def _read_compressed(path: Path) -> bytes:
    try:
        with gzip.open(path, "rb") as stream:
            raw = stream.read(MAX_UNCOMPRESSED_BYTES + 1)
    except (OSError, EOFError) as error:
        raise ValueError(f"cannot read compressed evidence: {path.name}") from error
    if len(raw) > MAX_UNCOMPRESSED_BYTES:
        raise ValueError("evidence exceeds the bounded decompression size")
    return raw


def _atomic_compressed(root: Path, relative: str, raw: bytes) -> None:
    path = _safe_path(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path = _safe_path(root, relative)
    if path.exists():
        if _read_compressed(path) != raw:
            raise ValueError("existing evidence content does not match its address")
        return
    packed = gzip.compress(raw, compresslevel=9, mtime=0)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=".evidence-", delete=False) as stream:
            temporary = stream.name
            stream.write(packed)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def _reject_reserved_references(value: Any) -> None:
    if isinstance(value, dict):
        if REFERENCE_KEY in value:
            raise ValueError("the original report contains a reserved evidence-reference key")
        for item in value.values():
            _reject_reserved_references(item)
    elif isinstance(value, list):
        for item in value:
            _reject_reserved_references(item)


def _verify_report_digest(report: Any) -> None:
    if not isinstance(report, dict) or not isinstance(report.get("report_sha256"), str):
        raise ValueError("evidence does not contain a report digest")
    if not SHA_PATTERN.fullmatch(report["report_sha256"]):
        raise ValueError("invalid original report digest")
    if digest({key: value for key, value in report.items() if key != "report_sha256"}) != report["report_sha256"]:
        raise ValueError("original report digest mismatch")


class EvidenceStore:
    """Store complete reports using shared deterministic compressed JSON chunks."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _chunk(self, value: Any) -> dict[str, str]:
        raw = canonical_json_bytes(value)
        address = hashlib.sha256(raw).hexdigest()
        _atomic_compressed(self.root, f"chunks/{address}.json.gz", raw)
        return {REFERENCE_KEY: address}

    def save(self, report: dict[str, Any]) -> str:
        """Verify the full report, save all its fields, and return a relative path."""
        original = canonical_json_bytes(report)
        _verify_report_digest(report)
        _reject_reserved_references(report)
        checked = verify_episode_report(report)
        if not checked["valid"]:
            raise ValueError("cannot store invalid full episode report: " + ", ".join(checked["failures"]))
        body = deepcopy(report)
        verification = body["verification"]
        for comparison in verification["comparisons"]:
            for label in ("before", "after"):
                comparison[label] = self._chunk(comparison[label])
        verification["passive_hold"]["run"] = self._chunk(verification["passive_hold"]["run"])
        verification["power_loss"] = self._chunk(verification["power_loss"])
        body["session"]["diagnostics"] = [self._chunk(row) for row in body["session"]["diagnostics"]]
        # The small outer verification object can itself be shared, while its
        # per-profile chunks provide reuse when only the candidate changes.
        body["verification"] = self._chunk(verification)
        original_address = hashlib.sha256(original).hexdigest()
        envelope = {"schema_version": STORAGE_ID, "original_report_sha256": report["report_sha256"],
                    "original_canonical_json_sha256": original_address, "report": body}
        relative = f"reports/{original_address}.json.gz"
        _atomic_compressed(self.root, relative, canonical_json_bytes(envelope))
        return relative

    def manifest(self) -> list[dict[str, Any]]:
        """Inventory stored report envelopes and chunks with compressed-file hashes."""
        result = []
        for kind in ("chunks", "reports"):
            directory = _safe_path(self.root, kind)
            if not directory.exists():
                continue
            for candidate in sorted(directory.glob("*.json.gz")):
                relative = f"{kind}/{candidate.name}"
                path = _safe_path(self.root, relative)
                address = candidate.name.removesuffix(".json.gz")
                if not SHA_PATTERN.fullmatch(address):
                    raise ValueError("unexpected file name in evidence store")
                raw = _read_compressed(path)
                value = _strict_load(raw)
                raw_digest = hashlib.sha256(raw).hexdigest()
                if kind == "chunks" and raw_digest != address:
                    raise ValueError("chunk digest mismatch while building manifest")
                if kind == "reports" and (not isinstance(value, dict)
                        or value.get("original_canonical_json_sha256") != address):
                    raise ValueError("report envelope address mismatch while building manifest")
                packed = path.read_bytes()
                result.append({"path": relative, "kind": "chunk" if kind == "chunks" else "report_envelope",
                               "sha256": hashlib.sha256(packed).hexdigest(), "size_bytes": len(packed),
                               "canonical_json_sha256": raw_digest, "uncompressed_bytes": len(raw)})
        return result


def load_report(root: Path, path: str | Path) -> dict[str, Any]:
    """Reconstruct exact JSON types/values and verify chunk and original digests."""
    root = Path(root).resolve()
    relative = str(path)
    location = _safe_path(root, relative)
    matched = REPORT_PATTERN.fullmatch(relative)
    if matched is None:
        raise ValueError("report path must be reports/<canonical-content-sha256>.json.gz")
    envelope = _strict_load(_read_compressed(location))
    expected_fields = {"schema_version", "original_report_sha256", "original_canonical_json_sha256", "report"}
    if (not isinstance(envelope, dict) or set(envelope) != expected_fields
            or envelope["schema_version"] != STORAGE_ID
            or envelope["original_canonical_json_sha256"] != matched.group(1)):
        raise ValueError("invalid evidence envelope or content address")
    cached: dict[str, Any] = {}
    active: set[str] = set()

    def expand(value: Any, depth: int = 0) -> Any:
        if depth > MAX_REFERENCE_DEPTH:
            raise ValueError("evidence reference depth exceeds the limit")
        if isinstance(value, dict):
            if REFERENCE_KEY in value:
                if set(value) != {REFERENCE_KEY}:
                    raise ValueError("evidence references must be singleton objects")
                address = value[REFERENCE_KEY]
                if not isinstance(address, str) or not SHA_PATTERN.fullmatch(address):
                    raise ValueError("invalid evidence reference; only a SHA256 address is allowed")
                if address in active:
                    raise ValueError("cyclic evidence reference")
                if address not in cached:
                    if len(cached) + len(active) >= MAX_CHUNKS_PER_REPORT:
                        raise ValueError("evidence chunk count exceeds the limit")
                    chunk = _safe_path(root, f"chunks/{address}.json.gz")
                    raw = _read_compressed(chunk)
                    if hashlib.sha256(raw).hexdigest() != address:
                        raise ValueError("chunk digest mismatch")
                    active.add(address)
                    try:
                        cached[address] = expand(_strict_load(raw), depth + 1)
                    finally:
                        active.remove(address)
                return deepcopy(cached[address])
            return {key: expand(child, depth) for key, child in value.items()}
        if isinstance(value, list):
            return [expand(child, depth) for child in value]
        return value

    try:
        report = expand(envelope["report"])
        canonical_address = hashlib.sha256(canonical_json_bytes(report)).hexdigest()
        if canonical_address != envelope["original_canonical_json_sha256"]:
            raise ValueError("reconstructed report canonical content digest mismatch")
        _verify_report_digest(report)
        if report["report_sha256"] != envelope["original_report_sha256"]:
            raise ValueError("envelope and original report digests differ")
        return report
    except RecursionError as error:
        raise ValueError("evidence nesting exceeds the interpreter limit") from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--report", required=True, help="relative reports/<sha256>.json.gz path beneath root")
    parser.add_argument("--replay", action="store_true", help="also rerun the source-bound physical episode")
    args = parser.parse_args()
    try:
        report = load_report(args.root, args.report)
        checked = verify_episode_report(report)
        result = {"report": args.report, "original_report_sha256": report["report_sha256"],
                  "content_reconstructed": True, "consistency": checked, "valid": checked["valid"]}
        if args.replay and result["valid"]:
            from recursivecal_lab.evidence_replay import verify_rl_replay
            result["replay"] = verify_rl_replay(report)
            result["valid"] = result["replay"]["valid"]
    except (ValueError, OSError, KeyError, TypeError) as error:
        result = {"valid": False, "error": str(error), "report": args.report}
    print(json.dumps(result, sort_keys=True, allow_nan=False), flush=True)
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
