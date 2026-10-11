#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 README 顶部的横幅图。

用法：
    python assets/make_banner.py <pages 目录> [-o assets/banner.png]

拿一套已经渲染好的页面（p01 是封面，p02 起是正文）拼成 1600×500 的横幅：
左边是项目名和一句话说明，右边是封面与两页正文叠放。
字体、配色、底纹图案全部复用 scripts/render.py，所以横幅和成品页面是同一套视觉。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import render as R  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

W, H = 1600, 500
BG = "#262A29"
TITLE = "#7FE196"
INK = "#F3F7F6"
MUTED = "#9FB3AC"

CARD_W, CARD_H = 228, 380                            # 3:5，和页面同比例
CARD_SLOTS = [(1005, 250, 3.4), (1218, 246, 0.0), (1431, 254, -3.4)]

NAME = "longform-carousel"
SUBTITLE = "小红书长文图文轮播"
TAGLINES = [
    "把一段真实经历做成一整套长文图文：封面 + 正文页（1440×2400）",
    "内容先查证、文字不带 AI 腔，交付题目、3 段文案、标签和首评",
]
FOOTER = "github.com/a5577/longform-carousel"


def text(d, s, x, ink_top, size, weight, color):
    ts = R.Typesetter(size, weight)
    ts.draw(d, s, x, ts.baseline_for_ink_top(ink_top), R.rgba(color))
    return ts.width(s)


def card_image(path: Path) -> Image.Image:
    im = Image.open(path).convert("RGB").resize((CARD_W, CARD_H), Image.LANCZOS)
    mask = Image.new("L", (CARD_W, CARD_H), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, CARD_W - 1, CARD_H - 1), radius=16, fill=255)
    card = im.convert("RGBA")
    card.putalpha(mask)
    ImageDraw.Draw(card).rounded_rectangle((0, 0, CARD_W - 1, CARD_H - 1), radius=16,
                                           outline=R.rgba("#41524A", 255), width=2)
    return card


def card_shadow(angle: float, blur: int = 18, alpha: int = 120,
                pad: int = 40) -> Image.Image:
    m = Image.new("L", (CARD_W + pad * 2, CARD_H + pad * 2), 0)
    ImageDraw.Draw(m).rounded_rectangle((pad, pad, pad + CARD_W - 1, pad + CARD_H - 1),
                                        radius=16, fill=alpha)
    m = m.rotate(angle, resample=Image.BICUBIC, expand=True).filter(ImageFilter.GaussianBlur(blur))
    shadow = Image.new("RGBA", m.size, (0, 0, 0, 255))
    shadow.putalpha(m)
    return shadow


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="生成 README 横幅图")
    ap.add_argument("pages", help="渲染好的 pages 目录（含 p01.png …）")
    ap.add_argument("-o", "--out", default="assets/banner.png", help="输出文件")
    args = ap.parse_args(argv)

    pages = sorted(Path(args.pages).glob("p*.png"))
    if not pages:
        raise SystemExit(f"{args.pages} 里没有 p*.png，先跑 scripts/render.py")
    picks = (pages + [pages[-1]] * 3)[:3]

    # 底色 + 淡淡的简笔花底纹（复用正文页那套图案）
    canvas = Image.new("RGB", (W, H), R.rgba(BG))
    R.draw_bg_pattern(canvas, {"底色": BG, "图案": "简笔花", "图案色": "#3D4C45",
                               "图案密度": 0.4, "图案间距": 200, "图案大小": 62,
                               "图案透明度": 0.7, "图案随机": 5})
    canvas = canvas.convert("RGBA")
    d = ImageDraw.Draw(canvas)

    # 左侧：封面同款三横条 + 项目名 + 说明
    x0 = 96
    y = 80
    for bw, bh in ((38, 14), (60, 12), (82, 14)):
        d.rectangle((x0, y, x0 + bw - 1, y + bh - 1), fill=R.rgba(TITLE))
        y += bh + 12

    widths = [
        text(d, NAME, x0, 152, 74, 800, TITLE),
        text(d, SUBTITLE, x0, 258, 38, 700, INK),
    ]
    for i, line in enumerate(TAGLINES):
        widths.append(text(d, line, x0, 332 + i * 38, 26, 400, MUTED))
    widths.append(text(d, FOOTER, x0, 418, 22, 400, "#6F827B"))

    # 右侧：封面 + 两页正文，错落叠放
    for (cx, cy, ang) in CARD_SLOTS:
        sh = card_shadow(ang)
        canvas.alpha_composite(sh, (cx - sh.width // 2, cy - sh.height // 2 + 8))
    for (cx, cy, ang), path in zip(CARD_SLOTS, picks):
        c = card_image(path).rotate(ang, resample=Image.BICUBIC, expand=True)
        canvas.alpha_composite(c, (cx - c.width // 2, cy - c.height // 2))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out, "PNG", optimize=True)
    print(f"横幅 → {out}  {canvas.size[0]}×{canvas.size[1]}  左侧文字最宽 {max(widths):.0f}px")
    print("页面：", ", ".join(p.name for p in picks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
