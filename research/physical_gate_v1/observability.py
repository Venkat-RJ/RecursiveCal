"""Bounded observation-contract audit for the frozen version 3 physical task.

This is a local sensitivity and structural-symmetry study, not proof of global
identifiability. The primary study retains the real noisy, quantized, delayed
instrument pipeline and feedback controller. A separately labelled auxiliary
study removes sensor noise and quantization while retaining acquisition timing.

Run in the foreground from the repository root::

    python research/physical_gate_v1/observability.py --output runs/observability.json.gz

The complete public measurements and finite-difference vectors are retained.
No evaluator state enters the sensitivity feature vector.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from recursivecal_lab.inquiry import (  # noqa: E402
    VERIFICATION_PROFILES, digest, public_measurement, public_result,
)
from recursivecal_lab.physical_rig import (  # noqa: E402
    CATALOG, OBSERVATION_FIELDS, Calibration, RigState, run_experiment, run_motion,
)
from recursivecal_lab.research_rig import ResearchRig, SensorParameters  # noqa: E402
from recursivecal_lab.rl_environment import PARAMETER_BOUNDS, _profile_quality  # noqa: E402

AUDIT_ID = "recursivecal.physical-observability-pilot/1"
PARAMETERS = tuple(asdict(Calibration()))
CENTRE = Calibration(27.0, 0.85, 0.95, 8.0, 0.0)
TEMPERATURES = (10.0, 22.5, 35.0)
SENSOR_SEEDS = (101, 211, 307)
PRIMARY_EPSILONS = (0.05, 0.025)
AUXILIARY_EPSILONS = (0.01, 0.005)
SINGULAR_THRESHOLDS = (0.001, 0.01, 0.1, 1.0)
SYMMETRY_TOLERANCE = 1e-10
PERSISTENT_SEQUENCE = ("hold", "high_sweep", "low_sweep", "reference", "coast")
SEQUENCES = {**{name: (name,) for name in CATALOG}, "persistent": PERSISTENT_SEQUENCE}
DEFAULT_SENSORS = SensorParameters()
AUXILIARY_SENSORS = replace(
    DEFAULT_SENSORS, angle_resolution_rad=0.0, velocity_resolution_rad_s=0.0,
    force_resolution_N=0.0, angle_noise_std_rad=0.0,
    velocity_noise_std_rad_s=0.0, force_noise_std_N=0.0,
)
RANGES = np.array([PARAMETER_BOUNDS[name][1] - PARAMETER_BOUNDS[name][0]
                   for name in PARAMETERS], dtype=float)
CHANNEL_SCALES = np.sqrt(np.array([
    DEFAULT_SENSORS.angle_noise_std_rad**2 + DEFAULT_SENSORS.angle_resolution_rad**2 / 12,
    DEFAULT_SENSORS.velocity_noise_std_rad_s**2 + DEFAULT_SENSORS.velocity_resolution_rad_s**2 / 12,
    DEFAULT_SENSORS.force_noise_std_N**2 + DEFAULT_SENSORS.force_resolution_N**2 / 12,
]))


class ResourceLimit(RuntimeError):
    """The declared elapsed-time cap was reached; completed cases are saved."""


def _write_json(path: str | Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    if path.suffix == ".gz":
        raw = gzip.compress(raw, mtime=0)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, path)


def _source_hashes() -> dict[str, str]:
    names = ["research/physical_gate_v1/observability.py", "recursivecal_lab/physics.py",
             "recursivecal_lab/physical_rig.py", "recursivecal_lab/research_rig.py",
             "recursivecal_lab/inquiry.py", "recursivecal_lab/rl_environment.py"]
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}


def _acquisition_key(row: dict[str, Any]) -> str:
    # The clock is continuous across fixture operations. Rounding only merges
    # floating representation differences far below the minimum 5 ms period.
    return format(float(row["sensor_sample_time_s"]), ".12f")


def deduplicated_features(trajectory: dict[str, Any]) -> dict[str, Any]:
    """Use each sensor acquisition once, including the useful reset acquisition."""
    measurements = [("initial", trajectory["initial_observation"])]
    for index, record in enumerate(trajectory["history"]):
        measurements.append((f"history/{index}/start", record["start_observation"]))
        measurements.extend((f"history/{index}/observations/{j}", sample)
                            for j, sample in enumerate(record["observations"]))
        measurements.append((f"history/{index}/final", record["final_observation"]))
    acquired: dict[str, dict[str, Any]] = {}
    duplicate_count = 0
    for source, sample in measurements:
        key = _acquisition_key(sample)
        values = [float(sample[name]) for name in OBSERVATION_FIELDS]
        if key in acquired:
            if any(abs(a - b) > 1e-10 for a, b in zip(acquired[key]["values"], values)):
                raise ValueError("one labelled acquisition has inconsistent sensor values")
            acquired[key]["sources"].append(source)
            duplicate_count += 1
            continue
        acquired[key] = {"sensor_sample_time_s": sample["sensor_sample_time_s"],
                         "first_read_time_s": sample["time_s"],
                         "sensor_age_s": sample["sensor_age_s"], "values": values,
                         "sources": [source]}
    keys = sorted(acquired, key=float)
    return {"acquisition_keys": keys, "acquisitions": [acquired[key] for key in keys],
            "vector": [value for key in keys for value in acquired[key]["values"]],
            "fields": list(OBSERVATION_FIELDS), "duplicate_reads_removed": duplicate_count,
            "feature_keys": [f"{key}/{field}" for key in keys for field in OBSERVATION_FIELDS]}


def public_trajectory(calibration: Calibration, *, temperature_C: float, sensor_seed: int,
                      sequence: tuple[str, ...], sensors: SensorParameters = DEFAULT_SENSORS,
                      side_effectiveness: tuple[float, float] = (1.0, 1.0),
                      check_budget: Callable[[], None] | None = None) -> dict[str, Any]:
    """Execute actual persistent experiments and retain only public results.

    No private traces are requested. Stop after a diagnostic guard, as the
    environment does. This helper does not fabricate a reset between actions.
    """
    if len(sequence) > 5 or sum(CATALOG[name].cost for name in sequence) > 8.0 + 1e-12:
        raise ValueError("audit sequence exceeds the frozen five-test, eight-unit contract")
    rig = ResearchRig(replace(calibration.model(), temperature_C=temperature_C), seed=sensor_seed,
                      state=RigState(), sensors=sensors, side_effectiveness=side_effectiveness)
    initial = public_measurement(rig.observe())
    measurement, history = initial, []
    for action in sequence:
        if check_budget is not None:
            check_budget()
        result = public_result(run_experiment(rig, action, measurement, noisy=True, include_truth=False))
        history.append({"action": action, "cost": CATALOG[action].cost,
                        "start_observation": measurement, **result})
        measurement = result["final_observation"]
        if result["termination"] != "completed":
            break
    body = {"initial_observation": initial, "history": history,
            "requested_sequence": list(sequence), "cost_used": sum(row["cost"] for row in history),
            "completed_requested_sequence": len(history) == len(sequence)
                and all(row["termination"] == "completed" for row in history)}
    body["features"] = deduplicated_features(body)
    return body


def _event_signature(trajectory: dict[str, Any]) -> list[Any]:
    return [[row["action"], row["termination"], [event["type"] for event in row["events"]]]
            for row in trajectory["history"]]


def _matrix_summary(matrix: np.ndarray) -> dict[str, Any]:
    if matrix.ndim != 2 or matrix.shape[1] != len(PARAMETERS) or not np.all(np.isfinite(matrix)):
        raise ValueError("invalid finite-difference matrix")
    if matrix.shape[0] == 0:
        raise ValueError("no common public acquisitions for finite differences")
    _, values, right = np.linalg.svd(matrix, full_matrices=False)
    # There are always at least three reset channels. Pad right null vectors
    # when a truncated trajectory supplies fewer rows than parameters.
    if matrix.shape[0] < len(PARAMETERS):
        _, values, right = np.linalg.svd(matrix, full_matrices=True)
        values = np.pad(values, (0, len(PARAMETERS) - len(values)))
    norms = np.linalg.norm(matrix, axis=0)
    correlations: list[list[float | None]] = []
    for i in range(len(PARAMETERS)):
        correlations.append([float(np.dot(matrix[:, i], matrix[:, j]) / (norms[i] * norms[j]))
                             if norms[i] > 0 and norms[j] > 0 else None
                             for j in range(len(PARAMETERS))])
    smallest = float(values[-1])
    condition = float(values[0] / smallest) if smallest > 0 else None
    return {"singular_values": values.tolist(),
            "rank_at_absolute_threshold": {str(threshold): int(np.sum(values > threshold))
                                            for threshold in SINGULAR_THRESHOLDS},
            "condition_number": condition, "condition_is_infinite": smallest == 0,
            "column_norms": dict(zip(PARAMETERS, norms.tolist())),
            "column_cosine_correlations": correlations,
            "weakest_right_singular_vector": dict(zip(PARAMETERS, right[-1].tolist())),
            "right_singular_vectors": right.tolist()}


def finite_difference_summary(centre: dict[str, Any], pairs: dict[str, tuple[dict[str, Any], dict[str, Any]]],
                              epsilon: float) -> dict[str, Any]:
    """Central secants aligned on acquisition identity, without padding stops."""
    common = set(centre["features"]["feature_keys"])
    full_keys = centre["features"]["feature_keys"]
    for plus, minus in pairs.values():
        common.intersection_update(plus["features"]["feature_keys"], minus["features"]["feature_keys"])
    keys = [key for key in full_keys if key in common]
    matrix, perturbations, changes = [], {}, {}
    for name, width in zip(PARAMETERS, RANGES):
        plus, minus = pairs[name]
        p = dict(zip(plus["features"]["feature_keys"], plus["features"]["vector"]))
        m = dict(zip(minus["features"]["feature_keys"], minus["features"]["vector"]))
        # Divide by 2*epsilon because columns are derivatives with respect to
        # one full declared parameter range, not one native-unit parameter.
        matrix.append([(p[key] - m[key]) / (2 * epsilon) for key in keys])
        perturbations[name] = float(epsilon * width)
        changes[name] = {
            "event_or_termination_mask_changed": _event_signature(plus) != _event_signature(minus)
                or _event_signature(plus) != _event_signature(centre),
            "acquisition_mask_changed": plus["features"]["feature_keys"] != full_keys
                or minus["features"]["feature_keys"] != full_keys,
            "plus_event_signature": _event_signature(plus), "minus_event_signature": _event_signature(minus),
        }
    scaled = np.asarray(matrix, dtype=float).T
    # Every acquisition supplies all three channels, in this exact order.
    sigma = np.array([CHANNEL_SCALES[OBSERVATION_FIELDS.index(key.rsplit("/", 1)[1])] for key in keys])
    whitened = scaled / sigma[:, None]
    result = _matrix_summary(whitened)
    result.update({"epsilon_fraction_of_range": epsilon, "native_parameter_half_steps": perturbations,
                   "feature_keys": keys, "common_feature_count": len(keys),
                   "centre_feature_count": len(full_keys),
                   "range_scaled_jacobian": scaled.tolist(),
                   "range_scaled_noise_whitened_jacobian": whitened.tolist(),
                   "changes": changes,
                   "all_masks_unchanged": not any(item["event_or_termination_mask_changed"]
                       or item["acquisition_mask_changed"] for item in changes.values()),
                   "interpretation": "Finite secant sensitivity, not a global-identifiability guarantee."
                       " Changed masks or quantization preclude a smooth-derivative claim."})
    return result


def _compare(left: Any, right: Any, *, tolerance: float = SYMMETRY_TOLERANCE) -> dict[str, Any]:
    max_difference, largest_path, differences = 0.0, "", []

    def visit(a: Any, b: Any, path: str) -> None:
        nonlocal max_difference, largest_path
        if isinstance(a, bool) or isinstance(b, bool):
            if type(a) is not type(b) or a != b:
                differences.append(path)
        elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
            delta = abs(float(a) - float(b))
            if delta > max_difference:
                max_difference, largest_path = delta, path
            if delta > tolerance:
                differences.append(path)
        elif isinstance(a, dict) and isinstance(b, dict):
            if set(a) != set(b):
                differences.append(path + "/keys")
            for key in sorted(set(a) & set(b)):
                visit(a[key], b[key], path + "/" + key)
        elif isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                differences.append(path + "/length")
            for index, (x, y) in enumerate(zip(a, b)):
                visit(x, y, path + f"/{index}")
        elif a != b:
            differences.append(path)

    visit(left, right, "")
    return {"equal_within_tolerance": not differences, "absolute_tolerance": tolerance,
            "maximum_numeric_difference": max_difference, "maximum_difference_path": largest_path,
            "difference_count": len(differences), "first_difference_paths": differences[:20]}


def _terminal_profiles(calibration: Calibration, sides: tuple[float, float], *,
                       check_budget: Callable[[], None]) -> dict[str, Any]:
    """Same fixed common controller and paired sensor seeds in all four profiles."""
    rows = []
    for index, (name, start, target, profile, duration, temperature) in enumerate(VERIFICATION_PROFILES):
        check_budget()
        rig = ResearchRig(replace(calibration.model(), temperature_C=temperature), seed=90101 + index,
                          state=RigState(angle_rad=math.radians(start)), side_effectiveness=sides)
        result = run_motion(rig, start_angle_rad=math.radians(start), target_angle_rad=math.radians(target),
                            duration_s=duration, profile_s=profile, calibration=CENTRE,
                            noisy=True, include_truth=False)
        rows.append({"name": name, "quality": _profile_quality(result),
                     "metrics": result["metrics"], "public": public_result(result)})
    return {"fixed_controller": asdict(CENTRE), "profiles": rows,
            "mean_quality": sum(row["quality"] for row in rows) / len(rows)}


def symmetry_audit(*, check_budget: Callable[[], None], progress: Callable[[str], None]) -> dict[str, Any]:
    specifications = {
        "side_permutation": ((CENTRE, (0.55, 0.95)), (CENTRE, (0.95, 0.55))),
        "same_motor_products": ((CENTRE, (0.6, 1.0)),
                                (replace(CENTRE, motor_efficiency=1.0), (0.51, 0.85))),
    }
    result: dict[str, Any] = {}
    for name, worlds in specifications.items():
        public_pairs, terminal_pairs = [], []
        for calibration, sides in worlds:
            public_pairs.append({sequence_name: public_trajectory(
                calibration, temperature_C=22.5, sensor_seed=101, sequence=sequence,
                side_effectiveness=sides, check_budget=check_budget)
                for sequence_name, sequence in SEQUENCES.items()})
            terminal_pairs.append(_terminal_profiles(calibration, sides, check_budget=check_budget))
        public_check, terminal_check = _compare(*public_pairs), _compare(*terminal_pairs)
        result[name] = {
            "worlds": [{"calibration_parameters": asdict(calibration), "side_effectiveness": list(sides)}
                       for calibration, sides in worlds],
            "public_trajectories": public_pairs, "public_comparison": public_check,
            "terminal_profiles": terminal_pairs, "terminal_comparison": terminal_check,
            "passed": public_check["equal_within_tolerance"] and terminal_check["equal_within_tolerance"],
        }
        progress(f"symmetry {name}: public={public_check['equal_within_tolerance']} terminal={terminal_check['equal_within_tolerance']}")
    # An explicitly separate negative control prevents promoting swap symmetry
    # into the unjustified claim that only the average gain ever matters.
    average_worlds = ((0.55, 0.95), (0.75, 0.75))
    average_pairs = [{sequence_name: public_trajectory(
        CENTRE, temperature_C=22.5, sensor_seed=101, sequence=sequence,
        side_effectiveness=sides, check_budget=check_budget)
        for sequence_name, sequence in SEQUENCES.items()} for sides in average_worlds]
    difference = _compare(*average_pairs)
    result["same_average_negative_control"] = {
        "side_effectiveness": [list(sides) for sides in average_worlds],
        "public_trajectories": average_pairs, "comparison": difference,
        "different_in_this_test": not difference["equal_within_tolerance"],
        "claim": "Equality of mean gain is not assumed to imply trajectory equivalence."
                 " This paired example is not a universal distinguishability proof.",
    }
    result["proof_scope"] = {
        "side_permutation": "Identical drive configurations, common commands and shaft speed, symmetric aggregate"
            " force and protection, and unlabeled sensors preserve observations under exchange of the two drives."
            " Identical observation histories also preserve any common adaptive policy's action sequence.",
        "product_scaling": "Plant torque, back EMF, initial current and numerical coupling depend on"
            " motor_efficiency times each side gain. Rescaling these factors while preserving both products"
            " leaves the mathematical plant unchanged; floating representation can create tiny differences.",
        "decision_relevance": "Swapped sides also have identical common-controller rewards. Side-label recovery"
            " is not required by the current motion-quality task. The five-field controller may nevertheless"
            " fail to represent some unequal-drive dynamics.",
        "not_proved": "Aggregate output is not assumed to depend only on average gain. Back EMF, current"
            " limits and heating can reveal unequal gains without revealing their labels.",
    }
    return result


def audit(*, max_seconds: float = 600.0, checkpoint_path: str | Path | None = None,
          progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Execute the frozen audit, raising ResourceLimit with a saved checkpoint.

    The cap is checked before every experiment, so the only possible overrun is
    the currently executing bounded catalog experiment or verification profile.
    All completed cases are saved on timeout or interruption. Nothing detaches.
    """
    if isinstance(max_seconds, bool) or not math.isfinite(max_seconds) or max_seconds <= 0:
        raise ValueError("max_seconds must be finite and positive")
    started = time.monotonic()
    checkpoint = Path(checkpoint_path or ROOT / "runs/physical_gate_v1/observability-checkpoint.json.gz")
    emit = progress or (lambda message: None)
    report: dict[str, Any] = {
        "schema_version": AUDIT_ID, "status": "running", "source_sha256": _source_hashes(),
        "protocol": {"centre": asdict(CENTRE), "temperatures_C": list(TEMPERATURES),
            "primary_sensor_seeds": list(SENSOR_SEEDS), "primary_relative_steps": list(PRIMARY_EPSILONS),
            "auxiliary_sensor_seed": 101, "auxiliary_relative_steps": list(AUXILIARY_EPSILONS),
            "sequences": {name: list(sequence) for name, sequence in SEQUENCES.items()},
            "persistent_cost": sum(CATALOG[name].cost for name in PERSISTENT_SEQUENCE),
            "parameter_order": list(PARAMETERS), "parameter_ranges": RANGES.tolist(),
            "primary_sensors": asdict(DEFAULT_SENSORS), "auxiliary_sensors": asdict(AUXILIARY_SENSORS),
            "channel_whitening_scale": dict(zip(OBSERVATION_FIELDS, CHANNEL_SCALES.tolist())),
            "whitening_scope": "Declared marginal noise plus quantization variance; not the full feedback"
                " output covariance. The SVD is a sensitivity diagnostic, not an exact Fisher information matrix.",
            "known_reset": {"angle_deg": 20.0, "velocity_rad_s": 0.0, "motor_force_N_each": 0.0},
            "deduplication": "Sensor acquisition timestamp, rounded to 1e-12s. Final and start reads"
                " of an already acquired sample are not additional independent measurements.",
            "maximum_elapsed_seconds": max_seconds, "resource_limit_check": "before each bounded experiment/profile",
            "hardware_validated": False},
        "runs": {}, "analyses": [], "symmetries": {},
    }

    def check() -> None:
        if time.monotonic() - started >= max_seconds:
            raise ResourceLimit(f"observability audit reached {max_seconds:g}s; checkpoint: {checkpoint}")

    def save(status: str) -> None:
        report["status"] = status
        report["elapsed_seconds"] = time.monotonic() - started
        _write_json(checkpoint, report)

    try:
        # Structural checks are performed first and are not inferred from SVD.
        report["symmetries"] = symmetry_audit(check_budget=check, progress=emit)
        save("running")
        modes = (("primary", DEFAULT_SENSORS, SENSOR_SEEDS, PRIMARY_EPSILONS),
                 ("smooth_auxiliary", AUXILIARY_SENSORS, (101,), AUXILIARY_EPSILONS))
        for mode, sensors, seeds, epsilons in modes:
            for temperature in TEMPERATURES:
                for seed in seeds:
                    for sequence_name, sequence in SEQUENCES.items():
                        check()
                        prefix = f"{mode}/T{temperature:g}/seed{seed}/{sequence_name}"
                        centre_id = prefix + "/centre"
                        centre = public_trajectory(CENTRE, temperature_C=temperature, sensor_seed=seed,
                                                   sequence=sequence, sensors=sensors, check_budget=check)
                        report["runs"][centre_id] = centre
                        for epsilon in epsilons:
                            pairs, ids = {}, {}
                            for name, width in zip(PARAMETERS, RANGES):
                                values, pair_ids = [], []
                                for sign in (1, -1):
                                    check()
                                    calibration = replace(CENTRE, **{name: getattr(CENTRE, name) + sign * epsilon * width})
                                    key = prefix + f"/eps{epsilon:g}/{name}/{sign:+d}"
                                    value = public_trajectory(calibration, temperature_C=temperature, sensor_seed=seed,
                                                              sequence=sequence, sensors=sensors, check_budget=check)
                                    report["runs"][key] = value
                                    values.append(value)
                                    pair_ids.append(key)
                                pairs[name], ids[name] = (values[0], values[1]), pair_ids
                            summary = finite_difference_summary(centre, pairs, epsilon)
                            report["analyses"].append({"mode": mode, "temperature_C": temperature,
                                "sensor_seed": seed, "sequence": sequence_name, "centre_run_id": centre_id,
                                "perturbation_run_ids": ids, **summary})
                        emit(f"observability {prefix}: {len(report['runs'])} completed trajectories;"
                             f" elapsed {time.monotonic() - started:.1f}s")
                        save("running")
        report["structural_checks_passed"] = all(report["symmetries"][name]["passed"]
            for name in ("side_permutation", "same_motor_products"))
        report["same_average_counterexample_observed"] = report["symmetries"]["same_average_negative_control"]["different_in_this_test"]
        save("complete")
        report["report_sha256"] = digest(report)
        _write_json(checkpoint, report)
        return report
    except ResourceLimit:
        save("resource_limit")
        raise
    except BaseException:
        save("interrupted_or_failed")
        raise


def smoke() -> dict[str, Any]:
    """Small contract smoke, deliberately not the frozen scientific sweep."""
    started = time.monotonic()
    trajectory = public_trajectory(CENTRE, temperature_C=22.5, sensor_seed=101, sequence=("hold",))
    features = trajectory["features"]
    if len(features["acquisition_keys"]) != 4 or len(features["vector"]) != 12:
        raise AssertionError("completed hold must contain reset plus three unique acquisitions")
    if features["duplicate_reads_removed"] != 2:
        raise AssertionError("start and final aliases should be deduplicated")
    examples = [public_trajectory(CENTRE, temperature_C=22.5, sensor_seed=101, sequence=("high_sweep",),
                                  side_effectiveness=sides) for sides in ((0.55, 0.95), (0.95, 0.55), (0.75, 0.75))]
    swapped, average = _compare(examples[0], examples[1]), _compare(examples[0], examples[2])
    if not swapped["equal_within_tolerance"]:
        raise AssertionError("side permutation counterexample failed")
    if average["equal_within_tolerance"]:
        raise AssertionError("the same-average negative control unexpectedly matched")
    return {"schema_version": AUDIT_ID, "status": "smoke_only", "elapsed_seconds": time.monotonic() - started,
            "unique_hold_acquisitions": len(features["acquisition_keys"]),
            "duplicate_reads_removed": features["duplicate_reads_removed"],
            "side_permutation": swapped, "same_average_negative_control": average,
            "not_a_scientific_result": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("runs/physical_gate_v1/observability.json.gz"))
    parser.add_argument("--max-seconds", type=float, default=600.0)
    parser.add_argument("--smoke", action="store_true", help="run only the short software smoke, not the frozen sweep")
    args = parser.parse_args()
    if args.smoke:
        report = smoke()
    else:
        report = audit(max_seconds=args.max_seconds, checkpoint_path=args.output,
                       progress=lambda message: print(message, flush=True))
    _write_json(args.output, report)
    print(json.dumps({"status": report["status"], "elapsed_seconds": report["elapsed_seconds"],
                      "output": str(args.output), "analyses": len(report.get("analyses", []))}, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
