"""尺寸与位置计算：让动画在任何分辨率 / 缩放比例 / 窗口大小下都显示正确。

三种"参照"：
  screen  以显示器可用区域为参照（旧行为）
  window  以被触发的那个程序窗口为参照，窗口怎么改分辨率就跟着改
  fixed   固定像素高度，不随分辨率变化

同时处理高 DPI：解码尺寸按物理像素算，避免 125% / 150% 缩放下发虚。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication, QScreen

try:
    _user32 = ctypes.windll.user32
    _dwm = ctypes.windll.dwmapi
    _HAS_WIN32 = True
except Exception:  # pragma: no cover - 非 Windows 兜底
    _user32 = None
    _dwm = None
    _HAS_WIN32 = False


# ---------------------------------------------------------------- Win32 桥
class _RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", _RECT),
                ("rcWork", _RECT), ("dwFlags", wintypes.DWORD),
                ("szDevice", wintypes.WCHAR * 32)]


_MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
    ctypes.POINTER(_RECT), wintypes.LPARAM) if _HAS_WIN32 else None

_WNDENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HWND, wintypes.LPARAM) if _HAS_WIN32 else None

# 不属于"程序窗口"的窗口类：桌面、任务栏、输入法候选框等
_SKIP_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
                 "Windows.UI.Core.CoreWindow", "ApplicationFrameWindow"}


def _monitor_map() -> Dict[str, QRect]:
    """显示器设备名 -> 物理像素矩形（rcMonitor）。"""
    out: Dict[str, QRect] = {}
    if not _HAS_WIN32:
        return out

    def _cb(hmon, hdc, lprc, data):
        mi = _MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(_MONITORINFOEXW)
        if _user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            r = mi.rcMonitor
            out[mi.szDevice] = QRect(r.left, r.top, r.right - r.left, r.bottom - r.top)
        return True

    try:
        _user32.EnumDisplayMonitors(None, None, _MONITORENUMPROC(_cb), 0)
    except Exception:
        pass
    return out


def _screen_by_name(name: str) -> Optional[QScreen]:
    """设备名匹配（不同 Windows/Qt 版本返回的 name 不一致，只作首选）。"""
    for scr in QGuiApplication.screens():
        if scr.name() == name:
            return scr
    return None


def _screen_for_monitor(pr: QRect) -> Optional[QScreen]:
    """按「Qt 逻辑尺寸 × 缩放比例」找出 Win32 那台显示器对应的 QScreen。

    Qt6 在 Windows 上 QScreen.name() 返回的是显示器型号（如 NE160QD2），
    拿不到 \\\\.\\DISPLAY1，所以靠尺寸比对最可靠。
    """
    screens = QGuiApplication.screens()
    best, best_err = None, 1e9
    for scr in screens:
        g = scr.geometry()
        dpr = scr.devicePixelRatio() or 1.0
        err = abs(g.width() * dpr - pr.width()) + abs(g.height() * dpr - pr.height())
        if err < best_err:
            best, best_err = scr, err
    if best is not None and best_err <= 8:
        return best
    # 分辨率就对不上时（例如系统做了虚拟化），退回名字匹配 / 主屏
    return _screen_by_name(_device_name_of(pr)) or QGuiApplication.primaryScreen()


def _device_name_of(pr: QRect) -> str:
    for name, r in _monitor_map().items():
        if r == pr:
            return name
    return ""


def physical_to_logical(rect: QRect) -> QRect:
    """Win32 坐标 → Qt 逻辑坐标。

    进程 DPI 感知状态不同，Win32 返回的可能是物理像素，也可能已被系统虚拟化成
    逻辑像素。用「显示器物理宽度 / Qt 逻辑宽度」实测比例来判断，两种情况都对。
    """
    if not _HAS_WIN32:
        return rect
    phys = _monitor_map()
    if not phys:
        return rect

    target = None
    for name, pr in phys.items():
        if pr.contains(rect.center()):
            target = (name, pr)
            break
    if target is None:
        best, best_area = None, -1
        for name, pr in phys.items():
            inter = pr.intersected(rect)
            area = max(0, inter.width()) * max(0, inter.height())
            if area > best_area:
                best, best_area = (name, pr), area
        target = best
    if target is None:
        return rect

    name, pr = target
    scr = _screen_by_name(name) or _screen_for_monitor(pr)
    if scr is None:
        return rect
    geo = scr.geometry()
    if geo.width() <= 0:
        return rect

    ratio = pr.width() / geo.width()
    if abs(ratio - 1.0) < 0.02:      # 已被系统虚拟化，坐标本来就是逻辑坐标
        return rect
    x = geo.x() + (rect.x() - pr.x()) / ratio
    y = geo.y() + (rect.y() - pr.y()) / ratio
    return QRect(round(x), round(y), max(1, round(rect.width() / ratio)),
                 max(1, round(rect.height() / ratio)))


def _hwnd_class(hwnd: int) -> str:
    if not _HAS_WIN32 or not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(wintypes.HWND(hwnd), buf, 256)
    return buf.value


def foreground_handle(exclude=(), exclude_pid: Optional[int] = None) -> Optional[int]:
    """当前前台窗口句柄；如果是本程序自己的窗口或桌面，返回 None。"""
    if not _HAS_WIN32:
        return None
    try:
        hwnd = int(_user32.GetForegroundWindow())
    except Exception:
        return None
    if not hwnd or hwnd in exclude:
        return None
    if _hwnd_class(hwnd) in _SKIP_CLASSES:
        return None
    if exclude_pid is not None:
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        if pid.value == exclude_pid:
            return None
    return hwnd


def process_family(pid: int, max_depth: int = 3) -> set:
    """pid 及其后代进程（启动器 / 引导程序会把真正的窗口交给子进程）。"""
    pids = {int(pid)}
    if not pid:
        return pids
    try:
        import psutil
        depth = 0
        frontier = [psutil.Process(pid)]
        while frontier and depth < max_depth:
            nxt = []
            for p in frontier:
                try:
                    for c in p.children():
                        if c.pid not in pids:
                            pids.add(c.pid)
                            nxt.append(c)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            frontier = nxt
            depth += 1
    except Exception:
        pass
    return pids


def window_of_pid(pid: int) -> Optional[int]:
    """进程（含子进程）的主窗口句柄（取面积最大的可见顶层窗口）。"""
    if not _HAS_WIN32 or not pid:
        return None
    pids = process_family(pid)
    found = []

    def _cb(hwnd, _):
        _collect_window(hwnd, pids, found)
        return True

    try:
        _user32.EnumWindows(_WNDENUMPROC(_cb), 0)
    except Exception:
        return None
    best, best_area = None, 0
    for hwnd in found:
        r = window_rect(hwnd)
        if r is None:
            continue
        area = r.width() * r.height()
        if area > best_area:
            best, best_area = hwnd, area
    return best


def _collect_window(hwnd, pids, out: list) -> None:
    p = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(p))
    if p.value not in pids:
        return
    if not _user32.IsWindowVisible(wintypes.HWND(hwnd)):
        return
    if _hwnd_class(int(hwnd)) in _SKIP_CLASSES:
        return
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetWindowTextW(wintypes.HWND(hwnd), buf, 256)
    if buf.value.strip():
        out.append(int(hwnd))


def window_rect(hwnd: Optional[int]) -> Optional[QRect]:
    """窗口的逻辑像素包围盒；最小化 / 已关闭 / 尺寸异常时返回 None。"""
    if not _HAS_WIN32 or not hwnd:
        return None
    try:
        if not _user32.IsWindow(wintypes.HWND(hwnd)) or _user32.IsIconic(wintypes.HWND(hwnd)):
            return None
    except Exception:
        return None

    rect = None
    try:  # 优先 DWM 外框，能去掉 Win10 窗口四周不可见的缩放边框
        r = _RECT()
        hr = _dwm.DwmGetWindowAttribute(wintypes.HWND(hwnd), 9,  # DWMWA_EXTENDED_FRAME_BOUNDS
                                        ctypes.byref(r), ctypes.sizeof(r))
        if hr == 0 and r.right > r.left and r.bottom > r.top:
            rect = QRect(r.left, r.top, r.right - r.left, r.bottom - r.top)
    except Exception:
        pass
    if rect is None:
        try:
            r = _RECT()
            if _user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r)):
                rect = QRect(r.left, r.top, r.right - r.left, r.bottom - r.top)
        except Exception:
            return None
    if rect is None or rect.width() < 160 or rect.height() < 120:
        return None
    return physical_to_logical(rect)


# ---------------------------------------------------------------- 布局
@dataclass
class Layout:
    rect: QRect                 # 叠加层在逻辑坐标下的位置与大小
    decode: Tuple[int, int]     # 解码目标尺寸（物理像素）
    scale: float                # 解码尺寸 / 逻辑尺寸，用作 QImage 的 devicePixelRatio
    ref: QRect                  # 计算时使用的参照区域（逻辑像素）
    ref_window: Optional[int]   # 参照窗口句柄（screen / fixed 模式为 None）

    @property
    def size(self) -> Tuple[int, int]:
        return self.rect.width(), self.rect.height()


def screen_for(index: int) -> QScreen:
    screens = QGuiApplication.screens()
    if 0 <= index < len(screens):
        return screens[index]
    return QGuiApplication.primaryScreen()


def compute(settings, aspect: float, src_size: Optional[Tuple[int, int]] = None,
            ref_window_rect: Optional[QRect] = None,
            ref_hwnd: Optional[int] = None) -> Layout:
    """根据设置和参照区域算出叠加层矩形与解码尺寸。"""
    if not aspect or aspect <= 0:
        aspect = 16 / 9
    mode = settings.get("size_ref", "screen")
    screen = screen_for(int(settings.get("screen_index", 0) or 0))
    sgeo = screen.availableGeometry()

    # 参照区域：屏幕 or 目标窗口（窗口取完整矩形，不用裁剪，否则贴边窗口会缩水）
    ref = sgeo
    if mode == "window" and ref_window_rect is not None and \
            ref_window_rect.width() >= 320 and ref_window_rect.height() >= 200:
        ref = ref_window_rect

    pct = int(settings.get("height_percent", 42) or 0)
    if mode == "fixed":
        h = max(40, min(2160, int(settings.get("fixed_height", 300) or 300)))
    else:
        h = ref.height() * max(5, min(100, pct)) / 100.0
    w = h * aspect

    # 上限：不超过参照宽度，也不超过屏幕本身（窗口比屏幕还大时以屏幕为准）
    max_w = min(ref.width() * 0.94, sgeo.width() * 0.98)
    if w > max_w:
        w = max_w
        h = w / aspect
    max_h = sgeo.height() * 0.98
    if h > max_h:
        h = max_h
        w = h * aspect
    w, h = max(2, round(w)), max(2, round(h))

    margin = int(settings.get("margin", 28) or 0)
    preset = settings.get("pos_preset", "bottom-right")
    if preset == "custom":
        # 自定义位置永远是屏幕绝对坐标，方便用户手动摆放
        x = sgeo.left() + int(settings.get("custom_x", 40) or 0)
        y = sgeo.top() + int(settings.get("custom_y", 40) or 0)
        ref = sgeo
    else:
        if preset == "bottom-left":
            x, y = ref.left() + margin, ref.bottom() - h - margin
        elif preset == "bottom-center":
            x, y = ref.left() + (ref.width() - w) // 2, ref.bottom() - h - margin
        elif preset == "center":
            x, y = ref.left() + (ref.width() - w) // 2, ref.top() + (ref.height() - h) // 2
        elif preset == "top-left":
            x, y = ref.left() + margin, ref.top() + margin
        elif preset == "top-right":
            x, y = ref.right() - w - margin, ref.top() + margin
        else:
            x, y = ref.right() - w - margin, ref.bottom() - h - margin
        # 目标窗口可能在屏幕外 / 比屏幕大，最后一步钳回屏幕内
        x = max(sgeo.left(), min(x, sgeo.right() - w + 1))
        y = max(sgeo.top(), min(y, sgeo.bottom() - h + 1))

    rect = QRect(round(x), round(y), int(w), int(h))

    # 解码尺寸：按所在屏幕的 DPI 走物理像素；不超过素材原始分辨率
    dpr = float(screen.devicePixelRatio() or 1.0)
    tw = int(round(w * dpr))
    if src_size:
        tw = min(tw, max(2, int(src_size[0])))
    tw = max(2, tw)
    scale = tw / w
    th = max(2, int(round(h * scale)))
    return Layout(rect=rect, decode=(tw, th), scale=scale, ref=ref,
                  ref_window=ref_hwnd)


def is_visually_same(a: Optional[Layout], b: Optional[Layout], tol: int = 2) -> bool:
    """位置/尺寸变化是否小到可以忽略（避免每帧抖动重排）。"""
    if a is None or b is None:
        return False
    ra, rb = a.rect, b.rect
    return (abs(ra.x() - rb.x()) <= tol and abs(ra.y() - rb.y()) <= tol and
            abs(ra.width() - rb.width()) <= tol and abs(ra.height() - rb.height()) <= tol
            and a.decode == b.decode)
