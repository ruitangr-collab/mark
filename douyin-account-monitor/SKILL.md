---
name: douyin-account-monitor
description: >
  抖音账号持续监控 skill。给定任意抖音链接或 App 分享口令，自动解析出账号 sec_uid，
  纳入监控名单，周期性巡查主页，记录粉丝/获赞/作品数快照，发现新作品并输出增量报告。
  适用于竞品监控、同行动态追踪、达人观察。
triggers:
  - 监控这个抖音账号
  - 抖音账号监控
  - 把这个账号监控起来
  - 巡查抖音账号
  - 抖音竞品监控
  - douyin account monitor
allowed-tools: Bash
agent_created: true
---

# 抖音账号持续监控 Skill

## 职责边界（重要）

| 需求 | 用哪个技能 |
|---|---|
| **周期性监控账号**（新作品/涨粉/数据曲线） | **本技能** |
| 一次性深度分析某个账号的评论区话题 | `douyin-comment-analyzer` |
| 实时监控直播间弹幕 | `douyin-live-monitor` |

本技能和 `douyin-comment-analyzer` 共用 Chrome 登录态 profile
（`~/.workbuddy/douyin_chrome_profile`），扫码一次两边都能用。

## 环境依赖

```bash
/Users/goterra/.workbuddy/binaries/python/envs/default/bin/pip install DrissionPage
```

## 使用方式

工作目录：`~/.workbuddy/skills/douyin-account-monitor/scripts`

### 添加账号到监控名单

```bash
# 直接丢分享口令/短链/主页链接/视频链接，都能识别
python3 monitor.py add "8.94 复制打开抖音，看看【xxx的作品】 https://v.douyin.com/xxxxx/"
```

首次添加会自动：解析 sec_uid → 打开主页 → 抓账号信息 → **把当前视频全部录为基线**（基线不报警）。

### 周期性巡查

```bash
python3 monitor.py run               # 巡查名单内全部账号（含新作品评论抓取）
python3 monitor.py run --no-comments # 只抓数据，不抓评论（快很多）
python3 monitor.py run <sec_uid>     # 只巡查指定账号
```

输出每次巡查的粉丝/获赞/作品数、粉丝变化量、新作品列表。
**新作品被确认后，会自动打开视频页抓单条数据 + 评论区**，存进库。
有变化时额外写 `data/changes_<时间戳>.json`。

单次巡查最多处理 20 条新作品（`MAX_DETAIL_FETCH`），超出部分下轮继续，防止任务失控。

### 查看名单与趋势

```bash
python3 monitor.py list              # 监控名单 + 最新数据
python3 monitor.py report <sec_uid>  # 该账号历史趋势（Markdown 表格）
python3 monitor.py videos <sec_uid> [N]  # 作品数据排行（按点赞降序，含相对常态的倍数）
python3 monitor.py detail <aweme_id> # 手动补抓单条视频的数据与评论
python3 monitor.py backfill [sec_uid] # 批量补抓已有作品的点赞数，建立常态基线
```

`videos` 命令是看「哪条爆了」的主出口。它会算出该账号点赞数的**中位数作为常态基线**，
并显示每条作品的倍数（如 `12.3x`）——没有这个基线就无法判断什么算爆款。

新增账号后务必先跑一次 `backfill` 建立基线，否则前几条新作品无法判断是否起量。

### 批量导入已分析过的账号

```bash
python3 monitor.py import-existing
```

从 `~/.workbuddy/douyin_analysis/account_*/user_info.json` 批量导入
（`douyin-comment-analyzer` 此前分析过的账号），复用其历史数据建基线，零浏览器开销。

## 数据库

SQLite：`data/monitor.db`

| 表 | 说明 |
|---|---|
| `accounts` | 监控名单。除基本信息外还有：`douyin_id`（抖音号）、`ip_location`（IP 属地）、`age`、`region`、`baseline_digg`（点赞中位数，判断爆款的参照系）、`baselined`（是否已完成基线轮） |
| `snapshots` | 每次巡查的数据快照（粉丝/获赞/作品数）。`ok=0` 表示该次抓取失败 |
| `videos` | 已发现的作品。`seen_count` 出现次数、`notified` 是否已报过新作品；`detail_fetched_at` 非空表示已抓过单条数据（点赞/评论/收藏/转发/文案/发布时间） |
| `comments` | 抓到的评论文本，按 `(aweme_id, content)` 去重 |

## 已知坑（务必遵守）

1. **新作品误报（本技能最大的坑，务必理解后再改代码）**

   有两层原因，需要两道防线：

   - **表层：主页异步加载抖动。** 每次打开主页，滚动加载出的视频集合并不完全一致。
     只按「视频 ID 没见过」判定，会把「上次没加载到的老视频」误报成新作品（实测相隔 1 分钟误报 8 条）。
     → 防线一**二次确认**：新 ID 首次出现只记 `seen_count=1` 不报警，连续第 2 次巡查仍出现才判定为真新作品。

   - **深层：基线永远不完整。** 主页一次只能加载几十条，而账号可能有几千个作品
     （实测「非洲达哥」3680 个作品只能看到约 30 条）。所以只要滚动深度一变，
     就会持续涌出「基线里没有的老视频」。13 个账号首轮巡查后，待确认队列直接堆到 **112 条**，
     二次确认对此完全无效（它们会连续两次都出现）。
     → 防线二**作品总数硬约束**：`expected_new = 当前 aweme_count - 上次 aweme_count`。
     **作品总数没增加，就绝不可能有新作品**，本次见到的所有新 ID 一律直接标为基线。
     这是最有效的过滤器，不要移除。

   - 防线三**基线轮不报警**：`accounts.baselined=0` 时（首次巡查）只建基线不报警。

2. **作品点赞数可以直接从主页卡片批量拿，不必逐个打开视频页**
   主页每个作品是一个 `<li>`，内部文本节点顺序固定：
   `[可选「置顶」] → 点赞数 → 文案 → 文案(重复一次)`
   且 `<a href="/video/<id>">` 与 `<img alt="作者名：文案">` 在同一个 li 内，
   三者可在 li 级别精确关联。
   **收益**：13 个账号补完全部作品数据只要 6-8 分钟；若逐个打开视频页需 1 小时以上。
   所以 `backfill` 用主页方式，只有「新作品」才值得开视频页抓详情（要拿评论和转发）。

3. **主页数据同步必须放在新作品判定之后，且不能新增记录**
   `sync_homepage_videos(..., insert_new=False)`：若在判新之前同步，或允许新增，
   真新作品会被标成「已确认基线」而**永远漏报**。这是本技能最容易踩坏的一处，改代码时留意。
   只有 `backfill`（首次补数据）才用 `insert_new=True`。

4. **单条视频数据是 DOM 里的裸数字，必须以「举报」为锚点定位**
   视频页的点赞/评论/收藏/转发**没有标签**，就是 4 个连续的数字行，
   固定顺序 点赞 → 评论 → 收藏 → 转发，紧邻「举报」之前。
   RENDER_DATA 里**没有** `statistics` / `digg_count` 字段（实测为空，别浪费时间找）。
   更坑的是：页面上方播放器控件区会**重复出现同一组数字**，所以不能全文搜数字，
   必须从「举报」往前取 4 个数字，否则取到的是控件区那份。
   「发布时间」在「举报」之后 1-3 行，视频文案在 4 个数字之前。

5. **统计字段在 DOM 文本，不在 RENDER_DATA**
   RENDER_DATA 里的 nickname 可能是页面其他作者。昵称优先取 `<title>`，
   粉丝/获赞从 body 文本抓取，且标签与数值**可能同行（"粉丝21.0万"）也可能分行**，
   需双路匹配。
   抖音号/IP属地/年龄/地区挤在同一行：`抖音号：123IP属地：科特迪瓦39岁香港`，需一次正则拆四项。

6. **评论抓取依赖 douyin-comment-analyzer 的 common.py**
   `monitor.py` 通过路径 import 它的 `extract_comments_from_page`（噪音过滤词表保持一份，
   避免两边漂移）。若该技能被删除或改名，脚本会降级到内置精简过滤器，
   评论噪音会明显变多。改这两个技能时要留意这条依赖。

7. **必须复用登录态 profile**
   用 `~/.workbuddy/douyin_chrome_profile`。无头模式易被识别，默认有头
   （`--start-minimized` 最小化，不打扰）。

8. **登录态会过期**
   长时间未用会掉线，脚本会提示扫码并等待最多 6 分钟。这是本方案唯一硬伤，需人工介入。

9. **巡查频率不要过高**
   每次巡查要开一次浏览器（单账号约 40-60 秒，抓评论的账号更久）。
   高频轮询无意义且加速风控，每天 1 次足够。

## 定时任务

已配置的定期巡查见 WorkBuddy 自动化列表。执行时会最小化弹出浏览器窗口，属正常现象。
