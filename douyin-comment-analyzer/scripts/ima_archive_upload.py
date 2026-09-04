#!/usr/bin/env python3
"""生成 IMA 归档待上传清单。

⚠️ 本脚本【不会上传任何东西】。IMA 归档必须走 MCP 通道：
   mcp__ima-mcp__create_media → COS 上传 → mcp__ima-mcp__add_knowledge
本脚本只负责列出「该传哪些文件」，供 agent 在连接器可用时按清单逐个处理；
连接器不可用时，清单落盘为 _archive/IMA_UPLOAD_QUEUE.md，标记未执行原因，便于后续补跑。

用法: python3 ima_archive_upload.py [--kb 7500455210911978]
"""
import argparse
import sys
from datetime import date
from pathlib import Path

ARCHIVE_DIR = Path.home() / ".workbuddy/douyin_analysis/_archive"
DISCOVERY_DIR = Path.home() / ".workbuddy/douyin_analysis/_discovery"

# (标题, 相对根的路径, 更新方式)
TARGETS = [
    ("【核验】非洲中资园区_公开资料去重主清单.md",
     DISCOVERY_DIR / "projects_verified.md", "每次覆盖新版本"),
    (None,  # 文件名含当天日期
     ARCHIVE_DIR / f"【核验】非洲中资园区_公开资料去重主清单_{date.today().isoformat()}.md",
     "日期版本化"),
    (None,
     ARCHIVE_DIR / f"【汇报】非洲园区官方号_中国企业入驻需求信号_{date.today().isoformat()}.md",
     "日期版本化"),
    ("africa_parks_reference.json", ARCHIVE_DIR / "africa_parks_reference.json", "有更新时"),
    ("parks_watchlist.json", ARCHIVE_DIR / "parks_watchlist.json", "有更新时"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kb", default="7500455210911978", help="目标知识库 ID")
    args = ap.parse_args()

    rows = [(t or p.name, p, how) for t, p, how in TARGETS]
    exist = [(t, p, how) for t, p, how in rows if p.exists()]
    missing = [(t, p, how) for t, p, how in rows if not p.exists()]

    print(f"待上传 {len(exist)} 个文件到知识库 {args.kb}：\n")
    for t, p, how in exist:
        print(f"  - {t}  ({p.stat().st_size} B)  [{how}]")
    if missing:
        print("\n以下文件不存在，跳过：")
        for t, p, _ in missing:
            print(f"  x {t}  ({p})")

    out = ARCHIVE_DIR / "IMA_UPLOAD_QUEUE.md"
    lines = [
        "# IMA 归档待上传清单（ima-mcp 连接器可用时按本清单补跑）",
        "",
        f"> 目标知识库：「媒体账号监控」knowledge_base_id = `{args.kb}`",
        "> 流程：create_media → COS 上传（Bucket: ima-share-kb-1258344701, Region: ap-shanghai）→ add_knowledge",
        "> 注意：IMA 无删除/覆盖接口，旧版本会保留，以最新日期为准。",
        "",
        f"## 待上传（{date.today().isoformat()}）",
        "",
        "| # | 文件 | 绝对路径 | 更新方式 |",
        "|---|---|---|---|",
    ]
    for i, (t, p, how) in enumerate(exist, 1):
        lines.append(f"| {i} | {t} | `{p}` | {how} |")
    lines += [
        "",
        "## 本脚本不做的事",
        "",
        "本清单由 `scripts/ima_archive_upload.py` 生成，它**不执行上传**。",
        "实际上传需 agent 调用 MCP 工具；若连接器未加载，会打印本清单并标记未执行。",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n清单已写入: {out}")
    print("⚠️ 未执行上传——IMA 上传必须走 MCP 通道，连接器不可用时请稍后补跑。")
    return 0


if __name__ == '__main__':
    sys.exit(main())
