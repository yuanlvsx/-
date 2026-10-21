"""程序启动监听：轮询进程列表，命中规则时发出信号。"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set

import psutil
from PySide6.QtCore import QObject, Qt, QTimer, Signal

from .config import Config, Rule


@dataclass
class ProcessRef:
    pid: int
    name: str
    exe: str


def snapshot() -> Dict[int, ProcessRef]:
    result: Dict[int, ProcessRef] = {}
    for p in psutil.process_iter(["pid", "name", "exe"]):
        try:
            name = p.info.get("name") or ""
            exe = p.info.get("exe") or ""
            if not name and exe:
                name = Path(exe).name
            if name:
                result[p.pid] = ProcessRef(p.pid, name, exe)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return result


def running_exes() -> List[str]:
    """去重后的当前进程名列表，供界面下拉选择。"""
    names: Set[str] = set()
    for ref in snapshot().values():
        names.add(ref.name)
    return sorted((n for n in names if n.lower().endswith(".exe")), key=str.lower)


class ProcessWatcher(QObject):
    ruleFired = Signal(object, int)      # Rule, 触发进程的 pid
    statusChanged = Signal(str)

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self.poll)
        self._seen: Dict[int, ProcessRef] = {}
        self._last_fired: Dict[str, float] = {}
        self._active = False

    # ------------------------------------------------------------ 控制
    def start(self) -> None:
        self._seen = snapshot()
        self._active = True
        self._timer.start(int(self.config.settings.get("poll_ms", 700)))
        self.statusChanged.emit("监听中")

    def stop(self) -> None:
        self._active = False
        self._timer.stop()
        self.statusChanged.emit("已暂停")

    @property
    def active(self) -> bool:
        return self._active

    def set_interval(self, ms: int) -> None:
        self._timer.setInterval(max(200, int(ms)))

    def baseline(self) -> None:
        """把当前进程当作"已在运行"，避免误触发。"""
        self._seen = snapshot()

    # ------------------------------------------------------------ 轮询
    def poll(self) -> None:
        if not self._active:
            return
        current = snapshot()
        old_names = {ref.name.lower(): ref.exe for ref in self._seen.values()}
        new_pids = [pid for pid in current if pid not in self._seen]
        self._seen = current

        if not new_pids:
            return
        if not self.config.settings.get("enabled", True):
            return

        now = time.time()
        skip_child = bool(self.config.settings.get("skip_if_running", True))
        for pid in new_pids:
            ref = current[pid]
            was_running = ref.name.lower() in old_names
            for rule in self.config.rules:
                if not rule.enabled or not rule.animation_ids:
                    continue
                if not self._match(rule, ref):
                    continue
                if was_running and skip_child and not rule.allow_child:
                    continue
                last = self._last_fired.get(rule.id, 0.0)
                if now - last < max(1, rule.cooldown):
                    continue
                self._last_fired[rule.id] = now
                self.ruleFired.emit(rule, ref.pid)
                break

    @staticmethod
    def _match(rule: Rule, ref: ProcessRef) -> bool:
        target = (rule.exe or "").strip()
        if not target:
            return False
        if rule.match == "path":
            if not ref.exe:
                return False
            return os.path.normcase(ref.exe) == os.path.normcase(target)
        return ref.name.lower() == Path(target).name.lower()
