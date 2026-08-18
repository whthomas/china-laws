#!/usr/bin/env python3
"""从 flk.npc.gov.cn 新版 API 抓取全量法规列表，保存为 new_list.json。"""
import json
import os
import time
import urllib.request
import urllib.error
import sys

API = "https://flk.npc.gov.cn/law-search/search/list"
UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://flk.npc.gov.cn",
    "Referer": "https://flk.npc.gov.cn/search",
}
PAGE_SIZE = 500
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 仓库根目录 = script/ 的上一级
OUT = os.path.join(ROOT, "new_list.json")


def post(body):
    req = urllib.request.Request(API, data=json.dumps(body).encode(), headers=UA, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main():
    body = {
        "searchRange": 1, "sxrq": [], "gbrq": [], "searchType": 2, "sxx": [],
        "gbrqYear": [], "flfgCodeId": [], "zdjgCodeId": [], "searchContent": "",
        "orderByParam": {"order": "-1", "sort": ""}, "pageNum": 1, "pageSize": PAGE_SIZE,
    }
    rows, page, total = [], 1, None
    while True:
        for attempt in range(5):
            try:
                body["pageNum"] = page
                d = post(body)
                if d.get("code") != 200:
                    raise RuntimeError(f"code={d.get('code')} msg={d.get('msg')}")
                break
            except Exception as e:
                if attempt == 4:
                    raise
                print(f"page {page} attempt {attempt+1} failed: {e}; retrying...", file=sys.stderr)
                time.sleep(3 * (attempt + 1))
        total = d["total"]
        batch = d.get("rows") or []
        rows.extend(batch)
        print(f"page {page}: +{len(batch)} (cum {len(rows)}/{total})", file=sys.stderr)
        if len(rows) >= total or not batch:
            break
        page += 1
        time.sleep(0.6)
    # 去重（保险）
    seen, uniq = set(), []
    for r in rows:
        if r["bbbs"] not in seen:
            seen.add(r["bbbs"])
            uniq.append(r)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"total": total, "fetched": len(uniq), "rows": uniq}, f, ensure_ascii=False)
    print(f"saved {len(uniq)} unique rows (total reported: {total})")


if __name__ == "__main__":
    main()
