# 抖音直播间监控 + 话题分析 Skill

基于 [LiveScope](https://github.com/PLA-yi/LiveScope) 改造的 WorkBuddy skill，用于监控抖音直播间、采集弹幕/进场/离场数据、分析聊天话题和主播语音内容。

## ✨ 功能特性

### 1. 弹幕数据采集（✅ 已验证）
- **弹幕**：实时采集观众聊天内容
- **进场/离场**：记录观众进入/离开直播间
- **礼物/点赞/关注**：采集互动数据
- **数据存储**：SQLite 数据库，支持批量写入

### 2. 话题分析（✅ 已验证）
- **弹幕话题**：从数据库读取 chat 消息，用 jieba 做关键词提取
- **音频转写**：支持 Whisper 音频转文字（tiny/base/small/medium 模型）
- **繁体转简体**：自动转换（opencc）
- **报告生成**：Markdown 格式，包含高频关键词和文本内容

### 3. 修复的问题
- ✅ 修复 `sign.js` 路径解析（原 LiveScope bug）
- ✅ 修复 `room_id` 识别逻辑（支持 18 位完整 room_id）
- ✅ 添加离场事件支持（MemberMessage action 字段判断）
- ✅ 添加 `MessageType.LEAVE` 枚举

## 📦 安装依赖

### 1. 创建 Python 虚拟环境（推荐）
```bash
cd ~/.workbuddy/skills/douyin-live-monitor
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# 或 venv\Scripts\activate  # Windows
```

### 2. 安装 Python 依赖
```bash
pip install -r requirements.txt
```

### 3. 安装 Protobuf 编译器（可选）
```bash
# macOS
brew install protobuf

# 或直接使用已编译的 protobuf 文件（已包含在 src/proto/ 目录）
```

### 4. 安装音频处理依赖（可选，用于音频转写）
```bash
# 安装 FFmpeg（用于音频格式转换）
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt update && sudo apt install ffmpeg

# 安装 Whisper（音频转文字）
pip install openai-whisper

# 安装 opencc（繁体转简体）
pip install opencc-python-reimplemented
```

## 🚀 快速开始

### 1. 监控直播间（采集数据）

```bash
# 方式 1：使用直播间 URL
python3 -m src.main douyin https://live.douyin.com/7659205935478393651

# 方式 2：使用 room_id
python3 -m src.main douyin 7659205935478393651

# 方式 3：使用短链接
python3 -m src.main douyin https://v.douyin.com/rAqHKqHzsAU/
```

**停止监控**：Ctrl+C

### 2. 查看采集数据

```bash
# 查看所有消息
python3 -m src.main messages

# 查看弹幕
python3 -m src.main messages --type chat

# 查看进场记录
python3 -m src.main messages --type enter

# 查看离场记录
python3 -m src.main messages --type leave
```

### 3. 分析话题

```bash
# 分析最近一场直播的弹幕话题
python3 -m src.main topic

# 分析指定会话
python3 -m src.main topic <session_id>

# 分析并生成报告
python3 -m src.main topic --output /tmp/topic_report.md
```

### 4. 音频转写 + 话题分析

```bash
# 使用 base 模型转写音频（推荐）
python3 audio_analysis.py /path/to/audio.wav --model base

# 使用 tiny 模型（最快，准确度较低）
python3 audio_analysis.py /path/to/audio.wav --model tiny

# 使用 small 模型（较慢，准确度高）
python3 audio_analysis.py /path/to/audio.wav --model small

# 指定报告输出路径
python3 audio_analysis.py /path/to/audio.wav -o /tmp/report.md

# 使用模拟数据测试
python3 audio_analysis.py --mock
```

## 📊 数据格式

### SQLite 数据库结构

**表：sessions**（直播会话）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT | 会话 ID（格式: douyin_<room_id>_<timestamp>）|
| platform | TEXT | 平台（douyin）|
| streamer_id | TEXT | 主播 ID |
| room_id | TEXT | 直播间 ID |
| status | TEXT | 状态（live/ended）|
| started_at | DATETIME | 开始时间 |
| ended_at | DATETIME | 结束时间 |

**表：messages**（消息记录）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增 ID |
| session_id | TEXT | 关联的会话 ID |
| msg_type | TEXT | 消息类型（chat/enter/leave/gift/like/subscribe）|
| user_id | TEXT | 用户 ID |
| username | TEXT | 用户名 |
| content | TEXT | 消息内容 |
| timestamp | DATETIME | 时间戳 |

## 🔧 高级用法

### 1. 定时监控（使用 cron）

```bash
# 编辑 crontab
crontab -e

# 添加定时任务（每天 10:00 开始监控，持续 2 小时）
0 10 * * * cd ~/.workbuddy/skills/douyin-live-monitor && timeout 7200 python3 -m src.main douyin <room_id>
```

### 2. 多直播间同时监控

```bash
# 启动多个进程，分别监控不同的直播间
python3 -m src.main douyin <room_id_1> &
python3 -m src.main douyin <room_id_2> &
wait
```

### 3. 自定义话题分析（修改停用词）

编辑 `src/processors/topic.py` 中的 `_STOP_WORDS` 集合，添加需要过滤的词语。

## 🐛 常见问题

### 1. `sign.js` 找不到
**错误**：`FileNotFoundError: [Errno 2] No such file or directory: 'sign.js'`

**解决**：确保从项目根目录运行脚本：
```bash
cd ~/.workbuddy/skills/douyin-live-monitor
python3 -m src.main douyin <room_id>
```

### 2. WebSocket 连接失败
**错误**：`websockets.exceptions.InvalidStatus: 400 Bad Request`

**原因**：抖音的签名算法更新，或 Cookie 失效。

**解决**：
- 更新 `douyin_sign/sign.js` 和 `douyin_sign/a_bogus.js`（从最新版抖音网页提取）
- 或提供有效的 Cookie（`--cookie` 参数）

### 3. 音频转写结果不准确
**建议**：
- 使用更大的 Whisper 模型（`--model small` 或 `--model medium`）
- 确保音频质量清晰（避免噪音、回声）
- 使用简体中文音频（或使用 `--language zh-cn` 参数）

### 4. 繁体中文输出
**原因**：Whisper 默认可能输出繁体。

**解决**：已内置 `opencc` 自动转换，确保已安装：
```bash
pip install opencc-python-reimplemented
```

## 📝 开发笔记

### 项目结构
```
douyin-live-monitor/
├── audio_analysis.py          # 音频转写 + 话题分析脚本
├── requirements.txt           # Python 依赖
├── SKILL.md                 # WorkBuddy skill 描述文件
├── src/
│   ├── config.py            # 配置文件（数据库路径、日志级别等）
│   ├── main.py             # CLI 入口
│   ├── collectors/         # 数据采集器
│   │   ├── base.py        # 采集器基类
│   │   └── douyin.py    # 抖音采集器（WebSocket + Protobuf）
│   ├── database/          # 数据库模块
│   │   ├── db.py         # 数据库连接和批量写入器
│   │   └── models.py     # SQLAlchemy ORM 模型
│   └── processors/       # 数据处理模块
│       ├── audio.py       # 音频处理器（预留）
│       └── topic.py       # 话题分析器（jieba 关键词提取）
├── proto/                  # Protobuf 定义
│   └── douyin.proto     # 抖音消息协议
├── douyin_sign/           # 抖音签名脚本
│   ├── sign.js           # 主签名算法
│   └── a_bogus.js      # 辅助签名算法
├── scripts/               # 工具脚本
│   ├── compile_proto.sh  # 编译 Protobuf 到 Python
│   └── get_stream_url.py # 获取直播流地址（预留）
├── tests/                 # 测试脚本
│   ├── monitor_5min.py  # 5 分钟监控测试
│   └── test_audio_analysis.py # 音频分析测试
└── .gitignore            # Git 忽略规则
```

### Git 提交历史
```
05d6b1a (HEAD -> main) feat: 添加音频转写 + 话题分析功能
8a28d3b chore: 移除测试文件
8c7a5e0 fix: 修复 sign.js 路径解析 + room_id 识别逻辑
f2a349b feat: 初始提交 - 抖音直播间监控 skill
```

## 📄 许可证

MIT License（基于 LiveScope 的修改版本）

## 🙏 致谢

- [LiveScope](https://github.com/PLA-yi/LiveScope) - 原始项目
- [DouyinLiveWebFetcher](https://github.com/saermart/DouyinLiveWebFetcher) - 抖音签名算法
- [jieba](https://github.com/fxsjy/jieba) - 中文分词
- [Whisper](https://github.com/openai/whisper) - 音频转文字
- [opencc](https://github.com/BYVoid/OpenCC) - 繁体转简体

## 📧 联系反馈

如有问题或建议，欢迎提交 Issue 或 Pull Request！
