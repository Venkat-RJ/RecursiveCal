"""Executable numerical checks for the historical exploratory research module."""
import sys
from pathlib import Path
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if (_PROJECT_ROOT / "recursivecal.py").exists():
    sys.path.insert(0, str(_PROJECT_ROOT))
import math
import unittest
import numpy as np
import recursivecal as rc
if __package__:
    from . import adaptive_benchmark as ab
    from . import audit_physics as ap
    from . import physical_requirements as pr
    from . import test_exact_duration as exact
    from . import check_mismatch
else:
    import adaptive_benchmark as ab
    import audit_physics as ap
    import physical_requirements as pr
    import test_exact_duration as exact
    import check_mismatch
try:
    if __package__:
        from . import train_adaptive_rl as arl
    else:
        import train_adaptive_rl as arl
except ModuleNotFoundError as error:
    if error.name != "torch":
        raise
    arl = None

class ResearchAuditTests(unittest.TestCase):
    def test_original_reference_dataset_regression(self):
        means=[]
        for seed,combined,novel in [(900000,False,False),(1200000,True,False),(1500000,False,True)]:
            rewards=[rc.calibration_quality(rc.plant_for_seed(seed+i,combined=combined,novel=novel)[0],rc.DEFAULT_CALIBRATION) for i in range(60)]
            means.append(round(float(np.mean(rewards)),5))
        self.assertEqual(means,[.84053,.79321,.64360])
    def test_pulse_symmetry(self):
        p=rc.Plant(motor=.83,friction=.19,load=.25,damping=.3,sensor_bias=.07)
        for a,b in [('pulse_pos_low','pulse_neg_low'),('pulse_pos_high','pulse_neg_high'),('pulse_pos_offset','pulse_neg_offset')]:
            x=rc.measurement_prediction(p,rc.PROBE_BY_NAME[a])
            y=rc.measurement_prediction(p,rc.PROBE_BY_NAME[b])
            self.assertTrue(all(abs(v+w)<1e-12 for v,w in zip(x,y)))
    def test_sensor_bias_unobservable_from_pulses(self):
        p=rc.Plant(motor=.87,sensor_bias=.0)
        q=rc.Plant(motor=.87,sensor_bias=.08)
        for probe in rc.PROBES[:-1]:
            self.assertEqual(rc.measurement_prediction(p,probe),rc.measurement_prediction(q,probe))
        self.assertNotEqual(rc.measurement_prediction(p,rc.PROBES[-1]),rc.measurement_prediction(q,rc.PROBES[-1]))
    def test_CAD_strut_jacobian(self):
        cad=ap.cad
        for deg in range(4,78,7):
            q=math.radians(deg);h=1e-5
            finite=(cad.geometry(q+h)['length_m']-cad.geometry(q-h)['length_m'])/(2*h)
            self.assertLess(abs(finite-cad.geometry(q)['lever_m']),1e-8)
    def test_passive_open_balance_has_valid_units(self):
        result=pr.evaluate()
        self.assertGreater(result['modeled_gravity_closing_torque_Nm'],0)
        self.assertAlmostEqual(result['passive_net_opening_torque_Nm'],
            result['modeled_strut_opening_torque_Nm_total']-result['modeled_gravity_closing_torque_Nm'],delta=2e-4)
        self.assertFalse(result['passive_open_hold_without_motor']) # known v0.2 limitation
    def test_true_pulse_duration_not_roundable(self):
        # Deliberately captures the known v0.2 numerical limitation.
        self.assertAlmostEqual(int(round(.55/.02))*.02,.56)
    def test_exact_duration_reports_accepted_time_on_abort(self):
        _,duration=exact.pulse_exact(rc.Plant(motor=100),.85,0.,.55,.02)
        self.assertEqual(duration,0.)
        _,duration=exact.pulse_exact(rc.Plant(),.85,0.,.55,.02)
        self.assertAlmostEqual(duration,.55)
    def test_adaptive_choices_vary_with_observation(self):
        mu,Q=ab.model_tables()
        h,obs,_=ab.make_dataset(128,99181,mu)
        values,second,_,_=ab.eval_adaptive(h,obs,mu,Q)
        self.assertTrue(np.isfinite(values).all())
        self.assertGreaterEqual(len(set(second)),3)
    @unittest.skipIf(arl is None, "PyTorch optional for learned-policy checks")
    def test_RL_feature_and_reward_table_shapes(self):
        mu,Q=ab.model_tables();h,obs,_=ab.make_dataset(25,917,mu)
        features,table=arl.prepare_data(h,obs,mu,Q)
        self.assertEqual(features.shape,(25,ab.N+2))
        self.assertEqual(table.shape,(25,len(arl.SECOND_ACTIONS)))
        self.assertTrue(np.isfinite(features).all())
        self.assertTrue(np.isfinite(table).all())

if __name__=='__main__':unittest.main(verbosity=2)
