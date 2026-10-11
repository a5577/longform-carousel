#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把渲染结果整理成一份可以直接用的交付目录。

用法：
    python package.py --note <笔记目录> [--out 交付] [--accept-visual "理由"]

没有通过 check.py 就不允许打包；确实只是留档时再加 --force。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render as R  # noqa: E402


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="打包小红书长文图文交付目录")
    ap.add_argument("--note", required=True, help="笔记目录（含 笔记.json）")
    ap.add_argument("--out", default="交付", help="交付目录")
    ap.add_argument("--accept-visual", default=None, help="逐页看过之后写一句放行理由")
    ap.add_argument("--force", action="store_true", help="校验没过也打包（仅留档用）")
    args = ap.parse_args(argv)

    spec, spec_path = R.load_spec(args.note)
    base = Path(spec["_base"])
    out = Path(args.out)
    if not out.is_absolute():
        out = base / out

    rep_file = base / "校验报告.json"
    if not rep_file.exists():
        print("缺少 校验报告.json，先跑 check.py", file=sys.stderr)
        if not args.force:
            return 2
        check = {}
    else:
        check = json.loads(rep_file.read_text(encoding="utf-8"))
    errors = check.get("errors", [])
    if errors and not args.force:
        print("校验有错误，先修好再打包；确实只是留档再加 --force：", file=sys.stderr)
        for e in errors:
            print("  -", e, file=sys.stderr)
        return 2
    if not args.accept_visual and not args.force:
        print("还没有逐页看过图。看完每一页、确认没问题后，用 "
              '--accept-visual "你的理由" 重新运行。', file=sys.stderr)
        return 2

    out_cfg = spec.get("输出", {})
    pages_dir = Path(out_cfg.get("页面目录", "pages"))
    if not pages_dir.is_absolute():
        pages_dir = base / pages_dir
    preview = Path(out_cfg.get("预览", "全套预览.jpg"))
    if not preview.is_absolute():
        preview = base / preview
    pages = sorted(pages_dir.glob("p*.png"))
    if not pages:
        print("没有页面可打包", file=sys.stderr)
        return 2

    dest_pages = out / "页面"
    if dest_pages.exists():
        shutil.rmtree(dest_pages)
    dest_pages.mkdir(parents=True)
    manifest_files = []
    for p in pages:
        q = dest_pages / p.name
        shutil.copy2(p, q)
        manifest_files.append({"路径": f"页面/{p.name}", "sha256": sha256(q), "字节": q.stat().st_size})
    if preview.exists():
        shutil.copy2(preview, out / "全套预览.jpg")
        manifest_files.append({"路径": "全套预览.jpg", "sha256": sha256(out / "全套预览.jpg"),
                               "字节": (out / "全套预览.jpg").stat().st_size})
    cand_dir = pages_dir / "封面候选"
    cover_files = []
    if cand_dir.exists():
        dest_cand = out / "封面候选"
        if dest_cand.exists():
            shutil.rmtree(dest_cand)
        dest_cand.mkdir(parents=True)
        for c in sorted(cand_dir.glob("*.png")):
            q = dest_cand / c.name
            shutil.copy2(c, q)
            cover_files.append(c.name)
            manifest_files.append({"路径": f"封面候选/{c.name}", "sha256": sha256(q),
                                   "字节": q.stat().st_size})

    title = spec.get("标题", "")
    body = spec.get("正文", "")
    caption = (spec.get("帖子文案") or "").strip()
    tags = [str(t).strip() for t in (spec.get("标签") or []) if str(t).strip()]
    titles = [str(t).strip() for t in (spec.get("标题候选") or []) if str(t).strip()]
    first_comment = (spec.get("首评") or "").strip()
    cover = spec.get("封面", {})
    paragraphs = [p for p in caption.split("\n") if p.strip()]

    (out / "标题.txt").write_text(title + "\n", encoding="utf-8")
    (out / "正文.txt").write_text(body.strip() + "\n", encoding="utf-8")
    if titles:
        (out / "标题候选.txt").write_text("\n".join(titles) + "\n", encoding="utf-8")
    if caption:
        (out / "帖子文案.txt").write_text(caption + "\n", encoding="utf-8")
    if tags:
        (out / "话题标签.txt").write_text(" ".join(tags) + "\n", encoding="utf-8")
    if first_comment:
        (out / "首评.txt").write_text(first_comment + "\n", encoding="utf-8")

    # 发布文案.md：把要复制进小红书 App 的东西集中到一处
    pick = "\n".join(f"{i}. {t}" for i, t in enumerate(titles, 1)) or "（没写 标题候选）"
    (out / "发布文案.md").write_text(
        "# 发布文案\n\n"
        f"## 题目（挑一个）\n\n{pick}\n\n"
        f"## 文案（{len(paragraphs)} 段，整段复制）\n\n{caption or '（没写 帖子文案）'}\n\n"
        f"{' '.join(tags)}\n\n"
        f"## 首评\n\n{first_comment or '（没写 首评）'}\n\n"
        f"## 图片\n\n封面 + {len(pages) - 1} 页正文，见 `页面/`；整套预览见 `全套预览.jpg`。\n",
        encoding="utf-8",
    )
    manifest_files.append({"路径": "发布文案.md", "sha256": sha256(out / "发布文案.md"),
                           "字节": (out / "发布文案.md").stat().st_size})

    missing = [label for label, value in
               [("标题候选", titles), ("帖子文案", caption), ("话题标签", tags), ("首评", first_comment)]
               if not value]
    if missing:
        print(f"提醒：发布件缺 {'、'.join(missing)}，" "用户拿不到能直接发的东西。", file=sys.stderr)
    elif len(paragraphs) < 3:
        print(f"提醒：帖子文案只有 {len(paragraphs)} 段，规范要求 3 段。", file=sys.stderr)
    cover_lines = "".join(cover.get("标题行", [])) or cover.get("标题", "")
    (out / "封面文案.txt").write_text(
        f"标题：{cover_lines}\n导语：{cover.get('导语', '')}\n"
        f"字数行：{cover.get('字数行', 'auto')}\n插画：{cover.get('插画', '（未指定）')}\n"
        f"插画说明：{cover.get('插画说明', '（未写）')}\n",
        encoding="utf-8",
    )
    src = base / "来源.md"
    if src.exists():
        shutil.copy2(src, out / "来源.md")
    else:
        print("提醒：笔记目录里没有 来源.md，交付内容将缺少出处记录。", file=sys.stderr)

    manifest = {
        "标题": title,
        "页数": len(pages),
        "封面候选": cover_files,
        "封面插画": {"文件": cover.get("插画", ""), "说明": cover.get("插画说明", "")},
        "发布件": {
            "题目候选": titles,
            "文案段数": len(paragraphs),
            "文案字数": len("".join(caption.split())),
            "标签": tags,
            "首评字数": len("".join(first_comment.split())),
            "缺": missing,
        },
        "字数": check.get("字数", R.char_count(body)),
        "阅读分钟": check.get("阅读分钟"),
        "文件": manifest_files,
        "校验": {"errors": errors, "warnings": check.get("warnings", [])},
        "visual_accepted": args.accept_visual or "未验收（--force 打包）",
        "备注": "封面与正文页尺寸均为 1440×2400；交付前请自己按原始尺寸再看一遍每一页。",
    }
    (out / "交付清单.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"交付目录 → {out}")
    print(f"  页面 {len(pages)} 张，正文 {manifest['字数']} 字")
    if errors:
        print(f"  注意：有 {len(errors)} 个校验错误被 --force 放行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
