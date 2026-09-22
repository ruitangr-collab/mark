#!/usr/bin/env python3
"""Generate a comment interaction analysis Excel from comment_cache.json + video data."""

import json, sys, re
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, numbers
from openpyxl.utils import get_column_letter

WORK_DIR = Path(r"C:/Users/53185/.workbuddy/skills/douyin-report-search")
RAW_FILE = WORK_DIR / "douyin_raw_data.json"
COMMENT_CACHE = WORK_DIR / "comment_cache.json"
OUT = WORK_DIR / "抖音非洲评论互动分析.xlsx"


def log(msg):
    sys.stdout.buffer.write(f"{msg}\n".encode("utf-8"))
    sys.stdout.buffer.flush()


def clean_text(s):
    if not s: return ""
    s = re.sub(r"<[^>]+>", "", s)
    return s.replace("\n", " ").replace("\r", " ").strip()


def format_count(n):
    if n >= 1e8: return f"{n/1e8:.1f}亿"
    if n >= 1e4: return f"{n/1e4:.1f}万"
    return str(n)


def main():
    log("加载数据...")

    # 加载评论缓存
    comments = {}
    if COMMENT_CACHE.exists():
        comments = json.loads(COMMENT_CACHE.read_text(encoding="utf-8"))

    total_cmts = sum(len(v) for v in comments.values())
    videos_with = sum(1 for v in comments.values() if v)
    log(f"评论缓存: {videos_with} 视频, {total_cmts} 条评论")

    # 加载视频数据（建立 aweme_id → 视频信息 映射）
    d = json.loads(RAW_FILE.read_text(encoding="utf-8"))
    vid_map = {}
    for v in d.get("videos", []):
        raw = v.get("_raw", {})
        aid = raw.get("aweme_id", v.get("aweme_id", ""))
        if not aid: continue
        author = raw.get("author", {})
        stats = raw.get("statistics", {})
        vid_map[aid] = {
            "nickname": author.get("nickname", ""),
            "desc": clean_text(raw.get("desc", ""))[:80],
            "video_url": f"https://www.douyin.com/video/{aid}",
            "author_url": f"https://www.douyin.com/user/{author.get('sec_uid','')}",
            "comment_count": stats.get("comment_count", 0),
            "digg_count": stats.get("digg_count", 0),
            "share_count": stats.get("share_count", 0),
        }

    # ========== 构建 Excel ==========
    wb = Workbook()

    hdr_fill = PatternFill("solid", fgColor="2E75B6")
    hdr_font = Font(bold=True, color="FFFFFF", size=11)
    hdr_fill2 = PatternFill("solid", fgColor="548235")
    hdr_fill3 = PatternFill("solid", fgColor="BF8F00")

    def style_header(ws, fill):
        for cell in ws[1]:
            cell.fill = fill
            cell.font = hdr_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # ── Sheet 1: 视频评论互动总览 ──
    ws1 = wb.active
    ws1.title = "视频评论总览"
    h1 = ["视频链接", "作者", "视频描述", "评论数", "点赞数", "分享数", "抓取评论数", "评论互动比", "热评预览"]
    ws1.append(h1)
    style_header(ws1, hdr_fill)

    for aid, cmts in sorted(comments.items(), key=lambda x: -len(x[1])):
        vi = vid_map.get(aid, {})
        cmt_total = vi.get("comment_count", 0)
        digg = vi.get("digg_count", 0)
        ratio = round(len(cmts) / max(cmt_total, 1) * 100, 1)

        # 热评预览：取点赞最高的一条
        top = max(cmts, key=lambda c: c.get("digg_count", 0)) if cmts else {}
        preview = f"[{top.get('nickname','')}] {top.get('text','')[:60]} ({top.get('digg_count',0)}赞)" if top else ""

        ws1.append([
            vi.get("video_url", ""),
            vi.get("nickname", ""),
            vi.get("desc", ""),
            cmt_total,
            digg,
            vi.get("share_count", 0),
            len(cmts),
            f"{ratio}%",
            preview,
        ])

    for row in ws1.iter_rows(min_row=2, max_row=ws1.max_row):
        for i, cell in enumerate(row, 1):
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            if i in [4,5,6,7]:
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.number_format = '#,##0'
    widths1 = [50, 18, 50, 12, 12, 10, 14, 12, 55]
    for i, w in enumerate(widths1, 1):
        ws1.column_dimensions[get_column_letter(i)].width = w
    ws1.row_dimensions[1].height = 30
    ws1.freeze_panes = "A2"
    ws1.auto_filter.ref = ws1.dimensions

    # ── Sheet 2: 评论明细（每条评论一行）──
    ws2 = wb.create_sheet("评论明细")
    h2 = ["视频作者", "评论者", "评论内容", "点赞数", "回复数", "视频链接"]
    ws2.append(h2)
    style_header(ws2, hdr_fill2)

    row_num = 0
    for aid, cmts in sorted(comments.items(), key=lambda x: -len(x[1])):
        vi = vid_map.get(aid, {})
        author_name = vi.get("nickname", "")
        video_url = vi.get("video_url", "")
        for c in cmts:
            ws2.append([
                author_name,
                c.get("nickname", ""),
                c.get("text", ""),
                c.get("digg_count", 0),
                c.get("reply_count", 0),
                video_url,
            ])
            row_num += 1

    for row in ws2.iter_rows(min_row=2, max_row=ws2.max_row):
        for i, cell in enumerate(row, 1):
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            if i in [4,5]:
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.number_format = '#,##0'
    widths2 = [20, 18, 60, 10, 10, 50]
    for i, w in enumerate(widths2, 1):
        ws2.column_dimensions[get_column_letter(i)].width = w
    ws2.row_dimensions[1].height = 30
    ws2.freeze_panes = "A2"
    ws2.auto_filter.ref = ws2.dimensions

    # ── Sheet 3: 高互动评论 TOP 50 ──
    ws3 = wb.create_sheet("高赞评论TOP50")
    h3 = ["排名", "评论者", "评论内容", "点赞数", "回复数", "视频作者", "视频链接"]
    ws3.append(h3)
    style_header(ws3, hdr_fill3)

    # 所有评论按点赞排序
    all_cmts = []
    for aid, cmts in comments.items():
        vi = vid_map.get(aid, {})
        for c in cmts:
            all_cmts.append({**c, "author": vi.get("nickname", ""), "video_url": vi.get("video_url", "")})

    all_cmts.sort(key=lambda c: -c.get("digg_count", 0))
    top50 = all_cmts[:50]

    for rank, c in enumerate(top50, 1):
        ws3.append([
            rank,
            c.get("nickname", ""),
            c.get("text", ""),
            c.get("digg_count", 0),
            c.get("reply_count", 0),
            c.get("author", ""),
            c.get("video_url", ""),
        ])

    for row in ws3.iter_rows(min_row=2, max_row=ws3.max_row):
        for i, cell in enumerate(row, 1):
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            if i in [1,4,5]:
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.number_format = '#,##0'
    widths3 = [8, 18, 60, 12, 10, 20, 50]
    for i, w in enumerate(widths3, 1):
        ws3.column_dimensions[get_column_letter(i)].width = w
    ws3.row_dimensions[1].height = 30
    ws3.freeze_panes = "A2"

    # ── Sheet 4: 评论者活跃度 ──
    ws4 = wb.create_sheet("活跃评论者")
    commenter_stats = {}
    for aid, cmts in comments.items():
        for c in cmts:
            nick = c.get("nickname", "")
            if nick not in commenter_stats:
                commenter_stats[nick] = {"count": 0, "total_digg": 0, "videos": set()}
            commenter_stats[nick]["count"] += 1
            commenter_stats[nick]["total_digg"] += c.get("digg_count", 0)
            commenter_stats[nick]["videos"].add(aid)

    h4 = ["评论者", "评论次数", "总获赞", "涉及视频数", "最近评论示例"]
    ws4.append(h4)
    style_header(ws4, hdr_fill)

    sorted_commenters = sorted(commenter_stats.items(), key=lambda x: -x[1]["count"])[:50]
    for nick, stats in sorted_commenters:
        # 找一条示例
        sample = ""
        for aid in stats["videos"]:
            for c in comments.get(aid, []):
                if c.get("nickname") == nick:
                    sample = c.get("text", "")[:60]
                    break
            if sample: break

        ws4.append([
            nick,
            stats["count"],
            stats["total_digg"],
            len(stats["videos"]),
            sample,
        ])

    for row in ws4.iter_rows(min_row=2, max_row=ws4.max_row):
        for i, cell in enumerate(row, 1):
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            if i in [2,3,4]:
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.number_format = '#,##0'
    widths4 = [20, 12, 12, 12, 55]
    for i, w in enumerate(widths4, 1):
        ws4.column_dimensions[get_column_letter(i)].width = w
    ws4.row_dimensions[1].height = 30
    ws4.freeze_panes = "A2"

    # 保存
    wb.save(str(OUT))
    log(f"\n{'='*50}")
    log(f"报告已生成: {OUT}")
    log(f"  Sheet1 视频评论总览: {videos_with} 条视频")
    log(f"  Sheet2 评论明细: {total_cmts} 条评论")
    log(f"  Sheet3 高赞评论TOP50")
    log(f"  Sheet4 活跃评论者: {len(sorted_commenters)} 人")
    log(f"\n=== 互动概况 ===")

    # 统计摘要
    total_digg = sum(c.get("digg_count", 0) for cmts in comments.values() for c in cmts)
    avg_digg = total_digg // max(total_cmts, 1)
    top_comment = all_cmts[0] if all_cmts else {}
    log(f"  总评论抓取: {total_cmts} 条")
    log(f"  评论总点赞: {total_digg:,}")
    log(f"  平均点赞/评论: {avg_digg}")
    log(f"  最高赞评论: [{top_comment.get('nickname','')}] {top_comment.get('text','')[:50]} ({top_comment.get('digg_count',0)}赞)")

    # 每个视频的互动概况
    log(f"\n=== 各视频评论互动概况 ===")
    for aid, cmts in sorted(comments.items(), key=lambda x: -len(x[1])):
        vi = vid_map.get(aid, {})
        if not cmts: continue
        total_d = sum(c.get("digg_count", 0) for c in cmts)
        top = max(cmts, key=lambda c: c.get("digg_count", 0))
        log(f"  [{vi.get('nickname','?')}] {vi.get('desc','')[:30]}... → {vi.get('comment_count',0)}评 | "
            f"抓取{len(cmts)}条 | 评论总赞{total_d} | 最高赞 [{top.get('nickname','')}] {top.get('text','')[:40]} ({top.get('digg_count',0)}赞)")


if __name__ == "__main__":
    main()
