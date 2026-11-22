"""Retain complete rig evidence losslessly and produce a browsable audit summary."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from recursivecal_lab.io import MAX_REPORT_BYTES, read_json
from recursivecal_lab.rl_environment import verify_episode_report


def compress_bytes(raw: bytes) -> bytes:
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0) as handle:
        handle.write(raw)
    return buffer.getvalue()


def full_report_metadata(raw: bytes, compressed: bytes) -> dict:
    return {"path": "validation.json.gz", "sha256": hashlib.sha256(compressed).hexdigest(),
            "uncompressed_sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(compressed), "uncompressed_size_bytes": len(raw)}


def validation_summary(report: dict, metadata: dict) -> dict:
    keys = ("model_id", "scope", "hardware_validated", "measured_data_used", "reference_method",
            "convergence_scope", "gates_fixed_before_run", "acceptance_limits", "runtime",
            "source_sha256", "source_sha256_after_audit", "gates", "passed", "smooth_maxima",
            "condition_counts", "limitations")
    summary = {"schema_version": "recursivecal.research-rig-validation-summary/1",
               "report_schema_version": report["schema_version"],
               "full_report": metadata, **{key: report[key] for key in keys},
               "smooth_case_count": len(report["smooth_cases"])}
    fields = ("name", "case", "accepted", "metrics", "checks", "error")
    summary["motion_outcomes"] = {
        group: [{key: row[key] for key in fields if key in row} for row in rows]
        for group, rows in (("healthy_profiles", report["healthy_profiles"]),
                            ("passive_support", report["passive_support"]),
                            ("power_loss", [report["power_loss"]]),
                            ("stratified_conditions", report["stratified_conditions"]))}
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation", type=Path, required=True, help="full uncompressed audit JSON")
    parser.add_argument("--rl-smoke", type=Path, required=True, help="full uncompressed RL episode JSON")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.validation.suffix != ".json" or args.rl_smoke.suffix != ".json":
        parser.error("input reports must be uncompressed .json files")
    audit = read_json(args.validation, max_bytes=MAX_REPORT_BYTES)
    episode = read_json(args.rl_smoke, max_bytes=MAX_REPORT_BYTES)
    if not audit["passed"] or not all(audit["gates"].values()):
        raise ValueError("audit gates must pass before packaging release evidence")
    if not verify_episode_report(episode)["valid"]:
        raise ValueError("RL episode does not pass its evidence verifier")
    raw = args.validation.read_bytes()
    compressed = compress_bytes(raw)
    rl_raw = args.rl_smoke.read_bytes()
    rl_compressed = compress_bytes(rl_raw)
    summary = validation_summary(audit, full_report_metadata(raw, compressed))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "validation.json.gz").write_bytes(compressed)
    (args.output / "rl-smoke.json.gz").write_bytes(rl_compressed)
    (args.output / "validation.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(args.output), "audit_bytes": len(raw),
                      "audit_gzip_bytes": len(compressed), "rl_bytes": len(rl_raw),
                      "rl_gzip_bytes": len(rl_compressed), "rl_report_sha256": episode["report_sha256"]}, indent=2))


if __name__ == "__main__":
    main()
