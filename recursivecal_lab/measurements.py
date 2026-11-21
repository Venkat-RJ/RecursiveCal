"""Strict SI CSV import, held-out force fitting, and trajectory comparison.

Imports never confer hardware validation. Provenance is declared by the data
provider and the included example data are entirely synthetic.
"""
from __future__ import annotations

import bisect
import csv
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .physics import ModelParameters, geometry

FORCE_UNITS = {"length_m": "m", "force_N_each": "N", "temperature_C": "degC"}
TRAJECTORY_UNITS = {"time_s": "s", "angle_rad": "rad", "velocity_rad_s": "rad/s"}


def _read_metadata(csv_path: Path, metadata_path: str | Path | dict[str, Any] | None,
                   required_units: dict[str, str]) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    if isinstance(metadata_path, dict):
        metadata = dict(metadata_path)
    else:
        candidate = Path(metadata_path) if metadata_path else csv_path.with_suffix(".metadata.json")
        if not candidate.exists():
            if metadata_path:
                raise ValueError(f"metadata file does not exist: {candidate}")
            metadata = {"source_kind": "unknown", "source": "not supplied", "units": required_units}
            warnings.append("No provenance sidecar supplied. SI units follow column names; source remains unknown.")
        else:
            try:
                metadata = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ValueError("metadata must be a readable JSON object") from exc
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    if metadata.get("source_kind") not in ("synthetic", "measured", "unknown"):
        raise ValueError("metadata source_kind must be synthetic, measured, or unknown")
    if not isinstance(metadata.get("source"), str) or not metadata["source"].strip():
        raise ValueError("metadata source must identify how/where the data were obtained")
    units = metadata.get("units")
    if not isinstance(units, dict):
        raise ValueError("metadata units must be an object")
    for column, unit in required_units.items():
        if units.get(column) != unit:
            raise ValueError(f"metadata unit for {column} must be {unit!r}")
    if metadata["source_kind"] == "measured":
        warnings.append("Measured provenance is user-declared and has not been independently verified.")
    try:
        metadata = json.loads(json.dumps(metadata, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError("metadata must contain finite JSON values") from exc
    return metadata, warnings


def load_measurement_csv(path: str | Path, *, kind: str = "force",
                         metadata_path: str | Path | dict[str, Any] | None = None) -> dict[str, Any]:
    """Read a force or trajectory CSV, rejecting ambiguous/nonfinite inputs."""
    csv_path = Path(path)
    if not csv_path.is_file():
        raise ValueError(f"CSV file does not exist: {csv_path}")
    if csv_path.stat().st_size > 10_000_000:
        raise ValueError("CSV exceeds the 10 MB import limit")
    if kind == "force":
        required = {"length_m", "force_N_each", "split"}
        allowed = required | {"temperature_C"}
        all_units = FORCE_UNITS
    elif kind == "trajectory":
        required = {"time_s", "angle_rad"}
        allowed = required | {"velocity_rad_s"}
        all_units = TRAJECTORY_UNITS
    else:
        raise ValueError("kind must be force or trajectory")
    rows: list[dict[str, Any]] = []
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        names = reader.fieldnames or []
        if len(names) != len(set(names)) or not names:
            raise ValueError("CSV headers must be present and unique")
        if required - set(names):
            raise ValueError("missing CSV columns: " + ", ".join(sorted(required - set(names))))
        if set(names) - allowed:
            raise ValueError("unsupported CSV columns: " + ", ".join(sorted(set(names) - allowed)))
        units = {column: unit for column, unit in all_units.items() if column in names}
        for line, raw in enumerate(reader, 2):
            if len(rows) >= 100000:
                raise ValueError("CSV exceeds 100000 rows")
            if None in raw:
                raise ValueError(f"row {line} has more values than headers")
            row: dict[str, Any] = {}
            for name, value in raw.items():
                if value is None or not value.strip():
                    raise ValueError(f"row {line}: missing {name}")
                if name == "split":
                    if value not in ("train", "validation"):
                        raise ValueError(f"row {line}: split must be train or validation")
                    row[name] = value
                    continue
                try:
                    number = float(value)
                except ValueError as exc:
                    raise ValueError(f"row {line}: {name} must be numeric") from exc
                if not math.isfinite(number):
                    raise ValueError(f"row {line}: {name} must be finite")
                row[name] = number
            if kind == "force":
                if row["length_m"] <= 0 or row["force_N_each"] < 0:
                    raise ValueError(f"row {line}: length must be positive and gas force nonnegative")
                if "temperature_C" in row and not -100 <= row["temperature_C"] <= 150:
                    raise ValueError(f"row {line}: temperature must lie in [-100, 150] degC")
            else:
                if row["time_s"] < 0 or (rows and row["time_s"] <= rows[-1]["time_s"]):
                    raise ValueError(f"row {line}: time_s must be nonnegative and strictly increasing")
                if not -math.pi <= row["angle_rad"] <= math.pi:
                    raise ValueError(f"row {line}: angle_rad is outside [-pi, pi]; check units")
            rows.append(row)
    if len(rows) < 3:
        raise ValueError("at least three data rows are required")
    metadata, warnings = _read_metadata(csv_path, metadata_path, units)
    return {"rows": rows, "columns": names, "metadata": metadata, "warnings": warnings,
            "sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(), "filename": csv_path.name,
            "kind": kind}


def _residual_metrics(residuals: list[float]) -> dict[str, float | int]:
    ordered = sorted(abs(r) for r in residuals)
    return {"n": len(residuals), "rmse": math.sqrt(math.fsum(r * r for r in residuals) / len(residuals)),
            "mae": math.fsum(abs(r) for r in residuals) / len(residuals),
            "bias": math.fsum(residuals) / len(residuals), "max_abs": max(ordered),
            "p95_abs": ordered[math.ceil(0.95 * len(ordered)) - 1]}


def fit_force_curve(csv_path: str | Path, metadata_path: str | Path | dict[str, Any] | None = None,
                    *, reference_temperature_C: float = 20.0) -> dict[str, Any]:
    """Fit only training rows; report held-out errors without refitting.

    force(T,L) = [a + b*(L-Lref)] * (T+273.15)/(Tref+273.15).
    Temperature scaling is an assumption, not a fitted thermal model.
    """
    if isinstance(reference_temperature_C, bool) or not isinstance(reference_temperature_C, (int, float)) or not math.isfinite(reference_temperature_C) or not -100 <= reference_temperature_C <= 150:
        raise ValueError("reference_temperature_C must lie in [-100,150]")
    dataset = load_measurement_csv(csv_path, kind="force", metadata_path=metadata_path)
    rows = dataset["rows"]
    train = [r for r in rows if r["split"] == "train"]
    valid = [r for r in rows if r["split"] == "validation"]
    if len(train) < 3 or len(valid) < 2:
        raise ValueError("force fitting needs at least 3 train and 2 validation rows with explicit split")
    fingerprint = lambda r: (r["length_m"], r["force_N_each"], r.get("temperature_C", reference_temperature_C))
    if {fingerprint(r) for r in train} & {fingerprint(r) for r in valid}:
        raise ValueError("identical rows occur in train and validation; provide separate held-out measurements")
    reference_length = math.fsum(r["length_m"] for r in train) / len(train)
    normalized_force = [r["force_N_each"] * (reference_temperature_C + 273.15) /
                        (r.get("temperature_C", reference_temperature_C) + 273.15) for r in train]
    mean_force = math.fsum(normalized_force) / len(train)
    xx = math.fsum((r["length_m"] - reference_length) ** 2 for r in train)
    if xx <= 1e-12:
        raise ValueError("training lengths have insufficient variation to identify a force slope")
    slope = math.fsum((r["length_m"] - reference_length) * (y - mean_force)
                      for r, y in zip(train, normalized_force)) / xx
    low, high = min(r["length_m"] for r in train), max(r["length_m"] for r in train)
    def predict(row: dict[str, Any]) -> float:
        base = mean_force + slope * (row["length_m"] - reference_length)
        return base * (row.get("temperature_C", reference_temperature_C) + 273.15) / (reference_temperature_C + 273.15)
    if min(mean_force + slope * (low - reference_length), mean_force + slope * (high - reference_length)) < 0:
        raise ValueError("fitted gas-force curve is negative in its training domain")
    predictions = [{"split": r["split"], "length_m": r["length_m"],
                    "temperature_C": r.get("temperature_C", reference_temperature_C),
                    "observed_force_N_each": r["force_N_each"], "predicted_force_N_each": predict(r),
                    "residual_N_each": predict(r) - r["force_N_each"],
                    "outside_training_length_range": not low <= r["length_m"] <= high} for r in rows]
    warnings = list(dataset["warnings"])
    if "temperature_C" not in dataset["columns"]:
        warnings.append("No temperatures supplied; every row is assumed to be at the chosen reference temperature.")
    if any(r["outside_training_length_range"] for r in predictions):
        warnings.append("Some validation rows extrapolate beyond training lengths; inspect their residuals separately.")
    if slope > 0:
        warnings.append("Fitted force rises with extension. This differs from the default gas-spring assumption; inspect the data and hardware type.")
    nominal = ModelParameters()
    closed_length, open_length = geometry(0, nominal)["length_m"], geometry(nominal.max_angle_rad, nominal)["length_m"]
    covered = low - 1e-9 <= closed_length <= high + 1e-9 and low - 1e-9 <= open_length <= high + 1e-9
    update = {
        "gas_force_compressed_N_each": mean_force + slope * (closed_length - reference_length),
        "gas_force_extended_N_each": mean_force + slope * (open_length - reference_length),
        "gas_reference_temperature_C": reference_temperature_C, "gas_scale": 1.0,
    } if covered else None
    return {
        "schema_version": "recursivecal.force-fit/1",
        "method": "ordinary least squares on explicit training rows only; fixed ideal-gas temperature normalization",
        "provenance": {"source_kind": dataset["metadata"]["source_kind"], "metadata": dataset["metadata"],
                       "source": dataset["metadata"]["source"], "csv_sha256": dataset["sha256"],
                       "filename": dataset["filename"], "hardware_validated": False,
                       "verification": "provider declaration, not independent provenance verification"},
        "curve": {"reference_length_m": reference_length, "force_at_reference_N_each": mean_force,
                  "slope_N_m": slope, "reference_temperature_C": reference_temperature_C,
                  "training_length_range_m": [low, high]},
        "training_metrics_N_each": _residual_metrics([r["residual_N_each"] for r in predictions if r["split"] == "train"]),
        "validation_metrics_N_each": _residual_metrics([r["residual_N_each"] for r in predictions if r["split"] == "validation"]),
        "validation_scope": "held-out rows under provider-supplied split; no claim of independent hardware/system validation",
        "application": {"can_apply_to_default_geometry": covered, "parameters": update,
                        "reason": "Training range covers both default CAD endpoints." if covered else "Default CAD endpoints are outside the training range; automatic extrapolation is refused."},
        "predictions": predictions, "warnings": warnings,
    }


def force_curve_parameters(fit: dict[str, Any], parameters: ModelParameters | None = None) -> ModelParameters:
    """Apply a fit to a selected mount geometry, refusing extrapolation."""
    p = (parameters or ModelParameters()).validate()
    if fit.get("schema_version") != "recursivecal.force-fit/1":
        raise ValueError("expected recursivecal.force-fit/1 artifact")
    curve = fit["curve"]
    low, high = curve["training_length_range_m"]
    short, long = geometry(0, p)["length_m"], geometry(p.max_angle_rad, p)["length_m"]
    if not (low - 1e-9 <= short <= high + 1e-9 and low - 1e-9 <= long <= high + 1e-9):
        raise ValueError("force fit does not cover the requested mount geometry; extrapolation refused")
    at = lambda length: curve["force_at_reference_N_each"] + curve["slope_N_m"] * (length - curve["reference_length_m"])
    return replace(p, gas_force_compressed_N_each=at(short), gas_force_extended_N_each=at(long),
                   gas_reference_temperature_C=curve["reference_temperature_C"], gas_scale=1.0).validate()


def compare_trajectory(csv_path: str | Path, simulation: dict[str, Any],
                       metadata_path: str | Path | dict[str, Any] | None = None,
                       *, acceptance_limits: dict[str, float] | None = None) -> dict[str, Any]:
    """Compare held-out sensor observations at their own timestamps.

    Linear interpolation is used only inside the simulated time interval.
    No alignment or time shift is fitted against the validation observations.
    """
    dataset = load_measurement_csv(csv_path, kind="trajectory", metadata_path=metadata_path)
    if simulation.get("schema_version") != "recursivecal.run/1":
        raise ValueError("simulation must be a recursivecal.run/1 artifact")
    trace = simulation.get("trace", [])
    if len(trace) < 2:
        raise ValueError("simulation must contain at least two trace rows")
    signal_names = ["angle_rad"] + (["velocity_rad_s"] if "velocity_rad_s" in dataset["columns"] else [])
    times = []
    for row in trace:
        for key in ["time_s"] + signal_names:
            if isinstance(row.get(key), bool) or not isinstance(row.get(key), (int, float)) or not math.isfinite(row[key]):
                raise ValueError(f"simulation trace has invalid {key}")
        if times and row["time_s"] <= times[-1]:
            raise ValueError("simulation times must be strictly increasing")
        times.append(row["time_s"])
    data = dataset["rows"]
    if data[0]["time_s"] < times[0] - 1e-9 or data[-1]["time_s"] > times[-1] + 1e-9:
        raise ValueError("measurement time range extends beyond the simulation; extrapolation refused")
    residual_rows = []
    for row in data:
        timestamp = min(times[-1], max(times[0], row["time_s"]))
        upper = min(len(times) - 1, max(1, bisect.bisect_left(times, timestamp)))
        lower = upper - 1
        weight = (timestamp - times[lower]) / (times[upper] - times[lower])
        residual = {"time_s": row["time_s"]}
        for signal in signal_names:
            prediction = trace[lower][signal] * (1 - weight) + trace[upper][signal] * weight
            residual["predicted_" + signal] = prediction
            residual["observed_" + signal] = row[signal]
            residual["residual_" + signal] = prediction - row[signal]
        residual_rows.append(residual)
    metrics = {signal: _residual_metrics([r["residual_" + signal] for r in residual_rows]) for signal in signal_names}
    accepted = None
    if acceptance_limits is not None:
        allowed = {"angle_rmse_rad": "angle_rad", "velocity_rmse_rad_s": "velocity_rad_s"}
        if not acceptance_limits or set(acceptance_limits) - set(allowed):
            raise ValueError("acceptance_limits supports angle_rmse_rad and velocity_rmse_rad_s")
        checks = []
        for limit, value in acceptance_limits.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError("acceptance limits must be finite nonnegative numbers")
            if allowed[limit] not in metrics:
                raise ValueError(f"data has no signal for {limit}")
            checks.append(metrics[allowed[limit]]["rmse"] <= value)
        accepted = all(checks)
    return {
        "schema_version": "recursivecal.trajectory-comparison/1",
        "provenance": {"source_kind": dataset["metadata"]["source_kind"], "metadata": dataset["metadata"],
                       "source": dataset["metadata"]["source"], "csv_sha256": dataset["sha256"],
                       "filename": dataset["filename"], "hardware_validated": False},
        "simulation_model_id": simulation.get("model_id"),
        "simulation_sha256": hashlib.sha256(json.dumps(simulation, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
        "method": "linear time interpolation without refitting, alignment, or extrapolation",
        "metrics": metrics, "acceptance_limits": acceptance_limits, "acceptance_passed": accepted,
        "validation_scope": "dataset agreement only; threshold origin and data independence are not verified",
        "residuals": residual_rows, "warnings": dataset["warnings"],
    }


def export_trace_csv(run: dict[str, Any], path: str | Path) -> Path:
    """Export every simulation trace row using the canonical SI column names."""
    if run.get("schema_version") != "recursivecal.run/1" or not run.get("trace"):
        raise ValueError("run must be a nonempty recursivecal.run/1 artifact")
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(run["trace"][0]))
        writer.writeheader()
        writer.writerows(run["trace"])
    return output
