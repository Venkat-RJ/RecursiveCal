"""Physical identities, failure behavior, and numerical regression checks."""
import json
import math
from dataclasses import replace
import unittest

from recursivecal_lab.physics import ModelParameters, gas_force, geometry, passive_hold, simulate


class PhysicalModelTests(unittest.TestCase):
    def test_geometry_derivative_and_virtual_work(self):
        for angle in (0.1, 0.4, 0.8, 1.2):
            h = 1e-6
            derivative = (geometry(angle + h)["length_m"] - geometry(angle - h)["length_m"]) / (2 * h)
            self.assertAlmostEqual(derivative, geometry(angle)["lever_m"], places=9)
        # A constant two-strut force must do 2 F delta-length of work.
        steps, force = 2000, 100.0
        q0, q1 = 0.1, 1.2
        dq = (q1 - q0) / steps
        work = sum(2 * force * geometry(q0 + (i + 0.5) * dq)["lever_m"] * dq for i in range(steps))
        exact = 2 * force * (geometry(q1)["length_m"] - geometry(q0)["length_m"])
        self.assertAlmostEqual(work, exact, places=5)

    def test_open_hold_failure_and_explicit_brake(self):
        nominal = passive_hold()
        self.assertFalse(nominal["can_hold_open_without_motor"])
        self.assertGreater(nominal["additional_holding_torque_required_Nm"], 57)
        falling = simulate(scenario="passive_hold", duration_s=1)
        self.assertEqual(falling["metrics"]["termination"], "aborted_speed_limit")
        self.assertLess(falling["metrics"]["completed_duration_s"], 1)
        held = simulate(replace(ModelParameters(), holding_brake_Nm=70), scenario="passive_hold", duration_s=1)
        self.assertTrue(held["metrics"]["passive_hold"]["can_hold_open_without_motor"])
        self.assertEqual(held["metrics"]["peak_speed_rad_s"], 0)
        self.assertEqual(held["metrics"]["termination"], "completed")

    def test_exact_duration_reproducibility_and_provenance(self):
        run = simulate(duration_s=0.553, dt_s=0.02, seed=8)
        self.assertEqual(run["trace"][-1]["time_s"], 0.553)
        self.assertEqual(run, simulate(duration_s=0.553, dt_s=0.02, seed=8))
        self.assertFalse(run["provenance"]["hardware_validated"])
        self.assertFalse(run["provenance"]["measured_data_used"])
        json.dumps(run, allow_nan=False)

    def test_timestep_refinement_reduces_trajectory_error(self):
        angles = [simulate(dt_s=dt, duration_s=2.553)["trace"][-1]["angle_rad"]
                  for dt in (0.02, 0.01, 0.005, 0.0025)]
        self.assertLess(abs(angles[2] - angles[3]), abs(angles[1] - angles[3]))
        self.assertLess(abs(angles[1] - angles[3]), abs(angles[0] - angles[3]))
        self.assertLess(abs(angles[0] - angles[3]), 0.004)

    def test_conservative_energy_converges_before_contact(self):
        p = replace(ModelParameters(), gas_scale=0, friction_coulomb_Nm=0, friction_static_Nm=0,
                    friction_viscous_Nm_s=0, strut_damping_N_s_m_each=0)
        drifts = []
        for dt in (0.02, 0.01, 0.005):
            run = simulate(p, dt_s=dt, duration_s=0.2, controller="disabled", initial_angle_rad=0.8, abort_on_limit=False)
            def energy(row):
                return 0.5 * p.inertia_kg_m2 * row["velocity_rad_s"] ** 2 - p.mass_kg * p.gravity_m_s2 * p.com_radius_m * math.cos(row["angle_rad"] + p.com_offset_rad)
            drifts.append(abs(energy(run["trace"][-1]) - energy(run["trace"][0])))
            self.assertFalse(any("stop" in event["type"] for event in run["events"]))
        self.assertLess(drifts[1], drifts[0] / 3)
        self.assertLess(drifts[2], drifts[1] / 3)

    def test_actuator_lag_and_bounds(self):
        p = replace(ModelParameters(), motor_efficiency=0.4)
        run = simulate(p, duration_s=0.5)
        self.assertEqual(run["trace"][0]["motor_force_N_each"], 0)
        self.assertTrue(all(abs(row["motor_force_N_each"]) <= 330 * 0.4 + 1e-9 for row in run["trace"]))
        self.assertTrue(all(0 <= row["angle_rad"] <= p.max_angle_rad for row in run["trace"]))
        self.assertEqual(run["controller_parameters"]["motor_efficiency"], 1)

    def test_power_loss_boundary_not_rounded_to_timestep(self):
        p = replace(ModelParameters(), power_loss_time_s=0.153)
        run = simulate(p, scenario="power_loss", dt_s=0.02, duration_s=0.4, abort_on_limit=False)
        loss = [event for event in run["events"] if event["type"] == "power_loss"]
        self.assertEqual(loss[0]["time_s"], 0.153)
        self.assertTrue(all(not row["motor_powered"] for row in run["trace"] if row["time_s"] >= 0.153))

    def test_temperature_is_explicit_assumption(self):
        p = ModelParameters()
        hotter = replace(p, temperature_C=40)
        self.assertAlmostEqual(gas_force(0.5, hotter) / gas_force(0.5, p), 313.15 / 293.15)

    def test_bad_inputs_rejected(self):
        for kwargs in ({"dt_s": 0}, {"duration_s": float("nan")}, {"scenario": "unknown"},
                       {"parameters": {"mass_kg": -1}}, {"parameters": {"mass_kg": True}},
                       {"parameters": {"friction_static_Nm": 1}}, {"parameters": {"typo": 1}},
                       {"initial_angle_rad": -1}, {"seed": "wrong"},
                       {"parameters": {"mass_kg": 1e308}}, {"initial_velocity_rad_s": 1e308}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                simulate(**kwargs)


if __name__ == "__main__":
    unittest.main()
