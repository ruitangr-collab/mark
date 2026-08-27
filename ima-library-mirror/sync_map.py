#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ima-library-mirror 幂等映射管理（纯本地，无网络）。

管理 ima_library_map.json：记录 IMA media_id -> 资料库 node_id 的映射，
保证镜像重跑只补新增、不重复建文档。

用法：
  python3 sync_map.py status
  python3 sync_map.py lookup <media_id>
  python3 sync_map.py record <media_id> <node_id> <title>
  python3 sync_map.py prune <media_id>          # 删除一条（极少用）
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

MAP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ima_library_map.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load() -> dict:
    if not os.path.exists(MAP_PATH):
        return {"kb_id": "", "kb_name": "", "space_id": "", "last_run": "", "items": {}}
    try:
        with open(MAP_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("items", {})
        return data
    except (json.JSONDecodeError, OSError):
        return {"kb_id": "", "kb_name": "", "space_id": "", "last_run": "", "items": {}}


def save(data: dict) -> None:
    data["last_run"] = _now()
    with open(MAP_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def cmd_status(data: dict) -> int:
    items = data.get("items", {})
    print(f"kb_id   : {data.get('kb_id') or '(未设置)'}")
    print(f"kb_name : {data.get('kb_name') or '(未设置)'}")
    print(f"space_id: {data.get('space_id') or '(我的文档/默认)'}")
    print(f"已同步  : {len(items)} 篇")
    if items:
        print("--- 最近 10 条 ---")
        for i, (mid, v) in enumerate(list(items.items())[-10:]):
            print(f"  {mid} -> {v.get('node_id')}  ({v.get('title','')[:30]})")
    return 0


def cmd_lookup(data: dict, media_id: str) -> int:
    it = data.get("items", {}).get(media_id)
    if it:
        print(f"SYNCED  {media_id} -> {it.get('node_id')}  ({it.get('title','')})")
        return 0
    print(f"UNSYNCED  {media_id}")
    return 1


def cmd_record(data: dict, media_id: str, node_id: str, title: str) -> int:
    data.setdefault("items", {})[media_id] = {
        "node_id": node_id,
        "title": title,
        "synced_at": _now(),
    }
    save(data)
    print(f"RECORDED  {media_id} -> {node_id}")
    return 0


def cmd_prune(data: dict, media_id: str) -> int:
    if media_id in data.get("items", {}):
        del data["items"][media_id]
        save(data)
        print(f"PRUNED  {media_id}")
        return 0
    print(f"NOT FOUND  {media_id}")
    return 1


def main() -> int:
    p = argparse.ArgumentParser(description="IMA->资料库 镜像幂等映射管理")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status")
    sp_lookup = sub.add_parser("lookup"); sp_lookup.add_argument("media_id")
    sp_rec = sub.add_parser("record")
    sp_rec.add_argument("media_id"); sp_rec.add_argument("node_id"); sp_rec.add_argument("title")
    sp_prune = sub.add_parser("prune"); sp_prune.add_argument("media_id")

    args = p.parse_args()
    data = load()
    if args.cmd == "status":
        return cmd_status(data)
    if args.cmd == "lookup":
        return cmd_lookup(data, args.media_id)
    if args.cmd == "record":
        return cmd_record(data, args.media_id, args.node_id, args.title)
    if args.cmd == "prune":
        return cmd_prune(data, args.media_id)
    return 2


if __name__ == "__main__":
    sys.exit(main())
