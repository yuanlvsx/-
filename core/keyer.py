"""绿幕抠像引擎：色度距离 + 幕布主导度 + 连通区域黑场处理。

设计要点
--------
1. 色度距离（YCrCb 平面）负责常规抠像与柔和边缘；
2. "幕布主导度"不受亮度影响，负责暗场/阴影/半透明面板——这些区域
   在纯色度抠像里会被当成前景，留下一块暗底；
3. 两者的 alpha 取较小值，再对"与画面边缘连通"的背景区域强制清零，
   避免误伤 Logo 内部的同色与深色细节。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np

KEY_COLORS = {
    "green": (0, 255, 0),   # RGB
    "blue": (0, 0, 255),
}


@dataclass
class VideoInfo:
    width: int
    height: int
    fps: float
    frames: int

    @property
    def duration(self) -> float:
        return self.frames / self.fps if self.fps else 0.0


def probe(path: str | Path) -> Optional[VideoInfo]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    cap.release()
    if w <= 0 or h <= 0:
        return None
    return VideoInfo(w, h, fps, frames)


def detect_key_mode(path: str | Path) -> str:
    """采样画面边缘，猜是绿幕还是蓝幕。"""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return "green"
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 1)
    samples = []
    for pos in (int(n * 0.15), int(n * 0.5), int(n * 0.75)):
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, pos))
        ok, frame = cap.read()
        if not ok:
            continue
        edge = np.concatenate([
            frame[0:4, :, :].reshape(-1, 3),
            frame[-4:, :, :].reshape(-1, 3),
            frame[:, 0:4, :].reshape(-1, 3),
        ])
        samples.append(np.median(edge, axis=0))
    cap.release()
    if not samples:
        return "green"
    b, g, r = np.median(np.array(samples), axis=0)
    if g > 90 and g > r * 1.5 and g > b * 1.5:
        return "green"
    if b > 90 and b > r * 1.5 and b > g * 1.5:
        return "blue"
    return "none"


def detect_trim(path: str | Path, black_luma: int = 28) -> Tuple[float, float]:
    """探测首尾的"死帧"（纯黑、与画面无关），返回建议裁剪的 (头部秒, 尾部秒)。"""
    info = probe(path)
    if not info:
        return 0.0, 0.0
    cap = cv2.VideoCapture(str(path))
    good: list[int] = []
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        small = cv2.resize(frame, (80, 45))
        ycrcb = cv2.cvtColor(small, cv2.COLOR_BGR2YCrCb)
        y = int(np.median(ycrcb[:, :, 0]))
        sat = int(np.median(np.abs(ycrcb[:, :, 1].astype(np.int16) - 128)) +
                  np.median(np.abs(ycrcb[:, :, 2].astype(np.int16) - 128)))
        if y > black_luma or sat > 18:
            good.append(idx)
        idx += 1
    cap.release()
    if not good or idx == 0:
        return 0.0, 0.0
    head = good[0] / info.fps
    tail = (idx - 1 - good[-1]) / info.fps
    return round(head, 2), round(tail, 2)


class ChromaKeyer:
    """把一帧 BGR 转成带 alpha 的 BGRA。"""

    def __init__(self, mode: str = "green", tolerance: float = 42,
                 softness: float = 26, spill: float = 0.75,
                 shadow: float = 45, auto_black: bool = True):
        self.mode = mode
        self.tolerance = float(tolerance)
        self.softness = float(max(1, softness))
        self.spill = float(spill)
        self.shadow = float(shadow)
        self.auto_black = bool(auto_black)
        # 幕布主导度阈值：shadow 越大越"狠"，0 表示关闭该通道
        self.dom_high = float(np.clip(255.0 - self.shadow * 2.0, 60.0, 255.0))
        self.dom_soft = 60.0
        if mode in KEY_COLORS:
            r, g, b = KEY_COLORS[mode]
            px = np.uint8([[[b, g, r]]])
            crcb = cv2.cvtColor(px, cv2.COLOR_BGR2YCrCb)[0, 0]
            self.key_cr = float(crcb[1])
            self.key_cb = float(crcb[2])
            self.key_bgr = (b, g, r)
        else:
            self.key_cr = self.key_cb = 128.0
            self.key_bgr = (0, 0, 0)

    # ------------------------------------------------------------ 内部
    def tune(self, mode: Optional[str] = None, tolerance: Optional[float] = None,
             softness: Optional[float] = None, spill: Optional[float] = None,
             shadow: Optional[float] = None) -> None:
        """实时改参数（供预览面板使用）。"""
        if mode is not None and mode != self.mode:
            other = ChromaKeyer(mode, self.tolerance, self.softness, self.spill, self.shadow)
            self.__dict__.update(other.__dict__)
            return
        if tolerance is not None:
            self.tolerance = float(tolerance)
        if softness is not None:
            self.softness = float(max(1, softness))
        if spill is not None:
            self.spill = float(spill)
        if shadow is not None:
            self.shadow = float(shadow)
        self.dom_high = float(np.clip(255.0 - self.shadow * 2.0, 60.0, 255.0))

    @classmethod
    def from_animation(cls, anim) -> "ChromaKeyer":
        return cls(anim.key_mode, anim.tolerance, anim.softness, anim.spill,
                   anim.shadow, getattr(anim, "auto_black", True))

    def _chroma_distance(self, ycrcb: np.ndarray) -> np.ndarray:
        cr = ycrcb[:, :, 1]
        cb = ycrcb[:, :, 2]
        dcr = cv2.subtract(cr, self.key_cr, dtype=cv2.CV_32F)
        dcb = cv2.subtract(cb, self.key_cb, dtype=cv2.CV_32F)
        return cv2.magnitude(dcr, dcb)

    def _dominance(self, bgr: np.ndarray) -> np.ndarray:
        """幕布色相对其他通道的主导度（0..255，与亮度无关）。

        纯绿约 254，暗绿/半透明压绿的黑影也有 150+，白/青/灰接近 0。
        """
        b, g, r = cv2.split(bgr)
        if self.mode == "green":
            exc = cv2.subtract(g, cv2.max(r, b))
            base = cv2.add(g, 1)
        else:
            exc = cv2.subtract(b, cv2.max(r, g))
            base = cv2.add(b, 1)
        return cv2.divide(exc, base, scale=255.0)

    def _background_mask(self, ycrcb: np.ndarray) -> np.ndarray:
        """与画面边缘连通的"近黑区"（淡出到黑场时用），避免误杀内部深色细节。"""
        h, w = ycrcb.shape[:2]
        y = ycrcb[:, :, 0]
        cand = np.where(y <= 26, 255, 0).astype(np.uint8)
        seeds = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
                 (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)]
        mask = np.zeros((h + 2, w + 2), np.uint8)
        for x, y0 in seeds:
            if cand[y0, x] == 255:
                cv2.floodFill(cand, mask, (x, y0), 128, 0, 0)
        return np.where(cand == 128, 255, 0).astype(np.uint8)

    # ------------------------------------------------------------ 对外
    def apply(self, bgr: np.ndarray, out_size: Optional[Tuple[int, int]] = None) -> np.ndarray:
        """返回 BGRA(uint8, HxWx4)，可直接塞进 QImage.Format_ARGB32（小端）。"""
        if out_size:
            tw, th = out_size
            if (tw, th) != (bgr.shape[1], bgr.shape[0]):
                bgr = cv2.resize(bgr, (tw, th), interpolation=cv2.INTER_AREA)

        if self.mode == "none":
            return cv2.cvtColor(bgr, cv2.COLOR_BGR2BGRA)

        ycrcb = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
        dist = self._chroma_distance(ycrcb)
        dom8 = self._dominance(bgr)

        # alpha = clamp((dist - tol) / soft)，用 uint8 饱和减法避免取绝对值
        dist8 = cv2.convertScaleAbs(dist)
        alpha_dist = cv2.convertScaleAbs(
            cv2.subtract(dist8, int(self.tolerance)), alpha=255.0 / self.softness)

        if self.shadow > 0.5:
            alpha_dom = cv2.convertScaleAbs(
                cv2.subtract(int(self.dom_high), dom8), alpha=255.0 / self.dom_soft)
            alpha8 = cv2.min(alpha_dist, alpha_dom)
        else:
            alpha8 = alpha_dist

        # 淡出到纯黑时，把与边缘连通的黑场也挖掉
        if self.auto_black:
            dark = self._background_mask(ycrcb)
            alpha8[dark == 255] = 0

        b, g, r = cv2.split(bgr)
        if self.spill > 0.001:
            if self.mode == "green":
                excess = cv2.subtract(g, cv2.max(r, b))
                g = cv2.subtract(g, cv2.convertScaleAbs(excess, alpha=self.spill))
            else:
                excess = cv2.subtract(b, cv2.max(r, g))
                b = cv2.subtract(b, cv2.convertScaleAbs(excess, alpha=self.spill))

        return cv2.merge([b, g, r, alpha8])


def grab_keyed_frame(path: str | Path, keyer: ChromaKeyer, at_ratio: float = 0.35,
                     width: int = 480) -> Optional[np.ndarray]:
    """取一帧并抠像，返回 BGRA 数组（缩略图 / 预览用）。"""
    info = probe(path)
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened() or not info:
        return None
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(max(0, info.frames - 1) * at_ratio))
    ok, frame = cap.read()
    if not ok:
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        ok, frame = cap.read()
    cap.release()
    if not ok:
        return None
    h, w = frame.shape[:2]
    tw = width
    th = max(1, int(round(h * tw / w)))
    return keyer.apply(frame, (tw, th))
