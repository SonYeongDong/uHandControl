"""The robot hand in 3D: the same procedural model and turntable view as uHandVirtualServer
(uhand_model + VisPy), fed with the simulated servo pulses. Right-drag turns it, the wheel zooms."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget
from uhand_model import hand_mesh
from vispy import app, scene

HOME = dict(elevation=12, azimuth=-12, scale_factor=4.3, center=(0, 0, 1.1))


class HandViewport(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        app.use_app("pyside6")
        self.canvas = scene.SceneCanvas(keys=None, bgcolor="#edf2fa", size=(320, 300), show=False)
        self.view = self.canvas.central_widget.add_view()
        self.view.camera = scene.cameras.TurntableCamera(fov=32, up="+z", **HOME)
        lines = []                                   # a grid in the floor plane
        for v in np.linspace(-4, 4, 17):
            lines.extend([[-4, v, -0.64], [4, v, -0.64], [v, -4, -0.64], [v, 4, -0.64]])
        scene.visuals.Line(pos=np.array(lines), color="#ccd7e8", connect="segments", parent=self.view.scene,
                           method="gl")
        self.mesh = scene.visuals.Mesh(parent=self.view.scene, shading="flat")
        self.last = None
        self.set_pulses([1500] * 6)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas.native)
        self._orbit = None
        self.canvas.native.installEventFilter(self)
        self.setMinimumSize(160, 96)

    def set_pulses(self, pulses) -> None:
        values = tuple(round(float(p) / 4) * 4 for p in pulses)      # redraw only when it would show
        if values == self.last:
            return
        self.last = values
        vertices, faces, colors = hand_mesh(values)
        self.mesh.set_data(vertices=vertices, faces=faces, face_colors=colors)

    def home(self) -> None:
        self.view.camera.set_state(**HOME)

    def zoom(self, factor: float) -> None:
        self.view.camera.scale_factor = max(1.5, min(12, self.view.camera.scale_factor * factor))

    def eventFilter(self, watched, event) -> bool:
        if watched is self.canvas.native:
            kind = event.type()
            if kind == QEvent.Type.Wheel:
                steps = max(-100, min(100, event.angleDelta().y() / 120.0))
                self.zoom(1.1 ** -steps)
                event.accept()
                return True
            if kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick) \
                    and event.button() == Qt.MouseButton.RightButton:
                camera = self.view.camera
                self._orbit = (event.position(), camera.azimuth, camera.elevation)
                watched.setCursor(Qt.CursorShape.ClosedHandCursor)
                return True
            if kind == QEvent.Type.MouseMove and self._orbit is not None:
                if event.buttons() & Qt.MouseButton.RightButton:
                    origin, azimuth, elevation = self._orbit
                    delta = event.position() - origin
                    self.view.camera.set_state(azimuth=azimuth - delta.x() * .5,
                                               elevation=max(-89, min(89, elevation + delta.y() * .5)))
                    return True
                self._orbit = None
                watched.unsetCursor()
            if kind == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.RightButton:
                self._orbit = None
                watched.unsetCursor()
                return True
            if kind in (QEvent.Type.FocusOut, QEvent.Type.Hide, QEvent.Type.WindowDeactivate):
                self._orbit = None
                watched.unsetCursor()
            if kind == QEvent.Type.ContextMenu:
                return True
        return super().eventFilter(watched, event)

    def shutdown(self) -> None:
        self.canvas.close()
