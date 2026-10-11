#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小红书长文图文轮播渲染器。

把一份 笔记.json 渲染成 1 张封面 + N 张正文页（1440x2400），并输出全套预览图。

用法：
    python render.py <笔记目录 或 笔记.json> [--out pages] [--preview 全套预览.jpg]

版式数值全部来自 references/版式规格.md，只改 DEFAULTS 里的数字，
不要改这里的排版逻辑；重新标定请同时更新那份规格文档。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1440, 2400
SKILL_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------- 版式常量
DEFAULTS = {
    "底色": "#262A29",
    "色块": "#223531",
    "标题色": "#7FE196",
    "正文色": "#F3F7F6",
    "插画底": "#E8D4A1",          # 没有插画时的兜底色
    "插画高": 976,
    "色块顶": 1824,
    # 封面：图标三横条
    "图标x": 80,
    "图标条": [[1064, 19, 7], [1077, 30, 6], [1089, 41, 7]],  # [顶, 宽, 高]
    # 封面：元信息行「全文NNNN字｜阅读需N分钟」
    "元信息x": 153,
    "元信息墨顶": 1059,
    "元信息字号": 48,
    # 封面：大字标题
    "封面左边距": 80,
    "封面右边界": 1340,
    "标题墨顶": 1177,
    "标题字号": "auto",           # auto：按行数在 标题块高 内配字号；写数字则强制
    "标题块高": 545,              # 标题可见区块目标高度（量自同账号多篇封面）
    "标题行距比": 1.23,           # 行距 = 字号 × 该比例
    "标题字身比": 0.94,           # 一行墨迹高 ≈ 字号 × 该比例
    "标题字号上限": 184,
    "标题字号下限": 72,
    "标题字重": 800,
    "标题最大行数": 4,
    # 封面：色块里的导语
    "导语墨顶": 1879,
    "导语字号": 52.5,
    "导语行距": 87,
    # 正文页
    "正文左边距": 127,
    "正文右边界": 1310,
    "正文墨顶": 146,
    "正文字号": 53.5,
    "正文行距": 92.5,
    "正文段距": 48,
    "正文最大行数": 23,
    "正文最小行数": 5,           # 末页少于此行数时警告
    "字重": 400,
    # 阅读时长估算
    "阅读速度": 480,             # 字/分钟
}

# 避头尾：不能出现在行首 / 不能出现在行尾
ACCENTS = {"绿": "#7FE196", "蓝": "#59C8FD", "黄": "#FEE98E"}  # 同账号三套配色的实测值

NO_START = "，。、；：！？）】》」』…·ーー,.!?)]}%\"'’”"
NO_END = "（【《「『([{“‘"
CJK_COVER_RATIO = 0.88  # 汉字字身框顶边相对基线的位置（负值）→ 基线 = 墨顶 + 0.88 * 字号


# ---------------------------------------------------------------- 字体
def _font_candidates(kind: str = "sans") -> list[str]:
    home = Path.home()
    if kind == "serif":
        return [
            str(SKILL_DIR / "assets" / "fonts" / "NotoSerifSC[wght].ttf"),
            str(home / ".codex" / "skills" / "cy-carousel" / "assets" / "fonts" / "NotoSerifSC[wght].ttf"),
            r"C:\Windows\Fonts\simsun.ttc",
            "/System/Library/Fonts/Songti.ttc",
            "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        ]
    return [
        str(SKILL_DIR / "assets" / "fonts" / "NotoSansSC[wght].ttf"),
        str(home / ".codex" / "skills" / "cy-carousel" / "assets" / "fonts" / "NotoSansSC[wght].ttf"),
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]


_FONT_PATH: dict[str, str] = {}


def font_path(kind: str = "sans") -> str:
    if kind in _FONT_PATH:
        return _FONT_PATH[kind]
    for c in _font_candidates(kind):
        if c and os.path.exists(c):
            _FONT_PATH[kind] = c
            return c
    need = "NotoSerifSC[wght].ttf" if kind == "serif" else "NotoSansSC[wght].ttf"
    raise SystemExit(
        f"找不到可用的中文{kind == 'serif' and '宋体/衬线' or ''}字体。请把 {need} 放进 "
        f"{SKILL_DIR / 'assets' / 'fonts'}。"
    )


def load_font(size: int, weight: int = 400, path: str | None = None, kind: str = "sans"):
    """返回 (font, stroke_width)。可变字体走字重轴，静态字体用描边加粗。"""
    f = ImageFont.truetype(path or font_path(kind), size)
    stroke = 0
    try:
        f.set_variation_by_axes([weight])
    except Exception:
        if weight >= 700:
            stroke = max(1, round(size * 0.022))
    return f, stroke


class Typesetter:
    """按单个字符计算宽度，支持中文两端避头尾和负/正字距。"""

    def __init__(self, size: int, weight: int = 400, tracking: float = 0.0,
                 path: str | None = None, kind: str = "sans"):
        self.size = size
        self.tracking = tracking
        self.font, self.stroke = load_font(size, weight, path, kind)
        self._w: dict[str, float] = {}

    def advance(self, ch: str) -> float:
        v = self._w.get(ch)
        if v is None:
            v = self.font.getlength(ch) + self.tracking
            self._w[ch] = v
        return v

    def width(self, text: str) -> float:
        return sum(self.advance(c) for c in text)

    def wrap(self, text: str, width: float) -> list[str]:
        lines: list[str] = []
        for raw in text.split("\n"):
            raw = raw.rstrip()
            if not raw:
                lines.append("")
                continue
            i, n = 0, len(raw)
            while i < n:
                line, used = [], 0.0
                while i < n:
                    cw = self.advance(raw[i])
                    if line and used + cw > width:
                        break
                    line.append(raw[i])
                    used += cw
                    i += 1
                while i < n and raw[i] in NO_START:      # 标点不落行首
                    line.append(raw[i])
                    i += 1
                while len(line) > 1 and line[-1] in NO_END:  # 前引号不落行尾
                    i -= 1
                    line.pop()
                lines.append("".join(line))
        return lines

    def draw(self, d: ImageDraw.ImageDraw, text: str, x: float, baseline: float, fill):
        if not text:
            return
        if not self.tracking and not self.stroke:
            d.text((x, baseline), text, font=self.font, fill=fill, anchor="ls")
            return
        cx = x
        for ch in text:
            d.text(
                (cx, baseline),
                ch,
                font=self.font,
                fill=fill,
                anchor="ls",
                stroke_width=self.stroke,
                stroke_fill=fill,
            )
            cx += self.advance(ch)

    def baseline_for_ink_top(self, ink_top: float) -> float:
        return ink_top + CJK_COVER_RATIO * self.size


# ---------------------------------------------------------------- 工具
def rgba(hex_str: str, alpha: int | None = None):
    h = hex_str.lstrip("#")
    rgb = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    return rgb if alpha is None else (*rgb, alpha)


def paragraphs_of(text: str) -> list[str]:
    out = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        s = raw.strip()
        if s:
            out.append(s)
    return out


def char_count(text: str) -> int:
    return len("".join(text.split()))


def reading_minutes(chars: int, speed: int) -> int:
    return max(1, math.ceil(chars / max(1, speed)))


def cover_fit(img: Image.Image, size: tuple[int, int], focus=(0.5, 0.5)) -> Image.Image:
    """等比缩放到铺满 size，再按 focus 裁剪（0=靠上/左，1=靠下/右）。"""
    tw, th = size
    iw, ih = img.size
    scale = max(tw / iw, th / ih)
    nw, nh = max(tw, int(round(iw * scale))), max(th, int(round(ih * scale)))
    img = img.resize((nw, nh), Image.LANCZOS)
    left = int(round((nw - tw) * focus[0]))
    top = int(round((nh - th) * focus[1]))
    return img.crop((left, top, left + tw, top + th))


def placeholder_illustration(size: tuple[int, int], base: str) -> Image.Image:
    """没有插画时的兜底：同色系柔和渐变，不带任何文字。"""
    tw, th = size
    img = Image.new("RGB", (tw, th), rgba(base))
    px = img.load()
    r0, g0, b0 = rgba(base)
    for y in range(th):
        t = y / max(1, th - 1)
        k = 0.82 + 0.30 * t
        for x in range(tw):
            s = 0.94 + 0.12 * (x / max(1, tw - 1))
            px[x, y] = (
                min(255, int(r0 * k * s)),
                min(255, int(g0 * k * s)),
                min(255, int(b0 * k * s)),
            )
    return img


# ---------------------------------------------------------------- 浅色封面样式
# 数值量自"封面参考"里同账号的浅色封面（1280×2133 等比换算到 1440×2400）。
LIGHT_STYLES = {
    "纸底": {
        "底色": "#E6F4E5",
        "线色": "#C9DECB",
        "标题色": "#0A814F",
        "文字色": "#2F3530",
        "字体": "serif",
        "字重": 600,
        "竖线x": [79, 1359],
        "横线y": 375,
        "元信息x": 82,
        "元信息墨顶": 331,
        "元信息字号": 40,
        "标题墨顶": 451,
        "标题块高": 395,
        "标题左": 79,
        "标题右": 1360,
        "标题上限": 240,
        "标题下限": 60,
        "图片框": [79, 951, 1360, 1814],   # 内嵌大图，左右和竖线对齐
        "导语墨顶": 1914,
        "导语字号": 53,
        "导语行距": 92,
        "导语左": 79,
        "导语右": 1360,
        "纸纹": True,
        "检查框": {"标题": [0, 400, 1440, 940], "导语": [0, 1870, 1440, 2075]},
    },
    "白底": {
        "底色": "#FFFFFF",
        "色带": "#CAEAE9",
        "标题色": "#2D2D2D",
        "文字色": "#26302F",
        "字体": "sans",
        "字重": 800,
        "图标x": 80,
        "图标y": 331,
        "图标色": "#D1999A",
        "图标边长": 37,
        "元信息x": 144,
        "元信息墨顶": 330,
        "元信息字号": 40,
        "标题墨顶": 500,
        "标题块高": 497,
        "标题左": 79,
        "标题右": 1360,
        "标题上限": 220,
        "标题下限": 60,
        "色带框": [0, 1055, 1440, 1311],
        "图片框": [0, 1311, 1440, 2400],   # 底部整幅出血
        "导语墨顶": 1117,
        "导语字号": 53,
        "导语行距": 78,
        "导语左": 79,
        "导语右": 1372,
        "检查框": {"标题": [0, 455, 1440, 1045], "导语": [0, 1062, 1440, 1305]},
    },
}


# ---------------------------------------------------------------- 封面
def cover_meta_text(cov: dict, spec: dict, theme: dict) -> tuple[str, int, int]:
    chars = char_count(spec.get("正文", ""))
    mins = reading_minutes(chars, theme["阅读速度"])
    meta = cov.get("字数行")
    if not meta or meta == "auto":
        meta = f"全文{chars}字｜阅读需{mins}分钟"
    elif "{字数}" in meta or "{分钟}" in meta:
        meta = meta.format(字数=chars, 分钟=mins)
    return meta, chars, mins


def fit_title_size(lines: list[str], theme: dict) -> float:
    """按行数把标题塞进 标题块高：行数少就放大，行数多就缩小，再用行宽兜底。"""
    if not isinstance(theme["标题字号"], str):
        return float(theme["标题字号"])
    n = max(1, len(lines))
    block = theme["标题块高"]
    ratio_line = theme["标题行距比"]
    ratio_ink = theme["标题字身比"]
    size = block / (ratio_ink + ratio_line * (n - 1))
    probe = Typesetter(100, theme["标题字重"])
    widest = max(probe.width(l) for l in lines) / 100.0
    if widest > 0:
        size = min(size, (theme["封面右边界"] - theme["封面左边距"]) / widest)
    return float(max(theme["标题字号下限"], min(theme["标题字号上限"], size)))


def render_cover(spec: dict, theme: dict, warnings: list[str]) -> tuple[Image.Image, dict]:
    """兼容入口：只出 深色 版封面。多版请用 render_cover_variants。"""
    img, info, _ = render_cover_variants(spec, theme, warnings, ["深色"])
    return img, info


def render_cover_variants(spec: dict, theme: dict, warnings: list[str],
                          versions: list[str]) -> tuple[Image.Image, dict, dict]:
    """按 版本 列表出多张封面，返回 (首版图, 首版信息, {版本: (图, 信息)})。"""
    out: dict[str, tuple[Image.Image, dict]] = {}
    for name in versions:
        if name == "深色":
            out[name] = _cover_dark(spec, theme, warnings)
        elif name in LIGHT_STYLES:
            out[name] = _cover_light(spec, theme, name, warnings)
        else:
            warnings.append(f"不认识的封面版本「{name}」，可选：深色 / {' / '.join(LIGHT_STYLES)}")
    if not out:
        out["深色"] = _cover_dark(spec, theme, warnings)
    first = next(iter(out.values()))
    return first[0], first[1], out


def _cover_dark(spec: dict, theme: dict, warnings: list[str]) -> tuple[Image.Image, dict]:
    cov = spec.get("封面", {})
    meta, chars, mins = cover_meta_text(cov, spec, theme)

    img = Image.new("RGB", (W, H), rgba(theme["底色"]))

    ill_path = cov.get("插画")
    if ill_path:
        p = Path(ill_path)
        if not p.is_absolute():
            p = Path(spec.get("_base", ".")) / p
        if p.exists():
            ill = Image.open(p).convert("RGB")
            focus = cov.get("焦点", [0.5, 0.5])
            img.paste(cover_fit(ill, (W, theme["插画高"]), (focus[0], focus[1])), (0, 0))
        else:
            warnings.append(f"插画不存在，已用底色渐变兜底：{ill_path}")
            img.paste(placeholder_illustration((W, theme["插画高"]), theme["插画底"]), (0, 0))
    else:
        warnings.append("没有指定封面插画，已用底色渐变兜底（建议补一张图）")
        img.paste(placeholder_illustration((W, theme["插画高"]), theme["插画底"]), (0, 0))

    # 底部色块
    ImageDraw.Draw(img).rectangle(
        (0, theme["色块顶"], W, H), fill=rgba(theme["色块"])
    )

    d = ImageDraw.Draw(img)

    # 图标三横条
    accent = rgba(theme["标题色"])
    for top, bw, bh in theme["图标条"]:
        d.rectangle((theme["图标x"], top, theme["图标x"] + bw - 1, top + bh - 1), fill=accent)

    # 元信息行
    meta_ts = Typesetter(theme["元信息字号"], theme["字重"])
    meta_ts.draw(d, meta, theme["元信息x"], meta_ts.baseline_for_ink_top(theme["元信息墨顶"]),
                 rgba(theme["正文色"]))

    # 大字标题
    title_lines = [t for t in cov.get("标题行", []) if t]
    if not title_lines:
        title = cov.get("标题") or spec.get("标题") or ""
        if title:
            probe = Typesetter(116, theme["标题字重"])
            title_lines = probe.wrap(title, theme["封面右边界"] - theme["封面左边距"])
            warnings.append("封面未给 标题行，已按每行容量自动断行（建议人工定行更顺口）")
    if not title_lines:
        warnings.append("封面没有标题")
    if len(title_lines) > theme["标题最大行数"]:
        over = len(title_lines) - theme["标题最大行数"]
        warnings.append(f"标题 {len(title_lines)} 行，超出 {over} 行会压到色块，请合并字句")

    size = fit_title_size(title_lines, theme)
    title_ts = Typesetter(size, theme["标题字重"])
    tl_base = title_ts.baseline_for_ink_top(theme["标题墨顶"])
    pitch = size * theme["标题行距比"]
    for i, line in enumerate(title_lines):
        title_ts.draw(d, line, theme["封面左边距"], tl_base + i * pitch, rgba(theme["标题色"]))

    # 导语
    lead = cov.get("导语", "") or ""
    lead_lines: list[str] = []
    if lead:
        lead_ts = Typesetter(theme["导语字号"], theme["字重"])
        lead_lines = lead_ts.wrap(lead, theme["封面右边界"] - theme["封面左边距"])
        lb = lead_ts.baseline_for_ink_top(theme["导语墨顶"])
        for i, line in enumerate(lead_lines):
            lead_ts.draw(d, line, theme["封面左边距"], lb + i * theme["导语行距"], rgba(theme["正文色"]))
        if len(lead_lines) > 3:
            warnings.append(f"导语 {len(lead_lines)} 行，建议压到 2 行以内")

    # 可选角标（默认不写，任何别人的小红书号都不要照抄）
    mark = cov.get("角标", "")
    if mark:
        mk = Typesetter(28, 400)
        mk.draw(d, mark, W - 40 - mk.width(mark), H - 46, rgba(theme["正文色"]))

    info = {
        "字数": chars,
        "阅读分钟": mins,
        "字数行": meta,
        "标题行": title_lines,
        "标题字号": round(size, 1),
        "导语行": lead_lines,
        "版本": "深色",
    }
    return img, info


def fit_size(lines: list[str], left: float, right: float, block: float,
             line_ratio: float, ink_ratio: float, cap: float, floor: float,
             weight: int, kind: str = "sans", forced=None) -> float:
    if not isinstance(forced, str) and forced:
        return float(forced)
    n = max(1, len(lines))
    size = block / (ink_ratio + line_ratio * (n - 1))
    probe = Typesetter(100, weight, kind=kind)
    widest = max(probe.width(l) for l in lines) / 100.0
    if widest > 0:
        size = min(size, (right - left) / widest)
    return float(max(floor, min(cap, size)))


def paper_grain(img: Image.Image, box: tuple[int, int, int, int], tone: int = 6, seed: int = 7,
                count: int = 2600):
    """纸底封面的极淡颗粒，避免大片纯色显得像色块。"""
    import random
    rnd = random.Random(seed)
    px = img.load()
    x0, y0, x1, y1 = box
    for _ in range(count):
        x = rnd.randrange(x0, x1)
        y = rnd.randrange(y0, y1)
        r, g, b = px[x, y]
        k = rnd.randint(0, tone)
        px[x, y] = (max(0, r - k), max(0, g - k), max(0, b - k))


def _cover_light(spec: dict, theme: dict, style_name: str,
                 warnings: list[str]) -> tuple[Image.Image, dict]:
    cov = spec.get("封面", {})
    st = dict(LIGHT_STYLES[style_name])
    st.update(cov.get("样式") or {})
    meta, chars, mins = cover_meta_text(cov, spec, theme)
    kind = st["字体"]
    weight = st["字重"]
    line_ratio = st.get("标题行距比", 1.23)
    ink_ratio = st.get("标题字身比", 0.94)

    img = Image.new("RGB", (W, H), rgba(st["底色"]))
    if st.get("纸纹"):
        paper_grain(img, (0, 0, W, H))
    d = ImageDraw.Draw(img)

    for x in st.get("竖线x", []):
        d.rectangle((x, 0, x + 1, H), fill=rgba(st["线色"]))
    if st.get("横线y"):
        d.rectangle((0, st["横线y"], W, st["横线y"] + 1), fill=rgba(st["线色"]))
    if st.get("色带框"):
        b0, b1, b2, b3 = st["色带框"]
        d.rectangle((b0, b1, b2, b3), fill=rgba(st["色带"]))

    # 大图（先贴图，文字后画压在图上）
    box = st["图片框"]
    pw, ph = box[2] - box[0], box[3] - box[1]
    ill_path = cov.get("插画")
    ill = None
    if ill_path:
        p = Path(ill_path)
        if not p.is_absolute():
            p = Path(spec.get("_base", ".")) / p
        if p.exists():
            ill = Image.open(p).convert("RGB")
        else:
            warnings.append(f"插画不存在，已用底色渐变兜底：{ill_path}")
    else:
        warnings.append("没有指定封面插画，已用底色渐变兜底（建议补一张图）")
    focus = cov.get("焦点", [0.5, 0.5])
    if ill is not None:
        img.paste(cover_fit(ill, (pw, ph), (focus[0], focus[1])), (box[0], box[1]))
    else:
        img.paste(placeholder_illustration((pw, ph), theme["插画底"]), (box[0], box[1]))

    # 标题
    title_lines = [t for t in cov.get("标题行", []) if t]
    if not title_lines:
        title = cov.get("标题") or spec.get("标题") or ""
        if title:
            probe = Typesetter(st.get("标题上限", 180) * 0.8, weight, kind=kind)
            title_lines = probe.wrap(title, st["标题右"] - st["标题左"])
            warnings.append("封面未给 标题行，已按每行容量自动断行（建议人工定行更顺口）")
    if not title_lines:
        warnings.append(f"{style_name} 封面没有标题")
    if len(title_lines) > 4:
        warnings.append(f"{style_name} 封面标题 {len(title_lines)} 行，超过 4 行会很挤，请合并字句")

    size = fit_size(title_lines, st["标题左"], st["标题右"], st["标题块高"], line_ratio, ink_ratio,
                    st["标题上限"], st["标题下限"], weight, kind, cov.get("标题字号"))
    ts = Typesetter(size, weight, kind=kind)
    base = ts.baseline_for_ink_top(st["标题墨顶"])
    for i, line in enumerate(title_lines):
        ts.draw(d, line, st["标题左"], base + i * size * line_ratio, rgba(st["标题色"]))

    # 元信息
    if st.get("图标边长"):
        ix, iy, s = st["图标x"], st["图标y"], st["图标边长"]
        d.rectangle((ix, iy, ix + s, iy + s), fill=rgba(st["图标色"]))
    mt = Typesetter(st["元信息字号"], 400, kind=kind)
    mt.draw(d, meta, st["元信息x"], mt.baseline_for_ink_top(st["元信息墨顶"]), rgba(st["文字色"]))

    # 导语
    lead = cov.get("导语", "") or ""
    lead_lines: list[str] = []
    if lead:
        lt = Typesetter(st["导语字号"], 400, kind=kind)
        lead_lines = lt.wrap(lead, st["导语右"] - st["导语左"])
        lb = lt.baseline_for_ink_top(st["导语墨顶"])
        for i, line in enumerate(lead_lines):
            lt.draw(d, line, st["导语左"], lb + i * st["导语行距"], rgba(st["文字色"]))
        if len(lead_lines) > 3:
            warnings.append(f"{style_name} 导语 {len(lead_lines)} 行，建议压到 2 行以内")

    info = {
        "字数": chars,
        "阅读分钟": mins,
        "字数行": meta,
        "标题行": title_lines,
        "标题字号": round(size, 1),
        "导语行": lead_lines,
        "版本": style_name,
    }
    return img, info


# ---------------------------------------------------------------- 正文页底色与背景图案
# 「深色」是原帖量出来的那一版（数值见 DEFAULTS）；「纸底」「白底」是后加的浅色版，
# 只换底色和文字色，分页、边距、字号、行距三版完全一样。
BODY_STYLES = {
    "深色": {"底色": "#262A29", "正文色": "#F3F7F6", "图案色": "#4A5A52"},
    "纸底": {"底色": "#F6F2E9", "正文色": "#2F3530", "图案色": "#C0B392"},
    "白底": {"底色": "#FFFFFF", "正文色": "#26302F", "图案色": "#D9D3C4"},
}
BODY_ALIASES = {"暗色": "深色", "浅色": "纸底", "米色": "纸底", "奶白": "白底"}
BODY_PATTERNS = ("无", "简笔花", "简笔叶", "圆点")


def _known_body_version(name: str) -> bool:
    return name in BODY_STYLES or name in BODY_ALIASES


def resolve_body_style(cfg: dict | None, theme: dict) -> tuple[str, dict]:
    """把 正文页 配置解析成 (版本名, 样式)。样式里含 底色/正文色/图案… 全部键。"""
    cfg = cfg or {}
    raw = str(cfg.get("版本") or "深色").strip()
    name = BODY_ALIASES.get(raw, raw)
    if name not in BODY_STYLES:
        name = "深色"
    st = dict(BODY_STYLES[name])
    if name == "深色":  # 保留旧写法：样式.底色 / 样式.正文色 仍能覆盖深色页
        st["底色"] = theme.get("底色", st["底色"])
        st["正文色"] = theme.get("正文色", st["正文色"])
    st.update(cfg.get("样式") or {})
    pat = str(cfg.get("图案", st.get("图案", "无")) or "无").strip()
    st["图案"] = pat if pat in BODY_PATTERNS else "无"
    st["图案密度"] = float(cfg.get("图案密度", 0.5))
    st["图案大小"] = float(cfg.get("图案大小", 0))
    st["图案透明度"] = float(cfg.get("图案透明度", cfg.get("图案不透明度", 0.3)))
    st["图案随机"] = int(cfg.get("图案随机", 11))
    st["版本"] = name
    return name, st


def body_styles_for(cfg: dict | None, theme: dict, count: int,
                    warnings: list[str] | None = None) -> list[tuple[str, dict]]:
    """返回每张正文页（从第 1 张起）的 (版本名, 样式)。"""
    warnings = warnings if warnings is not None else []
    cfg = cfg or {}
    raw_default = str(cfg.get("版本") or "深色").strip()
    if not _known_body_version(raw_default):
        warnings.append(
            f"不认识的正文页版本「{raw_default}」，可选："
            f"深色 / 纸底（浅色）/ 白底，已按深色处理"
        )
        raw_default = "深色"
    default_name, default_style = resolve_body_style({**cfg, "版本": raw_default}, theme)
    per = list(cfg.get("每页版本") or [])
    out: list[tuple[str, dict]] = []
    for i in range(count):
        raw = str(per[i]).strip() if i < len(per) and per[i] else raw_default
        if not _known_body_version(raw):
            warnings.append(f"第 {i + 1} 页不认识正文页版本「{raw}」，已按深色处理")
            raw = "深色"
        if raw == raw_default:
            out.append((default_name, default_style))
        else:
            out.append(resolve_body_style({**cfg, "版本": raw}, theme))
    return out


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _rotated_ellipse(cx: float, cy: float, rx: float, ry: float, rot: float,
                     n: int = 22) -> list[tuple[float, float]]:
    ca, sa = math.cos(rot), math.sin(rot)
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        x, y = rx * math.cos(t), ry * math.sin(t)
        pts.append((cx + x * ca - y * sa, cy + x * sa + y * ca))
    return pts


def _draw_flower(d, cx: float, cy: float, r: float, rot: float, color, stroke: int):
    """简笔花：五瓣勾线 + 小圆心。"""
    for k in range(5):
        a = rot + math.radians(-90 + k * 72)
        pxc = cx + math.cos(a) * r * 0.54
        pyc = cy + math.sin(a) * r * 0.54
        pts = _rotated_ellipse(pxc, pyc, r * 0.21, r * 0.43, a)
        d.line(pts + [pts[0]], fill=color, width=stroke, joint="curve")
    rr = r * 0.15
    d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), outline=color, width=stroke)


def _draw_leaf(d, cx: float, cy: float, r: float, rot: float, color, stroke: int):
    """简笔叶：两段弧拼成叶形 + 一条中脉。"""
    w, h, n = r * 0.30, r * 0.62, 16
    side = [(math.sin(math.pi * i / n) * w, -h + 2 * h * i / n) for i in range(n + 1)]
    ca, sa = math.cos(rot), math.sin(rot)

    def rot_pt(x, y):
        return (cx + x * ca - y * sa, cy + x * sa + y * ca)

    right = [rot_pt(x, y) for x, y in side]
    left = [rot_pt(-x, y) for x, y in reversed(side)]
    d.line(right + left, fill=color, width=stroke, joint="curve")
    d.line([rot_pt(0, -h), rot_pt(0, h)], fill=color, width=stroke)


def draw_bg_pattern(img: Image.Image, st: dict) -> None:
    """在底色上铺一层很淡的图案（文字压在图案上面）。图案默认关闭。"""
    name = st.get("图案", "无")
    if name in (None, "", "无", "none"):
        return
    density = min(1.0, max(0.0, st.get("图案密度", 0.5)))
    alpha = min(1.0, max(0.0, st.get("图案透明度", 0.08)))
    if alpha <= 0:
        return
    rgb = rgba(st.get("图案色", "#FFFFFF"))
    color = (*rgb, int(round(255 * alpha)))
    size = st.get("图案大小") or _lerp(48, 74, density)   # 越密图案越小
    spacing = _lerp(600, 380, density)
    stroke = max(2, int(round(size * 0.075)))
    step = int(round(spacing))
    jitter = spacing * 0.34
    rnd = random.Random(st.get("图案随机", 11))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    keep = 0.40 + density * 0.42      # 再随机跳掉一部分，保证「一点点」
    cols = int(W / step) + 2
    rows = int(H / step) + 2
    for row in range(rows):
        for c in range(cols):
            if rnd.random() > keep:
                continue
            cx = (c - 0.5) * step + rnd.uniform(-jitter, jitter)
            cy = (row - 0.5) * step + rnd.uniform(-jitter, jitter)
            rot = math.radians(rnd.uniform(0, 360))
            rad = size * 0.5
            if name == "简笔花":
                _draw_flower(d, cx, cy, rad, rot, color, stroke)
            elif name == "简笔叶":
                _draw_leaf(d, cx, cy, rad, rot, color, stroke)
            elif name == "圆点":
                rr = size * 0.09
                d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=color)
    img.paste(Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB"))


# ---------------------------------------------------------------- 正文分页
def build_lines(paras: list[str], ts: Typesetter, width: float) -> list[tuple[str, bool]]:
    out: list[tuple[str, bool]] = []
    for p in paras:
        lines = ts.wrap(p, width)
        for i, ln in enumerate(lines):
            out.append((ln, i == 0))
    return out


def paginate(lines: list[tuple[str, bool]], theme: dict) -> list[list[tuple[str, bool]]]:
    pitch = theme["正文行距"]
    para_gap = theme["正文段距"]
    capacity = (theme["正文最大行数"] - 1) * pitch
    pages: list[list[tuple[str, bool]]] = []
    page: list[tuple[str, bool]] = []
    used = 0.0
    for text, is_para_start in lines:
        add = 0.0 if not page else pitch + (para_gap if is_para_start else 0)
        if page and used + add > capacity:
            pages.append(page)
            page, used = [], 0.0
            add = 0.0
        page.append((text, is_para_start))
        used += add
    if page:
        pages.append(page)
    return pages


def render_body_page(page: list[tuple[str, bool]], theme: dict,
                     style: dict | None = None) -> Image.Image:
    st = style or {"底色": theme["底色"], "正文色": theme["正文色"], "图案": "无"}
    img = Image.new("RGB", (W, H), rgba(st["底色"]))
    draw_bg_pattern(img, st)
    d = ImageDraw.Draw(img)
    ts = Typesetter(theme["正文字号"], theme["字重"])
    base = ts.baseline_for_ink_top(theme["正文墨顶"])
    y = base
    for i, (text, is_para_start) in enumerate(page):
        if i:
            y += theme["正文行距"] + (theme["正文段距"] if is_para_start else 0)
        ts.draw(d, text, theme["正文左边距"], y, rgba(st["正文色"]))
    return img


# ---------------------------------------------------------------- 预览
PREVIEW_COLS = 4
PREVIEW_THUMB_W = 360
PREVIEW_GAP = 18


def preview_grid_size(n: int, cols: int = PREVIEW_COLS, thumb_w: int = PREVIEW_THUMB_W,
                      gap: int = PREVIEW_GAP) -> tuple[int, int]:
    """拼版预览（所有图摆在一起的那张）该有多大：页数一变尺寸就变，check.py 拿它核对。"""
    n = max(1, n)
    cols = max(1, min(cols, n))
    th = round(thumb_w * H / W)
    rows = math.ceil(n / cols)
    return (cols * thumb_w + (cols + 1) * gap, rows * th + (rows + 1) * gap)


def contact_sheet(pages: list[Image.Image], cols: int = PREVIEW_COLS, thumb_w: int = PREVIEW_THUMB_W,
                  gap: int = PREVIEW_GAP, bg: str = "#101312") -> Image.Image:
    n = len(pages)
    cols = max(1, min(cols, n))
    th = round(thumb_w * H / W)
    rows = math.ceil(n / cols)
    sheet = Image.new("RGB", preview_grid_size(n, cols, thumb_w, gap), rgba(bg))
    for i, p in enumerate(pages):
        r, c = divmod(i, cols)
        sheet.paste(p.resize((thumb_w, th), Image.LANCZOS),
                    (gap + c * (thumb_w + gap), gap + r * (th + gap)))
    return sheet


# ---------------------------------------------------------------- 主流程
def load_spec(target: str) -> tuple[dict, Path]:
    p = Path(target)
    if p.is_dir():
        p = p / "笔记.json"
    if not p.exists():
        raise SystemExit(f"找不到笔记文件：{p}")
    spec = json.loads(p.read_text(encoding="utf-8"))
    spec["_base"] = str(p.parent)
    return spec, p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="小红书长文图文渲染器")
    ap.add_argument("note", help="笔记目录，或 笔记.json 路径")
    ap.add_argument("--out", default=None, help="页面输出目录（默认取 笔记.json 的 输出.页面目录，再默认 pages）")
    ap.add_argument("--preview", default=None, help="全套预览图路径（默认 输出.预览）")
    ap.add_argument("--covers", default=None,
                    help="封面版本，逗号分隔，可多选：深色,纸底,白底（默认取 笔记.json 的 封面.版本）")
    args = ap.parse_args(argv)

    spec, spec_path = load_spec(args.note)
    theme = dict(DEFAULTS)
    theme.update(spec.get("样式", {}))
    preset = spec.get("样式", {}).get("主题")
    if preset in ACCENTS:
        theme["标题色"] = ACCENTS[preset]
    elif preset:
        print(f"提醒：不认识的主题「{preset}」，可选 {list(ACCENTS)}", file=sys.stderr)
    out_cfg = spec.get("输出", {})
    out_dir = Path(args.out or out_cfg.get("页面目录", "pages"))
    preview = Path(args.preview or out_cfg.get("预览", "全套预览.jpg"))
    if not out_dir.is_absolute():
        out_dir = Path(spec["_base"]) / out_dir
    if not preview.is_absolute():
        preview = Path(spec["_base"]) / preview
    out_dir.mkdir(parents=True, exist_ok=True)
    preview.parent.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    body_text = spec.get("正文", "")
    if not body_text.strip():
        raise SystemExit("笔记.json 里的 正文 是空的")

    versions = [v.strip() for v in (args.covers.split(",") if args.covers
                                    else (spec.get("封面", {}).get("版本") or ["深色"])) if v.strip()]
    cover, cover_info, cover_map = render_cover_variants(spec, theme, warnings, versions)

    ts = Typesetter(theme["正文字号"], theme["字重"])
    paras = paragraphs_of(body_text)
    lines = build_lines(paras, ts, theme["正文右边界"] - theme["正文左边距"])
    pages_plan = paginate(lines, theme)

    if len(pages_plan[-1]) < theme["正文最小行数"]:
        warnings.append(
            f"最后一页只有 {len(pages_plan[-1])} 行，看着会空。建议把正文再写长一点或压掉一页。"
        )
    if len(pages_plan) > 9:
        warnings.append(f"正文共 {len(pages_plan)} 页，超过 9 页（加上封面共 {len(pages_plan) + 1} 张），小红书会截断；建议压到 9 页以内")

    body_styles = body_styles_for(spec.get("正文页") or {}, theme, len(pages_plan), warnings)
    images = [cover] + [render_body_page(p, theme, st)
                        for p, (_, st) in zip(pages_plan, body_styles)]
    files = []
    for i, im in enumerate(images, 1):
        f = out_dir / f"p{i:02d}.png"
        im.save(f)
        files.append(str(f))
    cand_dir = out_dir / "封面候选"
    cand_dir.mkdir(parents=True, exist_ok=True)
    for name, (im, info) in cover_map.items():
        im.save(cand_dir / f"p01-{name}.png")
    (cand_dir / "封面说明.json").write_text(
        json.dumps({n: {"标题字号": i["标题字号"], "标题行": i["标题行"]} for n, (_, i) in cover_map.items()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    contact_sheet(images).save(preview, quality=92)

    report = {
        "笔记": str(spec_path),
        "字体": font_path(),
        "画布": [W, H],
        "页数": len(images),
        "封面": dict(cover_info, 全部版本=versions, 首版=versions[0]),
        "封面候选": {n: i for n, (_, i) in cover_map.items()},
        "正文": {
            "字数": cover_info["字数"],
            "段落数": len(paras),
            "行数": len(lines),
            "每页行数": [len(p) for p in pages_plan],
            "每页段首行数": [sum(1 for _, s in p if s) for p in pages_plan],
        },
        "正文页": [
            {"版本": n, "底色": st["底色"], "正文色": st["正文色"],
             "图案": st["图案"], "图案密度": st["图案密度"],
             "图案透明度": st["图案透明度"]}
            for n, st in body_styles
        ],
        "页面": files,
        "预览": str(preview),
        "警告": warnings,
    }
    (out_dir.parent / "渲染报告.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"封面 + {len(pages_plan)} 页正文 → {out_dir}")
    print(f"封面版本 → {' / '.join(cover_map)}（首版 {versions[0]} 已作为 p01.png）")
    body_versions = [n for n, _ in body_styles]
    if body_versions:
        counts: list[str] = []
        for v in body_versions:
            if not counts or counts[-1].split("×")[0] != v:
                counts.append(v + "×1")
            else:
                head, num = counts[-1].split("×")
                counts[-1] = f"{head}×{int(num) + 1}"
        pats = sorted({s["图案"] for _, s in body_styles if s["图案"] != "无"})
        tail = f"，图案 {'/'.join(pats)}" if pats else ""
        print(f"正文页 → {' / '.join(counts)}{tail}")
    print(f"预览 → {preview}")
    print(f"全文 {cover_info['字数']} 字｜阅读需 {cover_info['阅读分钟']} 分钟"
          f"（封面写作「{cover_info['字数行']}」）")
    if warnings:
        print("\n需要处理的警告：")
        for w in warnings:
            print("  -", w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
