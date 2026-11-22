"""Bounded classical identification using only public version-3 measurements.

This is regularized least squares, equivalently a Gaussian approximate MAP
estimator.  The likelihood is a declared approximation: the forward predictor
retains sampling, latency, command delay, drive dynamics and the complete action
prefix, but removes quantization and sensor noise for numerical optimization.
The real experiment remains noisy and quantized.  No evaluator state, sampled
world identifier, private seed, or post-commit outcome enters this module.
"""
from __future__ import annotations

from dataclasses import asdict, replace
import math
import time
from typing import Any

import numpy as np
from scipy.optimize import least_squares

from recursivecal_lab.physical_rig import (
    CATALOG, OBSERVATION_FIELDS, Calibration, RigState, run_experiment,
)
from recursivecal_lab.physics import gas_force
from recursivecal_lab.research_rig import ResearchRig, SensorParameters
from recursivecal_lab.rl_environment import CALIBRATION_BOUNDS, PARAMETER_BOUNDS

ESTIMATOR_ID = "recursivecal.physical-gate-regularized-map/1"
NAMES = tuple(asdict(Calibration()))
SCALES = np.array([PARAMETER_BOUNDS[name][1] - PARAMETER_BOUNDS[name][0]
                   for name in NAMES], dtype=float)
PRIOR = np.array([sum(PARAMETER_BOUNDS[name]) / 2 for name in NAMES], dtype=float)
LOWER = np.array([CALIBRATION_BOUNDS[name][0] for name in NAMES], dtype=float)
UPPER = np.array([CALIBRATION_BOUNDS[name][1] for name in NAMES], dtype=float)
INFERENCE_SIGMA = np.array([0.004, 0.016, 3.0])
PREDICTOR_SENSORS = replace(
    SensorParameters(), angle_resolution_rad=0.0, velocity_resolution_rad_s=0.0,
    force_resolution_N=0.0, angle_noise_std_rad=0.0,
    velocity_noise_std_rad_s=0.0, force_noise_std_N=0.0,
)


def _sample_key(row: dict[str, Any]) -> float:
    """An acquisition repeated in several views contributes only once."""
    return round(float(row["sensor_sample_time_s"]), 9)


def _public_inputs(view: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Copy only fields actually needed by the public observation estimator."""
    history = view["history"]
    if not isinstance(history, list) or len(history) > 6:
        raise ValueError("invalid diagnostic history")

    def measurement(row):
        names = ("sensor_sample_time_s", "ambient_temperature_C", *OBSERVATION_FIELDS)
        values = {key: row[key] for key in names}
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) for value in values.values()):
            raise ValueError("public measurements must be finite")
        return values

    initial = measurement(history[0]["start_observation"] if history else view["measurement"])
    records = []
    rows, seen = [initial], {_sample_key(initial)}
    for entry in history:
        if entry["action"] not in CATALOG:
            raise ValueError("unknown experiment in public history")
        record = {"action": entry["action"],
                  "start_observation": measurement(entry["start_observation"]),
                  "observations": [measurement(row) for row in entry["observations"]],
                  "final_observation": measurement(entry["final_observation"]),
                  "termination": entry["termination"]}
        records.append(record)
        for row in [*record["observations"], record["final_observation"]]:
            key = _sample_key(row)
            if key not in seen:
                rows.append(row)
                seen.add(key)
    return initial, records, rows


def _predict(calibration: Calibration, initial: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    """Replay a candidate model from the public reset state, never a true state."""
    rig = ResearchRig(replace(calibration.model(), temperature_C=initial["ambient_temperature_C"]),
                      state=RigState(), sensors=PREDICTOR_SENSORS, seed=0)
    first = rig.observe(noisy=False)
    samples = {_sample_key(first): first}
    terminations = []
    for record in records:
        result = run_experiment(rig, record["action"], record["start_observation"], noisy=False)
        for row in [*result["observations"], result["final_observation"]]:
            samples[_sample_key(row)] = row
        terminations.append(result["metrics"]["termination"])
        if result["metrics"]["termination"] != "completed":
            break
    return {"samples": samples, "terminations": terminations}


def fit_history(view: dict[str, Any], *, initial_estimate: dict[str, float] | None = None,
                max_nfev: int = 20, max_forward_calls: int = 144,
                prior_strength: float = 0.5, difference_step: float = 0.001) -> dict[str, Any]:
    """Fit zero, one or several paid experiments without accessing the evaluator.

    The fixed prior is centered on the training sampler's declared parameter
    intervals.  Its scale is one whole interval per parameter, multiplied by
    ``1 / prior_strength``.  Bounds are the public calibration bounds, allowing
    an OOD fit to leave the training envelope.  The returned covariance is a
    local Gaussian approximation under this approximate likelihood and prior,
    not a frequentist coverage guarantee or a physical identification proof.

    ``max_nfev`` limits SciPy's objective iterations.  ``max_forward_calls`` also
    counts every finite-difference model call, including final diagnostics.
    """
    if type(max_nfev) is not int or max_nfev < 1:
        raise ValueError("max_nfev must be a positive integer")
    if type(max_forward_calls) is not int or max_forward_calls < 12:
        raise ValueError("max_forward_calls must be an integer of at least 12")
    if not math.isfinite(prior_strength) or prior_strength <= 0:
        raise ValueError("prior_strength must be positive")
    if not math.isfinite(difference_step) or difference_step <= 0:
        raise ValueError("difference_step must be positive")
    started = time.monotonic()
    initial, records, observed = _public_inputs(view)
    target = np.array([[row[name] for name in OBSERVATION_FIELDS] for row in observed])
    row_keys = [_sample_key(row) for row in observed]
    ndata = target.size
    zlow, zhigh = (LOWER - PRIOR) / SCALES, (UPPER - PRIOR) / SCALES
    if initial_estimate is None:
        guess = PRIOR.copy()
        guess[NAMES.index("sensor_bias_rad")] = initial["angle_rad"] - RigState().angle_rad
        gas_reference = gas_force(RigState().angle_rad,
                                  replace(Calibration().model(), temperature_C=initial["ambient_temperature_C"]))
        guess[NAMES.index("gas_scale")] = initial["strut_force_N_each"] / gas_reference
    else:
        guess = np.array(list(asdict(Calibration.from_dict(initial_estimate)).values()), dtype=float)
    zstart = np.clip((guess - PRIOR) / SCALES, zlow + 1e-9, zhigh - 1e-9)
    cache: dict[bytes, tuple[np.ndarray, dict[str, Any]]] = {}
    jac_cache: dict[bytes, np.ndarray] = {}
    calls = 0
    best = {"cost": math.inf, "z": zstart.copy()}
    diagnostic_phase = False

    class BudgetExhausted(RuntimeError):
        pass

    def residual(z):
        nonlocal calls
        key = np.asarray(z, dtype=np.float64).tobytes()
        if key in cache:
            return cache[key][0]
        # Reserve five perturbations for a final observational-rank check.
        limit = max_forward_calls if diagnostic_phase else max_forward_calls - len(NAMES)
        if calls >= limit:
            raise BudgetExhausted("forward model call budget exhausted")
        calls += 1
        calibration = Calibration.from_dict(dict(zip(NAMES, (PRIOR + z * SCALES).tolist())))
        prediction = _predict(calibration, initial, records)
        errors, missing = [], []
        for index, sample_key in enumerate(row_keys):
            predicted = prediction["samples"].get(sample_key)
            if predicted is None:
                # This is a likelihood penalty, never a fabricated acquisition.
                errors.extend((100.0, 100.0, 100.0))
                missing.append(sample_key)
            else:
                errors.extend(((np.array([predicted[name] for name in OBSERVATION_FIELDS])
                                - target[index]) / INFERENCE_SIGMA).tolist())
        expected_terminations = [row["termination"] for row in records]
        termination_mismatch = prediction["terminations"] != expected_terminations
        result = np.concatenate([np.asarray(errors), prior_strength * z])
        details = {"missing_acquisition_times_s": missing,
                   "predicted_terminations": prediction["terminations"],
                   "termination_mismatch": termination_mismatch}
        cache[key] = result, details
        cost = float(result @ result)
        if cost < best["cost"]:
            best.update(cost=cost, z=np.array(z, copy=True))
        return result

    def jacobian(z):
        key = np.asarray(z, dtype=np.float64).tobytes()
        if key not in jac_cache:
            base = residual(z)
            jac = np.empty((len(base), len(NAMES)))
            for column in range(len(NAMES)):
                step = min(difference_step, zhigh[column] - z[column])
                if step < difference_step / 2:
                    step = -min(difference_step, z[column] - zlow[column])
                shifted = np.array(z, copy=True)
                shifted[column] += step
                jac[:, column] = (residual(shifted) - base) / step
            jac_cache[key] = jac
        return jac_cache[key]

    optimized = None
    budget_exhausted = False
    try:
        optimized = least_squares(residual, zstart, jac=jacobian, bounds=(zlow, zhigh),
                                  method="trf", max_nfev=max_nfev, ftol=1e-5,
                                  xtol=1e-4, gtol=1e-4)
        zfinal = optimized.x
    except BudgetExhausted:
        budget_exhausted = True
        zfinal = best["z"]
    diagnostic_phase = True
    final_residual = residual(zfinal)
    details = cache[np.asarray(zfinal, dtype=np.float64).tobytes()][1]
    jac = None
    try:
        jac = jacobian(zfinal)
    except BudgetExhausted:
        budget_exhausted = True
    data_residual = final_residual[:ndata]
    rms = float(np.sqrt(np.mean(data_residual**2)))
    peak = float(np.max(np.abs(data_residual)))
    estimate = PRIOR + zfinal * SCALES
    mismatch = bool(rms > 4.0 or peak > 6.0 or details["missing_acquisition_times_s"]
                    or details["termination_mismatch"])
    diagnostics: dict[str, Any] = {
        "singular_values_noise_scaled": None, "numerical_rank": None,
        "effective_rank_at_one_sigma": None, "posterior_covariance": None,
        "posterior_std": None,
    }
    if jac is not None:
        data_jac = jac[:ndata]
        singular = np.linalg.svd(data_jac, compute_uv=False)
        tolerance = max(data_jac.shape) * np.finfo(float).eps * (singular[0] if len(singular) else 0)
        normalized_covariance = np.linalg.inv(jac.T @ jac)
        covariance = normalized_covariance * SCALES[:, None] * SCALES[None, :]
        diagnostics.update(
            singular_values_noise_scaled=singular.tolist(),
            numerical_rank=int(np.count_nonzero(singular > tolerance)),
            effective_rank_at_one_sigma=int(np.count_nonzero(singular > 1.0)),
            posterior_covariance=covariance.tolist(),
            posterior_std=dict(zip(NAMES, np.sqrt(np.maximum(0, np.diag(covariance))).tolist())),
        )
    return {
        "estimator_id": ESTIMATOR_ID,
        "estimate": dict(zip(NAMES, estimate.tolist())),
        "parameter_order": list(NAMES),
        "source": "public initial measurement and unique acquisitions in the action prefix",
        "predictor_approximation": "zero quantization and sensor noise; default delays and persistent drive states retained",
        "likelihood_sigma": dict(zip(OBSERVATION_FIELDS, INFERENCE_SIGMA.tolist())),
        "prior_center": dict(zip(NAMES, PRIOR.tolist())),
        "prior_sigma": dict(zip(NAMES, (SCALES / prior_strength).tolist())),
        "experiment_count": len(records), "unique_acquisitions": len(observed),
        "data_dimension": ndata, "standardized_residual_rms": rms,
        "standardized_residual_max": peak, "model_mismatch": mismatch,
        "converged": bool(optimized is not None and optimized.success and not budget_exhausted),
        "optimizer_status": int(optimized.status) if optimized is not None else None,
        "optimizer_message": str(optimized.message) if optimized is not None else "forward model budget exhausted",
        "optimizer_nfev": int(optimized.nfev) if optimized is not None else None,
        "forward_calls": calls, "max_forward_calls": max_forward_calls,
        "max_nfev": max_nfev, "budget_exhausted": budget_exhausted,
        "elapsed_s": time.monotonic() - started,
        "near_bounds": [name for index, name in enumerate(NAMES)
                        if min(estimate[index] - LOWER[index], UPPER[index] - estimate[index])
                        <= 0.002 * SCALES[index]],
        "data_standardized_residual": data_residual.tolist(),
        **details, **diagnostics,
        "uncertainty_scope": "local regularized Gaussian approximation; no coverage or global uniqueness guarantee",
    }
