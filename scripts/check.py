#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""渲染结果自检：逐页量尺寸、墨迹边界、配色、分页完整性。

用法：
    python check.py <笔记目录> [--pages pages] [--preview 全套预览.jpg]

退出码非零表示有 error。警告和提醒不阻塞，但都要人工确认。
「技术通过」不等于视觉验收：最终必须把每一页按原始尺寸看一遍。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render as R  # noqa: E402

BODY_INK = 70          # 深底浅字：墨迹阈值（亮度）
BODY_INK_LIGHT = 260   # 浅底深字：与底色的通道落差之和（图案要留在阈值以下）


def ink_stats(img: Image.Image, thresh: int = BODY_INK):
    g = img.convert("L")
    px = g.load()
    w, h = g.size
    xs, ys, n = [], [], 0
    for y in range(h):
        for x in range(w):
            if px[x, y] > thresh:
                xs.append(x)
                ys.append(y)
                n += 1
    if not xs:
        return None
    return {
        "bbox": [min(xs), min(ys), max(xs), max(ys)],
        "覆盖率": round(n / (w * h), 4),
    }


def line_runs(img: Image.Image, thresh: int = BODY_INK, min_len: int = 3):
    g = img.convert("L")
    px = g.load()
    w, h = g.size
    prof = [sum(1 for x in range(0, w, 2) if px[x, y] > thresh) for y in range(h)]
    return runs_from_profile(prof, min_len)


def line_runs_light(img: Image.Image, bg_hex: str, thresh: int = BODY_INK_LIGHT,
                    min_len: int = 3):
    """浅底深字：只数比底色深的像素。"""
    bg = R.rgba(bg_hex)
    px = img.convert("RGB").load()
    w, h = img.size
    prof = []
    for y in range(h):
        c = 0
        for x in range(0, w, 2):
            p = px[x, y]
            if sum(max(0, bg[i] - p[i]) for i in range(3)) > thresh:
                c += 1
        prof.append(c)
    return runs_from_profile(prof, min_len)


def runs_from_profile(prof: list[int], min_len: int = 3):
    runs, start = [], None
    for i, v in enumerate(prof):
        if v >= 2 and start is None:
            start = i
        elif v < 2 and start is not None:
            if i - start >= min_len:
                runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(prof) - 1))
    return runs


def dominant_color(img: Image.Image) -> str:
    """取整页出现最多的颜色（背景压倒性地多，图案和文字都不影响众数）。"""
    small = img.convert("RGB").resize((240, 400), Image.NEAREST)
    colors = small.getcolors(240 * 400) or []
    colors.sort(reverse=True)
    r, g, b = colors[0][1]
    return "#%02X%02X%02X" % (r, g, b)


def is_dark(hex_str: str) -> bool:
    return sum(R.rgba(hex_str)) / 3 < 128


def _lum(c) -> float:
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def ink_threshold(st: dict, dark: bool) -> int:
    """图案不该被当成文字：阈值随图案的合成色抬高一点，正文（近黑或近白）仍数得到。"""
    base = BODY_INK if dark else BODY_INK_LIGHT
    if st.get("图案", "无") in (None, "", "无"):
        return base
    bg = R.rgba(st["底色"])
    pc = R.rgba(st.get("图案色", st["底色"]))
    a = min(1.0, max(0.0, float(st.get("图案透明度", 0.3))))
    if dark:
        return int(max(base, round(_lum(bg) + a * (_lum(pc) - _lum(bg)))))
    return int(max(base, round(a * sum(max(0, bg[i] - pc[i]) for i in range(3)))))


def near(hex_a: str, hex_b: str, tol: int = 10) -> bool:
    a, b = R.rgba(hex_a), R.rgba(hex_b)
    return all(abs(a[i] - b[i]) <= tol for i in range(3))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="小红书长文图文自检")
    ap.add_argument("note", help="笔记目录，或 笔记.json 路径")
    ap.add_argument("--pages", default=None, help="页面目录（默认取 笔记.json 的 输出.页面目录）")
    ap.add_argument("--preview", default=None, help="预览图路径")
    args = ap.parse_args(argv)

    spec, spec_path = R.load_spec(args.note)
    theme = dict(R.DEFAULTS)
    theme.update(spec.get("样式", {}))
    out_cfg = spec.get("输出", {})
    base = Path(spec["_base"])
    pages_dir = Path(args.pages or out_cfg.get("页面目录", "pages"))
    if not pages_dir.is_absolute():
        pages_dir = base / pages_dir
    preview = Path(args.preview or out_cfg.get("预览", "全套预览.jpg"))
    if not preview.is_absolute():
        preview = base / preview

    errors: list[str] = []
    notes: list[str] = []
    pages = sorted(pages_dir.glob("p*.png")) if pages_dir.exists() else []
    if not pages:
        errors.append(f"页面目录里没有 p*.png：{pages_dir}")

    rep_file = pages_dir.parent / "渲染报告.json"
    if not rep_file.exists():
        rep_file = base / "渲染报告.json"
    rep = json.loads(rep_file.read_text(encoding="utf-8")) if rep_file.exists() else {}
    cover_style = (rep.get("封面") or {}).get("首版") or "深色"

    body_styles = R.body_styles_for(spec.get("正文页") or {}, theme, max(0, len(pages) - 1))

    page_reports = []
    for i, p in enumerate(pages):
        im = Image.open(p)
        rec = {"文件": str(p), "尺寸": list(im.size)}
        if im.size != (R.W, R.H):
            errors.append(f"{p.name} 尺寸 {im.size}，应为 {(R.W, R.H)}")
        if i == 0:
            rec.update(cover_checks(im, theme, errors, notes, cover_style))
        else:
            name, st = body_styles[i - 1] if i - 1 < len(body_styles) else ("深色", None)
            rec.update(body_checks(im, theme, errors, notes, last=(i == len(pages) - 1),
                                   style=st))
            rec["版本"] = name
        page_reports.append(rec)

    cand_dir = pages_dir / "封面候选"
    cands = sorted(cand_dir.glob("p01-*.png")) if cand_dir.exists() else []
    if not cands:
        notes.append("没有封面候选图（pages/封面候选/）。只想出一版封面可以忽略。")
    for c in cands:
        if Image.open(c).size != (R.W, R.H):
            errors.append(f"候选封面 {c.name} 尺寸不是 {(R.W, R.H)}")

    # 配色
    if pages:
        c = Image.open(pages[0]).convert("RGB")
        st = R.LIGHT_STYLES.get(cover_style)
        probes = ([("底色", (6, 6), st["底色"])]
                  + ([("色带", ((st["色带框"][0] + st["色带框"][2]) // 2,
                                (st["色带框"][1] + st["色带框"][3]) // 2), st["色带"])] if st.get("色带框") else [])
                  ) if st else [("底色", (1380, 1500), theme["底色"]), ("色块", (1380, 2300), theme["色块"])]
        for label, xy, want in probes:
            got = "#%02X%02X%02X" % c.getpixel(xy)
            if not near(got, want, 16):
                notes.append(f"封面{label}实测 {got}，目标 {want}（可能被插画或角标覆盖，确认一下）")
        for i, (name, bst) in enumerate(body_styles, 2):
            f = pages_dir / f"p{i:02d}.png"
            if not f.exists():
                continue
            got = dominant_color(Image.open(f))
            if not near(got, bst["底色"], 12):
                errors.append(
                    f"p{i:02d}.png 底色实测 {got}，目标 {bst['底色']}"
                    f"（正文页版本「{name}」），请重新运行 render.py"
                )

    # 分页是否和当前 笔记.json 一致（防止改了文案没重渲染）
    ts = R.Typesetter(theme["正文字号"], theme["字重"])
    paras = R.paragraphs_of(spec.get("正文", ""))
    lines = R.build_lines(paras, ts, theme["正文右边界"] - theme["正文左边距"])
    plan = R.paginate(lines, theme)
    chars = R.char_count(spec.get("正文", ""))
    mins = R.reading_minutes(chars, theme["阅读速度"])
    if len(plan) != len(pages) - 1:
        errors.append(f"笔记.json 当前应为 {len(plan)} 页正文，实际渲染了 {len(pages) - 1} 页，请重新运行 render.py")
    else:
        for i, (pg, rec) in enumerate(zip(plan, page_reports[1:]), 2):
            if len(pg) != rec.get("行数"):
                errors.append(f"p{i:02d}.png 实测量到 {rec.get('行数')} 行，应为 {len(pg)} 行，请重新运行 render.py")

    # 封面上的字数/时长必须和正文一致
    cover_meta = (rep.get("封面") or {}).get("字数行", "")
    if rep:
        if rep.get("正文", {}).get("字数") not in (None, chars):
            errors.append("渲染报告里的字数与当前 笔记.json 不一致，请重新运行 render.py")
    m = re.search(r"全文(\d+)字", cover_meta)
    if m and int(m.group(1)) != chars:
        errors.append(f"封面写「全文{m.group(1)}字」，正文实际 {chars} 字")
    if m and not re.search(r"阅读需\d+分钟", cover_meta):
        notes.append("封面字数行缺「阅读需N分钟」")
    elif m and int(re.search(r"阅读需(\d+)分钟", cover_meta).group(1)) != mins:
        notes.append(f"封面阅读时长与按 {theme['阅读速度']} 字/分钟估算的 {mins} 分钟不一致")

    # 拼版预览：所有图摆在一起的那张，必须有，而且要和当前页数对得上
    if not preview.exists():
        errors.append(f"没有整套拼版预览图：{preview}（交付必须有「所有图摆在一起」的那一张，"
                      "重新运行 render.py）")
    else:
        want = R.preview_grid_size(len(pages))
        got = Image.open(preview).size
        if tuple(got) != tuple(want):
            errors.append(f"拼版预览 {preview.name} 尺寸 {tuple(got)}，按当前 {len(pages)} 张图应为 "
                          f"{want}，说明它是旧的或没包含全部图，请重新运行 render.py")

    # 字数：默认 2000-3500，上限 5000，别超
    if chars > 5000:
        errors.append(f"正文 {chars} 字，超过 5000 字上限：先删重复的例子和空话，再压到 5000 字以内")
    elif chars < 1000:
        notes.append(f"正文只有 {chars} 字，作为长文图文偏短，建议写到 2000 字以上")
    if len(plan) > 9:
        notes.append(f"正文 {len(plan)} 页（约 {chars} 字），超过 9 页小红书容易折叠/截断；"
                     "要么压字数，要么跟用户确认可以这么长")
    target = spec.get("字数目标")
    try:
        target = int(target) if target else None
    except (TypeError, ValueError):
        target = None
        notes.append("字数目标 不是数字，已忽略")
    if target:
        if abs(chars - target) > max(200, target * 0.15):
            notes.append(f"字数目标是 {target} 字，实际 {chars} 字，差得有点多，确认是保留还是压一版")

    # 内容质量（只提醒，不阻塞）：AI 腔、段落节奏、发布件完整性
    prose = "\n".join([
        spec.get("正文", ""),
        spec.get("帖子文案", ""),
        "".join((spec.get("封面") or {}).get("标题行") or []),
        (spec.get("封面") or {}).get("导语", "") or "",
    ])
    hits = ai_tone_hits(prose)
    for label, sample in hits[:10]:
        notes.append(f"疑似 AI 腔（{label}）：「{sample}」")
    if len(hits) > 10:
        notes.append(f"另有 {len(hits) - 10} 处疑似 AI 腔，整篇再读一遍")
    rhythm = rhythm_note(spec.get("正文", ""))
    if rhythm:
        notes.append(rhythm)
    source_checks(spec, base, errors, notes)
    cover_notes(spec, notes)
    publish = publish_checks(spec, base, notes)

    report = {
        "笔记": str(spec_path),
        "页面数": len(pages),
        "封面版本": [c.name for c in cands],
        "字数": chars,
        "阅读分钟": mins,
        "每页": page_reports,
        "ai_tone_hits": [f"{label}：{sample}" for label, sample in hits],
        "发布件": publish,
        "errors": errors,
        "warnings": notes,
        "visual_acceptance": "未验收：必须人工逐页看原始尺寸图",
    }
    (base / "校验报告.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"页面 {len(pages)} 张｜正文 {chars} 字｜约 {mins} 分钟")
    for rec in page_reports:
        bbox = rec.get("墨迹")
        cov = rec.get("覆盖率")
        extra = f" 行数={rec.get('行数')}" if "行数" in rec else ""
        if rec.get("版本") and "行数" in rec:
            extra += f" 版本={rec['版本']}"
        print(f"  {Path(rec['文件']).name:8s} 墨迹={bbox} 覆盖={cov}{extra}")
    if errors:
        print("\n错误：")
        for e in errors:
            print("  -", e)
    if notes:
        print("\n提醒（需人工确认）：")
        for n in notes:
            print("  -", n)
    print("\n视觉验收：未完成。技术通过不等于可以交付，请把每一页按 1440×2400 看过一遍。")
    return 1 if errors else 0


def ink_stats_bg(img: Image.Image, bg_hex: str, tol: int = 42):
    """浅底用：找出比底色深的像素（文字/线），深底页走 ink_stats。"""
    bg = R.rgba(bg_hex)
    px = img.convert("RGB").load()
    w, h = img.size
    xs, ys, n = [], [], 0
    for y in range(h):
        for x in range(w):
            c = px[x, y]
            if sum(max(0, bg[i] - c[i]) for i in range(3)) > tol:
                xs.append(x)
                ys.append(y)
                n += 1
    if not xs:
        return None
    return {"bbox": [min(xs), min(ys), max(xs), max(ys)], "覆盖率": round(n / (w * h), 4)}


def cover_checks(im, theme, errors, notes, style="深色"):
    if style == "深色":
        return _cover_checks_dark(im, theme, errors, notes)
    st = R.LIGHT_STYLES.get(style)
    if not st:
        notes.append(f"不认识封面版本「{style}」，跳过封面专项检查")
        return {}
    return _cover_checks_light(im, st, errors, notes, style)


def _cover_checks_light(im, st, errors, notes, style):
    rgb = im.convert("RGB")
    rec = {"版本": style}
    bg = st["底色"]
    parts = {}
    x0i, y0i, x1i, y1i = st["图片框"]
    crop = rgb.crop((x0i + 24, y0i + 24, x1i - 24, y1i - 24))
    b = R.rgba(bg)
    px = crop.load()
    diff = 0
    n = 0
    for y in range(0, crop.size[1], 3):
        for x in range(0, crop.size[0], 3):
            c = px[x, y]
            n += 1
            if sum(abs(c[i] - b[i]) for i in range(3)) > 40:
                diff += 1
    if n and diff / n < 0.5:
        errors.append(f"{style} 封面图区（{x0i},{y0i}-{x1i},{y1i}）看起来是空的，确认插画有没有贴上去")

    ck = st.get("检查框", {})
    boxes = [
        ("元信息", (0, st["元信息墨顶"] - 34, R.W, st["元信息墨顶"] + 70)),
        ("标题", tuple(ck.get("标题", [0, st["标题墨顶"] - 40, R.W, y0i - 10]))),
        ("导语", tuple(ck.get("导语", [0, st["导语墨顶"] - 40, R.W,
                                       st["导语墨顶"] + int(st["导语行距"] * 3)]))),
    ]
    for label, box in boxes:
        c = rgb.crop(box)
        stt = ink_stats_bg(c, bg, 200)
        if not stt:
            errors.append(f"{style} 封面「{label}」区域没有内容")
            continue
        x0, y0, x1, y1 = stt["bbox"]
        parts[label] = [x0 + box[0], y0 + box[1], x1 + box[0], y1 + box[1]]
    rec["区块"] = parts
    if "标题" in parts:
        x0, y0, x1, y1 = parts["标题"]
        if x0 < st["标题左"] - 14 or x1 > st["标题右"] + 40:
            errors.append(f"{style} 封面标题左右越界：{x0}..{x1}")
        if y1 > y0i - 20:
            errors.append(f"{style} 封面标题压到图片：标题底 {y1}，图顶 {y0i}")
    if "导语" in parts and parts["导语"][3] > R.H - 30:
        errors.append(f"{style} 封面导语贴到画面底边")
    rec["墨迹"] = parts.get("标题")
    rec["覆盖率"] = None
    return rec


def _cover_checks_dark(im, theme, errors, notes):
    rec = {}
    rgb = im.convert("RGB")
    # 插画必须铺满顶区
    band_y = theme["色块顶"]
    for y in (4, theme["插画高"] // 2, theme["插画高"] - 6):
        for x in (4, R.W // 2, R.W - 5):
            if rgb.getpixel((x, y)) == R.rgba(theme["底色"]):
                notes.append(f"封面顶部 ({x},{y}) 还是底色，插画可能没铺满或没给插画")
                break
    meta = R.Typesetter(theme["元信息字号"], theme["字重"])
    parts = {}
    for label, box in [
        ("元信息", (60, theme["元信息墨顶"] - 30, 1200, theme["元信息墨顶"] + 70)),
        ("标题", (0, theme["标题墨顶"] - 40, R.W, band_y - 10)),
        ("导语", (0, band_y, R.W, R.H - 20)),
    ]:
        crop = rgb.crop((box[0], box[1], box[2], box[3]))
        st = ink_stats(crop, 110)
        if not st:
            errors.append(f"封面「{label}」区域没有内容")
            continue
        x0, y0, x1, y1 = st["bbox"]
        parts[label] = [x0 + box[0], y0 + box[1], x1 + box[0], y1 + box[1]]
    rec["区块"] = parts
    if "标题" in parts:
        x0, y0, x1, y1 = parts["标题"]
        if x0 < theme["封面左边距"] - 12 or x1 > theme["封面右边界"] + 12:
            errors.append(f"封面标题左右越界：{x0}..{x1}")
        if y1 > band_y - 20:
            errors.append(f"封面标题压到色块：标题底 {y1}，色块顶 {band_y}")
    if "导语" in parts and parts["导语"][3] > R.H - 40:
        errors.append("封面导语贴到画面底边")
    rec["墨迹"] = parts.get("标题")
    rec["覆盖率"] = None
    return rec


def body_checks(im, theme, errors, notes, last=False, style=None):
    rgb = im.convert("RGB")
    st = style or {"底色": theme["底色"], "正文色": theme["正文色"]}
    dark = is_dark(st["底色"])
    thresh = ink_threshold(st, dark)
    if dark:
        ink = ink_stats(rgb, thresh)
        runs = line_runs(rgb, thresh)
    else:
        ink = ink_stats_bg(rgb, st["底色"], thresh)
        runs = line_runs_light(rgb, st["底色"], thresh)
    if not ink:
        errors.append("正文页是空的")
        return {"墨迹": None, "覆盖率": 0, "底色": st["底色"]}
    x0, y0, x1, y1 = ink["bbox"]
    left, right = theme["正文左边距"], theme["正文右边界"]
    if x0 < left - 12:
        errors.append(f"左越过边距：{x0} < {left}")
    if x1 > right + 45:
        errors.append(f"右越过边距：{x1} > {right}")
    if y0 < theme["正文墨顶"] - 12:
        errors.append(f"顶越过边距：{y0} < {theme['正文墨顶']}")
    if y1 > 2240:
        errors.append(f"底越过安全线：{y1} > 2240")
    if len(runs) > theme["正文最大行数"]:
        errors.append(f"排了 {len(runs)} 行，超过每页 {theme['正文最大行数']} 行上限")
    if ink["覆盖率"] < 0.02:
        errors.append(f"墨迹覆盖率只有 {ink['覆盖率']}，这一页几乎是空的")
    elif ink["覆盖率"] < 0.055:
        notes.append(f"墨迹覆盖率只有 {ink['覆盖率']}，这一页可能太空")
    if last and len(runs) < theme["正文最小行数"]:
        notes.append(f"末页只有 {len(runs)} 行，建议补内容或压页")
    return {"墨迹": [x0, y0, x1, y1], "覆盖率": ink["覆盖率"], "行数": len(runs),
            "底色": st["底色"], "图案": st.get("图案", "无")}


# ---------------------------------------------------------------- 内容质量
# 只提醒，不报错：check.py 判不了「像不像真人写的」，只把最像机器的痕迹挑出来给人看。
AI_PATTERNS = [
    ("空洞收尾", r"综上所述|总而言之|总的来说|由此可见|希望对(你|您)有帮助|以上就是"),
    ("万能开场", r"在当今(社会|这个|时代)|在这个(快节奏|信息爆炸|内卷)|"
                 r"随着(社会|时代|科技|互联网|生活水平)的(发展|进步|普及|提高)"),
    ("排比套话", r"不仅是.{0,14}更(是|要|需要)|让我们(一起|共同)|"
                 r"无论(你|您)是.{0,12}还是|既(能|要).{0,12}(又|也)"),
    ("互联网黑话", r"赋能|助力|抓手|闭环|颗粒度|底层逻辑|组合拳"),
    ("平台腔", r"干货满满|保姆级|一文读懂|必看|深度好文|纯干货|码住|建议收藏"),
    ("空形容词", r"极大地|显著地|深深地|充分地|很大程度上"),
    ("定义句开场", r"^\s*(所谓|什么是)?.{2,12}(是|就是)(一种|一个)"),
]
PLATFORM_WORDS = ("收藏", "点赞", "关注", "干货", "必看", "三连")


def ai_tone_hits(text: str) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    seen: set[str] = set()
    for para in text.split("\n"):
        if not para.strip():
            continue
        for label, pat in AI_PATTERNS:
            for m in re.finditer(pat, para, re.MULTILINE):
                word = m.group(0)
                if word in seen:
                    continue
                seen.add(word)
                hits.append((label, word))
    return hits


def rhythm_note(body: str) -> str | None:
    """每段字数几乎一样，读起来就是机器在匀速输出。"""
    lens = [len("".join(p.split())) for p in R.paragraphs_of(body)]
    if len(lens) < 5:
        return None
    mean = sum(lens) / len(lens)
    if mean and (max(lens) - min(lens)) / mean < 0.25:
        return (f"正文 {len(lens)} 段，字数都在 {min(lens)}-{max(lens)} 之间、长度几乎一样，"
                "读起来像模板；把最长的段拆开，或让某一段只写两三句")
    return None


def source_checks(spec: dict, base: Path, errors: list[str], notes: list[str]) -> None:
    """用户给了经历就不能编：正文里的数字都要能在 素材.md 里找到。"""
    name = str(spec.get("素材") or "").strip()
    if not name:
        return
    p = base / name
    if not p.exists():
        errors.append(f"笔记.json 里写了 素材: {name}，但笔记目录里没有这个文件（原文要原样留着）")
        return
    text = p.read_text(encoding="utf-8", errors="ignore")
    if not text.strip():
        notes.append(f"{name} 是空的，正文没法对照素材核一遍")
        return
    body = str(spec.get("正文") or "")
    missing = sorted({n for n in re.findall(r"[0-9][0-9.]*", body) if n not in text})
    if missing:
        notes.append("正文里的这些数字在 " + name + " 里找不到，确认不是编的："
                     + "、".join(missing[:10])
                     + ("…" if len(missing) > 10 else ""))


def cover_notes(spec: dict, notes: list[str]) -> None:
    """封面插画要合主题：这张图说不出「画的是什么、为什么合主题」，就是不对题。"""
    cov = spec.get("封面") or {}
    if not cov.get("插画"):
        return
    desc = str(cov.get("插画说明") or "").strip()
    if not desc:
        notes.append("封面插画没写 封面.插画说明：没法核对这张图是不是合主题"
                     "（把标题遮住、只看图能猜到讲什么才算合）")
    elif len(desc) < 12:
        notes.append(f"封面.插画说明只有 {len(desc)} 字，写清画的是什么、为什么合主题，"
                     "以及素材来源")


def publish_checks(spec: dict, base: Path, notes: list[str]) -> dict:
    """发布件完整性：题目、3 段文案、标签、首评。缺了不报错，但一定要让人看见。"""
    titles = [str(t).strip() for t in (spec.get("标题候选") or []) if str(t).strip()]
    caption = (spec.get("帖子文案") or "").strip()
    tags = [str(t).strip() for t in (spec.get("标签") or []) if str(t).strip()]
    first = (spec.get("首评") or "").strip()

    if not titles:
        notes.append("没有 标题候选：用户拿不到能直接发的题目，按规范写 2-3 个")
    else:
        if len(titles) < 2:
            notes.append("标题候选只有 1 个，建议给 2-3 个让用户挑")
        for t in titles:
            if len(t) > 22:
                notes.append(f"题目候选「{t}」有 {len(t)} 字，超过 20 字容易被折叠")

    if not caption:
        notes.append("没有 帖子文案：只有图没有文案，等于没做完")
    else:
        paras = R.paragraphs_of(caption)
        total = len("".join(caption.split()))
        if len(paras) != 3:
            notes.append(f"帖子文案是 {len(paras)} 段，规范要求 3 段（第 1 段勾人、第 2 段有用、第 3 段收尾）")
        if total < 120:
            notes.append(f"帖子文案只有 {total} 字，太短，第 2 段没给出真正有用的东西")
        elif total > 460:
            notes.append(f"帖子文案 {total} 字，偏长，小红书正文会被折叠，建议压到 300 字上下")
        for word in PLATFORM_WORDS:
            if word in caption:
                notes.append(f"帖子文案里出现「{word}」，是平台腔，删掉")

    if len(tags) < 3:
        notes.append(f"话题标签只有 {len(tags)} 个，建议 3-6 个：1 个大词 + 2-3 个细分词")
    if not first:
        notes.append("没有 首评：出处和补充资料没地方放（图上不写出处）")
    if not (base / "来源.md").exists():
        notes.append("笔记目录里没有 来源.md：正文里的数字和案例没有出处")

    return {
        "标题候选": titles,
        "文案段数": len(R.paragraphs_of(caption)),
        "文案字数": len("".join(caption.split())),
        "标签数": len(tags),
        "有首评": bool(first),
    }


if __name__ == "__main__":
    sys.exit(main())
