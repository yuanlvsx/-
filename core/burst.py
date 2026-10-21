"""光波（冲击环）检测与重建。

素材里的"发射"是绕 Logo 中心向外扩散的一圈光环，它在画幅边缘被裁掉，
所以放在小窗口里播到一半就没了。这里做三件事：

1. `analyze()` 离线测出光波的时间窗、扩散速度、每帧半径；
2. `radial_profile()` 在参考帧上取一条径向剖面（颜色 + 柔和的发光强度）；
3. `ring_profile()` 在播放时把这条剖面按当前半径平移，生成渐变色标，
   让光环从窗口里无缝续到整个屏幕。

关键点：半径和强度都用「相对绿幕底色的发光量」来量，而不是抠像后的 alpha。
发光是加色混色，抠像的 alpha 在辉光区会饱和成一片（量出来 0.4 个半径宽的
死白带），用它当锚点会让续画的光环整体偏大半个环宽，接缝必定错位；
而"幕布色加了多少光"对白环、红环都成立，且不会被饱和。

半径统一用「画面半高 = 1.0」归一化，换任何分辨率都不会错位。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from .keyer import ChromaKeyer

PROBE_W, PROBE_H = 256, 144      # 检测用低分辨率
PROFILE_W = 720                  # 取剖面的分辨率
R_MAX = 2.10                     # 画面内最大归一化半径（约等于对角线）
BINS = 160                       # 半径分箱数
ANG_BINS = 512                   # 极坐标展开的角度行数
CURVE_REF = 0.35                 # 用「峰值这个比例以上」的环带来算环心半径
SATURATED_R = 1.88               # 超过这个半径，光环已被画幅裁掉大半
MAX_EXTEND = 1.25                # 光环续画的最长时间（秒）


# ---------------------------------------------------------------- 基础
def screen_color(rgb: np.ndarray) -> np.ndarray:
    """估幕布底色：取四角的中位数（动画主体在中央，四角是净幕布）。"""
    h, w = rgb.shape[:2]
    k = max(4, min(h, w) // 12)
    corners = np.concatenate([
        rgb[:k, :k].reshape(-1, 3), rgb[:k, -k:].reshape(-1, 3),
        rgb[-k:, :k].reshape(-1, 3), rgb[-k:, -k:].reshape(-1, 3),
    ])
    return np.median(corners, axis=0)


def emission(rgb: np.ndarray, base: Optional[Sequence[float]] = None):
    """相对幕布底色的发光量。

    返回 (逐通道超出量, 发光强度)。加法混色下 P = S + G，所以 P - S 就是这
    块像素自己发的光；比幕布暗的地方（阴影、暗带）一律记 0，不参与重绘。
    """
    S = np.asarray(base if base is not None else screen_color(rgb), np.float32)
    exc = np.clip(rgb - S[None, None, :], 0.0, 255.0)
    return exc, exc.max(axis=2)


def _polar(abs_e: np.ndarray, bins: int = BINS, r_max: float = R_MAX,
           center: Tuple[float, float] = (0.0, 0.0)) -> np.ndarray:
    """把发光强度图沿半径展开，返回每个半径环上的最大值曲线。

    用极坐标重采样一次拿整条曲线：比逐帧 sort/percentile 快一个量级，
    而且对画幅裁切天然免疫——只剩一段圆弧时，环上最大值仍然是真实的环亮度。
    `center` 是相对画框中心的偏移（归一化），光环圆心不在正中时用它当极点。
    """
    h, w = abs_e.shape[:2]
    half = (h - 1) / 2.0
    max_r = max(2.0, r_max * half)
    px = ((w - 1) / 2.0 + center[0] * half, (h - 1) / 2.0 + center[1] * half)
    polar = cv2.warpPolar(abs_e, (bins, ANG_BINS), px, max_r,
                          cv2.WARP_POLAR_LINEAR | cv2.INTER_LINEAR |
                          cv2.WARP_FILL_OUTLIERS)
    return polar.max(axis=0)          # 每个半径取最亮的角度


def core_radius(centers: np.ndarray, curve: np.ndarray, r_min: float = 0.0,
                half_width: float = 0.42) -> Tuple[float, float]:
    """曲线在 r_min 之外的「环心半径」与其峰值。

    先找 r_min 之外最亮的那个半径，再只取它附近 ±half_width 内、亮度达峰值
    35% 的环带做加权质心。这样 Logo 的辉光长尾不会把质心往里拽，环被画幅
    裁掉一部分时也不受影响，逐帧之间可比。
    """
    ok = centers >= r_min
    if not ok.any():
        return 0.0, 0.0
    v = np.where(ok, curve, -1.0)
    k = int(v.argmax())
    peak = float(v[k])
    if peak < 1.0:
        return 0.0, 0.0
    peak_r = float(centers[k])
    band = ok & (np.abs(centers - peak_r) <= half_width) & (curve >= peak * CURVE_REF)
    w = np.where(band, curve, 0.0)
    tot = float(w.sum())
    if tot <= 1e-6:
        return peak_r, peak
    return float((centers * w).sum() / tot), peak


def _centers(bins: int = BINS, r_max: float = R_MAX) -> np.ndarray:
    return (np.arange(bins) + 0.5) * r_max / bins


# ---------------------------------------------------------------- 取帧
def _grab(path: str, at: float, width: int):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None, 30.0
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(round(at * fps))))
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return None, fps
    h = max(2, width * frame.shape[0] // frame.shape[1])
    f = cv2.resize(frame, (width, h), interpolation=cv2.INTER_AREA)
    return f[:, :, ::-1].astype(np.float32), fps        # BGR -> RGB


def base_color(path: str, samples: int = 9) -> List[float]:
    """从整段素材里采样干净帧，取一个稳定的幕布底色。"""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return [0.0, 255.0, 0.0]
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 1)
    got = []
    for i in range(samples):
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(n * (i + 0.5) / samples)))
        ok, frame = cap.read()
        if not ok:
            continue
        small = cv2.resize(frame, (160, max(2, 160 * frame.shape[0] // frame.shape[1])),
                           interpolation=cv2.INTER_AREA)
        got.append(screen_color(small[:, :, ::-1].astype(np.float32)))
    cap.release()
    if not got:
        return [0.0, 255.0, 0.0]
    return [float(x) for x in np.median(np.array(got), axis=0)]


# ---------------------------------------------------------------- 检测
def analyze(path, keyer: Optional[ChromaKeyer] = None,
            center: Tuple[float, float] = (0.0, 0.0),
            ref_at: Optional[float] = None) -> Dict:
    """扫描整段素材，找出光波发射的时间窗、扩散速度与半径曲线。

    `center` 是光环圆心相对画框中心的偏移：细环被画幅裁掉一部分时，从画框
    中心量出来的半径会随"看得见哪段圆弧"漂移，用光环自己的圆心量才逐帧可比。
    """
    base = base_color(path)
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return {"enabled": False, "auto": False}
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    centers = _centers()

    polar: List[np.ndarray] = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        small = cv2.resize(frame, (PROBE_W, PROBE_H), interpolation=cv2.INTER_AREA)
        _, e = emission(small[:, :, ::-1].astype(np.float32), base)
        e = cv2.GaussianBlur(e, (3, 3), 0)
        polar.append(_polar(e, center=center))
    cap.release()
    if len(polar) < 4:
        return {"enabled": False, "auto": False}

    # Logo 自身的外缘：安静帧里发光消失的半径（发光帧只占少数，取中位数）
    ext = []
    for cv_ in polar:
        pk = float(cv_.max())
        if pk < 1.0:
            continue
        idx = np.where(cv_ > pk * 0.10)[0]
        ext.append(float(centers[idx[-1]]) if idx.size else 0.0)
    logo_r = float(np.median(ext)) if ext else 0.60
    if logo_r <= 0.05:
        logo_r = 0.60

    radii: List[float] = []
    amps: List[float] = []
    for cv_ in polar:
        r, amp = core_radius(centers, cv_, r_min=logo_r * 1.02)
        radii.append(r)
        amps.append(amp)
    top_amp = float(np.percentile(amps, 97)) or 255.0

    hot = [f for f in range(len(radii))
           if radii[f] > logo_r * 1.22 and amps[f] > top_amp * 0.28]
    if len(hot) < 2:
        return {"enabled": False, "auto": False}

    # 最长的一段连续区间（允许 3 帧空档）
    groups: List[List[int]] = [[hot[0]]]
    for f in hot[1:]:
        if f - groups[-1][-1] <= 4:
            groups[-1].append(f)
        else:
            groups.append([f])
    group = max(groups, key=len)
    if radii[group[-1]] <= radii[group[0]] * 1.15:
        return {"enabled": False, "auto": False}

    curve: List[List[float]] = []
    for f in group:
        r = round(float(radii[f]), 3)
        if curve:
            if r < curve[-1][1] - 0.12:
                break                   # 掉回 Logo 半径 = 光环已经飞出画幅
            if r <= curve[-1][1] + 0.01:
                continue                # 分箱抖动的平台，跳过
        curve.append([round(f / fps, 3), r])
    if len(curve) < 2:
        return {"enabled": False, "auto": False}

    # 扩散速度：只用尾部几个没被画幅裁到的样本拟合（光环在减速，取尾速更准）
    fit = [(t, r) for t, r in curve if r <= SATURATED_R - 0.05][-4:]
    if len(fit) >= 2:
        ts = np.array([c[0] for c in fit], np.float64)
        rs = np.array([c[1] for c in fit], np.float64)
        speed = float(np.polyfit(ts, rs, 1)[0])
    else:
        speed = 3.0
    speed = max(1.0, min(20.0, speed))

    # 参考帧：光环尽量大、又还没被裁得太厉害的帧（第二遍沿用第一遍选的帧，
    # 免得两次的剖面和曲线对应到不同时刻）
    if ref_at is not None:
        ref_t = float(ref_at)
        ref_r = _curve_at(curve, ref_t)
    else:
        target = min(1.45, curve[-1][1])
        ref_t, ref_r = curve[0]
        for t, r in curve:
            if r <= target:
                ref_t, ref_r = t, r
            else:
                if abs(r - target) < abs(ref_r - target):
                    ref_t, ref_r = t, r
                break

    return {
        "enabled": True,
        "auto": True,
        "fps": round(fps, 3),
        "logo_r": round(logo_r, 3),
        "start": round(curve[0][0], 3),
        "end": round(curve[-1][0], 3),
        "ref": round(ref_t, 3),
        "ref_r": round(ref_r, 3),
        "speed": round(speed, 3),
        "curve": curve,
        "screen": [round(v, 1) for v in base],
        "profile": [],
    }


# ---------------------------------------------------------------- 剖面
PINPOINT_BINS = 360              # 精细径向采样
PINPOINT_ANG = 360               # 角度采样（1°）
PINPOINT_SPAN = 0.55             # 按峰对齐后每侧取多宽的截面
KEEP_RATIO = 0.35                # 角度行峰值达到全局峰值这个比例才算"看得到环"


def _polar_map(planes: Sequence[np.ndarray], center: Tuple[float, float],
               bins: int = PINPOINT_BINS, ang: int = PINPOINT_ANG) -> List[np.ndarray]:
    """把若干通道展开成极坐标图：[角度行, 半径列]。"""
    h, w = planes[0].shape[:2]
    half = (h - 1) / 2.0
    cx = (w - 1) / 2.0 + center[0] * half
    cy = (h - 1) / 2.0 + center[1] * half
    flags = cv2.WARP_POLAR_LINEAR | cv2.INTER_LINEAR | cv2.WARP_FILL_OUTLIERS
    return [cv2.warpPolar(p, (bins, ang), (cx, cy), R_MAX * half, flags) for p in planes]


def _row_peaks(pol: np.ndarray, k0: int = 0) -> Tuple[np.ndarray, np.ndarray]:
    """每个角度行上的峰值与峰位（半径分箱下标）。

    `k0` 之前的半径不参与（Logo 本身比光环还亮，必须排除掉）。
    """
    sub = pol[:, k0:] if k0 > 0 else pol
    return sub.max(axis=1), sub.argmax(axis=1) + k0


def _kept_rows(pk: np.ndarray) -> Tuple[float, np.ndarray]:
    """光环被画幅裁掉时只有一部分角度看得到，返回这些角度。"""
    top = float(pk.max()) if pk.size else 0.0
    if top < 1.0:
        return 0.0, np.zeros(0, np.int64)
    return top, np.nonzero(pk >= top * KEEP_RATIO)[0]


def _offset_from(rs: np.ndarray, ang: np.ndarray) -> Tuple[float, float]:
    """环心相对画框中心的偏移。

    半径为 R、圆心偏移 o 时，从画框中心沿单位向量 u 量到的半径约等于
    R + o·u，所以拿每角度的半径对 (cos, sin) 做线性拟合就解出来了。
    """
    if len(rs) < 8:
        return 0.0, 0.0
    A = np.c_[np.ones(len(rs)), np.cos(ang), np.sin(ang)]
    sol, *_ = np.linalg.lstsq(A, rs, rcond=None)
    ox, oy = float(sol[1]), float(sol[2])
    if not (abs(ox) < 0.25 and abs(oy) < 0.25):
        return 0.0, 0.0
    return ox, oy


def _sharpness(e: np.ndarray, center: Tuple[float, float], r_guess: float,
               span: float = 0.30) -> float:
    """同心度打分：环带内「峰值² / 半高宽」。

    圆心越准，环在极坐标图上越是一条直线，半高宽越小，分数越高。
    """
    pol = _polar_map([e], center, bins=240, ang=180)[0]
    centers = _centers(240)
    v = pol.max(axis=0)[np.abs(centers - r_guess) <= span]
    if not v.size:
        return 0.0
    peak = float(v.max())
    if peak < 1.0:
        return 0.0
    hw = max(1, int((v >= peak * 0.5).sum()))
    return peak * peak / hw


def pinpoint(path, at: float, screen: Optional[Sequence[float]] = None,
             r_min: float = 0.0, r_guess: float = 1.3) -> Dict:
    """在 at 秒处精确测量光环：截面、半径、圆心偏移、主色。

    细环（像语言层素材那根红线）若从画框中心按半径取最亮值，会被抹成一条
    宽色带——因为环的圆心并不在画框正中。这里改成"逐角度找峰、按峰对齐后
    叠加"：每个角度的截面先平移到同一位置再平均，粗细和颜色都是真实的；
    峰半径随角度的起伏再拟合出圆心偏移，画的时候按这个圆心画。

    颜色直接取原始像素、不减幕布底色：幕布的绿通道通常已经顶到 255，减完
    绿色发光会被算成 0，白环会偏成品红。
    """
    rgb, _ = _grab(path, at, PROFILE_W)
    if rgb is None:
        return {}
    base = screen if screen is not None else base_color(path)
    _, e = emission(rgb, base)
    e = cv2.GaussianBlur(e, (3, 3), 0)
    planes = [e, rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]]
    centers = _centers(PINPOINT_BINS)

    # 先按画框中心粗测，用峰半径随角度的起伏解出圆心偏移
    k0 = int(np.clip(r_min / R_MAX * PINPOINT_BINS, 0, PINPOINT_BINS - 2))
    pol0 = _polar_map([e], (0.0, 0.0))[0]
    pk0, arg0 = _row_peaks(pol0, k0)
    _, idx0 = _kept_rows(pk0)
    ox, oy = _offset_from(centers[arg0[idx0]], np.radians(idx0))
    # warpPolar 的角度方向与实际图像 y 轴朝向未必一致，代回去比一比再定符号
    if ox or oy:
        best = (_sharpness(e, (0.0, 0.0), r_guess), 0.0, 0.0)
        for cx_, cy_ in ((ox, oy), (-ox, oy), (ox, -oy), (-ox, -oy)):
            sc = _sharpness(e, (cx_, cy_), r_guess)
            if sc > best[0] * 1.02:
                best = (sc, cx_, cy_)
        ox, oy = best[1], best[2]

    # 以环心为原点重取极坐标，逐角度按峰对齐叠加
    pol = _polar_map(planes, (ox, oy))
    pk, arg = _row_peaks(pol[0], k0)
    top, idx = _kept_rows(pk)
    if len(idx) < 6:
        return {}
    rs = centers[arg[idx]]
    wts = pk[idx]
    r_ref = float((rs * wts).sum() / wts.sum())

    grid = np.linspace(-PINPOINT_SPAN, PINPOINT_SPAN, 121)
    acc = np.zeros(len(grid), np.float64)
    for row in idx:
        acc += np.interp(r_ref + grid, centers, pol[0][row]) * pk[row]
    acc /= float(wts.sum())

    # 主色：环峰处的原始像素，按峰值加权
    col = np.zeros(3, np.float64)
    for row in idx:
        k = int(arg[row])
        if k <= 0:
            continue
        for c in range(3):
            col[c] += float(pol[c + 1][row, k]) * pk[row]
    col /= float(wts.sum())
    hi = max(col) or 255.0
    core = [min(255.0, float(col[c]) * 255.0 / hi) for c in range(3)]

    if float(acc.max()) < 1.0:
        return {}
    out: List[List[float]] = []
    pk_a = float(acc.max())
    for i, d in enumerate(grid):
        r = r_ref + d
        if r < max(0.05, r_min):
            continue
        a = float(acc[i]) / pk_a
        if a < 0.045:
            continue
        a = min(1.0, a) ** 0.92
        out.append([round(r, 4), int(core[0]), int(core[1]), int(core[2]),
                    int(round(a * 255))])
    if len(out) < 3:
        return {}

    while len(out) > 3 and out[-1][4] < 12:
        out.pop()
    while len(out) > 3 and out[0][4] < 12:
        out.pop(0)
    for i in range(1, len(out) - 1):
        for c in range(1, 5):
            out[i][c] = int(round((out[i - 1][c] + out[i][c] * 2 + out[i + 1][c]) / 4))
    return {
        "profile": out,
        "radius": round(r_ref, 4),
        "offset": [round(ox, 4), round(oy, 4)],
        "color": [int(c) for c in core],
        "arc": round(len(idx) / float(len(pk)), 3),
    }


def radial_profile(path, at: float, keyer: Optional[ChromaKeyer] = None,
                   r_min: float = 0.0, samples: int = 96,
                   screen: Optional[Sequence[float]] = None) -> List[List[float]]:
    """兼容入口：只要截面。"""
    return pinpoint(path, at, screen, r_min=r_min).get("profile", [])


def profile_radius(prof: Sequence[Sequence[float]]) -> float:
    """剖面自身的环心半径（峰值位置）。"""
    if not prof:
        return 0.0
    c = np.array([p[0] for p in prof], np.float64)
    v = np.array([p[4] for p in prof], np.float64)
    return float(c[int(v.argmax())])


def _curve_at(curve: Sequence[Sequence[float]], t: float) -> float:
    """在半径曲线上插值出 t 时刻的半径。"""
    if not curve:
        return 0.0
    if t <= curve[0][0]:
        return float(curve[0][1])
    if t >= curve[-1][0]:
        return float(curve[-1][1])
    for i in range(len(curve) - 1):
        ta, ra = curve[i][0], curve[i][1]
        tb, rb = curve[i + 1][0], curve[i + 1][1]
        if ta <= t <= tb:
            f = 0.0 if tb - ta < 1e-9 else (t - ta) / (tb - ta)
            return float(ra + (rb - ra) * f)
    return float(curve[-1][1])


def detect(path, keyer: Optional[ChromaKeyer] = None) -> Dict:
    """检测 + 取剖面，返回可直接存进配置的 burst 字典。

    两遍：先用画框中心扫一遍找到光波窗口和参考帧，在参考帧上量出光环圆心
    的偏移，再用这个圆心扫第二遍拿半径曲线。细环被裁掉一部分后，从画框中心
    量的半径会随可见弧度变化而漂移，用光环自己的圆心量才不会。
    """
    keyer = keyer or ChromaKeyer("green", 42, 26, 0.85, 60, True)
    first = analyze(path, keyer)
    if not first.get("enabled"):
        return first
    r_min = max(0.0, float(first.get("logo_r") or 0.55) * 1.05)
    pin = pinpoint(path, first["ref"], first.get("screen"), r_min=r_min,
                   r_guess=float(first.get("ref_r") or 1.3))
    if not pin.get("profile"):
        return {"enabled": False, "auto": False}

    off = tuple(pin.get("offset") or (0.0, 0.0))
    info = first
    if abs(off[0]) > 2e-3 or abs(off[1]) > 2e-3:
        again = analyze(path, keyer, center=off, ref_at=first["ref"])
        if again.get("enabled") and len(again.get("curve") or []) >= 2:
            info = again

    info["profile"] = pin["profile"]
    info["ref_r"] = pin["radius"]
    info["offset"] = pin["offset"]
    info["color"] = pin["color"]
    info["ref"] = first["ref"]
    # 参考帧标定：剖面是在高分辨率上按环心量的，半径曲线是在低分辨率上量的，
    # 两者对同一帧会差几个百分点。播放时用曲线在参考帧上的读数当零点，
    # 参考帧处偏移严格为 0，接缝一定对得上。
    info["ref_curve"] = round(_curve_at(info["curve"], info["ref"]), 4)
    return info


# ---------------------------------------------------------------- 播放时
def radius_at(burst: Dict, t: float, half_h: float = 336.0,
              reach_px: float = 0.0) -> Tuple[float, float]:
    """播放时间 t（源视频绝对秒）→ (归一化半径, 不透明度)。

    实测区间外按测得的速度继续外扩，同时逐渐淡出；`reach_px` 给出画布上
    最远需要覆盖的距离（像素），用于决定淡出终点。
    """
    curve = burst.get("curve") or []
    if not curve:
        return 0.0, 0.0
    t0 = curve[0][0]
    if t <= curve[-1][0]:
        if t < t0:
            # 实测开始前最多回推 60ms（用第一段的速度），并淡入；再早就不画，
            # 那时半径只能瞎猜，偏一点就会和素材里的环错开成两根线
            back = t0 - t
            if back > 0.06 or len(curve) < 2:
                return 0.0, 0.0
            span = curve[1][0] - curve[0][0]
            seg = (curve[1][1] - curve[0][1]) / span if span > 1e-6 else 0.0
            r = curve[0][1] - seg * back
            return max(0.0, r), (1.0 - back / 0.06) * _gate(r)
        fade = min(1.0, (t - (t0 - 0.06)) / 0.06)
        for i in range(len(curve) - 1):
            ta, ra = curve[i]
            tb, rb = curve[i + 1]
            if ta <= t <= tb:
                f = 0.0 if tb - ta < 1e-6 else (t - ta) / (tb - ta)
                r = ra + (rb - ra) * f
                return r, fade * _gate(r)
        return curve[-1][1], fade * _gate(curve[-1][1])

    speed = float(burst.get("speed") or 3.0)
    t_last, r_last = curve[-1]
    r = r_last + speed * (t - t_last)
    if reach_px > 0 and half_h > 0:
        target = max(r_last * 1.15, reach_px / half_h)
        span = max(0.22, min(MAX_EXTEND, (target - r_last) / speed))
        op = 1.0 - (t - t_last) / span
        return r, max(0.0, min(1.0, op)) ** 1.3
    op = 1.0 - (t - t_last) / 0.45
    return r, max(0.0, min(1.0, op))


def _gate(radius: float) -> float:
    """光环还在画框内部时不需要补画（会和素材重复），接近边框才淡入。"""
    lo, hi = 0.92, 1.04
    if radius <= lo:
        return 0.0
    if radius >= hi:
        return 1.0
    t = (radius - lo) / (hi - lo)
    return t * t * (3 - 2 * t)


def ring_profile(burst: Dict, radius: float, half_h: float,
                 profile: Optional[List] = None,
                 opacity: float = 1.0) -> Tuple[float, List[Tuple[float, Tuple[int, int, int, int]]]]:
    """把径向剖面平移到当前半径，返回 (外圈像素半径, 色标列表)。

    用「平移」而不是「缩放」：素材里的光环扩散时厚度基本不变，
    平移才能保持原来的线条粗细和辉光宽度。
    """
    prof = profile if profile is not None else (burst.get("profile") or [])
    if not prof or radius <= 0:
        return 0.0, []
    anchor = burst.get("ref_curve")
    if not anchor:
        anchor = burst.get("ref_r") or 0.0
    shift = radius - float(anchor)
    pts: List[Tuple[float, Tuple[int, int, int, int]]] = []
    for p in prof:
        rr = float(p[0]) + shift
        if rr <= 0.02:
            continue
        pts.append((rr, (int(p[1]), int(p[2]), int(p[3]), int(p[4]))))
    if not pts:
        return 0.0, []
    outer = pts[-1][0] * half_h
    if outer <= 1:
        return 0.0, []
    stops = [(min(1.0, rr * half_h / outer),
              (c[0], c[1], c[2], int(max(0, min(255, c[3] * opacity)))))
             for rr, c in pts]
    # 位置必须严格递增
    fixed: List[Tuple[float, Tuple[int, int, int, int]]] = []
    for pos, c in stops:
        if fixed and pos <= fixed[-1][0]:
            pos = min(1.0, fixed[-1][0] + 1e-4)
        fixed.append((pos, c))
    # 首尾补透明色标：否则 Qt 会用首/末色标把圆内/圆外整片填满（PadSpread）
    if fixed and fixed[0][0] > 0.0:
        c = fixed[0][1]
        fixed.insert(0, (0.0, (c[0], c[1], c[2], 0)))
    if fixed and fixed[-1][0] < 1.0:
        c = fixed[-1][1]
        fixed.append((1.0, (c[0], c[1], c[2], 0)))
    return outer, fixed
