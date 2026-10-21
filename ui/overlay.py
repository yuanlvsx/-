"""屏幕叠加层：透明、置顶、鼠标穿透，播放抠像后的动画。

尺寸不再写死：按「屏幕 / 目标程序窗口 / 固定像素」三种参照自适应，
并且随 DPI 缩放、分辨率切换、窗口缩放实时重排（不打断播放）。

光波扩散：素材里的冲击环本来会在画框边缘被裁断。播放带光波的素材时，
窗口会临时扩到整个参照区域，素材边框做径向淡出，再按检测出的径向剖面
把光环接着往外画，直到铺满屏幕。
"""
from __future__ import annotations

import math
import os
import time
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import (QEasingCurve, QPointF, QPropertyAnimation, QRect, Qt,
                            QTimer, Signal)
from PySide6.QtGui import QColor, QImage, QPainter, QRadialGradient
from PySide6.QtWidgets import QWidget

from core import burst as burst_mod
from core import layout as layout_mod
from core.config import Animation, Config
from core.keyer import ChromaKeyer, probe
from core.layout import Layout
from core.player import ClipPlayer

try:  # 音频可选，失败时静默
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    HAS_AUDIO = True
except Exception:  # pragma: no cover
    HAS_AUDIO = False


class OverlayWindow(QWidget):
    playingChanged = Signal(bool)

    def __init__(self, config: Config):
        super().__init__(None)
        self.config = config
        self._queue: List[Animation] = []
        self._image: Optional[QImage] = None
        self._player: Optional[ClipPlayer] = None
        self._current: Optional[Animation] = None
        self._aspect = 16 / 9
        self._src_size = None          # 源素材像素尺寸
        self._layout: Optional[Layout] = None
        self._canvas_rect = QRect()
        self._frame_rect = QRect()     # 素材在窗口里的绘制区域
        self._burst: Optional[Dict] = None
        self._ring: Tuple[float, float] = (0.0, 0.0)   # (归一化半径, 不透明度)
        self._ref_hwnd: Optional[int] = None
        self._target_pid: int = 0
        self._pending_pid: Optional[int] = None
        self._pending_until: float = 0.0

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                            Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setWindowTitle("金枝共鸣 · 播放层")

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(150)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)

        # 播放期间定时检查分辨率 / 窗口尺寸变化（游戏切分辨率常常不发 Qt 信号）
        self._watch = QTimer(self)
        self._watch.setInterval(500)
        self._watch.timeout.connect(self._on_watch)

        self._audio_player = None
        self._audio_out = None
        if HAS_AUDIO:
            try:
                self._audio_out = QAudioOutput(self)
                self._audio_out.setVolume(0.8)
                self._audio_player = QMediaPlayer(self)
                self._audio_player.setAudioOutput(self._audio_out)
            except Exception:
                self._audio_player = None

        self._drag_from = None
        self.apply_flags()

    # ------------------------------------------------------------ 外观
    def apply_flags(self) -> None:
        s = self.config.settings
        was_visible = self.isVisible()
        flags = Qt.FramelessWindowHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
        if s.get("always_on_top", True):
            flags |= Qt.WindowStaysOnTopHint
        if s.get("click_through", True):
            flags |= Qt.WindowTransparentForInput
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, bool(s.get("click_through", True)))
        if was_visible:
            self.show()

    # ------------------------------------------------------------ 布局
    def _own_handles(self) -> tuple:
        hs = []
        for w in (self, self.parentWidget()):
            try:
                if w is not None:
                    hs.append(int(w.winId()))
            except (RuntimeError, TypeError):
                pass
        return tuple(hs)

    def _reference_window(self) -> Optional[int]:
        """window 模式下要跟随的窗口句柄。"""
        if self.config.settings.get("size_ref", "screen") != "window":
            return None
        if self._ref_hwnd and layout_mod.window_rect(self._ref_hwnd) is not None:
            return self._ref_hwnd
        self._ref_hwnd = None
        # 触发瞬间窗口往往还没建出来：在宽限期内一直按 pid 去找
        if self._pending_pid and time.time() < self._pending_until:
            hwnd = layout_mod.window_of_pid(self._pending_pid)
            if hwnd:
                self._ref_hwnd = hwnd
                self._pending_pid = None
                return hwnd
        return None

    def compute_layout(self) -> Layout:
        s = self.config.settings
        ref_hwnd = self._reference_window()
        ref_rect = layout_mod.window_rect(ref_hwnd) if ref_hwnd else None
        return layout_mod.compute(s, self._aspect, self._src_size,
                                  ref_window_rect=ref_rect, ref_hwnd=ref_hwnd)

    def canvas_rect(self, lay: Layout) -> QRect:
        """窗口实际占多大。

        有光波时窗口要扩到整个参照区域（屏幕 / 目标窗口），光环才能铺满屏幕；
        没有光波时窗口就是素材框本身。
        """
        if not self._burst:
            return lay.rect
        screen = layout_mod.screen_for(int(self.config.settings.get("screen_index", 0) or 0))
        sgeo = screen.geometry()
        area = lay.ref.intersected(sgeo)
        if area.width() < 32 or area.height() < 32:
            area = screen.availableGeometry()
        return lay.rect.united(area)

    def refresh_layout(self, force: bool = False) -> None:
        """重算并应用位置尺寸；播放中调用会热切换解码尺寸，不打断动画。"""
        new = self.compute_layout()
        old = self._layout
        canvas = self.canvas_rect(new)
        if not force and layout_mod.is_visually_same(old, new) and canvas == self._canvas_rect:
            return
        self._layout = new
        self._canvas_rect = canvas
        self._frame_rect = new.rect.translated(-canvas.topLeft())
        self.setGeometry(canvas)
        if self._player is not None:
            self._player.set_geometry(new.decode, new.scale)
        self.update()

    def _reach_px(self) -> float:
        """光环要铺满画布，最远得扩到多远（像素）。"""
        box = self._frame_rect
        canvas = self.rect()
        if box.isEmpty() or canvas.isEmpty():
            return 0.0
        cx, cy = box.center().x(), box.center().y()
        return max(
            math.hypot(cx - canvas.left(), cy - canvas.top()),
            math.hypot(cx - canvas.right(), cy - canvas.top()),
            math.hypot(cx - canvas.left(), cy - canvas.bottom()),
            math.hypot(cx - canvas.right(), cy - canvas.bottom()),
        )

    def set_size_for(self, aspect: float) -> None:  # 兼容旧调用
        self._aspect = aspect
        self.refresh_layout(force=True)

    def _on_watch(self) -> None:
        if self._current is None:
            return
        self.refresh_layout()

    # ------------------------------------------------------------ 播放
    @property
    def is_playing(self) -> bool:
        return self._current is not None

    def play_animations(self, anims: List[Animation], target_pid: int = 0) -> None:
        anims = [a for a in anims if a.exists()]
        if not anims:
            return
        self._queue = list(anims)
        self._target_pid = int(target_pid or 0)
        self._ref_hwnd = None            # 新的一次触发，重新锁定目标窗口
        self._pending_pid = None
        self._play_next()

    def _play_next(self) -> None:
        self.stop(reset_queue=False)
        if not self._queue:
            self._finish()
            return
        anim = self._queue.pop(0)
        info = probe(anim.abs_path())
        self._aspect = (info.width / info.height) if info and info.height else 16 / 9
        self._src_size = (info.width, info.height) if info else None

        # window 模式：锁定被触发的那个程序窗口，之后一直跟着它的分辨率
        window_mode = self.config.settings.get("size_ref", "screen") == "window"
        if not window_mode:
            self._ref_hwnd = None
            self._pending_pid = None
        elif self._ref_hwnd and layout_mod.window_rect(self._ref_hwnd) is not None:
            pass                        # 队列里的后续动画沿用同一个窗口
        else:
            self._ref_hwnd = None
            self._pending_pid = None
            if self._target_pid:
                self._pending_pid = self._target_pid
                self._pending_until = time.time() + 3.0
                self._ref_hwnd = layout_mod.window_of_pid(self._target_pid)
            else:
                self._ref_hwnd = layout_mod.foreground_handle(self._own_handles(),
                                                              exclude_pid=os.getpid())

        # 光波扩散：有检测结果才扩到全屏，否则保持原样
        burst = anim.burst or {}
        self._burst = burst if burst.get("enabled") and burst.get("profile") else None
        self._ring = (0.0, 0.0)

        self._layout = None
        self.refresh_layout(force=True)
        lay = self._layout or self.compute_layout()

        keyer = ChromaKeyer.from_animation(anim)
        self._current = anim
        self._player = ClipPlayer(str(anim.abs_path()), keyer, lay.decode,
                                  anim.trim_start, anim.trim_end, anim.loop, self,
                                  scale=lay.scale, edge_fade=self._burst is not None)
        self._player.frameReady.connect(self._on_frame)
        self._player.finishedClip.connect(self._on_clip_end)
        self._player.start()

        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
        self._watch.start()
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(1.0)
        self._fade.start()

        self._play_audio(anim)
        self.playingChanged.emit(True)

    def _play_audio(self, anim: Animation) -> None:
        if not self._audio_player:
            return
        try:
            if anim.muted or not self.config.settings.get("play_sound", False):
                self._audio_player.stop()
                return
            self._audio_player.setSource(anim.abs_path().as_uri())
            self._audio_player.setPosition(int(anim.trim_start * 1000))
            self._audio_out.setVolume(0.85)
            self._audio_player.play()
        except Exception:
            pass

    def _on_frame(self, img: QImage, t: float = 0.0) -> None:
        self._image = img
        if self._burst:
            half_h = max(1.0, self._frame_rect.height() / 2.0)
            self._ring = burst_mod.radius_at(self._burst, t, half_h, self._reach_px())
        else:
            self._ring = (0.0, 0.0)
        self.update()

    def _on_clip_end(self) -> None:
        if self._queue:
            self._play_next()
        else:
            self._finish()

    def _finish(self) -> None:
        self._current = None
        self._watch.stop()
        self.playingChanged.emit(False)
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self._on_faded_out)
        self._fade.start()

    def _on_faded_out(self) -> None:
        try:
            self._fade.finished.disconnect(self._on_faded_out)
        except (RuntimeError, TypeError):
            pass
        if self._current is None:
            self.hide()
            self._image = None

    def stop(self, reset_queue: bool = True) -> None:
        self._watch.stop()
        self._ring = (0.0, 0.0)
        if self._player:
            try:
                self._player.frameReady.disconnect()
                self._player.finishedClip.disconnect()
            except (RuntimeError, TypeError):
                pass
            self._player.stop()
            self._player.wait(1200)
            self._player = None
        if self._audio_player:
            try:
                self._audio_player.stop()
            except Exception:
                pass
        if reset_queue:
            self._queue.clear()
            self._finish()

    # ------------------------------------------------------------ 绘制
    def paintEvent(self, event) -> None:  # noqa: N802
        if self._image is None:
            return
        p = QPainter(self)
        p.setRenderHints(QPainter.SmoothPixmapTransform | QPainter.Antialiasing, True)
        box = self._frame_rect if not self._frame_rect.isEmpty() else self.rect()
        # 先画扩出去的光波，再把素材盖在上面：素材遮挡的地方用原图，
        # 素材淡出的地方由光环接续，边框处不会出现硬切口。
        self._paint_ring(p, box)
        img = self._image
        iw, ih = img.width(), img.height()
        if iw <= 0 or ih <= 0:
            return
        scale = min(box.width() / iw, box.height() / ih)
        tw, th = iw * scale, ih * scale
        target = QRect(round(box.x() + (box.width() - tw) / 2),
                       round(box.y() + (box.height() - th) / 2),
                       max(1, round(tw)), max(1, round(th)))
        p.drawImage(target, img)

    def _paint_ring(self, p: QPainter, box: QRect) -> None:
        radius, opacity = self._ring
        if not self._burst or radius <= 0 or opacity <= 0.01 or box.isEmpty():
            return
        half_h = max(1.0, box.height() / 2.0)
        outer, stops = burst_mod.ring_profile(self._burst, radius, half_h,
                                             opacity=opacity)
        if outer <= 1 or not stops:
            return
        # 光环的圆心不一定在画框正中（细环尤其明显），检测时量出的偏移要带上
        off = self._burst.get("offset") or (0.0, 0.0)
        center = QPointF(box.center().x() + float(off[0]) * half_h,
                         box.center().y() + float(off[1]) * half_h)
        grad = QRadialGradient(center, outer)
        for pos, c in stops:
            grad.setColorAt(pos, QColor(c[0], c[1], c[2], c[3]))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawEllipse(center, outer, outer)

    # ------------------------------------------------------------ 拖动
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.config.settings.get("click_through", True) or event.button() != Qt.LeftButton:
            return
        if self._canvas_rect != self._frame_rect:      # 光波模式：窗口即整屏，不拖
            return
        self._drag_from = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_from is not None and event.buttons() & Qt.LeftButton:
            pos = event.globalPosition().toPoint() - self._drag_from
            self.move(pos)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag_from is not None:
            self._drag_from = None
            geo = self.geometry()
            screen = self.screen().availableGeometry()
            self.config.settings["pos_preset"] = "custom"
            self.config.settings["custom_x"] = max(0, geo.left() - screen.left())
            self.config.settings["custom_y"] = max(0, geo.top() - screen.top())
            self.config.save()
