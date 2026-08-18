#!/usr/bin/env python3
"""用 new_list.json 刷新文档树中存量法规的时效性状态（frontmatter 的 status 字段）。

原地更新 markdown 文件：重写时以“重新渲染 + 正文原样回写”方式进行，
除 status 行外与原文件逐字节一致（verify_all.py 的回环校验可证实这一点）。
同时报告新库有而本地缺失的条数。
"""
import json
import os
import sys

import md_tree


def main():
    rows = {r["bbbs"]: r for r in json.load(open(md_tree.NEW_LIST, encoding="utf-8"))["rows"]}
    scanned = updated = nomatch = badid = parsefail = 0
    seen = set()
    changes = []
    for dirpath, _, filenames in os.walk(md_tree.MD_ROOT):
        for fn in sorted(filenames):
            if not fn.endswith(".md"):
                continue
            path = os.path.join(dirpath, fn)
            with open(path, encoding="utf-8", newline="") as f:
                text = f.read()
            fm, body = md_tree.parse(text)
            if fm is None:
                parsefail += 1
                print("frontmatter 无法解析:", path, file=sys.stderr)
                continue
            scanned += 1
            bbbs = md_tree.bbbs_of_id(fm.get("id") or "")
            if not bbbs:
                badid += 1
                continue
            seen.add(bbbs)
            r = rows.get(bbbs)
            if not r:
                nomatch += 1
                continue
            new_status = md_tree.STATUS_MAP.get(r.get("sxx"))
            if new_status is None or new_status == fm.get("status"):
                continue
            changes.append((path, fm.get("status"), new_status))
            fm["status"] = new_status
            md_tree.write_atomic(path, md_tree.render(fm, body))
            updated += 1

    missing = [r for b, r in rows.items() if b not in seen]
    print(f"扫描 {scanned} 个文件 | status 更新 {updated} | 新库无对应 {nomatch} "
          f"| id 无法解码 {badid} | 解析失败 {parsefail}")
    for p, old, new in changes[:20]:
        print(f"  {old or '空'} -> {new}  {os.path.relpath(p, md_tree.MD_ROOT)}")
    if len(changes) > 20:
        print(f"  ...（共 {len(changes)} 条变更）")
    if missing:
        print(f"新库有而本地缺失 {len(missing)} 条：运行 fetch_new_laws.py 抓取")
    sys.exit(0 if parsefail == 0 else 1)


if __name__ == "__main__":
    main()
