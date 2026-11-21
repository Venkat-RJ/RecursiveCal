"""Physical, information-boundary and protocol regressions for the connected rig."""
from copy import deepcopy
from dataclasses import asdict, replace
import math
import unittest

import numpy as np

from recursivecal_lab.inquiry import (BayesianInvestigator, InquirySession, digest,
                                    public_result, run_study, verify_report)
from recursivecal_lab.physical_rig import (Calibration, PhysicalRig, RigState, run_experiment,
                                         run_motion, controller_command)
from recursivecal_lab.physics import ModelParameters


class MechanicalFoundationTests(unittest.TestCase):
    def test_lag_solution_and_command_saturation(self):
        p = replace(ModelParameters(), motor_efficiency=0.65)
        rig = PhysicalRig(p)
        for _ in range(20):
            step = rig.advance(100000, 0.01)
        expected = 330 * 0.65 * (1 - math.exp(-0.2 / 0.06))
        self.assertAlmostEqual(rig.state.motor_force_N_each, expected, places=10)
        self.assertEqual(step['command_N_each'], 330)
        self.assertTrue(step['saturated'])

    def test_continuous_state_and_fork_do_not_reset_actuator(self):
        rig = PhysicalRig()
        for _ in range(17):
            rig.advance(-80, 0.01)
        branch = rig.fork()
        for _ in range(23):
            rig.advance(50, 0.01)
            branch.advance(50, 0.01)
        self.assertEqual(rig.state, branch.state)
        self.assertAlmostEqual(rig.state.time_s, 0.4)
        self.assertNotEqual(rig.state.motor_force_N_each, 0)

    def test_damping_dissipates_energy(self):
        p = replace(ModelParameters(), gravity_m_s2=0, gas_scale=0)
        rig = PhysicalRig(p, state=RigState(angle_rad=0.6, velocity_rad_s=0.4))
        energies = []
        for _ in range(50):
            energies.append(0.5 * p.inertia_kg_m2 * rig.state.velocity_rad_s**2)
            rig.advance(0, 0.01, powered=False)
        self.assertTrue(all(b <= a + 1e-12 for a, b in zip(energies, energies[1:])))
        self.assertLess(energies[-1], energies[0])

    def test_conservative_energy_converges_with_timestep(self):
        p = replace(ModelParameters(), gas_scale=0, friction_coulomb_Nm=0, friction_static_Nm=0,
                    friction_viscous_Nm_s=0, strut_damping_N_s_m_each=0)
        def energy(s):
            return 0.5 * p.inertia_kg_m2 * s.velocity_rad_s**2 - p.mass_kg * p.gravity_m_s2 * p.com_radius_m * math.cos(s.angle_rad + p.com_offset_rad)
        errors = []
        for dt in (0.02, 0.01, 0.005):
            rig = PhysicalRig(p, state=RigState(angle_rad=0.9, velocity_rad_s=-0.1))
            initial = energy(rig.state)
            for _ in range(round(0.2 / dt)):
                step = rig.advance(0, dt, powered=False)
                self.assertIsNone(step['contact'])
            errors.append(abs(energy(rig.state) - initial))
        self.assertLess(errors[1], errors[0] / 2)
        self.assertLess(errors[2], errors[1] / 2)

    def test_contact_cannot_hide_speed_breach(self):
        p = replace(ModelParameters(), gravity_m_s2=0, gas_scale=0, friction_coulomb_Nm=0,
                    friction_static_Nm=0, friction_viscous_Nm_s=0, strut_damping_N_s_m_each=0,
                    external_closing_torque_Nm=-24, speed_limit_rad_s=.03)
        rig = PhysicalRig(p, state=RigState(angle_rad=p.max_angle_rad - .0005, velocity_rad_s=.01))
        event = rig.advance(0, 0.02, powered=False)
        self.assertIsNotNone(event['contact'])
        self.assertTrue(event['speed_breach'])
        self.assertEqual(rig.state.velocity_rad_s, 0)
        self.assertGreater(event['precontact_speed_rad_s'], .03)

    def test_sensor_seed_and_noise_do_not_change_physics(self):
        a, b = PhysicalRig(seed=7), PhysicalRig(seed=7)
        self.assertEqual(a.observe(), b.observe())
        state = a.state
        a.observe()
        self.assertEqual(a.state, state)
        keys = set(a.observe())
        self.assertEqual(keys, {'time_s', 'ambient_temperature_C', 'angle_rad', 'velocity_rad_s', 'strut_force_N_each'})
        a.advance(-100, 0.01)
        b.advance(-100, 0.01)
        self.assertEqual(a.state, b.state)

    def test_exact_duration_and_power_loss_event(self):
        rig = PhysicalRig()
        run = run_motion(rig, start_angle_rad=math.radians(20), target_angle_rad=math.radians(25),
                         duration_s=0.553, power_loss_s=0.153, include_truth=True)
        self.assertAlmostEqual(run['trace'][-1]['time_s'], 0.553, places=12)
        events = [event for event in run['events'] if event['type'] == 'power_loss']
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(events[0]['time_s'], 0.153, places=12)
        self.assertTrue(all(row['command_N_each'] == 0 for row in run['trace'] if row['time_s'] > 0.153 + 0.011))

    def test_calibration_only_changes_controller(self):
        p = replace(ModelParameters(), mass_kg=30)
        rig = PhysicalRig(p)
        reading = rig.observe(noisy=False)
        target = (reading['angle_rad'], 0., 0.)
        a = controller_command(reading, target, Calibration())
        b = controller_command(reading, target, Calibration(mass_kg=30))
        self.assertNotEqual(a, b)
        self.assertEqual(rig.parameters, p)

    def test_bad_physical_inputs_fail_before_advancing(self):
        rig = PhysicalRig()
        before = rig.state
        for force, dt in ((float('nan'), .01), (1., 0), (True, .01), (1., .1)):
            with self.assertRaises(ValueError):
                rig.advance(force, dt)
        self.assertEqual(rig.state, before)


class SessionBoundaryTests(unittest.TestCase):
    def test_budget_copy_commit_and_sealed_truth(self):
        session = InquirySession(PhysicalRig(), max_tests=1, budget=.7)
        view = session.observe()
        view['measurement']['angle_rad'] = -100
        self.assertNotEqual(session.observe()['measurement']['angle_rad'], -100)
        with self.assertRaises(ValueError):
            session.sealed_records()
        with self.assertRaises(ValueError):
            session.step('high_sweep')
        after = session.step('hold')
        self.assertEqual(after['legal_actions'], [])
        self.assertEqual(after['budget_remaining'], 0)
        self.assertNotIn('metrics', after['history'][0])
        self.assertNotIn('parameters', str(after))
        session.commit(asdict(Calibration()), disposition='abstain')
        with self.assertRaises(ValueError):
            session.commit(asdict(Calibration()))
        with self.assertRaises(ValueError):
            session.step('hold')
        self.assertEqual(session.sealed_records()['cost'], .7)

    def test_explicit_fixture_and_continuity(self):
        rig = PhysicalRig()
        first = run_experiment(rig, 'hold', rig.observe(), include_truth=True)
        second = run_experiment(rig, 'mid_sweep', rig.observe(), include_truth=True)
        self.assertEqual(first['final_state'], second['initial_state'])
        fixture = run_experiment(rig, 'reference', rig.observe(), include_truth=True)
        self.assertEqual(fixture['initial_state'], second['final_state'])
        self.assertAlmostEqual(fixture['final_state']['angle_rad'], math.radians(20))
        self.assertEqual(fixture['events'][0]['type'], 'external_fixture')
        self.assertAlmostEqual(fixture['final_state']['time_s'] - fixture['initial_state']['time_s'], .1)

    def test_hold_drift_cannot_satisfy_direction_coverage(self):
        rig = PhysicalRig(Calibration(mass_kg=30, motor_efficiency=.82, gas_scale=.75,
                                      friction_coulomb_Nm=14, sensor_bias_rad=-.025).model())
        initial = rig.observe()
        agent = BayesianInvestigator(initial)
        result = public_result(run_experiment(rig, 'hold', initial))
        agent.update({'action': 'hold', 'start_observation': initial, **result})
        self.assertEqual(agent.directions, set())

    def test_observation_allowlist_strips_privileged_fields(self):
        rig = PhysicalRig()
        result = run_experiment(rig, 'hold', rig.observe(), include_truth=True)
        result['parameters'] = {'secret': 123}
        result['observations'][0]['true_angle_rad'] = 123
        result['final_observation']['quality'] = 123
        visible = public_result(result)
        self.assertNotIn('123', str(visible))
        self.assertNotIn('tracking_rmse_deg', str(visible))
        self.assertNotIn('true_angle_rad', str(visible))


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.weak = run_study(case='weak_motor', seed=7)
        cls.compound = run_study(case='compound', seed=7)
        cls.outside = run_study(case='overload', seed=7)

    def test_known_fault_is_identified_and_verified(self):
        report = self.weak
        self.assertEqual(report['outcome'], 'verified_in_simulation')
        self.assertAlmostEqual(report['commitment']['estimates']['motor_efficiency'], .65, places=3)
        self.assertLess(report['verification']['after_mean_rmse_deg'], report['verification']['before_mean_rmse_deg'])
        self.assertEqual(set(report['final_belief']['directions_observed']), {'opening', 'closing'})
        self.assertFalse(report['verification']['system_ready_for_hardware'])

    def test_correct_identification_does_not_override_failed_verification(self):
        report = self.compound
        self.assertEqual(report['outcome'], 'verification_failed')
        self.assertAlmostEqual(report['commitment']['estimates']['mass_kg'], 30., places=3)
        cold = next(item for item in report['verification']['comparisons'] if item['name'] == 'cold_open')
        self.assertFalse(cold['after']['accepted'])
        self.assertGreater(abs(cold['after']['metrics']['final_error_deg']), 2.)

    def test_unexplained_data_triggers_fixture_and_abstention(self):
        report = self.outside
        self.assertTrue(report['final_belief']['model_mismatch'])
        self.assertEqual(report['outcome'], 'abstained')
        self.assertIn('reference', [row['action'] for row in report['agent_history']])
        self.assertEqual(report['commitment']['estimates'], asdict(Calibration()))

    def test_integrity_history_and_tamper_detection(self):
        for report in (self.weak, self.compound, self.outside):
            self.assertTrue(verify_report(report)['valid'])
            self.assertEqual(digest(report['agent_history']), report['commitment']['history_sha256'])
        altered = deepcopy(self.weak)
        altered['cost'] = 0
        self.assertFalse(verify_report(altered)['valid'])
        altered = deepcopy(self.compound)
        altered['outcome'] = 'verified_in_simulation'
        altered['report_sha256'] = digest({k:v for k,v in altered.items() if k != 'report_sha256'})
        self.assertFalse(verify_report(altered)['valid'])

    def test_posterior_replays_from_measurements_without_truth(self):
        report = self.weak
        replay = BayesianInvestigator(report['initial_observation']['measurement'], seed=7)
        for record in report['agent_history']:
            replay.update(record)
        for key, value in report['final_belief']['posterior_mean'].items():
            self.assertAlmostEqual(replay.summary()['posterior_mean'][key], value, places=10)

    def test_controller_cannot_fix_unpowered_support(self):
        hold = self.weak['verification']['passive_hold']
        self.assertFalse(hold['static']['can_hold_open_without_motor'])
        self.assertGreater(hold['static']['additional_holding_torque_required_Nm'], 50)
        self.assertLess(hold['run']['trace'][-1]['true_angle_rad'], math.radians(78))


if __name__ == '__main__':
    unittest.main()
