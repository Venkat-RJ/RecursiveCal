"""Data contracts, leakage prevention, fit recovery, and trace comparison."""
import csv
import json
from pathlib import Path
import tempfile
import unittest

from recursivecal_lab.measurements import compare_trajectory, export_trace_csv, fit_force_curve, force_curve_parameters, load_measurement_csv
from recursivecal_lab.physics import ModelParameters, geometry, simulate


class MeasurementTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def write_csv(self, filename, rows, metadata=None):
        path = self.root / filename
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        if metadata:
            path.with_suffix(".metadata.json").write_text(json.dumps(metadata))
        return path

    def force_rows(self):
        p = ModelParameters()
        short, long = geometry(0, p)["length_m"], geometry(p.max_angle_rad, p)["length_m"]
        rows = []
        for fraction, split in [(0, "train"), (.25, "train"), (.75, "train"), (1, "train"), (.15, "validation"), (.65, "validation")]:
            length = short + fraction * (long - short)
            rows.append({"length_m": length, "force_N_each": 212 - 47 * fraction, "split": split})
        return rows

    def metadata(self, kind="force", source_kind="synthetic"):
        units = {"length_m": "m", "force_N_each": "N"} if kind == "force" else {"time_s": "s", "angle_rad": "rad"}
        return {"source_kind": source_kind, "source": "generated unit-test data", "units": units}

    def test_recover_curve_and_apply_to_model(self):
        path = self.write_csv("force.csv", self.force_rows(), self.metadata())
        fit = fit_force_curve(path)
        self.assertLess(fit["validation_metrics_N_each"]["rmse"], 1e-10)
        self.assertTrue(fit["application"]["can_apply_to_default_geometry"])
        p = force_curve_parameters(fit)
        self.assertAlmostEqual(p.gas_force_extended_N_each, 165)
        self.assertAlmostEqual(p.gas_force_compressed_N_each, 212)
        self.assertFalse(fit["provenance"]["hardware_validated"])

    def test_validation_labels_do_not_change_fit(self):
        rows = self.force_rows()
        first = fit_force_curve(self.write_csv("first.csv", rows))
        for row in rows:
            if row["split"] == "validation":
                row["force_N_each"] += 100
        second = fit_force_curve(self.write_csv("second.csv", rows))
        self.assertEqual(first["curve"], second["curve"])
        self.assertGreater(second["validation_metrics_N_each"]["rmse"], 99)

    def test_ambiguous_or_leaking_force_data_rejected(self):
        rows = self.force_rows()
        rows[-1] = dict(rows[0], split="validation")
        with self.assertRaisesRegex(ValueError, "identical rows"):
            fit_force_curve(self.write_csv("leak.csv", rows))
        metadata = self.metadata()
        metadata["units"]["force_N_each"] = "lbf"
        with self.assertRaisesRegex(ValueError, "must be 'N'"):
            fit_force_curve(self.write_csv("badunit.csv", self.force_rows(), metadata))

    def test_missing_metadata_is_unknown_not_measured(self):
        fit = fit_force_curve(self.write_csv("force.csv", self.force_rows()))
        self.assertEqual(fit["provenance"]["source_kind"], "unknown")
        self.assertFalse(fit["provenance"]["hardware_validated"])

    def test_temperature_normalization(self):
        rows = self.force_rows()
        for index, row in enumerate(rows):
            temperature = 10 + 10 * index
            row["temperature_C"] = temperature
            row["force_N_each"] *= (temperature + 273.15) / 293.15
        metadata = self.metadata()
        metadata["units"]["temperature_C"] = "degC"
        fit = fit_force_curve(self.write_csv("temperature.csv", rows, metadata))
        self.assertLess(fit["validation_metrics_N_each"]["rmse"], 1e-10)

    def test_replay_metrics_and_explicit_limits(self):
        run = simulate(duration_s=0.5)
        rows = [{"time_s": r["time_s"], "angle_rad": r["angle_rad"] + .01} for r in run["trace"][::5]]
        path = self.write_csv("angles.csv", rows, self.metadata("trajectory"))
        result = compare_trajectory(path, run, acceptance_limits={"angle_rmse_rad": .02})
        self.assertAlmostEqual(result["metrics"]["angle_rad"]["rmse"], .01)
        self.assertTrue(result["acceptance_passed"])
        self.assertIsNone(compare_trajectory(path, run)["acceptance_passed"])
        self.assertFalse(compare_trajectory(path, run, acceptance_limits={"angle_rmse_rad": .005})["acceptance_passed"])
        self.assertFalse(result["provenance"]["hardware_validated"])

    def test_replay_refuses_extrapolation_and_bad_timestamps(self):
        rows = [{"time_s": t, "angle_rad": .1} for t in [0, .5, 1]]
        path = self.write_csv("long.csv", rows)
        with self.assertRaisesRegex(ValueError, "extrapolation refused"):
            compare_trajectory(path, simulate(duration_s=.8))
        rows[-1]["time_s"] = .4
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            load_measurement_csv(self.write_csv("time.csv", rows), kind="trajectory")

    def test_nonfinite_and_missing_values_rejected(self):
        rows = self.force_rows()
        rows[0]["force_N_each"] = float("nan")
        with self.assertRaisesRegex(ValueError, "must be finite"):
            fit_force_curve(self.write_csv("nan.csv", rows))
        path = self.root / "missing.csv"
        path.write_text("time_s,angle_rad\n0,0\n1,\n2,.2\n")
        with self.assertRaisesRegex(ValueError, "missing angle_rad"):
            load_measurement_csv(path, kind="trajectory")

    def test_export_and_measured_parameter_provenance(self):
        run = simulate(duration_s=.1, parameter_provenance={"source_kind": "measured", "source": "declared test rig"})
        output = export_trace_csv(run, self.root / "trace.csv")
        with output.open() as handle:
            self.assertEqual(len(list(csv.DictReader(handle))), len(run["trace"]))
        self.assertTrue(run["provenance"]["measured_data_used"])
        self.assertFalse(run["provenance"]["hardware_validated"])
        self.assertEqual(run["provenance"]["source_kind"], "synthetic")


if __name__ == "__main__":
    unittest.main()
