"""动画素材编辑对话框（带实时抠像预览）。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget)

from core.config import Animation
from core.keyer import ChromaKeyer, probe
from core.player import ClipPlayer

from . import theme
from .base_dialog import BaseDialog, field_label
from .widgets import SliderRow, ThumbWidget

KEY_MODES = [("绿幕抠像", "green"), ("蓝幕抠像", "blue"), ("不抠像（原样叠加）", "none")]


class AnimationDialog(BaseDialog):
    def __init__(self, anim: Animation, parent=None):
        super().__init__("编辑动画" if anim.id else "导入动画", width=920, parent=parent)
        self.anim = anim
        self._player: Optional[ClipPlayer] = None
        self.info = probe(anim.abs_path())
        self.keyer = ChromaKeyer.from_animation(anim)

        aspect = (self.info.width / self.info.height) if self.info and self.info.height else 16 / 9
        self._prev_w = 520
        self._prev_h = int(self._prev_w / aspect)

        content = QHBoxLayout()
        content.setSpacing(22)

        # ---------------- 左：预览
        left = QVBoxLayout()
        left.setSpacing(10)
        self.preview = ThumbWidget(radius=12)
        self.preview.setFixedSize(self._prev_w, self._prev_h)
        self.preview.set_hint("正在载入预览…")
        left.addWidget(self.preview, 0, Qt.AlignTop)

        meta = QLabel(self._meta_text())
        meta.setObjectName("Meta")
        left.addWidget(meta)
        left.addStretch(1)
        content.addLayout(left, 0)

        # ---------------- 右：参数
        right = QVBoxLayout()
        right.setSpacing(12)

        title = QLabel("素材名称")
        title.setObjectName("FieldLabel")
        right.addWidget(title)
        self.name_edit = QLineEdit(anim.name)
        right.addWidget(self.name_edit)

        mode_row = QHBoxLayout()
        mode_lbl = QLabel("背景")
        mode_lbl.setObjectName("FieldLabel")
        self.mode_box = QComboBox()
        for text, value in KEY_MODES:
            self.mode_box.addItem(text, value)
        idx = max(0, [m[1] for m in KEY_MODES].index(anim.key_mode)) if anim.key_mode in [
            m[1] for m in KEY_MODES] else 0
        self.mode_box.setCurrentIndex(idx)
        mode_row.addWidget(mode_lbl)
        mode_row.addWidget(self.mode_box, 1)
        right.addLayout(mode_row)

        right.addWidget(field_label("抠像参数"))

        self.sl_tolerance = SliderRow("容差", 0, 100, anim.tolerance)
        self.sl_softness = SliderRow("边缘羽化", 1, 60, anim.softness)
        self.sl_spill = SliderRow("去绿强度", 0, 100, int(anim.spill * 100))
        self.sl_shadow = SliderRow("阴影扣除", 0, 100, anim.shadow)
        for row in (self.sl_tolerance, self.sl_softness, self.sl_spill, self.sl_shadow):
            right.addWidget(row)

        trim_row = QHBoxLayout()
        trim_row.setSpacing(10)
        self.trim_start = QDoubleSpinBox()
        self.trim_start.setDecimals(2)
        self.trim_start.setSingleStep(0.1)
        self.trim_start.setSuffix(" 秒")
        self.trim_end = QDoubleSpinBox()
        self.trim_end.setDecimals(2)
        self.trim_end.setSingleStep(0.1)
        self.trim_end.setSuffix(" 秒")
        dur = self.info.duration if self.info else 10.0
        for box in (self.trim_start, self.trim_end):
            box.setRange(0.0, max(0.0, dur))
            box.setFixedWidth(92)
        self.trim_start.setValue(anim.trim_start)
        self.trim_end.setValue(anim.trim_end)
        trim_row.addWidget(field_label("掐头"))
        trim_row.addWidget(self.trim_start)
        trim_row.addSpacing(8)
        trim_row.addWidget(field_label("去尾"))
        trim_row.addWidget(self.trim_end)
        trim_row.addStretch(1)
        right.addLayout(trim_row)

        self.chk_loop = QCheckBox("循环播放（否则只播一遍）")
        self.chk_loop.setChecked(anim.loop)
        self.chk_muted = QCheckBox("静音（不播放素材声音）")
        self.chk_muted.setChecked(anim.muted)
        right.addWidget(self.chk_loop)
        right.addWidget(self.chk_muted)

        # ---------------- 光波扩散
        right.addSpacing(2)
        right.addWidget(field_label("光波扩散"))
        self.chk_burst = QCheckBox("发射光波时扩散到整个屏幕")
        self.chk_burst.setChecked(bool((anim.burst or {}).get("enabled")))
        right.addWidget(self.chk_burst)

        burst_row = QHBoxLayout()
        burst_row.setSpacing(8)
        self.burst_info = QLabel("")
        self.burst_info.setObjectName("Meta")
        self.burst_btn = QPushButton("重新检测")
        self.burst_btn.setObjectName("Link")
        self.burst_btn.clicked.connect(self._detect_burst)
        burst_row.addWidget(self.burst_info, 1)
        burst_row.addWidget(self.burst_btn)
        right.addLayout(burst_row)
        self._update_burst_info()

        right.addStretch(1)
        content.addLayout(right, 1)
        self.body.addLayout(content)

        # ---------------- 底部按钮
        footer = QHBoxLayout()
        self.reset_btn = QPushButton("恢复默认抠像")
        self.reset_btn.setObjectName("Link")
        self.reset_btn.clicked.connect(self._reset_key)
        cancel = QPushButton("取消")
        cancel.setObjectName("Ghost")
        cancel.clicked.connect(self.reject)
        self.ok_btn = QPushButton("保存")
        self.ok_btn.setObjectName("Primary")
        self.ok_btn.clicked.connect(self._on_ok)
        footer.addWidget(self.reset_btn)
        footer.addStretch(1)
        footer.addWidget(cancel)
        footer.addWidget(self.ok_btn)
        self.body.addLayout(footer)

        # ---------------- 连接
        self.mode_box.currentIndexChanged.connect(self._on_mode)
        self.sl_tolerance.valueChanged.connect(lambda v: self._tune(tolerance=v))
        self.sl_softness.valueChanged.connect(lambda v: self._tune(softness=v))
        self.sl_spill.valueChanged.connect(lambda v: self._tune(spill=v / 100))
        self.sl_shadow.valueChanged.connect(lambda v: self._tune(shadow=v))
        self.trim_start.valueChanged.connect(self._restart_preview)
        self.trim_end.valueChanged.connect(self._restart_preview)

        QTimer.singleShot(60, self._restart_preview)

    # ------------------------------------------------------------ 预览
    def _meta_text(self) -> str:
        if not self.info:
            return f"{Path(self.anim.path).name}"
        return (f"{self.info.width}×{self.info.height} · "
                f"{self.info.duration:.1f}s · {self.info.fps:.0f}fps · "
                f"{Path(self.anim.abs_path()).name}")

    def _restart_preview(self) -> None:
        self._stop_player()
        if not self.anim.exists():
            self.preview.set_hint("文件不存在")
            return
        self._player = ClipPlayer(
            str(self.anim.abs_path()), self.keyer,
            (self._prev_w, self._prev_h),
            float(self.trim_start.value()), float(self.trim_end.value()),
            loop=True, parent=self,
        )
        self._player.frameReady.connect(lambda img, _t: self.preview.set_image(img))
        self._player.start()

    def _stop_player(self) -> None:
        if self._player:
            try:
                self._player.frameReady.disconnect()
            except (RuntimeError, TypeError):
                pass
            self._player.stop()
            self._player.wait(1200)
            self._player = None

    def _tune(self, **kwargs) -> None:
        if self._player:
            self.keyer.tune(**kwargs)

    def _on_mode(self) -> None:
        if self._player:
            self.keyer.tune(mode=self.mode_box.currentData())

    def _reset_key(self) -> None:
        default = Animation()
        self.keyer.tune(mode=default.key_mode, tolerance=default.tolerance,
                        softness=default.softness, spill=default.spill,
                        shadow=default.shadow)
        self.sl_tolerance.setValue(default.tolerance)
        self.sl_softness.setValue(default.softness)
        self.sl_spill.setValue(int(default.spill * 100))
        self.sl_shadow.setValue(default.shadow)
        self.mode_box.setCurrentIndex(0)

    # ------------------------------------------------------------ 光波
    def _update_burst_info(self) -> None:
        b = self.anim.burst or {}
        if b.get("enabled") and b.get("curve"):
            self.burst_info.setText(
                f"检测到光波：{b.get('start', 0):.2f}s – {b.get('end', 0):.2f}s，"
                f"扩散速度 {b.get('speed', 0):.1f}/秒")
        else:
            self.burst_info.setText("没有检测到向外扩散的光波（可手动重试）")

    def _detect_burst(self) -> None:
        from core import burst as burst_mod

        if not self.anim.exists():
            return
        self.burst_btn.setEnabled(False)
        self.burst_btn.setText("检测中…")
        self.burst_info.setText("正在扫描画面里的光波…")
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        try:
            info = burst_mod.detect(str(self.anim.abs_path()), self.keyer)
        except Exception as exc:                      # 素材异常时不要让对话框崩
            info = {}
            self.burst_info.setText(f"检测失败：{exc}")
        self.anim.burst = info or {}
        self.chk_burst.setChecked(bool(self.anim.burst.get("enabled")))
        self.burst_btn.setEnabled(True)
        self.burst_btn.setText("重新检测")
        self._update_burst_info()

    # ------------------------------------------------------------ 保存
    def _on_ok(self) -> None:
        a = self.anim
        a.name = self.name_edit.text().strip() or Path(a.path).stem
        a.key_mode = self.mode_box.currentData()
        a.tolerance = self.sl_tolerance.value()
        a.softness = self.sl_softness.value()
        a.spill = self.sl_spill.value() / 100
        a.shadow = self.sl_shadow.value()
        a.trim_start = float(self.trim_start.value())
        a.trim_end = float(self.trim_end.value())
        a.loop = self.chk_loop.isChecked()
        a.muted = self.chk_muted.isChecked()
        if a.burst:
            a.burst["enabled"] = self.chk_burst.isChecked()
        self.accept()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._stop_player()
        super().closeEvent(event)

    def reject(self) -> None:  # noqa: D102
        self._stop_player()
        super().reject()
