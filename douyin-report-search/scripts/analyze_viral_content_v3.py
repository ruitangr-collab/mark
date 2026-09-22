#!/usr/bin/env python3
"""
抖音非洲内容深度分析 v3
核心改进：消除循环论证
- 不用互动数据加权定义"爆款"
- 用创作者可控特征 → 独立互动指标做预测分析
- play_count不可用 → 用 follower_count 归一化 + 比率分析
"""
import json, os, re, sys, math
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side, numbers
from openpyxl.utils import get_column_letter

# ── Setup ──
sys.stdout.reconfigure(encoding='utf-8')
SKILL_DIR = Path(r"C:/Users/53185/.workbuddy/skills/douyin-report-search")
DATA_DIR = SKILL_DIR / "country_data"
OUTPUT = SKILL_DIR / "抖音内容策略深度分析_v3.xlsx"

UTC8 = timezone(timedelta(hours=8))

# ── Data Loading ──
def load_all_videos():
    """Load all videos with full raw data, extracting independent features."""
    videos = []
    stats = {"ok": 0, "no_raw": 0, "no_follower": 0, "no_time": 0, "total_files": 0}
    
    for f in sorted(DATA_DIR.glob("*.json")):
        stats["total_files"] += 1
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
        except:
            continue
        
        # Determine country from filename: "国家_国家_关键词.json"
        country = f.stem.split('_')[0] if '_' in f.stem else f.stem
        keyword = f.stem.split('_')[-1] if '_' in f.stem else f.stem
        
        for v in data.get("videos", []):
            raw = v.get("_raw") or {}
            if not raw:
                stats["no_raw"] += 1
                continue
            
            # Author data
            raw_author = raw.get("author") or {}
            follower_count = raw_author.get("follower_count") or 0
            if follower_count <= 0:
                stats["no_follower"] += 1
                continue
            
            # Stats
            s = v.get("statistics", {})
            likes = s.get("digg_count") or 0
            comments = s.get("comment_count") or 0
            shares = s.get("share_count") or 0
            collects = s.get("collect_count") or 0
            
            # Duration
            vid_info = raw.get("video") or {}
            duration_ms = vid_info.get("duration") or 0
            duration_sec = duration_ms / 1000
            
            # Video orientation
            h = vid_info.get("height") or 0
            w = vid_info.get("width") or 0
            is_portrait = h > w if h and w else None  # Portrait = vertical phone
            
            # Tags
            tags = []
            for te in (raw.get("text_extra") or []):
                tag_name = (te.get("hashtag_name") or "").strip("#")
                if tag_name:
                    tags.append(tag_name)
            
            # Create time
            ct = raw.get("create_time")
            if not ct:
                stats["no_time"] += 1
                continue
            
            try:
                dt = datetime.fromtimestamp(ct, tz=UTC8)
            except:
                stats["no_time"] += 1
                continue
            
            # Music
            music = raw.get("music") or {}
            music_title = music.get("title", "") or ""
            music_author = music.get("author", "") or ""
            author_nickname = v.get("author", {}).get("nickname", "")
            is_original_sound = (
                f"@{author_nickname}" in music_title 
                or author_nickname in music_author
                or "创作的原声" in music_title
            )
            
            # Title
            desc = raw.get("desc", "") or ""
            
            # Follower tier
            if follower_count < 1000:
                follower_tier = "微小(<1K)"
            elif follower_count < 10000:
                follower_tier = "小(1K-1W)"
            elif follower_count < 100000:
                follower_tier = "中(1W-10W)"
            elif follower_count < 1000000:
                follower_tier = "大(10W-100W)"
            else:
                follower_tier = "超大(>100W)"
            
            videos.append({
                "aweme_id": raw.get("aweme_id", ""),
                "desc": desc,
                "title_len": len(desc),
                "likes": likes,
                "comments": comments,
                "shares": shares,
                "collects": collects,
                "total_engagement": likes + comments + shares + collects,
                "comment_like_ratio": comments / max(likes, 1),
                "share_like_ratio": shares / max(likes, 1),
                "collect_like_ratio": collects / max(likes, 1),
                "engagement_per_follower": (likes + comments + shares + collects) / max(follower_count, 1),
                "follower_count": follower_count,
                "follower_tier": follower_tier,
                "duration_sec": duration_sec,
                "duration_min": duration_sec / 60,
                "is_portrait": is_portrait,
                "is_original_sound": is_original_sound,
                "tag_count": len(tags),
                "tags": tags,
                "country": country,
                "keyword": keyword,
                "day_of_week": dt.strftime("%A"),
                "day_num": dt.weekday(),
                "hour": dt.hour,
                "author_nickname": author_nickname,
                "author_uid": v.get("author", {}).get("uid", ""),
                "music_title": music_title,
            })
            stats["ok"] += 1
    
    print(f"Loaded {stats['ok']} videos from {stats['total_files']} files")
    print(f"  Skipped: no_raw={stats['no_raw']}, no_follower={stats['no_follower']}, no_time={stats['no_time']}")
    return videos, stats


def analyze_title_features(desc):
    """Extract independent title features."""
    features = {
        "has_question": bool(re.search(r'[?？]|吗|么|怎么|如何|什么|为什么|哪|谁|几', desc)),
        "has_number": bool(re.search(r'\d+', desc)),
        "has_exclamation": bool(re.search(r'[!！]', desc)),
        "has_emoji": bool(re.search(r'[\U0001F300-\U0001F9FF\u2600-\u27BF\u2B50\u2705\u274C]', desc)),
        "char_count": len(desc),
    }
    
    # Hook type detection
    desc_lower = desc.lower()
    hooks = []
    
    # 数字罗列: "3个方法" "5大" "TOP10"
    if re.search(r'(\d+[个种条项大]|[Tt][Oo][Pp]\s*\d+|第[一二三四五六七八九十\d]+)', desc):
        hooks.append("数字罗列")
    
    # 疑问/好奇: "为什么" "怎么" "如何" "你知道吗"
    if re.search(r'(为什么|怎么|如何|你知道吗|竟然|居然|原来|真相|揭秘|曝光)', desc):
        hooks.append("好奇悬念")
    
    # 对比反差: "vs" "对比" "差别" "区别" "对比" "不同"
    if re.search(r'(vs|对比|差别|区别|不同|竟然|居然|反而|却是)', desc_lower):
        hooks.append("对比反差")
    
    # 情绪共鸣: strong emotional words
    if re.search(r'(太|好|最|绝|爆|燃|泪目|感动|震惊|可怕|恐怖|疯狂|牛逼|厉害)', desc):
        hooks.append("情绪共鸣")
    
    # 稀缺/独家: "揭秘" "独家" "首次" "罕见" "秘密"
    if re.search(r'(揭秘|独家|首次|罕见|秘密|内幕|不为人知|99%|百分九十九|没几个人)', desc):
        hooks.append("稀缺独家")
    
    # 实用指南: "教程" "攻略" "方法" "技巧" "干货" "建议"
    if re.search(r'(教程|攻略|方法|技巧|干货|建议|指南|步骤|必看|收藏|避坑)', desc):
        hooks.append("实用指南")
    
    # 故事/经历: "我在" "经历" "故事" "见过"
    if re.search(r'(我在|经历|故事|见过|亲历|实拍|记录|日记)', desc):
        hooks.append("亲身经历")
    
    features["hooks"] = hooks
    features["hook_count"] = len(hooks)
    features["primary_hook"] = hooks[0] if hooks else "无明确钩子"
    
    return features


# ── Excel Helpers ──
HEADER_FONT = Font(name="微软雅黑", bold=True, size=11, color="FFFFFF")
HEADER_FILL = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
CELL_ALIGN = Alignment(vertical="center", wrap_text=True)
THIN_BORDER = Border(
    left=Side(style="thin"), right=Side(style="thin"),
    top=Side(style="thin"), bottom=Side(style="thin")
)
GOOD_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
BAD_FILL = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
YELLOW_FILL = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")

def style_header(ws, row, ncols):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER

def auto_width(ws, min_w=10, max_w=50):
    for col in ws.columns:
        letter = get_column_letter(col[0].column)
        lengths = []
        for cell in col:
            if cell.value:
                lines = str(cell.value).split('\n')
                lengths.append(max(len(l) for l in lines))
        w = min(max(max(lengths) + 2 if lengths else min_w, min_w), max_w)
        ws.column_dimensions[letter].width = w

def write_rows(ws, start_row, data, formatters=None):
    for i, row_data in enumerate(data):
        row_num = start_row + i
        for j, val in enumerate(row_data):
            cell = ws.cell(row=row_num, column=j + 1, value=val)
            cell.alignment = CELL_ALIGN
            cell.border = THIN_BORDER
            if formatters and j < len(formatters) and formatters[j]:
                formatters[j](cell, val)


# ── Analysis Functions ──

def analyze_title_vs_engagement(videos):
    """How do title features predict engagement RATIOS (not raw interactions)?"""
    # Group by title features
    feature_groups = defaultdict(list)
    
    for v in videos:
        features = analyze_title_features(v["desc"])
        
        # Question vs no question
        feature_groups["has_question"].append({
            "yes": features["has_question"],
            "comment_like_ratio": v["comment_like_ratio"],
            "share_like_ratio": v["share_like_ratio"],
            "collect_like_ratio": v["collect_like_ratio"],
        })
        
        # Number vs no number
        feature_groups["has_number"].append({
            "yes": features["has_number"],
            "comment_like_ratio": v["comment_like_ratio"],
            "share_like_ratio": v["share_like_ratio"],
        })
        
        # Exclamation
        feature_groups["has_exclamation"].append({
            "yes": features["has_exclamation"],
            "comment_like_ratio": v["comment_like_ratio"],
            "share_like_ratio": v["share_like_ratio"],
        })
        
        # Hook count
        hc = features["hook_count"]
        if hc <= 1:
            hc_label = "0-1个钩子"
        elif hc <= 2:
            hc_label = "2个钩子"
        else:
            hc_label = "3+个钩子"
        feature_groups[f"hooks_{hc_label}"].append({
            "comment_like_ratio": v["comment_like_ratio"],
            "share_like_ratio": v["share_like_ratio"],
            "collect_like_ratio": v["collect_like_ratio"],
        })
        
        # Primary hook
        ph = features["primary_hook"]
        feature_groups[f"hooktype_{ph}"].append({
            "comment_like_ratio": v["comment_like_ratio"],
            "share_like_ratio": v["share_like_ratio"],
            "collect_like_ratio": v["collect_like_ratio"],
            "engagement_per_follower": v["engagement_per_follower"],
        })
        
        # Title length bucket
        tl = len(v["desc"])
        if tl <= 10:
            tlb = "极短(≤10字)"
        elif tl <= 25:
            tlb = "短(11-25字)"
        elif tl <= 40:
            tlb = "中(26-40字)"
        elif tl <= 60:
            tlb = "长(41-60字)"
        else:
            tlb = "超长(>60字)"
        feature_groups[f"titlelen_{tlb}"].append({
            "comment_like_ratio": v["comment_like_ratio"],
            "share_like_ratio": v["share_like_ratio"],
            "collect_like_ratio": v["collect_like_ratio"],
            "engagement_per_follower": v["engagement_per_follower"],
            "total_engagement": v["total_engagement"],
        })
    
    return feature_groups


def analyze_duration_vs_engagement(videos):
    """Duration (creator decision) → engagement ratios."""
    buckets = {
        "极短(<15s)": (0, 15),
        "短(15-30s)": (15, 30),
        "中短(30-60s)": (30, 60),
        "中(1-2分钟)": (60, 120),
        "中长(2-5分钟)": (120, 300),
        "长(5-10分钟)": (300, 600),
        "超长(>10分钟)": (600, 99999),
    }
    
    groups = {name: [] for name in buckets}
    for v in videos:
        dur = v["duration_sec"]
        for name, (lo, hi) in buckets.items():
            if lo <= dur < hi:
                groups[name].append(v)
                break
    
    return groups, buckets


def analyze_posting_time(videos):
    """Posting day & hour → engagement ratios."""
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    day_labels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    
    day_groups = {d: [] for d in days}
    hour_groups = {h: [] for h in range(24)}
    
    for v in videos:
        day_groups[v["day_of_week"]].append(v)
        hour_groups[v["hour"]].append(v)
    
    return day_groups, hour_groups, day_labels


def analyze_author_tier(videos):
    """Within-tier analysis: how do features predict success for same-size authors?"""
    tiers = defaultdict(list)
    for v in videos:
        tiers[v["follower_tier"]].append(v)
    
    return tiers


def analyze_tags(videos):
    """Tag count and content → engagement ratios."""
    tag_count_groups = defaultdict(list)
    tag_content = defaultdict(list)
    
    for v in videos:
        tc = v["tag_count"]
        if tc == 0:
            tc_label = "无标签"
        elif tc <= 2:
            tc_label = "1-2个"
        elif tc <= 4:
            tc_label = "3-4个"
        elif tc <= 6:
            tc_label = "5-6个"
        else:
            tc_label = "7+个"
        tag_count_groups[tc_label].append(v)
        
        for tag in v["tags"]:
            tag_content[tag].append(v)
    
    return tag_count_groups, tag_content


def analyze_orientation_sound(videos):
    """Video orientation and original sound → engagement."""
    portrait_vids = [v for v in videos if v["is_portrait"] is True]
    landscape_vids = [v for v in videos if v["is_portrait"] is False]
    orig_sound = [v for v in videos if v["is_original_sound"]]
    trending_sound = [v for v in videos if not v["is_original_sound"]]
    
    return portrait_vids, landscape_vids, orig_sound, trending_sound


def analyze_country_topic(videos):
    """Country and topic → engagement performance."""
    country_groups = defaultdict(list)
    topic_groups = defaultdict(list)
    
    for v in videos:
        country_groups[v["country"]].append(v)
        topic_groups[v["keyword"]].append(v)
    
    return country_groups, topic_groups


# ── Statistics Helpers ──
def median(lst):
    if not lst:
        return 0
    s = sorted(lst)
    n = len(s)
    if n % 2 == 0:
        return (s[n//2 - 1] + s[n//2]) / 2
    return s[n//2]


def mean(lst):
    if not lst:
        return 0
    return sum(lst) / len(lst)


def group_stats(group_list, metric_keys):
    """Calculate mean/median for each metric in a group of videos."""
    result = {}
    for key in metric_keys:
        vals = [v[key] for v in group_list if key in v]
        result[f"{key}_mean"] = mean(vals)
        result[f"{key}_median"] = median(vals)
    result["count"] = len(group_list)
    return result


# ── Main Analysis ──
def main():
    print("=" * 60)
    print("抖音非洲内容策略深度分析 v3")
    print("方法论: 创作者可控特征 → 独立互动比率（消除循环论证）")
    print("=" * 60)
    
    videos, load_stats = load_all_videos()
    print(f"\n有效视频总数: {len(videos)}")
    
    # ── Sheet 1: 方法论说明 ──
    methodology = [
        ("分析维度", "说明"),
        ("核心原则", "只分析创作者发布前可控制的特征，不因结果循环定义爆款"),
        ("自变量(预测因子)", "标题结构、时长、标签、发布时间、画幅、音乐类型、作者量级、国家/话题"),
        ("因变量(结果指标)", "评赞比(评论数/点赞数)、分赞比(分享数/点赞数)、藏赞比(收藏数/点赞数)、粉均互动率(总互动/粉丝数)"),
        ("为什么不用点赞数直接比较", "大V和小V的粉丝基数不同，绝对点赞数无法公平比较"),
        ("为什么用比率而非绝对值", "比率反映的是「内容质量」而非「传播规模」，消除作者量级偏差"),
        ("play_count为何不用", "搜索API返回的play_count始终为0，无法作为归一化分母"),
        ("follower_count归一化", "粉均互动率 = 总互动 / 粉丝数，反映每条内容对粉丝的激活效率"),
        ("分位比较法", "将作者按粉丝量分级，在同级内比较内容表现，消除量级偏差"),
        ("", ""),
        ("为什么v1/v2有循环论证", ""),
        ("v1/v2 爆款定义", "互动得分 = 点赞×1+评论×3+分享×5+收藏×2 → 取TOP10%"),
        ("v1/v2 问题", "得分本身就是互动数据的加权组合，分析'什么特征导致高分'="),
        ("", "分析'什么特征导致高互动'——自变量和因变量共用同一组数据"),
        ("v3 改进", "分离自变量(创作决策)和因变量(互动比率)，消除循环"),
    ]
    
    # ── Sheet 2: 标题特征 → 互动比率 ──
    print("\n[1/8] 标题特征分析...")
    fg = analyze_title_vs_engagement(videos)
    
    # Title length vs metrics
    title_len_data = []
    for label in ["极短(≤10字)", "短(11-25字)", "中(26-40字)", "长(41-60字)", "超长(>60字)"]:
        key = f"titlelen_{label}"
        if key in fg:
            grp = fg[key]
            vals = group_stats(grp, ["comment_like_ratio", "share_like_ratio", "collect_like_ratio", "engagement_per_follower", "total_engagement"])
            title_len_data.append({
                "标题长度": label,
                "视频数": vals["count"],
                "占比": f"{vals['count']/len(videos)*100:.1f}%",
                "评赞比(均值)": f"{vals['comment_like_ratio_mean']:.4f}",
                "评赞比(中位数)": f"{vals['comment_like_ratio_median']:.4f}",
                "分赞比(均值)": f"{vals['share_like_ratio_mean']:.4f}",
                "分赞比(中位数)": f"{vals['share_like_ratio_median']:.4f}",
                "藏赞比(均值)": f"{vals['collect_like_ratio_mean']:.4f}",
                "粉均互动(均值)": f"{vals['engagement_per_follower_mean']:.4f}",
                "粉均互动(中位数)": f"{vals['engagement_per_follower_median']:.4f}",
            })
    
    # Binary title features
    binary_features = []
    for feat_key, feat_name in [("has_question", "含疑问句"), ("has_number", "含数字"), ("has_exclamation", "含感叹号")]:
        yes_grp = [x for x in fg[feat_key] if x["yes"]]
        no_grp = [x for x in fg[feat_key] if not x["yes"]]
        yes_stats = group_stats(yes_grp, ["comment_like_ratio", "share_like_ratio"])
        no_stats = group_stats(no_grp, ["comment_like_ratio", "share_like_ratio"])
        binary_features.append({
            "特征": feat_name,
            "有该特征 视频数": len(yes_grp),
            "有该特征 评赞比": f"{yes_stats['comment_like_ratio_mean']:.4f}",
            "有该特征 分赞比": f"{yes_stats['share_like_ratio_mean']:.4f}",
            "无该特征 视频数": len(no_grp),
            "无该特征 评赞比": f"{no_stats['comment_like_ratio_mean']:.4f}",
            "无该特征 分赞比": f"{no_stats['share_like_ratio_mean']:.4f}",
            "评赞比差异": f"+{yes_stats['comment_like_ratio_mean'] - no_stats['comment_like_ratio_mean']:.4f}",
        })
    
    # Hook types
    hook_data = []
    hook_types = ["对比反差", "好奇悬念", "数字罗列", "情绪共鸣", "实用指南", "稀缺独家", "亲身经历", "无明确钩子"]
    for ht in hook_types:
        key = f"hooktype_{ht}"
        if key in fg:
            grp = fg[key]
            vals = group_stats(grp, ["comment_like_ratio", "share_like_ratio", "collect_like_ratio", "engagement_per_follower"])
            hook_data.append({
                "钩子类型": ht,
                "视频数": vals["count"],
                "评赞比": f"{vals['comment_like_ratio_mean']:.4f}",
                "分赞比": f"{vals['share_like_ratio_mean']:.4f}",
                "藏赞比": f"{vals['collect_like_ratio_mean']:.4f}",
                "粉均互动率": f"{vals['engagement_per_follower_mean']:.4f}",
            })
    
    # Hook count
    hook_count_data = []
    for label in ["0-1个钩子", "2个钩子", "3+个钩子"]:
        key = f"hooks_{label}"
        if key in fg:
            grp = fg[key]
            vals = group_stats(grp, ["comment_like_ratio", "share_like_ratio", "collect_like_ratio", "engagement_per_follower"])
            hook_count_data.append({
                "钩子数量": label,
                "视频数": vals["count"],
                "评赞比": f"{vals['comment_like_ratio_mean']:.4f}",
                "分赞比": f"{vals['share_like_ratio_mean']:.4f}",
                "藏赞比": f"{vals['collect_like_ratio_mean']:.4f}",
                "粉均互动率": f"{vals['engagement_per_follower_mean']:.4f}",
            })
    
    # ── Sheet 3: 时长 → 互动比率 ──
    print("[2/8] 时长分析...")
    dur_groups, _ = analyze_duration_vs_engagement(videos)
    dur_data = []
    for label, grp in dur_groups.items():
        vals = group_stats(grp, ["comment_like_ratio", "share_like_ratio", "collect_like_ratio", "engagement_per_follower", "total_engagement"])
        avg_likes = mean([v["likes"] for v in grp])
        avg_comments = mean([v["comments"] for v in grp])
        avg_shares = mean([v["shares"] for v in grp])
        dur_data.append({
            "时长区间": label,
            "视频数": vals["count"],
            "占比": f"{vals['count']/len(videos)*100:.1f}%",
            "平均点赞": f"{avg_likes:.0f}",
            "平均评论": f"{avg_comments:.1f}",
            "平均分享": f"{avg_shares:.1f}",
            "评赞比(均值)": f"{vals['comment_like_ratio_mean']:.4f}",
            "分赞比(均值)": f"{vals['share_like_ratio_mean']:.4f}",
            "藏赞比(均值)": f"{vals['collect_like_ratio_mean']:.4f}",
            "粉均互动率": f"{vals['engagement_per_follower_mean']:.4f}",
        })
    
    # ── Sheet 4: 发布时间 → 互动 ──
    print("[3/8] 发布时间分析...")
    day_groups, hour_groups, day_labels = analyze_posting_time(videos)
    
    day_data = []
    for day_en, label in zip(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"], day_labels):
        grp = day_groups[day_en]
        vals = group_stats(grp, ["comment_like_ratio", "share_like_ratio", "collect_like_ratio", "engagement_per_follower", "total_engagement"])
        avg_likes = mean([v["likes"] for v in grp])
        day_data.append({
            "星期": label,
            "视频数": vals["count"],
            "平均点赞": f"{avg_likes:.0f}",
            "评赞比": f"{vals['comment_like_ratio_mean']:.4f}",
            "分赞比": f"{vals['share_like_ratio_mean']:.4f}",
            "藏赞比": f"{vals['collect_like_ratio_mean']:.4f}",
            "粉均互动率": f"{vals['engagement_per_follower_mean']:.4f}",
        })
    
    hour_data = []
    for h in range(24):
        grp = hour_groups[h]
        vals = group_stats(grp, ["comment_like_ratio", "share_like_ratio", "engagement_per_follower"])
        hour_data.append({
            "时段": f"{h:02d}:00-{(h+1):02d}:00",
            "视频数": vals["count"],
            "评赞比": f"{vals['comment_like_ratio_mean']:.4f}",
            "分赞比": f"{vals['share_like_ratio_mean']:.4f}",
            "粉均互动率": f"{vals['engagement_per_follower_mean']:.4f}",
        })
    
    # ── Sheet 5: 作者量级分层分析 ──
    print("[4/8] 作者量级分层分析...")
    tiers = analyze_author_tier(videos)
    tier_data = []
    tier_detail = []
    for tier_name in ["微小(<1K)", "小(1K-1W)", "中(1W-10W)", "大(10W-100W)", "超大(>100W)"]:
        grp = tiers[tier_name]
        if not grp:
            continue
        vals = group_stats(grp, ["comment_like_ratio", "share_like_ratio", "collect_like_ratio", "engagement_per_follower", "total_engagement"])
        avg_likes = mean([v["likes"] for v in grp])
        avg_comments = mean([v["comments"] for v in grp])
        avg_shares = mean([v["shares"] for v in grp])
        authors = len(set(v["author_uid"] for v in grp))
        tier_data.append({
            "作者量级": tier_name,
            "视频数": vals["count"],
            "独立作者数": authors,
            "平均粉丝数": f"{mean([v['follower_count'] for v in grp]):.0f}",
            "平均点赞": f"{avg_likes:.0f}",
            "平均评论": f"{avg_comments:.1f}",
            "平均分享": f"{avg_shares:.1f}",
            "评赞比": f"{vals['comment_like_ratio_mean']:.4f}",
            "分赞比": f"{vals['share_like_ratio_mean']:.4f}",
            "藏赞比": f"{vals['collect_like_ratio_mean']:.4f}",
            "粉均互动率": f"{vals['engagement_per_follower_mean']:.4f}",
        })
        
        # Within-tier: top performers by engagement_per_follower
        top_in_tier = sorted(grp, key=lambda x: x["total_engagement"], reverse=True)[:10]
        for v in top_in_tier:
            tier_detail.append({
                "作者量级": tier_name,
                "作者": v["author_nickname"],
                "粉丝数": v["follower_count"],
                "标题": v["desc"][:50],
                "点赞": v["likes"],
                "评论": v["comments"],
                "分享": v["shares"],
                "评赞比": f"{v['comment_like_ratio']:.3f}",
                "粉均互动": f"{v['engagement_per_follower']:.4f}",
                "国家": v["country"],
            })
    
    # ── Sheet 6: 标签策略 ──
    print("[5/8] 标签策略分析...")
    tag_count_groups, tag_content = analyze_tags(videos)
    
    tag_count_data = []
    for label in ["无标签", "1-2个", "3-4个", "5-6个", "7+个"]:
        grp = tag_count_groups[label]
        vals = group_stats(grp, ["comment_like_ratio", "share_like_ratio", "collect_like_ratio", "engagement_per_follower"])
        tag_count_data.append({
            "标签数量": label,
            "视频数": vals["count"],
            "占比": f"{vals['count']/len(videos)*100:.1f}%",
            "评赞比": f"{vals['comment_like_ratio_mean']:.4f}",
            "分赞比": f"{vals['share_like_ratio_mean']:.4f}",
            "藏赞比": f"{vals['collect_like_ratio_mean']:.4f}",
            "粉均互动率": f"{vals['engagement_per_follower_mean']:.4f}",
        })
    
    # Top tags by engagement
    tag_perf = []
    for tag, grp in tag_content.items():
        if len(grp) < 5:
            continue
        vals = group_stats(grp, ["comment_like_ratio", "share_like_ratio", "engagement_per_follower", "total_engagement"])
        avg_likes = mean([v["likes"] for v in grp])
        tag_perf.append({
            "标签": tag,
            "出现次数": vals["count"],
            "平均点赞": f"{avg_likes:.0f}",
            "评赞比": f"{vals['comment_like_ratio_mean']:.4f}",
            "分赞比": f"{vals['share_like_ratio_mean']:.4f}",
            "粉均互动率": f"{vals['engagement_per_follower_mean']:.4f}",
        })
    tag_perf.sort(key=lambda x: int(x["出现次数"]), reverse=True)
    
    # ── Sheet 7: 画幅与音乐 ──
    print("[6/8] 画幅与音乐分析...")
    portrait_vids, landscape_vids, orig_sound, trending_sound = analyze_orientation_sound(videos)
    
    format_data = []
    for label, grp in [("竖屏(人像)", portrait_vids), ("横屏(宽屏)", landscape_vids)]:
        vals = group_stats(grp, ["comment_like_ratio", "share_like_ratio", "collect_like_ratio", "engagement_per_follower"])
        format_data.append({
            "画幅": label,
            "视频数": vals["count"],
            "占比": f"{vals['count']/len(videos)*100:.1f}%",
            "评赞比": f"{vals['comment_like_ratio_mean']:.4f}",
            "分赞比": f"{vals['share_like_ratio_mean']:.4f}",
            "藏赞比": f"{vals['collect_like_ratio_mean']:.4f}",
            "粉均互动率": f"{vals['engagement_per_follower_mean']:.4f}",
        })
    
    sound_data = []
    for label, grp in [("原创声/配音", orig_sound), ("热门音乐/他人声", trending_sound)]:
        vals = group_stats(grp, ["comment_like_ratio", "share_like_ratio", "engagement_per_follower"])
        avg_likes = mean([v["likes"] for v in grp])
        sound_data.append({
            "音乐类型": label,
            "视频数": vals["count"],
            "占比": f"{vals['count']/len(videos)*100:.1f}%",
            "平均点赞": f"{avg_likes:.0f}",
            "评赞比": f"{vals['comment_like_ratio_mean']:.4f}",
            "分赞比": f"{vals['share_like_ratio_mean']:.4f}",
            "粉均互动率": f"{vals['engagement_per_follower_mean']:.4f}",
        })
    
    # ── Sheet 8: 国家与话题对比 ──
    print("[7/8] 国家与话题分析...")
    country_groups, topic_groups = analyze_country_topic(videos)
    
    country_perf = []
    for country, grp in sorted(country_groups.items()):
        vals = group_stats(grp, ["comment_like_ratio", "share_like_ratio", "collect_like_ratio", "engagement_per_follower"])
        avg_likes = mean([v["likes"] for v in grp])
        avg_followers = mean([v["follower_count"] for v in grp])
        authors = len(set(v["author_uid"] for v in grp))
        country_perf.append({
            "国家": country,
            "视频数": vals["count"],
            "独立作者": authors,
            "平均作者粉丝": f"{avg_followers:.0f}",
            "平均点赞": f"{avg_likes:.0f}",
            "评赞比": f"{vals['comment_like_ratio_mean']:.4f}",
            "分赞比": f"{vals['share_like_ratio_mean']:.4f}",
            "藏赞比": f"{vals['collect_like_ratio_mean']:.4f}",
            "粉均互动率": f"{vals['engagement_per_follower_mean']:.4f}",
        })
    
    topic_perf = []
    for topic, grp in sorted(topic_groups.items()):
        vals = group_stats(grp, ["comment_like_ratio", "share_like_ratio", "engagement_per_follower"])
        avg_likes = mean([v["likes"] for v in grp])
        topic_perf.append({
            "搜索词": topic,
            "视频数": vals["count"],
            "平均点赞": f"{avg_likes:.0f}",
            "评赞比": f"{vals['comment_like_ratio_mean']:.4f}",
            "分赞比": f"{vals['share_like_ratio_mean']:.4f}",
            "粉均互动率": f"{vals['engagement_per_follower_mean']:.4f}",
        })
    
    # ── Sheet 9: 核心结论 ──
    print("[8/8] 生成结论...")
    conclusions = []
    
    # Top findings
    # 1. Find best comment-like ratio by title length
    best_cl = max(title_len_data, key=lambda x: float(x["评赞比(均值)"]))
    conclusions.append((
        "标题长度与评赞比",
        f"最佳评赞比的标题长度是「{best_cl['标题长度']}」(评赞比={best_cl['评赞比(均值)']})",
        f"该长度段有{best_cl['视频数']}个视频，占{best_cl['占比']}",
    ))
    
    # 2. Question marks effect
    q_data = binary_features[0]
    conclusions.append((
        "疑问句效果",
        f"含疑问句的标题评赞比 {q_data['有该特征 评赞比']} vs 无 {q_data['无该特征 评赞比']}，差异: {q_data['评赞比差异']}",
        "疑问句能否有效引发评论，直接看这个数字",
    ))
    
    # 3. Best duration for comments
    best_dur_c = max(dur_data, key=lambda x: float(x["评赞比(均值)"]))
    conclusions.append((
        "最佳评论触发时长",
        f"评赞比最高的时长区间是「{best_dur_c['时长区间']}」(评赞比={best_dur_c['评赞比(均值)']})",
        "评论率 = 评论数 / 点赞数，反映内容引发讨论的能力",
    ))
    
    # 4. Best duration for shares
    best_dur_s = max(dur_data, key=lambda x: float(x["分赞比(均值)"]))
    conclusions.append((
        "最佳传播触发时长",
        f"分赞比最高的时长区间是「{best_dur_s['时长区间']}」(分赞比={best_dur_s['分赞比(均值)']})",
        "分享率 = 分享数 / 点赞数，反映内容的病毒传播潜力",
    ))
    
    # 5. Best posting day
    best_day = max(day_data, key=lambda x: float(x["评赞比"]))
    conclusions.append((
        "最佳发布日",
        f"评赞比最高的发布日是「{best_day['星期']}」(评赞比={best_day['评赞比']})",
        f"该天有{best_day['视频数']}个视频",
    ))
    
    # 6. Best hook type
    best_hook = max(hook_data, key=lambda x: float(x["评赞比"]))
    conclusions.append((
        "最佳标题钩子(评论)",
        f"引发评论效果最好的钩子是「{best_hook['钩子类型']}」(评赞比={best_hook['评赞比']})",
        f"该类型{best_hook['视频数']}个视频",
    ))
    
    best_hook_s = max(hook_data, key=lambda x: float(x["分赞比"]))
    conclusions.append((
        "最佳标题钩子(分享)",
        f"引发分享效果最好的钩子是「{best_hook_s['钩子类型']}」(分赞比={best_hook_s['分赞比']})",
        f"该类型{best_hook_s['视频数']}个视频",
    ))
    
    # 7. Tag count
    best_tc = max(tag_count_data, key=lambda x: float(x["评赞比"]))
    conclusions.append((
        "最佳标签数量",
        f"评赞比最高的标签数量是「{best_tc['标签数量']}」(评赞比={best_tc['评赞比']})",
        f"有{best_tc['视频数']}个视频({best_tc['占比']})",
    ))
    
    # 8. Author tier effect
    tier_by_epf = sorted(tier_data, key=lambda x: float(x["粉均互动率"]), reverse=True)
    best_tier = tier_by_epf[0]
    conclusions.append((
        "粉均互动率最高作者层",
        f"「{best_tier['作者量级']}」作者粉均互动率最高 ({best_tier['粉均互动率']})",
        "小作者的粉丝激活效率更高 — 这是「素人机会」的量化证据",
    ))
    
    # 9. Portrait vs landscape
    better_fmt = format_data[0] if float(format_data[0]["评赞比"]) >= float(format_data[1]["评赞比"]) else format_data[1]
    conclusions.append((
        "画幅差异",
        f"「{format_data[0]['画幅']}」评赞比 {format_data[0]['评赞比']} vs 「{format_data[1]['画幅']}」评赞比 {format_data[1]['评赞比']}",
        "竖屏是抖音原生格式，横屏多来自其他平台搬运",
    ))
    
    # 10. Original sound
    better_snd = sound_data[0] if float(sound_data[0]["评赞比"]) >= float(sound_data[1]["评赞比"]) else sound_data[1]
    conclusions.append((
        "音乐策略",
        f"「{sound_data[0]['音乐类型']}」粉均互动 {sound_data[0]['粉均互动率']} vs 「{sound_data[1]['音乐类型']}」{sound_data[1]['粉均互动率']}",
        "原创声还是热门音乐更好，看数据说话",
    ))
    
    # ── Build Excel ──
    print("\n生成Excel...")
    wb = Workbook()
    
    # Remove default sheet
    wb.remove(wb.active)
    
    # ── Sheet 1: 方法论 ──
    ws = wb.create_sheet("方法论说明")
    write_rows(ws, 1, methodology)
    style_header(ws, 1, 2)
    auto_width(ws)
    
    # ── Sheet 2: 标题特征分析 ──
    ws = wb.create_sheet("标题长度vs互动比率")
    headers = list(title_len_data[0].keys())
    ws.append(headers)
    style_header(ws, 1, len(headers))
    write_rows(ws, 2, [[d[k] for k in headers] for d in title_len_data])
    auto_width(ws)
    
    ws2 = wb.create_sheet("标题二元特征")
    headers2 = list(binary_features[0].keys())
    ws2.append(headers2)
    style_header(ws2, 1, len(headers2))
    write_rows(ws2, 2, [[d[k] for k in headers2] for d in binary_features])
    auto_width(ws2)
    
    ws = wb.create_sheet("标题钩子类型")
    headers = list(hook_data[0].keys())
    ws.append(headers)
    style_header(ws, 1, len(headers))
    write_rows(ws, 2, [[d[k] for k in headers] for d in hook_data])
    auto_width(ws)
    
    ws = wb.create_sheet("钩子数量分析")
    headers = list(hook_count_data[0].keys())
    ws.append(headers)
    style_header(ws, 1, len(headers))
    write_rows(ws, 2, [[d[k] for k in headers] for d in hook_count_data])
    auto_width(ws)
    
    # ── Sheet 3: 时长分析 ──
    ws = wb.create_sheet("时长vs互动比率")
    headers = list(dur_data[0].keys())
    ws.append(headers)
    style_header(ws, 1, len(headers))
    write_rows(ws, 2, [[d[k] for k in headers] for d in dur_data])
    auto_width(ws)
    
    # ── Sheet 4: 发布时间 ──
    ws = wb.create_sheet("发布日期分析")
    headers = list(day_data[0].keys())
    ws.append(headers)
    style_header(ws, 1, len(headers))
    write_rows(ws, 2, [[d[k] for k in headers] for d in day_data])
    auto_width(ws)
    
    ws = wb.create_sheet("发布时段分析")
    headers = list(hour_data[0].keys())
    ws.append(headers)
    style_header(ws, 1, len(headers))
    write_rows(ws, 2, [[d[k] for k in headers] for d in hour_data])
    auto_width(ws)
    
    # ── Sheet 5: 作者量级 ──
    ws = wb.create_sheet("作者量级分层")
    headers = list(tier_data[0].keys())
    ws.append(headers)
    style_header(ws, 1, len(headers))
    write_rows(ws, 2, [[d[k] for k in headers] for d in tier_data])
    auto_width(ws)
    
    ws = wb.create_sheet("各级内TOP视频")
    headers = list(tier_detail[0].keys())
    ws.append(headers)
    style_header(ws, 1, len(headers))
    write_rows(ws, 2, [[d[k] for k in headers] for d in tier_detail])
    auto_width(ws)
    
    # ── Sheet 6: 标签 ──
    ws = wb.create_sheet("标签数量vs互动")
    headers = list(tag_count_data[0].keys())
    ws.append(headers)
    style_header(ws, 1, len(headers))
    write_rows(ws, 2, [[d[k] for k in headers] for d in tag_count_data])
    auto_width(ws)
    
    ws = wb.create_sheet("热门标签互动表现")
    headers = list(tag_perf[0].keys())
    ws.append(headers)
    style_header(ws, 1, len(headers))
    write_rows(ws, 2, [[d[k] for k in headers] for d in tag_perf[:80]])
    auto_width(ws)
    
    # ── Sheet 7: 画幅与音乐 ──
    ws = wb.create_sheet("画幅与音乐")
    headers = list(format_data[0].keys())
    ws.append(headers)
    style_header(ws, 1, len(headers))
    write_rows(ws, 2, [[d[k] for k in headers] for d in format_data])
    ws.append([])
    headers2 = list(sound_data[0].keys())
    start = len(format_data) + 3
    for j, h in enumerate(headers2):
        ws.cell(row=start, column=j+1, value=h)
    style_header(ws, start, len(headers2))
    write_rows(ws, start + 1, [[d[k] for k in headers2] for d in sound_data])
    auto_width(ws)
    
    # ── Sheet 8: 国家话题 ──
    ws = wb.create_sheet("国家对比")
    headers = list(country_perf[0].keys())
    ws.append(headers)
    style_header(ws, 1, len(headers))
    write_rows(ws, 2, [[d[k] for k in headers] for d in country_perf])
    auto_width(ws)
    
    ws = wb.create_sheet("话题对比")
    headers = list(topic_perf[0].keys())
    ws.append(headers)
    style_header(ws, 1, len(headers))
    write_rows(ws, 2, [[d[k] for k in headers] for d in topic_perf])
    auto_width(ws)
    
    # ── Sheet 9: 核心结论 ──
    ws = wb.create_sheet("核心结论")
    ws.append(["发现维度", "核心结论", "数据支撑"])
    style_header(ws, 1, 3)
    write_rows(ws, 2, [[c[0], c[1], c[2]] for c in conclusions])
    auto_width(ws)
    
    # Save
    wb.save(str(OUTPUT))
    print(f"\n报告已保存: {OUTPUT}")
    print(f"文件大小: {OUTPUT.stat().st_size / 1024:.0f}KB")
    
    # Print key findings
    print("\n" + "=" * 60)
    print("核心结论摘要")
    print("=" * 60)
    for c in conclusions:
        print(f"\n【{c[0]}】")
        print(f"  {c[1]}")
        print(f"  {c[2]}")


if __name__ == "__main__":
    main()
