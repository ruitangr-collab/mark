#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wechat-article-harvester 本地侧管理工具（纯 stdlib，无需第三方包）。

职责：
  - 维护 urls.txt（待导入 URL 清单，去重）
  - 分批输出待导入 URL（每批 ≤10，供二货调 import_urls）
  - 维护 harvest_map.json（url -> media_id 映射，幂等依据）
  - 统计进度

import_urls 的实际调用由二货在对话中用 mcp__ima-mcp__import_urls 执行，
本脚本只管本地清单与映射，不发起网络请求。
"""
import json
import os
import sys
import argparse

BASE = os.path.dirname(os.path.abspath(__file__))
URLS = os.path.join(BASE, "urls.txt")
MAP = os.path.join(BASE, "harvest_map.json")
BATCH = 10
DEFAULT_KB = "7498636917212532"   # map data 知识库
DEFAULT_KB_NAME = "map data"


def load_map():
    if os.path.exists(MAP):
        try:
            return json.load(open(MAP, encoding="utf-8"))
        except Exception:
            pass
    return {"kb_id": DEFAULT_KB, "kb_name": DEFAULT_KB_NAME, "imported": {}, "last_run": ""}


def save_map(d):
    json.dump(d, open(MAP, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def load_urls():
    if not os.path.exists(URLS):
        return []
    out = []
    for line in open(URLS, encoding="utf-8"):
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


def cmd_add(urls):
    seen = set(load_urls())
    added = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            added.append(u)
    with open(URLS, "a", encoding="utf-8") as f:
        for u in added:
            f.write(u + "\n")
    print(f"新增 {len(added)} 条；已存在跳过 {len(urls) - len(added)} 条；当前共 {len(load_urls())} 条")


def cmd_batch():
    d = load_map()
    imported = set(d.get("imported", {}).keys())
    pend = [u for u in load_urls() if u not in imported]
    if not pend:
        print("# 无待导入 URL")
        return
    for i in range(0, len(pend), BATCH):
        chunk = pend[i:i + BATCH]
        print(f"# === BATCH {i // BATCH + 1} (共 {len(chunk)} 条) ===")
        for u in chunk:
            print(u)
    print(f"# 待导入合计 {len(pend)} 条，分 { (len(pend) + BATCH - 1) // BATCH } 批")


def cmd_record(url, media_id):
    d = load_map()
    d.setdefault("imported", {})[url] = {"media_id": media_id, "at": ""}
    save_map(d)
    print(f"recorded: {url} -> {media_id}")


def cmd_status():
    urls = load_urls()
    d = load_map()
    imp = len(d.get("imported", {}))
    pend = len(urls) - imp
    print(f"URL清单: {len(urls)} 条 | 已导入: {imp} 条 | 待导入: {pend} 条")
    print(f"目标知识库: {d.get('kb_name')} ({d.get('kb_id')})")


def main():
    ap = argparse.ArgumentParser(description="wechat-article-harvester 本地清单/映射管理")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("init")
    pa = sub.add_parser("add")
    pa.add_argument("urls", nargs="*", help="文章 URL 列表")
    sub.add_parser("batch")
    pr = sub.add_parser("record")
    pr.add_argument("url")
    pr.add_argument("media_id")
    sub.add_parser("status")
    args = ap.parse_args()

    if args.cmd == "add":
        if not args.urls:
            print("请至少给一个 URL")
            sys.exit(1)
        cmd_add(args.urls)
    elif args.cmd == "batch":
        cmd_batch()
    elif args.cmd == "record":
        cmd_record(args.url, args.media_id)
    elif args.cmd == "status":
        cmd_status()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
