"""自检脚本：验证「程序启动 -> 触发规则」链路（不写配置文件）。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.config import Config, Rule  # noqa: E402
from core.triggers import ProcessWatcher  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv[:1])
    cfg = Config()
    if not cfg.animations:
        print("no animations")
        return 1
    cfg.rules = [Rule(exe="notepad.exe", animation_ids=[cfg.animations[0].id], cooldown=3)]
    print("baseline snapshot...")
    w = ProcessWatcher(cfg)

    def fired(rule, pid: int = 0):
        print("FIRED", rule.exe, "pid", pid, flush=True)
        QTimer.singleShot(300, app.quit)

    w.ruleFired.connect(fired)
    w.start()
    QTimer.singleShot(1500, lambda: subprocess.Popen(["notepad.exe"]))
    QTimer.singleShot(12000, lambda: (print("TIMEOUT no fire", flush=True), app.quit()))
    return app.exec()


if __name__ == "__main__":
    code = main()
    subprocess.run(["taskkill", "/F", "/IM", "notepad.exe"], capture_output=True)
    print("exit", code)
