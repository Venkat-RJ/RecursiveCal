"""Generate a synthetic load-cell-like sample to test only the CSV ingestion path."""
import csv,random,math
from pathlib import Path
from physics_v2 import Plant,geometry,gas_force
out=Path(__file__).resolve().parents[1]/'assets'/'SYNTHETIC_force_samples.csv'
rng=random.Random(20261121)
with out.open('w',newline='') as f:
 w=csv.writer(f);w.writerow(['angle_deg','strut_force_N_each','measurement_type','temperature_C'])
 for deg in range(0,79,6):
  force=gas_force(deg*math.pi/180,Plant())+rng.gauss(0,1.8)
  w.writerow([deg,round(force,4),'SYNTHETIC_NOT_HARDWARE',23])
print('generated synthetic example',out)
