"""Cross-language kinematics and dynamics regression, 7 scenarios * 5 times."""
import json,subprocess,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'simulation'))
from physics_v2 import simulate,SCENARIOS,Controller,geometry

class JsParity(unittest.TestCase):
 def test_js_vs_python(self):
  script=f"""
  require({json.dumps(str(ROOT/'viewer'/'physics_v2.js'))});
  const P=globalThis.RecursivePhysics, out={{}};
  for(const [name,p] of Object.entries(P.plants)){{
   let run=P.simulate(p);
   out[name]={{metrics:run.metrics,samples:[0,37,101,160,217].map(i=>run.frames[i])}};
  }}
  console.log(JSON.stringify(out));
  """
  js=json.loads(subprocess.check_output(['node','-e',script],text=True))
  for name,p in SCENARIOS.items():
   py=simulate(p)
   self.assertEqual(py['metrics'],js[name]['metrics'],name)
   for i,a in zip([0,37,101,160,217],js[name]['samples']):
    b=py['frames'][i]
    for key in ['q','q_target','w','length_m','stroke_m','lever_m','motor_force_N_each','gas_force_N_each','motor_torque_Nm_total','gravity_torque_Nm']:
     self.assertAlmostEqual(a[key],b[key],delta=1e-7,msg=f'{name} frame{i} {key}')
if __name__=='__main__':unittest.main()
