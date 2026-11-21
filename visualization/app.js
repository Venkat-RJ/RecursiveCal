(() => {
'use strict';
const $=id=>document.getElementById(id);
const scenarios=JSON.parse($('scenarioData').textContent);
const format=x=>(x<0?'−':'')+Math.abs(x).toFixed(3);
const score=x=>Number(x).toFixed(4);
const probeLabels={
  pulse_pos_low:['↗','Positive / low'],pulse_pos_high:['⇗','Positive / high'],
  pulse_neg_low:['↙','Negative / low'],pulse_neg_high:['⇙','Negative / high'],
  pulse_pos_offset:['→','Offset / positive'],pulse_neg_offset:['←','Offset / negative'],
  reference_check:['⌖','Sensor reference']
};
const C={target:'#4f9fe8',actual:'#35c8a6',fault:'#e8a348',danger:'#e35d64',probe:'#a98aef',factory:'#e8a348'};
const state={scenario:5,view:'vehicle',budget:4.5,records:[],used:new Set(),cal:{...RC_DEFAULT},busy:false,reveal:false,motorAngle:0,mode:'tracking',comparisonComplete:false,autoRan:false};
const sc=()=>scenarios[state.scenario];
const reduced=()=>window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const matchCal=(a,b)=>['gain','friction_ff','sensor_offset'].every(k=>Math.abs(a[k]-b[k])<1e-7);
const legal=()=>({gain:RC_GAINS[+$('gain').value],friction_ff:RC_FRICTION[+$('ff').value],sensor_offset:RC_BIASES[+$('bias').value]});

function vehicleSVG(prefix,{compact=false}={}){
 const g=s=>`${prefix}-${s}`;
 return `<svg class="vehicle-svg" viewBox="0 0 850 360" role="img" aria-label="Illustrative SUV rear liftgate driven by normalized actuator simulation">
 <defs>
   <linearGradient id="${g('paint')}" x1="0" y1="0" x2=".8" y2="1"><stop stop-color="#4f6974"/><stop offset=".42" stop-color="#263e49"/><stop offset="1" stop-color="#192b36"/></linearGradient>
   <linearGradient id="${g('gate')}" x1="0" y1="0" x2="1" y2=".5"><stop stop-color="#79929a"/><stop offset=".40" stop-color="#536c78"/><stop offset="1" stop-color="#1b343d"/></linearGradient>
   <linearGradient id="${g('glass')}" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#203a4b"/><stop offset="1" stop-color="#0b1c28"/></linearGradient>
   <radialGradient id="${g('ground')}"><stop stop-color="#52737e" stop-opacity=".18"/><stop offset="1" stop-color="#304856" stop-opacity="0"/></radialGradient>
 </defs>
 <ellipse cx="426" cy="295" rx="330" ry="29" fill="url(#${g('ground')})"/>
 <path d="M52 290H808" stroke="#8ca6ad" stroke-opacity=".26" stroke-width="2"/>
 <path d="M80 301h690" stroke="#8ca6ad" stroke-opacity=".09" stroke-dasharray="4 8"/>
 <g class="suv-body">
  <path d="M95 254L95 232Q99 220 119 215L162 199 187 158Q193 146 211 143L257 111Q273 99 298 99H514Q547 99 565 117L601 155Q620 168 637 188L656 222V258Q655 267 643 269H113Q95 268 95 254Z" fill="url(#${g('paint')})" stroke="#8ba6ae" stroke-width="2.2"/>
  <path d="M191 160L256 116Q272 107 293 107H388V173H184Z" fill="url(#${g('glass')})" stroke="#7192a1" stroke-width="1.2"/>
  <path d="M400 107H517Q541 107 552 123L594 173H400Z" fill="url(#${g('glass')})" stroke="#6e8c9c" stroke-width="1.2"/>
  <path d="M392 107v155M602 173v87M177 176v85" stroke="#8197a1" stroke-opacity=".6" stroke-width="2"/>
  <path d="M164 204L604 204" stroke="#c7d8d9" stroke-opacity=".19" stroke-width="3"/>
  <path d="M105 243Q183 246 634 243" stroke="#b8d0d5" stroke-opacity=".13" stroke-width="2"/>
  <rect x="399" y="188" rx="3" width="25" height="5" fill="#8eafb8"/><rect x="261" y="188" rx="3" width="25" height="5" fill="#8eafb8"/>
  <path d="M109 222l28-6v15l-32 3z" fill="#ededd8" stroke="#c7dcc5" stroke-opacity=".5"/>
  <path d="M622 202l14 4 4 22 -19-7Z" fill="#ed7365" stroke="#f3ab9b" stroke-opacity=".7"/>
  <path d="M99 266h555" stroke="#0c1b23" stroke-width="7" stroke-linecap="round"/>
 </g>
 ${[224,552].map(x=>`<g transform="translate(${x} 269)"><circle r="47" fill="#0b141a" stroke="#3e565f" stroke-width="4"/><circle r="33" fill="#202f39" stroke="#738994" stroke-width="4"/><circle r="24" fill="#334750" stroke="#b4c3c8" stroke-width="1.8"/>${Array.from({length:5},(_,i)=>`<path d="M0 -19V-8" stroke="#d1e0df" stroke-width="4" stroke-linecap="round" transform="rotate(${i*72})"/>`).join('')}<circle r="6" fill="#b4c4c7"/></g>`).join('')}
 <path d="M629 166Q649 184 651 220V247" stroke="#e09c57" stroke-width="2.5" opacity=".7" fill="none"/>
 <g id="${g('target')}" transform="rotate(-55 615 125)" opacity=".50">
  <path d="M613 126Q628 147 648 214L648 248L631 249Q620 194 605 141Z" fill="none" stroke="${C.target}" stroke-width="4" stroke-dasharray="9 8"/>
 </g>
 <path id="${g('strut')}" d="M556 200L624 181" stroke="${C.fault}" stroke-width="8" stroke-linecap="round"/>
 <circle cx="556" cy="200" r="6" fill="#aec5c8"/><circle id="${g('strut-end')}" cx="624" cy="181" r="5" fill="#ddd6c7"/>
 <g id="${g('lid')}" transform="rotate(-28 615 125)">
  <path d="M610 125Q623 140 650 208L653 248L636 253Q624 209 602 143Z" fill="url(#${g('gate')})" stroke="${prefix==='before'?C.factory:C.actual}" stroke-width="2.8"/>
  <path d="M617 150L641 211L643 235" fill="none" stroke="#aabfc3" stroke-opacity=".65" stroke-width="2"/>
  <rect x="642" y="221" width="10" height="20" rx="3" fill="#ed7065"/>
  <path d="M604 133L616 126" stroke="#c9dde0" stroke-width="4"/>
 </g>
 <circle cx="615" cy="125" r="7" fill="#26383f" stroke="#b9c6c8" stroke-width="2"/>
 <circle cx="615" cy="125" r="2.5" fill="#e2edef"/>
 <path d="M610 75L620 75L615 83Z" fill="${C.target}" opacity=".85"/>
 ${compact?'':`<g font-family="ui-monospace,monospace" font-size="11" letter-spacing="1.1"><text x="70" y="65" fill="#87a6ad">01 / AUTOMOTIVE CONTEXT</text><text x="70" y="84" fill="#d2dee0" font-size="14" font-weight="700">POWER LIFTGATE</text><text x="70" y="102" fill="#75939d" font-size="10">POSITION MAPPED FROM 1-AXIS SIMULATOR</text><g id="${g('faultBadge')}"><rect x="690" y="68" width="114" height="25" rx="4" stroke="${C.fault}" stroke-opacity=".6" fill="#3d3128"/><circle cx="705" cy="80" r="3.2" fill="${C.fault}"/><text x="716" y="84" fill="#ebc28c" font-size="10">FAULT INJECTED</text></g><text x="72" y="332" fill="${C.actual}">● ACTUAL MOTION</text><text x="267" y="332" fill="${C.target}">- - TARGET POSITION</text></g>`}
 </svg>`;
}
for(const prefix of ['main','before','after']){$('vehicle-'+prefix).innerHTML=vehicleSVG(prefix,{compact:prefix!=='main'});}
function gateAngle(x){return 5+rcClamp((x+.5),0,1)*66;}
function paintVehicle(prefix,x,target=.28){
  const angle=gateAngle(x),r=-angle*Math.PI/180;
  $(`${prefix}-lid`).setAttribute('transform',`rotate(${-angle.toFixed(3)} 615 125)`);
  $(`${prefix}-target`).setAttribute('transform',`rotate(${-gateAngle(target).toFixed(3)} 615 125)`);
  const px=615+18*Math.cos(r)-52*Math.sin(r),py=125+18*Math.sin(r)+52*Math.cos(r);
  $(`${prefix}-strut`).setAttribute('d',`M556 200L${px.toFixed(2)} ${py.toFixed(2)}`);
  $(`${prefix}-strut-end`).setAttribute('cx',px.toFixed(2));$(`${prefix}-strut-end`).setAttribute('cy',py.toFixed(2));
  if(prefix==='main') $('gateReadout').textContent=`${Math.round(rcClamp(x+.5,0,1)*100)}%`;
  const badge=$(prefix+'-faultBadge');if(badge)badge.style.display=state.scenario===0?'none':'';
}
function paintBench(x,target=.28,v=0){
 const px=490+rcClamp(x,-.5,.5)*620,tx=490+rcClamp(target,-.5,.5)*620;
 $('carriage').setAttribute('transform',`translate(${px.toFixed(2)} 158)`);
 $('pistonShaft').setAttribute('d',`M171 158H${px.toFixed(2)}`);
 $('targetLine').setAttribute('x1',tx.toFixed(2));$('targetLine').setAttribute('x2',tx.toFixed(2));
 $('targetCaption').setAttribute('x',tx.toFixed(2));$('targetCaptionBg').setAttribute('x',(tx-48).toFixed(2));
 state.motorAngle+=v*14;$('motorRotor').setAttribute('transform',`rotate(${state.motorAngle.toFixed(2)} 12 0)`);$('benchPos').textContent=format(x);
}
function paintMain(x,target=.28,v=0,torque=0,risk=0){
 paintVehicle('main',x,target);paintBench(x,target,v);
 $('valPos').textContent=format(x);$('valVel').textContent=format(v);$('valTorque').textContent=format(torque);$('valInterventions').textContent=String(risk);
 $('valInterventions').style.color=risk?C.danger:'var(--text)';
}
function setView(which){state.view=which;$('vehicleView').hidden=which!=='vehicle';$('benchView').hidden=which!=='bench';$('btnVehicle').classList.toggle('active',which==='vehicle');$('btnBench').classList.toggle('active',which==='bench');$('btnVehicle').setAttribute('aria-pressed',String(which==='vehicle'));$('btnBench').setAttribute('aria-pressed',String(which==='bench'));$('sceneNote').textContent=which==='vehicle'?'SUV geometry is illustrative. Motion is driven by the 1D actuator simulation.':'This one-axis bench is directly driven by the simulator coordinates and equations.';}
function showStatus(message,kind='ready'){$('simStatus').textContent='● '+message.toUpperCase();$('simStatus').classList.toggle('warning',kind==='warning');}
function setBusy(b){state.busy=b;for(const id of ['btnAuto','btnCompare','btnReset','btnReplayCompare','btnTest','btnFactory','gain','ff','bias','btnVehicle','btnBench'])$(id).disabled=b;drawProbes();}
function setCal(cal){state.cal={...cal};$('gain').value=RC_GAINS.findIndex(x=>Math.abs(x-cal.gain)<1e-8);$('ff').value=RC_FRICTION.findIndex(x=>Math.abs(x-cal.friction_ff)<1e-8);$('bias').value=RC_BIASES.findIndex(x=>Math.abs(x-cal.sensor_offset)<1e-8);if($('bias').value==='-1')$('bias').value=2;updateCalInputs();}
function updateCalInputs(){$('gainValue').textContent=RC_GAINS[+$('gain').value].toFixed(2);$('ffValue').textContent=RC_FRICTION[+$('ff').value].toFixed(2);$('biasValue').textContent=RC_BIASES[+$('bias').value].toFixed(2);}
function drawScenarioButtons(){const node=$('scenarios');node.replaceChildren();scenarios.forEach((s,i)=>{const b=document.createElement('button');b.type='button';b.className='scenario-chip'+(i===state.scenario?' active':'');b.setAttribute('aria-pressed',String(i===state.scenario));const dot=document.createElement('i');dot.className='fault-dot';b.append(dot,document.createTextNode(s.name));b.onclick=()=>{if(state.busy)return;state.scenario=i;reset();};node.appendChild(b);});}
function drawProbes(){const node=$('probeButtons');node.replaceChildren();sc().reference_probes.forEach(p=>{const [symbol,label]=probeLabels[p.name];const b=document.createElement('button');b.type='button';b.className='probe'+(p.kind==='reference'?' wide':'')+(state.used.has(p.name)?' used':'');b.disabled=state.busy||state.used.has(p.name)||p.cost>state.budget+1e-8;b.title=p.name;const icon=document.createElement('span');icon.className='probe-symbol';icon.textContent=symbol;const cost=document.createElement('small');cost.className='probe-cost';cost.textContent=`${p.cost.toFixed(1)} budget units`;b.append(icon,document.createTextNode(label),cost);b.onclick=()=>runProbe(p);node.appendChild(b);});}
function updateBudget(){$('valCost').textContent=(4.5-state.budget).toFixed(2);$('budgetChip').textContent=state.budget.toFixed(2)+' LEFT';drawProbes();}
function addObservation(probe,observed){state.records.push({probe:probe.name,observed,cost:probe.cost});if(state.records.length===1)$('log').replaceChildren();const row=document.createElement('div');row.className='obs-row';const i=document.createElement('span');i.className='obs-index';i.textContent=String(state.records.length).padStart(2,'0');const content=document.createElement('div');const title=document.createElement('strong');title.textContent=probeLabels[probe.name][1];const sub=document.createElement('small');sub.textContent=(probe.kind==='reference'?'Encoder bias: ':'Δx / velocity: ')+observed.map(x=>format(x)).join(' / ');content.append(title,sub);row.append(i,content);$('log').appendChild(row);$('log').scrollTop=$('log').scrollHeight;}
function inspectParams(){$('hiddenDetails').hidden=!state.reveal;$('revealMark').textContent=state.reveal?'HIDE −':'SHOW +';if(!state.reveal)return;const node=$('hiddenDetails');node.replaceChildren();for(const [k,v] of Object.entries(sc().ground_truth)){const label=document.createElement('span');label.textContent=k.replaceAll('_',' ').toUpperCase();const num=document.createElement('b');num.textContent=v.toFixed(4);node.append(label,num);}}
function renderScore(){const plant=sc().ground_truth,cal=state.cal;const q=rcQuality(plant,cal),net=q.quality-.012*(4.5-state.budget),factory=sc().factory_quality,delta=net-factory;$('factoryScore').textContent=score(factory);$('currentScore').textContent=score(net);$('scoreDelta').textContent=(delta>=0?'+':'−')+Math.abs(delta).toFixed(4);$('scoreDelta').style.color=delta>0?C.actual:delta<0?C.danger:'var(--text)';$('scoreCaption').textContent=delta>0?'improved vs factory':'vs factory';$('factoryQualityMini').textContent=score(factory);$('currentQualityMini').textContent=score(q.quality);$('compareOutcome').textContent=matchCal(cal,RC_DEFAULT)?'Same controller settings. Run Bayesian diagnosis or adjust calibration to compare a change.':`Factory quality ${score(factory)} → calibrated quality ${score(q.quality)}. ${delta>=0?'Net reward improves':'Net reward does not improve'} after diagnostic cost (${(4.5-state.budget).toFixed(1)}).`;return {q,net,delta};}
function plot(mode='tracking',progress=1,probeFrames=null){
 const canvas=$('plot'),box=canvas.getBoundingClientRect(),W=box.width,H=box.height;if(W<10||H<10)return;const dpr=Math.min(2,devicePixelRatio||1);canvas.width=Math.round(W*dpr);canvas.height=Math.round(H*dpr);const ctx=canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,W,H);
 const margin={l:42,r:12,t:9,b:22};const pw=W-margin.l-margin.r,ph=H-margin.t-margin.b,yy=v=>margin.t+(.5-v)*ph;
 ctx.font='10px ui-monospace,monospace';ctx.textAlign='right';for(const y of [-.5,-.25,0,.25,.5]){const py=yy(y);ctx.strokeStyle='#49667444';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(margin.l,py);ctx.lineTo(W-margin.r,py);ctx.stroke();ctx.fillStyle='#7e9da5';ctx.fillText((y>0?'+':'')+y.toFixed(2),margin.l-9,py+3);}
 const duration=mode==='probe'?(probeFrames?.at(-1)?.t||.55):1.8;
 for(let i=0;i<=4;i++){const x=margin.l+(i/4)*pw;ctx.strokeStyle='#344f5c44';ctx.beginPath();ctx.moveTo(x,margin.t);ctx.lineTo(x,H-margin.b);ctx.stroke();ctx.textAlign='center';ctx.fillStyle='#708f98';ctx.fillText((duration*i/4).toFixed(2),x,H-4);}
 function line(frames,color,width,dash=[],max=1){if(!frames?.length)return;ctx.save();ctx.beginPath();ctx.rect(margin.l,margin.t,pw,ph);ctx.clip();ctx.strokeStyle=color;ctx.lineWidth=width;ctx.lineJoin='round';ctx.lineCap='round';ctx.setLineDash(dash);ctx.beginPath();const stop=Math.min(frames.length,Math.max(1,Math.round(frames.length*max)));for(let i=0;i<stop;i++){const p=frames[i],x=margin.l+p.t/duration*pw,y=yy(p.x);if(!i)ctx.moveTo(x,y);else ctx.lineTo(x,y);}ctx.stroke();ctx.restore();}
 if(mode==='probe'){$('plotTitle').textContent='Diagnostic pulse response';line(probeFrames,C.actual,2.6,[],progress);ctx.strokeStyle=C.probe;ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(margin.l,margin.t+3);ctx.lineTo(margin.l+pw*progress,margin.t+3);ctx.stroke();}
 else {$('plotTitle').textContent='Position tracking';const plant=sc().ground_truth;const before=rcClosedLoop(plant,RC_DEFAULT,-.15,.28);const after=rcClosedLoop(plant,state.cal,-.15,.28);ctx.strokeStyle=C.target;ctx.lineWidth=1.7;ctx.setLineDash([6,5]);ctx.beginPath();ctx.moveTo(margin.l,yy(.28));ctx.lineTo(W-margin.r,yy(.28));ctx.stroke();ctx.setLineDash([]);line(before.frames,C.factory,2,[7,5],progress);line(after.frames,C.actual,2.8,[],progress);}
 if(progress<.999){const x=margin.l+pw*progress;ctx.beginPath();ctx.moveTo(x,margin.t);ctx.lineTo(x,H-margin.b);ctx.strokeStyle='#d0e9e96b';ctx.setLineDash([2,5]);ctx.lineWidth=1;ctx.stroke();ctx.setLineDash([]);}
}
function renderComparisonStatic(){paintVehicle('before',-.15);paintVehicle('after',-.15);$('beforeProgress').style.width='0%';$('afterProgress').style.width='0%';$('beforePosition').textContent='Position '+format(-.15);$('afterPosition').textContent='Position '+format(-.15);renderScore();}
function reset(){state.budget=4.5;state.records=[];state.used.clear();state.motorAngle=0;state.mode='tracking';state.autoRan=false;state.comparisonComplete=false;setCal(RC_DEFAULT);$('log').innerHTML='<p class="no-measurement">No measurements yet.<br>Try a low-torque diagnostic pulse.</p>';$('scenarioTitle').textContent=sc().name;drawScenarioButtons();updateBudget();showStatus('System ready');inspectParams();paintMain(-.15,.28);plot();renderComparisonStatic();}
const pause=ms=>new Promise(r=>setTimeout(r,reduced()?30:ms));
function animate(frames,{duration=1550,mode='tracking',target=.28,risk=0}={}){return new Promise(resolve=>{const start=performance.now(),dur=reduced()?160:duration,last=frames.at(-1);function tick(now){const frac=Math.min(1,(now-start)/dur),ix=Math.min(frames.length-1,Math.round(frac*(frames.length-1))),f=frames[ix];paintMain(f.x,target,f.v,f.torque||0,risk);plot(mode,frac,mode==='probe'?frames:null);if(frac<1)requestAnimationFrame(tick);else{paintMain(last.x,target,last.v,last.torque||0,risk);plot(mode,1,mode==='probe'?frames:null);resolve();}}requestAnimationFrame(tick);});}
async function executeProbeInternal(probe,reference=null){
 if(state.used.has(probe.name)||probe.cost>state.budget+1e-8)return;
 state.used.add(probe.name);state.budget=Math.round((state.budget-probe.cost)*100)/100;updateBudget();showStatus('Diagnostic in progress');
 const trace=rcPulseTrace(sc().ground_truth,probe);
 if(probe.kind!=='reference'){await animate(trace.frames,{mode:'probe',duration:950,target:probe.fixture_x,risk:trace.risk});}else{paintMain(0,0);await pause(350);}
 const obs=reference?.observed??probe.prediction.map((v,i)=>v+rcNoise(sc().seed*13+state.records.length*71+sc().reference_probes.findIndex(q=>q.name===probe.name)*997+i*123,i===0?(probe.kind==='reference'?.006:.004):.009));
 addObservation(probe,obs);showStatus('Measurement recorded');renderScore();
}
async function runProbe(probe){if(state.busy)return;setBusy(true);try{await executeProbeInternal(probe)}finally{setBusy(false)}}
async function testCalibration(){if(state.busy)return;setBusy(true);try{state.cal=legal();showStatus('Verifying calibration');const trace=rcClosedLoop(sc().ground_truth,state.cal,-.15,.28);await animate(trace.frames,{duration:1800,risk:trace.risk});const m=renderScore();showStatus(m.delta>=0?'Calibration verified':'No net improvement',m.delta>=0?'ready':'warning');}finally{setBusy(false)}}
async function compareRuns({scroll=false}={}){
 const plant=sc().ground_truth,before=rcClosedLoop(plant,RC_DEFAULT,-.15,.28),after=rcClosedLoop(plant,state.cal,-.15,.28),duration=reduced()?250:2250,started=performance.now();
 if(scroll)$('comparison').scrollIntoView({behavior:reduced()?'instant':'smooth',block:'center'});
 return new Promise(resolve=>{function tick(now){const t=Math.min(1,(now-started)/duration),indexB=Math.min(before.frames.length-1,Math.floor(t*(before.frames.length-1))),indexA=Math.min(after.frames.length-1,Math.floor(t*(after.frames.length-1))),fb=before.frames[indexB],fa=after.frames[indexA];paintVehicle('before',fb.x);paintVehicle('after',fa.x);$('beforeProgress').style.width=(t*100).toFixed(2)+'%';$('afterProgress').style.width=(t*100).toFixed(2)+'%';$('beforePosition').textContent='Position '+format(fb.x)+'  /  Error '+Math.abs(.28-fb.x).toFixed(3);$('afterPosition').textContent='Position '+format(fa.x)+'  /  Error '+Math.abs(.28-fa.x).toFixed(3);if(t<1)requestAnimationFrame(tick);else{state.comparisonComplete=true;resolve();}}requestAnimationFrame(tick);});}
async function runCompare(){if(state.busy)return;setBusy(true);try{showStatus('Comparing two runs');await compareRuns({scroll:true});renderScore();showStatus('Comparison complete');}finally{setBusy(false)}}
async function runAuto(){if(state.busy)return;reset();setBusy(true);const btn=$('btnAuto');btn.textContent='DIAGNOSIS RUNNING…';try{showStatus('Bayesian baseline running');for(const rec of sc().bayesian.probes){const p=sc().reference_probes.find(p=>p.name===rec.probe);if(!p)throw new Error('Missing diagnostic action '+rec.probe);await executeProbeInternal(p,rec);await pause(145);}setCal(sc().bayesian.calibration);const trace=rcClosedLoop(sc().ground_truth,state.cal,-.15,.28);await animate(trace.frames,{duration:1250,risk:trace.risk});const result=renderScore();if(Math.abs(result.net-sc().bayesian.net_reward)>1e-8)console.error('Score parity regression',result.net,sc().bayesian.net_reward);state.autoRan=true;showStatus('Bayesian result verified');await compareRuns({scroll:false});}finally{btn.innerHTML='<span class="play-icon">▶</span> Run Bayesian diagnosis';setBusy(false);}}
$('btnVehicle').addEventListener('click',()=>setView('vehicle'));
$('btnBench').addEventListener('click',()=>setView('bench'));
$('btnAuto').addEventListener('click',runAuto);
$('btnCompare').addEventListener('click',runCompare);
$('btnReplayCompare').addEventListener('click',runCompare);
$('btnTest').addEventListener('click',testCalibration);
$('btnFactory').addEventListener('click',()=>{if(state.busy)return;setCal(RC_DEFAULT);renderScore();plot();renderComparisonStatic();showStatus('Factory values restored');});
$('btnReset').addEventListener('click',()=>{if(!state.busy)reset()});
$('btnReveal').addEventListener('click',()=>{state.reveal=!state.reveal;inspectParams()});
for(const k of ['gain','ff','bias'])$(k).addEventListener('input',()=>{updateCalInputs();if(!state.busy){state.cal=legal();renderScore();plot();renderComparisonStatic();showStatus('Controller adjusted')}});
window.addEventListener('resize',()=>plot(state.mode));
setView('vehicle');reset();
window.RecursiveCalDemo={scenarios,state,physics:{acceleration:rcAcceleration,quality:rcQuality,closedLoop:rcClosedLoop,pulse:rcPulseTrace},runAuto,runCompare,vehicleSVG,paintVehicle};
})();
