# 文档分类体系与领域推断规则

## 业务领域定义

本分类体系定义了知识索引中使用的业务领域划分规则，用于将文档、对话记录、记忆条目归类到正确的领域下。

### 一级领域列表

| 领域编码 | 领域名称 | 说明 |
|----------|----------|------|
| `realestate` | 非洲房地产运营 | 涉及非洲地区的房产投资、开发、出租、价格分析、土地交易等 |
| `marketing` | 内容营销 | 涉及抖音/TikTok 短视频、内容策略、脚本撰写、海报设计、社交媒体运营等 |
| `business` | 企业运营 | 涉及公司注册、证照、合规、投资、融资、会议、合作等企业行政事务 |
| `techdev` | 技术开发 | 涉及代码编写、数据库、自动化测试、Web 开发、工具开发等 |
| `appstore` | 应用商店上架 | 涉及 App Store / Google Play 应用提交、审核、上架等 |
| `finance` | 金融数据 | 涉及股票、基金、外汇、宏观经济的查询与分析 |
| `aigc` | AI 内容生成 | 涉及 AI 绘画、AI 写作、Prompt 工程、AIGC 工具使用等 |
| `uncategorized` | 未分类 | 无法归入以上任何领域的条目 |

### 二级分类（部分领域展开）

#### realestate（非洲房地产运营）下的二级分类

| 二级编码 | 名称 | 典型文件 |
|----------|------|----------|
| `realestate.project` | 项目资料 | 天鹅湖公寓、凤凰城等项目文件夹 |
| `realestate.analysis` | 市场分析 | 地块价格地图、市场分析报告、国别对比 |
| `realestate.data` | 数据文件 | CSV 价格数据、物业数据、位置数据 |
| `realestate.operation` | 运营管理 | 出租管理、客户资料、合同模板 |

#### marketing（内容营销）下的二级分类

| 二级编码 | 名称 | 典型文件 |
|----------|------|----------|
| `marketing.strategy` | 策略文档 | 出海策略 JSON、品牌定位文档 |
| `marketing.script` | 脚本 | 分镜脚本、口播稿 |
| `marketing.design` | 设计素材 | 海报（中/英/法）、插画、图片 |

## 领域推断规则

### 基于文件名/目录名的关键词匹配

| 关键词（任一命中） | 归属领域 |
|--------------------|----------|
| 非洲、阿比让、abidjan、天鹅湖、凤凰城、公寓、地块、地产、properties、price_adjust、location、nigeria、kenya、象牙海岸、科特迪瓦 | `realestate` |
| 抖音、douyin、tiktok、脚本、海报、poster、内容、营销、短视频、content、brand、strategy、出海 | `marketing` |
| 公司、营业执照、DUNS、邓白氏、投资、会议纪要、备案、承诺书、SACSILOGIC | `business` |
| sql、csv、html、代码、test、project、superset、automated_testing、ai-agent、设计 | `techdev` |
| app store、google play | `appstore` |
| 股、基金、ETF、行情、财报、宏观 | `finance` |
| AIGC、aigc、prompt、插画、ChatGPT Image、AI 生成 | `aigc` |

### 基于文件扩展名的类型推断

| 扩展名 | 文件类型 | 通常归属领域（若无其他关键词） |
|--------|----------|------|
| `.pdf` | PDF 文档 | `business` |
| `.csv` `.xlsx` | 数据表格 | `realestate.data` 或 `finance` |
| `.sql` | 数据库脚本 | `techdev` |
| `.html` `.htm` | 网页/报告 | `realestate.analysis` 或 `techdev` |
| `.json` | JSON 数据 | 视内容而定（策略→`marketing`，数据→`techdev`） |
| `.png` `.jpg` `.jpeg` | 图片 | `marketing.design` 或 `aigc` |
| `.zip` `.dmg` | 压缩包/安装包 | `techdev` |
| `.pen` | 雷达图/脑图 | 视文件名而定 |
| `.eml` | 邮件 | `business` |

### 推断优先级

当文件名同时命中多个领域的关键词时，按以下优先级判定：

1. **特定领域关键词**优先于通用关键词（如「天鹅湖」>「数据」）
2. **目录名**优先于文件名（如文件夹名含「非洲」则整个文件夹归入该领域）
3. **数量更多的关键词**优先于数量更少的（命中 3 个关键词 > 命中 1 个）

## 索引条目格式规范

### 历史对话条目格式

```
- [{YYYY-MM-DD}] {主题摘要} — {状态标签} | 关键实体：{实体1}、{实体2}
```

状态标签取值：`已完成`、`进行中`、`未完成`

### 文档条目格式

```
- `{相对路径}` — {类型}：{推断说明}
```

### 关键决策条目格式

```
- [{YYYY-MM-DD}] {决策内容}（来源：{对话ID 或 文件路径}）
```
