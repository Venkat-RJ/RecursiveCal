"""Versioned numerical correction proposal; does not modify frozen v0.2 simulator.
Checks pulse duration exactly and compares timestep refinements.
"""
import sys
from pathlib import Path
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if (_PROJECT_ROOT / "recursivecal.py").exists():
    sys.path.insert(0, str(_PROJECT_ROOT))
import json
import math
from pathlib import Path
import recursivecal as rc

def pulse_exact(plant,torque,fixture,seconds,dt):
    if abs(torque)>rc.TORQUE_LIMIT or abs(fixture)>.30 or not 0<seconds<=.6:
        raise ValueError('Unsafe diagnostic command')
    x,v=fixture,0.
    n=round(seconds/dt,10)
    whole=int(math.floor(n+1e-9))
    intervals=[dt]*whole
    rem=seconds-whole*dt
    if rem>1e-11:intervals.append(rem)
    if abs(sum(intervals)-seconds)>1e-10:raise AssertionError('duration drift')
    for h in intervals:
        a=rc.acceleration(plant,x,v,torque)
        vn=v+a*h;xn=x+vn*h
        if abs(vn)>rc.SPEED_LIMIT or abs(xn)>rc.POSITION_LIMIT:break
        x,v=xn,vn
    return (x-fixture,v),sum(intervals)

def main():
    plants={'nominal':rc.Plant(),'weak_motor':rc.Plant(motor=.7),
            'high_friction':rc.Plant(friction=.31),'heavy_load':rc.Plant(load=.39),
            'deadzone':rc.Plant(motor=.82,friction=.22,torque_deadzone=.24)}
    cases={};fixed_err=[];original_err=[]
    for name,plant in plants.items():
        values={}
        for dt in (.02,.01,.005,.0025):
            values[str(dt)]={'corrected':pulse_exact(plant,.85,0.,.55,dt)[0],
                             'actual_duration':pulse_exact(plant,.85,0.,.55,dt)[1]}
            rc.DT=dt
            values[str(dt)]['original']=rc.measurement_prediction(plant,rc.PROBE_BY_NAME['pulse_pos_high'])
        baseline=values['0.0025']['corrected'][0]
        fixed_err.append(abs(values['0.02']['corrected'][0]-baseline))
        original_err.append(abs(values['0.02']['original'][0]-baseline))
        cases[name]=values
    rc.DT=.02
    result={'duration_specified_s':.55,'original_at_dt_0_02_s':int(round(.55/.02))*.02,
            'corrected_at_dt_0_02_s':.55,
            'max_abs_probe_displacement_error_original_0_02_vs_exact_reference':max(original_err),
            'max_abs_probe_displacement_error_corrected_0_02_vs_exact_reference':max(fixed_err),
            'cases':cases}
    Path('exact_pulse_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Actual v0.2 duration at dt .02:',result['original_at_dt_0_02_s'])
    print('Max pulse x error vs refined reference: original',round(max(original_err),6),'corrected',round(max(fixed_err),6))
if __name__=='__main__':main()
