#!/usr/bin/env python3
"""监督 fetch_new_laws.py：超过 STALL_KILL 秒无进展则杀掉重启。

用法:
    python3 supervise_crawl.py [target]

爬虫把抓取成果直接写成 markdown/ 文件，进度即文档树中已存在的待抓取条目数。
target 为可选的目标条数；缺省时自动取当前待抓取条数
（new_list.json 中不在文档树里的条数，启动时计算一次）。
连续 MAX_BARREN 轮重启都没有任何新进展则放弃，避免对永久性失败无限循环。
"""
import json
import os
import signal
import subprocess
import sys
import time

import md_tree

CRAWLER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fetch_new_laws.py")
STALL_KILL = 600  # 10 分钟无新的成功条目则强制重启
MAX_BARREN = 3    # 连续 N 轮重启无进展则放弃


def pending_bbbs():
    rows = json.load(open(md_tree.NEW_LIST, encoding="utf-8"))["rows"]
    have = md_tree.scan_ids()
    return {r["bbbs"] for r in rows if r["bbbs"] not in have}


def progress(todo):
    have = md_tree.scan_ids()
    return len(set(have) & todo)


def main():
    todo = pending_bbbs()
    target = int(sys.argv[1]) if len(sys.argv) > 1 else len(todo)
    done = progress(todo)
    print(f"[supervisor] 待抓取 {len(todo)} 条，目标 {target}，当前已完成 {done}", flush=True)
    barren = 0
    while True:
        if done >= target:
            print(f"[supervisor] 已达目标 {done}/{target}，监督结束", flush=True)
            return
        if barren >= MAX_BARREN:
            print(f"[supervisor] 连续 {MAX_BARREN} 轮无任何新进展，停止监督（差 {target - done} 条）", flush=True)
            sys.exit(1)
        start_done = done
        print(f"[supervisor] 启动爬虫（当前 {done}/{target}）", flush=True)
        p = subprocess.Popen([sys.executable, CRAWLER])
        last, last_t = done, time.time()
        while p.poll() is None:
            time.sleep(30)
            done = progress(todo)
            if done > last:
                last, last_t = done, time.time()
            elif time.time() - last_t > STALL_KILL:
                print(f"[supervisor] {STALL_KILL}s 无进展（{last}），强杀重启", flush=True)
                p.send_signal(signal.SIGKILL)
                p.wait()
                time.sleep(30)  # 冷却
                break
        else:
            # 爬虫自行退出（全部完成或收场于失败条目）：检查是否达标，否则继续
            done = progress(todo)
            if done >= target:
                print(f"[supervisor] 完成 {done}/{target}", flush=True)
                return
            print(f"[supervisor] 爬虫退出（{done}/{target}）", flush=True)
            time.sleep(3)
        done = progress(todo)
        barren = 0 if done > start_done else barren + 1


if __name__ == "__main__":
    main()
