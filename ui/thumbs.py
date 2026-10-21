"""缩略图生成与缓存。"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtGui import QImage, QPixmap

from core.config import CACHE_DIR, Animation
from core.keyer import ChromaKeyer, grab_keyed_frame


def _crop_to_content(bgra: np.ndarray, pad_ratio: float = 0.06) -> np.ndarray:
    """裁掉透明留白，让缩略图里的 Logo 更大（仅影响界面展示）。"""
    alpha = bgra[:, :, 3]
    ys, xs = np.where(alpha > 16)
    if len(xs) == 0:
        return bgra
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    h, w = alpha.shape
    pad = int(max(x1 - x0, y1 - y0) * pad_ratio) + 2
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(w - 1, x1 + pad), min(h - 1, y1 + pad)
    return np.ascontiguousarray(bgra[y0:y1 + 1, x0:x1 + 1])


def preview_ratio(anim: Animation) -> float:
    from core.keyer import probe
    info = probe(anim.abs_path())
    if not info or not info.duration:
        return 0.4
    start = anim.trim_start
    end = max(start + 0.2, info.duration - anim.trim_end)
    t = start + (end - start) * 0.45
    return max(0.0, min(0.99, t / info.duration))


def thumb_pixmap(anim: Animation, width: int = 360) -> QPixmap:
    if not anim.exists():
        return QPixmap()
    try:
        mtime = int(Path(anim.abs_path()).stat().st_mtime)
    except OSError:
        mtime = 0
    tag = f"v2_{anim.id}_{width}_{mtime}_{anim.key_mode}_{anim.tolerance}_{anim.softness}_" \
          f"{anim.spill}_{anim.shadow}_{int(anim.auto_black)}_{anim.trim_start}_{anim.trim_end}"
    cache = CACHE_DIR / "thumbs"
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / f"{tag}.png"
    if target.is_file():
        pm = QPixmap(str(target))
        if not pm.isNull():
            return pm

    keyer = ChromaKeyer.from_animation(anim)
    bgra = grab_keyed_frame(anim.abs_path(), keyer, preview_ratio(anim), width)
    if bgra is None:
        return QPixmap()
    bgra = _crop_to_content(bgra)
    h, w = bgra.shape[:2]
    img = QImage(bgra.data, w, h, w * 4, QImage.Format_ARGB32).copy()
    pm = QPixmap.fromImage(img)
    try:
        pm.save(str(target), "PNG")
    except Exception:
        pass
    return pm
