"""First-probe discrepancy audit, threshold chosen exclusively on training model cases.
This is a diagnostic sanity check, not real-world anomaly detection validation.
"""
import sys
from pathlib import Path
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if (_PROJECT_ROOT / "recursivecal.py").exists():
    sys.path.insert(0, str(_PROJECT_ROOT))
import argparse
import json
import numpy as np
if __package__:
    from . import adaptive_benchmark as ab
else:
    import adaptive_benchmark as ab

def residuals(observations,mu):
    y=observations[:,ab.FIRST,:2]
    r=(y[:,None,:]-mu[None,:,ab.FIRST,:2])/ab.SIGMA[None,ab.FIRST,:2]
    return np.sqrt(np.min(np.sum(r*r,axis=2),axis=1))

def main(output='mismatch_detection.json'):
    mu,_=ab.model_tables()
    _,train,_=ab.make_dataset(5000,701050,mu)
    thresh=float(np.quantile(residuals(train,mu),.95))
    cases=[('in_model',ab.make_dataset(2048,9202026,mu)),
           ('continuous_jitter',ab.make_dataset(512,7212026,mu,True)),
           ('unseen_high_load',ab.make_ood_dataset(512,981138,mu,'high_load')),
           ('unseen_extreme_deadzone',ab.make_ood_dataset(512,883388,mu,'extreme_deadzone'))]
    result={'first_probe':ab.rc.PROBES[ab.FIRST].name,
            'first_probe_model_discrepancy_threshold_sigma':round(thresh,5),
            'threshold_training_false_alarm_fraction':.05,'cases':{}}
    for name,(h,obs,plant) in cases:
        x=residuals(obs,mu)
        result['cases'][name]={'n':len(x),'flag_rate':round(float(np.mean(x>thresh)),5),
                               'median_min_standardized_residual':round(float(np.median(x)),5),
                               'p95_min_standardized_residual':round(float(np.quantile(x,.95)),5)}
        print(name,result['cases'][name])
    Path(output).write_text(json.dumps(result,indent=2)+'\n')
if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='mismatch_detection.json')
    main(parser.parse_args().output)
