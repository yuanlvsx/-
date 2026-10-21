"""配色、全局样式表与图标绘制。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QIcon, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap)

from core.config import CACHE_DIR

BG = "#0C0E13"
SIDEBAR = "#101319"
PANEL = "#14181F"
CARD = "#171B23"
CARD_HOVER = "#1B2029"
BORDER = "#232833"
BORDER_SOFT = "#1C212A"
TEXT = "#E9ECF3"
TEXT_DIM = "#98A1B3"
TEXT_MUTE = "#6A7284"
GOLD = "#D8A54A"
GOLD_LIGHT = "#F2C878"
GOLD_DARK = "#A87B27"
GREEN = "#4ADE80"
RED = "#EF6666"

QSS = f"""
* {{
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
    outline: none;
}}
QWidget {{ color: {TEXT}; font-size: 13px; }}
QWidget#Root {{ background: {BG}; }}
QWidget#Sidebar {{ background: {SIDEBAR}; border-right: 1px solid {BORDER_SOFT}; }}
QWidget#Page {{ background: transparent; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QLabel#AppName {{ font-size: 17px; font-weight: 600; letter-spacing: 0.5px; color: #F3F5FA; }}
QLabel#AppSub {{ font-size: 10px; color: {TEXT_MUTE}; letter-spacing: 2px; }}
QLabel#PageTitle {{ font-size: 20px; font-weight: 600; color: #F3F5FA; }}
QLabel#PageDesc {{ font-size: 12px; color: {TEXT_MUTE}; }}
QLabel#Section {{ font-size: 11px; color: {TEXT_MUTE}; letter-spacing: 1.4px; font-weight: 600; }}
QLabel#CardName {{ font-size: 13.5px; font-weight: 600; color: #EDF0F6; }}
QLabel#Meta {{ font-size: 11px; color: {TEXT_MUTE}; }}
QLabel#Hint {{ font-size: 11px; color: {TEXT_MUTE}; }}

QPushButton#Nav {{
    text-align: left; padding: 10px 14px; border: none; border-radius: 9px;
    color: {TEXT_DIM}; background: transparent; font-size: 13px;
}}
QPushButton#Nav:hover {{ background: #161B24; color: #D8DEEA; }}
QPushButton#Nav:checked {{
    background: #1B2029; color: {GOLD_LIGHT}; font-weight: 600;
    border-left: 3px solid {GOLD};
}}

QPushButton#Primary {{
    background: {GOLD}; color: #17120A; border: none; border-radius: 8px;
    padding: 9px 16px; font-weight: 600;
}}
QPushButton#Primary:hover {{ background: #E5B45C; }}
QPushButton#Primary:pressed {{ background: #C08F35; }}
QPushButton#Ghost {{
    background: #1A1F28; color: #C8D0DE; border: 1px solid {BORDER};
    border-radius: 8px; padding: 7px 13px;
}}
QPushButton#Ghost:hover {{ background: #212836; border-color: #333B4B; color: #E3E8F1; }}
QPushButton#Ghost:pressed {{ background: #171C24; }}
QPushButton#Link {{
    background: transparent; border: none; color: {TEXT_DIM}; padding: 4px 6px; font-size: 12px;
}}
QPushButton#Link:hover {{ color: {GOLD_LIGHT}; }}
QPushButton#Danger {{ background: transparent; border: none; color: #7C8497; padding: 4px 8px; }}
QPushButton#Danger:hover {{ color: {RED}; }}

QFrame#Card {{ background: {CARD}; border: 1px solid {BORDER_SOFT}; border-radius: 14px; }}
QFrame#Card:hover {{ border-color: #2E3646; background: {CARD_HOVER}; }}
QFrame#Panel {{ background: {PANEL}; border: 1px solid {BORDER_SOFT}; border-radius: 14px; }}
QFrame#Divider {{ background: {BORDER_SOFT}; max-height: 1px; border: none; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: #1A1F28; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 7px 10px; color: {TEXT}; selection-background-color: {GOLD_DARK};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {GOLD_DARK}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: none; }}
QComboBox QAbstractItemView {{
    background: #171B23; border: 1px solid {BORDER}; border-radius: 8px;
    selection-background-color: #2A3140; padding: 4px; color: {TEXT};
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 14px; background: transparent; border: none; }}

QSlider::groove:horizontal {{ height: 4px; background: #242A36; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {GOLD}; border-radius: 2px; }}
QSlider::add-page:horizontal {{ background: #242A36; border-radius: 2px; }}
QSlider::handle:horizontal {{
    width: 13px; height: 13px; margin: -5px 0; border-radius: 7px;
    background: {GOLD_LIGHT}; border: 2px solid #12151B;
}}
QSlider::handle:horizontal:hover {{ background: #FFDCA0; }}

QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2A303C; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #39404F; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QCheckBox {{ color: #C8D0DE; spacing: 8px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px; border-radius: 4px;
    border: 1px solid {BORDER}; background: #1A1F28;
}}
QCheckBox::indicator:checked {{ background: {GOLD}; border-color: {GOLD}; image: url(__CHECKICON__); }}
QListWidget::indicator {{ width: 15px; height: 15px; border-radius: 4px;
    border: 1px solid {BORDER}; background: #1A1F28; }}
QListWidget::indicator:checked {{ background: {GOLD}; border-color: {GOLD}; image: url(__CHECKICON__); }}
QListWidget {{
    background: #161A22; border: 1px solid {BORDER_SOFT}; border-radius: 10px;
    padding: 4px; color: {TEXT};
}}
QListWidget::item {{ padding: 7px 8px; border-radius: 6px; }}
QListWidget::item:selected {{ background: #2A3140; color: #FFF; }}
QListWidget::item:hover {{ background: #1F242E; }}

QMenu {{
    background: #171B23; border: 1px solid {BORDER}; border-radius: 10px; padding: 6px;
}}QMenu::item {{ padding: 7px 22px 7px 14px; border-radius: 6px; color: {TEXT}; }}
QMenu::item:selected {{ background: #2A3140; }}
QToolTip {{
    background: #1F2530; color: {TEXT}; border: 1px solid {BORDER};
    border-radius: 6px; padding: 5px 8px;
}}

QFrame#DialogRoot {{
    background: #12151C; border: 1px solid #2B3140; border-radius: 14px;
}}
QLabel#DialogTitle {{ font-size: 15px; font-weight: 600; color: #F1F4FA; }}
QPushButton#Close {{
    background: transparent; border: none; color: #7C8497;
    font-size: 15px; padding: 0px; border-radius: 7px;
}}
QPushButton#Close:hover {{ background: #242A36; color: #E8ECF3; }}
QLabel#FieldLabel {{ font-size: 12px; color: {TEXT_DIM}; }}
QLabel#Badge {{
    background: #1E242F; border-radius: 6px; padding: 3px 8px;
    font-size: 10.5px; color: {GOLD_LIGHT};
}}
"""


def _check_icon_path() -> str:
    """生成勾选标记图片（QSS 无法直接画对勾）。"""
    folder = CACHE_DIR / "ui"
    folder.mkdir(parents=True, exist_ok=True)
    png = folder / "check.png"
    if not png.is_file():
        pm = QPixmap(16, 16)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor("#191307"), 2.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        path = QPainterPath()
        path.moveTo(3.6, 8.6)
        path.lineTo(6.6, 11.6)
        path.lineTo(12.4, 4.6)
        p.drawPath(path)
        p.end()
        pm.save(str(png), "PNG")
    return png.as_posix()


def build_qss() -> str:
    """在 QApplication 创建之后调用：补上勾选图标路径。"""
    return QSS.replace("__CHECKICON__", _check_icon_path())


def make_app_icon(size: int = 128) -> QIcon:
    """画一个金色菱形徽记作为程序/托盘图标。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)

    s = size
    grad = QLinearGradient(0, 0, s, s)
    grad.setColorAt(0.0, QColor("#F7DC9E"))
    grad.setColorAt(0.45, QColor(GOLD))
    grad.setColorAt(1.0, QColor("#8C6520"))

    diamond = QPainterPath()
    diamond.moveTo(s * 0.5, s * 0.08)
    diamond.lineTo(s * 0.9, s * 0.5)
    diamond.lineTo(s * 0.5, s * 0.92)
    diamond.lineTo(s * 0.1, s * 0.5)
    diamond.closeSubpath()

    p.setPen(Qt.NoPen)
    p.setBrush(grad)
    p.drawPath(diamond)

    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(QColor(20, 16, 8, 170), s * 0.045))
    p.drawPath(diamond)

    inner = QPainterPath()
    inner.moveTo(s * 0.5, s * 0.28)
    inner.lineTo(s * 0.72, s * 0.5)
    inner.lineTo(s * 0.5, s * 0.72)
    inner.lineTo(s * 0.28, s * 0.5)
    inner.closeSubpath()
    p.setPen(QPen(QColor("#FFF4D6"), max(1.0, s * 0.035)))
    p.drawPath(inner)

    p.end()
    return QIcon(pm)


def font(size: int, weight: QFont.Weight = QFont.Normal) -> QFont:
    f = QFont("Microsoft YaHei UI", size)
    f.setWeight(weight)
    return f
