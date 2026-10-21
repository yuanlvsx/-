"""通用自绘控件：开关、卡片、棋盘格预览、滑杆行。"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (Property, QEasingCurve, QPropertyAnimation, QRectF,
                            QSize, Qt, Signal)
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QFrame, QHBoxLayout, QLabel,
                               QSizePolicy, QSlider, QVBoxLayout, QWidget)

from . import theme


class Card(QFrame):
    def __init__(self, parent=None, object_name: str = "Card"):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setAttribute(Qt.WA_Hover, True)


class Switch(QAbstractButton):
    """iOS 风格开关。"""

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(42, 24)
        self._offset = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(42, 24)

    # 供动画使用
    def get_offset(self) -> float:
        return self._offset

    def set_offset(self, value: float) -> None:
        self._offset = float(value)
        self.update()

    offset = Property(float, get_offset, set_offset)

    def _animate(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        r = h / 2
        off = self._offset
        base = QColor(0x2A, 0x31, 0x3D)
        on = QColor(theme.GOLD)
        col = QColor(
            int(base.red() + (on.red() - base.red()) * off),
            int(base.green() + (on.green() - base.green()) * off),
            int(base.blue() + (on.blue() - base.blue()) * off),
        )
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)
        knob_x = 3 + off * (w - h)
        p.setBrush(QColor("#FBFAF7") if off > 0.5 else QColor("#C6CDDA"))
        p.drawEllipse(QRectF(knob_x, 3, h - 6, h - 6))
        p.end()


class ThumbWidget(QWidget):
    """棋盘格背景 + 带透明通道的画面预览。"""

    def __init__(self, radius: int = 10, parent=None):
        super().__init__(parent)
        self._image: Optional[QImage] = None
        self._radius = radius
        self._hint = "无预览"
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._board = self._make_board()
        self.setAttribute(Qt.WA_StyledBackground, False)

    @staticmethod
    def _make_board() -> QPixmap:
        tile = 8
        pm = QPixmap(tile * 2, tile * 2)
        pm.fill(QColor("#1A1E26"))
        p = QPainter(pm)
        p.fillRect(0, 0, tile, tile, QColor("#22272F"))
        p.fillRect(tile, tile, tile, tile, QColor("#22272F"))
        p.end()
        return pm

    def set_image(self, img: Optional[QImage]) -> None:
        self._image = img
        self.update()

    def set_hint(self, text: str) -> None:
        self._hint = text
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        p.setClipPath(path)
        p.fillRect(rect, QColor("#14181F"))
        p.fillRect(rect, self._board)

        if self._image and not self._image.isNull():
            iw, ih = self._image.width(), self._image.height()
            scale = min(rect.width() / iw, rect.height() / ih)
            w, h = iw * scale, ih * scale
            target = QRectF(rect.center().x() - w / 2, rect.center().y() - h / 2, w, h)
            p.drawImage(target, self._image)
        else:
            p.setPen(QColor(theme.TEXT_MUTE))
            p.setFont(theme.font(11))
            p.drawText(rect, Qt.AlignCenter, self._hint)

        p.setClipping(False)
        p.setPen(QColor(0, 0, 0, 70))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), self._radius, self._radius)
        p.end()


class SliderRow(QWidget):
    valueChanged = Signal(int)

    def __init__(self, label: str, minimum: int, maximum: int, value: int,
                 suffix: str = "", parent=None):
        super().__init__(parent)
        self._suffix = suffix
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self.title = QLabel(label)
        self.title.setObjectName("Meta")
        self.title.setFixedWidth(76)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(value)
        self.value_label = QLabel(f"{value}{suffix}")
        self.value_label.setFixedWidth(46)
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.value_label.setObjectName("Meta")
        lay.addWidget(self.title)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.value_label)
        self.slider.valueChanged.connect(self._on_change)

    def _on_change(self, v: int) -> None:
        self.value_label.setText(f"{v}{self._suffix}")
        self.valueChanged.emit(v)

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, v: int) -> None:  # noqa: N802
        self.slider.setValue(int(v))


class FormRow(QWidget):
    """左标题 + 右控件的设置行。"""

    def __init__(self, title: str, control: QWidget, hint: str = "", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(2)
        lbl = QLabel(title)
        lbl.setStyleSheet("font-size: 13px; color: #DDE3ED;")
        left.addWidget(lbl)
        if hint:
            sub = QLabel(hint)
            sub.setObjectName("Hint")
            sub.setWordWrap(True)
            left.addWidget(sub)
        lay.addLayout(left, 1)
        lay.addWidget(control, 0, Qt.AlignVCenter)


class SectionCard(Card):
    """带小标题的设置分组。"""

    def __init__(self, title: str, parent=None):
        super().__init__(parent, "Panel")
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(20, 16, 20, 18)
        self._lay.setSpacing(14)
        if title:
            head = QLabel(title)
            head.setObjectName("Section")
            self._lay.addWidget(head)

    def add(self, widget: QWidget) -> None:
        self._lay.addWidget(widget)

    def add_divider(self) -> None:
        line = QFrame()
        line.setObjectName("Divider")
        line.setFixedHeight(1)
        self._lay.addWidget(line)
