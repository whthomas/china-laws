#!/usr/bin/env python3
"""下载新增法规的正文，直接以 Markdown 文件写入文档树（markdown/ 为唯一数据源）。

- 对比 new_list.json 与文档树 frontmatter 的 id 索引找出新增法规，逐条下载后
  立即落盘为一个 md 文件（临时文件 + 原子替换），格式与整树导出完全一致；
- 主路线: download/pc -> 签名 OSS URL -> docx -> 纯 Python 提取段落
- 兜底:   flfgDetails -> previewLink(word-ofd) -> flkofd reader/text 按页提取
- 断点续传以文件为单位：已存在于文档树的条目自动跳过，中断后直接重跑；
- --dry-run 只统计并展示待抓取条目，不发起下载。
"""
import json
import random
import re
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.cookiejar import CookieJar

import md_tree

socket.setdefaulttimeout(60)  # 防止僵死连接无限挂起

BASE = "https://flk.npc.gov.cn"
UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://flk.npc.gov.cn/",
    "Accept": "application/json, text/plain, */*",
}
W_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff\u2060"))


def strip_zero_width(s):
    return s.translate(ZERO_WIDTH)

_local = threading.local()


def http_get(url, timeout=30, is_json=True):
    # 带线程本地 cookie jar：网宿 WAF 会通过 302 + wzws_cid cookie 质询
    opener = getattr(_local, "opener", None)
    if opener is None:
        opener = _local.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar()))
    req = urllib.request.Request(url, headers=UA)
    with opener.open(req, timeout=timeout) as r:
        raw = r.read()
    # JS 挑战页: 页面内明文嵌入 /WZWS... 重定向路径，直接请求即可拿到真实响应
    # （仅 flk.npc.gov.cn 主站有 WAF；flkofd/flkoss 是其他服务，不做挑战检测）
    if "://flk.npc.gov.cn" not in url or raw[:1] == b"{":
        return json.loads(raw) if is_json else raw
    m = re.search(rb"'(/WZWS[A-Za-z0-9+/=]+)'", raw) or re.search(rb'"(/WZWS[A-Za-z0-9+/=]+)"', raw)
    if not m:
        raise RuntimeError(f"WAF challenge page without redirect path ({len(raw)}B)")
    origin = urllib.parse.urlsplit(url)
    req2 = urllib.request.Request(f"{origin.scheme}://{origin.netloc}{m.group(1).decode()}", headers=UA)
    with opener.open(req2, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw) if is_json else raw


def retry(fn, times=4, base_delay=3.0):
    last = None
    for i in range(times):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(base_delay * (i + 1) + random.random())
    raise last


# ---------- docx 提取 ----------
def docx_paras(data):
    import io
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    body = root.find("w:body", W_NS)

    def para_text(p):
        parts = []
        for el in p.iter():
            tag = el.tag.split("}")[-1]
            if tag == "t" and el.text:
                parts.append(el.text)
            elif tag == "tab":
                parts.append("\t")
            elif tag == "br":
                parts.append("\n")
        return "".join(parts)

    paras = []
    for child in body:
        tag = child.tag.split("}")[-1]
        if tag == "p":
            t = strip_zero_width(para_text(child)).strip()
            if t:
                paras.append(t)
        elif tag == "tbl":
            for row in child.findall(".//w:tr", W_NS):
                cells = [para_text(tc).strip() for tc in row.findall(".//w:tc", W_NS)]
                if any(cells):
                    paras.append(" | ".join(cells))
    return paras


def fetch_docx_content(bbbs):
    d = retry(lambda: http_get(
        f"{BASE}/law-search/download/pc?format=docx&bbbs={bbbs}&fileId=", timeout=30))
    if d.get("code") != 200 or not (d.get("data") or {}).get("url"):
        raise RuntimeError(f"download/pc: {d.get('msg')}")
    docx = retry(lambda: http_get(d["data"]["url"], timeout=120, is_json=False))
    if not docx.startswith(b"PK"):
        raise RuntimeError("not a docx (PK header missing)")
    paras = docx_paras(docx)
    if not paras:
        raise RuntimeError("docx has no text")
    return "\n\n".join(paras), "docx"


# ---------- OFD reader text 兜底 ----------
def fetch_ofd_content(bbbs):
    det = retry(lambda: http_get(f"{BASE}/law-search/search/flfgDetails?bbbs={bbbs}"))
    if det.get("code") != 200:
        raise RuntimeError(f"flfgDetails: {det.get('msg')}")
    oss = ((det.get("data") or {}).get("ossFile") or {})
    path = oss.get("ossWordOfdPath") or oss.get("ossPdfOfdPath")
    if not path:
        raise RuntimeError("no ofd file")
    pl = retry(lambda: http_get(
        f"{BASE}/law-search/amazonFile/previewLink?filePath=" + urllib.parse.quote(path, safe="")))
    reader_url = (pl.get("data") or {}).get("url")
    if not reader_url:
        raise RuntimeError("previewLink empty")
    inner = urllib.parse.parse_qs(urllib.parse.urlparse(reader_url).query)["file"][0]
    fparam = urllib.parse.quote(inner, safe="")
    pages = []
    for i in range(500):  # 硬上限防死循环
        try:
            d = http_get(f"https://flkofd.npc.gov.cn/reader/text?file={fparam}&_b=3.2.0&_v=1&_i={i}")
        except Exception:
            break
        areas = d.get("areas") if isinstance(d, dict) else None
        if not areas:
            break
        parts = []
        for area in areas:
            lines = area.get("lines") or []
            text = "".join(
                "".join(c.get("char", "") for c in (ln.get("chars") or []))
                for ln in lines
            ).strip()
            if text:
                parts.append(text)
        pages.append("\n\n".join(parts))
        time.sleep(0.05)
    if not pages:
        raise RuntimeError("ofd text empty")
    return "\n\n".join(pages), "ofd"


def fetch_content(bbbs):
    """主路线 docx，失败兜底 OFD。返回 (content, last_error)，成功时 last_error 为 None。"""
    err = None
    for fetcher in (fetch_docx_content, fetch_ofd_content):
        try:
            content, _via = fetcher(bbbs)
            return content, None
        except Exception as e:  # noqa: BLE001
            err = f"{fetcher.__name__}: {e}"
    return "", err


def main():
    dry = "--dry-run" in sys.argv
    rows = json.load(open(md_tree.NEW_LIST, encoding="utf-8"))["rows"]
    have = md_tree.scan_ids()
    todo = [r for r in rows if r["bbbs"] not in have]
    print(f"待抓取: {len(todo)}（文档树已有: {len(have)}）", flush=True)
    if dry:
        for r in todo[:5]:
            print("  -", r.get("title"))
        return
    if not todo:
        return

    lock = threading.Lock()  # 串行化“选文件名 + 写盘”，避免并发写同目录时重名冲突
    counter = {"ok": 0, "fail": 0}
    failed = []

    def work(row):
        content, err = fetch_content(row["bbbs"])
        time.sleep(0.6 + random.random() * 0.6)
        with lock:
            if content:
                law = md_tree.entry_from_row(row, content)
                path = md_tree.law_path(row, law)
                md_tree.write_atomic(path, md_tree.render(law))
                counter["ok"] += 1
            else:
                counter["fail"] += 1
                failed.append((row.get("title") or row["bbbs"], err))
            n = counter["ok"] + counter["fail"]
            if n % 100 == 0:
                print(f"进度 {n}/{len(todo)} ok={counter['ok']} fail={counter['fail']}", flush=True)

    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = [ex.submit(work, r) for r in todo]
        for f in as_completed(futs):
            f.result()

    print(f"完成: ok={counter['ok']} fail={counter['fail']}", flush=True)
    if failed:
        print(f"失败 {len(failed)} 条（重跑本脚本会自动重试）:", flush=True)
        for title, err in failed[:10]:
            print(f"  - {title} | {err}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
