---
name: ima-library-mirror
description: 把 IMA 知识库单向镜像进 WorkBuddy 资料库。以 IMA 云为主本（source of truth），把指定知识库的笔记/Markdown/文件，按幂等方式同步为资料库在线文档。用于统一管理「历史文件」——一次写入 IMA，资料库自动有只读镜像。范围仅 IMA→资料库，不回写、不删、不碰 Obsidian。
version: 1.0.0
visibility: public
---

# ima-library-mirror

IMA 知识库（主本）→ WorkBuddy 资料库（镜像）单向同步。

## 架构（已实测可用）

```
IMA 知识库 (主本, 云)
   │  mcp__ima-mcp__*  (只读拉取)
   ▼
二货 (桥接 + 幂等映射)
   │  create_doc.py (资料库 skill, 写入)
   ▼
资料库 在线文档 (镜像, 只读)
```

- **主本**：IMA。所有增改在 IMA 发生。
- **镜像**：资料库。只进不出，绝不回写 IMA、绝不删资料库节点。
- **桥接**：二货。用本地 JSON 记录 `media_id → 资料库 node_id` 映射，保证幂等（重跑只补新增，不重复建）。

## ⚠️ 关键现实（动手前必须知道）

1. **不要用本地 `ima-skills/ima_api.cjs`**。该脚本的接口路径实测返回 **HTTP 404**（子模块文档 `notes/`、`knowledge-base/` 也缺失），当前不可用。本 skill 一律走 **`ima-mcp` 连接器工具**（已连、实测可用）读取 IMA。
2. **Obsidian 不在本 skill 范围内**。你已决定范围=IMA↔资料库单向。Obsidian 是本地 md，如需后续接入，单独再写。
3. **资料库写操作需要 token**：客户端模式下由资料库 skill 自动获取（`connect_open_platform`），沙箱模式走 auth-proxy。镜像落点 space 由你指定，缺省落「我的文档」。

## 读取侧（IMA，已抓真实 schema）

工具前缀 `mcp__ima-mcp__`，只读、安全。

| 目的 | 工具 | 关键参数 |
|---|---|---|
| 列我的知识库 | `get_knowledge_base_list` | `params:[{limit:50, type:"KBT_MINE_KB"}]` → `results.knowledge_base_list[]`：`id`, `basic_info.name`, `knowledge_total_size` |
| 列某库条目 | `get_knowledge_list` | `{knowledge_base_id, limit:50, cursor:""}` → 翻页直到 `is_end=true`；条目：`media_id`, `title`, `media_type`(11=笔记/7=MD/…), `can_fetch_content`, `introduction` |
| 取条目全文 | `fetch_media_content` | `{media_id}` → 返回 Markdown 全文（仅 `can_fetch_content=true` 时调） |

条目字段速记（来自 `小红书内容选题` 实测）：
- `media_id`：唯一键，形如 `note_xxx_xxx` / `markdown_xxx_xxx`。**用它做幂等 key。**
- `media_type=7`(MD)：`introduction` 常常已是全文；`can_fetch_content=true` 时优先 `fetch_media_content` 取完整版。
- `media_type=11`(笔记)：`introduction` 只是简介，必须 `fetch_media_content` 取正文。

## 写入侧（资料库）

用资料库 skill 的 `doc/create_doc.py`，按 Markdown 创建在线文档：

```
python3 <资料库skill>/doc/create_doc.py --title "<标题>" --content-file /tmp/<media_id>.md [--space-id <SPACE>] [--parent-id <PID>]
```

- `--space-id` 缺省 → 落「我的文档」默认位置。
- 成功末两列统计：`KS_DOC_CREATE\t<nodeId>\t<kind>\t<url>\t<failed>\t<fatal>`。取 `<nodeId>` 写回映射。
- `failed>0` 或 `fatal>0` → 文档已建但内容可能不全，必须提示用户核对。

## 映射文件

落在本仓 `ima_library_map.json`（首次运行时建立），结构：

```json
{
  "kb_id": "<知识库ID>",
  "kb_name": "<知识库名>",
  "space_id": "<资料库space，空=我的文档>",
  "last_run": "ISO8601",
  "items": {
    "<media_id>": { "node_id": "<资料库节点ID>", "title": "<标题>", "synced_at": "ISO8601" }
  }
}
```

用随附 `sync_map.py` 管理（纯本地，可测）：
- `python3 sync_map.py status` → 显示已同步/未同步数
- `python3 sync_map.py lookup <media_id>` → 查 node_id
- `python3 sync_map.py record <media_id> <node_id> <title>` → 记录一条

## 同步流程（每次执行）

1. **确认目标**（首次必须问用户）：`kb_id`（哪个 IMA 知识库=历史文件）、`space_id`（镜像落哪个资料库空间，可空）。
2. 载入/初始化 `ima_library_map.json`。
3. `get_knowledge_base_list` 校验 `kb_id` 存在；`get_knowledge_list` 翻页拉全量条目。
4. 对每个 `media_id`：
   - 已在 `items` 且 `node_id` 有效 → **跳过**（幂等）。
   - 否则：`can_fetch_content` 为真 → `fetch_media_content` 取全文，写 `/tmp/<media_id>.md`；`create_doc.py` 建资料库文档；`sync_map.py record` 写回映射。
5. 汇总：本次新增 N 篇、跳过 M 篇、失败 K 篇（列出 media_id 供核对）。
6. **绝不做**：回写 IMA、删除资料库节点、修改 IMA 原文。

## 首次运行决策（必须问用户）

- 哪个 IMA 知识库当「历史文件」主本？（候选：`map data` 7498636917212532【微信图文采集目标】/ `小红书内容选题` 7483447085916016 / `GitHub 管理与部署` 7486333052279440 / `微信用户的知识库` 001a075b97006171）
- 镜像落资料库哪个空间？（空=我的文档）
- 是否仅镜像 `media_type=7/11`（笔记与MD），还是含 PDF/WORD 等（需 `fetch_media_content` 支持且转 MD 可能丢版式）？
