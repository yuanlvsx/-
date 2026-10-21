"""预览：光波续到全屏时，素材画框处的接缝是否对得上。

和叠加层走完全相同的绘制顺序：先在整块画布上画矢量光环，再把做了边缘
径向淡出的素材盖上去。所以这张图和真机上的效果一致。
"""
from __future__ import annotations

import glob
import sys

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QRadialGradient
from PySide6.QtWidgets import QApplication

sys.path.insert(0, ".")
from core import burst as burst_mod  # noqa: E402
from core.keyer import ChromaKeyer, probe  # noqa: E402
from core.player import edge_mask  # noqa: E402

CW, CH = 1440, 900
BH = 428
KEYER = ChromaKeyer("green", 42, 26, 0.85, 60, True)
CACHE: dict = {}
ASPECT = {"v": 16 / 9}


def _box():
    """画框尺寸按素材本身的宽高比算（不能硬拉成 16:9，否则环会变椭圆）。"""
    bw = int(round(BH * ASPECT["v"]))
    return QRect(CW - 24 - bw, CH - 24 - BH, bw, BH)


def frame(path, t):
    key = (path, round(t, 4))
    if key in CACHE:
        return CACHE[key]
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * fps)))
    ok, fr = cap.read()
    cap.release()
    if not ok:
        return None
    b = _box()
    bgra = KEYER.apply(fr, (b.width(), b.height()))
    bgra[:, :, 3] = cv2.multiply(bgra[:, :, 3], edge_mask(BH, b.width()), scale=1.0 / 255.0)
    img = QImage(bgra.data, b.width(), BH, b.width() * 4, QImage.Format_ARGB32).copy()
    CACHE[key] = img
    return img


def compose(path, burst, t):
    canvas = QImage(CW, CH, QImage.Format_ARGB32_Premultiplied)
    canvas.fill(QColor(28, 30, 36))
    p = QPainter(canvas)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(QColor(44, 46, 54))
    for x in range(0, CW, 90):
        p.drawLine(x, 0, x, CH)
    for y in range(0, CH, 90):
        p.drawLine(0, y, CW, y)
    box = _box()
    half = BH / 2.0
    cx, cy = box.center().x(), box.center().y()
    reach = max(np.hypot(cx, cy), np.hypot(CW - cx, cy),
                np.hypot(cx, CH - cy), np.hypot(CW - cx, CH - cy))

    radius, op = burst_mod.radius_at(burst, t, half, reach)
    outer, stops = burst_mod.ring_profile(burst, radius, half, opacity=op)
    off = burst.get("offset") or (0.0, 0.0)
    qx, qy = cx + float(off[0]) * half, cy + float(off[1]) * half
    if stops and outer > 2:
        g = QRadialGradient(QPointF(qx, qy), outer)
        for pos, c in stops:
            g.setColorAt(pos, QColor(c[0], c[1], c[2], c[3]))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPointF(qx, qy), outer, outer)

    img = frame(path, t)
    if img is not None:
        p.drawImage(box, img)
    p.end()
    return canvas, radius, op


def main():
    app = QApplication(sys.argv)  # noqa: F841
    only2 = len(sys.argv) > 1
    for path in sorted(glob.glob("assets/*.mp4")):
        name = "起司" if "起司" in path else "语言层"
        info = probe(path)
        if info and info.height:
            ASPECT["v"] = info.width / info.height
            CACHE.clear()
        b = burst_mod.detect(path, KEYER)
        if not b.get("enabled"):
            print(name, "无光波")
            continue
        print(f"\n{name}: start={b['start']} end={b['end']} ref={b['ref']} "
              f"ref_r={b['ref_r']} ref_curve={b.get('ref_curve')} speed={b['speed']}")
        print("  profile:", [(round(x[0], 2), x[4]) for x in b["profile"]][:6], "...")
        times = [b["ref"] - 0.04 + i * 0.04 for i in range(8)]
        tiles = []
        box = _box()
        for i, t in enumerate(times):
            img, r, op = compose(path, b, t)
            img.save(f"seam_{name}_{i}.png")
            crop = img.copy(int(box.left() - 150), int(box.top() - 150),
                            box.width() + 300, box.height() + 300)
            crop = crop.scaled(int(crop.width() * 0.62), int(crop.height() * 0.62),
                               Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            tiles.append((crop, t, r, op))
        tw, th = tiles[0][0].width(), tiles[0][0].height()
        grid = QImage(tw * 2, th * 4, QImage.Format_RGB32)
        gp = QPainter(grid)
        for i, (tile, t, r, op) in enumerate(tiles):
            x, y = (i % 2) * tw, (i // 2) * th
            gp.drawImage(x, y, tile)
            gp.setPen(QColor(255, 220, 120))
            gp.drawText(x + 10, y + 22, f"{t:.2f}s r={r:.2f} op={op:.2f}")
        gp.end()
        grid.save(f"grid_{name}.png")
        print("  ->", f"grid_{name}.png")


if __name__ == "__main__":
    main()
