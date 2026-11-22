"""Physical laws and information/timing checks for the declared v3 mechanism."""
from dataclasses import replace
import math
import unittest

from recursivecal_lab.physics import ModelParameters, geometry, passive_hold
from recursivecal_lab.physical_rig import RigState, run_motion
from recursivecal_lab.research_rig import (
    ResearchRig, SensorParameters, electrical_interval,
)


def bare():
    return replace(ModelParameters(), gravity_m_s2=0, gas_scale=.4,
                   gas_force_extended_N_each=0, gas_force_compressed_N_each=0,
                   friction_coulomb_Nm=0, friction_static_Nm=0,
                   friction_viscous_Nm_s=0, strut_damping_N_s_m_each=0)


def exact_sensors(**changes):
    return replace(SensorParameters(), angle_noise_std_rad=0, velocity_noise_std_rad_s=0,
                   force_noise_std_N=0, angle_resolution_rad=0,
                   velocity_resolution_rad_s=0, force_resolution_N=0, **changes)


class ElectricalLawsTests(unittest.TestCase):
    def test_stall_current_and_energy_follow_rl_circuit(self):
        result = electrical_interval(0, 12, 0, .7, .006, .015, .03)
        self.assertAlmostEqual(result['current_A'], 12 / .7 * (1 - math.exp(-.7 * .03 / .006)), places=12)
        self.assertAlmostEqual(result['terminal_energy_J'],
                               result['resistive_loss_J'] + result['inductive_energy_change_J'], places=12)
        self.assertEqual(result['shaft_work_J'], 0)

    def test_motor_and_generator_obey_the_same_power_identity(self):
        for current, speed in ((2., 100.), (-2., 200.)):
            voltage = .7 * current + .015 * speed
            result = electrical_interval(current, voltage, speed, .7, .006, .015, .1)
            self.assertAlmostEqual(result['current_A'], current, places=12)
            self.assertAlmostEqual(result['shaft_work_J'], .015 * current * speed * .1, places=12)
            self.assertAlmostEqual(result['terminal_energy_J'], result['resistive_loss_J'] + result['shaft_work_J'], places=12)
        self.assertLess(result['terminal_energy_J'], 0)
        self.assertGreater(result['resistive_loss_J'], 0)

    def test_dump_circuit_dissipates_initial_magnetic_energy(self):
        result = electrical_interval(7, 0, 0, 3.7, .006, .015, .1)
        self.assertAlmostEqual(result['resistive_loss_J'], .5 * .006 * 7**2, places=12)
        self.assertAlmostEqual(result['current_A'], 0, places=12)
        self.assertEqual(result['terminal_energy_J'], 0)

    def test_inductor_energy_is_retained_through_reversal(self):
        result = electrical_interval(5, -12, 80, .7, .006, .015, .02)
        self.assertLess(result['current_A'], 0)
        self.assertAlmostEqual(result['terminal_energy_J'],
                               result['resistive_loss_J'] + result['shaft_work_J'] + result['inductive_energy_change_J'], places=12)


class ResearchMechanismTests(unittest.TestCase):
    def test_healthy_brake_holds_and_explicit_unbraked_case_falls(self):
        state = RigState(angle_rad=ModelParameters().max_angle_rad)
        healthy = ResearchRig(state=state)
        unbraked = ResearchRig(state=state, drive={'brake_capacity_Nm': 0})
        self.assertTrue(passive_hold(healthy.parameters)['can_hold_open_without_motor'])
        self.assertFalse(passive_hold(unbraked.parameters)['can_hold_open_without_motor'])
        for _ in range(50):
            healthy.advance(0, .01, powered=False)
            unbraked.advance(0, .01, powered=False)
        self.assertEqual(healthy.state.angle_rad, state.angle_rad)
        self.assertEqual(healthy.state.velocity_rad_s, 0)
        self.assertLess(unbraked.state.angle_rad, state.angle_rad - .01)
        self.assertFalse(unbraked.telemetry()['brake_engaged'])

    def test_gear_screw_transform_preserves_power_and_geometry(self):
        rig = ResearchRig(state=RigState(angle_rad=.6, velocity_rad_s=.2, motor_force_N_each=100))
        data = rig.telemetry()
        g = geometry(.6, rig.parameters)
        ratio = 2 * math.pi * rig.drive.gear_ratio / rig.drive.screw_lead_m
        self.assertAlmostEqual(data['left_motor_speed_rad_s'], ratio * g['lever_m'] * .2, places=12)
        self.assertAlmostEqual(data['left_rotor_angle_rad'] * rig.drive.screw_lead_m / (2 * math.pi * rig.drive.gear_ratio),
                               g['length_m'] - geometry(0, rig.parameters)['length_m'], places=12)
        shaft_power = rig.drive.torque_constant_Nm_A * data['left_current_A'] * data['left_motor_speed_rad_s']
        self.assertAlmostEqual(shaft_power, data['left_force_N'] * g['lever_m'] * .2, places=12)

    def test_sides_have_independent_effectiveness_and_thermal_state(self):
        rig = ResearchRig(state=RigState(angle_rad=ModelParameters().max_angle_rad), side_effectiveness=(1, .7))
        for _ in range(50):
            rig.advance(200, .01)
        data = rig.telemetry()
        self.assertAlmostEqual((data['right_force_N'] / data['right_current_A'])
                               / (data['left_force_N'] / data['left_current_A']), .7, places=10)
        self.assertAlmostEqual(rig.state.motor_force_N_each, (data['left_force_N'] + data['right_force_N']) / 2)
        self.assertGreater(data['left_temperature_C'], 20)

    def test_voltage_current_and_thermal_constraints_are_physical(self):
        rig = ResearchRig(replace(ModelParameters(), temperature_C=50),
                          state=RigState(angle_rad=ModelParameters().max_angle_rad),
                          drive={'max_current_A': 3, 'coil_heat_capacity_J_K': 5,
                                 'thermal_resistance_K_W': 30, 'derate_start_C': 50,
                                 'trip_temperature_C': 90})
        saturated = False
        for _ in range(1000):
            saturated |= rig.advance(330, .01)['saturated']
            data = rig.telemetry()
            self.assertLessEqual(abs(data['left_current_A']), 3 + 1e-10)
            self.assertLessEqual(abs(data['left_voltage_V']), 12 + 1e-10)
        self.assertTrue(saturated)
        self.assertGreater(data['left_temperature_C'], 50)
        self.assertLess(data['left_current_A'], 3)

    def test_power_loss_disconnects_supply_and_delays_brake(self):
        rig = ResearchRig(state=RigState(angle_rad=ModelParameters().max_angle_rad))
        for _ in range(30):
            rig.advance(200, .01)
        before = rig.telemetry()
        rig.advance(0, .01, powered=False)
        middle = rig.telemetry()
        self.assertFalse(middle['brake_engaged'])
        self.assertEqual(middle['left_electrical_energy_J'], before['left_electrical_energy_J'])
        self.assertGreater(middle['left_dump_loss_J'], before['left_dump_loss_J'])
        self.assertLess(abs(middle['left_current_A']), abs(before['left_current_A']))
        rig.advance(0, .01, powered=False)
        self.assertTrue(rig.telemetry()['brake_engaged'])

    def test_trip_disconnects_both_drives_and_obeys_brake_delay(self):
        rig = ResearchRig(state=RigState(angle_rad=ModelParameters().max_angle_rad))
        rig._motors[0] = replace(rig._motors[0], temperature_C=111)
        outcome = rig.advance(100, .005)
        self.assertTrue(outcome['drive_trip'])
        self.assertFalse(rig.telemetry()['brake_engaged'])
        self.assertEqual(rig.telemetry()['right_voltage_V'], 0)
        rig.advance(100, .015)
        self.assertTrue(rig.telemetry()['brake_engaged'])

    def test_complete_drive_energy_accounts_for_regeneration_and_storage(self):
        rig = ResearchRig(state=RigState(angle_rad=0))
        run_motion(rig, start_angle_rad=0, target_angle_rad=math.radians(78),
                   duration_s=5.8, profile_s=4.8, noisy=False)
        data = rig.telemetry()
        for side in ('left', 'right'):
            used = (data[side + '_copper_loss_J'] + data[side + '_dump_loss_J']
                    + data[side + '_shaft_work_J'] + data[side + '_inductive_energy_J']
                    - data[side + '_initial_inductive_energy_J'])
            self.assertAlmostEqual(data[side + '_electrical_energy_J'], used, places=9)
        self.assertLess(abs(data['coupling_residual_J']), .1)

    def test_coupling_and_motion_converge_under_internal_refinement(self):
        runs = []
        for dt in (.001, .0005, .00025):
            rig = ResearchRig(state=RigState(angle_rad=.4), drive={'integration_dt_s': dt},
                              sensors=exact_sensors(command_delay_s=0, latency_s=0))
            for _ in range(50):
                rig.advance(140, .01)
            runs.append((rig.state.angle_rad, abs(rig.telemetry()['coupling_residual_J'])))
        self.assertLess(abs(runs[1][0] - runs[2][0]), abs(runs[0][0] - runs[1][0]))
        self.assertLess(runs[1][1], runs[0][1])
        self.assertLess(runs[2][1], runs[1][1])

    def test_stiff_allowed_drive_is_subdivided_and_converges(self):
        states = []
        for dt in (.001, .0001):
            rig = ResearchRig(bare(), state=RigState(angle_rad=.5),
                              drive={'integration_dt_s': dt, 'current_kp_ohm': 2,
                                     'current_ki_ohm_s': 100, 'inductance_H': .001},
                              sensors=exact_sensors(command_delay_s=0, latency_s=0))
            self.assertLess(rig.metadata()['effective_internal_step_s'], .0001)
            for _ in range(10):
                rig.advance(50, .01)
            states.append(rig.state)
            self.assertGreater(rig.state.velocity_rad_s, .2)
            self.assertLess(abs(rig.telemetry()['coupling_residual_J']), .001)
        self.assertAlmostEqual(states[0].angle_rad, states[1].angle_rad, places=12)


class AcquisitionContractTests(unittest.TestCase):
    def test_command_delay_precedes_motor_response(self):
        rig = ResearchRig(bare(), sensors=exact_sensors(command_delay_s=.01))
        rig.advance(100, .005)
        rig.advance(100, .005)
        self.assertEqual(rig.telemetry()['left_current_A'], 0)
        rig.advance(100, .005)
        self.assertGreater(rig.telemetry()['left_current_A'], 0)

    def test_control_and_agent_use_the_same_delayed_held_sample(self):
        rig = ResearchRig(bare(), state=RigState(angle_rad=.4, velocity_rad_s=.1),
                          sensors=exact_sensors(latency_s=.02))
        initial = rig.observe(noisy=False)
        rig.advance(0, .02)
        delayed = rig.observe(noisy=False)
        self.assertEqual(delayed['angle_rad'], initial['angle_rad'])
        self.assertAlmostEqual(delayed['sensor_age_s'], .02)
        self.assertNotEqual(delayed['angle_rad'], rig.state.angle_rad)
        rig.advance(0, .01)
        delivered = rig.observe(noisy=False)
        self.assertAlmostEqual(delivered['sensor_sample_time_s'], .01)
        self.assertAlmostEqual(delivered['sensor_age_s'], .02)
        self.assertEqual(delivered, rig.control_observation(noisy=False))

    def test_quantization_and_noise_are_captured_once_per_sample(self):
        rig = ResearchRig(state=RigState(angle_rad=.30017), sensors={'angle_resolution_rad': .001}, seed=7)
        self.assertAlmostEqual(rig.observe(noisy=False)['angle_rad'], .300)
        first = rig.observe()
        for _ in range(20):
            self.assertEqual(rig.observe(), first)
        self.assertNotIn('left_current_A', first)
        self.assertNotIn('mass_kg', first)

    def test_fork_preserves_drive_heat_sensor_queues_and_random_state(self):
        rig = ResearchRig(seed=41, sensors={'dropout_probability': .1})
        for _ in range(23):
            rig.advance(140, .01)
        copy = rig.fork()
        for _ in range(30):
            self.assertEqual(rig.advance(-70, .007), copy.advance(-70, .007))
            self.assertEqual(rig.observe(), copy.observe())
            self.assertEqual(rig.telemetry(), copy.telemetry())
        self.assertEqual(rig.state, copy.state)

    def test_fixture_preserves_heat_and_explicit_time(self):
        rig = ResearchRig(state=RigState(angle_rad=ModelParameters().max_angle_rad))
        for _ in range(30):
            rig.advance(200, .01)
        before = rig.telemetry()
        t = rig.state.time_s
        rig.fixture(.4, .1)
        self.assertAlmostEqual(rig.state.time_s, t + .1)
        self.assertAlmostEqual(rig.state.angle_rad, .4)
        self.assertEqual(rig.state.velocity_rad_s, 0)
        self.assertEqual(rig.state.motor_force_N_each, 0)
        self.assertGreater(rig.telemetry()['left_temperature_C'], 20)
        self.assertGreater(rig.telemetry()['left_dump_loss_J'], before['left_dump_loss_J'])
        self.assertAlmostEqual(rig.observe(noisy=False)['angle_rad'], .4)

    def test_invalid_configs_and_inputs_fail_before_advancing(self):
        for kwargs in ({'drive': {'unknown': 1}}, {'sensors': {'latency_s': -.1}},
                       {'side_effectiveness': [1]}, {'drive': {'supply_voltage_V': True}}):
            with self.assertRaises(ValueError):
                ResearchRig(**kwargs)
        rig = ResearchRig()
        before = rig.telemetry(), rig.state, rig.observe()
        for command, duration in ((float('nan'), .01), (0, 0), (1, .03), (True, .01)):
            with self.assertRaises(ValueError):
                rig.advance(command, duration)
        self.assertEqual(before, (rig.telemetry(), rig.state, rig.observe()))


if __name__ == '__main__':
    unittest.main()
