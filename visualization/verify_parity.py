"""Cross-check visual JavaScript physics with RecursiveCal's canonical Python simulator."""
import json
import math
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root.parent))
from recursivecal import Plant, Calibration, calibration_quality, run_closed_loop

cases = []
for sc in json.loads((root / "scenarios.json").read_text()):
    p = Plant(**sc["ground_truth"])
    controls = [
        Calibration(1.0, 0.08, 0.0),
        Calibration(1.25, 0.24, -0.04),
        Calibration(0.9, 0.16, 0.04),
        Calibration(**sc["bayesian"]["calibration"]),
    ]
    for cal in controls:
        traj = run_closed_loop(p, cal, -0.15, 0.28)
        cases.append({
            "plant": sc["ground_truth"], "cal": vars(cal),
            "expected": {
                "quality": calibration_quality(p, cal),
                "x": traj.x, "v": traj.v,
                "effort": traj.effort,
                "error": traj.cumulative_tracking_error,
                "risk": traj.risk_interventions,
            }
        })

js = r"""
const fs=require('fs'), vm=require('vm');
const c=vm.createContext({Math});
vm.runInContext(fs.readFileSync(process.argv[1],'utf8')+
  '\nthis._quality=rcQuality;this._run=rcClosedLoop;',c);
const cases=JSON.parse(fs.readFileSync(0,'utf8'));
console.log(JSON.stringify(cases.map(x=>{
  const t=c._run(x.plant,x.cal,-0.15,0.28);
  return {quality:c._quality(x.plant,x.cal).quality,
          x:t.x,v:t.v,effort:t.effort,error:t.cumulative,risk:t.risk};
})));
"""
result = subprocess.run(
    ["node", "-e", js, str(root / "engine.js")],
    input=json.dumps(cases), text=True, capture_output=True, check=True,
)
observed = json.loads(result.stdout)
assert len(observed) == len(cases) == 28
worst = 0.0
for reference, got in zip(cases, observed):
    for name, expected in reference["expected"].items():
        error = abs(expected - got[name])
        worst = max(worst, error)
        assert error < 5e-12, (name, expected, got[name])
print(f"PASS: {len(cases)} canonical Python vs JavaScript comparisons, max error {worst:.3g}")
