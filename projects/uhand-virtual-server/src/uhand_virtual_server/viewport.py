"""VisPy turntable viewport embedded in the Qt layout."""
from PySide6.QtCore import Qt, QEvent
from PySide6.QtWidgets import QWidget, QVBoxLayout
from vispy import app, scene
import numpy as np

from .model import hand_mesh


class HandViewport(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        app.use_app("pyside6")
        self.canvas = scene.SceneCanvas(keys=None, bgcolor="#edf2fa", size=(780, 500), show=False)
        self.view = self.canvas.central_widget.add_view()
        self.view.camera = scene.cameras.TurntableCamera(
            fov=32, elevation=12, azimuth=-12, scale_factor=4.3, center=(0,0,1.1), up="+z"
        )
        # Grid in the floor plane, independently from the moving wrist.
        lines = []
        for v in np.linspace(-4, 4, 17):
            lines.extend([[-4,v,-0.64],[4,v,-0.64],[v,-4,-0.64],[v,4,-0.64]])
        scene.visuals.Line(pos=np.array(lines), color="#ccd7e8", connect="segments",
                           parent=self.view.scene, method="gl")
        self.mesh = scene.visuals.Mesh(parent=self.view.scene, shading="flat")
        self.last = None
        self.set_pulses([1500]*6)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.addWidget(self.canvas.native)
        self._orbit=None
        self.canvas.native.installEventFilter(self)
        self.setMinimumSize(420, 230)

    def set_pulses(self, pulses):
        values = tuple(round(float(p), 2) for p in pulses)
        if values == self.last:
            return
        self.last = values
        vertices, faces, colors = hand_mesh(values)
        self.mesh.set_data(vertices=vertices, faces=faces, face_colors=colors)

    def home(self):
        self.view.camera.set_state(elevation=12, azimuth=-12, scale_factor=4.3, center=(0,0,1.1))

    def front(self):
        self.view.camera.set_state(elevation=0, azimuth=0, scale_factor=4.3, center=(0,0,1.1))

    def zoom(self, factor):
        self.view.camera.scale_factor = max(1.5, min(12, self.view.camera.scale_factor * factor))

    def eventFilter(self,watched,event):
        if watched is self.canvas.native:
            kind=event.type()
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
