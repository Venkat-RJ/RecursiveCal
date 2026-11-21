"""Regenerate the bundled synthetic CSV examples. No hardware data are used."""
import csv
import json
from pathlib import Path
import random

from recursivecal_lab.physics import ModelParameters, gas_force, geometry, simulate


def main():
    root = Path(__file__).resolve().parent
    rng = random.Random(7112026)
    p = ModelParameters()
    rows = []
    for fractions, split in (([i / 12 for i in range(13)], "train"),
                             ([(i + .5) / 7 for i in range(7)], "validation")):
        for fraction in fractions:
            angle = fraction * p.max_angle_rad
            rows.append({"length_m": f"{geometry(angle, p)['length_m']:.12f}",
                         "force_N_each": f"{gas_force(angle, p) + rng.gauss(0, 1.5):.8f}",
                         "temperature_C": "20", "split": split})
    with (root / "synthetic_force.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    force_metadata = {
        "source_kind": "synthetic", "source": "generate_examples.py, seed 7112026; no hardware measurements",
        "units": {"length_m": "m", "force_N_each": "N", "temperature_C": "degC"},
        "split_definition": "13 training locations and 7 separate validation locations chosen before generation",
        "noise": "independent Gaussian force noise with standard deviation 1.5 N per strut",
        "parameter_origin": "illustrative SI model defaults", "license": "MIT",
    }
    (root / "synthetic_force.metadata.json").write_text(json.dumps(force_metadata, indent=2) + "\n")
    run = simulate(duration_s=6.5, dt_s=.01)
    trajectory = [{"time_s": f"{r['time_s']:.8f}",
                   "angle_rad": f"{r['angle_rad'] + .0012 + rng.gauss(0,.0005):.12f}"}
                  for r in run["trace"][::5]]
    with (root / "synthetic_trajectory.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(trajectory[0]))
        writer.writeheader()
        writer.writerows(trajectory)
    metadata = {
        "source_kind": "synthetic", "source": "generate_examples.py, seed 7112026; default SI simulation with artificial observation error",
        "units": {"time_s": "s", "angle_rad": "rad"},
        "noise": "angle bias 0.0012 rad plus Gaussian standard deviation 0.0005 rad",
        "independence": "Same simulator as the comparison model. This is an import demo, not independent validation.",
        "license": "MIT",
    }
    (root / "synthetic_trajectory.metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Generated {len(rows)} synthetic force rows and {len(trajectory)} synthetic trajectory rows in {root}")


if __name__ == "__main__":
    main()
