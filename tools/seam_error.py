"""量化接缝误差：逐角度看「素材里的环」和「续画出来的环」差几像素。"""
from __future__ import annotations

import glob
import sys

import cv2
import numpy as np

sys.path.insert(0, ".")
from core import burst as B  # noqa: E402


def ring_radius_by_angle(e, off, k0):
    """以 off 为极点，逐角度找环的峰半径。"""
    centers = B._centers(B.PINPOINT_BINS)
    pol = B._polar_map([e], off)[0]
    pk, arg = B._row_peaks(pol, k0)
    top, idx = B._kept_rows(pk)
    out = {}
    for row in idx:
        out[int(np.degrees(np.radians(row)))] = (float(centers[arg[row]]), float(pk[row]))
    return pol, pk, arg, idx, centers


def main():
    for path in sorted(glob.glob("assets/*.mp4")):
        name = "起司" if "起司" in path else "语言层"
        b = B.detect(path)
        if not b.get("enabled"):
            print(name, "无光波")
            continue
        half = 214.0
        off = tuple(b.get("offset") or (0, 0))
        k0 = int(np.clip(float(b["logo_r"]) * 1.05 / B.R_MAX * B.PINPOINT_BINS, 0,
                         B.PINPOINT_BINS - 2))
        print(f"\n=== {name}  offset={off} ref_r={b['ref_r']} ref_curve={b['ref_curve']} ===")
        ts = [b["ref"] - 0.06, b["ref"] - 0.03, b["ref"], b["ref"] + 0.03, b["ref"] + 0.06]
        for t in ts:
            radius, op = B.radius_at(b, t, half, 700)
            outer, stops = B.ring_profile(b, radius, half, opacity=1.0)
            if not stops:
                continue
            # 续画的环在 t 时刻的半径（以 off 为圆心）= 剖面峰 + 曲线增量
            prof = b["profile"]
            r_draw = max(prof, key=lambda p: p[4])[0] + (radius - float(b["ref_curve"]))
            rgb, _ = B._grab(path, t, B.PROFILE_W)
            _, e = B.emission(rgb, b["screen"])
            e = cv2.GaussianBlur(e, (3, 3), 0)
            pol, pk, arg, idx, centers = ring_radius_by_angle(e, off, k0)
            errs = []
            for row in idx:
                # 两边都是以 off 为圆心量的半径，直接相减
                errs.append(centers[arg[row]] - r_draw)
            errs = np.array(errs) * half
            print(f"  t={t:.3f} r_draw={r_draw:.3f} 弧={len(idx) * 100 // 360:3d}% "
                  f"误差(px) 均值={errs.mean():+6.1f} 最大={np.abs(errs).max():6.1f} "
                  f"标准差={errs.std():5.1f}")


if __name__ == "__main__":
    main()
