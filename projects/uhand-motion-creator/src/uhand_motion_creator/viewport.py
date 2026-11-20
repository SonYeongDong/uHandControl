"""Shared geometry with explicit edit/camera modes and triangle picking."""
import numpy as np
from .motion import PULSE_LIMITS
from PySide6.QtCore import Signal, Qt, QPointF, QEvent
from PySide6.QtGui import QColor, QPainter, QPixmap, QPolygonF
from PySide6.QtWidgets import QWidget, QVBoxLayout, QSizePolicy
from vispy import app, scene
from uhand_model import hand_mesh_parts, hand_mesh, rotation_z, rotation_x

def thumbnail(pulses):
    vertices,faces,colors=hand_mesh(pulses)
    # Fixed oblique orthographic projection, independent of the working camera.
    points=vertices @ rotation_z(np.deg2rad(-12)).T
    x=points[:,0]+points[:,1]*.25
    y=-points[:,2]+points[:,1]*.12
    scale=23
    xy=np.column_stack((x*scale+43,y*scale+77))
    pix=QPixmap(88,96);pix.fill(QColor("#edf2fa"))
    painter=QPainter(pix);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    for idx in np.argsort(-points[faces,1].mean(axis=1)):
        painter.setBrush(QColor.fromRgbF(*colors[idx]))
        painter.drawPolygon(QPolygonF([QPointF(*p) for p in xy[faces[idx]]]))
    painter.end()
    return pix

class EditViewport(QWidget):
    pulseChanged=Signal(int,int)
    axisSelected=Signal(int)
    def __init__(self):
        super().__init__()
        app.use_app("pyside6")
        self.canvas=scene.SceneCanvas(keys=None,bgcolor="#edf2fa",show=False)
        self.canvas.native.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Ignored)
        self.view=self.canvas.central_widget.add_view()
        self.view.camera=scene.cameras.TurntableCamera(fov=32,elevation=12,azimuth=-12,scale_factor=4.3,center=(0,0,1.1),up="+z",interactive=False)
        lines=[]
        for v in np.linspace(-4,4,17):
            lines.extend([[-4,v,-.64],[4,v,-.64],[v,-4,-.64],[v,4,-.64]])
        scene.visuals.Line(pos=np.array(lines),color="#ccd7e8",connect="segments",parent=self.view.scene,method="gl")
        self.mesh=scene.visuals.Mesh(parent=self.view.scene,shading="flat")
        self.pulses=(1500,)*6;self.axis=0;self.edit_mode=True;self.drag=None;self.previewing=False
        self.set_pulses(self.pulses)
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.addWidget(self.canvas.native)
        self._orbit=None
        self.canvas.native.installEventFilter(self)
        self.setMinimumSize(380,270)
        self.canvas.events.mouse_press.connect(self._press)
        self.canvas.events.mouse_move.connect(self._move)
        self.canvas.events.mouse_release.connect(self._release)
    def set_pulses(self,pulses):
        self.pulses=tuple(pulses)
        self.vertices,self.faces,colors,self.parts=hand_mesh_parts(pulses)
        colors=colors.copy();colors[self.parts==self.axis]=(0.25,.55,1,1)
        self.mesh.set_data(vertices=self.vertices,faces=self.faces,face_colors=colors)
    def select_axis(self,axis):
        self.axis=axis;self.set_pulses(self.pulses)
    def mode(self,editing):
        self.edit_mode=editing;self.drag=None;self.view.camera.interactive=not editing
    def home(self):
        self.view.camera.set_state(elevation=12,azimuth=-12,scale_factor=4.3,center=(0,0,1.1))
    def front(self):
        self.view.camera.set_state(elevation=0,azimuth=0,scale_factor=4.3,center=(0,0,1.1))
    def zoom(self,factor):
        self.view.camera.scale_factor=max(1.5,min(12,self.view.camera.scale_factor*factor))
    def projected(self):
        p=self.mesh.get_transform("visual","canvas").map(self.vertices)
        return p[:,:3]/p[:,3:4]
    def pick(self,pos):
        projected=self.projected()
        triangles=projected[self.faces]
        a,b,c=triangles[:,0,:2],triangles[:,1,:2],triangles[:,2,:2]
        v0=b-a;v1=c-a;v2=np.asarray(pos)-a
        det=v0[:,0]*v1[:,1]-v1[:,0]*v0[:,1]
        safe=np.where(abs(det)>1e-8,det,np.nan)
        u=(v2[:,0]*v1[:,1]-v1[:,0]*v2[:,1])/safe
        v=(v0[:,0]*v2[:,1]-v2[:,0]*v0[:,1])/safe
        valid=(u>=0)&(v>=0)&(u+v<=1)&np.isfinite(safe)
        ids=np.flatnonzero(valid)
        if not len(ids): return None
        depth=(1-u-v)*triangles[:,0,2]+u*triangles[:,1,2]+v*triangles[:,2,2]
        part=int(self.parts[ids[np.argmin(depth[ids])]])
        return part if part>=0 else None
    def _press(self,event):
        if self.previewing or not self.edit_mode or event.button!=1:return
        axis=self.pick(event.pos)
        if axis is None:return
        self.axisSelected.emit(axis)
        self.drag=(axis,tuple(event.pos),self.pulses[axis])
        event.handled=True
    def _move(self,event):
        if self.previewing or self.drag is None or not self.edit_mode:return
        axis,start,value=self.drag
        delta=event.pos[0]-start[0] if axis==5 else start[1]-event.pos[1]
        low,high=PULSE_LIMITS[axis]
        self.pulseChanged.emit(axis,max(low,min(high,round(value+delta*8))))
        event.handled=True
    def _release(self,event):
        self.drag=None
    def eventFilter(self,watched,event):
        if watched is self.canvas.native:
            kind=event.type()
            if kind==QEvent.Type.Wheel:
                # Handle once in both modes without enabling left-drag camera input.
                steps=max(-100,min(100,event.angleDelta().y()/120.0))
                if steps:self.zoom(1.1 ** -steps)
                event.accept()
                return True
            if kind in (QEvent.Type.MouseButtonPress,QEvent.Type.MouseButtonDblClick) and event.button()==Qt.MouseButton.RightButton:
                camera=self.view.camera
                self._orbit=(event.position(),camera.azimuth,camera.elevation)
                if hasattr(self,"drag"):self.drag=None
                watched.setCursor(Qt.CursorShape.ClosedHandCursor)
                return True
            if kind==QEvent.Type.MouseMove and self._orbit is not None:
                if event.buttons() & Qt.MouseButton.RightButton:
                    origin,azimuth,elevation=self._orbit;delta=event.position()-origin
                    self.view.camera.set_state(azimuth=azimuth-delta.x()*.5,
                        elevation=max(-89,min(89,elevation+delta.y()*.5)))
                    return True
                self._orbit=None;watched.unsetCursor()
            if kind==QEvent.Type.MouseButtonRelease and event.button()==Qt.MouseButton.RightButton:
                self._orbit=None;watched.unsetCursor();return True
            if kind in (QEvent.Type.FocusOut,QEvent.Type.Hide,QEvent.Type.WindowDeactivate):
                self._orbit=None;watched.unsetCursor()
            if kind==QEvent.Type.ContextMenu:return True
        return super().eventFilter(watched,event)

    def shutdown(self):
        self.canvas.close()
