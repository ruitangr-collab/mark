# WorkBuddy Skills 仓库

由 WorkBuddy 助手「二货 🐶」统一管理的个人技能集合，使用 git 版本控制。

## 技能清单

### dontbesilent 商业工具箱 (dbs*)

| 目录 | 名称 | 说明 |
| --- | --- | --- |
| `dbs` | dbs | dontbesilent 商业工具箱主入口。根据你的问题自动路由到最合适的诊断工具。 触发方式：/dbs、/商业、「帮我看看」 Main entry point… |
| `dbs-action` | dbs-action | dontbesilent 执行力诊断。用阿德勒心理学框架诊断你「知道该做什么但就是不做」的真正原因。 触发方式：/dbs-action、/action、「我知道… |
| `dbs-agent-migration` | dbs-agent-migration | Agent 工作台迁移。把任意项目整理成 Claude Code / Codex / Grok 三端一致、可长期维护的 Agent 工作台：审计规则文件、识别真… |
| `dbs-ai-check` | dbs-ai-check | dontbesilent AI 写作特征识别。扫描文案中的 AI 生成痕迹，输出检测报告。默认只诊断不改。 触发方式：/dbs-ai-check、/AI检测、「… |
| `dbs-benchmark` | dbs-benchmark | dontbesilent 对标分析。用五重过滤法帮你找到值得模仿的对标，排除一切关于「我」的噪音。 触发方式：/dbs-benchmark、/对标、「帮我找对标… |
| `dbs-chatroom` | dbs-chatroom | 定向聊天室：根据话题推荐或接受用户指定的专家，模拟多角色对话。触发方式：/dbs-chatroom、/定向聊天室、「定向聊天室」 |
| `dbs-chatroom-austrian` | dbs-chatroom-austrian | 哈耶克 × 米塞斯 × Claude 三人对话。奥派经济学视角的多角色讨论。 触发方式：/dbs-chatroom-austrian、/chatroom-aus… |
| `dbs-content` | dbs-content | dontbesilent 内容创作诊断。选题通过后，诊断怎么把这个选题做成好内容。 触发方式：/dbs-content、/内容诊断、「这个内容怎么做」「帮我看看… |
| `dbs-content-system` | dbs-content-system | dontbesilent 内容结构化系统。把本地大量文稿、推文、选题、案例和课程稿搭成一个可持续生长的内容结构化工程：先审计内容规模与边界，再建立新工程、复制素… |
| `dbs-decision` | dbs-decision | dontbesilent 个人决策系统。把任何一个需要长期跟踪的领域（业务、关系、健康、职业、学习、投资……）做成一个本地知识工程：四层结构、来源标签、写完不改… |
| `dbs-deconstruct` | dbs-deconstruct | dontbesilent 概念拆解。用维特根斯坦 + 奥派经济学的方法，把模糊的商业概念拆到原子级别。 触发方式：/dbs-deconstruct、/拆概念、「… |
| `dbs-diagnosis` | dbs-diagnosis | dontbesilent 商业模式诊断。两种模式：问诊（消解你的问题）和体检（拆解你的商业模式）。 触发方式：/dbs-diagnosis、/问诊、「帮我看看商… |
| `dbs-goal` | dbs-goal | dontbesilent 目标清晰化。用维特根斯坦的语言哲学把模糊的目标审计成可检查的交付物。 触发方式：/dbs-goal、/目标、「帮我搞清楚目标」「我想做… |
| `dbs-good-question` | dbs-good-question | dontbesilent 好问题生成器。把模糊问题改写成 Agent 可推理、可批评、可验证的问题说明书，并判断它能被自动化解决到什么程度。 触发方式：/dbs… |
| `dbs-hook` | dbs-hook | dontbesilent 短视频开头优化。诊断开头问题 + 生成优化方案。 触发方式：/dbs-hook、/hook、「帮我优化开头」「开头怎么写」 Short… |
| `dbs-learning` | dbs-learning | dontbesilent 交互式学习。把一个课题拆成连续学习文章，根据用户在上一篇中的反馈调整下一篇的深度、角度和节奏。 触发方式：/dbs-learning、… |
| `dbs-report` | dbs-report | 把多次 dbs-save 攒下来的诊断状态合并成一份可交付的 markdown 报告。 触发方式：/dbs-report、/出报告、「打包」「整理一份」「给合伙… |
| `dbs-restore` | dbs-restore | 把上次诊断的状态拉出来，接着用。配合 dbs-save 使用。 触发方式：/dbs-restore、/续上、「接着上次」「之前的结论」「上次诊断到哪了」 Res… |
| `dbs-save` | dbs-save | 把当前诊断的关键状态存到本地，下次回来可以接着用。 触发方式：/dbs-save、/存档、「保存这次诊断」「记下来」「这个结论留着」 Save the curr… |
| `dbs-slowisfast` | dbs-slowisfast | dontbesilent 慢就是快。帮创业者找到看起来更慢但长期更快的方法，用摩擦建造资产。 触发方式：/dbs-slowisfast、/慢就是快、「有没有更慢… |
| `dbs-xhs-title` | dbs-xhs-title | 小红书标题公式工具。从 75 个验证过的爆款公式中，帮你挑对的、用对的、理解为什么用这个。 触发方式：/dbs-xhs-title、/小红书标题、「帮我起个小红… |

### 抖音相关

| 目录 | 名称 | 说明 |
| --- | --- | --- |
| `douyin-comment-analyzer` | douyin-comment-analyzer | 抖音评论区高频话题分析工具。给定抖音号（unique_id 或主页链接）， 自动定位账号 → 提取所有视频评论 → 分词 → 统计高频话题 → 输出分析报告。 … |
| `douyin-live-monitor` | douyin-live-monitor | 抖音直播间实时监控 skill。给定主播直播间 URL 或 room_id， 自动连接抖音 WebSocket 弹幕流，实时抓取弹幕、进场/离场、礼物、点赞、关… |
| `douyin-video-script` | douyin-video-script | 基于策略 JSON 生成抖音短视频分镜脚本。当用户提供了出海/品牌策略文档（JSON 格式），并要求撰写具体视频脚本时触发。自动完成：读取策略文档 → 匹配选题… |

### 小红书相关

| 目录 | 名称 | 说明 |
| --- | --- | --- |
| `xhs-batch-pipeline` | xhs-batch-pipeline | 小红书内容批量生产管线。从策略日历中自动取选题、补充真实背景、撰写图文笔记、交付草稿、等待用户确认后入库。 触发方式：/xhs-batch、"继续写"、"批量出… |
| `xhs-note-writer` | xhs-note-writer | 基于用户提供的关键信息和选题，撰写去AI味的小红书图文笔记。自动完成：收集信息 → 确定钩子类型 → 撰写笔记正文 → 去AI味处理 → 设计封面方案 → 输出… |

### IMA 知识库

| 目录 | 名称 | 说明 |
| --- | --- | --- |
| `ima-skills` | ima-skills | ima笔记与知识库管理（读取、写入、检索）；统一 IMA OpenAPI 技能，支持 notes 与 knowledge-base 两个模块。 |

### 营销工具箱

| 目录 | 名称 | 说明 |
| --- | --- | --- |
| `marketing-skills` | marketing-skills | TL;DR: 23 marketing playbooks (CRO, SEO, copy, analytics, experiments, pricing, … |

### 其它 / 通用

| 目录 | 名称 | 说明 |
| --- | --- | --- |
| `json-schema-generator` | json-schema-generator | 根据用户的自然语言描述，自动生成符合 JSON Schema Draft 2020-12 规范的完整 Schema 文件。适用于 API 接口设计、前端表单校验… |
| `sanduan-script` | sanduan-script | 三段式结构脚本创作。基于"不卖避险，卖抢滩；不卖下注，卖先机"的核心理念， 用轻咨询三段式结构撰写出海非洲/商业变现类文案。 触发方式：/三段式、/轻咨询结构、… |
| `stealth-browser` | stealth-browser | Ultimate stealth browser automation with anti-detection, Cloudflare bypass, CAPT… |
| `workspace-knowledge-indexer` | workspace-knowledge-indexer | 工作空间知识索引器，将历史对话、本地文档、业务知识结构化为可检索知识索引。 支持构建索引（全量扫描）和智能检索（召回相关上下文）两种模式。 当用户提到之前、上次… |

## 远程安装 / 调用

```bash
# 1) 克隆到本机技能目录（或合并进已有的 ~/.workbuddy/skills）
git clone <REMOTE_URL> ~/skills-tmp
cp -r ~/skills-tmp/* ~/.workbuddy/skills/   # 合并到用户级技能目录

# 2) 或作为独立仓库，按需软链
ln -s ~/skills-tmp/<skill-name> ~/.workbuddy/skills/<skill-name>
```

> 说明：用户级技能位于 `~/.workbuddy/skills/`，项目级技能位于
> `<workspace>/.workbuddy/skills/`。复制或链接后，WorkBuddy 会自动加载。

_共 32 个技能。生成于 git 管理脚本。_
