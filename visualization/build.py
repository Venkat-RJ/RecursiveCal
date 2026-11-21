"""Build the offline, self-contained RecursiveCal visual demo."""
from pathlib import Path
import json
root=Path(__file__).resolve().parent
scenarios=json.loads((root/'scenarios.json').read_text())
assert len(scenarios)==7
html=(root/'template.html').read_text()
for key,name in [('__CSS__','styles.css'),('__ENGINE__','engine.js'),('__APP__','app.js'),('__BENCH__','bench.svg')]:
    assert html.count(key)==1
    html=html.replace(key,(root/name).read_text())
assert html.count('__SCENARIOS__')==1
html=html.replace('__SCENARIOS__',json.dumps(scenarios,separators=(',',':')).replace('</','<\\/'))
(root/'index.html').write_text(html)
print('Built',root/'index.html',len(html.encode()),'bytes')
