"""RecursiveCal engineering demonstrator: original parametric liftgate CAD assembly.

UNITS: CAD dimensions mm, kinematics/dynamics SI. NO OEM geometry or measurements.
Export STEP solids at two poses and GLB visualization meshes. CAD and the dynamics
share the same geometric reference to eliminate accidental visual/physical mismatch.
"""
from __future__ import annotations
import csv, json, math
from pathlib import Path
from dataclasses import dataclass
import cadquery as cq
import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'assets'
OUT.mkdir(exist_ok=True)

HINGE=(0.,0.,1760.)
Q_OPEN=math.radians(78)
MOUNT_BODY=(-470.,1170.)  # x,z in mm
MOUNT_HATCH=(18.,-300.)  # hatch-local x,z in mm relative to hinge
HALF_WIDTH=650.  # y coordinates for powered strut centers

COLORS={
 'frame':('#475363',.75),'skin':('#73889a',.75),'glass':('#29485a',.35),
 'steel':('#c6ced8',.95),'hinge':('#a3b4c0',.85),'black':('#273440',.45),
 'rubber':('#151b25',.0),'housing':('#3c5260',.63),'rod':('#e3e9f0',.98),
 'electrical':('#b58239',.4),'red':('#a3423d',.2),'gas':('#717d8b',.5),
 'guide':('#527880',.75),
}
@dataclass
class Component:
 name:str
 solid:cq.Shape
 family:str='static'
 color:str='steel'
 shade:str=''


def box(cx,cy,cz,dx,dy,dz,fillet=0):
 s=cq.Workplane('XY').box(dx,dy,dz).translate((cx,cy,cz))
 if fillet:
  try: s=s.edges().fillet(fillet)
  except Exception: pass
 return s.val()

def cylinder(a,b,r):
 A=cq.Vector(*a);B=cq.Vector(*b);v=B-A
 return cq.Solid.makeCylinder(r,v.Length,A,v.normalized())

def sphere(c,r):
 return cq.Solid.makeSphere(r,cq.Vector(*c))

def plate_yz(x,contour,depth,roundness=0):
 # local YZ sketch, extrudes in positive X
 s=cq.Workplane('YZ',origin=(x,0,0)).polyline(contour).close().extrude(depth)
 if roundness:
  try:s=s.edges('|X').fillet(roundness)
  except Exception:pass
 return s.val()

def transform_hatch(shape,q):
 return shape.rotate((0,0,0),(0,1,0),-math.degrees(q)).translate(HINGE)

def hatch_mount(q,side):
 x,z=MOUNT_HATCH
 return ((x*math.cos(q)-z*math.sin(q)),side*HALF_WIDTH,HINGE[2]+x*math.sin(q)+z*math.cos(q))

def length_mm(q):
 bx,_,bz=hatch_mount(q,1)
 return math.dist((MOUNT_BODY[0],HALF_WIDTH,MOUNT_BODY[1]),(bx,HALF_WIDTH,bz))

def make_parts(q:float=0)->list[Component]:
 parts=[]
 def add(name,s,family='static',color='steel'):
  if hasattr(s,'val'):s=s.val()
  assert s.Volume()>1e-5,(name,s.Volume())
  parts.append(Component(name,s,family,color))

 # Compact open rear body clip with physical box-section panels, aperture and flange.
 add('BODY_01_header_crossmember',box(-154,0,1722,260,1750,128,9),'static','frame')
 add('BODY_02_lower_sill',box(-160,0,665,285,1690,135,10),'static','frame')
 for sign,side in [(-1,'LH'),(1,'RH')]:
  y=sign*808
  add(f'BODY_03_{side}_D_pillar',box(-250,y,1210,290,150,940,14),'static','skin')
  add(f'BODY_04_{side}_inner_rail',box(-80,sign*730,1190,105,57,910,5),'static','frame')
  add(f'BODY_05_{side}_seal_channel',box(-3,sign*739,1224,22,22,920,3),'static','rubber')
  add(f'BODY_06_{side}_upper_hinge_bracket',box(-91,sign*575,1747,130,85,61,6),'static','hinge')
  add(f'BODY_07_{side}_hinge_mount_lug',box(-19,sign*588,1753,57,40,66,6),'static','hinge')
  add(f'BODY_08_{side}_strut_ball_stud',sphere((MOUNT_BODY[0],sign*HALF_WIDTH,MOUNT_BODY[1]),15),'static','steel')
  add(f'BODY_09_{side}_strut_mount_bracket',box(-460,sign*HALF_WIDTH,1168,78,85,72,8),'static','frame')
  add(f'BODY_10_{side}_strut_ball_neck',cylinder((-480,sign*HALF_WIDTH,1165),(-470,sign*HALF_WIDTH,1170),10),'static','steel')
  add(f'BODY_11_{side}_lamphousing',box(-5,sign*791,1120,68,72,250,12),'static','red')
 add('BODY_12_bumper',box(-40,0,541,180,1840,123,25),'static','skin')
 add('BODY_13_cargo_floor',box(-675,0,689,1100,1550,72,10),'static','frame')
 add('BODY_14_upper_rail_reinforcement',box(-270,0,1750,470,1680,65,8),'static','black')
 add('BODY_15_latch_striker',cylinder((-25,-25,665),(-25,25,665),12),'static','steel')
 
 # Mobile hatch as a real shell, inset glass pane, reinforcement, hinges and latch.
 outer=[(-760,-70),(760,-70),(705,-1158),(-705,-1158)]  # Y,Z local
 window=[(-605,-174),(605,-174),(567,-670),(-567,-670)]
 panel=cq.Workplane('YZ',origin=(65,0,0)).polyline(outer).close().extrude(30)
 hole=cq.Workplane('YZ',origin=(60,0,0)).polyline(window).close().extrude(44)
 add('HATCH_01_outer_skin_cut_glazing',panel.cut(hole).val(),'hatch','skin')
 add('HATCH_02_laminated_rear_glass',plate_yz(93,window,9),'hatch','glass')
 add('HATCH_03_window_inner_bezel',plate_yz(58,[(-630,-157),(630,-157),(584,-691),(-584,-691)],17).cut(plate_yz(51,window,32)),'hatch','black')
 add('HATCH_04_bottom_reinforcement',box(34,0,-1102,72,1360,83,6),'hatch','frame')
 add('HATCH_05_top_spoiler',box(100,0,-55,210,1580,58,12),'hatch','black')
 add('HATCH_06_center_latch_motor',box(-14,0,-1095,85,148,116,8),'hatch','black')
 add('HATCH_07_trunk_handle',box(109,0,-907,22,220,47,5),'hatch','steel')
 add('HATCH_08_brakelamp',box(140,0,-64,14,1250,18,5),'hatch','red')
 for sign,side in [(-1,'LH'),(1,'RH')]:
  y=sign*620
  add(f'HATCH_09_{side}_longitudinal_stiffener',box(22,sign*678,-670,83,45,893,5),'hatch','frame')
  add(f'HATCH_10_{side}_hinge_leaf',box(-22,sign*572,-39,130,78,63,6),'hatch','hinge')
  add(f'HATCH_11_{side}_latch_reinforcement',box(-13,sign*530,-1090,73,170,74,6),'hatch','frame')
  add(f'HATCH_12_{side}_strut_lug',box(-14,sign*650,-300,73,91,69,5),'hatch','hinge')
  add(f'HATCH_13_{side}_strut_ball',sphere((MOUNT_HATCH[0],sign*HALF_WIDTH,MOUNT_HATCH[1]),14),'hatch','steel')
  add(f'HATCH_14_{side}_ball_stud_neck',cylinder((-15,sign*HALF_WIDTH,-300),(18,sign*HALF_WIDTH,-300),8),'hatch','steel')
  add(f'HATCH_15_{side}_hinge_bushing',cylinder((0,sign*525,0),(0,sign*625,0),18),'hatch','black')
 # upper hinge static pin must be one fixed axle through moving hinge bearings
 add('HINGE_01_continuous_pivot',cylinder((0,-680,HINGE[2]),(0,680,HINGE[2]),10),'static','steel')
 for sign,side in [(-1,'LH'),(1,'RH')]:
  add(f'HINGE_02_{side}_washer',cylinder((0,sign*613,HINGE[2]),(0,sign*622,HINGE[2]),23),'static','hinge')

 # Physical powered strut with axial housing and exposed telescopic rod.
 for sign,side in [(-1,'LH'),(1,'RH')]:
  A=np.array((MOUNT_BODY[0],sign*HALF_WIDTH,MOUNT_BODY[1]),dtype=float)
  B=np.array(hatch_mount(q,sign),dtype=float)
  axis=(B-A)/np.linalg.norm(B-A)
  def pt(t):return tuple((A+t*axis).tolist())
  length=float(np.linalg.norm(B-A))
  assert length>460,(q,length)
  add(f'STRUT_{side}_motor_housing',cylinder(pt(35),pt(155),38),'strut','housing')
  add(f'STRUT_{side}_outer_tube',cylinder(pt(140),pt(402),31),'strut','housing')
  add(f'STRUT_{side}_rod_gland',cylinder(pt(391),pt(421),35),'strut','steel')
  add(f'STRUT_{side}_piston_rod',cylinder(pt(412),pt(length-18),12.5),'strut','rod')
  add(f'STRUT_{side}_neck_eye',cylinder(pt(length-21),pt(length-5),19),'strut','steel')
  add(f'STRUT_{side}_body_socket',cylinder(pt(8),pt(38),19),'strut','black')
  add(f'STRUT_{side}_seal_ring',cylinder(pt(396),pt(401),33.5),'strut','rubber')
  add(f'STRUT_{side}_motor_cap',cylinder(pt(37),pt(63),40),'strut','black')
  add(f'STRUT_{side}_motor_connector',sphere(tuple((A+85*axis+np.array((0,sign*38,0))).tolist()),16),'strut','electrical')
  add(f'STRUT_{side}_rod_end_socket',sphere(pt(length-8),21),'strut','black')

 # pose mobile hatch parts
 for item in parts:
  if item.family=='hatch':item.solid=transform_hatch(item.solid,q)
 return parts


def make_assembly(q,name):
 parts=make_parts(q)
 a=cq.Assembly(name=name)
 for part in parts:
  c,metal=COLORS[part.color]
  rgb=tuple(int(c[i:i+2],16)/255 for i in (1,3,5))
  a.add(part.solid,name=part.name,color=cq.Color(*rgb))
 return a,parts


def trimesh_for(solid,material):
 verts,faces=solid.tessellate(1.5,0.30)
 xyz=np.array([[x.x,x.y,x.z] for x in verts],dtype='float64')*.001
 ijk=np.array(faces,dtype='int64')
 mesh=trimesh.Trimesh(vertices=xyz,faces=ijk,process=False)
 c=COLORS[material][0]; rgba=np.array([int(c[i:i+2],16) for i in (1,3,5)]+[255],dtype=np.uint8)
 mesh.visual.face_colors=np.tile(rgba,(len(mesh.faces),1))
 return mesh


def export_pose(degrees,filename):
 q=math.radians(degrees)
 a,parts=make_assembly(q,filename)
 step=OUT / f'{filename}.step'
 a.save(str(step))
 sc=trimesh.Scene()
 triangles=0
 for part in parts:
  mesh=trimesh_for(part.solid,part.color)
  triangles+=len(mesh.faces)
  sc.add_geometry(mesh,node_name=part.name,geom_name=part.name)
 glb=OUT/f'{filename}.glb'
 glb.write_bytes(sc.export(file_type='glb'))
 return {'pose_deg':degrees,'step':step.name,'glb':glb.name,'components':len(parts),'triangles':triangles,'step_bytes':step.stat().st_size,'glb_bytes':glb.stat().st_size}


def main():
 stats=[export_pose(0,'recursivecal_tailgate_closed'),export_pose(78,'recursivecal_tailgate_open')]
 _,parts=make_assembly(0,'bom')
 with (OUT/'bill_of_materials.csv').open('w',newline='') as f:
  writer=csv.writer(f);writer.writerow(('part_name','subassembly','color','volume_cm3','CAD_material_note'))
  for x in parts:writer.writerow((x.name,x.family,x.color,round(x.solid.Volume()/1000,1),'illustrative geometric solid; not OEM manufacturing spec'))
 summary={'identity':'RecursiveCal parametric mechanical assembly','CAD_units':'mm',
  'references':'illustrative engineering design, no OEM measurements',
  'hinge_height_m':HINGE[2]/1000,'opening_angle_deg':78,
  'body_strut_mount_xz_m':[v/1000 for v in MOUNT_BODY],
  'hatch_local_strut_mount_xz_m':[v/1000 for v in MOUNT_HATCH],
  'strut_closed_length_mm':round(length_mm(0),2),
  'strut_open_length_mm':round(length_mm(Q_OPEN),2),
  'strut_stroke_mm':round(length_mm(Q_OPEN)-length_mm(0),2),
  'snapshots':stats}
 (OUT/'assembly_metadata.json').write_text(json.dumps(summary,indent=2))
 print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
