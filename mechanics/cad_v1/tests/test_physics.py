import math,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'simulation'))
sys.path.insert(0,str(ROOT/'cad'))
from physics_v2 import *
from build_assembly import length_mm,hatch_mount,make_parts
class GeometryTests(unittest.TestCase):
 def test_exact_cad_length(self):
  for deg in range(0,79,3):
   q=math.radians(deg)
   self.assertAlmostEqual(geometry(q)['length_m'],length_mm(q)*.001,places=9)
 def test_geometry_bound_and_stroke(self):
  samples=[geometry(math.radians(x))['length_m'] for x in range(79)]
  self.assertTrue(all(a<b for a,b in zip(samples,samples[1:])))
  self.assertAlmostEqual((samples[-1]-samples[0])*1000,373.5331,delta=.06)
  self.assertGreater(samples[0],.5)
  self.assertLess(samples[-1],1.0)
 def test_jacobian_finite_difference(self):
  h=1e-5
  for deg in range(5,76,5):
   q=math.radians(deg)
   measured=(geometry(q+h)['length_m']-geometry(q-h)['length_m'])/(2*h)
   self.assertAlmostEqual(measured,geometry(q)['lever_m'],delta=1e-8)
 def test_equal_strut_lengths(self):
  for deg in (0,39,78):
   q=math.radians(deg)
   self.assertAlmostEqual(math.dist((-470,-650,1170),hatch_mount(q,-1)),math.dist((-470,650,1170),hatch_mount(q,1)),delta=1e-8)
 def test_all_policies_bounded(self):
  for p in SCENARIOS.values():
   for c in (Controller(),Controller(gain=1.3,gravity_comp=1.12,friction_ff=1.7)):
    run=simulate(p,c)
    self.assertEqual(len(run['frames']),218)
    self.assertTrue(all(0<=f['q']<=MAX_Q+1e-10 for f in run['frames']))
    self.assertTrue(all(abs(f['motor_force_N_each'])<=330+1e-10 for f in run['frames']))
    self.assertTrue(all(0<=f['stroke_m']<.38 for f in run['frames']))
 def test_replay_is_deterministic(self):
  self.assertEqual(simulate(SCENARIOS['combined']),simulate(SCENARIOS['combined']))
 def test_fault_has_effect(self):
  good=simulate(SCENARIOS['nominal'])['metrics']['final_angle_deg']
  bad=simulate(SCENARIOS['motor_fade'])['metrics']['final_angle_deg']
  self.assertGreater(good-bad,5)
 def test_cad_components(self):
  closed=make_parts(0);opened=make_parts(MAX_Q)
  self.assertEqual(len(closed),len(opened))
  self.assertGreater(len(closed),50)
  self.assertTrue(all(p.solid.Volume()>0 for p in opened))
if __name__=='__main__':unittest.main()
