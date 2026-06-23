---
name: douyin-comment-analyzer
description: >
  抖音评论区高频话题分析工具。给定抖音号（unique_id 或主页链接），
  自动定位账号 → 提取所有视频评论 → 分词 → 统计高频话题 → 输出分析报告。
  支持登录态持久化（扫码一次即可），适合反复分析不同账号。
triggers:
  - 分析抖音号评论区
  - 抖音评论区高频话题
  - 帮我分析某个抖音号的评论
  - douyin comment analysis
---

# 抖音评论区高频话题分析 Skill

## 功能概述

给定抖音号（unique_id，如 `wxs666777888`），自动完成：

1. **定位账号** — 通过搜索找到对应 sec_uid 和视频列表
2. **提取评论** — 用 DrissionPage 无头浏览器逐个视频滚动加载，从 RENDER_DATA 提取评论文本
3. **话题分析** — 用 jieba 分词 + 停用词过滤，统计高频词组和话题
4. **输出报告** — 生成 Markdown 报告 + 词云图（可选）

## 环境依赖

需要以下 Python 包（在 managed 环境中安装）：

```bash
/Users/goterra/.workbuddy/binaries/python/envs/default/bin/pip install DrissionPage jieba wordcloud requests
```

Chrome/Chromium 由 DrissionPage 自动管理，无需手动安装。

## 文件结构

```
douyin-comment-analyzer/
├── SKILL.md            # 本文件
├── scripts/
│   ├── extract.py     # 评论提取脚本（登录态持久化）
│   └── analyze.py     # 话题分析脚本（分词+统计+报告）
└── profiles/
    └── README.md      # Chrome profile 存放说明
```

## 使用方式

### 第一步：安装依赖

```bash
/Users/goterra/.workbuddy/binaries/python/envs/default/bin/pip install DrissionPage jieba wordcloud requests
```

### 第二步：提取评论

```bash
/Users/goterra/.workbuddy/binaries/python/envs/default/bin/python3 \
  scripts/extract.py <douyin_unique_id> [max_videos]
```

- `max_videos` 可选，默认分析全部视频
- 首次运行会弹出浏览器，**需要扫码登录抖音**（只需一次，登录态保存在 `~/.workbuddy/douyin_chrome_profile`）
- 提取结果保存在 `~/.workbuddy/douyin_analysis/<unique_id>/`

### 第三步：分析话题

```bash
/Users/goterra/.workbuddy/binaries/python/envs/default/bin/python3 \
  scripts/analyze.py <unique_id>
```

- 自动读取提取结果，输出高频话题报告
- 报告保存在 `~/.workbuddy/douyin_analysis/<unique_id>/report.md`

## 关键技术细节

### 登录态持久化

使用固定 Chrome user-data-dir：`~/.workbuddy/douyin_chrome_profile`
首次运行 headless=False（显示浏览器），登录后切回 headless=True。

### 评论提取策略

1. 从页面 `RENDER_DATA`（base64 编码的 script 标签）解码提取
2. 正则匹配 `"text":"..."` 和 `"content":"..."` 字段
3. 同时用 DOM 文本节点作为补充
4. 过滤页脚/导航/法律声明等噪音文本

### 反爬应对

- `--disable-blink-features=AutomationControlled` 隐藏自动化特征
- 固定 user-data-dir 保持 cookies
- 滚动等待 + 随机延迟模拟人工操作
- 如遇 CAPTCHA，脚本会 pause 等待用户手动处理

## 注意事项

- 抖音有反爬机制，如遇到验证码需手动处理
- 评论提取速度约 1-2 分钟/视频（含滚动加载时间）
- 登录态 cookie 有效期约 2-7 天，过期后需重新扫码
- 如账号视频数 > 20，建议先用 `max_videos` 参数测试

## 输出格式

分析报告包含：

1. **账号基本信息**（昵称、粉丝数、视频数）
2. **评论总量统计**
3. **高频词 Top 50**（词频柱状图）
4. **话题聚类**（按关键词分组，每组列出典型评论）
5. **用户画像推断**（基于评论内容）
6. **内容建议**（基于高频提问/需求）
