---
name: douyin-live-monitor
description: >
  抖音直播间实时监控 skill。给定主播直播间 URL 或 room_id，
  自动连接抖音 WebSocket 弹幕流，实时抓取弹幕、进场/离场、礼物、点赞、关注消息，
  存入 SQLite 数据库，并支持对弹幕内容做话题分析（jieba 关键词提取）。
triggers:
  - 监控抖音直播间
  - 抖音直播弹幕
  - 抓取抖音直播间弹幕
  - 抖音主播直播间监控
  - douyin live monitor
  - 分析直播间话题
  - 抖音直播间离场
---

# 抖音直播间实时监控 Skill

## 功能概述

给定抖音主播直播间 URL（如 `https://live.douyin.com/XXXXXX`），自动完成：

1. **自动解析 room_id** — 从 URL 提取真实 room_id（无需手动查）
2. **实时抓取弹幕流** — WebSocket 长连接，Protobuf 协议解析，自动重连
3. **抓取全部消息类型**：
   - `chat` — 弹幕聊天内容
   - `enter` — 观众进场（MemberMessage action=1）
   - `leave` — 观众离场（MemberMessage action=2）**← 原 LiveScope 缺失，已修复**
   - `gift` — 礼物打赏
   - `like` — 点赞
   - `subscribe` — 关注主播
4. **持久化存储** — SQLite（`livescope.db`），含 session + message 两张表
5. **话题分析** — 对弹幕内容做 jieba 关键词提取，生成 Markdown 报告
6. **无 Cookie 也能跑** — 自动获取 ttwid，大部分公开直播间可直接监控

## 环境依赖

```bash
# 在 managed Python 环境中安装
/Users/goterra/.workbuddy/binaries/python/envs/default/bin/pip install \
    sqlalchemy aiosqlite httpx websockets pyexecjs rich click python-dotenv jieba
```

Node.js 需要系统已安装（签名计算用 `sign.js` 通过 execjs 调用 Node）。

## 文件结构

```
douyin-live-monitor/
├── SKILL.md                  # 本文件
├── requirements.txt          # Python 依赖
├── src/
│   ├── main.py               # CLI 入口（click 命令）
│   ├── config.py             # 配置（DATABASE_URL, Cookie 等）
│   ├── collectors/
│   │   ├── base.py           # 采集器基类（去重、重连、emit）
│   │   └── douyin.py         # 抖音采集器（WebSocket + Protobuf）
│   ├── database/
│   │   ├── models.py         # Session / Message ORM 模型
│   │   └── db.py             # 异步数据库引擎 + BatchWriter
│   └── processors/
│       └── topic.py          # 话题分析器（jieba 关键词提取）
├── proto/
│   └── douyin.proto          # 抖音消息 Protobuf 定义
├── scripts/
│   └── compile_proto.sh      # 编译 proto → Python
├── douyin_sign/              # 签名计算 JS 文件
│   ├── sign.js
│   └── a_bogus.js
└── livescope.db              # 运行时自动生成（SQLite 数据库）
```

## 使用方式

### 第一步：安装依赖 + 编译 Protobuf

```bash
cd ~/.workbuddy/skills/douyin-live-monitor

# 安装 Python 依赖
/Users/goterra/.workbuddy/binaries/python/envs/default/bin/pip install -r requirements.txt

# 编译 Protobuf（生成 src/proto/douyin_pb2.py）
bash scripts/compile_proto.sh
```

### 第二步：开始监控直播间

```bash
# 方式一：传直播间完整 URL（推荐，自动解析 room_id）
/Users/goterra/.workbuddy/binaries/python/envs/default/bin/python3 \
  -m src.main douyin https://live.douyin.com/XXXXXX

# 方式二：传 room_id（如果你已经知道）
/Users/goterra/.workbuddy/binaries/python/envs/default/bin/python3 \
  -m src.main douyin XXXXX
```

按 `Ctrl+C` 停止监控，自动结束会话并记录到数据库。

### 第三步：查看采集结果

```bash
# 查看最近一场直播的弹幕（默认显示 100 条）
/Users/goterra/.workbuddy/binaries/python/envs/default/bin/python3 \
  -m src.main messages

# 查看进场/离场记录
/Users/goterra/.workbuddy/binaries/python/envs/default/bin/python3 \
  -m src.main messages --type enter --limit 50

# 查看离场记录（leave 是本次修复新增的）
/Users/goterra/.workbuddy/binaries/python/envs/default/bin/python3 \
  -m src.main messages --type leave --limit 50

# 导出弹幕到文件
/Users/goterra/.workbuddy/binaries/python/envs/default/bin/python3 \
  -m src.main messages --export /tmp/danmu.txt
```

### 第四步：分析聊天话题

```bash
# 分析最近一场直播的话题（自动选最新 session）
/Users/goterra/.workbuddy/binaries/python/envs/default/bin/python3 \
  -m src.main topic

# 分析指定 session，并指定报告输出路径
/Users/goterra/.workbuddy/binaries/python/envs/default/bin/python3 \
  -m src.main topic douyin_XXXXXX_1234567890 --output /tmp/topic_report.md
```

## 数据库说明

SQLite 数据库文件：`livescope.db`（运行时在当前目录自动生成）

### sessions 表（直播会话）

| 字段 | 说明 |
|------|------|
| `id` | `{platform}_{room_id}_{timestamp}` |
| `platform` | `douyin` 或 `tiktok` |
| `streamer_id` | 主播 ID / room_id |
| `room_id` | 直播间 room_id |
| `started_at` | 开始时间 |
| `ended_at` | 结束时间（Stop 时自动填写）|
| `status` | `live` / `ended` |

### messages 表（弹幕消息）

| 字段 | 说明 |
|------|------|
| `session_id` | 关联的会话 ID |
| `msg_type` | `chat` / `enter` / `leave` / `gift` / `like` / `subscribe` |
| `user_id` | 用户 ID |
| `username` | 用户昵称 |
| `content` | 弹幕内容 / 礼物名称 |
| `extra` | JSON 附加字段（如礼物 ID、重复次数）|
| `timestamp` | 消息时间 |

## 注意事项

1. **抖音签名算法** — 项目使用 `sign.js`（从 LiveScope 继承）计算 WebSocket 连接签名，无需 Cookie 即可连接大部分公开直播间。若连接失败，尝试在 `.env` 中填入 `DOUYIN_COOKIE=你的cookie`。

2. **离场事件** — 抖音并不是所有直播间都推送离场消息（部分直播间只推进场），这是平台限制，不是代码 bug。

3. **Proto 编译** — 首次使用必须运行 `bash scripts/compile_proto.sh`，否则 Protobuf 解析模块无法加载。

4. **Node.js 依赖** — 签名计算需要 Node.js（execjs 调用）。系统已安装 Node 即可，无需额外配置。

## 获取抖音 Cookie（可选，连接失败时使用）

1. Chrome 打开 `https://live.douyin.com/`，登录抖音账号
2. 进入任意直播间
3. F12 → Application → Cookies → 复制 `ttwid` 和 `__ac_nonce` 等字段
4. 在项目目录创建 `.env` 文件：
   ```
   DOUYIN_COOKIE="ttwid=xxx; __ac_nonce=xxx"
   ```
