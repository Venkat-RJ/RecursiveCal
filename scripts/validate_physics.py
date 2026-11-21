"""Independent numerical checks of the declared synthetic mechanics, in foreground.

Usage: python scripts/validate_physics.py --output PATH
Requires the validation extra. No policy training, network, hardware or GPU use.
The reference RHS rederives geometry and forces without production helpers.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
import platform
import random
import sys

import numpy as np
import scipy
from scipy.integrate import solve_ivp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from recursivecal_lab.physics import MODEL_ID, ModelParameters, advance_mechanics


def reference_geometry(q, p):
    # Independently express the moving anchor and its rotational velocity.
    anchor = np.array([p.hatch_anchor_x_m, -p.hatch_anchor_down_m])
    rotation = np.array([[np.cos(q), -np.sin(q)], [np.sin(q), np.cos(q)]])
    rotated = rotation @ anchor
    separation = rotated + np.array([-p.body_anchor_x_m, p.hinge_height_m - p.body_anchor_z_m])
    length = np.linalg.norm(separation)
    velocity_per_rad = np.array([-rotated[1], rotated[0]])
    return length, np.dot(separation, velocity_per_rad) / length


def reference_rhs(p, command):
    low, high = reference_geometry(0, p)[0], reference_geometry(p.max_angle_rad, p)[0]
    temperature = (273.15 + p.temperature_C) / (273.15 + p.gas_reference_temperature_C)
    def rhs(t, state):
        q, velocity, force = state
        length, leverage = reference_geometry(q, p)
        fraction = np.clip((length - low) / (high - low), 0, 1)
        gas = p.gas_scale * temperature * ((1 - fraction) * p.gas_force_compressed_N_each + fraction * p.gas_force_extended_N_each)
        gravity = p.mass_kg * p.gravity_m_s2 * p.com_radius_m * np.sin(q + p.com_offset_rad)
        resistive = (p.friction_viscous_Nm_s + 2 * p.strut_damping_N_s_m_each * leverage**2) * velocity
        acceleration = (2 * (force + gas) * leverage - gravity - p.external_closing_torque_Nm - resistive) / p.inertia_kg_m2
        return [velocity, acceleration, (command * p.motor_efficiency - force) / p.actuator_time_constant_s]
    return rhs


def reference(p, initial, commands, interval=.04):
    times, states = [0.0], [np.asarray(initial)]
    for index, command in enumerate(commands):
        begin, end = index * interval, (index + 1) * interval
        sol = solve_ivp(reference_rhs(p, command), (begin, end), states[-1], method='DOP853',
                        rtol=2e-12, atol=2e-13, max_step=.005, t_eval=[end])
        if not sol.success:
            raise RuntimeError(sol.message)
        times.append(end)
        states.append(sol.y[:, -1])
    return np.asarray(times), np.asarray(states)


def production(p, initial, commands, dt, interval=.04):
    q, velocity, force = initial
    states, contacts = [initial], 0
    for command in commands:
        for _ in range(round(interval / dt)):
            step = advance_mechanics(q, velocity, force, command * p.motor_efficiency, dt, p, powered=True)
            contacts += len(step['contacts'])
            q, velocity, force = step['angle_rad'], step['velocity_rad_s'], step['motor_force_N_each']
        states.append((q, velocity, force))
    return np.asarray(states), contacts


def run_audit():
    rng = random.Random(271828)
    step_sizes = (.02, .01, .005, .0025)
    records = []
    print('Comparing 24 smooth mechanisms with independent DOP853 trajectories.', flush=True)
    for case in range(24):
        mass, radius = rng.uniform(18, 36), rng.uniform(.45, .65)
        p = replace(ModelParameters(), mass_kg=mass, com_radius_m=radius,
                    inertia_kg_m2=mass * radius**2 + rng.uniform(3, 8),
                    gas_scale=rng.uniform(.5, 1.3), temperature_C=rng.uniform(-20, 60),
                    motor_efficiency=rng.uniform(.5, 1.1), actuator_time_constant_s=rng.uniform(.02, .12),
                    friction_coulomb_Nm=0, friction_static_Nm=0,
                    friction_viscous_Nm_s=rng.uniform(0, 12), strut_damping_N_s_m_each=rng.uniform(0, 12),
                    body_anchor_x_m=rng.uniform(-.50, -.44), body_anchor_z_m=rng.uniform(1.14, 1.20)).validate()
        initial = (.7, rng.uniform(-.15, .15), rng.uniform(-20, 20))
        commands = [rng.uniform(-50, 150) for _ in range(5)]
        times, truth = reference(p, initial, commands)
        errors = []
        for dt in step_sizes:
            actual, contacts = production(p, initial, commands, dt)
            delta = np.max(np.abs(actual - truth), axis=0)
            errors.append({'dt_s': dt, 'max_angle_error_deg': float(np.degrees(delta[0])),
                           'max_velocity_error_rad_s': float(delta[1]), 'max_motor_force_error_N': float(delta[2]),
                           'contacts': contacts})
        records.append({'case': case, 'parameters': asdict(p), 'initial_state': initial,
                        'command_N_each': commands, 'command_interval_s': .04, 'comparison_times_s': times.tolist(),
                        'reference_states': truth.tolist(), 'errors': errors})
    maxima = [{key: max(row['errors'][index][key] for row in records)
               for key in ('max_angle_error_deg', 'max_velocity_error_rad_s', 'max_motor_force_error_N', 'contacts')}
              | {'dt_s': dt} for index, dt in enumerate(step_sizes)]

    print('Checking three motor-reversal contact cases with independent event roots.', flush=True)
    contact_cases = []
    for name, tau, gap, velocity, force, command in (
        ('fast_reversal_above_impact_limit', .001, .0014, .2, 330, -330),
        ('fast_reversal_previously_missed_contact', .001, .002, .2, 330, -330),
        ('nominal_lag_previously_false_contact', .06, .0006, .1, -330, 330),
    ):
        p = replace(ModelParameters(), gravity_m_s2=0, gas_scale=0,
                    friction_coulomb_Nm=0, friction_static_Nm=0,
                    friction_viscous_Nm_s=0, strut_damping_N_s_m_each=0,
                    actuator_time_constant_s=tau).validate()
        initial = (p.max_angle_rad - gap, velocity, force)
        def upper_stop(t, y):
            return y[0] - p.max_angle_rad
        upper_stop.direction = 1
        upper_stop.terminal = True
        sol = solve_ivp(reference_rhs(p, command), (0, .02), initial, method='DOP853',
                        rtol=2e-12, atol=2e-13, max_step=.00005, events=upper_stop)
        if not sol.success:
            raise RuntimeError(sol.message)
        actual = advance_mechanics(*initial, command, .02, p, powered=True)
        reference_contact = bool(len(sol.t_events[0]))
        row = {'name': name, 'parameters': asdict(p), 'initial_state': initial, 'command_N_each': command,
               'dt_s': .02, 'reference_contact': reference_contact, 'actual_contacts': actual['contacts'],
               'classification_matches': reference_contact == bool(actual['contacts'])}
        if reference_contact and actual['contacts']:
            row.update(reference_time_s=float(sol.t_events[0][0]),
                       reference_speed_rad_s=float(abs(sol.y_events[0][0][1])))
            row['time_error_s'] = abs(row['reference_time_s'] - actual['contacts'][0]['time_offset_s'])
            row['speed_error_rad_s'] = abs(row['reference_speed_rad_s'] - actual['contacts'][0]['incident_speed_rad_s'])
        contact_cases.append(row)

    print('Checking 60 seconds of conservative oscillation at three step sizes.', flush=True)
    p = replace(ModelParameters(), com_offset_rad=-.65, gas_scale=0, friction_coulomb_Nm=0,
                friction_static_Nm=0, friction_viscous_Nm_s=0, strut_damping_N_s_m_each=0).validate()
    initial = (.85, 0, 0)
    # Independent potential and RHS. The stable equilibrium is inside both stops.
    strength = p.mass_kg * p.gravity_m_s2 * p.com_radius_m
    def pendulum_rhs(t, y):
        return [y[1], -strength / p.inertia_kg_m2 * np.sin(y[0] - .65)]
    times = np.linspace(0, 60, 3001)
    ref = solve_ivp(pendulum_rhs, (0, 60), initial[:2], method='DOP853',
                    rtol=2e-12, atol=2e-13, max_step=.04, t_eval=times)
    if not ref.success:
        raise RuntimeError(ref.message)
    initial_energy = strength * (1 - math.cos(.2))
    long_runs = []
    for dt in (.02, .01, .005):
        q, velocity, force = initial
        maximum_energy_error = maximum_angle_error = 0.0
        contacts = 0
        sample_every = round(.02 / dt)
        for index in range(1, round(60 / dt) + 1):
            step = advance_mechanics(q, velocity, force, 0, dt, p, powered=False)
            q, velocity, force = step['angle_rad'], step['velocity_rad_s'], step['motor_force_N_each']
            contacts += len(step['contacts'])
            energy = .5 * p.inertia_kg_m2 * velocity**2 + strength * (1 - math.cos(q - .65))
            maximum_energy_error = max(maximum_energy_error, abs(energy - initial_energy))
            if index % sample_every == 0:
                maximum_angle_error = max(maximum_angle_error, abs(q - ref.y[0, index // sample_every]))
        long_runs.append({'dt_s': dt, 'duration_s': 60, 'energy_excursion_J': maximum_energy_error,
                          'relative_energy_excursion': maximum_energy_error / initial_energy,
                          'maximum_angle_error_deg': math.degrees(maximum_angle_error), 'contacts': contacts})

    gates = {
        'all_smooth_states_finite': all(np.isfinite(row['reference_states']).all() for row in records),
        'smooth_cases_avoid_contact': all(row['contacts'] == 0 for row in maxima),
        '10ms_angle_error_below_0_01_degree': maxima[1]['max_angle_error_deg'] < .01,
        '10ms_velocity_error_below_0_002_rad_s': maxima[1]['max_velocity_error_rad_s'] < .002,
        'motor_lag_error_below_1e_8_N': all(row['max_motor_force_error_N'] < 1e-8 for row in maxima),
        'angle_refinement_at_least_1_8_per_halving': all(b['max_angle_error_deg'] < a['max_angle_error_deg'] / 1.8 for a, b in zip(maxima, maxima[1:])),
        'velocity_refinement_at_least_1_8_per_halving': all(b['max_velocity_error_rad_s'] < a['max_velocity_error_rad_s'] / 1.8 for a, b in zip(maxima, maxima[1:])),
        'long_run_avoids_contact': all(row['contacts'] == 0 for row in long_runs),
        'long_run_10ms_relative_energy_excursion_below_0_001': long_runs[1]['relative_energy_excursion'] < .001,
        'long_run_10ms_angle_error_below_0_3_degree': long_runs[1]['maximum_angle_error_deg'] < .3,
        'long_run_angle_error_refines': all(b['maximum_angle_error_deg'] < a['maximum_angle_error_deg'] / 2 for a, b in zip(long_runs, long_runs[1:])),
        'long_run_energy_error_refines': all(b['energy_excursion_J'] < a['energy_excursion_J'] / 2 for a, b in zip(long_runs, long_runs[1:])),
        'motor_reversal_contact_classifications_match': all(row['classification_matches'] for row in contact_cases),
        'motor_reversal_contact_time_error_below_20_us': all(row.get('time_error_s', 0) < 2e-5 for row in contact_cases),
        'motor_reversal_contact_speed_error_below_0_0002_rad_s': all(row.get('speed_error_rad_s', 0) < 2e-4 for row in contact_cases),
        'fast_reversal_correctly_exceeds_impact_cutoff': bool(contact_cases[0]['actual_contacts']) and contact_cases[0]['actual_contacts'][0]['incident_speed_rad_s'] > .12,
    }
    source_paths = ['recursivecal_lab/physics.py', 'recursivecal_lab/physical_rig.py',
                    'scripts/validate_physics.py', 'tests/test_mechanics_foundation_v2.py']
    return {'schema_version': 'recursivecal.physics-validation/1', 'model_id': MODEL_ID,
            'scope': 'Numerical verification of synthetic equations, not measured-hardware validation. The 24-case trajectory envelope excludes dry friction and contact. Three additional motor-reversal cases check contact event roots. Analytical tests separately cover sticking and sliding.',
            'hardware_validated': False, 'measured_data_used': False,
            'reference_method': 'Independent force/geometry implementation, SciPy DOP853, rtol 2e-12, atol 2e-13.',
            'runtime': {'python': platform.python_version(), 'numpy': np.__version__, 'scipy': scipy.__version__},
            'source_sha256': {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in source_paths},
            'gates': gates, 'passed': all(gates.values()), 'smooth_maxima': maxima,
            'long_conservative_runs': long_runs, 'smooth_cases': records, 'motor_reversal_contacts': contact_cases}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = run_audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({key: report[key] for key in ('passed', 'gates', 'smooth_maxima', 'long_conservative_runs')}, indent=2), flush=True)
    raise SystemExit(0 if report['passed'] else 1)
