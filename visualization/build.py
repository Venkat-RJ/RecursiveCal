"""Rebuild the standalone RecursiveCal visual laboratory from local source files."""
from pathlib import Path
import json
p=Path(__file__).resolve().parent
scenarios=json.loads((p/'scenarios.json').read_text())
assert len(scenarios)==7 and all(row['seed']>=70_000_000 for row in scenarios)
t=(p/'template.html').read_text()
for placeholder,filename in [('__CSS__','styles.css'),('__ENGINE__','engine.js'),('__APP__','app.js')]:
    assert t.count(placeholder)==1
    t=t.replace(placeholder,(p/filename).read_text().strip())
assert t.count('__SCENARIOS__')==1
t=t.replace('__SCENARIOS__',json.dumps(scenarios,separators=(',',':')).replace('</','<\\/'))
assert not any(x in t for x in ('__CSS__','__ENGINE__','__APP__','__SCENARIOS__'))
(p/'index.html').write_text(t)
print('Built',p/'index.html')
