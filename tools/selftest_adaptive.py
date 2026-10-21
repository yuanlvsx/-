"""自检：窗口 / 屏幕两种参照下的尺寸自适应，以及窗口缩放后的实时跟随。"""
from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core import layout as L  # noqa: E402
from core.config import Config  # noqa: E402
from ui.overlay import OverlayWindow  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable


def find_by_title(title: str):
    found = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
        if buf.value == title and ctypes.windll.user32.IsWindowVisible(hwnd):
            found.append(int(hwnd))
        return True

    ctypes.windll.user32.EnumWindows(proc(cb), 0)
    return found[0] if found else None


def main() -> int:
    app = QApplication(sys.argv)
    cfg = Config()
    cfg.settings.update({"size_ref": "window", "height_percent": 50,
                         "pos_preset": "bottom-right", "margin": 20})

    helper = subprocess.Popen([PY, str(ROOT / "tools" / "_test_window.py")])
    hwnd = None
    for _ in range(40):
        time.sleep(0.25)
        hwnd = find_by_title("WB_TEST_WIN")
        if hwnd:
            break
    print("target hwnd:", hwnd, "| rect:", L.window_rect(hwnd))
    if not hwnd:
        helper.kill()
        return 1

    # 按 pid 找窗口（和真实触发链路一致，不依赖前台窗口）
    overlay = OverlayWindow(cfg)
    overlay.play_animations([cfg.animations[0]], target_pid=helper.pid)

    def report(tag: str) -> None:
        lay = overlay._layout
        print(f"[{tag}] overlay={overlay.geometry().getRect()} "
              f"decode={lay.decode} scale={round(lay.scale, 3)} "
              f"ref={lay.ref.getRect()}")

    def resize(w: int, h: int) -> None:
        ctypes.windll.user32.SetWindowPos(wintypes.HWND(hwnd), 0, 160, 120, w, h, 0x0004)

    def step1() -> None:
        report("初始 700x500")
        resize(720, 420)
        QTimer.singleShot(1200, step2)

    def step2() -> None:
        report("窗口 720x420")
        resize(1150, 760)
        QTimer.singleShot(1200, step3)

    def step3() -> None:
        report("窗口 1150x760")
        ctypes.windll.user32.ShowWindow(wintypes.HWND(hwnd), 6)  # 最小化
        QTimer.singleShot(1200, step4)

    def step4() -> None:
        report("窗口最小化后回退屏幕")
        ctypes.windll.user32.ShowWindow(wintypes.HWND(hwnd), 9)
        cfg.settings.update({"size_ref": "screen", "pos_preset": "center"})
        overlay.set_size_for(overlay._aspect)
        QTimer.singleShot(400, lambda: (report("切换为屏幕参照"), done()))

    def done() -> None:
        overlay.stop()
        helper.kill()
        QTimer.singleShot(200, app.quit)

    QTimer.singleShot(1000, step1)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
