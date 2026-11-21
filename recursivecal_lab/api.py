"""Transport-independent local API. No network, actuator, or subprocess access."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import tempfile
from typing import Any

from . import __version__
from .io import MAX_INPUT_BYTES, write_json
from .physics import MODEL_ID, SCENARIOS, ModelParameters, passive_hold, simulate


def capabilities() -> dict[str, Any]:
    from . import physics
    parameters = asdict(ModelParameters())
    schema = physics.parameter_schema() if hasattr(physics, "parameter_schema") else {}
    return {
        "schema_version": "recursivecal.capabilities.v1", "version": __version__,
        "model_id": MODEL_ID, "default_parameters": parameters,
        "parameters": schema, "parameter_schema": schema,
        "defaults": {"parameters": parameters, "duration_s": 6.5, "dt_s": 0.01,
                     "seed": 0, "scenario": "open", "controller": "nominal", "abort_on_limit": True},
        "scenarios": list(SCENARIOS), "controllers": ["nominal", "disabled"],
        "limits": {"duration_s_max": 120, "dt_s_min": 0.0001, "dt_s_max": 0.05,
                   "max_steps": 50000, "max_input_bytes": MAX_INPUT_BYTES},
        "passive_hold": passive_hold(),
        "scope": "Local software-in-the-loop research. Default parameters and observations are synthetic.",
        "hardware_connected": False,
    }


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _allowed(payload: dict[str, Any], keys: set[str]) -> None:
    unknown = set(payload) - keys
    if unknown:
        raise ValueError("unknown request fields: " + ", ".join(sorted(unknown)))


def dispatch(path: str, payload: Any) -> dict[str, Any]:
    body = _object(payload, "request")
    if path == "/api/inquiry":
        from .inquiry import run_study
        _allowed(body, {"case", "seed", "policy", "max_tests", "budget"})
        return run_study(**body)
    if path == "/api/verify-inquiry":
        from .inquiry import verify_report
        _allowed(body, {"report"})
        return verify_report(body.get("report"))
    if path == "/api/simulate":
        _allowed(body, {"parameters", "duration_s", "dt_s", "seed", "scenario", "controller",
                        "initial_angle_rad", "initial_velocity_rad_s", "abort_on_limit", "controller_parameters", "parameter_provenance"})
        duration, dt = body.get("duration_s", 6.5), body.get("dt_s", 0.01)
        if isinstance(duration, (int, float)) and isinstance(dt, (int, float)) and dt > 0 and duration / dt > 50000:
            raise ValueError("browser simulation is limited to 50000 integration steps; use the CLI for longer runs")
        return simulate(**body)
    if path == "/api/apply-force-fit":
        from .measurements import force_curve_parameters
        _allowed(body, {"fit", "parameters"})
        fit = _object(body.get("fit"), "fit")
        base = ModelParameters(**_object(body["parameters"], "parameters")) if "parameters" in body else None
        parameters = force_curve_parameters(fit, base)
        return {"schema_version": "recursivecal.parameter-set/1", "parameters": asdict(parameters),
                "parameter_provenance": fit["provenance"]}
    if path not in ("/api/fit-force", "/api/replay"):
        raise ValueError("unknown API operation")
    _allowed(body, {"csv_text", "metadata"} if path == "/api/fit-force" else {"csv_text", "metadata", "simulation", "acceptance_limits"})
    csv_text = body.get("csv_text")
    if not isinstance(csv_text, str) or not csv_text.strip():
        raise ValueError("csv_text must contain a CSV file")
    if len(csv_text.encode()) > MAX_INPUT_BYTES:
        raise ValueError("CSV exceeds 8 MiB")
    metadata = _object(body.get("metadata"), "metadata")
    with tempfile.TemporaryDirectory(prefix="recursivecal-input-") as directory:
        root = Path(directory)
        csv_path = root / "measurements.csv"
        csv_path.write_text(csv_text, encoding="utf-8")
        metadata_path = write_json(root / "metadata.json", metadata)
        if path == "/api/fit-force":
            from .measurements import fit_force_curve
            return fit_force_curve(csv_path, metadata_path=metadata_path)
        from .measurements import compare_trajectory
        return compare_trajectory(csv_path, _object(body.get("simulation"), "simulation"), metadata_path=metadata_path,
                                  acceptance_limits=body.get("acceptance_limits"))

