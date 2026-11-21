"""Foreground command line entry points for a clean installed checkout."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import importlib.metadata
from importlib.resources import files
import json
from pathlib import Path
import platform
import sys

from . import __version__
from .io import read_json, write_json


def _output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", type=Path, required=True, help="JSON result path")
    parser.add_argument("--overwrite", action="store_true", help="replace the named output file")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="recursivecal", description="Reproducible calibration research and local SIL workbench")
    p.add_argument("--version", action="version", version=__version__)
    commands = p.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="check installed dependencies, assets, and one SI run")
    model = commands.add_parser("model", help="print model defaults and physical support calculation")
    model.add_argument("--parameters", type=Path)
    sim = commands.add_parser("simulate", help="run the SI liftgate simulator")
    sim.add_argument("--parameters", type=Path, help="JSON ModelParameters object")
    sim.add_argument("--controller-parameters", type=Path, help="separate calibrated controller model")
    sim.add_argument("--scenario", choices=["open", "close", "passive_hold", "power_loss"], default="open")
    sim.add_argument("--controller", choices=["nominal", "disabled"], default="nominal")
    sim.add_argument("--duration", type=float, default=6.5, dest="duration_s")
    sim.add_argument("--dt", type=float, default=0.01, dest="dt_s")
    sim.add_argument("--seed", type=int, default=0)
    sim.add_argument("--initial-angle", type=float, dest="initial_angle_rad")
    sim.add_argument("--continue-on-limit", action="store_true", help="record limit events without stopping the synthetic run")
    sim.add_argument("--csv", type=Path, help="also export the full trace")
    _output(sim)
    fit = commands.add_parser("fit-force", help="fit a force/length curve using explicit train and validation rows")
    fit.add_argument("csv", type=Path)
    fit.add_argument("--metadata", type=Path, required=True)
    fit.add_argument("--parameters-output", type=Path, help="also save a provenance-bearing parameter set for simulate")
    fit.add_argument("--base-parameters", type=Path, help="model parameter set to update using this curve")
    _output(fit)
    replay = commands.add_parser("replay", help="compare measured trajectory CSV against a saved simulation")
    replay.add_argument("csv", type=Path)
    replay.add_argument("--simulation", type=Path, required=True)
    replay.add_argument("--metadata", type=Path, required=True)
    replay.add_argument("--angle-rmse-max", type=float, help="predeclared angle RMSE limit in radians")
    replay.add_argument("--velocity-rmse-max", type=float, help="predeclared velocity RMSE limit in rad/s")
    _output(replay)
    exp = commands.add_parser("experiment", help="train and evaluate the normalized diagnostic benchmark")
    exp.add_argument("--output", type=Path, required=True, help="new experiment directory")
    exp.add_argument("--train-size", type=int, default=1024)
    exp.add_argument("--test-size", type=int, default=512)
    exp.add_argument("--seeds", type=int, nargs="+", default=[13, 37, 103])
    exp.add_argument("--quick", action="store_true", help="small smoke run, not publication evidence")
    verify = commands.add_parser("verify", help="verify experiment artifacts and saved checkpoints")
    verify.add_argument("directory", type=Path)
    web = commands.add_parser("serve", help="serve the workbench in the foreground on loopback")
    web.add_argument("--host", choices=["127.0.0.1", "localhost"], default="127.0.0.1")
    web.add_argument("--port", type=int, default=8765)
    return p


def _parameter_input(path: Path | None) -> tuple[dict | None, dict | None]:
    if path is None:
        return None, None
    value = read_json(path)
    if not isinstance(value, dict):
        raise ValueError("parameter file must contain a JSON object")
    if "schema_version" in value:
        if value.get("schema_version") != "recursivecal.parameter-set/1":
            raise ValueError("unsupported parameter file schema")
        return value["parameters"], value.get("parameter_provenance")
    return value, None


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command in ("simulate", "fit-force", "replay"):
            paths = [args.output] + [value for value in (getattr(args, "csv", None) if args.command == "simulate" else None,
                                                       getattr(args, "parameters_output", None)) if value is not None]
            resolved = [path.resolve() for path in paths]
            if len(set(resolved)) != len(resolved):
                raise ValueError("each output must have a distinct path")
            for path in paths:
                if path.exists() and not args.overwrite:
                    raise FileExistsError(f"{path} exists; choose another output or pass --overwrite")
        if args.command == "doctor":
            from .physics import simulate
            trial = simulate(duration_s=0.1)
            assets = files("recursivecal_lab").joinpath("web", "index.html").is_file()
            report = {"version": __version__, "python": platform.python_version(),
                      "numpy": importlib.metadata.version("numpy"), "workbench_assets": assets,
                      "simulation_samples": len(trial["trace"]), "hardware_connected": False,
                      "status": "ok" if assets else "missing workbench assets"}
            print(json.dumps(report, indent=2))
            return 0 if assets else 1
        if args.command == "serve":
            from .server import serve
            serve(host=args.host, port=args.port)
            return 0
        if args.command == "model":
            from .physics import ModelParameters, passive_hold
            parameters, provenance = _parameter_input(args.parameters)
            parameters = parameters or asdict(ModelParameters())
            print(json.dumps({"parameters": parameters, "passive_hold": passive_hold(parameters)}, indent=2))
            return 0
        if args.command == "simulate":
            from .physics import simulate
            from .measurements import export_trace_csv
            if args.csv and args.csv.exists() and not args.overwrite:
                raise FileExistsError(f"{args.csv} exists; choose another output or pass --overwrite")
            parameters, provenance = _parameter_input(args.parameters)
            controller_parameters, _ = _parameter_input(args.controller_parameters)
            result = simulate(parameters=parameters, parameter_provenance=provenance,
                              controller_parameters=controller_parameters,
                              duration_s=args.duration_s, dt_s=args.dt_s, seed=args.seed,
                              scenario=args.scenario, controller=args.controller,
                              initial_angle_rad=args.initial_angle_rad, abort_on_limit=not args.continue_on_limit)
            saved = write_json(args.output, result, overwrite=args.overwrite)
            if args.csv:
                export_trace_csv(result, args.csv)
            print(json.dumps({"output": str(saved), "metrics": result["metrics"], "events": result["events"]}, indent=2))
            return 0
        if args.command == "fit-force":
            from .measurements import fit_force_curve, force_curve_parameters
            if args.parameters_output and args.parameters_output.exists() and not args.overwrite:
                raise FileExistsError(f"{args.parameters_output} exists; choose another output or pass --overwrite")
            result = fit_force_curve(args.csv, metadata_path=args.metadata)
            if args.parameters_output:
                from .physics import ModelParameters
                base_parameters, _ = _parameter_input(args.base_parameters)
                mapped = force_curve_parameters(result, ModelParameters(**base_parameters) if base_parameters else None)
                write_json(args.parameters_output, {"schema_version": "recursivecal.parameter-set/1",
                           "parameters": asdict(mapped), "parameter_provenance": result["provenance"]}, overwrite=args.overwrite)
        elif args.command == "replay":
            from .measurements import compare_trajectory
            limits = {}
            if args.angle_rmse_max is not None:
                limits["angle_rmse_rad"] = args.angle_rmse_max
            if args.velocity_rmse_max is not None:
                limits["velocity_rmse_rad_s"] = args.velocity_rmse_max
            result = compare_trajectory(args.csv, read_json(args.simulation), metadata_path=args.metadata, acceptance_limits=limits or None)
        elif args.command == "experiment":
            from .experiments import run_experiment
            print(f"Running experiment in foreground: {args.output}", flush=True)
            result = run_experiment(args.output, train_size=args.train_size, test_size=args.test_size,
                                    seeds=tuple(args.seeds), quick=args.quick)
            print(json.dumps({"output": str(args.output.resolve()), "model_id": result["model_id"],
                              "seeds": result["seeds"], "cohorts": list(result["results"]),
                              "summary": str(args.output.resolve() / "summary.json")}, indent=2, allow_nan=False))
            return 0
        elif args.command == "verify":
            from .experiments import validate_artifacts
            result = validate_artifacts(args.directory)
            print(json.dumps(result, indent=2, allow_nan=False))
            return 0 if result.get("valid", result.get("ok", True)) else 1
        else:
            raise ValueError("unknown command")
        saved = write_json(args.output, result, overwrite=args.overwrite)
        brief = {key: result[key] for key in ("schema_version", "curve", "validation_metrics_N_each", "metrics",
                 "acceptance_limits", "acceptance_passed", "warnings") if key in result}
        print(json.dumps({"output": str(saved), **brief}, indent=2, allow_nan=False))
        if args.command == "replay" and result.get("acceptance_passed") is False:
            return 1
        return 0
    except (ValueError, TypeError, OSError, KeyError) as exc:
        print(f"recursivecal: {exc}", file=sys.stderr)
        return 2

