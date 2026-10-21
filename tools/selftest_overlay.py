"""自检脚本：在屏幕上真实播放一段动画，再把整屏抓下来看透明叠加效果。

用法：python tools/selftest_overlay.py [动画序号] [延迟毫秒]
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.config import Config  # noqa: E402
from ui.overlay import OverlayWindow  # noqa: E402


def main() -> int:
    index = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    delay = int(sys.argv[2]) if len(sys.argv) > 2 else 1800
    app = QApplication(sys.argv[:1])
    cfg = Config()
    if not cfg.animations:
        print("没有可用动画")
        return 1
    ov = OverlayWindow(cfg)
    anim = cfg.animations[index]
    print("playing:", anim.name, anim.abs_path())
    ov.play_animations([anim])

    def shot() -> None:
        screen = QGuiApplication.primaryScreen()
        pm = screen.grabWindow(0)
        ratio = pm.width() / screen.geometry().width()
        g = ov.geometry()
        rect = pm.rect().intersected(
            type(pm.rect())(int(g.x() * ratio), int(g.y() * ratio),
                            int(g.width() * ratio), int(g.height() * ratio)))
        out = BASE / "overlay_shot.png"
        pm.copy(rect).save(str(out))
        print("saved", out, rect)
        app.quit()

    QTimer.singleShot(delay, shot)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
