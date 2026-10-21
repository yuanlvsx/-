"""配置与数据模型：动画素材、触发规则、全局设置。"""
from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

APP_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = APP_DIR / "config.json"
ASSETS_DIR = APP_DIR / "assets"
CACHE_DIR = APP_DIR / "cache"


# ---------------------------------------------------------------- 数据模型
@dataclass
class Animation:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    name: str = "未命名动画"
    path: str = ""                      # 相对 APP_DIR 或绝对路径
    key_mode: str = "green"             # green | blue | none
    tolerance: int = 42                 # 抠像主容差
    softness: int = 26                  # 边缘羽化
    spill: float = 0.85                 # 溢色抑制
    shadow: int = 60                    # 暗部 / 阴影 / 半透明面板扣除
    auto_black: bool = True             # 淡出到黑场时也能自动透明
    trim_start: float = 0.0             # 掐头（秒）
    trim_end: float = 0.0               # 去尾（秒）
    loop: bool = False                  # 循环播放（否则播完一次）
    muted: bool = True                  # 静音（默认不吵）
    burst: Dict[str, Any] = field(default_factory=dict)   # 光波扩散（检测结果 + 径向剖面）

    def abs_path(self) -> Path:
        p = Path(self.path)
        return p if p.is_absolute() else (APP_DIR / p)

    def exists(self) -> bool:
        try:
            return self.abs_path().is_file()
        except OSError:
            return False


@dataclass
class Rule:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    exe: str = ""                       # 程序名 或 完整路径
    match: str = "name"                 # name | path
    animation_ids: List[str] = field(default_factory=list)
    delay_ms: int = 0
    cooldown: int = 10                  # 秒
    allow_child: bool = False           # 程序已在运行时，新出现的同名进程也触发
    enabled: bool = True


DEFAULT_SETTINGS: Dict[str, Any] = {
    "enabled": True,
    "pos_preset": "bottom-right",       # bottom-right / bottom-left / bottom-center / center / top-right / top-left / custom
    "custom_x": 40,
    "custom_y": 40,
    "screen_index": 0,
    "size_ref": "screen",               # screen 屏幕 / window 目标程序窗口 / fixed 固定像素
    "height_percent": 42,               # 占参照区域高度的百分比
    "fixed_height": 300,                 # size_ref=fixed 时的像素高度
    "margin": 28,
    "always_on_top": True,
    "click_through": True,
    "skip_if_running": True,
    "poll_ms": 700,
    "default_cooldown": 10,
    "queue_mode": "sequence",           # sequence | random
    "autostart": False,
    "play_sound": False,
}


class Config:
    def __init__(self) -> None:
        self.settings: Dict[str, Any] = dict(DEFAULT_SETTINGS)
        self.animations: List[Animation] = []
        self.rules: List[Rule] = []
        self.load()

    # ---------------------------------------------------------- 读写
    def load(self) -> None:
        if not CONFIG_PATH.exists():
            return
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return
        s = data.get("settings") or {}
        self.settings.update({k: v for k, v in s.items() if k in DEFAULT_SETTINGS})
        self.animations = [self._anim_from_dict(d) for d in data.get("animations", [])]
        self.rules = [self._rule_from_dict(d) for d in data.get("rules", [])]

    def save(self) -> None:
        data = {
            "version": 1,
            "settings": self.settings,
            "animations": [asdict(a) for a in self.animations],
            "rules": [asdict(r) for r in self.rules],
        }
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, CONFIG_PATH)

    @staticmethod
    def _anim_from_dict(d: Dict[str, Any]) -> Animation:
        allowed = {f for f in Animation.__dataclass_fields__}
        return Animation(**{k: v for k, v in d.items() if k in allowed})

    @staticmethod
    def _rule_from_dict(d: Dict[str, Any]) -> Rule:
        allowed = {f for f in Rule.__dataclass_fields__}
        return Rule(**{k: v for k, v in d.items() if k in allowed})

    # ---------------------------------------------------------- 素材
    def add_animation(self, src: Path, name: Optional[str] = None, copy: bool = True) -> Animation:
        src = Path(src)
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        anim = Animation(name=name or src.stem)
        if copy:
            target = ASSETS_DIR / f"{anim.id}_{src.name}"
            shutil.copy2(src, target)
            anim.path = str(target.relative_to(APP_DIR)).replace("\\", "/")
        else:
            anim.path = str(src)
        self.animations.append(anim)
        self.save()
        return anim

    def remove_animation(self, anim_id: str) -> None:
        anim = self.get_animation(anim_id)
        self.animations = [a for a in self.animations if a.id != anim_id]
        for r in self.rules:
            r.animation_ids = [i for i in r.animation_ids if i != anim_id]
        if anim and anim.path:
            p = anim.abs_path()
            try:
                if ASSETS_DIR in p.parents and p.exists():
                    p.unlink()
            except OSError:
                pass
        self.save()

    def get_animation(self, anim_id: str) -> Optional[Animation]:
        return next((a for a in self.animations if a.id == anim_id), None)

    # ---------------------------------------------------------- 规则
    def add_rule(self, rule: Rule) -> Rule:
        self.rules.append(rule)
        self.save()
        return rule

    def remove_rule(self, rule_id: str) -> None:
        self.rules = [r for r in self.rules if r.id != rule_id]
        self.save()

    def get_rule(self, rule_id: str) -> Optional[Rule]:
        return next((r for r in self.rules if r.id == rule_id), None)


def human_duration(seconds: float) -> str:
    if seconds <= 0:
        return "—"
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:04.1f}" if m else f"{s:.1f}s"


def now() -> float:
    return time.time()
