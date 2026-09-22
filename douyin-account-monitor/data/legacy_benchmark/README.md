# legacy_benchmark — 对标矩阵存档迁移数据（2026-06 项目，2026-09-04 导入）

> 来源：`/Users/goterra/Downloads/对标矩阵项目存档_2026-06-16/`（Windows 机器 Phase 2 Step 1c 归档）
> 用途：douyin-account-monitor 拓号引擎的存量候选池 + 排除基准 + 人工标注样本
> 审查清单：`/Users/goterra/.workbuddy/douyin_analysis/对标矩阵存档_复用资料审查清单_2026-09-04.md`

## ⚠️ 分级口径决策（Mark 2026-09-04）

- **保留 6 月口径**：内容相关性 + 粉丝量（本目录内所有分类标签均按此口径理解）
- **09-02 定的 S 级标准（出海服务类 ∩ 需求密度 ≥13%）对本批历史数据先暂停**——不回灌、不重分类
- 即：本目录的"优质账号"标签 ≠ 现行监控库 S/A 级，两套体系不混用

## 文件清单

| 文件 | 内容 | 规模 |
|---|---|---|
| `author_profiles_cache.json` | 5,584 位非洲商业/财经抖音作者 × 37 字段完整画像（sec_uid 为键） | 21MB |
| `business_data/` | 144 关键词 × 17,308 条视频原始数据（23 国 × 经商/创业/市场/投资/贸易 + 泛非 24 词） | 11MB / 144 JSON |
| `business_keywords.json` + `country_keywords.json` | 关键词矩阵设计：泛非宽/窄 + 单国 T1(7国)/T2(11国) 分层与配额 | — |
| `初筛排除名单_v8重建_2026-06-12.csv/.json` | 567 个新闻号/媒体号/机构号排除记录（uid/昵称/tier/category/reason/签名） | 8 版迭代成果 |
| `非洲抖音头部账号清单_v6-手工整理.xlsx` | 人工确认过的头部账号分类结果（6 月口径） | — |

## 配套迁移（不在本目录）

- `~/.workbuddy/skills/douyin-report-search/` — 6 月采集技能整包已还原（关键词搜索采集 + 作者画像批量拉取）；**过期 session 已剔除，首次使用需重新扫码登录**；脚本出自 Windows，Mac 上跑通前需验证
- `douyin-account-monitor/scripts/semantic_classify_v10.py` — 语义分类器参考实现（身份→领域→非洲关联→角色四层加权决策，媒体号识别正则可直接复用）；**尚未接入 discover_services.py，接入前先与现行 STRONG_WORDS/EXCLUDE_WORDS 逻辑做对照测试**

## 已知限制

- 数据截至 2026-06-11，粉丝/作品数为当时快照，仅作候选池与比对基准，不作实时依据
- `raw_data/00_raw/`（72MB 中间快照）未迁移，仍留在 Downloads 存档内
