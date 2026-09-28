---
name: douyin-comment-analyzer
description: >
  抖音评论区高频话题分析工具。给定抖音号（unique_id 或主页链接）， 自动定位账号 → 提取所有视频评论 → 分词 → 统计高频话题 →
  输出分析报告。 支持登录态持久化（扫码一次即可），适合反复分析不同账号。
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
│   ├── common.py       # 公共模块（解码/登录/评论提取/过滤，2026-09 抽取）
│   │                   #   ⚠️ 单一来源：CONTROL_WORDS / PLAYER_WORDS / TOPIC_STOPWORDS /
│   │                   #      is_ui_residue()，分析类脚本一律从这里 import，勿各写一份
│   ├── extract.py     # 评论提取脚本（账号维度，登录态持久化）
│   ├── keyword_extract.py  # 评论提取脚本（关键词/话题维度）
│   ├── account_analyzer.py # 链接入口脚本（丢链接→账号分析，2026-09 新增）
│   ├── login_probe.py  # 登录态探针（几秒返回 LOGIN_OK / LOGIN_EXPIRED）
│   ├── gen_daily_run.py     # 由 s_watchlist.json 生成当日串行抓取脚本（2026-09-17 新增）
│   ├── demand_density.py    # 跨账号需求密度（账号分级核心指标，全量口径）
│   ├── daily_digest.py      # 当日摘要（第7步汇报，10 数据集口径，2026-09-17 新增）
│   ├── build_archive_docs.py # 归档文档生成器（4类文档，2026-09 新增）
│   └── analyze.py     # 话题分析脚本（分词+统计+报告）
└── profiles/
    └── README.md      # Chrome profile 存放说明
```

## 使用方式

### 第一步：安装依赖

```bash
/Users/goterra/.workbuddy/binaries/python/envs/default/bin/pip install DrissionPage jieba wordcloud requests
```

### 第二步：提取评论（账号维度）

```bash
/Users/goterra/.workbuddy/binaries/python/envs/default/bin/python3 \
  scripts/extract.py <douyin_unique_id> [max_videos]
```

- `max_videos` 可选，默认分析全部视频
- 首次运行会弹出浏览器，**需要扫码登录抖音**（只需一次，登录态保存在 `~/.workbuddy/douyin_chrome_profile`）
- 提取结果保存在 `~/.workbuddy/douyin_analysis/<unique_id>/`

### 第二步b：提取评论（关键词/话题维度）

```bash
/Users/goterra/.workbuddy/binaries/python/envs/default/bin/python3 \
  scripts/keyword_extract.py <关键词> [max_videos] [--minimized]
```

- 通过搜索页（视频 tab）拿视频列表，逐个视频提取评论
- 结果保存在 `~/.workbuddy/douyin_analysis/keyword_<关键词>/`，可直接用 analyze.py keyword_<关键词> 分析
- `--minimized`：窗口最小化运行（定时任务用，避免打扰）。**不要用 --headless，会被抖音风控拿不到搜索结果**
- 登录态过期时用默认模式（正常窗口）跑一次扫码即可

### 第二步c：丢链接分析账号（手机端推荐入口）

```bash
/Users/goterra/.workbuddy/binaries/python/envs/default/bin/python3 \
  scripts/account_analyzer.py "<抖音链接或分享口令>" [max_videos] [--minimized]
```

- 输入支持：`v.douyin.com` 短链 / 主页链接 / 视频链接 / **App 分享口令整段文本**（自动正则提取链接）
- 自动跟随重定向 → 识别主页或视频 → 视频则提取作者 sec_uid → 跳转主页
- 提取账号信息：**昵称、签名、粉丝数、获赞数、作品数** + 视频列表（滚动加载）
- 逐个视频抓评论，输出到 `~/.workbuddy/douyin_analysis/account_<昵称>/`
- 结果兼容 analyze.py：`analyze.py account_<昵称>` 出话题报告
- 典型场景：手机端看到讲出海非洲/非洲创业的号 → 丢链接过来 → 直接出账号分析

### 第三步：生成归档文档（监控体系数据层）
```bash
/Users/goterra/.workbuddy/binaries/python/envs/default/bin/python3 \
  scripts/build_archive_docs.py
```

扫描 `~/.workbuddy/douyin_analysis/` 下所有分析结果，自动生成 4 类归档文档到 `_archive/`：
1. **【监控对象】账号清单.md** — 所有分析过的账号总表（粉丝/获赞/作品/评论量）
2. **【时序】<日期>_关键词<kw>.md** — 每日关键词监控结果（高频词+需求信号）
3. **【档案】<账号名>.md** — 单账号分析文档（内容定位+评论话题+需求信号）
4. **【汇报】跨账号趋势汇总.md** — **提炼汇报**（高热度话题/内容类型占比/高频问题/高价值需求信号）

这些文档通过 IMA MCP（create_media → COS → add_knowledge）上传到「媒体账号监控」知识库（单库+命名分区）。每次账号分析或关键词监控完成后运行本脚本并归档，保持数据层最新。

### 每日监控流水线（2026-09-17 定稿，自动化任务标准流程）

S 级名单唯一维护点是 `_archive/s_watchlist.json`——**扩充账号只改这个文件**，
驱动脚本每日由 `gen_daily_run.py` 现场生成，不要在自动化任务里硬编码账号 URL。

```bash
PY=/Users/goterra/.workbuddy/binaries/python/envs/default/bin/python3
cd /Users/goterra/.workbuddy/skills/douyin-comment-analyzer

# 0. 登录态探针（几秒返回；可选，仅用于判断本轮能否跑）
#    ⚠️ 登录态检查点已前移到 04:00 巡查任务（2026-09-18 从 09:00 前移）。
#       本任务（09:00）遇 LOGIN_EXPIRED 只记录「登录态失效，需人工扫码续期」并跳过，
#       不弹扫码、不自行续期（避免与其它任务互踢登录态、也避免用户收到重复提醒）。
#       扫码提示的唯一职责在 04:00 任务——它是当天第一个用浏览器的任务，能最早报警。
$PY scripts/login_probe.py

# 1. 由 s_watchlist.json 生成当日串行驱动脚本 → _runtime/run_daily_<date>.sh
$PY scripts/gen_daily_run.py 2026-09-17

# 2. 串行抓取（约 36 分钟，9 账号×10 视频 + 关键词×10）
#    ⚠️ 必须串行！共享 Chrome profile 并行会串号（2026-09-04 踩坑）
nohup zsh _runtime/run_daily_<date>.sh > /dev/null 2>&1 &

# 3. 话题分析（每个数据集一次）
$PY scripts/analyze.py account_<昵称>
$PY scripts/analyze.py keyword_非洲出海

# 4. 需求密度（账号分级，全量口径）
$PY scripts/demand_density.py | tee _runtime/demand_density_<date>.txt

# 5. 归档文档（4 类）
$PY scripts/build_archive_docs.py

# 6. 当日摘要（第 7 步汇报，10 数据集口径）
$PY scripts/daily_digest.py <date> > _runtime/digest_<date>.md
```

**两套口径别混用**：
- `demand_density.py` = **全量口径**（所有 `account_*`），用于 S/A/B 分级复核；
- `daily_digest.py` = **当日 10 数据集口径**（9 个 S 账号 + 关键词），用于当日舆情与选题。
  后者分母小、密度更敏感，两者数值不可直接对比。

**`all_comments.json` 语义**：每个 `account_<昵称>/` 目录里，`all_comments.json` 是
**最近一次运行的 10 个视频**去重后的评论文本数组（不是历史累积）；
`video_*_comments.json` 才是跨天累积的明细，按日期取用时要留意。

### 串号防护与并发隔离（2026-09-22 新增，重要）

**背景**：2026-09-22 09:00 任务与 04:00 巡查任务被同一时刻唤醒（机器休眠后补跑），
两者共用 `~/.workbuddy/douyin_chrome_profile` 与调试端口 9222，DrissionPage 附着到
**同一个 Chrome 实例**，导致：① 首轮 10 个数据集只成功 6 个（`PageDisconnectedError`）；
② 补抓时页面被对方抢走，把**别的账号**的评论写进了 `account_<对方账号>/` 目录（静默串号）。
→ 结论：**三套抖音任务必须严格串行**；一旦发现并发，先做隔离再抓。

**`account_analyzer.py` 已内建三重防护**（默认生效，无需额外参数）：

| 防护 | 触发点 | 行为 |
|---|---|---|
| 主页 URL 校验 | 打开主页后 | `page.url` 不含目标 sec_uid（被重定向到推荐流/别的账号）→ `exit 2`，不写文件 |
| `--expect "<昵称>"` | 解析出昵称后 | 昵称与期望不符 → `exit 2`，不写文件（`gen_daily_run.py` 已自动带上） |
| 视频页 URL 校验 | 每个视频抓取前后各一次 | 页面被抢走 → 丢弃该视频；有效视频 < max(5, N/2) → `exit 3` |

**崩溃容错**：抖音视频页偶发 renderer 崩溃（`PageDisconnectedError`），
旧版会整轮作废。现改为**保留已抓到的视频并聚合出结果**，`meta.json` 增加
`videos_done` / `partial` / `crash` 字段；`partial=true` 的轮次应视为降级数据。

**并发隔离通道**（当必须与其它任务同时跑时）：
```bash
# 复制一份独立 profile（排除缓存，约 130MB），用独立调试端口，与共享实例互不干扰
rsync -a --delete --exclude 'Default/Cache/' --exclude 'Default/Code Cache/' \
  --exclude 'Default/GPUCache/' --exclude 'Default/Service Worker/' \
  ~/.workbuddy/douyin_chrome_profile/ ~/.workbuddy/douyin_chrome_profile_iso/
rm -f ~/.workbuddy/douyin_chrome_profile_iso/Singleton*

export DOUYIN_PROFILE_DIR=~/.workbuddy/douyin_chrome_profile_iso
export DOUYIN_DEBUG_PORT=9333
$PY scripts/account_analyzer.py "<url>" 10 --minimized --expect "<昵称>"
```
⚠️ 隔离 profile 的登录态是**复制时的快照**，会独立过期；只在并发冲突时临时用，
日常仍走共享 profile。用完后不要删（下次冲突可直接复用，但要先重新 rsync 刷新 cookie）。

### 账号分级标准（出海服务核心，2026-09-02 定）

**核心定位**：监控对象 = 瞄准「想出海非洲的生意人」（去非洲创业/开厂/建仓库搞分销/建设经销网络）的账号，评论区是目标客户池。

**分级规则**（三维度：出海服务属性 × 需求密度 × 需求绝对量）：

| 级别 | 判定条件 |
|------|---------|
| S 出海服务核心 | ①账号本身是出海服务方（考察/招商/物流/海外仓/顾问）②评论区需求密度 ≥13% ③需求绝对量 ≥50 条 |
| A 服务腰部/实操王者 | 出海服务类但密度未达标，或非服务类但数据顶级（密度/需求双高） |
| B 垂直小号/低需求 | 体量太小（<10万粉），或需求密度 <10% |

> **⚠️ 两套判定不要混（2026-09-28 澄清）**：
> 上表是**准入标准**——用于决定一个账号能否被写进 `s_watchlist.json`（名单由人工确认、变动很少）。
> 日常【监控对象】账号清单.md 里的 **S 标记 = 名单成员身份**，不随当日密度波动：名单成员即使某天密度跌到 3%，清单里仍标 S。
> 每日真正浮动的是**「双线达标」判定**（密度 ≥13% **且** 需求 ≥50 条），由 `demand_density.py` / `daily_digest.py` 计算，用于观察名单成员的当日状态，**不等于**把账号踢出名单。要调整名单请直接改 `s_watchlist.json`。

**关键反例（防止重蹈覆辙）**：
- 粉丝量大 ≠ 评论含金量高（楠哥 81.2万粉密度仅 7.1%，泛叙事评论区是感慨不是需求）
- 服务属性 ≠ S 级（张馨月属地化培训，服务类但密度仅 7.2%，是邹先华的一半）
- 数据顶级 ≠ 服务类（非洲高箭密度 16.9%/需求 102 条，但属目的地实操非服务类，按标准降 A）

**需求密度统计方法**：对 `account_*/all_comments.json` 逐条评论做噪音过滤（页脚/播放器/时间戳词表）后用五类需求正则（投资创业/货源采购/意向咨询/合作商务/渠道获客）匹配，命中任意类的去重评论数 ÷ 过滤后总评论数 × 100%。五类正则见跨账号需求密度分析脚本（2026-09-02）。

### 第二步d：账号发现 + 项目库维护（商贸城/中国城/产业园，2026-09-02 新增）

面向「记录中国人做的非洲商贸城/中国城项目分别在哪些国家」的资产盘点需求，
产出**账号 × 项目 × 国家**三元组清单，而非评论分析。

```bash
# 1. 搜索发现账号（16 个内置关键词，搜索抖音用户 tab，约 11 分钟）
python3 scripts/discover_accounts.py --min-fans 0
#   指定关键词：python3 scripts/discover_accounts.py "安哥拉世纪城,非洲商贸城"
#   输出：~/.workbuddy/douyin_analysis/_discovery/accounts_<日期>.json/.md

# 3. 公开资料交叉核验 + 去重（核心：抖音只是线索，必须交叉验证）
python3 scripts/reconcile_projects.py
#   输出：_discovery/projects_verified.json/.md（五段式）
#   + _archive/【核验】非洲中资园区_公开资料去重主清单_<日期>.md

# 4. 回填：把核验命中的账号写回公开资料基准库，标记补搜状态
python3 scripts/backfill_parks.py
#   写 _archive/africa_parks_reference.json 的 douyin_accounts / douyin_found / douyin_found_date
#   并把 official+tenant 属性账号追加进 _archive/parks_watchlist.json（按 sec_uid 去重）
#   ⚠️ 名单互斥（2026-09-18）：同一 sec_uid 不得同时在 parks_watchlist.json 与
#      s_watchlist.json 里。前者由 13:00 抓、后者由 09:00 抓，重复会让同一账号的评论
#      被抓两遍且写进同一个 douyin_analysis/account_<昵称>/ 目录互相覆盖。冲突时保留在
#      parks_watchlist.json。规则全文见 douyin-account-monitor/SKILL.md「三套监控名单的边界与互斥」
#   回填后必须重跑 reconcile_projects.py，让状态机更新（已补搜园区不再进种子）
```

**核验环节的两个坑（2026-09-03 修复，勿回退）：**

8. **归档文件名日期不能硬编码**。`reconcile_projects.py` 曾写死 `主清单_2026-09-02.md`，
   导致第二天的结果直接覆盖前一天的归档。必须用 `date.today().isoformat()` 动态生成。
9. **跨实体营销话术不能强制映射到某个园区**。`MANUAL_MAP` 曾把「非洲最大商贸城」
   「非洲人流最旺的商贸城」「最成熟的华人投资商贸城」「香港商贸城」「新时代商贸中心」
   全部指向「安哥拉世纪城」——但这些是**多个园区都在用的自夸语**，结果非洲旭日集团旗下
   （中国城/迪高路/新时代）的账号全被错并进世纪城，世纪城虚增到 20 号。
   现由 `GENERIC_PHRASE` 集合兜底，不进 MANUAL_MAP，落回**账号级归属判定**
   （`competing_park()` + `reassign_misattributed()`：昵称/签名说了算，串号账号自动迁回真园区）。

**评论提取的坑（2026-09-03 修复，影响所有历史报告）：**

10. **视频自身简介会被当成评论抓进来**。`extract_comments_from_page()` 从 RENDER_DATA 抓
    `"text"`/`"content"` 字段，但视频简介也存在同名字段（`"desc"`）。实测**污染率 28-31%**，
    园区官方号尤甚（爱发带 #话题标签的招商长文案），导致话题高频词被账号自述主导，
    「产城融合」「全产业链」这类招商话术被误当真实用户声音。
    已修复：先取视频 `desc` 建排除集，再过滤 ≥3 个 `#` 的营销文案。污染率 31% → 10%。
    ⚠️ **2026-09-03 之前所有评论报告的高频词需谨慎采信**，重抓才准。

**判断「反向补搜有没有种子」的正确方法**：看 `projects_verified.json` 的
`not_found_on_douyin` 数组长度。为 0 表示泛搜已命中所有公开园区，**跳过补搜直接做回填**
（否则会白白再跑 11 分钟）。基准库 18 个园区全部标了 `douyin_found` 后就不再产生种子。

**关键坑（2026-09-02 验证，务必遵守）：**
1. 搜索必须用 `?type=user`（用户 tab）。视频 tab 的 RENDER_DATA 无作者数据，DOM 里只能捞到 1 个 `/user/` 链接。
2. 用户卡片容器是 `<li>`，不是 `<a>` 的父元素。筛选同时含「抖音号」和「粉丝」的 li，再从内部 `a[href*="/user/MS4w"]` 取 sec_uid。
3. 卡片文本结构：`昵称 \n 关注 \n 抖音号:<id><粉丝数>获赞<获赞数>粉丝 \n 签名`
   —— **粉丝数夹在「抖音号」和「获赞」之间**，是个反直觉的位置。
4. **粉丝数只能认带单位的（万/亿/w/W）**。抖音号本身可能以数字结尾（如 `ft058113903`），
   纯数字尾数无法与粉丝数区分，会把 58113903 当成 5811 万粉。同时加 5000 万上限校验。
5. **过滤条件必须是「非洲国家词」AND，不能是 OR**。用 OR 会混入 2/3 的国内账号
   （苏州工业园区、镇雄亿联商贸城、华硕商城等）。
6. 项目名抽取正则会抓到「海外仓」「工业园」「市场」等无前缀的通用词 → 必须排除纯后缀。
   还会连前缀动词一起抓（「就职于非洲安哥拉世纪城」）→ 需清洗开头噪音词。
7. `run_js` 在该页面返回 None，改用 DrissionPage 原生 `li.raw_text` + `li.ele('css:a[href...]')`。

**数据规模参考（2026-09-02 首跑）：** 16 关键词 → 429 账号去重 → 292 命中过滤 →
合并画像库 → 129 个「非洲+项目」账号 → 128 个项目 → 覆盖 19 个国家。

### 第三步：分析话题

```bash
/Users/goterra/.workbuddy/binaries/python/envs/default/bin/python3 \
  scripts/analyze.py <unique_id>
```

- 自动读取提取结果，输出高频话题报告
- 报告保存在 `~/.workbuddy/douyin_analysis/<unique_id>/report.md`

## 关键技术细节

### 评论区容器选择器：DrissionPage 必须带 `css:` 前缀 + `eles()`（2026-09-25 根治污染）

污染反复 9 次，**真根因**是选择器写法，不是抖音改版：

| bug | 错误写法 | 后果 | 正确写法 |
|---|---|---|---|
| 语法 | `page('[data-e2e="comment-list"]')` | `page()` 返回**单个元素**不是列表，且裸属性选择器不带 `css:` 前缀 → **恒 0 命中** | `page.eles('css:[data-e2e="comment-list"]')` |
| 语义 | 容器命中但内容是「暂无评论」时仍回落整页 | 抓进「京公网安备11010802050006号」「快乐大本营」「粉丝0」这类页面 chrome | 容器显式声明无评论 → **直接返回空，不回落** |
| 策略 | 回落 `page('tag:body').text` | 右侧推荐流整段进评论，低流量账号**污染率 100%**（赞比亚某号 8 视频真实 0 条却"抓"出 297 条） | 默认**关闭**回落；需旧行为设 `DOUYIN_COMMENT_BODY_FALLBACK=1` |

诊断工具：`scripts/dump_comment_dom.py <video_url>`（dump 整页 HTML + 实测各选择器命中数）。
**判定一条抓取是否可信**：跑完看日志里是不是 `[DOM] 评论区容器命中 N 条（未回落整页）`；
出现「未回落整页」以外的任何回落提示，该批数据不可用于需求分析。

> 2026-09-25 及之前抓取的园区号评论（含 09-24 莱基 7 条 inbound）**均需按此标准复核**：
> 只要当天日志是回落整页，其中"真实 inbound"就可能是推荐流文案。

### 园区官方号评论轮抓：固定 ≥14 天间隔（2026-09-24 验证，2026-09-25 固化）

**不要用「最久未抓」贪心策略，用固定间隔。** 实测：莱基自贸区距上次 **21 天** 时一次挖出
**7 条真实 inbound**（厂房租赁多少钱一平米／想了解厂房租赁／本月下旬去考察厂址／六月中旬去
考察园区／想去办个工厂／怎么合作／租车间请联系我）；而此前 3–7 天一轮反复抓时结论一直是
「园区号＝招商输出、无真实 inbound」。

→ **根因不是没需求，是抓太勤需求没沉淀。** 挑号时按 `parks_watchlist.json` 的
`last_crawled` 升序取，且**只取距今 ≥14 天**的；不足 14 天的宁可少抓，不要凑数。

### 回填基准库：必须 canonical 精确匹配（2026-09-24 踩坑，禁止子串）

`'湖南' in canonical` 这类子串匹配会误改无关条目（当时误改「科吉湖南经济特区」
「乌干达二手工程机械产业园」两条）。回填脚本一律用
`EXACT = {canonical: (value, note)}` 字典 + `p['canonical'] == c` 判定，
并在写入后打印全部改动条目人工复核。

### 反向补搜的「管道衰减」判据（第 6 次复现，2026-09-25）

同一轮里**稳定词**（如 `安哥拉世纪城`，历史上必返回数十个账号）也返回 0 → 判定
**管道衰减**，本轮**不下任何「抖音无号」结论**，`douyin_found` 保持空串，下轮重搜。
只有当稳定词健康返回、而目标专名 0 命中时，才能标 `douyin_found=no`。

### IMA 归档通道（2026-09-27 更新：两条路都堵着）

1. MCP 通道：`~/.workbuddy/mcp.json` = `{"mcpServers": {}}` → `mcp__ima-mcp__*` 不存在；
2. 直连 OpenAPI：`~/.workbuddy/skills/ima-skills/ima_api.cjs` + `~/.config/ima/{client_id,api_key}`
   实测 `node ima_api.cjs openapi/list_docs` → **stdout 0 字节、rc=0**（空响应，非报错）。

→ **结论（2026-09-24 起修正）**：OpenAPI 路径在本机**不可达（沙箱拦截）**，不是单纯的凭证过期。
   依据：9/23 曾返回 `{"code":200002,"msg":"skill auth failed"}`，但 9/24、9/26、9/27 连续三天
   变为「空响应 rc=0」，且 `ima.qq.com` 首页 curl 可达 200（非全站网络问题）。
→ 处置：**需 Mark 连接 ima-mcp 连接器**；直连通道不再作为可行备选。

#### 连接器不可用时的每日兜底：生成补传清单（必须做）

归档上传失败不影响当日分析结果，但**必须**落盘补传清单，供通道恢复后连同历史积压一并补跑。

```bash
# 1) 先跑归档与清单脚本（会刷新 IMA_UPLOAD_QUEUE.md）
python3 scripts/build_archive_docs.py          # 输出形如 "  - 【档案】xxx.md (988 B)"
python3 scripts/ima_archive_upload.py          # 刷新 _archive/IMA_UPLOAD_QUEUE.md

# 2) 再生成当日补传清单：取 build_archive_docs 当日输出的文件清单 + IMA_UPLOAD_QUEUE.md
#    落盘 _archive/IMA_补传清单_<日期>_抖音监控.md
```

⚠️ 两个易错点（2026-09-27 踩过）：
- **范围**：清单只列**当日新生成/刷新**的文件（≈92 个 + 队列文件 = 93），
  **不要** glob 整个 `_archive/*.md`（会把 24 个历史【时序】、23 份历史补传清单全卷进来，数量翻倍）；
- **解析**：解析 `build_archive_docs` 输出时正则不要先 `.strip()` 再去匹配带前导缩进的模式
  （`^\s*-\s+(.+?)\s+\((\d+) B\)$` 直接匹配原始行即可）。

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

### 2026-09 验证的关键坑（重要）

- **RENDER_DATA 已从 base64 改为 URL 编码**（`%7B%22app%22...`），解码必须用 `urllib.parse.unquote`，base64 会报 Incorrect padding（common.py 已双兼容）
- **登录态判断**：不要用页面是否含"扫码"字样判断（会误判），要解析 RENDER_DATA 的 `app.user.isLogin` 字段
- **headless 会被风控**：无头模式搜索页拿不到视频列表，必须用有头 + `--start-minimized`
- **搜索页视频链接**是 `//www.douyin.com/video/<id>` 相对协议形式，用正则 `/video/(\d{15,})` 提取（RENDER_DATA 里不含搜索结果的 aweme_id）
- **登录态有效期约 2-7 天**，过期后需重新扫码（脚本会检测 isLogin 并提示）
- **噪音过滤**：DOM 抓取会把"下载抖音""N小时前·XX省""展开N条回复""播放中""3s 后播放""进入全屏"当评论，common.py 的 is_comment_text 已过滤这些
- **账号昵称/统计信息在 DOM，不在 RENDER_DATA**：RENDER_DATA 里的 nickname 是页面其他作者；账号名从 `<title>`（"xxx的抖音 - 抖音"）提取，粉丝/获赞/作品数从 body 文本提取（标签与数值可能同行"粉丝21.0万"或分行"粉丝\n21.0万"）
- **搜索页偶发空壳**：页面只有导航+页脚（HTML <100KB），是异步加载失败，keyword_extract.py 会用页面长度检测并自动重开重试
- **词表噪音需定期维护（2026-09-16 踩坑）**：`build_archive_docs.py::top_words` 的 `stop` 词表会随抖音前端改版失效。09-16 发现【汇报】话题 Top20 被「快乐大本营/京公网安备/剪映专业版/标清/狗杂/天前/万获赞/下一章/内容由/加载中/暂时没有更多/小时前/结语」等**页面残留 + 视频简介 + 时间戳**词占据，掩盖真实话题。已补约 50 词。**若话题榜出现明显无意义词，先怀疑停用词表过期**，补词后重跑 `build_archive_docs.py` 即可（无需重抓）
- **✅ 语料混入「视频简介/字幕」原文（2026-09-16 观察 → 2026-09-25 根治）**：`all_comments.json` 里曾出现整段视频简介或 ASR 字幕（如「东非坦桑尼亚中国产业园」21 条跨 6 账号、「结语」「大江非洲咨询将于」）。根因不是抖音改版，而是评论区容器选择器写法错误导致**每天每号都回落整页 body**（详见下方「评论区容器选择器」条）。2026-09-25 修复后回落默认关闭，2026-09-26 首次全量验证：10 数据集语料里账号名残留 22%→**0.7%**、章节字幕残留 **0**、UI 残留 **0**。**该口径偏差已消除**
- **UI 残留会以「独立单条评论」形式混入（2026-09-17 踩坑，已修）**：新版页面把**播放器倒计时**「1s 后播放下一个视频」「0s 后播放」按秒数变体混进评论区（旧词表只挡了固定 `3s 后播放`，全部漏网），加上「短剧/通知/消息/狗杂/30天内」等控件标签和「用户7048135123713」占位昵称。后果：当日话题 Top10 被这些词整榜占据，真实话题（加纳/人民币/外贸）被挤出。**修法**：`common.py` 新增 `COUNTDOWN_RE`（正则匹配任意秒数倒计时）、`PLACEHOLDER_USER_RE`、`is_ui_residue()` 统一判定，并在 `is_comment_text` 里调用；`TOPIC_STOPWORDS` 补入这批词。**判定经验**：任何「2-6 字中文词」若在话题榜里排进 Top10 但你读不出业务含义，先查它是不是 UI 标签。
- **停用词表必须单一来源（2026-09-17 收敛）**：`build_archive_docs.py` 与 `daily_digest.py` 曾各维护一份停用词表，导致修了一处另一处仍污染（09-17 摘要与 09-17 汇报话题榜不一致即由此产生）。现已统一到 `common.py::TOPIC_STOPWORDS`，**两个脚本都从 common 导入，禁止再内联复制**。切词前还要 `is_ui_residue()` 预过滤 + 丢弃 `#`≥2 的标签文案，否则长文案会被切成「计划/后播放下一个」这类碎片混入词频榜。
- **提问样本要卡「以问号结尾」（2026-09-17）**：抽取「评论区问得最多的问题」时，若只按「怎么/能不能/多少钱」匹配，会把**视频简介与标题**（如「实地探访非洲家具一条街，来非洲开家具厂能不能赚钱？」）当成用户提问。加「以 ？/? 结尾 + 不含 # + 长度 6-60」三重条件后才是真实提问。
- **🔴 语料 22% 是「账号名行」而非评论（2026-09-18 定量确认 + 已修话题榜）**：新版页面 DOM 通道会把**右侧推荐流的账号名**当独立条目抓进来，形态是「数字前缀 + 昵称」——前缀其实是粉丝数/获赞数/序号，如 `4853叶镇平出海贸易`、`2.5万勇闯非洲的家敏（机票签证旅游商务接待)`、`5414梨花带雨`。当日 3368 条语料里 **730 条（21.7%）是账号名行，真评论只有 2616 条（77.7%）**。
  - **⚠️ 分工（极易踩错）**：账号名行**不是评论**（不该进话题榜、不该进密度分母），但**是「同行线索」的唯一来源**——`daily_digest.py::PREFIX_PAT` 就是剥它的数字前缀。所以**话题统计要排除，同行线索提取绝不能排除**。`common.py` 只提供判定器，由消费方决定。
  - **已修**：`common.py` 新增 `is_account_mention()`（带「吗/怎么/我/你/多少」等真评论标记守卫，实测 746 条命中里只放过 3 条真提问）、`is_chapter_residue()`（章节要点/字幕的工程参数式长句，如「沙坪河段…：水深6.3米，宽度80米，最小弯曲半径360米」）、`is_topic_noise()`（三合一）；`build_archive_docs.py::top_words` 与 `daily_digest.py::top_topics` 均已接入。
  - **✅ 已随 2026-09-25 抓取层修复一并解决**：上述「1.28 倍低估」推算的前提是「账号名行占分母 22%」，而 22% 这个比例本身就是**整页回落**造成的。容器选择器修好后（2026-09-25），2026-09-26 实测账号名残留仅 0.7%（且均为 `14亿人民`/`1000人民币` 这类被正则误判的**真评论**），`demand_density.py` 分母已基本纯净，**无需再做 1.28 倍修正**。
  - **🔴 但历史口径断裂（2026-09-26 定论）**：9/3–9/25 的评论数与密度**全部基于整页 body 文本**（含简介/推荐流/页面 chrome），与 2026-09-26 起的纯评论区口径**不可直接环比**。旧口径下评论量约为新口径的 2–4 倍，密度绝对值因账号而异（义乌升、佳哥/大江腰斩）。**任何跨 9/26 的密度对比都必须标注「口径变更」，历史 S/A/B 分级结论需按新口径重估。**
- **平台注入内容会跨数据集逐字重复（2026-09-18 新增 `cross_dataset_duplicates()`）**：推荐流视频标题/推广卡在**每个账号页面逐字一致**，实例「以为库里南已经无敌了，结果后面还有个更猛的……」在 9 个 S 级账号页面全部出现，被切词后贡献 45 次词频、直接霸榜 Top10。**判定：在 ≥4 个数据集里逐字完全相同的字符串 = 平台注入，不是用户评论**（真评论再热也不可能在 9 个账号下逐字一致）。已接入 `top_words` / `top_topics`，当日仅命中 42 条、其中多为已在停用词表内的控件文案，误杀风险极低。
- **标签文案门槛由 `#`≥2 收紧到 `#`≥1（2026-09-18）**：只带 1 个话题标签的条目几乎全是**视频标题/账号自述**（如「投资300万开的养生馆，到底要不要卖房缓解经济压力！ #邹先华」），不是评论。当日此类 74 条，已从话题榜剔除。

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

## 反向补搜：短专名撞词规则（2026-09-27 实战教训）

反向补搜用**园区短专名做关键词，撞词率接近 100%**，必须遵守：

1. **禁止直接用 2 字短专名单独搜索**。实测：「越美」命中 20+ 条全为国内撞词（安徽望江绣花厂、个人号）；「中策」命中 40+ 条全为中策橡胶轮胎/电缆/装饰/职业学校。
2. **必须叠加三重词**：`专名 + 国家词 + 运营方名/产业词`，例如用「尼日利亚奥贡州工业园」而不是「中策」。
3. **归属判定三重门**：nickname 与 signature **同时**含园区专名 + 国家词才计命中；任一仅有专名、仅有国家词、或指向国内同名实体（轮胎/电缆/装饰/职校）一律判噪。
4. **地理相关 ≠ 园区账号**：如「日月同辉」自述在尼日利亚卡拉巴做汽修，属个人号且粉丝 <1000，不入库、不计入命中。
5. **优先选生僻专名**做关键词；生僻专名也搜不到 + 三重词轮次也搜不到，才可判 `douyin_found=no`。

## 园区官方号需求采集：账号分层建议（2026-09-27）

- 需求密度 ≥15% 的园区号（实测：安哥拉中国城 16.7%、莱基自贸区 7.3% 为第一梯队）→ 提速至 3 天一轮
- 连续 2 轮密度 <2%（中乌辽沈、ZCCZ）→ 降为 14 天一轮或移出序列
- 10 条视频评论区容器全空、仅回收个位数平台噪声（尼日利亚华非产业园）→ 账号实质停更，**移出需求采集序列**，仅保留数据巡查
