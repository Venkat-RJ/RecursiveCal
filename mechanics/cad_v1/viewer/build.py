"""Build fully standalone interactive CAD lab: embeds CAD triangle geometry and scripts."""
from pathlib import Path
p=Path(__file__).parent
s=(p/'index.html').read_text()
s=s.replace('<link rel="stylesheet" href="style.css">','<style>\n'+(p/'style.css').read_text()+'\n</style>')
for file in ['physics_v2.js','cad_mesh.js','cad_renderer.js','app.js']:
 s=s.replace(f'<script src="{file}"></script>',f'<script>\n'+(p/file).read_text()+'\n</script>')
(p/'RecursiveCal_CAD_Lab.html').write_text(s)
print('standalone',(p/'RecursiveCal_CAD_Lab.html').stat().st_size,'bytes')
