"""金枝共鸣 · 启动器

用法：双击「启动器.bat」，或 python app.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui import theme  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("金枝共鸣 · 启动器")
    app.setApplicationDisplayName("金枝共鸣 · 启动器")
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(theme.build_qss())
    app.setWindowIcon(theme.make_app_icon(128))

    window = MainWindow()
    window.show()

    # 自检用：WB_PAGE 切换页面，WB_SHOT 渲染一张窗口快照后退出
    if os.environ.get("WB_PAGE"):
        window._switch(int(os.environ["WB_PAGE"]))
    shot = os.environ.get("WB_SHOT")
    if shot:
        def _grab() -> None:
            window.grab().save(shot)
            QTimer.singleShot(250, app.quit)
        QTimer.singleShot(1400, _grab)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
