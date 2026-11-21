"""Numerical and identifiability audit for RecursiveCal (standard library + numpy).
Run: python audit_physics.py --output physics_audit.json
Uses only the public simulator equations, not hardware measurements.
"""
import sys
from pathlib import Path
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if (_PROJECT_ROOT / "recursivecal.py").exists():
    sys.path.insert(0, str(_PROJECT_ROOT))
import argparse
import itertools
import json
import math
from dataclasses import fields, replace
from pathlib import Path
import numpy as np
import recursivecal as rc
try:
    from mechanics.cad_v1.simulation import physics_v2 as cad
except ModuleNotFoundError:
    import sys
    sys.path.insert(0, str(_PROJECT_ROOT / "mechanics" / "cad_v1" / "simulation"))
    import physics_v2 as cad

def linear_energetics():
    """Inspect high- and low-torque calibration/physics sensitivity to timestep."""
    original=rc.DT
    plants = {
        'nominal':rc.Plant(),
        'weak_motor':rc.Plant(motor=.7),
        'heavy_load':rc.Plant(load=.39),
        'high_friction':rc.Plant(friction=.31),
        'deadzone':rc.Plant(motor=.82,friction=.22,torque_deadzone=.24),
    }
    samples={}
    try:
        for name,p in plants.items():
            vals={}
            for dt in [.02,.01,.005,.0025]:
                rc.DT=dt
                cal=rc.Calibration(gain=1.25,friction_ff=.24,sensor_offset=0)
                probe=rc.measurement_prediction(p,rc.PROBE_BY_NAME['pulse_pos_high'])
                q=rc.calibration_quality(p,cal)
                vals[str(dt)]={'probe_x':probe[0],'probe_v':probe[1],'quality':q}
            fine=vals[str(.0025)]
            samples[name]={'values':vals,'coarse_errors':{
                key:abs(vals[str(.02)][key]-fine[key]) for key in fine},
                'quality_0.02_vs_0.005':abs(vals[str(.02)]['quality']-vals[str(.005)]['quality'])}
    finally: rc.DT=original
    return samples

def rank_identifiability():
    """Derivative response wrt six plant parameters, standardized by observation noise."""
    p=rc.Plant(motor=.82,friction=.23,load=.26,damping=.23,sensor_bias=.04,torque_deadzone=.16)
    params=['motor','friction','load','damping','sensor_bias','torque_deadzone']
    h={'motor':.001,'friction':.001,'load':.001,'damping':.001,'sensor_bias':.001,'torque_deadzone':.001}
    response=lambda plant,probe:np.asarray(rc.measurement_prediction(plant,probe))
    J=[]
    for probe in rc.PROBES:
        diff=[]
        for k in params:
            b=replace(p,**{k:getattr(p,k)-h[k]});a=replace(p,**{k:getattr(p,k)+h[k]})
            diff.append((response(a,probe)-response(b,probe))/(2*h[k]))
        diff=np.array(diff).T
        sig=np.array([.006] if probe.kind=='reference' else [.004,.009])
        J.extend((diff/sig[:,None]).tolist())
    J=np.array(J)
    by_group={}
    pulse_J=J[:-1,:]
    for name,M in [('pulse_only',pulse_J),('pulse_and_reference',J)]:
        sv=np.linalg.svd(M,compute_uv=False)
        by_group[name]={'singular_values':np.round(sv,5).tolist(),
                        'rank_at_1e-6':int((sv>1e-6).sum()),
                        'rank_at_1e-2':int((sv>1e-2).sum()),
                        'condition_number':float(sv[0]/sv[-1]) if sv[-1]>1e-10 else None}
    return {'parameters':params,'jacobian_std_noise':np.round(J,3).tolist(),'rank':by_group}

def mirrored_probes():
    rng=np.random.default_rng(20261121)
    max_error=0.
    for _ in range(1000):
        p=rc.Plant(motor=float(rng.uniform(.6,1.1)),friction=float(rng.uniform(.06,.35)),
                   load=float(rng.uniform(.08,.45)),damping=float(rng.uniform(.1,.35)),
                   sensor_bias=float(rng.uniform(-.09,.09)),torque_deadzone=float(rng.uniform(0,.3)))
        for pos,neg in [('pulse_pos_low','pulse_neg_low'),('pulse_pos_high','pulse_neg_high'),('pulse_pos_offset','pulse_neg_offset')]:
            yp=rc.measurement_prediction(p,rc.PROBE_BY_NAME[pos]);yn=rc.measurement_prediction(p,rc.PROBE_BY_NAME[neg]);
            max_error=max(max_error,max(abs(a+b) for a,b in zip(yp,yn)))
    return {'plants':1000,'positive_negative_pairs':3,'maximum_symmetry_residual':max_error}

def cad_precision():
    """Kinematic identity and a discrete mechanical work/energy consistency check."""
    q_values=np.linspace(.01,cad.MAX_Q-.01,201)
    errs=[]
    for q in q_values:
        h=1e-5
        finite=(cad.geometry(q+h)['length_m']-cad.geometry(q-h)['length_m'])/(2*h)
        errs.append(abs(finite-cad.geometry(q)['lever_m']))
    # In the ideal unforced model, the strut work equals the integral of gas torque.
    motor_force=100.0
    work_via_length=2*motor_force*(cad.geometry(cad.MAX_Q)['length_m']-cad.geometry(0)['length_m'])
    levers=np.array([cad.geometry(q)['lever_m'] for q in np.linspace(0,cad.MAX_Q,20001)])
    # NumPy 1.24 is supported. np.trapezoid was introduced in NumPy 2.0.
    coordinates=np.linspace(0,cad.MAX_Q,20001)
    values=2*motor_force*levers
    integral=float(np.sum(.5*(values[1:]+values[:-1])*np.diff(coordinates)))
    return {'lever_derivative_max_abs_m_per_rad':max(errs),
            'constant_strut_work_via_stroke_J':work_via_length,
            'constant_strut_work_via_torque_J':integral,
            'relative_work_mismatch':abs(work_via_length-integral)/max(1,abs(work_via_length)),
            'gas_force_ratio_closed_open':cad.gas_force(0,cad.Plant())/cad.gas_force(cad.MAX_Q,cad.Plant()),
            'mechanics_scope':'single rigid hinge and synthetic force assumptions, no hardware validation'}

def run():
    return {'source':'Imported frozen RecursiveCal core and CAD simulation files from this repository checkout',
            'linear_time_step':linear_energetics(),
            'observability':rank_identifiability(),
            'mirror_symmetry':mirrored_probes(),
            'cad_geometry':cad_precision()}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='physics_audit.json')
    args=parser.parse_args(); result=run(); Path(args.output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    for k,v in result['linear_time_step'].items():
        print('dt-convergence',k,'quality coarse->fine',round(v['coarse_errors']['quality'],6),'pulse_x',round(v['coarse_errors']['probe_x'],6))
    print('probe symmetry worst error',result['mirror_symmetry']['maximum_symmetry_residual'])
    for k,v in result['observability']['rank'].items():
        print('observability',k,'rank',v['rank_at_1e-2'],'singular values',v['singular_values'])
    print('CAD lever derivative error',result['cad_geometry']['lever_derivative_max_abs_m_per_rad'])
    print('CAD mechanical work mismatch',result['cad_geometry']['relative_work_mismatch'])
