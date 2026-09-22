---
name: xhs-account-monitor
description: 小红书账号持续监控（抖音监控技能的小红书适配版）。给定任意小红书主页链接、笔记链接、xhslink 短链或 App 分享口令，自动解析账号、纳入监控名单、周期性巡查主页，记录粉丝/获赞快照，发现新笔记并抓取数据与评论，输出增量报告。另可对已监控账号做结构参数拆解与跨账号选题机会汇总，供内容创作参考。当用户说「监控这个小账号」「小红书账号监控」「把这个小红书号监控起来」「巡查小红书账号」「小红书竞品监控」「拆解这个小红书号」「小红书选题机会」时使用。
triggers:
  - 监控这个小红书账号
  - 小红书账号监控
  - 把这个小红书号监控起来
  - 巡查小红书账号
  - 小红书竞品监控
  - 拆解这个小红书号
  - xhs account monitor
allowed-tools: Bash
agent_created: true
version: 1.0.0
---

# 小红书账号持续监控

抖音 `douyin-account-monitor` 的小红书适配版。**架构相同，判新逻辑不同** —— 差异不是细节，是机制。

## 职责边界

| 需求 | 用哪个技能 |
|---|---|
| **监控别人（或自己）的小红书账号，看新笔记/涨粉/趋势** | **本技能** |
| **分析自己账号的后台数据**（创作者中心，曝光/点击率/涨粉） | `xhs-account-data` |
| 写小红书笔记 | `xhs-note-writer` |
| 批量出笔记管线 | `xhs-batch-pipeline` |

**登录态共享**：本技能与 `xhs-account-data` 共用同一套 CDP + Chrome profile
（`~/.workbuddy/runtime/xhs-data/`），扫码一次两边都能用。

## ⚠️ 与抖音版的三处机制差异（改代码前必读）

| 维度 | 抖音 | 小红书 | 本技能的取舍 |
|---|---|---|---|
| **笔记标识** | `aweme_id` 永久有效，可随时 `detail` 补抓 | `feed_id` + `xsec_token`，**token 是列表派生的临时令牌，会过期** | 详情必须在**同轮巡查内**立刻抓；`detail` 补抓会先回主页刷新 token |
| **主页卡片指标** | 主页卡片带点赞数，13 账号批量 backfill 仅 6-8 分钟 | 主页卡片**零指标**（只有 标题/封面/id/token） | 建基线只能逐个开详情页，成本高一个数量级。**不要试图复用抖音的批量 backfill** |
| **作品总数** | `aweme_count` 可算 `expected_new` 增量，是最有效的防误报防线 | 主页**没有笔记总数**（`probe` 可现场确认） | 改用**头部位置约束**（见下） |

## 判新三防线

这是本技能最容易改坏的地方。改之前先跑 `scripts/_selftest.py`。

```
防线 0  头部位置约束（小红书独有，替代抖音的作品总数硬约束）
        主页按「置顶 + 最新发布」排序 → 真新笔记必然落在前 HEAD_WINDOW 位。
        出现在深部的「新 ID」= 基线没采全的历史笔记 → 直接压制，不报警。
        ⚠️ 取舍：两轮之间发布超过 HEAD_WINDOW 条的高频号会有漏报。
           用 `run --head-window N` 按账号放宽，别动默认值。

防线 1  二次确认
        新 ID 首次出现只入队（seen_count=1），不报警；
        下一轮列表里仍在 → 提到 seen_count=2，才算确认。

防线 2  publish_time 复核
        确认后抓到发布时间，若早于今天 STALE_DAYS(=7) 天 → 判为误入的历史笔记，
        回写 suppressed='stale_publish_time' 并从报告撤下。
```

### 两条不可违反的实现约束（都踩过，都是真 bug）

1. **入队不设预算，抓详情才设预算。**
   入队便宜（写一行），抓详情贵（一次页面加载）。`MAX_DETAIL_PER_RUN` **只截详情抓取**，
   超额部分保持 `notified=0` 留到下轮。
   ❌ **绝不能在入队阶段写死压制** —— 笔记一旦进 DB 就不再是 fresh，
   下轮不会被重新发现，那条真新笔记**永远报不出来**。
   这是抖音坑 14（配额被烧掉导致永久压制）的同一类错误，别重犯。

2. **`notified=1` 只能在详情抓取成功之后写。**
   它表示「详情已抓到**并已报告**」，不是「已确认」。
   写早了 → 详情抓取失败时那条永久卡在未报告状态。
   配套机制：`_judge_new` 里的**欠账重试** —— 每轮会把
   `seen_count>=2 AND notified=0` 的笔记重新带出来重抓，保证不丢。

### 📌 给调用方（含自动化）的提醒

**stdout 的「本轮无新笔记」完全不可信**，它只表示本轮没走到报告。真新笔记可能：
- 还在二次确认队列里（`seen_count=1 AND notified=0`）
- 已确认但详情超预算顺延（`seen_count>=2 AND notified=0`）

正确查法：

```sql
-- 待确认队列
SELECT note_id,title FROM notes WHERE seen_count=1 AND notified=0;
-- 已确认待抓详情（含上轮欠账）
SELECT note_id,title FROM notes WHERE seen_count>=2 AND notified=0;
-- 被压制的原因分布（判断防线是否过严）
SELECT suppressed, COUNT(*) FROM notes WHERE suppressed IS NOT NULL GROUP BY suppressed;
```

## 使用方式

工作目录：`~/.workbuddy/skills/xhs-account-monitor/scripts`
解释器：`~/.workbuddy/binaries/python/envs/default/bin/python`

```bash
cd ~/.workbuddy/skills/xhs-account-monitor
PY=~/.workbuddy/binaries/python/envs/default/bin/python
export LOCALAPPDATA=~/.workbuddy/runtime/xhs-data   # 与 xhs-account-data 共用登录态
```

### 0. 首次自检（强烈建议先跑）

```bash
$PY scripts/monitor.py probe "https://www.xiaohongshu.com/user/profile/<user_id>"
```

它会打印主页**实际暴露了什么字段**，并直接回答两个关键问题：
主页有没有「笔记总数」？卡片有没有指标？
**这是唯一能确认上面那张差异表的最快方式** —— 小红书改版频繁，先 probe 再动手。

### 1. 纳入监控

```bash
$PY scripts/monitor.py add "8.94 复制打开小红书，看看【xxx】的主页 https://xhslink.com/xxxx"
$PY scripts/monitor.py add "https://www.xiaohongshu.com/user/profile/<user_id>"
```

支持：主页链接 / 笔记链接 / xhslink 短链 / App 分享口令。
首次添加会自动：解析 user_id → 抓账号信息 → **把当前可见笔记全部录为基线**（基线不报警）
→ 建点赞中位数基线。

### 2. 巡查

```bash
$PY scripts/monitor.py run                 # 全部账号
$PY scripts/monitor.py run --no-comments   # 只抓数据不抓评论（快很多）
$PY scripts/monitor.py run <user_id>       # 单个账号
```

每次巡查：粉丝/获赞快照 + 判新 + **同轮抓新笔记详情**（赞/藏/评/转/发布时间/标签）。

### 3. 查看

```bash
$PY scripts/monitor.py list                 # 名单 + 最新快照 + 待确认队列深度
$PY scripts/monitor.py report <user_id>     # 粉丝趋势
$PY scripts/monitor.py notes <user_id> [N]  # 笔记排行（含相对常态倍数 + 藏赞比）
$PY scripts/monitor.py detail <note_id>     # 补抓单条（自动刷新 token）
$PY scripts/monitor.py backfill [user_id]   # 建/重建点赞基线
```

`notes` 是看「哪条爆了」的主出口。它用点赞**中位数**作为常态基线，显示每条作品的倍数。
**倍数低 ≠ 内容差，先看新鲜度** —— 发布不足 24 小时的笔记点赞远未发酵完成。
不受发酵期影响的指标是**藏赞比**和**评论意向密度**，优先看这两个。

### 4. 结构拆解（选题参考，非洗稿）

```bash
$PY scripts/monitor.py matrix <user_id> [N]   # 单账号结构参数
$PY scripts/monitor.py opportunities          # 跨账号选题机会汇总
```

## 关于「模仿」——安全边界（重要）

`matrix` / `opportunities` 是本技能唯一涉及「借鉴」的出口，**设计上刻意做了限制**：

**✅ 只抽结构参数**：选题角度、钩子句式类型、信息密度（字数/段数/均段长）、
互动引导方式、标签数量、发布时段、人称与场景词分布。

**🚫 不输出、也不得复用**：
- 原文表述（`_structure_of` 刻意不返回 content 全文）
- 标题的具体措辞
- 封面图

理由不是保守，是**风险量级不同**：

1. **改写式洗稿是最高危动作。** 平台原创度判定看语义指纹，不是字面重合度。换词保结构照样命中。
2. **小红书图文，封面是一等公民。** 封面图复用（图床指纹 + 肉眼可辨）比文案复用更容易被抓。
3. **照抄等于放弃护城河。** 目标账号的通用选题谁都能抄，但「科特迪瓦门店实战 + 真实客户案例」
   是抄不走的。模仿一个没有门店的人，是拿稀缺换通用。

**正确用法**：`opportunities` 挑出「中位倍数高且样本 ≥3」的钩子类型 → 当作**选题角度**输入给
`xhs-note-writer` → 用它自己的一手素材填充。产出物是**结构模板 + 选题机会清单**，不是仿写稿。

## 数据库

SQLite：`data/monitor.db`（已在仓库 `.gitignore` 覆盖 `*.db`）

| 表 | 说明 |
|---|---|
| `accounts` | 监控名单。`baseline_likes`=点赞中位数（判爆款的参照系）、`baselined`=是否已建基线 |
| `snapshots` | 每次巡查的 粉丝/关注/获赞 快照。`ok=0` 表示该次抓取失败 |
| `notes` | 笔记。`seen_count`/`notified`/`suppressed` 三列构成判新状态机 |
| `comments` | 抓到的评论文本，按 `(note_id, content)` 去重 |
| `runs` | 每次巡查的起止与汇总 |

`suppressed` 取值：`baseline`（基线轮）/ `deep_position`（防线 0 压制）/
`stale_publish_time`（防线 2 撤回）。**排查误报/漏报先看这一列的分布。**

## 已知坑

1. **xsec_token 会过期。** `detail` 命令独立补抓时若失败，会自动回主页刷新 token。
   但如果笔记已被作者删除或移出可见范围，刷新也会失败 —— 这是预期行为，不是 bug。
2. **登录态会过期。** 脚本会明确报 `NOT_LOGGED_IN` 并打印恢复命令。长时间未用需重新扫码，
   这是本方案唯一需要人工介入的硬伤。
3. **巡查频率不要过高。** 每次巡查开一次浏览器，高频轮询无意义且加速风控。
   每天 1 次足够，对齐抖音那边 04:00 的节奏。
4. **详情写入必须用 COALESCE 保护。** 抓取失败会返回 None 字段，直接覆盖会把已知值抹成 NULL
   （抖音坑 10）。`write_detail` 已实现，改代码时保留。
5. **`_dig` 按 key 名搜索而非按路径取。** 小红书 `__INITIAL_STATE__` 结构随版本变动，
   硬编码路径很容易整条抓空。新增字段提取时沿用这个模式。
6. **小红书改版频繁。** 每次改动 `cdp_publish.py` 的选择器后，先用 `probe` 确认取数没坏，
   再跑 `run`。

## 自检

```bash
$PY scripts/_selftest.py
```

72 项离线断言，覆盖数值解析、链接解析、详情解析、三防线判新、COALESCE 保护、
基线计算、报告渲染、钩子分类。**不碰浏览器，改完逻辑必跑。**
