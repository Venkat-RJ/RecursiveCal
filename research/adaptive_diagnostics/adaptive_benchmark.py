"""Reproducible finite-model adaptive experiment-design diagnostic pilot.
The benchmark uses RecursiveCal v0.2 dynamics, but a NEW explicitly specified prior.
Classical Bayesian, not RL. In-simulator evidence only, no real hardware data.

Uses true pre-generated observation arrays for all strategies (common random numbers).
Fixed schedules are selected using independent training episodes only.
Evaluates the predeclared 4-family task and out-of-prior continuous jitter.

Run: python adaptive_benchmark.py --output adaptive_results.json
"""
from __future__ import annotations
# Works from a GitHub checkout or from this standalone bundle.
import sys
from pathlib import Path
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if (_PROJECT_ROOT / "recursivecal.py").exists():
    sys.path.insert(0, str(_PROJECT_ROOT))
import argparse
import json
import math
from functools import lru_cache
from pathlib import Path
import numpy as np
from dataclasses import replace
from typing import Sequence
import recursivecal as rc

# Predeclared study of uncertainty about a *sensor*, motor/friction and torque deadzone.
# The first low-torque pulse may classify mechanical vs near-nominal response,
# whereas reference and high-torque measurements target different remaining uncertainties.
# These are synthetic scenario assumptions, not an automotive empirical distribution.
HYPOTHESES=(
 ('nominal_a',rc.Plant(motor=1.,friction=.1,load=.12,sensor_bias=.0)),
 ('nominal_b',rc.Plant(motor=.98,friction=.12,load=.13,sensor_bias=.0)),
 ('bias_plus',rc.Plant(motor=1.,friction=.1,load=.12,sensor_bias=.075)),
 ('bias_minus',rc.Plant(motor=1.,friction=.1,load=.12,sensor_bias=-.075)),
 ('motor_weak_a',rc.Plant(motor=.69,friction=.115,load=.12)),
 ('motor_weak_b',rc.Plant(motor=.78,friction=.12,load=.12)),
 ('high_friction_a',rc.Plant(motor=.92,friction=.30,load=.14)),
 ('high_friction_b',rc.Plant(motor=.95,friction=.27,load=.14)),
 ('torque_deadzone_a',rc.Plant(motor=.91,friction=.14,load=.14,torque_deadzone=.25)),
 ('torque_deadzone_b',rc.Plant(motor=1.02,friction=.17,load=.14,torque_deadzone=.31)),
)
# Posterior weights are available to classical solver. This is a correctly specified
# model in the first experiment, and an approximate model for continuous jitter.
N=len(HYPOTHESES)
P=np.full(N,1/N)
COST=np.array([p.cost for p in rc.PROBES])
NPROBES=len(rc.PROBES)
SIGMA=np.array([[.004,.009]]*6+[[.006,1.0]],dtype=float)
FIRST=0 # pulse_pos_low; fixed independently of performance observations.
SAMPLE_COUNT=40 # posterior predictive MC samples for second-test value of information.
LAMBDA=.012

def model_tables():
    mu=np.zeros((N,NPROBES,2),dtype=np.float64)
    Q=np.zeros((N,len(rc.CALIBRATIONS)),dtype=np.float64)
    for h,(_,plant) in enumerate(HYPOTHESES):
        for j,probe in enumerate(rc.PROBES):
            obs=rc.measurement_prediction(plant,probe)
            mu[h,j,:len(obs)]=obs
        for k,cal in enumerate(rc.CALIBRATIONS): Q[h,k]=rc.calibration_quality(plant,cal)
    return mu,Q

def update(w,observations,probe,mu):
    dims=1 if probe==NPROBES-1 else 2
    r=(mu[:,probe,:dims]-observations[:dims])/SIGMA[probe,:dims]
    logs=np.log(np.maximum(w,1e-300))-.5*np.sum(r*r,axis=-1)
    logs-=logs.max(); nw=np.exp(logs)
    return nw/nw.sum()

def terminate(w,Q):
    utilities=w@Q
    return int(np.argmax(utilities)),float(np.max(utilities))

def choose_second(w,mu,Q,used,rng,force_two=False):
    """Monte Carlo model-based decision-focused VOI. Can STOP to save cost.

    Score uses expected best terminal reward after observing second probe.
    Only conditional outcomes sampled from the CURRENT posterior, never true hidden plant.
    """
    _,best_stop=terminate(w,Q)
    best_action=None
    best_value=(-float('inf') if force_two else best_stop)
    for j in range(NPROBES):
        if j in used:continue
        inds=rng.choice(N,size=SAMPLE_COUNT,p=w)
        obs=mu[inds,j,:]+rng.standard_normal((SAMPLE_COUNT,2))*SIGMA[j,:]
        d=1 if j==NPROBES-1 else 2
        residual=(obs[:,None,:d]-mu[None,:,j,:d])/SIGMA[None,j,:d]
        logw=np.log(np.maximum(w[None,:],1e-300))-.5*np.sum(residual**2,axis=2)
        logw-=np.max(logw,axis=1,keepdims=True)
        ww=np.exp(logw);ww/=ww.sum(axis=1,keepdims=True)
        utility=np.max(ww@Q,axis=1)
        value=float(utility.mean()-LAMBDA*COST[j])
        if value>best_value:
            best_action=j;best_value=value
    return best_action,best_value-best_stop

def make_dataset(n,seed,mu,jitter=False):
    rng=np.random.default_rng(seed)
    hidden=rng.choice(N,size=n,p=P)
    # Same observation noise for all candidate strategies on a task.
    probes=mu[hidden]+rng.standard_normal((n,NPROBES,2))*SIGMA[None,:,:]
    if not jitter:
        truthQ=None # Fast exact quality table for the underlying discrete hidden model.
    else:
        # Transfer: parameter jitter omitted from the inference bank.
        jittered=[]
        for idx in hidden:
            plant=HYPOTHESES[int(idx)][1]
            motor=plant.motor+rng.uniform(-.035,.035)
            friction=max(0.01,plant.friction+rng.uniform(-.027,.027))
            load=max(.01,plant.load+rng.uniform(-.025,.025))
            damping=max(.01,plant.damping+rng.uniform(-.026,.026))
            bias=plant.sensor_bias+rng.uniform(-.012,.012)
            deadzone=max(0,plant.torque_deadzone+rng.uniform(-.018,.018)) if plant.torque_deadzone else 0.
            jittered.append(replace(plant,motor=motor,friction=friction,load=load,
                                    damping=damping,sensor_bias=bias,torque_deadzone=deadzone))
        # True observations generated from jittered plants, not model-table means.
        for i,plant in enumerate(jittered):
            for j,p in enumerate(rc.PROBES):
                y=rc.measurement_prediction(plant,p)
                probes[i,j,:len(y)]+=np.array(y)-mu[hidden[i],j,:len(y)]
        # Compute only the terminal choices actually used, memoize as needed.
        truthQ=jittered
    return hidden,probes,truthQ

def make_ood_dataset(n,seed,mu,family):
    """Structurally out-of-bank parameter classes. No corresponding prior mode."""
    rng=np.random.default_rng(seed)
    hidden=np.zeros(n,dtype=int)
    observations=np.zeros((n,NPROBES,2),dtype=float)
    true=[]
    for i in range(n):
        if family=='high_load':
            plant=rc.Plant(motor=float(rng.uniform(.90,1.0)),friction=float(rng.uniform(.09,.15)),
                           load=float(rng.uniform(.29,.46)),damping=float(rng.uniform(.20,.27)))
        elif family=='extreme_deadzone':
            plant=rc.Plant(motor=float(rng.uniform(.68,.92)),friction=float(rng.uniform(.13,.22)),
                           torque_deadzone=float(rng.uniform(.37,.48)),load=float(rng.uniform(.1,.16)))
        else:raise ValueError('Unknown OOD family')
        true.append(plant)
        for j,p in enumerate(rc.PROBES):
            y=rc.measurement_prediction(plant,p)
            d=len(y)
            observations[i,j,:d]=np.array(y)+rng.normal(0,SIGMA[j,:d])
    return hidden,observations,true

def reward(h,cal,trainQ,jittered,cache=None):
    if jittered is None:return float(trainQ[int(h),cal])
    return float(rc.calibration_quality(jittered,rc.CALIBRATIONS[cal]))

def eval_schedule(schedule,hidden,obs,mu,Q,jittered=None,seq_rng=None):
    totals=np.empty(len(hidden),dtype=np.float64)
    for idx,(h,observations) in enumerate(zip(hidden,obs)):
        w=P.copy()
        for j in schedule:w=update(w,observations[j],j,mu)
        c,_=terminate(w,Q)
        r=reward(h,c,Q,None if jittered is None else jittered[idx])
        totals[idx]=r-LAMBDA*sum(COST[j] for j in schedule)
    return totals

def choose_fixed(train_h,train_obs,mu,Q):
    sequences=[()]+[(i,) for i in range(NPROBES)]+[(i,j) for i in range(NPROBES) for j in range(i+1,NPROBES)]
    outcomes=[]
    for s in sequences:
        mean=float(np.mean(eval_schedule(s,train_h,train_obs,mu,Q)))
        outcomes.append((mean,s))
    return sorted(outcomes,key=lambda x:(x[0],-len(x[1])),reverse=True)

def eval_adaptive(hidden,obs,mu,Q,jittered=None,second_mode='adaptive'):
    totals=np.empty(len(hidden),dtype=np.float64)
    second=[];reasons=[];calibrations=[]
    for k,(h,observations) in enumerate(zip(hidden,obs)):
        w=update(P.copy(),observations[FIRST],FIRST,mu)
        # Deterministic independent rollout RNG keyed by index, not simulator hidden state.
        rng=np.random.default_rng(21002000+k)
        j,gain=choose_second(w,mu,Q,{FIRST},rng,force_two=(second_mode=='forced_two'))
        second.append(-1 if j is None else j)
        reasons.append(gain)
        if j is not None:w=update(w,observations[j],j,mu)
        c,_=terminate(w,Q)
        r=reward(h,c,Q,None if jittered is None else jittered[k])
        totals[k]=r-LAMBDA*(COST[FIRST]+(0 if j is None else COST[j]))
        calibrations.append(c)
    return totals,np.array(second),np.array(reasons),np.array(calibrations)

def ci(values,seed=381,n=3000):
    rng=np.random.default_rng(seed)
    means=[]
    for _ in range(n):means.append(float(rng.choice(values,size=len(values),replace=True).mean()))
    return [round(float(x),6) for x in np.percentile(means,[2.5,97.5])]

def experiment(ntrain,neval,ntransfer):
    mu,Q=model_tables()
    uniq=[str(rc.CALIBRATIONS[i]) for i in sorted(set(np.argmax(Q,axis=1)))]
    train_h,train_obs,_=make_dataset(ntrain,100120,mu)
    ordered=choose_fixed(train_h,train_obs,mu,Q)
    selected=ordered[0][1]
    fixed1=next(s for _,s in ordered if len(s)==1)
    fixed2=next(s for _,s in ordered if len(s)==2)
    print('best fixed schedules:',[(round(x,6),list(s)) for x,s in ordered[:6]],flush=True)
    results={}
    for split,n,seed,jitter in [('in_model',neval,9202026,False),('continuous_jitter',ntransfer,7212026,True),('unseen_high_load',ntransfer,981138,True),('unseen_extreme_deadzone',ntransfer,883388,True)]:
        if split.startswith('unseen_'):
            h,obs,jittered=make_ood_dataset(n,seed,mu,split.removeprefix('unseen_'))
        else:
            h,obs,jittered=make_dataset(n,seed,mu,jitter=jitter)
        policies={
            'no_probe':eval_schedule((),h,obs,mu,Q,jittered),
            'fixed_best':eval_schedule(selected,h,obs,mu,Q,jittered),
            'fixed_one':eval_schedule(fixed1,h,obs,mu,Q,jittered),
            'fixed_two':eval_schedule(fixed2,h,obs,mu,Q,jittered),
            'fixed_first_only':eval_schedule((FIRST,),h,obs,mu,Q,jittered),
        }
        adapt,second,vois,cals=eval_adaptive(h,obs,mu,Q,jittered)
        policies['adaptive_second']=adapt
        forced,forced_second,_,_=eval_adaptive(h,obs,mu,Q,jittered,second_mode='forced_two')
        policies['adaptive_forced_two']=forced
        # Swapped second-action control preserves action frequencies but breaks per-episode decisions.
        # An honest shuffled action experiment must recompute posterior with the shuffled test.
        rng=np.random.default_rng(5884)
        shuffled=second[rng.permutation(n)]
        shuffled_scores=np.empty(n)
        for k,(h_i,obs_i) in enumerate(zip(h,obs)):
            w=update(P.copy(),obs_i[FIRST],FIRST,mu)
            j=shuffled[k]
            if j!=-1:w=update(w,obs_i[j],int(j),mu)
            c,_=terminate(w,Q)
            r=reward(h_i,c,Q,None if jittered is None else jittered[k])
            shuffled_scores[k]=r-LAMBDA*(COST[FIRST]+(0 if j==-1 else COST[j]))
        policies['shuffled_second_decision']=shuffled_scores
        summary={k:round(float(v.mean()),6) for k,v in policies.items()}
        diffs=adapt-policies['fixed_best']
        distribution={('STOP' if j<0 else rc.PROBES[j].name):int(np.sum(second==j)) for j in np.unique(second)}
        results[split]={
            'forced_two_minus_fixed_two':round(float((forced-policies['fixed_two']).mean()),6),
            'forced_two_minus_fixed_two_95pct_paired_bootstrap':ci(forced-policies['fixed_two'],seed=382),
            'forced_second_action_counts':{('STOP' if j<0 else rc.PROBES[j].name):int(np.sum(forced_second==j)) for j in np.unique(forced_second)},
            'count':n,'mean_net_reward':summary,
            'adaptive_minus_fixed':round(float(diffs.mean()),6),
            'adaptive_minus_fixed_95pct_paired_bootstrap':ci(diffs),
            'adaptive_minus_shuffled':round(float((adapt-shuffled_scores).mean()),6),
            'second_action_counts':distribution,
            'branch_by_family':{HYPOTHESES[i][0]:{'n':int(np.sum(h==i)),
                  'mean_reward':round(float(adapt[h==i].mean()),5),
                  'second_action_most_common': ('STOP' if np.bincount(second[h==i]+1,minlength=NPROBES+1).argmax()==0 else rc.PROBES[np.bincount(second[h==i]+1,minlength=NPROBES+1).argmax()-1].name)}
                   for i in range(N) if (not split.startswith('unseen_')) and np.sum(h==i)>0},
            'note':'All policies receive same probe observations on each task and use same Bayes calibration table.'}
        print(split,summary,'adaptive advantage',results[split]['adaptive_minus_fixed'],
              'actions',distribution,flush=True)
    return {'source':'Original RecursiveCal normalized dynamics, custom preregistered finite mixture, NOT empirically validated physics',
            'hypotheses':[{ 'name':n,'plant':vars(p)} for n,p in HYPOTHESES],
            'train_count':ntrain,'first_probe':rc.PROBES[FIRST].name,
            'model_predictions':[{'probe':pr.name,'mu':[list(x) for x in mu[:,i,:]]} for i,pr in enumerate(rc.PROBES)],
            'distinct_terminal_calibrations_per_model':len(uniq),
            'calibration_argmax':{name:str(rc.CALIBRATIONS[np.argmax(Q[i])]) for i,(name,_) in enumerate(HYPOTHESES)},
            'best_fixed_schedule':list(selected),'best_fixed_one':list(fixed1),
            'best_fixed_two':list(fixed2),'training_fixed_scores':[(round(s,6),list(seq)) for s,seq in ordered],
            'evaluation':results}

if __name__=='__main__':
    pa=argparse.ArgumentParser();pa.add_argument('--dt',type=float,default=.02);pa.add_argument('--output',default='adaptive_results.json');pa.add_argument('--train',type=int,default=256);pa.add_argument('--eval',type=int,default=512);pa.add_argument('--transfer',type=int,default=128)
    args=pa.parse_args();rc.DT=args.dt;r=experiment(args.train,args.eval,args.transfer);r['dt_s']=args.dt
    Path(args.output).write_text(json.dumps(r,indent=2,allow_nan=False)+'\n')
    print('saved',args.output)
