"""逐帧解码 + 实时抠像，通过 Qt 信号把 QImage 送到界面上。"""
from __future__ import annotations

import time
from typing import Dict, Optional, Tuple

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from .keyer import ChromaKeyer, probe

# 边缘径向淡出的遮罩（按尺寸缓存）：让画面靠近边框时柔和收边，
# 光波才能"漏"出画框、由叠加层接着往外扩散
_EDGE_CACHE: Dict[Tuple[int, int], np.ndarray] = {}


def edge_mask(h: int, w: int, inner: float = 0.84, outer: float = 1.0) -> np.ndarray:
    key = (h, w)
    cached = _EDGE_CACHE.get(key)
    if cached is not None:
        return cached
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.sqrt(((yy - cy) / max(cy, 1.0)) ** 2 + ((xx - cx) / max(cx, 1.0)) ** 2)
    t = np.clip((d - inner) / max(1e-3, outer - inner), 0.0, 1.0)
    t = t * t * (3 - 2 * t)                      # smoothstep
    mask = ((1.0 - t) * 255).astype(np.uint8)
    if len(_EDGE_CACHE) > 12:
        _EDGE_CACHE.clear()
    _EDGE_CACHE[key] = mask
    return mask


class ClipPlayer(QThread):
    """在后台线程按原始帧率解码、抠像，并发出 BGRA 的 QImage。"""

    frameReady = Signal(QImage, float)           # (图像, 源视频时间秒)
    finishedClip = Signal()

    def __init__(self, path: str, keyer: ChromaKeyer, out_size: Tuple[int, int],
                 trim_start: float = 0.0, trim_end: float = 0.0,
                 loop: bool = False, parent=None, scale: float = 1.0,
                 edge_fade: bool = False):
        super().__init__(parent)
        self.path = str(path)
        self.keyer = keyer
        self.out_size = out_size
        self.trim_start = max(0.0, float(trim_start))
        self.trim_end = max(0.0, float(trim_end))
        self.loop = bool(loop)
        self.edge_fade = bool(edge_fade)
        self._stop = False
        # (解码宽, 解码高, QImage 的 devicePixelRatio)；整体替换保证线程安全
        self._geo = (int(out_size[0]), int(out_size[1]), float(scale) or 1.0)

    def set_geometry(self, out_size: Tuple[int, int], scale: float) -> None:
        """分辨率 / 缩放变化时热更新，不用重启播放。"""
        self._geo = (max(2, int(out_size[0])), max(2, int(out_size[1])),
                     max(0.01, float(scale)))

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:  # noqa: D401
        info = probe(self.path)
        cap = cv2.VideoCapture(self.path)
        if not cap.isOpened() or info is None:
            self.finishedClip.emit()
            return

        fps = info.fps if info.fps > 1 else 30.0
        interval = 1.0 / fps
        start_frame = min(int(self.trim_start * fps), max(0, info.frames - 1))
        end_frame = max(start_frame + 1, info.frames - int(self.trim_end * fps))

        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        idx = start_frame
        next_t = time.perf_counter()
        while not self._stop:
            ok, frame = cap.read()
            if not ok:
                if self.loop:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
                    idx = start_frame
                    next_t = time.perf_counter()
                    continue
                break
            if idx >= end_frame:
                if self.loop:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
                    idx = start_frame
                    next_t = time.perf_counter()
                    continue
                break

            tw, th, img_scale = self._geo
            bgra = self.keyer.apply(frame, (tw, th))
            if self.edge_fade:
                hh, ww = bgra.shape[:2]
                bgra[:, :, 3] = cv2.multiply(bgra[:, :, 3], edge_mask(hh, ww),
                                             scale=1.0 / 255.0)
            h, w = bgra.shape[:2]
            img = QImage(bgra.data, w, h, w * 4, QImage.Format_ARGB32).copy()
            if abs(img_scale - 1.0) > 1e-3:
                # 让 Qt 按 DPI 缩放绘制，高清屏上不发虚
                img.setDevicePixelRatio(img_scale)
            self.frameReady.emit(img, idx / fps)
            idx += 1

            next_t += interval
            delay = next_t - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            else:
                next_t = time.perf_counter()

        cap.release()
        self.finishedClip.emit()
