"""Analytical mechanics and event regressions, independent of policy scores."""
from dataclasses import replace
import math
import unittest

from recursivecal_lab.physics import (ModelParameters, _friction_flow, _lagged_flow,
    advance_mechanics, geometry, gas_force, gravity_torque, mechanical_energy, simulate)
from recursivecal_lab.physical_rig import PhysicalRig, RigState, run_motion, run_experiment


def bare(**changes):
    return replace(ModelParameters(), gravity_m_s2=0, gas_scale=0,
                   friction_coulomb_Nm=0, friction_static_Nm=0,
                   friction_viscous_Nm_s=0, strut_damping_N_s_m_each=0,
                   **changes)


class AnalyticalMechanicsTests(unittest.TestCase):
    def test_stopping_distance_and_stiction_with_viscosity(self):
        p = ModelParameters()
        velocity, distance, stopped = _friction_flow(.001, -7, 5, .02, p)
        exact_stop = p.inertia_kg_m2 / 5 * math.log1p(5 * .001 / 13)
        equilibrium = -13 / 5
        exact_distance = equilibrium * exact_stop + (.001 - equilibrium) * p.inertia_kg_m2 / 5 * (-math.expm1(-5 * exact_stop / p.inertia_kg_m2))
        self.assertEqual(velocity, 0)
        self.assertAlmostEqual(stopped, exact_stop, places=14)
        self.assertAlmostEqual(distance, exact_distance, places=13)
        self.assertLess(distance, 1e-6)

    def test_coulomb_stopping_distance(self):
        p = ModelParameters()
        velocity, distance, stopped = _friction_flow(.01, -7, 0, .02, p)
        acceleration = -13 / p.inertia_kg_m2
        exact_stop = -.01 / acceleration
        self.assertEqual(velocity, 0)
        self.assertAlmostEqual(stopped, exact_stop, places=14)
        self.assertAlmostEqual(distance, -.01**2 / (2 * acceleration), places=14)

    def test_reversal_uses_remaining_time_and_new_friction_direction(self):
        p = ModelParameters()
        velocity, distance, stopped = _friction_flow(.01, -20, 0, .04, p, closing_extra=4)
        tstop = p.inertia_kg_m2 * .01 / 26
        remaining = .04 - tstop
        acceleration_after = (-20 + 6 + 4) / p.inertia_kg_m2
        self.assertAlmostEqual(stopped, tstop, places=14)
        self.assertAlmostEqual(velocity, acceleration_after * remaining, places=14)
        self.assertAlmostEqual(distance, .01 * tstop / 2 + acceleration_after * remaining**2 / 2, places=14)

    def test_directional_static_threshold_can_prevent_reversal(self):
        p = ModelParameters()
        self.assertEqual(_friction_flow(.001, -10, 0, .04, p, closing_extra=4)[0], 0)
        self.assertGreater(_friction_flow(0, 10, 0, .04, p, closing_extra=4)[0], 0)

    def test_zero_damping_limit_is_well_conditioned(self):
        p = bare()
        exact = _friction_flow(.2, 7, 0, .02, p)
        for damping in (1e-14, 1e-10, 1e-6):
            actual = _friction_flow(.2, 7, damping, .02, p)
            self.assertAlmostEqual(actual[0], exact[0], delta=1e-9)
            self.assertAlmostEqual(actual[1], exact[1], delta=1e-11)

    def test_coincident_motor_and_damping_rates_are_well_conditioned(self):
        p = bare()
        k, t, arm, target, initial_force, initial_v = 1 / p.actuator_time_constant_s, .02, .2, 100, 20, .1
        decay = math.exp(-k*t)
        c, beta = 2*arm*target, 2*arm*(initial_force-target)
        exact_v = initial_v*decay + c/(p.inertia_kg_m2*k)*(1-decay) + beta/p.inertia_kg_m2*t*decay
        exact_q = (initial_v/k*(1-decay) + c/(p.inertia_kg_m2*k)*(t-(1-decay)/k)
                   + beta/(p.inertia_kg_m2*k*k)*(1-(1+k*t)*decay))
        for relative in (0, 1e-10, -1e-10):
            flow = _lagged_flow(initial_v, 0, initial_force, target, arm,
                                p.inertia_kg_m2*k*(1+relative), t, p, 0, 0)
            self.assertAlmostEqual(flow.velocity, exact_v, delta=1e-11)
            self.assertAlmostEqual(flow.displacement, exact_q, delta=1e-12)

    def test_parallel_axis_inertia_validation(self):
        with self.assertRaisesRegex(ValueError, 'hinge inertia'):
            replace(ModelParameters(), inertia_kg_m2=.02).validate()
        p = ModelParameters()
        replace(p, inertia_kg_m2=p.mass_kg * p.com_radius_m**2).validate()

    def test_gas_gravity_and_external_load_have_correct_potential(self):
        for p in (ModelParameters(), replace(ModelParameters(), temperature_C=40, external_closing_torque_Nm=7)):
            for q in (.1, .5, 1.2):
                h = 1e-6
                negative_gradient = -(mechanical_energy(q + h, 0, p) - mechanical_energy(q - h, 0, p)) / (2 * h)
                actual = 2 * gas_force(q, p) * geometry(q, p)['lever_m'] - gravity_torque(q, p)
                self.assertAlmostEqual(negative_gradient, actual, delta=5e-8)

    def test_impact_time_speed_and_energy_are_localized(self):
        p = bare(external_closing_torque_Nm=-24, speed_limit_rad_s=.03)
        q = p.max_angle_rad - .0005
        exact_speed = math.sqrt(.01**2 + 2 * 2 * .0005)
        exact_time = (exact_speed - .01) / 2
        step = advance_mechanics(q, .01, 0, 0, .02, p, powered=False)
        contact = step['contacts'][0]
        self.assertAlmostEqual(contact['time_offset_s'], exact_time, places=12)
        self.assertAlmostEqual(contact['incident_speed_rad_s'], exact_speed, places=12)
        self.assertAlmostEqual(contact['kinetic_energy_loss_J'], .5 * p.inertia_kg_m2 * exact_speed**2, places=12)
        self.assertEqual(step['angle_rad'], p.max_angle_rad)
        self.assertEqual(step['velocity_rad_s'], 0)

    def test_impact_cannot_hide_real_speed_limit_breach(self):
        p = bare(external_closing_torque_Nm=-24, speed_limit_rad_s=.03)
        run = simulate(p, controller='disabled', duration_s=.02, dt_s=.02,
                       initial_angle_rad=p.max_angle_rad - .0005, initial_velocity_rad_s=.01)
        self.assertEqual(run['metrics']['termination'], 'aborted_speed_limit')
        self.assertGreater(run['metrics']['peak_speed_rad_s'], .03)
        self.assertEqual(run['trace'][-1]['velocity_rad_s'], 0)

    def test_motion_through_stop_is_not_counted_as_a_speed_breach(self):
        p = bare(external_closing_torque_Nm=-24, speed_limit_rad_s=.03)
        run = simulate(p, controller='disabled', duration_s=.02, dt_s=.02,
                       initial_angle_rad=p.max_angle_rad - .00001, initial_velocity_rad_s=.01)
        self.assertEqual(run['metrics']['termination'], 'completed')
        self.assertLess(run['metrics']['peak_speed_rad_s'], .03)
        self.assertAlmostEqual(run['metrics']['peak_speed_rad_s'], math.sqrt(.01**2 + 4 * .00001), places=11)

    def test_sustained_contact_and_inward_release(self):
        p = bare(external_closing_torque_Nm=-24)
        held = advance_mechanics(p.max_angle_rad, 0, 0, 0, .02, p, powered=False)
        self.assertEqual(held['angle_rad'], p.max_angle_rad)
        self.assertEqual(held['mechanical_work_abs_J'], 0)
        self.assertEqual(held['contacts'], [])
        inward = replace(p, external_closing_torque_Nm=24)
        released = advance_mechanics(p.max_angle_rad, 0, 0, 0, .02, inward, powered=False)
        self.assertAlmostEqual(released['angle_rad'], p.max_angle_rad - .5 * 2 * .02**2, places=12)
        self.assertAlmostEqual(released['velocity_rad_s'], -.04, places=12)

    def test_remaining_time_after_impact_is_integrated(self):
        p = bare(external_closing_torque_Nm=24)
        step = advance_mechanics(p.max_angle_rad - .001, .2, 0, 0, .02, p, powered=False)
        impact_time = (.2 - math.sqrt(.2**2 - 4 * .001)) / 2
        remainder = .02 - impact_time
        self.assertEqual(len(step['contacts']), 1)
        self.assertAlmostEqual(step['contacts'][0]['time_offset_s'], impact_time, places=12)
        self.assertAlmostEqual(step['angle_rad'], p.max_angle_rad - remainder**2, places=12)
        self.assertAlmostEqual(step['velocity_rad_s'], -2 * remainder, places=12)

    def test_lag_does_not_break_static_friction_early(self):
        p = replace(bare(), friction_coulomb_Nm=6, friction_static_Nm=8)
        q = .5
        arm = geometry(q, p)['lever_m']
        breakaway = -p.actuator_time_constant_s * math.log1p(-8 / (2 * arm * 100))
        held = advance_mechanics(q, 0, 0, 100, breakaway * .9, p, powered=True)
        self.assertEqual(held['angle_rad'], q)
        self.assertEqual(held['velocity_rad_s'], 0)
        moved = advance_mechanics(q, 0, 0, 100, breakaway + .003, p, powered=True)
        self.assertGreater(moved['angle_rad'], q)
        self.assertGreater(moved['velocity_rad_s'], 0)

    def test_simulator_and_persistent_rig_share_unpowered_trajectory(self):
        p = ModelParameters()
        run = simulate(p, controller='disabled', duration_s=.12, dt_s=.01,
                       initial_angle_rad=.5, initial_velocity_rad_s=-.1, abort_on_limit=False)
        rig = PhysicalRig(p, state=RigState(angle_rad=.5, velocity_rad_s=-.1))
        for row in run['trace'][1:]:
            rig.advance(0, .01, powered=False)
            self.assertAlmostEqual(rig.state.angle_rad, row['angle_rad'], places=12)
            self.assertAlmostEqual(rig.state.velocity_rad_s, row['velocity_rad_s'], places=12)

    def test_fast_motor_reversal_preserves_impact_decision(self):
        p = bare(actuator_time_constant_s=.001)
        step = advance_mechanics(p.max_angle_rad - .0014, .2, 330, -330, .02, p, powered=True)
        self.assertEqual(len(step['contacts']), 1)
        self.assertGreater(step['contacts'][0]['incident_speed_rad_s'], .12)
        # Independent DOP853 continuous-mechanics values, reproduced by the audit.
        self.assertAlmostEqual(step['contacts'][0]['time_offset_s'], .00805088758, delta=2e-5)
        self.assertAlmostEqual(step['contacts'][0]['incident_speed_rad_s'], .13052868, delta=2e-4)
        farther = advance_mechanics(p.max_angle_rad - .002, .2, 330, -330, .02, p, powered=True)
        self.assertEqual(len(farther['contacts']), 1)

    def test_changing_motor_force_does_not_invent_contact(self):
        p = bare()
        step = advance_mechanics(p.max_angle_rad - .0006, .1, -330, 330, .02, p, powered=True)
        self.assertEqual(step['contacts'], [])


class ExperimentTimingTests(unittest.TestCase):
    def test_nearby_sampling_boundary_cannot_duplicate_power_loss(self):
        for cutoff in (.02 - 5e-11, .02 + 5e-11):
            result = run_motion(PhysicalRig(), start_angle_rad=.35, target_angle_rad=.35,
                                duration_s=.06, power_loss_s=cutoff, noisy=False)
            events = [event for event in result['events'] if event['type'] == 'power_loss']
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]['time_s'], cutoff)

    def test_power_loss_events_at_zero_grid_between_and_final(self):
        for cutoff in (0, .02, .023, .053):
            rig = PhysicalRig()
            result = run_motion(rig, start_angle_rad=math.radians(20),
                                target_angle_rad=math.radians(20), duration_s=.053,
                                power_loss_s=cutoff, noisy=False)
            events = [event for event in result['events'] if event['type'] == 'power_loss']
            self.assertEqual(len(events), 1)
            self.assertAlmostEqual(events[0]['time_s'], cutoff, places=12)
            if cutoff == 0:
                self.assertTrue(all(row['command_N_each'] == 0 for row in result['trace']))

    def test_sub_microsecond_event_remainder_is_valid(self):
        rig = PhysicalRig()
        run = run_motion(rig, start_angle_rad=.35, target_angle_rad=.35,
                         duration_s=.06, power_loss_s=.0200001, noisy=False)
        self.assertAlmostEqual(run['metrics']['completed_duration_s'], .06, places=12)
        self.assertAlmostEqual([e for e in run['events'] if e['type'] == 'power_loss'][0]['time_s'], .0200001, places=12)

    def test_fixture_samples_are_taken_at_their_recorded_times(self):
        rig = PhysicalRig(state=RigState(time_s=2.1))
        sampled_at = []
        original = rig.observe
        def observed(**kwargs):
            sampled_at.append(rig.state.time_s)
            return original(**kwargs)
        rig.observe = observed
        result = run_experiment(rig, 'reference', original(noisy=False), noisy=False)
        self.assertEqual(sampled_at, [row['time_s'] for row in result['observations']])
        self.assertTrue(all(b > a for a, b in zip(sampled_at, sampled_at[1:])))


if __name__ == '__main__':
    unittest.main()
