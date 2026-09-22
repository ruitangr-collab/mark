---
name: xhs-account-data
description: 抓取并分析用户自己小红书账号的后台数据（创作者中心「笔记基础信息」表）。通过 Chrome DevTools Protocol 复用本机已登录的浏览器会话，取回曝光/观看/封面点击率/点赞/评论/收藏/涨粉/分享/人均观看时长等逐篇指标，落 SQLite 快照后产出账号趋势报告与单篇归因。当用户提到「小红书数据分析」「我的小红书数据」「小红书后台数据」「笔记数据怎么看」「哪篇笔记数据好」「小红书数据复盘」「账号数据诊断」「涨粉分析」「封面点击率」，或要求分析/导出自己小红书创作服务平台数据时使用。
agent_created: true
version: 1.0.0
---

# 小红书账号数据分析

从用户**自己的**创作者中心抓取逐篇笔记数据，建立历史快照，做趋势与归因分析。

底层取数能力来自开源项目 [white0dew/XiaohongshuSkills](https://github.com/white0dew/XiaohongshuSkills)（MIT，3.4k stars），原 `SKILL.md` 保留在本目录 `SKILL.upstream.md`。

## 安全边界（必读，不得放宽）

1. **默认只读。** 只用 `content-data`（读数据）与 `chrome_launcher`（起浏览器）。
2. **禁止自作主张执行写操作。** 上游还提供自动发布、评论、回复、点赞、收藏等命令。这些会以用户身份对平台产生公开动作，**风控等级远高于读取**，且本技能不承担发布职责（发布走 `xhs-batch-pipeline`）。除非用户当轮明确点名要求，否则不得调用。
3. **Cookie 与 profile 不落在 git 仓库内。** 运行数据统一放 `~/.workbuddy/runtime/xhs-data/`，该路径在 `~/.workbuddy/skills/` git 仓库之外。禁止把 Chrome profile 或 DB 写进技能目录。
4. 抓取频率克制。一天一次足够，不要连续高频轮询。

## 环境

| 项 | 值 |
|---|---|
| 技能目录 | `~/.workbuddy/skills/xhs-account-data` |
| Python | `~/.workbuddy/binaries/python/envs/default/bin/python` |
| 运行目录 | `~/.workbuddy/runtime/xhs-data/`（CSV / SQLite / 报告 / Chrome profile） |
| 依赖 | `requests`、`websockets`（已装在隔离 venv） |
| 平台 | macOS 已验证；上游 README 写「仅测试 Windows」是过期信息，`chrome_launcher.py` 有 `sys.platform == "darwin"` 分支 |

统一设 `PY` 与运行目录环境变量：

```bash
cd ~/.workbuddy/skills/xhs-account-data
PY=~/.workbuddy/binaries/python/envs/default/bin/python
export XHS_RUNTIME_DIR=~/.workbuddy/runtime/xhs-data
export LOCALAPPDATA="$XHS_RUNTIME_DIR"   # 否则 profile 会落到 ~/Google/Chrome
```

## 工作流

### 第一步：登录（每个账号一次性）

```bash
$PY scripts/chrome_launcher.py --account default      # 起一个带调试端口的 Chrome
$PY scripts/cdp_publish.py login                      # 在弹出的窗口里扫码
$PY scripts/cdp_publish.py check-login                # 验证
```

登录态默认缓存 12 小时（仅缓存「已登录」结果）。失效时 `content-data` 会报非 200 API 状态，重跑 `login` 即可。

### 第二步：抓快照

**一条命令完成 抓取 → 入库 → 出报告：**

```bash
$PY scripts/xhs_snapshot.py collect
```

也可分开：

```bash
$PY scripts/cdp_publish.py content-data --csv-file "$XHS_RUNTIME_DIR/csv/2026-09-17.csv"
$PY scripts/xhs_snapshot.py ingest --csv "$XHS_RUNTIME_DIR/csv/2026-09-17.csv"
$PY scripts/xhs_snapshot.py report --days 30 --top 5
$PY scripts/xhs_snapshot.py trend --note-id <note_id>     # 或 --title 关键词
```

### 第三步：解读

拿 `report` 输出做归因。判断顺序按漏斗走，不要跳步：

| 症状 | 归因方向 |
|---|---|
| 曝光低 | 选题/标签/发布时间问题，或账号权重（新号冷启动）——流量池没进 |
| 曝光正常但封面点击率低（<3%） | 封面与标题问题。曝光是平台给的，点击率是封面挣的 |
| 点击率正常但观看低 | 标题党与实际内容不符，或首图与正文脱节 |
| 观看正常但互动低 | 内容没给行动理由，缺少提问/引导 |
| 互动正常但不涨粉 | 单篇价值成立但**人设不成立**——用户看完不觉得"关注你有后续" |
| 人均观看时长短 | 开头 3 行没接住；或图文信息密度不够，用户划走 |

**核心事实：`content-data` 给的是累计值，不是当日值。** 所以：

- 单次抓取只能横向比（哪篇比哪篇好）——**这已经能回答"为什么这篇比那篇好"**。
- 要回答"这篇的衰减速度"「发布后 24h vs 72h 表现」，必须有 ≥3 天快照。**每次运行只写一条当日快照，攒天数是唯一的办法。**
- 因此建议每日固定跑一次 `collect`，形成基线。

## 数据字段

`content-data` 抓取创作者中心 `statistics/data-analysis` 页的「笔记基础信息」表，共 12 个指标：

标题、发布时间、曝光、观看、封面点击率、点赞、评论、收藏、涨粉、分享、人均观看时长、弹幕。

## 技术要点（排查用）

- **脚本不直接调 API。** 创作者中心数据接口 `/api/galaxy/creator/datacenter/note/analyze/list` 对裸 HTTP 请求返回 **HTTP 406**（缺反爬头）。上游走 CDP `Network.responseReceived` 捕获页面自身发起的请求，天然携带会话 Cookie 与平台生成头，因此能拿到数据。
- **它校验的是「创作者中心」登录态**，与首页登录态不同。`content-data` 要求前者。
- **分页要注意。** `--page-num` / `--page-size` 是"调用方的意图"，实际返回取决于页面脚本自己请求了什么。若捕获到的请求与请求参数不一致，脚本会打印 warning 并原样返回。**抓全量笔记需要核对返回条数，必要时翻页重试。**
- 页面改版后若报错，先查 `scripts/cdp_publish.py` 的 `SELECTORS` 与 `CDP/Network` 捕获逻辑。
- 想直接读某个文件夹的 CSV（比如手动从别处导出的），用 `ingest`，不需要 Chrome。

## 风险提示

上游 README 明确警告：使用本项目进行小红书自动化，**存在被平台风控、限流、封号的风险**。

实操建议：
- 一天一次抓取，不要脚本化高频轮询。
- 用**测试号**先验证流程，再上主号。
- 绝对不要在未获用户明确确认时调用发布/评论/点赞类命令。
- 若账号为实名主号（如「非洲地产人」人设号），读取类操作的收益/风险比明显优于写操作——优先只做读取。

## 与其他技能的分工

| 技能 | 职责 |
|---|---|
| `xhs-batch-pipeline` | 生产端：选题 → 写稿 → 入库 |
| `xhs-note-writer` | 单篇图文笔记撰写 |
| **本技能** | **回收端：取数 → 快照 → 趋势/归因** |

三者构成闭环：本技能产出的「哪类选题/封面真的有效」应当回流到 `xhs-batch-pipeline` 的选题决策。
