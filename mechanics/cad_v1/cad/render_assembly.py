"""Physical CAD renders using the exact parametric solids, via VTK EGL."""
from pathlib import Path
import sys, math
import numpy as np
import vtk
from vtk.util.numpy_support import numpy_to_vtk,numpy_to_vtkIdTypeArray
from build_assembly import make_parts,COLORS,ROOT
ASSET=ROOT/'assets'

def render(deg,name,cut=False):
    ren=vtk.vtkRenderer();ren.SetBackground(.06,.085,.116);ren.SetBackground2(.13,.17,.20);ren.GradientBackgroundOn()
    ren.AutomaticLightCreationOn()
    for part in make_parts(math.radians(deg)):
        v,f=part.solid.tessellate(2.8,.38)
        coords=np.array([[p.x,p.y,p.z] for p in v],dtype=np.float32)/1000
        faces=np.array(f,dtype=np.int64)
        pts=vtk.vtkPoints();pts.SetData(numpy_to_vtk(coords,deep=True))
        cells=np.column_stack([np.full(len(faces),3,dtype=np.int64),faces]).ravel()
        poly=vtk.vtkCellArray();poly.SetCells(len(faces),numpy_to_vtkIdTypeArray(cells,deep=True))
        data=vtk.vtkPolyData();data.SetPoints(pts);data.SetPolys(poly)
        ma=vtk.vtkPolyDataMapper();ma.SetInputData(data)
        actor=vtk.vtkActor();actor.SetMapper(ma)
        col,metal=COLORS[part.color];color=[int(col[i:i+2],16)/255 for i in (1,3,5)]
        actor.GetProperty().SetColor(*color);actor.GetProperty().SetAmbient(.3)
        actor.GetProperty().SetSpecular(.25*metal);actor.GetProperty().SetSpecularPower(36)
        if part.color=='glass':actor.GetProperty().SetOpacity(.7 if not cut else .25)
        if cut and part.color in ('skin','frame'):actor.GetProperty().SetOpacity(.15)
        ren.AddActor(actor)
    cam=ren.GetActiveCamera();cam.SetPosition(3.15,-3.5,2.5);cam.SetFocalPoint(-.15,0,1.29);cam.SetViewUp(0,0,1);cam.SetParallelProjection(True);cam.SetParallelScale(1.22)
    w=vtk.vtkRenderWindow();w.SetSize(1500,1000);w.SetOffScreenRendering(1);w.SetMultiSamples(4);w.AddRenderer(ren)
    w.Render();cap=vtk.vtkWindowToImageFilter();cap.SetInput(w);cap.ReadFrontBufferOff();cap.Update()
    writer=vtk.vtkPNGWriter();writer.SetFileName(str(ASSET/name));writer.SetInputConnection(cap.GetOutputPort());writer.Write()
    print(name,(ASSET/name).stat().st_size,flush=True)
    w.Finalize()

if __name__=='__main__':
    render(0,'mechanical_closed.png');render(78,'mechanical_open.png');render(45,'mechanical_cutaway.png',True)
