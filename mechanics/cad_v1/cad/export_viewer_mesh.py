"""Export compact CAD-derived browser meshes without any downloaded 3D assets.

Vertex coordinates are quantized to 0.1 mm and normals to signed 8-bit.
This mesh is for display; full-precision STEP/GLB remains authoritative.
"""
import base64,json
import numpy as np
from build_assembly import ROOT,make_parts,COLORS,HINGE
parts=[];faces_total=0
for part in make_parts(0):
 if part.family=='strut':continue  # runtime telescoping rods, same CAD dimensions
 verts,faces=part.solid.tessellate(5,1.4)
 xyz=np.array([[x.x,x.y,x.z] for x in verts],dtype=float)*.001
 if part.family=='hatch':xyz[:,2]-=HINGE[2]*.001
 f=np.asarray(faces,dtype=int)
 positions=[];normals=[]
 for a,b,c in f:
  A,B,C=xyz[a],xyz[b],xyz[c]
  normal=np.cross(B-A,C-A);normal=normal/(np.linalg.norm(normal)+1e-12)
  for v in (A,B,C):
   positions.extend(round(float(vv)*10000) for vv in v)
   normals.extend(round(float(vv)*127) for vv in normal)
 p=np.asarray(positions,dtype='<i2');n=np.asarray(normals,dtype='i1')
 col,metal=COLORS[part.color]
 parts.append({'name':part.name,'group':part.family,'c':col,'metal':metal,
  'p':base64.b64encode(p.tobytes()).decode(),'n':base64.b64encode(n.tobytes()).decode()})
 faces_total+=len(f)
model={'hinge_z':HINGE[2]*.001,'body_anchor':[-.47,1.17],'hatch_mount':[.018,-.30],
       'strut_y':.65,'parts':parts}
path=ROOT/'viewer'/'cad_mesh.js'
raw='window.RecursiveCAD='+json.dumps(model,separators=(',',':'))+';\n'
raw+='''// Decode display-only fixed-point CAD geometry synchronously (WebGL and Canvas fallback).
for(const mesh of window.RecursiveCAD.parts){
 const bytes=base64=>Uint8Array.from(atob(base64),c=>c.charCodeAt(0));
 const p=bytes(mesh.p),n=bytes(mesh.n);const view=new DataView(p.buffer);
 mesh.positions=Array.from({length:p.length/2},(_,i)=>view.getInt16(i*2,true)/10000);
 mesh.normals=Array.from(n,x=>(x>127?x-256:x)/127);
 delete mesh.p;delete mesh.n;
}
'''
path.write_text(raw)
print(f'compact CAD viewer: {len(parts)} parts, {faces_total} triangles, {path.stat().st_size/1024:.1f} KiB')
