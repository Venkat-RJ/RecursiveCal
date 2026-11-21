"""Adapt the existing offline WebGL/software 3D renderer to CAD-generated meshes."""
from pathlib import Path
src=Path('/mnt/data/RecursiveCal_PhysicalTwin/renderer3d.js').read_text()
src=src.replace('const P=global.TailgatePhysics;','const P=global.RecursivePhysics;const CAD=global.RecursiveCAD;')
src=src.replace('this.yaw=.70;this.elev=.36;this.radius=4.75;this.target=[-.53,0,1.10];','this.yaw=.73;this.elev=.34;this.radius=3.45;this.target=[-.12,0,1.27];')
src=src.replace('this.hatchTr=(q)=>M.mul(M.translate(0,0,1.76),M.ry(-q));','this.hatchTr=(q)=>M.mul(M.translate(0,0,CAD.hinge_z),M.ry(-q));')
src=src.replace("['body','window','cargo','wheel'].includes(part.group)","['body','window','hatch'].includes(part.group)")
src=src.replace("if(part.group==='wheel')continue;","if(part.group==='window')continue;")
src=src.replace("alpha=part.group==='body'?.07:.13;","alpha=part.group==='body'?.08:.16;")
src=src.replace("alpha=part.group==='body'?.065:.13;","alpha=part.group==='body'?.07:.16;")
src=src.replace("this.yaw=.70;this.elev=.36;this.radius=4.75;","this.yaw=.73;this.elev=.34;this.radius=3.45;")
src=src.replace("this.radius=3.45;this.yaw=.76;this.elev=.27;","this.radius=2.75;this.yaw=.78;this.elev=.25;")
src=src.replace("this.target=[-.53,0,1.1];this.radius=4.75;this.yaw=.70;this.elev=.36;","this.target=[-.12,0,1.27];this.radius=3.45;this.yaw=.73;this.elev=.34;")
start=src.index(' makeScene(b){')
end=src.index(' attachControls(){',start)
new=''' makeScene(b){
  // All vehicle/hatch triangle meshes are tessellated from the STEP CAD source.
  // Strut cylinders use the exact CAD outer diameters and CAD mount points with
  // length/orientation recomputed from the hinge angle for every simulation frame.
  this.box([-.15,0,.423],[3.1,3.1,.02],{c:'#1a2730',metal:.1},'floor');
  for(let i=-10;i<=10;i++){
   this.box([i*.15,0,.435],[.0015,2.75,.001],{c:'#415563',a:.22},'floorLine');
   this.box([-.15,i*.14,.435],[2.9,.0015,.001],{c:'#415563',a:.22},'floorLine');
  }
  for(const part of CAD.parts){
   const model=part.group==='hatch'?((q)=>M.mul(M.translate(0,0,CAD.hinge_z),M.ry(-q))):M.id();
   const material={c:part.c,metal:part.metal};
   if(part.c==='#29485a')material.a=.73;
   const group=part.group==='hatch'?'hatch':(part.name.includes('BODY')?'body':'mechanism');
   this.add(this.custom({positions:part.positions,normals:part.normals}),model,material,group,{name:part.name});
  }
  const len=(q)=>P.geometry(q).length_m;
  for(const sign of [-1,1]){
   const a=[CAD.body_anchor[0],sign*CAD.strut_y,CAD.body_anchor[1]];
   const b=(q)=>{const p=P.geometry(q);return[p.hatch_point_x_m,sign*CAD.strut_y,p.hatch_point_z_m]};
   const point=(q,at)=>{const B=b(q),d=V.norm(V.sub(B,a));return V.add(a,V.mul(d,at));};
   const cyl=(from,to,r,material)=>this.add('cylinder',(q)=>M.between(point(q,from),point(q,typeof to==='function'?to(len(q)):to),r),material,'mechanism');
   cyl(.035,.155,.038,{c:'#3c5260',metal:.63}); // motor
   cyl(.140,.402,.031,{c:'#3c5260',metal:.72}); // outer housing
   cyl(.391,.421,.035,{c:'#bdccd7',metal:.91}); // gland
   cyl(.412,L=>L-.018,.0125,{c:'#e3e9f0',metal:.99}); // telescopic steel rod
   cyl(.396,.401,.034,{c:'#151b25',metal:.08}); // seal
   cyl(.037,.063,.040,{c:'#263440',metal:.45}); // rear motor cap
   this.ball(a,.015,{c:'#c6ced8',metal:.95},'mechanism');
   this.add('sphere',(q)=>M.box(b(q),[.014,.014,.014]),{c:'#c6ced8',metal:.95},'mechanism');
  }
 }
'''
src=src[:start]+new+src[end:]
Path('/mnt/data/RecursiveCal_CAD_v1/viewer/cad_renderer.js').write_text(src)
print('CAD renderer:',len(src),'bytes; no original procedural SUV scene')
