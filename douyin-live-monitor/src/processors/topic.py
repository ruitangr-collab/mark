"""
聊天话题分析器

从 SQLite 数据库读取 chat 消息，用 jieba 做关键词提取 + 话题聚类。
输出：高频词云数据、话题片段列表、Markdown 报告。
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# ── 停用词（可扩展）───────────────────────────────────────────────────────────

_STOP_WORDS = {
    # 标点符号 & 特殊字符
    "", " ", "　", "，", "。", "、", "！", "？", "!", "?",
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人",
    "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去",
    "你", "会", "着", "没有", "看", "好", "自己", "这",
    # 弹幕语气词
    "哈哈", "哈哈哈", "嗯", "哦", "啊", "呃", "哟", "呀", "哇",
    "主播", "加油", "666", "牛", "牛牛牛",
}

# 尝试导入 jieba，失败则降级为正则分词
try:
    import jieba    # type: ignore
    import jieba.analyse  # type: ignore
    _HAS_JIEBA = True
except ImportError:
    _HAS_JIEBA = False
    logger.warning("[Topic] jieba 未安装，将使用正则降级分词")


def _extract_keywords_regex(texts: list[str], top_k: int = 30) -> list[tuple[str, int]]:
    """正则降级方案：按非中文字符切分，统计词频"""
    words: list[str] = []
    for text in texts:
        # 提取中文词组（2字及以上）和英文单词
        tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{2,}", text)
        words.extend(w for w in tokens if w not in _STOP_WORDS)
    return Counter(words).most_common(top_k)


def _extract_keywords_jieba(texts: list[str], top_k: int = 30) -> list[tuple[str, int]]:
    """jieba TF-IDF 关键词提取"""
    corpus = " ".join(texts)
    # 使用 TF-IDF 算法，取 top_k 个关键词
    keywords = jieba.analyse.extract_tags(corpus, topK=top_k, withWeight=True)
    return [(w, int(score * 1000)) for w, score in keywords]


def analyze_text(text: str, top_k: int = 30) -> dict:
    """
    分析纯文本的话题（用于音频转写结果）。
    
    参数
    ----
    text : 要分析的文本
    top_k : 返回高频词数量
    
    返回
    ----
    {
        "text_length": int,
        "keywords": [("词", 权重), ...],
        "sentences": [句子列表],
    }
    """
    # 按标点符号分割句子
    sentences = [s.strip() for s in re.split(r'[。！？!?\n]+', text) if s.strip()]
    
    # 关键词提取
    if _HAS_JIEBA:
        keywords = _extract_keywords_jieba(sentences, top_k)
    else:
        keywords = _extract_keywords_regex(sentences, top_k)
    
    return {
        "text_length": len(text),
        "sentence_count": len(sentences),
        "keywords": keywords,
        "sentences": sentences,
    }


def analyze_session(db_path: str | Path, session_id: str, top_k: int = 30) -> dict:
    """
    分析一场直播的聊天话题。

    参数
    ----
    db_path : SQLite 数据库路径
    session_id : 会话 ID
    top_k : 返回高频词数量

    返回
    ----
    {
        "session_id": str,
        "total_chat": int,
        "keywords": [("词", 权重), ...],
        "topics": [{"topic": "话题描述", "messages": [...]}],
        "timeline": [{"time": "...", "keyword": "..."}],
    }
    """
    import sqlite3

    db_path = Path(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 读取该 session 的所有 chat 消息
    cur.execute(
        "SELECT content, timestamp FROM messages "
        "WHERE session_id = ? AND msg_type = 'chat' "
        "ORDER BY timestamp",
        (session_id,),
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return {"session_id": session_id, "total_chat": 0, "keywords": [], "topics": []}

    texts = [r["content"] for r in rows if r["content"]]

    # 关键词提取
    if _HAS_JIEBA:
        keywords = _extract_keywords_jieba(texts, top_k)
    else:
        keywords = _extract_keywords_regex(texts, top_k)

    # 简单话题分段：按时间窗口（每 5 分钟）提取局部高频词
    topics = _extract_topic_windows(rows, window_minutes=5)

    return {
        "session_id": session_id,
        "total_chat": len(texts),
        "keywords": keywords,
        "topics": topics,
    }


def _extract_topic_windows(
    rows: list, window_minutes: int = 5, top_per_window: int = 5
) -> list[dict]:
    """按时间窗口分段，每段提取局部高频词作为话题线索"""
    if not rows:
        return []

    windows: list[dict] = []
    window: list[str] = []
    window_start: str | None = None

    for row in rows:
        ts = row["timestamp"]
        content = row["content"] or ""
        if window_start is None:
            window_start = ts
            window = [content]
        else:
            # 简单字符串比较（SQLite 时间格式是可排序的）
            try:
                from datetime import datetime
                t0 = datetime.fromisoformat(window_start.replace("Z", "+00:00"))
                t1 = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                diff_min = (t1 - t0).total_seconds() / 60
            except Exception:
                diff_min = 0

            if diff_min < window_minutes:
                window.append(content)
            else:
                # 结束当前窗口
                words = _extract_keywords_jieba(window, top_per_window) if _HAS_JIEBA else _extract_keywords_regex(window, top_per_window)
                windows.append({
                    "start": window_start,
                    "end": ts,
                    "msg_count": len(window),
                    "keywords": [w for w, _ in words],
                })
                window_start = ts
                window = [content]

    # 最后一个窗口
    if window:
        words = _extract_keywords_jieba(window, top_per_window) if _HAS_JIEBA else _extract_keywords_regex(window, top_per_window)
        windows.append({
            "start": window_start,
            "end": rows[-1]["timestamp"],
            "msg_count": len(window),
            "keywords": [w for w, _ in words],
        })

    return windows


def generate_text_report(analysis: dict, output_path: str | Path, title: str = "音频转写话题分析报告") -> Path:
    """
    为文本分析结果生成 Markdown 报告。
    
    参数
    ----
    analysis : analyze_text() 的返回值
    output_path : 报告输出路径
    title : 报告标题
    
    返回
    ----
    报告文件路径
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    lines = [
        f"# {title}",
        f"",
        f"- 文本长度：{analysis['text_length']} 字符",
        f"- 句子数：{analysis['sentence_count']}",
        f"- 分析时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"",
        f"## 高频关键词（Top {len(analysis['keywords'])}）",
        f"",
    ]
    
    for word, weight in analysis["keywords"]:
        lines.append(f"- **{word}**（权重 {weight}）")
    
    lines += [
        f"",
        f"## 转写文本（分句）",
        f"",
    ]
    
    for i, sent in enumerate(analysis["sentences"], 1):
        lines.append(f"{i}. {sent}")
    
    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("[Topic] 文本报告已生成：%s", output_path)
    return output_path


def generate_report(analysis: dict, output_path: str | Path) -> Path:
    """
    生成 Markdown 话题分析报告。
    返回报告文件路径。
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# 直播间话题分析报告",
        f"",
        f"- 会话 ID：{analysis['session_id']}",
        f"- 弹幕总数：{analysis['total_chat']}",
        f"- 分析时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"",
        f"## 高频关键词（Top {len(analysis['keywords'])}）",
        f"",
    ]

    for word, weight in analysis["keywords"]:
        lines.append(f"- **{word}**（权重 {weight}）")

    lines += [
        f"",
        f"## 时间窗口话题分布",
        f"",
        f"按每 5 分钟窗口提取的局部高频词：",
        f"",
    ]

    for i, w in enumerate(analysis["topics"], 1):
        keywords_str = "、".join(w["keywords"][:5])
        lines.append(f"### 窗口 {i}：{w['start']} ~ {w['end']}")
        lines.append(f"- 弹幕条数：{w['msg_count']}")
        lines.append(f"- 局部高频词：{keywords_str}")
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("[Topic] 报告已生成：%s", output_path)
    return output_path
