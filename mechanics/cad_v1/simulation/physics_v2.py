"""RecursiveCal CAD-linked tailgate dynamics in SI units.

This is a *new illustrative model*, separate from the original 1D RL benchmark.
Strut kinematics use exact CAD body/hatch mounting coordinates.
Not calibrated to any vehicle, not suitable for actuation or safety validation.
"""
from __future__ import annotations
from dataclasses import dataclass,asdict
from math import sin,cos,pi,sqrt,tanh
import json
from pathlib import Path

MAX_Q=78*pi/180
HINGE_Z=1.76
BODY_X=-.470
BODY_Z=1.170
HATCH_X=.018
HATCH_DOWN=.300
STRUT_BASE=0.567674
DT=.01
T_MAX=6.5
OPEN_TIME=4.8
G=9.81
J=12.0
F_MOTOR_MAX=330.0

@dataclass(frozen=True)
class Plant:
    hatch_mass:float=25.0
    motor_eff:float=1.0
    friction_factor:float=1.0
    gas_factor:float=1.0
    sensor_bias:float=0.0
    extra_load:float=0.0

@dataclass(frozen=True)
class Controller:
    gain:float=1.0
    damping_gain:float=1.0
    gravity_comp:float=1.0
    friction_ff:float=1.0
    sensor_comp:float=0.0

SCENARIOS={
    'nominal':Plant(),
    'hinge_friction':Plant(friction_factor=2.5),
    'motor_fade':Plant(motor_eff=.55),
    'heavy_hatch':Plant(hatch_mass=33),
    'gas_leak':Plant(gas_factor=.47),
    'sensor_bias':Plant(sensor_bias=.075),
    'combined':Plant(motor_eff=.62,friction_factor=2.5,hatch_mass=29),
}

def xy(q):
    return (HATCH_X*cos(q)+HATCH_DOWN*sin(q),
            HINGE_Z+HATCH_X*sin(q)-HATCH_DOWN*cos(q))

def geometry(q):
    x,z=xy(q)
    dx=-HATCH_X*sin(q)+HATCH_DOWN*cos(q)
    dz=HATCH_X*cos(q)+HATCH_DOWN*sin(q)
    ux=x-BODY_X;uz=z-BODY_Z
    L=sqrt(ux*ux+uz*uz)
    dldq=(ux*dx+uz*dz)/L
    return {'length_m':L,'lever_m':dldq,'hatch_point_x_m':x,'hatch_point_z_m':z}

def gas_force(q,p):
    # Nonlinear illustrative gas force. Not an OEM spring-rating curve.
    length=geometry(q)['length_m']
    stroke=geometry(MAX_Q)['length_m']-geometry(0)['length_m']
    compression=max(0,min(1,(geometry(MAX_Q)['length_m']-length)/stroke))
    return (165+47*compression)*p.gas_factor

def torque_gravity(q,p):return p.hatch_mass*G*.55*sin(q+.15)+p.extra_load

def torque_hinge(v,p):return p.friction_factor*(6*tanh(v/.026)+5*v)

def reference(t):
    r=max(0,min(1,t/OPEN_TIME))
    q=MAX_Q*(10*r**3-15*r**4+6*r**5)
    if not 0<r<1:return q,0,0
    return q,MAX_Q*(30*r*r-60*r**3+30*r**4)/OPEN_TIME,MAX_Q*(60*r-180*r*r+120*r**3)/(OPEN_TIME**2)

def simulate(p:Plant,ctrl:Controller=Controller()):
    q=0.;v=0.;records=[];saturation=0;interventions=0;total_energy=0.
    n=round(T_MAX/DT)
    nominal=Plant()
    for i in range(n+1):
        t=round(i*DT,5)
        ref,refvel,refacc=reference(t)
        g=geometry(q);lever=g['lever_m']
        gas=gas_force(q,p)
        # Motor force commanded per strut, generated from feedforward + feedback torque.
        nom_gas=gas_force(q,nominal)
        nom_gravity=torque_gravity(q,nominal)
        err=ref-(q+p.sensor_bias-ctrl.sensor_comp)
        desired_torque=(J*refacc+ctrl.gain*178*err+ctrl.damping_gain*68*(refvel-v)
                        +ctrl.gravity_comp*nom_gravity-2*nom_gas*lever
                        +ctrl.friction_ff*6*tanh(refvel/.05))
        demand=desired_torque/(2*lever)
        request=max(-F_MOTOR_MAX,min(F_MOTOR_MAX,demand))
        force=request*p.motor_eff
        tau_gas=2*gas*lever
        tau_motor=2*force*lever
        tau_grav=torque_gravity(q,p)
        tau_frict=torque_hinge(v,p)
        damping_torque=2*6.0*(lever*v)*lever
        net=tau_motor+tau_gas-tau_grav-tau_frict-damping_torque
        acc=net/J
        current=.55+abs(force)/39.0
        # Host-side physical hard limits; not a safety certified controller.
        if abs(v)>1.15 or current>9.5:interventions+=1
        if abs(demand)>F_MOTOR_MAX:saturation+=1
        if i%3==0 or i==n:
            records.append({'t':t,'q':q,'q_target':ref,'w':v,
                           'length_m':g['length_m'],'stroke_m':g['length_m']-geometry(0)['length_m'],
                           'lever_m':lever,'motor_force_N_each':force,
                           'gas_force_N_each':gas,'motor_current_A_each':current,
                           'motor_torque_Nm_total':tau_motor,'gas_torque_Nm_total':tau_gas,
                           'gravity_torque_Nm':tau_grav,'net_torque_Nm':net,'angular_accel_rad_s2':acc,
                           'error_deg':(ref-q)*180/pi})
        if i<n:
            newv=v+acc*DT;newq=q+newv*DT
            if newq<0:newq=0;newv=0
            if newq>MAX_Q:newq=MAX_Q;newv=0
            total_energy+=abs(2*force*lever*v)*DT
            q,v=newq,newv
    mean_error=sum(abs(row['error_deg']) for row in records)/len(records)
    return {'frames':records,'metrics':{'mae_deg':round(mean_error,3),
        'final_angle_deg':round(records[-1]['q']*180/pi,2),
        'final_error_deg':round((MAX_Q-records[-1]['q'])*180/pi,2),
        'peak_motor_current_A_each':round(max(r['motor_current_A_each'] for r in records),2),
        'peak_strut_force_N_each':round(max(abs(r['motor_force_N_each'])+r['gas_force_N_each'] for r in records),1),
        'motor_mechanical_energy_J_approx':round(total_energy,1),
        'host_limit_events':interventions,'force_saturation_steps':saturation}}


def reference_force_table():
    rows=[]
    for deg in range(0,79,6):
        q=deg*pi/180;g=geometry(q);nominal=Plant()
        tg=torque_gravity(q,nominal)
        fg=gas_force(q,nominal)
        holding_motor_force=(tg-2*fg*g['lever_m'])/(2*g['lever_m'])
        rows.append({'angle_deg':deg,'length_mm':round(g['length_m']*1000,2),
            'moment_arm_mm':round(g['lever_m']*1000,2),'nominal_gas_N_each':round(fg,1),
            'gravity_torque_Nm':round(tg,1),'gas_torque_Nm':round(2*fg*g['lever_m'],1),
            'static_holding_motor_N_each':round(holding_motor_force,1)})
    return rows

if __name__=='__main__':
    print('CAD-linked geometry:',geometry(0),geometry(MAX_Q))
    for name,p in SCENARIOS.items():
        for ctrlname,ctrl in [('factory',Controller()),('recalibrated',Controller(gain=1.3,gravity_comp=1.12,friction_ff=1.7))]:
            print(name,ctrlname,simulate(p,ctrl)['metrics'])
    root=Path(__file__).resolve().parents[1]
    out={'metadata':{'model':'illustrative non-OEM CAD-linked rigid-body hinge with two struts',
            'mass_kg':25,'hinge_inertia_kg_m2':J,'max_motor_force_N_each':F_MOTOR_MAX,
            'gas_force_curve':'illustrative 165 to 212 N per strut',
            'not_measured':True},
         'static_force_curve':reference_force_table(),
         'scenarios':{name:{key:simulate(p,ctrl) for key,ctrl in {
             'factory':Controller(), 'modified':Controller(gain=1.3,gravity_comp=1.12,friction_ff=1.7)}.items()} for name,p in SCENARIOS.items()}}
    (root/'assets'/'simulated_runs.json').write_text(json.dumps(out,separators=(',',':')))
