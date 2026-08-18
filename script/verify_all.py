#!/usr/bin/env python3
"""文档树最终校验。

1. 树自洽：每个文件 frontmatter 完整可解析、字段齐全、id 唯一且可解码回 bbbs、
   重新渲染与原文逐字节一致（防格式漂移）、正文非空；
2. 与 new_list.json 交叉核对：status 与远端索引一致（不一致判失败，update_status.py 可修复）；
   title 不一致仅告警——上游标题本身存在漂移（如给失效决定追加“（失效）”后缀、
   修订笔误等），本地标题以实际文档为准，不自动同步；
   新库有而树中缺失的条目计数（告警不判失败——抓取失败/未抓取属正常状态）。
"""
import json
import os
import sys

import md_tree


def main():
    rows = {}
    if os.path.exists(md_tree.NEW_LIST):
        rows = {r["bbbs"]: r for r in json.load(open(md_tree.NEW_LIST, encoding="utf-8"))["rows"]}

    n = 0
    ids = set()
    seen_bbbs = set()
    errors = 0
    badid = 0
    title_drift = []
    for dirpath, _, filenames in os.walk(md_tree.MD_ROOT):
        for fn in sorted(filenames):
            if not fn.endswith(".md"):
                continue
            path = os.path.join(dirpath, fn)
            with open(path, encoding="utf-8", newline="") as f:
                text = f.read()
            n += 1
            fm, body = md_tree.parse(text)
            if fm is None:
                errors += 1
                print("frontmatter 无法解析:", path)
                continue
            missing_fields = [k for k in md_tree.META_FIELDS if k not in fm]
            if missing_fields:
                errors += 1
                print("frontmatter 缺字段:", path, missing_fields)
                continue
            if not fm.get("title"):
                errors += 1
                print("title 为空:", path)
                continue
            if fm["id"] in ids:
                errors += 1
                print("重复 id:", path)
                continue
            ids.add(fm["id"])
            if md_tree.render(fm, body) != text:
                errors += 1
                print("重新渲染不一致（格式漂移）:", path)
            prefix = f"\n# {fm['title']}\n\n"
            if not body.startswith(prefix) or len(body.rstrip()) <= len(prefix.rstrip()):
                errors += 1
                print("正文缺失:", path)
            bbbs = md_tree.bbbs_of_id(fm["id"])
            if not bbbs:
                badid += 1
                print("id 无法解码:", path)
                continue
            seen_bbbs.add(bbbs)
            r = rows.get(bbbs)
            if r:
                st = md_tree.STATUS_MAP.get(r.get("sxx"))
                if st is not None and st != fm.get("status"):
                    errors += 1
                    print(f"status 与 new_list 不一致: {path}: {fm.get('status')!r} -> {st!r}")
                if (r.get("title") or "") != fm.get("title"):
                    title_drift.append((path, fm.get("title"), r.get("title")))

    print(f"markdown 文件: {n} | id 唯一: {len(ids)} | 解析/格式/status错误: {errors} | id 解码失败: {badid}")
    if title_drift:
        print(f"title 与 new_list 漂移 {len(title_drift)} 条（告警，不判失败；上游标题变更不自动同步）:")
        for p, old, new in title_drift[:5]:
            print(f"  本地: {old}\n  远端: {new}\n  文件: {os.path.relpath(p, md_tree.MD_ROOT)}")
    missing = [r for b, r in rows.items() if b not in seen_bbbs]
    if rows:
        print(f"new_list 共 {len(rows)} 条 | 树中缺失 {len(missing)} 条（告警，不判失败）")
        for r in missing[:5]:
            print("  -", r.get("title"))
    ok = errors == 0 and badid == 0
    print("校验结果:", "全部通过 ✓" if ok else "存在问题 ✗")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
