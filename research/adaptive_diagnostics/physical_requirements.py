"""Independent physical-plausibility gate for the CAD-linked tailgate test cell.

External reference: NHTSA Engineering Analysis EA06-020 (June 2008),
Toyota Sienna power liftgate. These data are vehicle-specific, so they are NOT
used as model-fitting labels or transferred to the RecursiveCal geometry.

Run: python physical_requirements.py --output physical_requirements.json
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
try:
    import cad_simulation_physics_v2 as cad
except ModuleNotFoundError:
    import sys
    repo=Path(__file__).resolve().parents[2]
    sys.path.insert(0,str(repo/'mechanics'/'cad_v1'/'simulation'))
    import physics_v2 as cad

# A small curated subset of published physical observations for a DIFFERENT vehicle.
# Physical force values in pounds-force, not newtons.
NHTSA_REFERENCE={
    'source':'https://static.nhtsa.gov/odi/inv/2006/INCR-EA06020-29305P.pdf',
    'document':'NHTSA EA06-020, Engineering Analysis Report, June 2008, 2004-2006 Toyota Sienna',
    'vehicle_hatch_weight_lb':71,
    'new_strut_A_full_compression_lb_at_F':{'35F':140,'72F':147,'110F':160},
    'new_strut_A_full_extension_lb_at_F':{'35F':113,'72F':119,'110F':129},
    'observed_combined_ext_force_and_state':[
        {'configuration':'C/D','extension_force_lb':189,'state':'did_not_drop'},
        {'configuration':'C/H','extension_force_lb':176,'state':'dropped_slowly'},
        {'configuration':'G/H','extension_force_lb':145,'state':'dropped_and_motor_engaged'},
    ],
    'warning':'Different hatch, mounting coordinates, actuator and control design; do not fit our CAD forces to these measurements.'
}

def evaluate():
    plant=cad.Plant()
    theta=cad.MAX_Q
    mount=cad.geometry(theta)
    force=cad.gas_force(theta,plant)
    gas_torque=2*force*mount['lever_m']
    gravity=cad.torque_gravity(theta,plant)
    # A nominal hatch should not immediately accelerate closed after its opening
    # motor disengages (absent a separate mechanical hold/latch); current model lacks such a mechanism.
    passive_net=gas_torque-gravity
    required_force=gravity/(2*mount['lever_m'])
    return {
      'model':'RecursiveCal CAD v0.2, synthetic rigid 1-DOF model',
      'units':{'force':'N per strut','torque':'Nm','angle':'deg'},
      'nominal_open_angle_deg':round(theta*180/math.pi,3),
      'open_strut_lever_m':round(mount['lever_m'],6),
      'modeled_strut_force_N_each':round(force,4),
      'modeled_strut_opening_torque_Nm_total':round(gas_torque,4),
      'modeled_gravity_closing_torque_Nm':round(gravity,4),
      'passive_net_opening_torque_Nm':round(passive_net,4),
      'minimum_strut_force_to_balance_gravity_N_each':round(required_force,4),
      'force_shortfall_N_each':round(required_force-force,4),
      'passive_open_hold_without_motor':bool(passive_net>=-1e-9),
      'external_reference':NHTSA_REFERENCE,
      'status':'SIMULATED NOMINAL PASSIVE HOLD FAILS' if passive_net<0 else 'SIMULATED PASSIVE HOLD BALANCES GRAVITY',
      'additional_missing_behaviors':['latched closed state','motor disengagement at open','temperature-dependent force','direction-dependent force and stiction','contact/anti-pinch and motor re-engagement','real-world parameter measurements'],
      'scope':'A model-plausibility calculation, not a verification of real vehicle safe operation'
    }

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',default='physical_requirements.json')
    args=ap.parse_args();out=evaluate()
    Path(args.output).write_text(json.dumps(out,indent=2)+'\n')
    print('at open: gas=',out['modeled_strut_opening_torque_Nm_total'],'Nm, gravity=',out['modeled_gravity_closing_torque_Nm'],'Nm')
    print('strut force required per strut=',out['minimum_strut_force_to_balance_gravity_N_each'],'N, assumed=',out['modeled_strut_force_N_each'],'N')
    print(out['status'])
