"""实机自检：启动叠加层播放光波，在光环扩散到不同半径时截屏。"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

sys.path.insert(0, ".")
from core.config import Config  # noqa: E402
from ui.overlay import OverlayWindow  # noqa: E402


def main() -> None:
    index = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    app = QApplication(sys.argv)
    cfg = Config()
    anim = cfg.animations[index]
    cfg.settings.update({"size_ref": "screen", "height_percent": 42,
                         "pos_preset": "bottom-right", "margin": 28,
                         "screen_index": 0})

    # 铺一块深色背景，方便看抠像边缘
    back = QWidget()
    back.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
    back.setGeometry(QApplication.primaryScreen().geometry())
    pal = back.palette()
    pal.setColor(QPalette.Window, QColor(28, 30, 36))
    back.setPalette(pal)
    back.setAutoFillBackground(True)
    back.show()

    overlay = OverlayWindow(cfg)
    print("playing", anim.name, "burst", {k: anim.burst.get(k) for k in ("start", "end", "ref")})
    overlay.play_animations([anim])
    print("window", overlay.geometry().getRect(), "frame", overlay._frame_rect.getRect())

    queue = [1.35, 2.1, 3.2, 5.0]

    def grab(t: float, target: float) -> None:
        from PIL import ImageGrab
        r, op = overlay._ring
        path = f"burst_{index}_{target:.1f}.png"
        ImageGrab.grab().save(path)
        print(f"  截屏 t={t:.2f} r={r:.2f} op={op:.2f} -> {path}")

    orig = overlay._on_frame

    def hooked(img, t: float) -> None:
        orig(img, t)
        r, op = overlay._ring
        if queue and r >= queue[0] and op > 0.02:
            target = queue.pop(0)
            QTimer.singleShot(40, lambda: grab(t, target))

    overlay._on_frame = hooked

    def done() -> None:
        overlay.stop()
        overlay.close()
        back.close()
        QTimer.singleShot(150, app.quit)

    QTimer.singleShot(6500, done)
    app.exec()


if __name__ == "__main__":
    main()
