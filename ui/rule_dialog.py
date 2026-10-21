"""触发规则编辑对话框。"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMenu, QMessageBox, QPushButton, QSpinBox,
                               QVBoxLayout)

from core.config import Animation, Config, Rule
from core.triggers import running_exes

from .base_dialog import BaseDialog, field_label
from .thumbs import thumb_pixmap


class RuleDialog(BaseDialog):
    def __init__(self, rule: Rule, config: Config, parent=None):
        super().__init__("编辑触发规则" if rule.exe else "新建触发规则", width=620, parent=parent)
        self.rule = rule
        self.config = config

        # 程序
        self.body.addWidget(field_label("程序（进程名或完整路径）"))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.exe_edit = QLineEdit(rule.exe)
        self.exe_edit.setPlaceholderText("例如 chrome.exe")
        pick_btn = QPushButton("运行中…")
        pick_btn.setObjectName("Ghost")
        pick_btn.clicked.connect(self._pick_running)
        browse_btn = QPushButton("浏览…")
        browse_btn.setObjectName("Ghost")
        browse_btn.clicked.connect(self._browse)
        row.addWidget(self.exe_edit, 1)
        row.addWidget(pick_btn)
        row.addWidget(browse_btn)
        self.body.addLayout(row)

        self.body.addWidget(field_label("匹配方式"))
        self.match_box = QComboBox()
        self.match_box.addItem("按程序名匹配（推荐，程序更新后依然有效）", "name")
        self.match_box.addItem("按完整路径匹配（同名程序多时更精确）", "path")
        self.match_box.setCurrentIndex(0 if rule.match == "name" else 1)
        self.body.addWidget(self.match_box)

        # 动画
        hint = QLabel("动画（可多选，按这里的顺序播放）")
        hint.setObjectName("FieldLabel")
        self.body.addWidget(hint)
        self.list = QListWidget()
        self.list.setFixedHeight(118)
        self.list.setIconSize(QSize(44, 26))
        for anim in config.animations:
            item = QListWidgetItem(anim.name)
            pm = thumb_pixmap(anim, 120)
            if not pm.isNull():
                item.setIcon(QIcon(pm))
            item.setData(Qt.UserRole, anim.id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if anim.id in rule.animation_ids else Qt.Unchecked)
            item.setSizeHint(QSize(0, 44))
            self.list.addItem(item)
        if not config.animations:
            empty = QListWidgetItem("先到「动画库」导入素材，再回来配置规则")
            empty.setFlags(Qt.NoItemFlags)
            self.list.addItem(empty)
        self.body.addWidget(self.list)

        # 参数
        params = QHBoxLayout()
        params.setSpacing(10)
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(0, 20000)
        self.delay_spin.setSingleStep(100)
        self.delay_spin.setSuffix(" ms")
        self.delay_spin.setValue(rule.delay_ms)
        self.cool_spin = QSpinBox()
        self.cool_spin.setRange(1, 3600)
        self.cool_spin.setSuffix(" 秒")
        self.cool_spin.setValue(rule.cooldown)
        params.addWidget(field_label("启动后延迟"))
        params.addWidget(self.delay_spin)
        params.addSpacing(12)
        params.addWidget(field_label("冷却时间"))
        params.addWidget(self.cool_spin)
        params.addStretch(1)
        self.body.addLayout(params)

        self.chk_child = QCheckBox("程序已在运行时，新出现的同名进程也触发（浏览器多标签/更新器会频繁触发，慎用）")
        self.chk_child.setChecked(rule.allow_child)
        self.chk_enabled = QCheckBox("启用这条规则")
        self.chk_enabled.setChecked(rule.enabled)
        self.body.addWidget(self.chk_child)
        self.body.addWidget(self.chk_enabled)

        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("Ghost")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("保存")
        ok.setObjectName("Primary")
        ok.clicked.connect(self._on_ok)
        footer.addWidget(cancel)
        footer.addWidget(ok)
        self.body.addLayout(footer)

    # ------------------------------------------------------------ 选择程序
    def _pick_running(self) -> None:
        menu = QMenu(self)
        names = running_exes()
        if not names:
            menu.addAction("（没有检测到可选的程序）").setEnabled(False)
        for name in names:
            act = menu.addAction(name)
            act.triggered.connect(lambda _=False, n=name: self._set_exe(n, "name"))
        menu.exec(self.cursor().pos())

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择程序", "", "可执行文件 (*.exe)")
        if path:
            self._set_exe(path, "path")

    def _set_exe(self, value: str, match: str) -> None:
        self.exe_edit.setText(value)
        self.match_box.setCurrentIndex(0 if match == "name" else 1)

    # ------------------------------------------------------------ 保存
    def _on_ok(self) -> None:
        exe = self.exe_edit.text().strip().strip('"')
        if not exe:
            QMessageBox.warning(self, "缺少程序", "请填写或选择一个程序。")
            return
        match = self.match_box.currentData()
        if match == "name" and (os.sep in exe or "/" in exe):
            exe = Path(exe).name
        ids = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.flags() & Qt.ItemIsUserCheckable and item.checkState() == Qt.Checked:
                ids.append(item.data(Qt.UserRole))
        if not ids:
            QMessageBox.warning(self, "缺少动画", "请至少勾选一段要播放的动画。")
            return
        self.rule.exe = exe
        self.rule.match = match
        self.rule.animation_ids = ids
        self.rule.delay_ms = self.delay_spin.value()
        self.rule.cooldown = self.cool_spin.value()
        self.rule.allow_child = self.chk_child.isChecked()
        self.rule.enabled = self.chk_enabled.isChecked()
        self.accept()
