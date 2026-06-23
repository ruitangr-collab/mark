#!/usr/bin/env python3
"""
抖音评论话题分析脚本 - Skill 版
用法: python3 analyze.py <douyin_unique_id>

功能:
  1. 读取 extract.py 输出的 all_comments.json
  2. jieba 分词 + 停用词过滤
  3. 统计高频词 Top 50 + 关键词组
  4. 聚类话题 + 提取典型评论
  5. 输出 Markdown 报告
"""
import sys, json, re, collections
from pathlib import Path

try:
    import jieba
    import jieba.analyse
except ImportError:
    print("❌ 请先安装 jieba: pip install jieba")
    sys.exit(1)

# ─── 配置 ─────────────────────────────────────────────────────────────
OUTPUT_BASE = Path.home() / ".workbuddy/douyin_analysis"
STOPWORDS = set("""
的 了 是 在 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 你 会 能 要 去 好 可以 怎么 什么 吧 啊 哦 嗯 呢 哈 嗯嗯 哈哈 在哪 哪里 哪个 有没有 是不是 能不能 会不会
抖音 视频 主页 关注 粉丝 点赞 评论 分享 收藏 播放 私信 首页 搜索 推荐 直播
video com http https www 主页 双击 评论区 评论区了 打开抖音 抖音号 抖音APP
""".split())
# ────────────────────────────────────────────────────────────────────────


def load_comments(unique_id: str) -> list[str]:
    """读取提取好的评论文件"""
    path = OUTPUT_BASE / unique_id / "all_comments.json"
    if not path.exists():
        print(f"❌ 未找到评论文件: {path}")
        print(f"   请先运行: python3 extract.py {unique_id}")
        sys.exit(1)
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def tokenize(texts: list[str]) -> list[tuple[str, int]]:
    """
    jieba 分词，返回 (词, 词频) 列表，已过滤停用词和短词。
    """
    counter = collections.Counter()
    for text in texts:
        words = jieba.lcut(text)
        for w in words:
            w = w.strip()
            if len(w) < 2 or w in STOPWORDS:
                continue
            # 过滤纯数字/标点
            if re.fullmatch(r'[\d\s\W_]+', w):
                continue
            counter[w] += 1

    return counter.most_common(100)


def extract_topics(texts: list[str], top_words: list[str]) -> dict:
    """
    基于高频词对评论做话题聚类。
    返回 {话题名: [典型评论...]}
    """
    topics = collections.defaultdict(list)

    for text in texts:
        matched = False
        for word in top_words:
            if word in text:
                key = word
                topics[key].append(text)
                matched = True
                break
        if not matched and len(topics) < 20:
            # 归入"其他"
            topics['__其他__'].append(text)

    # 每个话题最多保留 5 条典型评论
    result = {}
    for k, v in sorted(topics.items(), key=lambda x: -len(x[1])):
        result[k] = v[:5]
    return result


def generate_report(unique_id: str, comments: list[str],
                    word_freq: list[tuple], topics: dict) -> str:
    """生成 Markdown 分析报告"""
    lines = []
    lines.append(f"# 抖音号 `{unique_id}` 评论区高频话题分析\n")
    lines.append(f"> 分析时间: {Path(__file__).stat().st_mtime}")
    lines.append(f"> 评论总数: {len(comments)} 条\n")
    lines.append("---\n")

    # 高频词 Top 30
    lines.append("## 📊 高频词 Top 30\n")
    for i, (word, freq) in enumerate(word_freq[:30], 1):
        bar = "█" * min(freq // 2, 40)
        lines.append(f"{i:2d}. **{word}** `{freq:3d}` {bar}")
    lines.append("")

    # 话题聚类
    lines.append("## 💬 话题聚类\n")
    # 按话题评论数排序
    sorted_topics = sorted(topics.items(), key=lambda x: -len(x[1]))
    for topic, samples in sorted_topics[:15]:
        if topic == '__其他__':
            continue
        lines.append(f"### {topic}（{len(topics[topic])} 条相关评论）\n")
        for sample in samples:
            lines.append(f"- _{sample}_")
        lines.append("")

    # 典型评论展示
    lines.append("## 📋 随机典型评论（20条）\n")
    import random
    random.seed(42)
    samples = random.sample(comments, min(20, len(comments)))
    for i, c in enumerate(samples, 1):
        lines.append(f"{i}. {c}")
    lines.append("")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("用法: python3 analyze.py <douyin_unique_id>")
        sys.exit(1)

    unique_id = sys.argv[1]
    print(f"[分析] {unique_id}")

    # 1. 加载评论
    comments = load_comments(unique_id)
    print(f"  评论数: {len(comments)}")

    # 2. 分词统计
    print("  正在分词...")
    word_freq = tokenize(comments)
    print(f"  高频词 Top10: {[w for w, _ in word_freq[:10]]}")

    # 3. 话题聚类
    top_words = [w for w, _ in word_freq[:50]]
    print("  正在聚类话题...")
    topics = extract_topics(comments, top_words)

    # 4. 生成报告
    report = generate_report(unique_id, comments, word_freq, topics)
    out_path = OUTPUT_BASE / unique_id / "report.md"
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"\n✅ 报告已生成: {out_path}")
    print(f"\n── 高频词 Top 15 ──")
    for i, (w, f) in enumerate(word_freq[:15], 1):
        print(f"  {i:2d}. {w} ({f})")


if __name__ == '__main__':
    main()
