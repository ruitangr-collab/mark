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
│   ├── extract.py     # 评论提取脚本（账号维度，登录态持久化）
│   ├── keyword_extract.py  # 评论提取脚本（关键词/话题维度）
│   ├── account_analyzer.py # 链接入口脚本（丢链接→账号分析，2026-09 新增）
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

### 账号分级标准（出海服务核心，2026-09-02 定）

**核心定位**：监控对象 = 瞄准「想出海非洲的生意人」（去非洲创业/开厂/建仓库搞分销/建设经销网络）的账号，评论区是目标客户池。

**分级规则**（三维度：出海服务属性 × 需求密度 × 需求绝对量）：

| 级别 | 判定条件 |
|------|---------|
| S 出海服务核心 | ①账号本身是出海服务方（考察/招商/物流/海外仓/顾问）②评论区需求密度 ≥13% ③需求绝对量 ≥50 条 |
| A 服务腰部/实操王者 | 出海服务类但密度未达标，或非服务类但数据顶级（密度/需求双高） |
| B 垂直小号/低需求 | 体量太小（<10万粉），或需求密度 <10% |

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
