import math,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'simulation'))
from fit_force_curve import fit,read_csv,MeasurementError
class FittingTests(unittest.TestCase):
 def test_fit_synthetic(self):
  rows=read_csv(ROOT/'assets'/'SYNTHETIC_force_samples.csv')
  result=fit(rows)
  self.assertEqual(result['n'],14)
  self.assertIn('SYNTHETIC_NOT_HARDWARE',result['measurement_type'])
  self.assertLess(abs(result['open_force_N_each']-165),3.0)
  self.assertLess(abs(result['slope_N_per_m']-47/(.9411984943175743-.5676653944006099)),15)
 def test_one_angle_rejected(self):
  with self.assertRaises(MeasurementError):fit([{'angle_deg':0.0,'strut_force_N_each':150.0,'measurement_type':'TEST'} for i in range(5)])
if __name__=='__main__':unittest.main()
