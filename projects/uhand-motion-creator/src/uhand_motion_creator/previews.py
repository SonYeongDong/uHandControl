"""Small local previews and mixed-card thumbnails (no networking)."""
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor,QPainter,QPen,QPixmap,QFont
from PySide6.QtWidgets import QWidget
from .motion import Motion,Buzzer,LED
from .viewport import thumbnail

class OutputPreview(QWidget):
    def __init__(self,mode,parent=None):
        super().__init__(parent);self.mode=mode;self.rgb=(False,)*3;self.frequency=1000;self.active=False
        self.setMinimumSize(220,180)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Keep the output caption and both lamps visible in the compact window.
        scale = min(1.0, self.height() / 310)
        p.scale(scale, scale)
        width, height = round(self.width() / scale), round(self.height() / scale)
        center=QPointF(width/2,height/2-12)
        p.setPen(Qt.PenStyle.NoPen)
        if self.mode=="led":
            color=QColor(*self.rgb) if any(self.rgb) else QColor("#27364c")
            for x in (width*.33,width*.67):
                p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor("#eaf1fa"));p.drawEllipse(QPointF(x,center.y()),61,61)
                p.setBrush(color);p.setPen(QPen(QColor("#bac9dc"),2));p.drawEllipse(QPointF(x,center.y()),43,43)
                p.setPen(QColor("#718098"));p.drawText(int(x-36),int(center.y()+90),72,30,Qt.AlignmentFlag.AlignCenter,"LED 1" if x<width/2 else "LED 2")
            text=f"RGB {self.rgb[0]}, {self.rgb[1]}, {self.rgb[2]}" if any(self.rgb) else "OFF"
        else:
            p.setBrush(QColor("#f0eaff"));p.drawEllipse(center,73,73)
            p.setPen(QColor("#7856c8"));p.setFont(QFont("Segoe UI",44));p.drawText(int(center.x()-60),int(center.y()-48),120,96,Qt.AlignmentFlag.AlignCenter,"♪")
            text=f"{self.frequency} Hz  ·  "+("재생 중" if self.active else "대기")
        p.setPen(QColor("#182a45"));p.setFont(QFont("Malgun Gothic",16))
        p.drawText(0,int(center.y()+125),width,36,Qt.AlignmentFlag.AlignCenter,text)
        p.end()

def card_thumbnail(item):
    if isinstance(item,Motion):return thumbnail(item.pulses)
    pix=QPixmap(88,96);pix.fill(Qt.GlobalColor.transparent)
    p=QPainter(pix);p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor("#eee7fb" if isinstance(item,Buzzer) else "#e3f4ed"))
    p.drawRoundedRect(2,2,84,92,12,12)
    if isinstance(item,Buzzer):
        p.setPen(QColor("#7856c8"));p.setFont(QFont("Segoe UI",32));p.drawText(pix.rect(),Qt.AlignmentFlag.AlignCenter,"♪")
    else:
        color=QColor(*item.output_rgb) if any(item.output_rgb) else QColor("#27364c")
        p.setBrush(color);p.setPen(QPen(QColor("#9cbbc0"),1))
        p.drawEllipse(QPointF(27,45),14,14);p.drawEllipse(QPointF(61,45),14,14)
        p.setPen(QColor("#396654"));p.setFont(QFont("Segoe UI",10));p.drawText(0,68,88,20,Qt.AlignmentFlag.AlignCenter,"RGB")
    p.end();return pix
