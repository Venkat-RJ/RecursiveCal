"""CPU contextual-bandit RL pilot on new physically motivated synthetic diagnosis mixture.
The policy gets only first pulse readings and a Bayes posterior from those readings.
It chooses a second probe or STOP. Bayesian inference handles final calibration.
All counterfactual second-action rewards are precomputed by the simulator for
speed, but the learner observes only reward for the action it actually takes.
This is not language-model RL or end-to-end learned calibration.
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
from pathlib import Path
import numpy as np
import torch
from torch import nn
if __package__:
    from . import adaptive_benchmark as ab
else:
    import adaptive_benchmark as ab

torch.set_num_threads(1)
SECOND_ACTIONS=np.array([-1]+[j for j in range(ab.NPROBES) if j!=ab.FIRST],dtype=int)

class QNetwork(nn.Module):
    def __init__(self):
        super().__init__()
        self.net=nn.Sequential(nn.Linear(ab.N+2,64),nn.Tanh(),nn.Linear(64,64),nn.Tanh(),
                               nn.Linear(64,len(SECOND_ACTIONS)))
    def forward(self,x):return self.net(x)

def prepare_data(hidden,obs,mu,Q,jittered=None):
    first=obs[:,ab.FIRST,:]
    n=len(hidden)
    r=(mu[None,:,ab.FIRST,:2]-first[:,None,:])/ab.SIGMA[None,ab.FIRST,:2]
    logw=np.log(ab.P[None,:])-.5*np.sum(r*r,axis=2)
    logw-=logw.max(axis=1,keepdims=True)
    w=np.exp(logw);w/=w.sum(axis=1,keepdims=True)
    features=np.hstack([first[:,0,None]/.10,first[:,1,None]/.35,w*4.0]).astype('float32')
    reward_table=np.zeros((n,len(SECOND_ACTIONS)),dtype=np.float32)
    for a,j in enumerate(SECOND_ACTIONS):
        if j==-1:ww=w.copy();cost=0.
        else:
            d=1 if j==ab.NPROBES-1 else 2
            r=(mu[None,:,j,:d]-obs[:,None,j,:d])/ab.SIGMA[None,j,:d]
            logs=np.log(np.maximum(w,1e-300))-.5*np.sum(r*r,axis=2)
            logs-=logs.max(axis=1,keepdims=True)
            ww=np.exp(logs);ww/=ww.sum(axis=1,keepdims=True)
            cost=ab.COST[j]
        cal=np.argmax(ww@Q,axis=1)
        if jittered is None:quality=Q[hidden,cal]
        else:quality=np.array([ab.rc.calibration_quality(p,ab.rc.CALIBRATIONS[int(c)]) for p,c in zip(jittered,cal)])
        reward_table[:,a]=(quality-ab.LAMBDA*(ab.COST[ab.FIRST]+cost)).astype('float32')
    return features,reward_table

def train(seed,features,reward_table,iterations=300,batch=128):
    torch.manual_seed(seed);rng=np.random.default_rng(seed)
    net=QNetwork()
    optimizer=torch.optim.Adam(net.parameters(),lr=.0015)
    n=len(features);epochs=[]
    for step in range(iterations):
        idx=rng.integers(0,n,batch)
        inputs=torch.from_numpy(features[idx])
        with torch.no_grad():prediction=net(inputs).numpy()
        epsilon=.55-.45*step/max(1,iterations-1)
        greedy=np.argmax(prediction,axis=1)
        explore=rng.random(batch)<epsilon
        chosen=np.where(explore,rng.integers(0,len(SECOND_ACTIONS),batch),greedy)
        # Environment's reward is only observed for the selected legal action.
        observed=reward_table[idx,chosen]
        pred=net(inputs).gather(1,torch.from_numpy(chosen[:,None])).flatten()
        # Standard contextual bandit regression target; no counterfactual targets.
        target=(torch.from_numpy(observed)-.8)*10
        loss=((pred-target)**2).mean()
        optimizer.zero_grad();loss.backward();optimizer.step()
        if step%50==0 or step==iterations-1:epochs.append([step,round(float(loss.item()),5),round(float(observed.mean()),5),round(float(epsilon),4)])
    return net,epochs

def evaluate(net,features,reward_table):
    with torch.no_grad():
        idx=np.argmax(net(torch.from_numpy(features)).numpy(),axis=1)
    reward=reward_table[np.arange(len(idx)),idx]
    return {'mean_net_reward':round(float(np.mean(reward)),6),
            'choices':{('STOP' if j<0 else ab.rc.PROBES[j].name):int(np.sum(idx==a)) for a,j in enumerate(SECOND_ACTIONS)},
            'per_action_index':idx,'per_episode_reward':reward}

def main():
    pa=argparse.ArgumentParser();pa.add_argument('--out',default='rl_adaptive_results.json');pa.add_argument('--train',type=int,default=20000);pa.add_argument('--steps',type=int,default=350);pa.add_argument('--eval',type=int,default=2048);pa.add_argument('--transfer',type=int,default=512)
    args=pa.parse_args();mu,Q=ab.model_tables()
    ev_h,ev_obs,_=ab.make_dataset(args.eval,9202026,mu)
    tr_h,tr_obs,tr_jitter=ab.make_dataset(args.transfer,7212026,mu,True)
    ood_sets={}
    for fam,seed in [('high_load',981138),('extreme_deadzone',883388)]:
        oo_h,oo_obs,oo_plant=ab.make_ood_dataset(args.transfer,seed,mu,fam)
        ood_sets[fam]=prepare_data(oo_h,oo_obs,mu,Q,oo_plant)
    xev,rev=prepare_data(ev_h,ev_obs,mu,Q)
    xtr,rtr=prepare_data(tr_h,tr_obs,mu,Q,tr_jitter)
    fixed_schedule=(2,6) # Selected on independent 1024-episode training split.
    baselines={
        'in_model':{'fixed':ab.eval_schedule(fixed_schedule,ev_h,ev_obs,mu,Q), 'bayes':ab.eval_adaptive(ev_h,ev_obs,mu,Q)[0]},
        'jitter':{'fixed':ab.eval_schedule(fixed_schedule,tr_h,tr_obs,mu,Q,tr_jitter), 'bayes':ab.eval_adaptive(tr_h,tr_obs,mu,Q,tr_jitter)[0]}}
    models=[]
    for seed in [13,37,103]:
        h,obs,_=ab.make_dataset(args.train,1000000+seed,mu)
        x,rewards=prepare_data(h,obs,mu,Q)
        model,logs=train(seed,x,rewards,iterations=args.steps)
        evalr=evaluate(model,xev,rev); transferr=evaluate(model,xtr,rtr)
        oodr={family:evaluate(model,*arrays) for family,arrays in ood_sets.items()}
        paired={}
        for split,result in [('in_model',evalr),('jitter',transferr)]:
            paired[split]={}
            for comparator,values in baselines[split].items():
                delta=result['per_episode_reward']-values
                paired[split][f'minus_{comparator}']=round(float(np.mean(delta)),6)
                paired[split][f'minus_{comparator}_95pct_bootstrap']=ab.ci(delta,seed=seed+53)
        print('seed',seed,'heldout',evalr['mean_net_reward'],'jitter',transferr['mean_net_reward'], 'OOD', {k:x['mean_net_reward'] for k,x in oodr.items()},flush=True)
        models.append({'seed':seed,'train_records':len(h),'train_log':logs,'paired_comparisons':paired,
                       'in_model':{k:v for k,v in evalr.items() if k not in ('per_action_index','per_episode_reward')},
                       'jitter':{k:v for k,v in transferr.items() if k not in ('per_action_index','per_episode_reward')},
                       'ood':{family:{k:v for k,v in result.items() if k not in ('per_action_index','per_episode_reward')} for family,result in oodr.items()}})
    res={'type':'contextual-bandit RL with single observed reward and fixed Bayesian final calibration; not model-free multi-step RL',
         'first_probe':ab.rc.PROBES[ab.FIRST].name,
         'action_set':[('STOP' if j<0 else ab.rc.PROBES[j].name) for j in SECOND_ACTIONS],
         'train_samples_per_seed':args.train,'gradient_steps':args.steps,
         'training_seeds':3,'seeds':models}
    Path(args.out).write_text(json.dumps(res,indent=2)+'\n')
    print('Saved',args.out)
if __name__=='__main__':main()
