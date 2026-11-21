(() => {
'use strict';
const $=id=>document.getElementById(id);
const scenarios=JSON.parse($('scenarioData').textContent);
const f3=x=>(x<0?'−':'')+Math.abs(x).toFixed(3);
const f2=x=>(x<0?'−':'')+Math.abs(x).toFixed(2);
const fmtScore=x=>Number(x).toFixed(4);
const labels={pulse_pos_low:['＋','Positive / low'],pulse_pos_high:['↗','Positive / high'],pulse_neg_low:['−','Negative / low'],pulse_neg_high:['↙','Negative / high'],pulse_pos_offset:['⇢','Offset / positive'],pulse_neg_offset:['⇠','Offset / negative'],reference_check:['⌖','Sensor reference']};
const state={index:5,budget:4.5,records:[],used:new Set(),cal:{...RC_DEFAULT},animation:false,angle:0,reveal:false,mode:'tracking',plotProgress:1,runningAfter:false};
const svgCar=$('carriage'),shaft=$('pistonShaft'),targetLine=$('targetLine'),targetText=$('targetCaption'),targetBg=$('targetCaptionBg');
const sc=()=>scenarios[state.index];
const clone=x=>JSON.parse(JSON.stringify(x));
const matches=(a,b)=>['gain','friction_ff','sensor_offset'].every(k=>Math.abs(a[k]-b[k])<1e-8);
const getCal=()=>({gain:RC_GAINS[+$('gain').value],friction_ff:RC_FRICTION[+$('ff').value],sensor_offset:RC_BIASES[+$('bias').value]});
function setCal(c){$('gain').value=RC_GAINS.indexOf(c.gain);$('ff').value=RC_FRICTION.indexOf(c.friction_ff);$('bias').value=RC_BIASES.findIndex(v=>Math.abs(v-c.sensor_offset)<1e-7); if($('bias').value==='-1')$('bias').value=2; updateCalReadouts();state.cal={...c};}
function updateCalReadouts(){$('gainValue').textContent=RC_GAINS[+$('gain').value].toFixed(2);$('ffValue').textContent=RC_FRICTION[+$('ff').value].toFixed(2);$('biasValue').textContent=f2(RC_BIASES[+$('bias').value]);}
function updateBusy(b){state.animation=b;document.body.classList.toggle('is-busy',b);['btnAuto','btnTest','btnReset','btnFactory','gain','ff','bias'].forEach(id=>$(id).disabled=b);drawProbeButtons();}
function setStatus(msg,type='ready'){$('simStatus').textContent='● '+msg.toUpperCase();$('simStatus').style.color=type==='bad'?'#f9a492':type==='live'?'#84f9df':'#a4bfc2';}
function renderMachine(x,target=0.28,v=0,torque=0,risk=0){
  const px=490+rcClamp(x,-.5,.5)*620;
  const tx=490+rcClamp(target,-.5,.5)*620;
  svgCar.setAttribute('transform',`translate(${px.toFixed(2)} 158)`);
  shaft.setAttribute('d',`M171 158H${px.toFixed(2)}`);
  targetLine.setAttribute('x1',tx.toFixed(2));targetLine.setAttribute('x2',tx.toFixed(2));
  targetText.setAttribute('x',tx.toFixed(2));targetBg.setAttribute('x',(tx-48).toFixed(2));
  state.angle+=v*15;$('motorRotor').setAttribute('transform',`rotate(${state.angle.toFixed(2)} 12 0)`);
  $('posBig').textContent=f3(x);$('valPos').textContent=f3(x);$('valVel').textContent=f3(v);$('valTorque').textContent=f3(torque);$('valInterventions').textContent=String(risk);
}
function drawScenarioTabs(){const wrap=$('scenarios');wrap.innerHTML='';scenarios.forEach((s,i)=>{const b=document.createElement('button');b.className='scenario'+(i===state.index?' active':'');b.textContent=s.name;b.type='button';b.setAttribute('aria-pressed',String(i===state.index));b.onclick=()=>{if(state.animation)return;state.index=i;reset()};wrap.appendChild(b)});}
function drawProbeButtons(){const root=$('probeButtons');root.innerHTML='';for(const p of sc().reference_probes){const [symbol,text]=labels[p.name];const b=document.createElement('button');b.type='button';b.className='probe-btn'+(p.kind==='reference'?' wide':'');b.innerHTML=`<span class="probe-icon">${symbol}</span>${text}<span class="price">${p.cost.toFixed(1)} UNITS</span>`;b.disabled=state.animation||state.used.has(p.name)||p.cost>state.budget+1e-9;b.title=state.used.has(p.name)?'Probe already used':p.name;b.onclick=()=>executeProbe(p);root.appendChild(b);}}
function updateBudget(){$('valCost').textContent=f2(4.5-state.budget)+' / 4.50';$('budgetChip').textContent=f2(state.budget)+' LEFT';$('budgetChip').style.color=state.budget<1?'#ffb77b':'#94f7d8';drawProbeButtons();}
function addLog(p,observed){state.records.push({name:p.name,observed,cost:p.cost});const node=document.createElement('div');node.className='log-row';const obs=observed.map(v=>f3(v)).join(' · ');node.innerHTML=`<span class="log-no">${String(state.records.length).padStart(2,'0')}</span><div class="log-body"><strong>${labels[p.name][1]}</strong><small>${p.kind==='reference'?'encoder bias':'Δx / v'}: ${obs}</small></div>`;if(state.records.length===1)$('log').innerHTML='';$('log').appendChild(node);$('log').scrollTop=$('log').scrollHeight;}
function renderReveal(){const hidden=$('hiddenDetails');hidden.hidden=!state.reveal;$('revealMark').textContent=state.reveal?'HIDE −':'SHOW +';if(!state.reveal)return;hidden.innerHTML='';for(const [key,val] of Object.entries(sc().ground_truth)){const a=document.createElement('span'),b=document.createElement('b');a.textContent=key.replace(/_/g,' ').toUpperCase();b.textContent=val.toFixed(3);hidden.append(a,b);}}
function updateScores(cal=state.cal){const plant=sc().ground_truth;const after=rcQuality(plant,cal);const score=after.quality-0.012*(4.5-state.budget);const baseline=sc().factory_quality;const delta=score-baseline;$('factoryScore').textContent=fmtScore(baseline);$('currentScore').textContent=fmtScore(score);$('scoreDelta').textContent=(delta>=0?'+':'−')+Math.abs(delta).toFixed(4);$('scoreDelta').style.color=delta>0?'#89f4df':delta<0?'#ffba91':'#d8eae8';$('scoreCaption').textContent=delta>0?'Higher than factory':'Compared with factory';return after;}
function drawChart(mode='tracking',progress=1,probeFrames=null){
  const canvas=$('plot'),rect=canvas.getBoundingClientRect();if(rect.width<10)return;
  const dpr=Math.min(2,window.devicePixelRatio||1);canvas.width=Math.ceil(rect.width*dpr);canvas.height=Math.ceil(rect.height*dpr);
  const ctx=canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);const W=rect.width,H=rect.height;
  const m={l:37,r:12,t:10,b:22},plotW=W-m.l-m.r,plotH=H-m.t-m.b;
  ctx.clearRect(0,0,W,H);const yy=v=>m.t+(0.5-v)/1.0*plotH;
  for(const y of [-.5,-.25,0,.25,.5]){const py=yy(y);ctx.beginPath();ctx.strokeStyle='rgba(109,154,166,0.14)';ctx.lineWidth=1;ctx.moveTo(m.l,py);ctx.lineTo(W-m.r,py);ctx.stroke();ctx.fillStyle='#72909b';ctx.font='10px ui-monospace,monospace';ctx.textAlign='right';ctx.fillText((y>0?'+':'')+y.toFixed(2),m.l-9,py+3)}
  const duration=mode==='probe'?(probeFrames?.at(-1)?.t||.55):1.8;
  for(let k=0;k<=4;k++){const x=m.l+k/4*plotW;ctx.beginPath();ctx.strokeStyle='rgba(109,154,166,0.10)';ctx.moveTo(x,m.t);ctx.lineTo(x,H-m.b);ctx.stroke();ctx.fillStyle='#6c8791';ctx.textAlign='center';ctx.fillText((duration*k/4).toFixed(2),x,H-5)}
  function line(frames,color,width,dashed=[],limit=1){if(!frames?.length)return;ctx.save();ctx.beginPath();ctx.rect(m.l,m.t,plotW,plotH);ctx.clip();ctx.beginPath();ctx.strokeStyle=color;ctx.lineWidth=width;ctx.setLineDash(dashed);ctx.lineJoin='round';ctx.lineCap='round';const max=Math.max(1,Math.ceil(frames.length*limit));for(let i=0;i<max&&i<frames.length;i++){const f=frames[i],x=m.l+f.t/duration*plotW,y=yy(f.x);i?ctx.lineTo(x,y):ctx.moveTo(x,y);}ctx.stroke();ctx.restore();}
  if(mode==='probe'){
    $('plotTitle').textContent='Diagnostic pulse response';
    line(probeFrames,'#7af9da',2.7,[],progress);
  }else{
    $('plotTitle').textContent='Tracking response';
    const plant=sc().ground_truth,start=-.15,target=.28;
    const before=rcClosedLoop(plant,RC_DEFAULT,start,target);
    const after=rcClosedLoop(plant,state.cal,start,target);
    ctx.beginPath();ctx.strokeStyle='rgba(255,185,112,.78)';ctx.lineWidth=1.3;ctx.setLineDash([6,5]);const tarY=yy(target);ctx.moveTo(m.l,tarY);ctx.lineTo(W-m.r,tarY);ctx.stroke();ctx.setLineDash([]);
    line(before.frames,'rgba(119,153,176,.82)',2,[5,4]);
    if(!matches(state.cal,RC_DEFAULT)||progress<1)line(after.frames,'#83ffe3',2.8,[],progress);
  }
  const x=m.l+plotW*progress;if(progress<1){ctx.beginPath();ctx.moveTo(x,m.t);ctx.lineTo(x,H-m.b);ctx.strokeStyle='rgba(127,255,220,.44)';ctx.lineWidth=1;ctx.setLineDash([3,5]);ctx.stroke();ctx.setLineDash([]);}
}
function reset(){state.budget=4.5;state.records=[];state.used=new Set();state.mode='tracking';state.angle=0;state.currentFrames=null;$('log').innerHTML='<div class="empty-log">No measurements yet.<br>Choose a diagnostic probe.</div>';setCal(RC_DEFAULT);$('scenarioTitle').textContent=sc().name.toUpperCase();setStatus('System ready');drawScenarioTabs();updateBudget();renderReveal();renderMachine(-.15,.28,0,0,0);updateScores();drawChart();}
function sleep(ms){return new Promise(resolve=>setTimeout(resolve,ms))}
function animate(frames,{duration=1600,mode='tracking',target=.28,baseRisk=0}={}){
  return new Promise(resolve=>{
   const started=performance.now(),last=frames[frames.length-1];
   function tick(now){const progress=Math.max(0,Math.min(1,(now-started)/duration));const ix=Math.max(0,Math.min(frames.length-1,Math.floor(progress*(frames.length-1)))),f=frames[ix];renderMachine(f.x,target,f.v,f.torque||0,baseRisk);drawChart(mode,progress,mode==='probe'?frames:null);if(progress<1)requestAnimationFrame(tick);else{renderMachine(last.x,target,last.v,last.torque||0,baseRisk);drawChart(mode,1,mode==='probe'?frames:null);resolve();}}
   requestAnimationFrame(tick);
  });
}
async function executeProbe(p,record=null){if(state.animation||state.used.has(p.name)||p.cost>state.budget+1e-9)return;updateBusy(true);try{await executeProbeInternal(p,record)}finally{updateBusy(false)}}
async function executeProbeInternal(p,record=null){if(state.used.has(p.name)||p.cost>state.budget+1e-9)return;state.used.add(p.name);state.budget=Math.round((state.budget-p.cost)*100)/100;updateBudget();setStatus('Diagnostic running','live');const plant=sc().ground_truth;const trace=rcPulseTrace(plant,p);if(p.kind!=='reference'){await animate(trace.frames,{mode:'probe',duration:1300,target:p.fixture_x});}else{renderMachine(0,0,0,0);await sleep(450);}const observed=record?.observed||p.prediction.map((v,i)=>v+rcNoise(sc().seed*13+state.records.length*71+sc().reference_probes.findIndex(q=>q.name===p.name)*997+i*123,i===0?(p.kind==='reference'?0.006:0.004):0.009));addLog(p,observed);setStatus('Measurement captured');updateScores();}
async function runTest(){if(state.animation)return;updateBusy(true);try{state.cal=getCal();setStatus('Calibration verifying','live');const plant=sc().ground_truth,trace=rcClosedLoop(plant,state.cal,-.15,.28);await animate(trace.frames,{duration:2400,mode:'tracking',target:.28,baseRisk:trace.risk});const evald=updateScores();const delta=evald.quality-0.012*(4.5-state.budget)-sc().factory_quality;setStatus(delta>=0?'Verified + improvement':'Verified / no gain',delta>=0?'live':'bad');}finally{updateBusy(false)}}
async function runAuto(){if(state.animation)return;reset();updateBusy(true);$('btnAuto').textContent='DIAGNOSING…';try{setStatus('Bayesian baseline running','live');const plan=sc().bayesian;for(const rec of plan.probes){const p=sc().reference_probes.find(p=>p.name===rec.probe);await executeProbeInternal(p,rec);await sleep(180);}setCal(plan.calibration);setStatus('Calibration verifying','live');const trace=rcClosedLoop(sc().ground_truth,state.cal,-.15,.28);await animate(trace.frames,{duration:2100,mode:'tracking',target:.28,baseRisk:trace.risk});const result=updateScores(),net=result.quality-.012*(4.5-state.budget);const error=Math.abs(net-plan.net_reward);if(error>1e-8)console.warn('Physics mismatch vs Python reference:',error);setStatus(net>=sc().factory_quality?'Bayesian / gain verified':'Bayesian / no gain',net>=sc().factory_quality?'live':'bad');}finally{$('btnAuto').innerHTML='<span>▶</span> Replay Bayesian diagnosis';updateBusy(false)}}
$('btnReset').onclick=reset;$('btnTest').onclick=runTest;$('btnAuto').onclick=runAuto;$('btnFactory').onclick=()=>{if(state.animation)return;setCal(RC_DEFAULT);runTest()};for(const id of ['gain','ff','bias'])$(id).oninput=()=>{updateCalReadouts();if(!state.animation)setStatus('Calibration adjusted')};$('btnReveal').onclick=()=>{state.reveal=!state.reveal;renderReveal()};window.addEventListener('resize',()=>drawChart(state.mode,1),{passive:true});
reset();
// Self-test exposed for browser automation and offline parity checks.
window.RecursiveCalDemo={scenarios,physics:{acceleration:rcAcceleration,closedLoop:rcClosedLoop,quality:rcQuality,pulse:rcPulseTrace},state};
})();
