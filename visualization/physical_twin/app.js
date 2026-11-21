(function(){'use strict';
const p=window.TailgatePhysics;
const $=id=>document.getElementById(id);
const names={healthy:'Nominal system. No injected degradation.',friction:'Hinge resistance increased 3.1×.',motor:'Actuator drive efficiency reduced to 57%.',load:'Tailgate mass increased from 25 to 33 kg.',sensor:'Position sensor reports an 4.9° offset.',combined:'Drive efficiency 63%, higher friction and heavier load.',gas:'Gas-spring assistance reduced to 48%.'};
const referencePresets={
 healthy:{gain:1.7,friction_ff:0,gravity_ff:1.06,sensor_comp:0},
 friction:{gain:1.7,friction_ff:15,gravity_ff:1.06,sensor_comp:0},
 motor:{gain:1.7,friction_ff:23,gravity_ff:1.20,sensor_comp:0},
 load:{gain:1.7,friction_ff:15,gravity_ff:1.20,sensor_comp:0},
 sensor:{gain:1.7,friction_ff:0,gravity_ff:1.06,sensor_comp:.085},
 combined:{gain:1.7,friction_ff:30,gravity_ff:1.20,sensor_comp:0},
 gas:{gain:1.7,friction_ff:30,gravity_ff:1.20,sensor_comp:0}
};
let scene;
try{scene=new PhysicalRenderer($('scene'));}catch(err){$('unsupported').hidden=false;$('unsupported').textContent='WebGL2 unavailable: '+err.message;console.error(err);return;}
window.__recursivecal={scene,physics:p};
let state={fault:'combined',controller:'factory',time:3.45,playing:false,compare:false,cal:{gain:1,friction_ff:8,gravity_ff:1,sensor_comp:0},factoryRun:null,tunedRun:null,last:0,labels:false,visible:true};
const fmt=(n,dec=1)=>Number(n).toFixed(dec);
function refresh(){state.factoryRun=p.simulate(p.scenarios[state.fault],p.factory);state.tunedRun=p.simulate(p.scenarios[state.fault],state.cal);refreshSummary();render();}
function frame(run,time){const frames=run.frames;if(time<=0)return frames[0];if(time>=frames.at(-1).t)return frames.at(-1);
 let lo=0,hi=frames.length-1;while(hi-lo>1){let mid=(hi+lo)>>1;if(frames[mid].t<time)lo=mid;else hi=mid;}
 const a=frames[lo],b=frames[hi],k=(time-a.t)/(b.t-a.t);
 let f={};for(const field of ['q','target','vel','current','force','stroke','tau','error'])f[field]=a[field]*(1-k)+b[field]*k;return f;
}
function activeRun(){return state.controller==='factory'?state.factoryRun:state.tunedRun;}
function chart(){const canvas=$('plot');let rect=canvas.getBoundingClientRect(),dpr=Math.min(window.devicePixelRatio||1,2),W=Math.max(1,Math.round(rect.width*dpr)),H=Math.max(1,Math.round(rect.height*dpr));if(canvas.width!==W||canvas.height!==H){canvas.width=W;canvas.height=H;}
 const ctx=canvas.getContext('2d');ctx.clearRect(0,0,W,H);ctx.scale(dpr,dpr);const w=rect.width,h=rect.height;
 const area={left:28,right:w-9,top:8,bottom:h-19};const x=t=>area.left+t/p.RUNTIME*(area.right-area.left),y=q=>area.bottom-q/(p.MAX_Q*1.09)*(area.bottom-area.top);
 ctx.font='9px ui-monospace,SFMono-Regular,monospace';ctx.textAlign='right';ctx.lineWidth=.8;
 for(const value of [0,20,40,60,80]){let py=y(value*Math.PI/180);ctx.strokeStyle='#273a49';ctx.beginPath();ctx.moveTo(area.left,py);ctx.lineTo(area.right,py);ctx.stroke();ctx.fillStyle='#8296a4';ctx.fillText(String(value),area.left-6,py+3);}
 ctx.fillStyle='#718798';ctx.textAlign='center';for(const t of [0,2,4,6])ctx.fillText(t+'s',x(t),h-4);
 const drawLine=(frames,key,c,linewidth,dashed=false)=>{ctx.beginPath();ctx.strokeStyle=c;ctx.lineWidth=linewidth;ctx.setLineDash(dashed?[3,4]:[]);let started=false;for(const f of frames){let xx=x(f.t),yy=y(f[key]);if(!started){ctx.moveTo(xx,yy);started=true;}else ctx.lineTo(xx,yy);}ctx.stroke();ctx.setLineDash([]);};
 drawLine(state.factoryRun.frames,'target','#6fa8ff',1.6,true);
 if(state.compare){drawLine(state.factoryRun.frames,'q','#efb356',2.1);drawLine(state.tunedRun.frames,'q','#41d1b9',2.1);}
 else drawLine(activeRun().frames,'q','#41d1b9',2.2);
 ctx.beginPath();ctx.strokeStyle='#e8f2f5';ctx.globalAlpha=.8;ctx.lineWidth=1;ctx.moveTo(x(state.time),area.top);ctx.lineTo(x(state.time),area.bottom);ctx.stroke();ctx.globalAlpha=1;
 const v=frame(activeRun(),state.time);ctx.beginPath();ctx.arc(x(state.time),y(v.q),3.5,0,2*Math.PI);ctx.fillStyle='#53ddc1';ctx.fill();
 ctx.setTransform(1,0,0,1,0,0);
}
function refreshSummary(){const a=state.factoryRun.metrics,b=state.tunedRun.metrics;
 $('resultSummary').innerHTML=`<strong>Factory:</strong> ${fmt(a.mae_deg,2)}° mean tracking error <span class="sep">·</span> <strong>Modified:</strong> ${fmt(b.mae_deg,2)}° <span class="sep">·</span> Simulated fault: ${state.fault}`;
}
function callouts(q){if(!state.labels||state.compare){$('callouts').classList.remove('visible');return;}
 $('callouts').classList.add('visible'); const a=scene.projectPoint([0,.03,1.76]);const g=p.strutGeom(q),b=scene.projectPoint([(g.x-.48)/2,.64,(g.z+1.10)/2]);
 $('callHinge').style.transform=`translate(${a.x-12}px,${a.y-47}px)`;
 $('callStrut').style.transform=`translate(${b.x+8}px,${b.y-20}px)`;
}
function render(){if(!state.factoryRun||!state.tunedRun)return;
 const A=frame(state.factoryRun,state.time),B=frame(state.tunedRun,state.time),active=state.controller==='factory'?A:B;
 scene.draw(state.compare?A.q:active.q,B.q,state.compare);
 $('compareHalf').hidden=!state.compare;$('factoryAngle').textContent=fmt(A.q*180/Math.PI)+'°';$('tunedAngle').textContent=fmt(B.q*180/Math.PI)+'°';
 $('angleNow').innerHTML=`${fmt(active.q*180/Math.PI)}<span>deg</span>`;
 $('strokeNow').innerHTML=`${Math.round(active.stroke*1000)}<span>mm</span>`;
 $('currentNow').innerHTML=`${fmt(active.current)}<span>A</span>`;
 $('errorNow').innerHTML=`${fmt(Math.abs(active.error)*180/Math.PI)}<span>deg</span>`;
 $('timeNow').textContent=fmt(state.time,2);$('scrubber').value=fmt(state.time,2);callouts(active.q);chart();
}
function tick(now){if(state.playing){const dt=Math.min(.07,Math.max(0,(now-state.last)/1000));state.time=Math.min(p.RUNTIME,state.time+dt);if(state.time>=p.RUNTIME){state.playing=false;updatePlay();$('testState').textContent='COMPLETE';}render();}state.last=now;requestAnimationFrame(tick);}
function updatePlay(){const stop=state.playing;$('playLabel').textContent=stop?'PAUSE TEST':'RUN OPENING TEST';$('playSymbol').textContent=stop?'Ⅱ':'▶';$('overlayPlay').textContent=stop?'Ⅱ':'▶';$('testState').textContent=stop?'RUNNING':(state.time>=p.RUNTIME?'COMPLETE':state.time>0?'PAUSED':'READY');}
function play(){if(state.time>=p.RUNTIME)state.time=0;state.playing=!state.playing;state.last=performance.now();updatePlay();render();}
function reset(){state.playing=false;state.time=0;updatePlay();render();}
function selectController(which){state.controller=which;document.querySelectorAll('[data-controller]').forEach(x=>x.classList.toggle('active',x.dataset.controller===which));render();}
function setTuned(cal){state.cal={...cal};$('gainInput').value=cal.gain;$('frictionInput').value=cal.friction_ff;$('gravityInput').value=cal.gravity_ff;
 $('gainValue').textContent=fmt(cal.gain,2)+'×';$('frictionValue').textContent=fmt(cal.friction_ff,0)+' Nm';$('gravityValue').textContent=fmt(cal.gravity_ff,2)+'×';refresh();}
$('faultSelect').addEventListener('change',e=>{state.fault=e.target.value;$('faultInfo').textContent=names[state.fault];state.cal={...p.factory};setTuned(state.cal);reset();});
$('runBtn').addEventListener('click',play);$('resetBtn').addEventListener('click',reset);$('overlayPlay').addEventListener('click',play);
window.addEventListener('keydown',e=>{if(e.code==='Space'&&!['INPUT','SELECT','TEXTAREA','BUTTON'].includes(document.activeElement?.tagName)){e.preventDefault();play();}});
for(const btn of document.querySelectorAll('[data-controller]'))btn.addEventListener('click',()=>selectController(btn.dataset.controller));
for(const [field,key,dec,unit] of [['gainInput','gain',2,'×'],['frictionInput','friction_ff',0,' Nm'],['gravityInput','gravity_ff',2,'×']]){
 $(field).addEventListener('input',e=>{state.cal[key]=Number(e.target.value);$(key==='gain'?'gainValue':key==='friction_ff'?'frictionValue':'gravityValue').textContent=fmt(state.cal[key],dec)+unit;selectController('tuned');refresh();});
}
$('suggestBtn').addEventListener('click',()=>{setTuned(referencePresets[state.fault]);selectController('tuned');reset();$('resultSummary').innerHTML='<strong>Reference calibration applied.</strong> This preset was chosen using known simulator parameters, not by an agent. Run the test or enable comparison.';});
$('compareBtn').addEventListener('click',()=>{state.compare=!state.compare;$('compareBtn').classList.toggle('active',state.compare);$('compareBtn').innerHTML=state.compare?'<span class="square-icon"></span> Exit side-by-side comparison':'<span class="square-icon"></span> Compare factory / modified';$('baselineLegend').hidden=!state.compare;render();});
$('viewVehicle').addEventListener('click',()=>{scene.setFocus('vehicle');$('viewVehicle').classList.add('active');$('viewMech').classList.remove('active');render();});
$('viewMech').addEventListener('click',()=>{scene.setFocus('mechanism');$('viewMech').classList.add('active');$('viewVehicle').classList.remove('active');render();});
$('resetCamera').addEventListener('click',()=>{scene.yaw=.70;scene.elev=.36;scene.radius=scene.mechanics?3.25:4.75;render();});
$('fullscreenBtn').addEventListener('click',()=>{document.body.classList.toggle('immersive');$('fullscreenBtn').textContent=document.body.classList.contains('immersive')?'⤢':'⛶';requestAnimationFrame(()=>{scene.resize();render();});});
window.addEventListener('keydown',e=>{if(e.code==='Escape'&&document.body.classList.contains('immersive')){$('fullscreenBtn').click();}});
$('toggleLabels').addEventListener('click',()=>{state.labels=!state.labels;$('toggleLabels').classList.toggle('active',state.labels);render();});
$('scrubber').addEventListener('input',e=>{state.playing=false;state.time=Number(e.target.value);updatePlay();render();});
window.addEventListener('resize',()=>{scene.resize();render();});
setTuned(p.factory);$('faultInfo').textContent=names[state.fault];selectController('factory');updatePlay();tick(performance.now());
})();