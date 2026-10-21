"""自检脚本：渲染两个对话框并截图。"""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.config import Config, Rule  # noqa: E402
from ui.anim_dialog import AnimationDialog  # noqa: E402
from ui.rule_dialog import RuleDialog  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv[:1])
    cfg = Config()
    from ui import theme
    app.setStyleSheet(theme.build_qss())

    anim = cfg.animations[0]
    d1 = AnimationDialog(anim)
    d1.show()

    def grab_first() -> None:
        d1.grab().save(str(BASE / "dlg_anim.png"))
        d1.close()
        rule = Rule(exe="chrome.exe", animation_ids=[a.id for a in cfg.animations],
                    cooldown=12, delay_ms=300)
        d2 = RuleDialog(rule, cfg)
        d2.show()
        QTimer.singleShot(700, lambda: (d2.grab().save(str(BASE / "dlg_rule.png")), app.quit()))

    QTimer.singleShot(1600, grab_first)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
