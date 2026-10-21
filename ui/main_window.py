"""主窗口：动画库、触发规则、设置。"""
from __future__ import annotations

import os
import random
import sys
import time
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox,
                               QDoubleSpinBox, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu,
                               QMessageBox, QPushButton, QScrollArea, QSizePolicy,
                               QSpinBox, QStackedWidget, QSystemTrayIcon, QVBoxLayout,
                               QWidget)

from core.config import APP_DIR, ASSETS_DIR, Animation, Config, Rule, human_duration
from core.keyer import probe
from core.triggers import ProcessWatcher

from . import theme
from .anim_dialog import AnimationDialog
from .base_dialog import BaseDialog
from .overlay import OverlayWindow
from .rule_dialog import RuleDialog
from .thumbs import thumb_pixmap
from .widgets import Card, FormRow, SectionCard, SliderRow, Switch, ThumbWidget

VIDEO_FILTER = "视频素材 (*.mp4 *.mov *.webm *.mkv *.avi *.gif *.m4v);;所有文件 (*.*)"
KEY_LABEL = {"green": "绿幕", "blue": "蓝幕", "none": "不抠像"}


def _apply_dark_titlebar(widget: QWidget) -> None:
    """让 Windows 原生标题栏跟随暗色主题。"""
    try:
        import ctypes

        hwnd = int(widget.winId())
        value = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE（新旧版本取值不同）
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


# ================================================================ 小组件
class Toast(QLabel):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setStyleSheet(
            "background: rgba(30,36,47,235); color: #E9ECF3; border-radius: 9px;"
            "padding: 9px 16px; font-size: 12.5px; border: 1px solid #2E3646;"
        )
        self.hide()

    def show_message(self, text: str, ms: int = 2200) -> None:
        self.setText(text)
        self.adjustSize()
        parent = self.parentWidget()
        self.move((parent.width() - self.width()) // 2, parent.height() - self.height() - 28)
        self.show()
        self.raise_()
        QTimer.singleShot(ms, self.hide)


class AnimationCard(Card):
    def __init__(self, anim: Animation, page: "AnimationsPage"):
        super().__init__(page)
        self.anim = anim
        self.page = page
        self.setFixedWidth(252)
        self.setFixedHeight(262)
        self.setCursor(Qt.PointingHandCursor)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(7)

        self.thumb = ThumbWidget(radius=10)
        self.thumb.setFixedHeight(124)
        pm = thumb_pixmap(anim, 380)
        if not pm.isNull():
            self.thumb.set_image(pm.toImage())
        else:
            self.thumb.set_hint("素材缺失")
        lay.addWidget(self.thumb)

        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        name = QLabel(anim.name)
        name.setObjectName("CardName")
        name.setToolTip(anim.name)
        name.setTextInteractionFlags(Qt.NoTextInteraction)
        badge = QLabel(KEY_LABEL.get(anim.key_mode, "抠像"))
        badge.setObjectName("Badge")
        name_row.addWidget(name, 1)
        name_row.addWidget(badge, 0, Qt.AlignRight)
        lay.addLayout(name_row)

        info = probe(anim.abs_path())
        meta_text = (f"{info.width}×{info.height} · {human_duration(info.duration)}"
                     if info else "文件缺失")
        meta = QLabel(meta_text)
        meta.setObjectName("Meta")
        lay.addWidget(meta)

        bound = [Path(r.exe).name for r in page.config.rules
                 if anim.id in r.animation_ids and r.enabled]
        if bound:
            names = "、".join(bound[:2]) + (f" 等 {len(bound)} 个" if len(bound) > 2 else "")
            prog_text = f"▶ {names}"
        else:
            prog_text = "▶ 尚未绑定程序"
        prog = QLabel(prog_text)
        prog.setObjectName("Hint")
        prog.setStyleSheet("color: #8A93A6;" if bound else "color: #5D6474;")
        prog.setToolTip("、".join(bound) if bound else "到「触发规则」里把这段动画绑定到程序")
        lay.addWidget(prog)

        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        play_btn = QPushButton("预览")
        play_btn.setObjectName("Link")
        play_btn.clicked.connect(lambda: page.preview(anim))
        edit_btn = QPushButton("编辑")
        edit_btn.setObjectName("Link")
        edit_btn.clicked.connect(lambda: page.edit(anim))
        del_btn = QPushButton("删除")
        del_btn.setObjectName("Danger")
        del_btn.clicked.connect(lambda: page.remove(anim))
        buttons.addWidget(play_btn)
        buttons.addWidget(edit_btn)
        buttons.addStretch(1)
        buttons.addWidget(del_btn)
        lay.addLayout(buttons)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.page.preview(self.anim)


class RuleRow(Card):
    def __init__(self, rule: Rule, page: "RulesPage"):
        super().__init__(page)
        self.rule = rule
        self.page = page
        self.setFixedHeight(76)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 16, 12)
        lay.setSpacing(14)

        first: Optional[Animation] = page.config.get_animation(rule.animation_ids[0]) if rule.animation_ids else None
        thumb = ThumbWidget(radius=8)
        thumb.setFixedSize(76, 46)
        if first:
            pm = thumb_pixmap(first, 160)
            if not pm.isNull():
                thumb.set_image(pm.toImage())
        lay.addWidget(thumb)

        text = QVBoxLayout()
        text.setSpacing(3)
        title = QLabel(Path(rule.exe).name)
        title.setObjectName("CardName")
        title.setToolTip(rule.exe)
        names = [page.config.get_animation(i).name for i in rule.animation_ids
                 if page.config.get_animation(i)]
        sub = QLabel(" · ".join(names) if names else "未指定动画")
        sub.setObjectName("Meta")
        detail = QLabel(f"延迟 {rule.delay_ms} ms · 冷却 {rule.cooldown}s"
                        + ("" if rule.match == "name" else " · 路径匹配"))
        detail.setObjectName("Meta")
        text.addWidget(title)
        text.addWidget(sub)
        text.addWidget(detail)
        lay.addLayout(text, 1)

        switch = Switch(rule.enabled)
        switch.toggled.connect(lambda v: page.toggle(rule, v))
        lay.addWidget(switch, 0, Qt.AlignVCenter)

        edit = QPushButton("编辑")
        edit.setObjectName("Link")
        edit.clicked.connect(lambda: page.edit(rule))
        remove = QPushButton("删除")
        remove.setObjectName("Danger")
        remove.clicked.connect(lambda: page.remove(rule))
        lay.addWidget(edit)
        lay.addWidget(remove)


# ================================================================ 页面：动画库
class AnimationsPage(QWidget):
    def __init__(self, main: "MainWindow"):
        super().__init__()
        self.main = main
        self.setObjectName("Page")
        self.setAcceptDrops(True)
        self.config = main.config

        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 26, 30, 20)
        outer.setSpacing(18)

        head = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(4)
        title = QLabel("动画库")
        title.setObjectName("PageTitle")
        desc = QLabel("导入任意视频素材，启动器会实时抠掉绿幕/蓝幕并以透明叠加层播放")
        desc.setObjectName("PageDesc")
        title_box.addWidget(title)
        title_box.addWidget(desc)
        head.addLayout(title_box, 1)
        add_btn = QPushButton("＋  导入动画")
        add_btn.setObjectName("Primary")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self.import_files)
        head.addWidget(add_btn, 0, Qt.AlignTop)
        outer.addLayout(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.container = QWidget()
        self.container.setObjectName("Page")
        self.grid = QGridLayout(self.container)
        self.grid.setContentsMargins(0, 0, 6, 0)
        self.grid.setSpacing(16)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll.setWidget(self.container)
        outer.addWidget(self.scroll, 1)

        self.empty = QWidget()
        e_lay = QVBoxLayout(self.empty)
        e_lay.setAlignment(Qt.AlignCenter)
        e_tip = QLabel("还没有动画素材")
        e_tip.setAlignment(Qt.AlignCenter)
        e_tip.setStyleSheet("font-size: 14px; color: #7A8296;")
        e_sub = QLabel("点击右上角「导入动画」，或把视频文件拖进来")
        e_sub.setAlignment(Qt.AlignCenter)
        e_sub.setObjectName("Meta")
        e_lay.addWidget(e_tip)
        e_lay.addWidget(e_sub)
        outer.addWidget(self.empty, 1)

        self.refresh()

    def refresh(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        anims = self.config.animations
        self.scroll.setVisible(bool(anims))
        self.empty.setVisible(not anims)
        cols = 3
        for i, anim in enumerate(anims):
            self.grid.addWidget(AnimationCard(anim, self), i // cols, i % cols)
        self.grid.setColumnStretch(cols, 1)

    # ------------------------------------------------------------ 操作
    def import_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "选择动画素材", "", VIDEO_FILTER)
        if files:
            self.import_paths([Path(f) for f in files])

    def import_paths(self, paths: List[Path]) -> None:
        from core import burst as burst_mod
        from core.keyer import detect_key_mode, detect_trim

        added, failed = 0, []
        todo: List[Animation] = []
        for src in paths:
            if not src.is_file():
                continue
            anim = self.config.add_animation(src, name=src.stem)
            if probe(anim.abs_path()) is None:
                self.config.remove_animation(anim.id)
                failed.append(src.name)
                continue
            anim.key_mode = detect_key_mode(anim.abs_path())
            anim.trim_start, anim.trim_end = detect_trim(anim.abs_path())
            todo.append(anim)
            added += 1
        self.config.save()
        if todo:
            self.main.toast("正在分析素材里的光波…")
            QApplication.processEvents()
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                for anim in todo:
                    anim.burst = burst_mod.detect(str(anim.abs_path()), None)
                    # 自动裁剪可能把光波那一段剪掉，那样就永远看不到扩散了
                    b = anim.burst or {}
                    info = probe(anim.abs_path()) if b.get("enabled") else None
                    if info and info.duration > 0 and b.get("end"):
                        head = anim.trim_start
                        if b["end"] > info.duration - anim.trim_end - 0.25:
                            anim.trim_end = max(0.0, round(info.duration - b["end"] - 0.3, 2))
                        if b["end"] < head:
                            anim.trim_start = 0.0
            finally:
                QApplication.restoreOverrideCursor()
            self.config.save()
        self.refresh()
        self.main.refresh_rules_page()
        if added:
            self.main.toast(f"已导入 {added} 段动画，记得去「触发规则」绑定程序")
        if failed:
            self.main.toast(f"无法识别：{'、'.join(failed[:2])}")

    def preview(self, anim: Animation) -> None:
        self.main.overlay.play_animations([anim])

    def edit(self, anim: Animation) -> None:
        dlg = AnimationDialog(anim, self)
        if dlg.exec():
            self.config.save()
            self.refresh()
            self.main.refresh_rules_page()
            self.main.toast("已保存")

    def remove(self, anim: Animation) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("删除动画")
        box.setText(f"确定删除「{anim.name}」吗？\n引用它的触发规则也会一并移除该动画。")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.button(QMessageBox.Yes).setText("删除")
        box.button(QMessageBox.No).setText("取消")
        if box.exec() == QMessageBox.Yes:
            self.config.remove_animation(anim.id)
            self.refresh()
            self.main.refresh_rules_page()
            self.main.toast("已删除")

    # 拖放导入
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        files = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if files:
            self.import_paths(files)


# ================================================================ 页面：规则
class RulesPage(QWidget):
    def __init__(self, main: "MainWindow"):
        super().__init__()
        self.main = main
        self.setObjectName("Page")
        self.config = main.config

        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 26, 30, 20)
        outer.setSpacing(18)

        head = QHBoxLayout()
        box = QVBoxLayout()
        box.setSpacing(4)
        title = QLabel("触发规则")
        title.setObjectName("PageTitle")
        desc = QLabel("指定「哪些程序启动时」播放「哪段动画」，同一个程序可以绑定多段动画")
        desc.setObjectName("PageDesc")
        box.addWidget(title)
        box.addWidget(desc)
        head.addLayout(box, 1)
        add_btn = QPushButton("＋  新建规则")
        add_btn.setObjectName("Primary")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self.create)
        head.addWidget(add_btn, 0, Qt.AlignTop)
        outer.addLayout(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.container = QWidget()
        self.container.setObjectName("Page")
        self.list_lay = QVBoxLayout(self.container)
        self.list_lay.setContentsMargins(0, 0, 6, 0)
        self.list_lay.setSpacing(10)
        self.list_lay.addStretch(1)
        self.scroll.setWidget(self.container)
        outer.addWidget(self.scroll, 1)

        self.empty = QWidget()
        e_lay = QVBoxLayout(self.empty)
        e_lay.setAlignment(Qt.AlignCenter)
        e_lay.setSpacing(10)
        e_tip = QLabel("还没有触发规则")
        e_tip.setAlignment(Qt.AlignCenter)
        e_tip.setStyleSheet("font-size: 15px; color: #8A92A6; font-weight: 600;")
        e_sub = QLabel("每条规则 = 一个程序 + 一段（或多段）动画\n例如「chrome.exe 启动时播放 起司的金枝共鸣」")
        e_sub.setAlignment(Qt.AlignCenter)
        e_sub.setObjectName("Meta")
        cta = QPushButton("＋  新建第一条规则")
        cta.setObjectName("Ghost")
        cta.setCursor(Qt.PointingHandCursor)
        cta.clicked.connect(self.create)
        wrap = QHBoxLayout()
        wrap.addStretch(1)
        wrap.addWidget(cta)
        wrap.addStretch(1)
        e_lay.addWidget(e_tip)
        e_lay.addWidget(e_sub)
        e_lay.addSpacing(6)
        e_lay.addLayout(wrap)
        outer.addWidget(self.empty, 1)

        self.refresh()

    def refresh(self) -> None:
        while self.list_lay.count() > 1:
            item = self.list_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        rules = self.config.rules
        self.scroll.setVisible(bool(rules))
        self.empty.setVisible(not rules)
        for rule in rules:
            self.list_lay.insertWidget(self.list_lay.count() - 1, RuleRow(rule, self))

    # ------------------------------------------------------------ 操作
    def create(self) -> None:
        if not self.config.animations:
            self.main.toast("先导入动画素材，再创建规则")
            return
        rule = Rule()
        rule.cooldown = int(self.config.settings.get("default_cooldown", 10))
        dlg = RuleDialog(rule, self.config, self)
        if dlg.exec():
            self.config.add_rule(rule)
            self.refresh()
            self.main.update_status()
            self.main.toast("规则已创建")

    def edit(self, rule: Rule) -> None:
        dlg = RuleDialog(rule, self.config, self)
        if dlg.exec():
            self.config.save()
            self.refresh()
            self.main.toast("已保存")

    def toggle(self, rule: Rule, enabled: bool) -> None:
        rule.enabled = enabled
        self.config.save()

    def remove(self, rule: Rule) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("删除规则")
        box.setText(f"确定删除规则「{Path(rule.exe).name}」吗？")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.button(QMessageBox.Yes).setText("删除")
        box.button(QMessageBox.No).setText("取消")
        if box.exec() == QMessageBox.Yes:
            self.config.remove_rule(rule.id)
            self.refresh()
            self.main.update_status()


# ================================================================ 页面：设置
class SettingsPage(QWidget):
    def __init__(self, main: "MainWindow"):
        super().__init__()
        self.main = main
        self.config = main.config
        self.setObjectName("Page")
        s = self.config.settings

        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 26, 30, 20)
        outer.setSpacing(16)

        title = QLabel("设置")
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        holder.setObjectName("Page")
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(14)

        # --- 播放
        play = SectionCard("播放")
        self.pos_box = QComboBox()
        for text, val in [("右下角", "bottom-right"), ("左下角", "bottom-left"),
                          ("底部居中", "bottom-center"), ("屏幕中央", "center"),
                          ("右上角", "top-right"), ("左上角", "top-left"),
                          ("自定义（拖拽叠加层）", "custom")]:
            self.pos_box.addItem(text, val)
        self.pos_box.setCurrentIndex(self._index_of(self.pos_box, s.get("pos_preset", "bottom-right")))
        self.pos_box.currentIndexChanged.connect(lambda: self._set("pos_preset", self.pos_box.currentData()))
        play.add(FormRow("播放位置", self.pos_box, "选「自定义」后可解锁叠加层并直接拖动"))

        self.screen_box = QComboBox()
        self.screen_box.setMinimumWidth(250)
        self._refresh_screens()
        self.screen_box.currentIndexChanged.connect(lambda: self._set("screen_index", self.screen_box.currentData()))
        play.add(FormRow("显示器", self.screen_box))

        self.ref_box = QComboBox()
        self.ref_box.addItem("屏幕（按显示器高度自适应）", "screen")
        self.ref_box.addItem("目标程序窗口（跟随它自己的分辨率）", "window")
        self.ref_box.addItem("固定像素（不随分辨率变化）", "fixed")
        self.ref_box.setCurrentIndex(self._index_of(self.ref_box, s.get("size_ref", "screen")))
        self.ref_box.currentIndexChanged.connect(self._on_size_ref)
        play.add(FormRow("尺寸参照", self.ref_box,
                         "选「目标程序窗口」时，窗口多大动画就占它高度的百分比，游戏改分辨率也能跟着变"))

        self.size_slider = SliderRow("画面高度", 5, 100, int(s.get("height_percent", 42)), "%")
        self.size_slider.valueChanged.connect(lambda v: self._set("height_percent", v))
        play.add(self.size_slider)

        self.fixed_spin = QSpinBox()
        self.fixed_spin.setRange(40, 2160)
        self.fixed_spin.setSuffix(" px")
        self.fixed_spin.setValue(int(s.get("fixed_height", 300)))
        self.fixed_spin.valueChanged.connect(lambda v: self._set("fixed_height", v))
        self.fixed_row = FormRow("固定高度", self.fixed_spin, "固定像素模式下动画的高度")
        play.add(self.fixed_row)
        self.fixed_row.setVisible(s.get("size_ref", "screen") == "fixed")
        self.size_slider.setVisible(s.get("size_ref", "screen") != "fixed")

        self.margin_spin = QSpinBox()
        self.margin_spin.setRange(0, 400)
        self.margin_spin.setSuffix(" px")
        self.margin_spin.setValue(int(s.get("margin", 28)))
        self.margin_spin.valueChanged.connect(lambda v: self._set("margin", v))
        play.add(FormRow("贴边距离", self.margin_spin, "画面与参照边缘的距离，自动按 DPI 缩放"))

        self.sw_top = Switch(bool(s.get("always_on_top", True)))
        self.sw_top.toggled.connect(lambda v: self._set("always_on_top", v))
        play.add(FormRow("总在最前", self.sw_top, "叠在其他窗口之上，不会被遮挡"))

        self.sw_click = Switch(bool(s.get("click_through", True)))
        self.sw_click.toggled.connect(lambda v: self._set("click_through", v))
        play.add(FormRow("鼠标穿透", self.sw_click, "开启后点击会落在下面的窗口；关闭后可拖动叠加层"))

        self.sw_sound = Switch(bool(s.get("play_sound", False)))
        self.sw_sound.toggled.connect(lambda v: self._set("play_sound", v))
        play.add(FormRow("播放素材声音", self.sw_sound, "默认静音，避免突然出声"))

        # --- 触发
        trig = SectionCard("触发")
        self.sw_enabled = Switch(bool(s.get("enabled", True)))
        self.sw_enabled.toggled.connect(self._on_enabled)
        trig.add(FormRow("启用程序监听", self.sw_enabled, "关闭后只保留手动预览"))

        self.poll_box = QComboBox()
        for ms in (300, 500, 700, 1000, 1500):
            self.poll_box.addItem(f"{ms} 毫秒", ms)
        idx = [self.poll_box.itemData(i) for i in range(self.poll_box.count())].index(
            int(s.get("poll_ms", 700))) if int(s.get("poll_ms", 700)) in [
            self.poll_box.itemData(i) for i in range(self.poll_box.count())] else 2
        self.poll_box.setCurrentIndex(idx)
        self.poll_box.currentIndexChanged.connect(self._on_poll)
        trig.add(FormRow("检测间隔", self.poll_box, "越短越灵敏，但会略微占用 CPU"))

        self.cool_spin = QSpinBox()
        self.cool_spin.setRange(1, 3600)
        self.cool_spin.setSuffix(" 秒")
        self.cool_spin.setValue(int(s.get("default_cooldown", 10)))
        self.cool_spin.valueChanged.connect(lambda v: self._set("default_cooldown", v))
        trig.add(FormRow("默认冷却时间", self.cool_spin, "新建规则时的默认值，防止同一次启动重复播放"))

        self.queue_box = QComboBox()
        self.queue_box.addItem("按规则里的顺序依次播放", "sequence")
        self.queue_box.addItem("随机挑一段播放", "random")
        self.queue_box.setCurrentIndex(0 if s.get("queue_mode", "sequence") == "sequence" else 1)
        self.queue_box.currentIndexChanged.connect(lambda: self._set("queue_mode", self.queue_box.currentData()))
        trig.add(FormRow("同一程序多段动画", self.queue_box))

        self.sw_skip = Switch(bool(s.get("skip_if_running", True)))
        self.sw_skip.toggled.connect(lambda v: self._set("skip_if_running", v))
        trig.add(FormRow("程序已在运行时忽略子进程", self.sw_skip,
                         "浏览器、更新器会不断派生同名进程，开启后只在真正启动时触发"))

        # --- 其他
        other = SectionCard("其他")
        self.sw_auto = Switch(bool(s.get("autostart", False)))
        self.sw_auto.toggled.connect(self._on_autostart)
        other.add(FormRow("开机自启", self.sw_auto, "登录 Windows 后自动在后台待命"))

        open_btn = QPushButton("打开素材文件夹")
        open_btn.setObjectName("Ghost")
        open_btn.clicked.connect(self._open_assets)
        other.add(FormRow("素材库", open_btn, "导入的素材会复制到 assets 目录"))

        about = QLabel("金枝共鸣 · 启动器 v1.0　|　实时色度抠像 + 屏幕叠加层，素材与配置都在本地")
        about.setObjectName("Meta")
        other.add(about)

        lay.addWidget(play)
        lay.addWidget(trig)
        lay.addWidget(other)
        lay.addStretch(1)
        scroll.setWidget(holder)
        outer.addWidget(scroll, 1)

    # ------------------------------------------------------------ 设置写入
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._refresh_screens()

    def _refresh_screens(self) -> None:
        """每次打开设置页都重新读一遍显示器，分辨率和缩放变了也能看准。"""
        cur = int(self.config.settings.get("screen_index", 0) or 0)
        self.screen_box.blockSignals(True)
        self.screen_box.clear()
        for i, scr in enumerate(QGuiApplication.screens()):
            g = scr.geometry()
            dpr = scr.devicePixelRatio() or 1.0
            phys_w, phys_h = int(round(g.width() * dpr)), int(round(g.height() * dpr))
            text = f"屏幕 {i + 1}（{phys_w}×{phys_h}"
            text += f" · 缩放 {int(round(dpr * 100))}%）" if abs(dpr - 1.0) > 0.01 else "）"
            self.screen_box.addItem(text, i)
        self.screen_box.setCurrentIndex(min(cur, max(0, self.screen_box.count() - 1)))
        self.screen_box.blockSignals(False)

    @staticmethod
    def _index_of(combo: QComboBox, value) -> int:
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                return i
        return 0

    def _set(self, key: str, value) -> None:
        self.config.settings[key] = value
        self.config.save()
        self.main.apply_settings()

    def _on_size_ref(self) -> None:
        ref = self.ref_box.currentData()
        self.config.settings["size_ref"] = ref
        self.config.save()
        self.size_slider.setVisible(ref != "fixed")
        self.fixed_row.setVisible(ref == "fixed")
        self.main.apply_settings()

    def _on_enabled(self, value: bool) -> None:
        self.config.settings["enabled"] = value
        self.config.save()
        if value:
            self.main.start_watcher()
        else:
            self.main.stop_watcher()

    def _on_poll(self) -> None:
        ms = self.poll_box.currentData()
        self.config.settings["poll_ms"] = ms
        self.config.save()
        self.main.watcher.set_interval(ms)

    def _on_autostart(self, value: bool) -> None:
        ok = self.main.set_autostart(value)
        self.config.settings["autostart"] = bool(value) if ok else False
        self.config.save()
        if value and not ok:
            self.sw_auto.setChecked(False)
            self.main.toast("写入开机自启失败，请检查权限")

    def _open_assets(self) -> None:
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(ASSETS_DIR))  # noqa: S606


# ================================================================ 主窗口
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = Config()
        self.setWindowTitle("金枝共鸣 · 启动器")
        self.setWindowIcon(theme.make_app_icon(128))
        self.resize(1120, 748)
        self.setMinimumSize(940, 640)

        self.overlay = OverlayWindow(self.config)
        self.watcher = ProcessWatcher(self.config)
        self.watcher.ruleFired.connect(self._on_rule_fired)
        self.watcher.statusChanged.connect(lambda _: self.update_status())

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        lay.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        self.anims_page = AnimationsPage(self)
        self.rules_page = RulesPage(self)
        self.settings_page = SettingsPage(self)
        self.stack.addWidget(self.anims_page)
        self.stack.addWidget(self.rules_page)
        self.stack.addWidget(self.settings_page)
        lay.addWidget(self.stack, 1)

        self.toast_label = Toast(root)
        self._build_tray()

        self.nav_buttons[0].setChecked(True)
        self.stack.setCurrentIndex(0)
        self.update_status()

        if self.config.settings.get("enabled", True):
            self.start_watcher()
        QTimer.singleShot(400, self._first_run_hint)
        self._close_hint_shown = False

    # ------------------------------------------------------------ 侧边栏
    def _build_sidebar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("Sidebar")
        bar.setFixedWidth(226)
        lay = QVBoxLayout(bar)
        lay.setContentsMargins(16, 22, 16, 16)
        lay.setSpacing(6)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(theme.make_app_icon(64).pixmap(38, 38))
        names = QVBoxLayout()
        names.setSpacing(0)
        n1 = QLabel("金枝共鸣")
        n1.setObjectName("AppName")
        n2 = QLabel("LAUNCHER")
        n2.setObjectName("AppSub")
        names.addWidget(n1)
        names.addWidget(n2)
        brand.addWidget(logo)
        brand.addLayout(names, 1)
        lay.addLayout(brand)
        lay.addSpacing(22)

        self.nav_buttons: List[QPushButton] = []
        group = QButtonGroup(self)
        group.setExclusive(True)
        for i, (text, icon) in enumerate([("◈   动画库", 0), ("⌁   触发规则", 1), ("⚙   设置", 2)]):
            btn = QPushButton(text)
            btn.setObjectName("Nav")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(40)
            btn.clicked.connect(lambda _=False, idx=i: self._switch(idx))
            group.addButton(btn)
            self.nav_buttons.append(btn)
            lay.addWidget(btn)

        lay.addStretch(1)

        self.status_box = QFrame()
        self.status_box.setStyleSheet(
            "background: #151A22; border: 1px solid #1F252F; border-radius: 11px;")
        sb = QVBoxLayout(self.status_box)
        sb.setContentsMargins(12, 10, 12, 11)
        sb.setSpacing(3)
        row = QHBoxLayout()
        row.setSpacing(7)
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet("color: #4ADE80; font-size: 10px;")
        self.status_text = QLabel("监听中")
        self.status_text.setStyleSheet("font-size: 12.5px; color: #DDE3ED;")
        row.addWidget(self.status_dot)
        row.addWidget(self.status_text)
        row.addStretch(1)
        sb.addLayout(row)
        self.status_sub = QLabel("2 条规则")
        self.status_sub.setObjectName("Meta")
        sb.addWidget(self.status_sub)
        lay.addWidget(self.status_box)
        lay.addSpacing(10)

        test = QPushButton("▶   测试播放")
        test.setObjectName("Ghost")
        test.setCursor(Qt.PointingHandCursor)
        test.clicked.connect(self._test_play)
        lay.addWidget(test)
        return bar

    def _switch(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)
        if index == 1:
            self.rules_page.refresh()

    # ------------------------------------------------------------ 托盘
    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(theme.make_app_icon(64), self)
        self.tray.setToolTip("金枝共鸣 · 启动器")
        menu = QMenu()
        act_open = QAction("打开主界面", self)
        act_open.triggered.connect(self._show_window)
        self.act_toggle = QAction("暂停监听", self)
        self.act_toggle.triggered.connect(self._toggle_watch)
        act_stop = QAction("停止播放", self)
        act_stop.triggered.connect(lambda: self.overlay.stop())
        act_quit = QAction("退出", self)
        act_quit.triggered.connect(self._quit)
        menu.addAction(act_open)
        menu.addSeparator()
        menu.addAction(self.act_toggle)
        menu.addAction(act_stop)
        menu.addSeparator()
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self._show_window() if reason == QSystemTrayIcon.DoubleClick else None)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def _show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit(self) -> None:
        self.overlay.stop()
        self.watcher.stop()
        self.tray.hide()
        QApplication.instance().quit()

    # ------------------------------------------------------------ 监听
    def start_watcher(self) -> None:
        self.watcher.start()
        self.update_status()

    def stop_watcher(self) -> None:
        self.watcher.stop()
        self.update_status()

    def _toggle_watch(self) -> None:
        if self.watcher.active:
            self.stop_watcher()
        else:
            self.start_watcher()
        self.settings_page.sw_enabled.setChecked(self.watcher.active)

    def _on_rule_fired(self, rule: Rule, pid: int = 0) -> None:
        anims: List[Animation] = [a for a in (self.config.get_animation(i) for i in rule.animation_ids) if a]
        anims = [a for a in anims if a.exists()]
        if not anims:
            return
        if self.config.settings.get("queue_mode") == "random":
            anims = [random.choice(anims)]
        delay = max(0, rule.delay_ms)
        QTimer.singleShot(delay, lambda: self.overlay.play_animations(anims, target_pid=pid))
        self.status_sub.setText(f"刚刚触发：{Path(rule.exe).name}")
        QTimer.singleShot(6000, self.update_status)

    def _test_play(self) -> None:
        anim = self.config.animations[0] if self.config.animations else None
        if not anim:
            self.toast("还没有动画，先导入一段素材")
            return
        self.overlay.play_animations([anim])

    def update_status(self) -> None:
        active = self.watcher.active
        self.status_text.setText("监听中" if active else "已暂停")
        self.status_dot.setStyleSheet(f"color: {theme.GREEN if active else '#7A8296'}; font-size: 10px;")
        n = len([r for r in self.config.rules if r.enabled])
        if self.status_sub.text().startswith("刚刚触发"):
            pass
        else:
            self.status_sub.setText(f"{n} 条规则启用中")
        self.act_toggle.setText("暂停监听" if active else "恢复监听")

    def refresh_rules_page(self) -> None:
        self.rules_page.refresh()
        self.update_status()

    # ------------------------------------------------------------ 设置
    def apply_settings(self) -> None:
        self.overlay.apply_flags()
        if self.overlay.is_playing and self.overlay._current is not None:
            self.overlay.set_size_for(self.overlay._aspect)
        self.update_status()

    def set_autostart(self, enabled: bool) -> bool:
        try:
            import winreg
            name = "GoldenBoughLauncher"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                                 winreg.KEY_SET_VALUE)
            if enabled:
                pyw = Path(sys.executable).with_name("pythonw.exe")
                exe = pyw if pyw.exists() else Path(sys.executable)
                run = f'"{exe}" "{APP_DIR / "app.py"}"'
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, run)
            else:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
            return True
        except OSError:
            return False

    def toast(self, text: str) -> None:
        self.toast_label.show_message(text)

    # ------------------------------------------------------------ 杂项
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not getattr(self, "_dark_bar_done", False):
            self._dark_bar_done = True
            _apply_dark_titlebar(self)

    def _first_run_hint(self) -> None:
        if not self.config.rules:
            self.toast("提示：先在「动画库」导入素材，再到「触发规则」绑定程序")

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.tray.isVisible():
            event.ignore()
            self.hide()
            if not self._close_hint_shown:
                self._close_hint_shown = True
                self.tray.showMessage("金枝共鸣 · 启动器", "已最小化到托盘，仍会监听程序启动。",
                                      QSystemTrayIcon.Information, 2500)
        else:
            self.overlay.stop()
            self.watcher.stop()
            event.accept()
