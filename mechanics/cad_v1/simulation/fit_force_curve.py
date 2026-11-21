"""Fit actuator spring force from real or simulated load-cell data.

The fitter never labels synthetic data as measurements. Input columns:
 angle_deg, strut_force_N_each, measurement_type; optional temperature_C.
Geometry fixed to the published parametric CAD. No OEM calibration implied.
"""
from __future__ import annotations
import argparse,csv,json,sys,math
from pathlib import Path
from statistics import fmean
from physics_v2 import MAX_Q,geometry

class MeasurementError(ValueError):pass

def read_csv(path):
 with Path(path).open(newline='') as f:
  rows=list(csv.DictReader(f))
 if len(rows)<3: raise MeasurementError('Need >=3 angle/force pairs')
 for i,r in enumerate(rows):
  if not {'angle_deg','strut_force_N_each','measurement_type'}<=r.keys():
   raise MeasurementError('Require angle_deg,strut_force_N_each,measurement_type')
  try:
   angle=float(r['angle_deg']);force=float(r['strut_force_N_each'])
  except Exception as e:raise MeasurementError(f'Row {i+2} nonnumeric') from e
  if not math.isfinite(angle) or not math.isfinite(force) or not 0<=angle<=78 or force<=0:
   raise MeasurementError(f'Row {i+2} outside valid domain')
  r.update(angle_deg=angle,strut_force_N_each=force)
 return rows

def fit(rows):
 origin=geometry(MAX_Q)['length_m']
 xs=[origin-geometry(math.radians(r['angle_deg']))['length_m'] for r in rows]
 ys=[r['strut_force_N_each'] for r in rows]
 meanx,meany=fmean(xs),fmean(ys)
 sx=sum((x-meanx)**2 for x in xs)
 if sx<1e-8:raise MeasurementError('Measure at multiple hinge angles')
 b=sum((x-meanx)*(y-meany) for x,y in zip(xs,ys))/sx
 a=meany-b*meanx
 residual=[y-(a+b*x) for x,y in zip(xs,ys)]
 return {'open_force_N_each':round(a,4),'slope_N_per_m':round(b,4),
   'rmse_N_each':round(math.sqrt(fmean(x*x for x in residual)),5),
   'n':len(rows),'measurement_type':sorted(set(r['measurement_type'] for r in rows)),
   'angle_range_deg':[min(r['angle_deg'] for r in rows),max(r['angle_deg'] for r in rows)],
   'status':'fitted only to supplied data; not validated on independent hardware'}

def main():
 parser=argparse.ArgumentParser();parser.add_argument('csv');parser.add_argument('--out',default='')
 args=parser.parse_args();result=fit(read_csv(args.csv));print(json.dumps(result,indent=2))
 if args.out:Path(args.out).write_text(json.dumps(result,indent=2))
if __name__=='__main__':main()
