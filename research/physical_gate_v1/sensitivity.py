"""Derive affordable-prefix sensitivities from retained observability evidence.

No physical simulation is run. The source report digest and exact simulator /
audit source hashes must match before its existing trajectories are sliced.
All six prefixes, including the reset observation alone, retain the original
sensor acquisition deduplication and finite-difference definitions.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from recursivecal_lab.inquiry import digest  # noqa: E402
from recursivecal_lab.physical_rig import CATALOG  # noqa: E402
from research.physical_gate_v1.observability import (  # noqa: E402
    AUDIT_ID, PARAMETERS, PERSISTENT_SEQUENCE, _source_hashes, _write_json,
    deduplicated_features, finite_difference_summary,
)

REPORT_ID = "recursivecal.physical-prefix-sensitivity/1"
PREFIX_COSTS = tuple(round(sum(CATALOG[name].cost for name in PERSISTENT_SEQUENCE[:length]), 12)
                     for length in range(len(PERSISTENT_SEQUENCE) + 1))
MAX_RAW_BYTES = 256 * 1024 * 1024


def _read(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key in original observability report")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError("nonfinite JSON number in original report: " + value)

    packed = path.read_bytes()
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as stream:
        raw = stream.read(MAX_RAW_BYTES + 1)
    if len(raw) > MAX_RAW_BYTES:
        raise ValueError("original observability report exceeds the decompression limit")
    report = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=nonfinite)
    resolved = path.resolve()
    source_name = str(resolved.relative_to(ROOT)) if resolved.is_relative_to(ROOT) else path.name
    return report, {"path": source_name, "file_sha256": hashlib.sha256(packed).hexdigest(),
                    "file_bytes": len(packed), "uncompressed_sha256": hashlib.sha256(raw).hexdigest(),
                    "uncompressed_bytes": len(raw)}


def _validate_original(report: dict[str, Any]) -> None:
    if (not isinstance(report, dict) or report.get("schema_version") != AUDIT_ID
            or report.get("status") != "complete"):
        raise ValueError("a completed original observability report is required")
    if digest({key: value for key, value in report.items() if key != "report_sha256"}) != report.get("report_sha256"):
        raise ValueError("original observability report digest mismatch")
    current = _source_hashes()
    if report.get("source_sha256") != current:
        mismatched = sorted(set(current) ^ set(report.get("source_sha256", {}))
                            | {name for name, value in current.items()
                               if report.get("source_sha256", {}).get(name) != value})
        raise ValueError("original audit source revision mismatch: " + ", ".join(mismatched))
    if len(report.get("runs", {})) != 1764 or len(report.get("analyses", [])) != 168:
        raise ValueError("original report is not the complete frozen 1764-trajectory, 168-analysis audit")
    if tuple(report["protocol"]["sequences"]["persistent"]) != PERSISTENT_SEQUENCE:
        raise ValueError("persistent sequence differs from the frozen protocol")


def _prefix(trajectory: dict[str, Any], length: int) -> dict[str, Any]:
    requested = list(PERSISTENT_SEQUENCE[:length])
    history = trajectory["history"][:length]
    if trajectory["requested_sequence"] != list(PERSISTENT_SEQUENCE):
        raise ValueError("prefix input is not the declared persistent trajectory")
    if [row["action"] for row in history] != requested[:len(history)]:
        raise ValueError("retained diagnostic actions differ from the requested prefix")
    result = {"initial_observation": trajectory["initial_observation"], "history": history,
              "requested_sequence": requested,
              "cost_used": round(sum(row["cost"] for row in history), 12),
              "completed_requested_sequence": len(history) == length
                  and all(row["termination"] == "completed" for row in history)}
    result["features"] = deduplicated_features(result)
    return result


def _summary(analyses: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    result = []
    for prefix, cost in enumerate(PREFIX_COSTS):
        rows = [row for row in analyses if row["mode"] == mode and row["prefix_length"] == prefix]
        spectra = np.array([row["singular_values"] for row in rows])
        ranks = {}
        for threshold in ("0.001", "0.01", "0.1", "1.0"):
            values = [row["rank_at_absolute_threshold"][threshold] for row in rows]
            ranks[threshold] = {"minimum": min(values), "maximum": max(values),
                                "counts": {str(rank): values.count(rank) for rank in sorted(set(values))}}
        result.append({"prefix_length": prefix, "requested_cost": cost,
                       "requested_sequence": list(PERSISTENT_SEQUENCE[:prefix]), "analyses": len(rows),
                       "rank_at_absolute_threshold": ranks,
                       "smallest_singular_value": {"minimum": float(spectra[:, -1].min()),
                                                   "median": float(np.median(spectra[:, -1])),
                                                   "maximum": float(spectra[:, -1].max())},
                       "unchanged_mask_analyses": sum(row["all_masks_unchanged"] for row in rows),
                       "complete_centre_prefixes": sum(row["centre_completed_requested_prefix"] for row in rows)})
    return result


def derive_prefixes(original: dict[str, Any], *, input_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return all 144 derived SVDs without modifying the retained original data."""
    began = time.monotonic()
    _validate_original(original)
    parents = [(index, row) for index, row in enumerate(original["analyses"]) if row["sequence"] == "persistent"]
    if len(parents) != 24:
        raise ValueError("expected 24 persistent analyses: 12 mode/temperature/seed combinations and two steps")
    combinations = {(row["mode"], row["temperature_C"], row["sensor_seed"]) for _, row in parents}
    if len(combinations) != 12:
        raise ValueError("unexpected mode, temperature and seed combinations")
    output: list[dict[str, Any]] = []
    full_prefix_checked = 0
    for parent_index, parent in parents:
        epsilon = parent["epsilon_fraction_of_range"]
        raw_centre = original["runs"][parent["centre_run_id"]]
        raw_pairs = {name: tuple(original["runs"][key] for key in parent["perturbation_run_ids"][name])
                     for name in PARAMETERS}
        for length, cost in enumerate(PREFIX_COSTS):
            centre = _prefix(raw_centre, length)
            pairs = {name: (_prefix(plus, length), _prefix(minus, length))
                     for name, (plus, minus) in raw_pairs.items()}
            summary = finite_difference_summary(centre, pairs, epsilon)
            if length == len(PERSISTENT_SEQUENCE):
                for field in ("range_scaled_jacobian", "range_scaled_noise_whitened_jacobian", "singular_values"):
                    if not np.allclose(np.asarray(summary[field]), np.asarray(parent[field]), rtol=1e-12, atol=1e-12):
                        raise ValueError("full-prefix derivation does not reproduce original " + field)
                if summary["rank_at_absolute_threshold"] != parent["rank_at_absolute_threshold"]:
                    raise ValueError("full-prefix ranks differ from the original report")
                full_prefix_checked += 1
            output.append({"mode": parent["mode"], "temperature_C": parent["temperature_C"],
                "sensor_seed": parent["sensor_seed"], "prefix_length": length,
                "requested_sequence": list(PERSISTENT_SEQUENCE[:length]), "requested_cost": cost,
                "centre_cost_used": centre["cost_used"],
                "centre_completed_requested_prefix": centre["completed_requested_sequence"],
                "perturbation_costs": {name: [plus["cost_used"], minus["cost_used"]] for name, (plus, minus) in pairs.items()},
                "original_analysis_index": parent_index, "centre_run_id": parent["centre_run_id"],
                "perturbation_run_ids": parent["perturbation_run_ids"],
                "centre_features": centre["features"],
                "perturbation_features": {name: [plus["features"], minus["features"]]
                                           for name, (plus, minus) in pairs.items()}, **summary})
    if len(output) != 144:
        raise AssertionError("derived prefix analysis count differs from the frozen protocol")
    sources = _source_hashes()
    sources["research/physical_gate_v1/sensitivity.py"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report = {"schema_version": REPORT_ID, "status": "complete", "source_sha256": sources,
              "original_report_sha256": original["report_sha256"],
              "original_source_sha256": original["source_sha256"],
              "input": input_metadata or {}, "new_physical_trajectories": 0,
              "protocol": {"parent_schema_version": AUDIT_ID, "prefixes": list(range(6)),
                           "prefix_costs": list(PREFIX_COSTS), "persistent_sequence": list(PERSISTENT_SEQUENCE),
                           "sensor_and_perturbation_protocol": original["protocol"],
                           "method": "Slice retained public histories at each prefix, deduplicate sensor acquisition"
                               " timestamps, and apply the original finite-difference and SVD functions.",
                           "cost_scope": "Requested prefix costs are stated separately from actual costs if a guard"
                               " prevents completion. No missing acquisition is fabricated.",
                           "scope": "Local finite-secant sensitivity of the allowed sparse observations. Full rank"
                               " does not establish global identifiability, robust estimation or adaptive reward advantage."},
              "validation": {"original_digest_valid": True, "original_sources_match": True,
                             "full_prefix_reproductions": full_prefix_checked, "expected_analyses": 144},
              "runtime": {"python": platform.python_version(), "numpy": np.__version__},
              "analyses": output, "primary_by_cost": _summary(output, "primary"),
              "smooth_auxiliary_by_cost": _summary(output, "smooth_auxiliary"),
              "elapsed_seconds": time.monotonic() - began}
    report["report_sha256"] = digest(report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    original, metadata = _read(args.input)
    report = derive_prefixes(original, input_metadata=metadata)
    _write_json(args.output, report)
    print(json.dumps({"status": report["status"], "analyses": len(report["analyses"]),
                      "new_physical_trajectories": 0, "full_prefix_reproductions": report["validation"]["full_prefix_reproductions"],
                      "elapsed_seconds": report["elapsed_seconds"], "output": str(args.output)}, sort_keys=True), flush=True)
    for row in report["primary_by_cost"]:
        print(json.dumps({"cost": row["requested_cost"], "prefix_length": row["prefix_length"],
                          "analyses": row["analyses"], "rank_at_1": row["rank_at_absolute_threshold"]["1.0"],
                          "rank_at_0_1": row["rank_at_absolute_threshold"]["0.1"],
                          "smallest_singular_value": row["smallest_singular_value"],
                          "unchanged_mask_analyses": row["unchanged_mask_analyses"]}, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
