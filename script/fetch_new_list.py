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
MAX_OFFSET = 30000  # API 对 offset ≥ 30000 的深分页固定返回 500（系统异常），需反序补抓尾部
GAP_TOLERANCE = 5   # 正反两段合并后允许的最大缺口：上游 total 偶有虚高（条目已下架/隐藏但计数未扣），
                    # 深分页窗口内永远取不到，重跑也无法消除（实测连续两轮稳定差同 2 条）
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 仓库根目录 = script/ 的上一级
OUT = os.path.join(ROOT, "new_list.json")


def post(body):
    req = urllib.request.Request(API, data=json.dumps(body).encode(), headers=UA, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_pages(body, label, stop=None):
    """按 body 里的排序方向从第 1 页抓起，返回 (rows, total, capped)。

    API 对 offset >= MAX_OFFSET 的深分页固定返回 500（系统异常），因此抓到
    MAX_OFFSET 为止即止（capped=True），缺口由调用方用反序分页补齐。
    """
    rows, page, total = [], 1, None
    while True:
        if (page - 1) * PAGE_SIZE >= MAX_OFFSET:
            return rows, total, True
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
                print(f"{label} page {page} attempt {attempt+1} failed: {e}; retrying...", file=sys.stderr)
                time.sleep(3 * (attempt + 1))
        total = d["total"]
        batch = d.get("rows") or []
        rows.extend(batch)
        print(f"{label} page {page}: +{len(batch)} (cum {len(rows)}/{total})", file=sys.stderr)
        if stop and stop(rows):
            return rows, total, False
        if len(rows) >= total or not batch:
            return rows, total, False
        page += 1
        time.sleep(0.6)

def main():
    body = {
        "searchRange": 1, "sxrq": [], "gbrq": [], "searchType": 2, "sxx": [],
        "gbrqYear": [], "flfgCodeId": [], "zdjgCodeId": [], "searchContent": "",
        "orderByParam": {"order": "-1", "sort": ""}, "pageNum": 1, "pageSize": PAGE_SIZE,
    }
    rows, total, capped = fetch_pages(body, "fwd")
    if capped and total is not None and len(rows) < total:
        # 正序触达深分页上限：改用反序从尾部补抓剩余条目（重复项随后去重）
        print(f"hit deep-pagination cap, fetching tail in reverse order", file=sys.stderr)
        tail_body = json.loads(json.dumps(body))
        tail_body["orderByParam"]["order"] = "1"
        seen = {r["bbbs"] for r in rows}
        rev_done = lambda tail: len(seen | {r["bbbs"] for r in tail}) >= total
        tail_rows, total, tail_capped = fetch_pages(tail_body, "rev", stop=rev_done)
        rows.extend(tail_rows)
    # 去重（保险）
    seen, uniq = set(), []
    for r in rows:
        if r["bbbs"] not in seen:
            seen.add(r["bbbs"])
            uniq.append(r)
    if total is not None and len(uniq) < total:
        gap = total - len(uniq)
        if gap > GAP_TOLERANCE:
            raise RuntimeError(f"coverage {len(uniq)}/{total}: 深分页受限且反序补抓未能覆盖全量，请重跑")
        print(f"WARNING: coverage gap {gap}/{total} within tolerance "
              f"(upstream total likely overcounts withdrawn entries); saving anyway", file=sys.stderr)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"total": total, "fetched": len(uniq), "rows": uniq}, f, ensure_ascii=False)
    print(f"saved {len(uniq)} unique rows (total reported: {total}"
          + (f", gap {total - len(uniq)}" if total is not None and len(uniq) < total else "") + ")")


if __name__ == "__main__":
    main()
