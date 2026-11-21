/* RecursiveCal instrument workspace. One clock drives every replay surface. */
(() => {
  "use strict";
  const C = window.RecursiveWorkspace, $ = id => document.getElementById(id);
  const S = {view:"simulation", connected:false, busy:false, phase:"", run:null, study:null,
    runOrigin:"", studyOrigin:"", reference:null, diag:0, profile:0, component:"left",
    data:null, renderer:null, time:0, playing:false, frame:null, stream:null, abort:null, baseParameters:{}, plots:[]};
  const names = {simulation:"Simulation",investigate:"Investigation",calibrate:"Calibration",verify:"Verification"};
  const scenarios = {open:"Full opening",close:"Full closing",passive_hold:"Passive hold",power_loss:"Power loss"};
  const labels = {power_loss:"Power loss",speed_limit:"Speed limit",lower_stop:"Lower stop",upper_stop:"Upper stop",external_fixture:"External fixture"};
  const fmt = (v,n=2) => Number.isFinite(v) ? v.toFixed(n) : "n/a";
  const deg = v => v*180/Math.PI;
  const human = value => String(value || "").replaceAll("_"," ");
  const text = (id,value) => { const e=$(id); if(e)e.textContent=String(value); };
  function el(tag,value,cls) { const n=document.createElement(tag); if(value != null)n.textContent=value; if(cls)n.className=cls; return n; }
  function svg(tag,attributes={},value) { const n=document.createElementNS("http://www.w3.org/2000/svg",tag);
    for(const [key,v] of Object.entries(attributes))n.setAttribute(key,String(v));if(value!=null)n.textContent=value;return n; }
  function button(label,handler,cls="text-button") { const b=el("button",label,cls);b.type="button";b.addEventListener("click",handler);return b; }
  function notice(value,kind="info") { text("noticeText",value);$("notice").className="notice "+kind;$("notice").hidden=false; }
  function hideNotice() { $("notice").hidden=true; }
  function section(title,parent=$("inspector")) { const n=el("section",null,"inspector-section");n.append(el("h2",title));parent.append(n);return n; }
  function signals(parent,rows) {
    const dl=el("dl",null,"signal-list");
    for(const [label,value,unit,id,emphasis] of rows) {
      const row=el("div",null,emphasis?"signal-emphasis":""),dd=el("dd");
      if(id)dd.id=id;dd.append(document.createTextNode(String(value ?? "n/a")));if(unit)dd.append(el("small",unit));
      row.append(el("dt",label),dd);dl.append(row);
    }parent.append(dl);return dl;
  }
  function reading(id,value,unit="",places=2) {
    const n=$(id);if(!n)return;n.replaceChildren(document.createTextNode(typeof value==="number"?fmt(value,places):value==null?"n/a":String(value)));
    if(unit)n.append(el("small",unit));
  }
  function navItem(title,subtitle,icon,active,handler,result="") {
    const b=button("",handler,"nav-item"+(active?" active":""));b.setAttribute("aria-pressed",String(active));
    const glyph=el("span",icon,"nav-icon");glyph.setAttribute("aria-hidden","true");b.append(glyph);const label=el("span",null,"nav-label");
    label.append(el("strong",title));if(subtitle)label.append(el("small",subtitle));b.append(label);
    if(result)b.append(el("span",result,"nav-result"+(result==="Fail"?" bad":"")));
    return b;
  }
  function studyRecord() { return S.study?.agent_history[S.diag] || S.stream?.records[S.diag]; }
  function currentPredictions() {
    return S.study?.prediction_history?.find(x=>x.step===S.diag+1) ||
      S.stream?.predictions.find(x=>x.step===S.diag+1);
  }
  function predictionRows(candidate) {
    if(candidate.trace?.length)return candidate.trace.map(r=>C.normalized(r,"investigate"));
    return (candidate.observations||[]).map(r=>C.normalized({...r,time_s:r.sample_time_s},"investigate"));
  }
  function makeData() {
    if(S.view==="simulation") {
      if(!S.run)return null;
      const rows=S.run.trace.map(r=>C.normalized(r,"simulation",S.run.parameters));
      return {rows,before:[],predictions:[],events:S.run.events||[],samples:[],end:rows.at(-1).t,
        parameters:S.run.parameters,origin:S.runOrigin,model:S.run.model_id,kind:"simulation"};
    }
    if(S.view==="verify" && S.study) {
      const pair=S.study.verification.comparisons[S.profile];
      const rows=pair.after.trace.map(r=>C.normalized(r,"verify"));
      const before=pair.before.trace.map(r=>C.normalized(r,"verify"));
      return {rows,before,predictions:[],events:pair.after.events||[],samples:[],
        end:Math.max(rows.at(-1).t,before.at(-1).t),parameters:{},origin:S.studyOrigin,model:S.study.model_id,kind:"verify"};
    }
    const record=studyRecord();
    if(record) {
      const rows=S.study?C.diagnosticRows(S.study,S.diag):C.publicRows(record);
      return {rows,before:[],predictions:(currentPredictions()?.candidates||[]).map(predictionRows),
        events:record.events||[],samples:record.observations||[],end:Math.max(record.elapsed_s||0,rows.at(-1)?.t||0),
        parameters:{},origin:S.study?S.studyOrigin:"Computing locally",model:S.study?.model_id||"recursivecal.physical-rig/2",kind:"investigate"};
    }
    if(S.stream?.observation) {
      const row=C.normalized({...S.stream.observation.measurement,time_s:0},"investigate");
      const predictions=(currentPredictions()?.candidates||[]).map(predictionRows);
      const end=Math.max(0,...predictions.map(rows=>rows.at(-1)?.t||0));
      return {rows:[row],before:[],predictions,events:[],samples:[],end,parameters:{},
        origin:"Computing locally",model:"recursivecal.physical-rig/2",kind:"investigate"};
    }
    return null;
  }
  function stop() {
    S.playing=false;cancelAnimationFrame(S.frame);S.frame=null;
    text("playButton","▶");$("playButton").setAttribute("aria-label","Play recorded trace");
    document.body.dataset.playing="false";updateState();
  }
  function updateState() {
    let label=S.busy?S.phase:S.playing?"Replaying":S.data?"Paused":"Ready";
    if(!S.busy&&!S.playing&&S.view==="calibrate"&&S.study)label=S.study.commitment.disposition==="candidate"?"Sealed":"Abstained";
    if(!S.busy&&!S.playing&&S.view==="verify"&&S.study)
      label=C.accepted(S.study.verification.comparisons[S.profile].after)?"Passed":"Failed";
    text("runState",label);$("runState").className="run-state"+(S.busy?" busy":label==="Failed"?" bad":"");
  }
  function selectView(view,updateHash=true) {
    if(!names[view])view="simulation";if(S.busy)return;
    stop();S.view=view;document.body.dataset.view=view;
    if(updateHash && location.hash!=="#"+view)history.replaceState(null,"","#"+view);
    render(0);
  }
  function renderNav() {
    const nav=$("sideNav");nav.replaceChildren();$("sideDetails").replaceChildren();
    const details=$("sideDetails"),r=S.study;
    $("displayControls").hidden=S.view==="calibrate";
    if(S.view==="simulation") {
      text("navTitle","Assembly");text("navCount","01 rig");
      const components=[["hatch","Hatch & hinge","◇"],["left","Left actuator","↗"],["right","Right actuator","↗"],["gas","Gas assistance","⊙"],["sensor","Angle sensor","◉"]];
      for(const [key,label,icon] of components)nav.append(navItem(label,"",icon,S.component===key,()=>{
        S.component=key;if(S.renderer)S.renderer.selected=key;
        if(key==="left"||key==="right")$("showCutaway").checked=true;render(S.time);
      }));
      details.append(el("h2","Current run"));
      signals(details,[["Scenario",scenarios[S.run?.configuration?.scenario]||"No run"],["Engine",S.run?"Physics "+S.run.model_id.split("/").at(-1):"2"],
        ["Source","Synthetic"],["Hardware","None"]]);
      text("viewScope","Evaluator view");text("scopeDetail","One hinge. Two struts. Shared actuator dynamics.");
    } else if(S.view==="verify") {
      text("navTitle","Test profiles");text("navCount","04 tests");
      for(const [index,pair] of (r?.verification.comparisons||[]).entries()) {
        const pass=C.accepted(pair.after);
        nav.append(navItem(C.profiles[pair.name],C.profileConditions[pair.name],pass?"✓":"×",S.profile===index,()=>{
          stop();S.profile=index;render(0);
        },pass?"Pass":"Fail"));
      }
      details.append(el("h2","Evaluation"),el("p","Candidate frozen before testing. Fresh simulated state and paired sensor seeds for each profile."));
      text("viewScope","Verification view");text("scopeDetail","Development tests in the same simulator. Hardware evidence remains separate.");
    } else {
      const historyRows=r?.agent_history||S.stream?.records||[];
      text("navTitle",S.view==="calibrate"?"Supporting tests":"Experiment history");
      text("navCount",String(historyRows.length).padStart(2,"0")+" tests");
      for(const [index,record] of historyRows.entries())
        nav.append(navItem(C.actions[record.action]||record.action,human(record.termination),String(index+1).padStart(2,"0"),S.diag===index,()=>{
          stop();S.diag=index;render(0);
        }));
      if(S.busy&&S.stream?.selected && S.stream.selected.step>historyRows.length) {
        const selected=S.stream.selected;
        nav.append(navItem(C.actions[selected.action]||selected.action,"Executing",String(selected.step).padStart(2,"0"),true,()=>{}));
      }
      if(!historyRows.length&&!S.busy)nav.append(el("p",r?"No diagnostic tests were requested.":"Open an investigation or run a new one.","calibration-note"));
      const record=studyRecord(),cost=r?.cost??S.stream?.observation?.cost_used??0;
      details.append(el("h2",record?"Selected test":"Investigation"));
      if(record)signals(details,[["Duration",fmt(record.elapsed_s,2)+" s"],["Samples",record.observations.length],["Test cost",fmt(record.cost,1)]]);
      signals(details,[["Total cost",fmt(cost,1)],["Budget",fmt(r?.configuration.budget??Number($("budget").value),1)]]);
      details.append(el("p","Cost is in declared test-cost units. It includes setup and is not wall-clock time."));
      text("viewScope",S.view==="calibrate"?"Sealed estimates":"Instrument view");
      text("scopeDetail",S.view==="calibrate"?"The committed calibration stays fixed during verification.":"Synthetic sensor traces. The agent receives only the declared acquisition samples.");
    }
  }
  function renderHeading() {
    const r=S.study,record=studyRecord(),view=S.view;
    text("workspaceName",names[view]);
    for(const b of document.querySelectorAll(".workspace-tabs button")) {
      if(b.dataset.view===view)b.setAttribute("aria-current","page");else b.removeAttribute("aria-current");
      b.disabled=S.busy;
    }
    text("runButton",S.busy?"■ Cancel request":view==="simulation"?"▶ Run simulation":"▶ New investigation");
    $("runButton").disabled=!S.connected;
    for(const id of ["openSettings","importButton","loadExample"])$(id).disabled=S.busy;
    $("exportButton").disabled=S.busy||!(view==="simulation"?S.run:r);
    $("exportCsv").disabled=S.busy||!S.data?.rows.length;
    text("runOrigin",view==="simulation"?S.runOrigin:S.busy?"Computing locally":S.studyOrigin);
    text("runTitle",view==="simulation"?(scenarios[S.run?.configuration?.scenario]||"Liftgate rig"):
      r?"Investigation · seed "+r.configuration.seed:"Physical investigation");
    if(view==="simulation") {
      text("sectionEyebrow","SI liftgate · physics "+(S.run?.model_id.split("/").at(-1)||"2"));
      text("sectionTitle","Mechanism inspection");
      text("sectionDetail","One clock for the rig, actuator extension and recorded signals.");
    } else if(view==="investigate") {
      text("sectionEyebrow",S.busy?"Investigator · "+S.phase:record?"Experiment "+String(S.diag+1).padStart(2,"0")+" · recorded evidence":"Physical investigation");
      text("sectionTitle",S.busy&&S.stream?.selected?C.actions[S.stream.selected.action]||"Choosing a test":record?C.actions[record.action]:"Observe, experiment, infer");
      const decision=(r?.decisions||S.stream?.decisions||[]).find(d=>d.step===S.diag+1);
      text("sectionDetail",decision?.reason||"The investigator chooses a bounded test and compares the observations with its model bank.");
    } else if(view==="calibrate") {
      text("sectionEyebrow","Controller estimates · evidence retained");
      text("sectionTitle",r?.commitment.disposition==="abstain"?"Calibration withheld":"Committed calibration");
      text("sectionDetail","Compare the inferred estimates with the values actually sent to verification.");
    } else {
      text("sectionEyebrow","Frozen calibration · independent motion checks");
      text("sectionTitle",r?C.profiles[r.verification.comparisons[S.profile].name]:"Verification");
      text("sectionDetail",r?C.profileConditions[r.verification.comparisons[S.profile].name]+" · baseline and candidate":"A committed investigation is required.");
    }
    $("rigStage").hidden=view==="calibrate";
    $("calibrationPanel").hidden=view!=="calibrate";
    $("actuatorPane").hidden=!$("showCutaway").checked;
    $("showVectors").closest("label").hidden=view!=="simulation";
    $("comparisonLabels").hidden=view!=="verify"||!r;
    text("actuatorTitle",(S.component==="right"?"Right":"Left")+" actuator");
    text("poseSource",view==="simulation"?"Simulator state":view==="verify"?"Verifier state":"Pose derived from the angle sensor");
    text("sourceStatus",S.data?S.data.origin+" · "+S.data.model+" · synthetic":S.busy?"Computing a new investigation":"No run loaded");
    text("statusDetail",view==="investigate"&&S.busy?"Only observed evidence is shown":"No hardware connected");
    updateState();
  }
  function renderInspector() {
    const host=$("inspector");host.replaceChildren();
    const r=S.study,record=studyRecord();
    if(S.view==="simulation") {
      let p=section("At the current time");
      signals(p,[["Hatch angle","n/a","deg","readingAngle",true],["Target","n/a","deg","readingTarget"],
        ["Angular speed","n/a","rad/s","readingSpeed"],["Extension","n/a","mm","readingStroke"]]);
      p.append(el("p","Pose and extension come from the displayed trace. Playback interpolates between recorded samples.","meta-label"));
      const parameters=S.run?.parameters||{};
      if(S.component==="hatch") {
        p=section("Hatch & hinge");
        signals(p,[["Mass",fmt(parameters.mass_kg),"kg"],["Hinge inertia",fmt(parameters.inertia_kg_m2),"kg·m²"],
          ["Center of mass",fmt(parameters.com_radius_m,3),"m"],["Coulomb friction",fmt(parameters.friction_coulomb_Nm),"N·m"],
          ["Static friction",fmt(parameters.friction_static_Nm),"N·m"]]);
      } else if(S.component==="gas") {
        p=section("Gas assistance model");
        signals(p,[["At cursor","n/a","N / strut","readingGas"],["Force scale",fmt(parameters.gas_scale,3)],
          ["Compressed reference",fmt(parameters.gas_force_compressed_N_each,1),"N / strut"],
          ["Extended reference",fmt(parameters.gas_force_extended_N_each,1),"N / strut"],
          ["Temperature",fmt(parameters.temperature_C,1),"°C"]]);
      } else if(S.component==="sensor") {
        p=section("Angle sensor model");
        signals(p,[["Encoder bias",fmt(parameters.sensor_bias_rad,4),"rad"],["Logging noise σ",fmt(parameters.sensor_noise_std_rad,4),"rad"]]);
        p.append(el("p","The simulation pose shows model state. The investigator view uses the recorded sensor angle.","description"));
      } else {
        p=section(S.component==="right"?"Right actuator":"Left actuator");
        signals(p,[["Command","n/a","N / strut","readingCommand"],["Delivered force","n/a","N / strut","readingDrive"],
          ["Gas assistance","n/a","N / strut","readingGas"],["Command limit",fmt(parameters.motor_force_max_N_each,0),"N / strut"],
          ["Saturated","n/a","","readingSaturated"]]);
      }
      p=section("Model coverage");
      signals(p,[["Force response","Simulated"],["Motor current","Not modeled"],["Rotor speed","Not modeled"],["Motor heating","Not modeled"]]);
      p=section("Run events");appendEvents(p,S.data?.events||[]);
      if(S.run)p.append(el("p","Termination: "+human(S.run.metrics.termination)+".","meta-label"));
    } else if(S.view==="verify"&&r) {
      const pair=r.verification.comparisons[S.profile],passed=r.verification.comparisons.filter(x=>C.accepted(x.after)).length;
      let p=section("Motion acceptance");
      p.append(el("p",passed+" / 4 passed","result-text"+(passed===4?" good":" bad")));
      p.append(el("p","Every profile must meet every limit. Improvement alone does not pass verification.","description"));
      p=section("Selected profile limits");
      const table=el("table",null,"check-table"),head=el("tr");
      head.append(el("th","Check"),el("th","Candidate / limit"));const thead=el("thead");thead.append(head);table.append(thead);
      const body=el("tbody");
      for(const check of C.acceptance(pair.after)) {
        const tr=el("tr",null,check.pass?"pass":"fail"),value=typeof check.value==="number"?fmt(check.value,2)+(check.unit||""):check.value;
        const cell=el("td",value);cell.append(el("small",check.limit));tr.append(el("td",(check.pass?"✓ ":"× ")+check.label),cell);body.append(tr);
      }table.append(body);p.append(table);
      const failure=C.acceptance(pair.after).find(c=>!c.pass);if(failure)p.append(el("p",failure.label+" did not meet its acceptance limit.","failure-note"));
      p=section("At the cursor");
      signals(p,[["Baseline angle","n/a","deg","readingBefore"],["Candidate angle","n/a","deg","readingAngle"],["Candidate trace","n/a","","readingEnd"]]);
      p=section("Separate checks");
      const support=r.verification.passive_hold.static;
      signals(p,[["Passive support",support.can_hold_open_without_motor?"Modeled hold":"Insufficient"],
        ["Power loss",human(r.verification.power_loss.metrics.termination)],["Hardware evidence","Unavailable"]]);
      p.append(el("p","Additional modeled holding torque: "+fmt(support.additional_holding_torque_required_Nm,1)+" N·m.","description"));
      p.append(button("Export evidence",exportCurrent,"primary-button"),button("Create a new investigation",openSettings));
    } else if(S.view==="calibrate"&&r) {
      let p=section(r.commitment.disposition==="candidate"?"Sealed candidate":"Abstained");
      signals(p,[["Experiments",r.agent_history.length],["History",r.commitment.history_sha256.slice(0,12)],["State","Frozen"]]);
      p.append(el("p",r.commitment.reason,"description"));
      p=section("Model adequacy");
      p.append(el("p",r.final_belief.model_mismatch?"Mismatch detected":"Within the model bank","result-note"+(r.final_belief.model_mismatch?" bad":"")));
      p.append(el("p","Uncertainty is conditional on 72 declared hypotheses. A zero grid standard deviation is not zero physical uncertainty.","description"));
      p=section("Verification");
      const passed=r.verification.comparisons.filter(x=>C.accepted(x.after)).length;
      signals(p,[["Motion profiles",passed+" / 4 passed"],["Hardware evidence","Unavailable"]]);
      p.append(button("Open verification →",()=>selectView("verify"),"primary-button"));
      p.append(button("Export committed evidence",exportCurrent));
    } else {
      let p=section(S.busy?"Investigator status":"Why this test");
      const decision=(r?.decisions||S.stream?.decisions||[]).find(x=>x.step===S.diag+1);
      p.append(el("p",S.busy?S.phase:decision?.reason||"Select an experiment to inspect its observations and decision record.","description"));
      if(S.busy)p.append(el("p","Progress is reported by the Python engine at experiment and inference boundaries.","meta-label"));
      p=section("Before-test predictions");
      const candidates=currentPredictions()?.candidates||[];
      if(candidates.length) {
        candidates.forEach((candidate,i)=>{
          const row=el("div","Candidate "+(i+1),"hypothesis-row");
          row.append(el("span","w "+fmt(candidate.prior_weight,3)));p.append(row);
        });
        p.append(el("p","Three highest-weight models, recorded before this test. Weights are conditional on the model bank.","meta-label"));
      } else p.append(el("p","No prediction traces were recorded for this selection.","description"));
      p=section("Observed at cursor");
      signals(p,[["Hatch angle","n/a","deg","readingAngle",true],["Angular speed","n/a","rad/s","readingSpeed"],
        ["Total strut force","n/a","N / strut","readingForce"],["Acquired samples","n/a","","readingSamples"]]);
      if(record?.action==="reference")p.append(el("p","External fixture. Repositioning is outside the actuator model.","description"));
      p=section("Test events");appendEvents(p,S.data?.events||[],S.data?.samples||[]);
      if(!record&&!S.busy)p.append(el("p","Run a new investigation or open a recorded example.","description"));
      if(r) {
        p=section("Decision after investigation");
        p.append(el("p",r.commitment.disposition==="candidate"?"Calibration committed":"Calibration withheld","result-note"));
        p.append(button("Inspect calibration →",()=>selectView("calibrate")));
      }
    }
  }
  function appendEvents(parent,events,samples=[]) {
    const list=el("ol",null,"event-log");
    const items=[...events.map(e=>({t:e.time_s,label:labels[e.type]||human(e.type),incident:e.type!=="external_fixture"})),
      ...samples.map((s,i)=>({t:s.sample_time_s,label:"Sample "+(i+1),incident:false}))].sort((a,b)=>a.t-b.t);
    for(const item of items) {
      const li=el("li",null,item.incident?"incident":"");li.append(el("time",fmt(item.t)+" s"),button(item.label,()=>{stop();setTime(item.t);},""));
      list.append(li);
    }
    if(!items.length)list.append(el("li","No recorded limit events."));
    parent.append(list);
  }
  function renderCalibration() {
    const panel=$("calibrationPanel");panel.replaceChildren();if(S.view!=="calibrate")return;
    const r=S.study;
    if(!r) {
      const n=el("div",null,"calibration-empty");n.append(el("h2","No committed investigation"),el("p","Run an investigation or import a sealed report to compare the estimates and committed values."),button("Open investigation",()=>selectView("investigate"),"primary-button"));panel.append(n);return;
    }
    panel.append(el("h2","Parameter comparison"));
    const table=el("table",null,"parameter-table"),head=el("thead"),tr=el("tr");
    for(const label of ["Parameter","Nominal","Inferred","Committed","Unit"])tr.append(el("th",label));head.append(tr);table.append(head);
    const body=el("tbody");
    for(const [key,label,unit,places] of C.parameters) {
      const row=el("tr"),estimate=r.final_belief.posterior_mean[key],committed=r.commitment.estimates[key];
      row.append(el("td",label),el("td",fmt(C.defaults[key],places)));
      const inferred=el("td",fmt(estimate,places));inferred.append(el("small","σ "+fmt(r.final_belief.posterior_std[key],places)));
      row.append(inferred,el("td",fmt(committed,places),Math.abs(committed-C.defaults[key])>1e-8?"changed":""),el("td",unit));body.append(row);
    }table.append(body);panel.append(table);
    panel.append(el("p",r.commitment.disposition==="candidate"?
      "The investigator committed these estimates before verification. Source observations and the history digest are retained with the candidate.":
      "The investigator abstained. Inferred values are shown for inspection; the nominal calibration was retained for verification.","calibration-note"));
    panel.append(el("h2","Fixed & derived"));
    const fixed=el("div",null,"fixed-table");
    for(const [name,status] of [["Hinge geometry","Fixed"],["Hinge inertia","Derived from mass"],["Static friction","Coulomb + 2 N·m"],["Feedback gains","Fixed"],["Electrical motor","Not modeled"],["Left / right drives","Shared model"]]) {
      const row=el("div",name);row.append(el("span",status));fixed.append(row);
    }panel.append(fixed);
    panel.append(el("p","The plots below show the selected recorded experiment. They are not an independently fitted calibration-response curve.","calibration-note"));
  }
  function buildPlot(id,series,unit) {
    const root=$(id);root.replaceChildren();const end=Math.max(S.data?.end||0,.01);
    const width=600,left=43,right=584,top=14,bottom=142;
    let min=0,max=1;
    for(const line of series)for(const row of line.rows)if(Number.isFinite(row[line.key])){
      const value=row[line.key]*(line.scale||1);min=Math.min(min,value);max=Math.max(max,value);
    }
    if(unit==="deg"){min=Math.min(0,min);max=Math.max(80,max);}
    const span=Math.max(1e-6,max-min);min-=span*.04;max+=span*.08;
    const X=t=>left+t/end*(right-left),Y=v=>bottom-(v-min)/(max-min)*(bottom-top);
    root.setAttribute("viewBox","0 0 "+width+" 175");root.dataset.duration=String(end);
    for(let i=0;i<=4;i++) {
      const y=top+i/4*(bottom-top),v=max-i/4*(max-min);
      root.append(svg("line",{x1:left,x2:right,y1:y,y2:y,stroke:"#dde0d6","stroke-width":.7}));
      root.append(svg("text",{x:left-9,y:y+3,"text-anchor":"end",fill:"#939c88","font-size":9,"font-family":"monospace"},Math.abs(v)>10?fmt(v,0):fmt(v,1)));
    }
    for(let i=0;i<=4;i++) {
      const t=end*i/4;root.append(svg("line",{x1:X(t),x2:X(t),y1:top,y2:bottom,stroke:"#e3e5dc","stroke-width":.6}),
        svg("text",{x:X(t),y:bottom+19,"text-anchor":"middle",fill:"#939c88","font-size":9,"font-family":"monospace"},fmt(t,1)));
    }
    const defs=svg("defs"),clip=svg("clipPath",{id:id+"Clip"}),clipRect=svg("rect",{x:left,y:top-3,width:0,height:bottom-top+6});
    clip.append(clipRect);defs.append(clip);root.append(defs);
    const future=svg("rect",{x:left,y:top,width:0,height:bottom-top,fill:"#efede5",opacity:.6});root.append(future);
    const group=svg("g");
    for(const seriesItem of series) {
      const points=seriesItem.rows.filter(r=>Number.isFinite(r[seriesItem.key]));
      if(!points.length)continue;
      const d=points.map((r,i)=>(i?"L":"M")+fmt(X(r.t),2)+","+fmt(Y(r[seriesItem.key]*(seriesItem.scale||1)),2)).join(" ");
      const path=svg("path",{d,fill:"none",stroke:seriesItem.color||"#d96b28","stroke-width":seriesItem.width||1.9,"stroke-linejoin":"round"});
      if(seriesItem.dash)path.setAttribute("stroke-dasharray",seriesItem.dash);
      if(!seriesItem.future)path.setAttribute("clip-path","url(#"+id+"Clip)");
      group.append(path);
    }
    root.append(group);
    const markers=[];
    if(S.data?.kind==="investigate")for(const sample of S.data.samples) {
      const sampleTime=sample.sample_time_s,field=unit==="deg"?"angle_rad":"strut_force_N_each";
      if(!Number.isFinite(sample[field]))continue;
      const mark=svg("circle",{cx:X(sampleTime),cy:Y(sample[field]*(unit==="deg"?180/Math.PI:1)),r:3.1,fill:"#d96b28",stroke:"#faf9f5","stroke-width":1.3});
      mark.dataset.time=String(sampleTime);root.append(mark);markers.push(mark);
    }
    const cursor=svg("line",{x1:left,x2:left,y1:top,y2:bottom,stroke:"#d96b28","stroke-width":1});
    const dot=svg("circle",{cx:left,cy:bottom,r:3.3,fill:"#d96b28",stroke:"#faf9f5","stroke-width":1.4});
    root.append(cursor,dot);
    root.append(svg("text",{x:(left+right)/2,y:173,"text-anchor":"middle",fill:"#9ba28f","font-size":8},"Simulation time (s)"));
    S.plots.push({id,X,Y,left,right,top,bottom,clipRect,future,cursor,dot,series,markers,end});
  }
  function renderPlots() {
    S.plots=[];const d=S.data,has=Boolean(d?.rows.length);
    $("plotGrid").hidden=!has;$("plotEmpty").hidden=has;$("forcePlot").closest("figure").hidden=S.view==="verify";
    const legend=$("plotLegend");legend.replaceChildren();
    function key(label,cls){const n=el("span");n.append(el("i",null,cls),document.createTextNode(label));legend.append(n);}
    if(!has){$("anglePlot").replaceChildren();$("forcePlot").replaceChildren();return;}
    let angle=[],force=[];
    if(d.kind==="simulation") {
      text("plotsHeading","Signals");text("anglePlotTitle","Hatch angle · deg");text("forcePlotTitle","Actuator force · N / strut");
      key("Target / command","target");key("Recorded","");
      angle=[{rows:d.rows,key:"target",scale:180/Math.PI,color:"#929b8c",dash:"5 4",future:true},{rows:d.rows,key:"q",scale:180/Math.PI}];
      force=[{rows:d.rows,key:"command",color:"#929b8c",dash:"5 4",future:false},{rows:d.rows,key:"drive"}];
    } else if(d.kind==="verify") {
      text("plotsHeading","Position response");text("anglePlotTitle","Hatch angle · deg");key("Target","target");key("Baseline","baseline");key("Candidate","");
      angle=[{rows:d.rows,key:"target",scale:180/Math.PI,color:"#929b8c",dash:"5 4",future:true},
        {rows:d.before,key:"q",scale:180/Math.PI,color:"#a7ada0"},{rows:d.rows,key:"q",scale:180/Math.PI}];
    } else {
      text("plotsHeading",d.predictions.length?"Predictions & observations":"Recorded observations");
      text("anglePlotTitle","Measured angle · deg");text("forcePlotTitle","Measured strut force · N / strut");
      if(d.predictions.length)key("Prior predictions","target");key("Observed","");
      angle=d.predictions.map(rows=>({rows,key:"q",scale:180/Math.PI,color:"#adb3a4",dash:"4 4",width:1.3,future:true}));
      force=d.predictions.map(rows=>({rows,key:"force",color:"#adb3a4",dash:"4 4",width:1.3,future:true}));
      angle.push({rows:d.rows,key:"q",scale:180/Math.PI});force.push({rows:d.rows,key:"force"});
    }
    buildPlot("anglePlot",angle,"deg");if(d.kind!=="verify")buildPlot("forcePlot",force,"N");
  }
  function renderTimeline() {
    const d=S.data,end=d?.end||0,disabled=!d?.rows.length||S.busy;
    for(const id of ["timeline","playButton","stepBack","stepForward"])$(id).disabled=disabled||end===0;
    $("eventMarkers").replaceChildren();if(!d||end<=0)return;
    const markers=[...d.samples.map((s,i)=>({t:s.sample_time_s,label:"S"+(i+1),incident:false})),
      ...d.events.map(e=>({t:e.time_s,label:labels[e.type]||human(e.type),incident:e.type!=="external_fixture"}))];
    for(const m of markers) {
      const b=button(m.label,()=>{stop();setTime(m.t);},m.incident?"incident":"");
      b.title=m.label+" at "+fmt(m.t,3)+" s";b.style.left=(C.clamp(m.t/end,0,1)*100)+"%";$("eventMarkers").append(b);
    }
  }
  function setTime(value) {
    const d=S.data,start=d?.rows[0]?.t||0;S.time=C.clamp(value,start,Math.max(start,d?.end||0));
    const current=C.sample(d?.rows,S.time),before=C.sample(d?.before,S.time);
    $("workspace").dataset.time=String(S.time);
    text("timeReadout",fmt(S.time)+" s");text("endReadout",fmt(d?.end||0)+" s");
    $("timeline").value=d?.end?Math.round(S.time/d.end*10000):0;
    $("timeline").style.setProperty("--progress",(d?.end?S.time/d.end*100:0)+"%");
    if(!current){S.renderer?.draw(0);return;}
    const geometryKeys={hinge_height_m:1.76,body_anchor_x_m:-.47,body_anchor_z_m:1.17,hatch_anchor_x_m:.018,hatch_anchor_down_m:.3};
    const standard=Object.entries(geometryKeys).every(([k,v])=>d.parameters[k]===undefined||Math.abs(d.parameters[k]-v)<1e-9);
    $("cadUnavailable").hidden=Boolean(S.renderer)&&standard;
    if(!standard)$("cadUnavailable").lastElementChild.textContent="This imported run uses different mounting geometry. The standard CAD mesh is hidden; its recorded signals remain available.";
    $("rigCanvas").style.visibility=standard?"visible":"hidden";
    if(S.renderer&&S.view!=="calibrate"&&standard) {
      S.renderer.trailAngle=$("showTrail").checked?C.sample(d.rows,Math.max(0,S.time-.25))?.q:null;
      if(d.kind==="verify")S.renderer.draw(before?.q??current.q,current.q,true);
      else S.renderer.draw(current.q,current.q,false);
    }
    const maxStroke=C.stroke(d.parameters.max_angle_rad??78*Math.PI/180,d.parameters);
    const extension=Number.isFinite(current.stroke)?current.stroke:C.stroke(current.q,d.parameters);
    $("movingActuator").setAttribute("transform","translate("+fmt(C.clamp(extension/Math.max(maxStroke,.001),0,1)*164,3)+" 0)");
    $("actuatorSvg").dataset.strokeM=String(extension);$("rigCanvas").dataset.angleRad=String(current.q);
    text("extensionLabel",fmt(extension*1000,1)+" mm extension");
    reading("readingAngle",deg(current.q),"deg",2);reading("readingTarget",deg(current.target),"deg",2);
    reading("readingSpeed",current.velocity,"rad/s",3);reading("readingStroke",extension*1000,"mm",1);
    reading("readingCommand",current.command,"N / strut",1);reading("readingDrive",current.drive,"N / strut",1);
    reading("readingGas",current.gas,"N / strut",1);reading("readingForce",current.force,"N / strut",1);
    reading("readingSaturated",current.saturated===undefined?"n/a":current.saturated?"Yes":"No");
    reading("readingBefore",deg(before?.q),"deg",2);
    reading("readingEnd",current.ended?"Ended at "+fmt(current.sampledAt)+" s":"At cursor");
    reading("readingSamples",d.samples.filter(s=>s.sample_time_s<=S.time+1e-9).length+" / "+d.samples.length);
    text("beforePose",fmt(deg(before?.q),1)+"°");text("afterPose",fmt(deg(current.q),1)+"°");
    for(const plot of S.plots) {
      const x=plot.X(S.time),full=$("showFullTrace").checked;
      plot.clipRect.setAttribute("width",full?plot.right-plot.left:Math.max(0,x-plot.left));
      plot.future.setAttribute("x",x);plot.future.setAttribute("width",full?0:Math.max(0,plot.right-x));
      plot.cursor.setAttribute("x1",x);plot.cursor.setAttribute("x2",x);
      const line=plot.series.at(-1),point=C.sample(line.rows,S.time),v=point?.[line.key];
      const visible=Number.isFinite(v)&&!point.ended;
      plot.dot.style.display=visible?"":"none";
      if(visible){plot.dot.setAttribute("cx",plot.X(point.t));plot.dot.setAttribute("cy",plot.Y(v*(line.scale||1)));}
      for(const marker of plot.markers)marker.style.visibility=full||Number(marker.dataset.time)<=S.time+1e-9?"visible":"hidden";
    }
    drawVectors(current);
  }
  function drawVectors(current) {
    const overlay=$("rigOverlay");overlay.replaceChildren();
    if(!$("showVectors").checked||S.data?.kind!=="simulation"||!S.renderer||!Number.isFinite(current.drive)||$("rigCanvas").style.visibility==="hidden")return;
    const canvas=$("rigCanvas"),w=canvas.clientWidth,h=canvas.clientHeight;
    overlay.setAttribute("viewBox","0 0 "+w+" "+h);
    const defs=svg("defs"),marker=svg("marker",{id:"forceArrow",markerWidth:6,markerHeight:6,refX:5,refY:3,orient:"auto"});
    marker.append(svg("path",{d:"M0 0L6 3L0 6",fill:"#d96b28"}));defs.append(marker);overlay.append(defs);
    const p=S.data.parameters,g=C.geometry(current.q,p),sign=Math.sign(current.drive);
    if(!sign)return;
    for(const side of [-1,1]) {
      const a=S.renderer.projectPoint([p.body_anchor_x_m??-.47,side*window.RecursiveCAD.strut_y,p.body_anchor_z_m??1.17]);
      const b=S.renderer.projectPoint([g.x,side*window.RecursiveCAD.strut_y,g.z]);
      if(!a.visible||!b.visible)continue;
      const dx=b.x-a.x,dy=b.y-a.y,length=Math.hypot(dx,dy)||1,scale=C.clamp(Math.abs(current.drive)/330,.12,.8);
      const x=(a.x+b.x)/2+12,y=(a.y+b.y)/2;
      overlay.append(svg("line",{x1:x-dx/length*18*sign,y1:y-dy/length*18*sign,x2:x+dx/length*55*scale*sign,y2:y+dy/length*55*scale*sign,
        stroke:"#d96b28","stroke-width":2,"marker-end":"url(#forceArrow)"}));
    }
  }
  function render(time=0) {
    S.data=makeData();renderNav();renderHeading();renderCalibration();renderInspector();renderPlots();renderTimeline();
    S.renderer?.resize();setTime(time);document.body.dataset.loaded=String(Boolean(S.run||S.study));
    document.body.dataset.study=S.study?"loaded":"empty";
  }
  function play() {
    if(S.busy||!S.data?.end)return;
    if(S.playing){stop();return;}
    if(S.time>=S.data.end-1e-9)setTime(0);
    S.playing=true;text("playButton","Ⅱ");$("playButton").setAttribute("aria-label","Pause recorded trace");
    document.body.dataset.playing="true";updateState();let previous=performance.now();
    const tick=now=>{
      if(!S.playing)return;
      const delta=Math.min(.15,(now-previous)/1000)*Number($("playbackSpeed").value);previous=now;
      setTime(S.time+delta);
      if(S.time>=S.data.end){stop();return;}
      S.frame=requestAnimationFrame(tick);
    };S.frame=requestAnimationFrame(tick);
  }
  function openSettings() {
    const simulation=S.view==="simulation";
    $("simulationForm").hidden=!simulation;$("investigationForm").hidden=simulation;
    text("settingsTitle",simulation?"Simulation configuration":"Investigation configuration");
    $("offlineHint").hidden=S.connected;
    for(const b of document.querySelectorAll(".dialog-run"))b.disabled=!S.connected;
    $("settingsDialog").showModal();
  }
  function syncSimulationForm(run) {
    S.baseParameters={...run.parameters};
    for(const input of document.querySelectorAll("[data-param]"))if(Number.isFinite(run.parameters[input.dataset.param]))input.value=run.parameters[input.dataset.param];
    const cfg=run.configuration;
    for(const [key,id] of [["scenario","scenario"],["controller","controller"],["duration_s","duration"],["dt_s","dt"],["seed","simulationSeed"]])
      if(cfg?.[key]!==undefined)$(id).value=cfg[key];
    $("abortOnLimit").checked=cfg?.abort_on_limit!==false;
  }
  function syncStudyForm(report) {
    for(const [key,id] of [["case","condition"],["policy","policy"],["seed","studySeed"],["budget","budget"],["max_tests","maxTests"]])
      if(report.configuration[key]!==undefined)$(id).value=report.configuration[key];
  }
  async function loadRun(run,origin,autoplay=false) {
    C.validateRun(run);stop();S.run=run;S.runOrigin=origin;syncSimulationForm(run);
    S.view="simulation";document.body.dataset.view=S.view;history.replaceState(null,"","#simulation");
    render(autoplay?0:(run.trace.at(-1).time_s*.42));if(autoplay&&!matchMedia("(prefers-reduced-motion: reduce)").matches)play();
  }
  async function loadStudy(report,origin,view="investigate") {
    await C.validateReport(report);stop();S.study=report;S.studyOrigin=origin;S.stream=null;S.diag=0;
    S.profile=Math.max(0,report.verification.comparisons.findIndex(pair=>!C.accepted(pair.after)));
    syncStudyForm(report);S.view=view;document.body.dataset.view=view;history.replaceState(null,"","#"+view);render(0);
  }
  async function decodeReference() {
    if(S.reference)return S.reference;
    if(!window.RecursiveWorkspaceReference)throw new Error("The recorded workspace example is unavailable.");
    if(typeof DecompressionStream!=="function")throw new Error("This browser cannot decompress the recorded example. Import a JSON report instead.");
    const bytes=Uint8Array.from(atob(window.RecursiveWorkspaceReference),x=>x.charCodeAt(0));
    const stream=new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
    const ref=JSON.parse(await new Response(stream).text());
    C.validateRun(ref.simulation);await C.validateReport(ref.investigation);S.reference=ref;return ref;
  }
  async function loadExample() {
    if(S.busy)return;hideNotice();
    try {
      const ref=await decodeReference();
      if(S.view==="simulation")await loadRun(ref.simulation,"Recorded example · physics 2");
      else await loadStudy(ref.investigation,"Recorded example · physics 2",S.view);
      notice("Recorded synthetic evidence. Run the local engine to compute a new result.");
    }catch(error){notice(error.message,"error");}
  }
  function setBusy(value,phase="") {
    S.busy=value;S.phase=phase;document.body.dataset.busy=String(value);
    document.body.classList.toggle("busy-workspace",value);renderHeading();renderTimeline();
  }
  async function runSimulation(event) {
    event?.preventDefault();if(S.busy||!S.connected||!$("simulationForm").reportValidity())return;
    const parameters={...S.baseParameters};
    for(const input of document.querySelectorAll("[data-param]"))parameters[input.dataset.param]=Number(input.value);
    const payload={parameters,scenario:$("scenario").value,controller:$("controller").value,
      duration_s:Number($("duration").value),dt_s:Number($("dt").value),seed:Number($("simulationSeed").value),abort_on_limit:$("abortOnLimit").checked};
    stop();hideNotice();$("settingsDialog").close();S.abort=new AbortController();setBusy(true,"Computing");
    try {
      const response=await fetch("api/simulate",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload),signal:S.abort.signal});
      const run=await response.json();if(!response.ok)throw new Error(run.error||"Simulation failed.");
      C.validateRun(run);setBusy(false);await loadRun(run,"Computed locally",true);
    }catch(error){notice(error.name==="AbortError"?"Request cancelled. The previous run remains available.":error.message,"error");}
    finally{S.abort=null;setBusy(false);}
  }
  function streamEvent(event) {
    if(event.type==="started") {
      S.study=null;S.stream={records:[],decisions:[],predictions:[],observation:event.observation,selected:null};
      S.diag=0;S.phase="Choosing a test";render(0);
    } else if(event.type==="experiment_selected") {
      S.stream.selected=event.decision;S.stream.decisions.push(event.decision);S.stream.predictions.push(event.prediction);
      S.stream.observation=event.observation;S.diag=event.decision.step-1;S.phase="Running test";render(0);
    } else if(event.type==="experiment_completed") {
      S.stream.records.push(event.record);S.stream.observation=event.observation;S.phase="Updating estimates";
      render(event.record.elapsed_s);
    } else if(event.type==="belief_updated") {
      S.stream.belief=event.summary;S.phase="Choosing a test";render(S.time);
    } else if(event.type==="committed") {
      S.stream.commitment=event.commitment;S.phase="Verifying";render(S.time);
    } else if(event.type==="error")throw new Error(event.error||"Investigation failed.");
  }
  async function runInvestigation(event) {
    event?.preventDefault();if(S.busy||!S.connected||!$("investigationForm").reportValidity())return;
    const previous={study:S.study,origin:S.studyOrigin,diag:S.diag,profile:S.profile};
    const payload={case:$("condition").value,policy:$("policy").value,seed:Number($("studySeed").value),
      budget:Number($("budget").value),max_tests:Number($("maxTests").value)};
    stop();hideNotice();$("settingsDialog").close();S.view="investigate";document.body.dataset.view="investigate";
    history.replaceState(null,"","#investigate");S.abort=new AbortController();setBusy(true,"Starting");
    let complete=null,reader;
    try {
      const response=await fetch("api/inquiry/stream",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload),signal:S.abort.signal});
      if(!response.ok){const error=await response.json();throw new Error(error.error||"Investigation failed.");}
      if(!response.body)throw new Error("The browser did not provide a progress stream.");
      reader=response.body.getReader();const decoder=new TextDecoder();let buffer="";
      const process=line=>{if(!line.trim())return;const message=JSON.parse(line);if(message.type==="complete")complete=message.report;else streamEvent(message);};
      while(true) {
        const {value,done}=await reader.read();if(done)break;
        buffer+=decoder.decode(value,{stream:true});
        let newline;while((newline=buffer.indexOf("\n"))>=0){process(buffer.slice(0,newline));buffer=buffer.slice(newline+1);}
        if(buffer.length>32*1024*1024)throw new Error("Investigation exceeded the report size limit.");
      }
      buffer+=decoder.decode();if(buffer.trim())process(buffer);
      if(!complete)throw new Error("The investigation ended without a sealed report.");
      await C.validateReport(complete);setBusy(false);await loadStudy(complete,"Computed locally");
      notice(complete.outcome==="verified_in_simulation"?"The committed calibration passed all four motion profiles. Passive support and hardware evidence are shown separately.":
        complete.outcome==="verification_failed"?"The calibration was committed, then rejected by motion verification. Open Verify to inspect the failed profile.":
        "The investigator withheld a new calibration: "+complete.commitment.reason+".",
        complete.outcome==="verified_in_simulation"?"info":"warning");
      if(S.data?.end&&!matchMedia("(prefers-reduced-motion: reduce)").matches)play();
    }catch(error) {
      S.study=previous.study;S.studyOrigin=previous.origin;S.diag=previous.diag;S.profile=previous.profile;S.stream=null;
      notice((error.name==="AbortError"?"Request cancelled. The calculation stops at the next reporting boundary.":error.message)+
        (previous.study?" The previous complete investigation remains available.":""),"error");
    }finally{if(reader)reader.releaseLock();S.abort=null;setBusy(false);render(S.time);}
  }
  function download(name,content,type) {
    const url=URL.createObjectURL(new Blob([content],{type})),link=el("a");link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  function exportCurrent() {
    const value=S.view==="simulation"?S.run:S.study;if(!value)return;
    download(S.view==="simulation"?"recursivecal-simulation.json":"recursivecal-investigation.json",JSON.stringify(value,null,2)+"\n","application/json");
  }
  function showProvenance() {
    const value=S.view==="simulation"?S.run:S.study,summary=$("provenanceSummary");summary.replaceChildren();
    if(!value){summary.append(el("p","No complete run loaded."));text("provenanceJson","");}
    else {
      summary.append(el("p",(S.view==="simulation"?S.runOrigin:S.studyOrigin)+". "+value.model_id+". All displayed model outputs are synthetic."));
      const list=el("ul");
      for(const note of value.limitations||["One rigid hinge with two identical struts.","The actuator cutaway illustrates the assembly; it is not manufacturing CAD.","No motor electrical model, independent left/right dynamics or hardware validation."])list.append(el("li",note));
      summary.append(list);
      text("provenanceJson",JSON.stringify({model_id:value.model_id,configuration:value.configuration,
        parameters:S.view==="simulation"?value.parameters:undefined,commitment:value.commitment,provenance:value.provenance,
        report_sha256:value.report_sha256},null,2));
    }$("provenanceDialog").showModal();
  }
  for(const b of document.querySelectorAll(".workspace-tabs button"))b.addEventListener("click",()=>selectView(b.dataset.view));
  for(const b of document.querySelectorAll("[data-close]"))b.addEventListener("click",()=>$(b.dataset.close).close());
  $("openSettings").addEventListener("click",openSettings);$("dismissNotice").addEventListener("click",hideNotice);
  $("simulationForm").addEventListener("submit",runSimulation);$("investigationForm").addEventListener("submit",runInvestigation);
  $("runButton").addEventListener("click",()=>{if(S.busy){S.abort?.abort();return;}if(S.view==="simulation")$("simulationForm").requestSubmit();else $("investigationForm").requestSubmit();});
  $("loadExample").addEventListener("click",loadExample);$("exportButton").addEventListener("click",exportCurrent);
  $("exportCsv").addEventListener("click",()=>{if(S.data?.rows.length)download("recursivecal-"+S.data.kind+"-trace.csv",C.traceCsv(S.data.rows),"text/csv");});
  $("openProvenance").addEventListener("click",showProvenance);
  $("importButton").addEventListener("click",()=>$("importFile").click());
  $("importFile").addEventListener("change",async event=>{
    const file=event.target.files[0];if(!file)return;hideNotice();
    try {
      if(file.size>32*1024*1024)throw new Error("The report exceeds the 32 MiB limit.");
      const data=JSON.parse(await file.text());
      if(data.schema_version==="recursivecal.run/1")await loadRun(data,"Imported simulation");
      else await loadStudy(data,"Imported investigation");
      notice("Imported evidence. The original report is preserved for export.");
    }catch(error){notice("Import rejected. "+error.message+" The previous run remains displayed.","error");}
    finally{event.target.value="";}
  });
  $("playButton").addEventListener("click",play);
  $("stepBack").addEventListener("click",()=>{stop();setTime(C.stepTime(S.data?.rows,S.time,-1));});
  $("stepForward").addEventListener("click",()=>{stop();setTime(C.stepTime(S.data?.rows,S.time,1));});
  $("timeline").addEventListener("input",()=>{stop();setTime(Number($("timeline").value)/10000*(S.data?.end||0));});
  for(const id of ["showCutaway","showTrail","showVectors","showFullTrace"])$(id).addEventListener("change",()=>render(S.time));
  for(const id of ["anglePlot","forcePlot"]) {
    $(id).addEventListener("click",event=>{
      if(S.busy)return;const plot=S.plots.find(p=>p.id===id);if(!plot)return;
      const point=$(id).createSVGPoint();point.x=event.clientX;point.y=event.clientY;
      const matrix=$(id).getScreenCTM();if(!matrix)return;
      const x=point.matrixTransform(matrix.inverse()).x;
      stop();setTime(C.clamp((x-plot.left)/(plot.right-plot.left),0,1)*plot.end);
    });
    $(id).addEventListener("keydown",event=>{if(event.key==="ArrowRight"||event.key==="ArrowLeft"){event.preventDefault();stop();setTime(C.stepTime(S.data?.rows,S.time,event.key==="ArrowRight"?1:-1));}});
  }
  $("resetCamera").addEventListener("click",()=>{S.renderer?.setFocus("assembly");$("focusMechanism").setAttribute("aria-pressed","false");setTime(S.time);});
  $("focusMechanism").addEventListener("click",()=>{const active=$("focusMechanism").getAttribute("aria-pressed")!=="true";
    $("focusMechanism").setAttribute("aria-pressed",String(active));S.renderer?.setFocus(active?"mechanism":"assembly");setTime(S.time);});
  $("rigCanvas").addEventListener("pointermove",()=>{if(S.data)drawVectors(C.sample(S.data.rows,S.time));});
  $("rigCanvas").addEventListener("wheel",()=>{if(S.data)drawVectors(C.sample(S.data.rows,S.time));});
  window.addEventListener("hashchange",()=>selectView(location.hash.slice(1),false));
  document.addEventListener("visibilitychange",()=>{if(document.hidden)stop();});
  window.addEventListener("pagehide",()=>{stop();S.abort?.abort();});
  let resizeFrame;window.addEventListener("resize",()=>{cancelAnimationFrame(resizeFrame);resizeFrame=requestAnimationFrame(()=>{renderPlots();S.renderer?.resize();setTime(S.time);});});
  async function init() {
    S.view=names[location.hash.slice(1)]?location.hash.slice(1):"simulation";document.body.dataset.view=S.view;
    try{S.renderer=new window.PhysicalRenderer($("rigCanvas"),{theme:"light"});}catch(error){$("cadUnavailable").hidden=false;}
    if(["localhost","127.0.0.1"].includes(location.hostname)) {
      try {
        const response=await fetch("api/capabilities");const capabilities=await response.json();
        S.connected=response.ok&&capabilities.schema_version==="recursivecal.capabilities.v1";
        if(S.connected)S.baseParameters={...capabilities.default_parameters};
      }catch(error){S.connected=false;}
    }
    $("engineStatus").replaceChildren(el("i"),document.createTextNode(S.connected?"Local engine":"Recorded view"));
    $("engineStatus").className="engine-status"+(S.connected?" connected":"");document.body.dataset.ready=S.connected?"connected":"offline";
    try {
      const ref=await decodeReference();S.run=ref.simulation;S.study=ref.investigation;
      S.runOrigin=S.studyOrigin="Recorded example · physics 2";syncSimulationForm(S.run);syncStudyForm(S.study);
      S.profile=Math.max(0,S.study.verification.comparisons.findIndex(pair=>!C.accepted(pair.after)));
    }catch(error){notice(error.message,"error");}
    render(S.view==="simulation"?(S.run?.trace.at(-1).time_s||0)*.42:0);
  }
  init().catch(error=>notice("Workspace could not initialize: "+error.message,"error"));
})();
