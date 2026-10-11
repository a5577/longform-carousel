#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画这张示例的封面插画（1440×976，扁平风黄昏小站）。

用法：
    python make_cover.py [输出路径]

为什么是画出来的：这张图要长期放在开源仓库里当示例，用代码画就没有素材授权问题，
谁 clone 下来都能重跑出一模一样的图。想换成自己拍的照片或 $imagegen 生成的图，
把 cover.png 替掉即可。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

W, H = 1440, 976
S = 2                      # 画布放大倍数，画完再缩回去，等于抗锯齿

SKY_TOP = (246, 220, 174)
SKY_BOT = (232, 178, 127)
SUN = (251, 240, 210)
HALO = (250, 232, 196)
HILL_FAR = (140, 156, 119)
HILL_NEAR = (109, 127, 94)
PLATFORM = (201, 191, 166)
PLATFORM_EDGE = (179, 168, 143)
INK = (44, 56, 51)
INK_SOFT = (58, 74, 67)
WARM = (247, 227, 188)


def rect(d, x0, y0, x1, y1, color):
    d.rectangle((x0 * S, y0 * S, x1 * S, y1 * S), fill=color)


def rrect(d, x0, y0, x1, y1, r, color):
    d.rounded_rectangle((x0 * S, y0 * S, x1 * S, y1 * S), radius=r * S, fill=color)


def ellipse(d, cx, cy, rx, ry, color, outline=None, width=0):
    box = ((cx - rx) * S, (cy - ry) * S, (cx + rx) * S, (cy + ry) * S)
    d.ellipse(box, fill=color, outline=outline, width=int(width * S))


def line(d, pts, color, w):
    d.line([(x * S, y * S) for x, y in pts], fill=color, width=int(w * S), joint="curve")


def poly(d, pts, color):
    d.polygon([(x * S, y * S) for x, y in pts], fill=color)


def sky(img):
    px = img.load()
    top, bot = SKY_TOP, SKY_BOT
    for y in range(H * S):
        t = y / (H * S - 1)
        c = tuple(round(top[i] + (bot[i] - top[i]) * t) for i in range(3))
        for x in range(W * S):
            px[x, y] = c


def build() -> Image.Image:
    img = Image.new("RGB", (W * S, H * S), SKY_TOP)
    sky(img)
    d = ImageDraw.Draw(img, "RGBA")

    # 夕阳
    ellipse(d, 1062, 214, 168, 168, (*HALO, 70))
    ellipse(d, 1062, 214, 96, 96, (*SUN, 235))

    # 归鸟
    for cx, cy, k in ((300, 176, 1.0), (372, 140, 0.8), (438, 198, 0.9)):
        line(d, [(cx - 22 * k, cy), (cx, cy - 12 * k), (cx + 22 * k, cy)], (*INK_SOFT, 190), 4)

    # 远近两层山
    poly(d, [(0, 626), (180, 540), (352, 596), (560, 512), (760, 584),
             (980, 508), (1180, 570), (1330, 528), (1440, 566), (1440, 640), (0, 640)], HILL_FAR)
    poly(d, [(0, 640), (240, 596), (470, 634), (700, 588), (960, 630),
             (1200, 592), (1440, 626), (1440, 700), (0, 700)], HILL_NEAR)

    # 站台
    rect(d, 0, 626, W, H, PLATFORM)
    rect(d, 0, 626, W, 636, PLATFORM_EDGE)
    for y in (786, 900):
        rect(d, 0, y, W, y + 3, PLATFORM_EDGE)

    # 地影
    ellipse(d, 360, 902, 250, 26, (86, 92, 74, 60))
    ellipse(d, 610, 908, 70, 14, (86, 92, 74, 55))

    # 长椅
    seat_y = 762
    rect(d, 148, seat_y, 566, seat_y + 22, INK_SOFT)
    rect(d, 172, seat_y + 22, 200, 902, INK_SOFT)
    rect(d, 514, seat_y + 22, 542, 902, INK_SOFT)
    rect(d, 172, 648, 186, seat_y, INK_SOFT)
    rect(d, 528, 648, 542, seat_y, INK_SOFT)
    for y in (664, 700, 736):
        rect(d, 172, y, 542, y + 14, INK_SOFT)

    # 坐在长椅上的人（背面）
    poly(d, [(352, 688), (412, 688), (434, 768), (330, 768)], INK)   # 外套
    rrect(d, 344, 690, 420, 726, 16, INK)                            # 肩
    ellipse(d, 382, 656, 30, 30, INK)                                # 头
    # 长椅另一端放的布包
    rrect(d, 186, 716, 244, 766, 10, INK_SOFT)
    line(d, [(196, 716), (196, 702), (234, 702), (234, 716)], INK_SOFT, 7)

    # 行李箱
    rrect(d, 566, 774, 664, 898, 12, INK_SOFT)
    line(d, [(586, 776), (586, 748), (644, 748), (644, 776)], INK_SOFT, 8)
    rect(d, 566, 800, 664, 808, PLATFORM)
    ellipse(d, 590, 902, 11, 11, INK_SOFT)
    ellipse(d, 640, 902, 11, 11, INK_SOFT)

    # 路灯
    rect(d, 1240, 372, 1256, 902, INK_SOFT)
    rect(d, 1148, 372, 1256, 386, INK_SOFT)
    poly(d, [(1132, 386), (1180, 386), (1172, 424), (1140, 424)], INK_SOFT)
    ellipse(d, 1156, 436, 62, 62, (WARM[0], WARM[1], WARM[2], 70))
    rrect(d, 1146, 404, 1166, 424, 4, WARM)

    return img.resize((W, H), Image.LANCZOS)


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("cover.png")
    build().save(out, "PNG", optimize=True)
    print(f"封面插画 → {out}  {W}×{H}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
