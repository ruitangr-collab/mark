---
name: wechat-article-harvester
description: 从自己运营的微信公众号批量采集图文，统一进 IMA「map data」知识库（IMA 界面图文都显示，已验证），再由 ima-library-mirror 镜像到资料库。层1用 agent-browser 驱动已登录 MP 后台「已发表内容」抓全历史 URL；层2用 import_urls 批量入库 IMA（文字+图都进 IMA）；层3触发 ima-library-mirror 镜像资料库。幂等、可断点续跑。
version: 2.0.0
visibility: public
---

# wechat-article-harvester

自己运营的微信公众号图文 → IMA「map data」知识库 + 资料库 的批量采集与双管流水线。

## 架构（三层）

```
层1 URL采集      agent-browser 驱动已登录 MP 后台「已发表内容」→ 翻页提取全部文章 URL → urls.txt
        │
层2 入库 IMA      import_urls 批量(≤10/批) 进「map data」知识库(kb_id=7498636917212532)
        │          folder_id = "" (该库无子文件夹, 直接进库根; 见下文「IMA map data」)
        │          → IMA 自动抓全文+图(界面显示图, 已验证)
        │
层3 镜像资料库    ima-library-mirror: IMA「map data」(主本) → 资料库(只读镜像)
```

- **单一真本**：IMA「map data」知识库。资料库只是只读镜像，编辑只在 IMA。
- **幂等**：`urls.txt`（去重）+ `harvest_map.json`（url→media_id 映射），重跑只补未导入的，不重复建。
- **目标库/文件夹**：所有采集内容统一进 IMA 的 `map data` 知识库（`kb_id=7498636917212532`）。该库当前无子文件夹，`folder_id=""` 进库根；若你之后在 map data 里建子文件夹，把目标 `folder_id` 告诉我即可精准归位。

## ✅ 实测结论（2026-08-27，用真实号文章校准）

| 环节 | 结果 |
|---|---|
| `import_urls` 吃公众号链接 | ✅ **文字全抓**（标题/作者/时间/正文）；图在 **IMA 界面自渲染显示**（用户已确认 IMA 里能看图；`fetch_media_content` API 不含 `<img>` 但 UI 显示） |
| `create_media` 外部直传 COS | ❌ **死路**：返回 COS 临时密钥，但 qcloud_cos / boto3 直传均 `InvalidAccessKeyId`（两次不同密钥一致）。IMA 不允许外部直传文件，仅开放服务端 `import_urls` |
| agent-browser 启动并到达 mp.weixin.qq.com | ✅ 能启动、能打开页面 |
| 自动复用登录态（本沙箱） | ❌ 不可行：① headless shell 读不到 macOS Keychain 的 cookie 解密密钥 → 复制 Profile 2 的 Cookies 后 `document.cookie=0`、页面「登录超时」；② 真实 Chrome 在本沙箱 `sandbox initialization failed` + network/GPU 崩溃，起不来；③ `--auto-connect` 需用户 Chrome 以远程调试端口运行（默认不开） |

**结论（据此定稿）**：
- 内容入库走 `import_urls`（文字+图都在 IMA 显示）→ 单一通道，最省事。
- 自动登录复用在本沙箱被环境封死；层1 的浏览器采集需在你**本机（有显示器+你的 Chrome）**跑，登录态用下方三选一解决。
- `fetch_article.py`（本地渲染存 HTML 再提取图文）保留为**兜底**：仅当 import_urls 图质量不足时，由 agent-browser 渲染后存 HTML 本地化图文。当前 IMA 显示图，通常不需要。

## 关于「找 XHS 浏览器抓取 skill 改进」
- 本机 **没有**专门的「小红书浏览器抓取」skill。`xhs-batch-pipeline` / `xhs-note-writer` 是**产出**笔记的，不是抓取。
- 真正的浏览器自动化能力在 **`agent-browser`**（原生二进制，支持 `--profile` 复用登录态、`--auto-connect` 接管运行中的 Chrome、`auth save` 存会话）+ `stealth-browser`（四层反检测/持久会话模式，思路同源）。
- 本 skill 即「把 agent-browser 的持久会话+抓取模式改进用于公众号」的落地：登录态复用用 agent-browser 的机制，抓「已发表内容」列表，再 import_urls 进 IMA。

## ⚠️ 关键现实
1. **自有号优势**：你提供的是**自己的号**，可登录 mp 后台。全历史列表走「后台登录 → 已发表内容」最稳、合规、全量。
2. **IMA 显示图已确认**：用户实测 IMA 里那篇测试文章（标题含「非洲营商环境图谱」）能正常显示图。所以 import_urls 足够，无需外部传图。
3. **资料库写操作需 token**：`create_doc.py` 客户端模式由资料库 skill 自动获取（`connect_open_platform`）。层3 在你本机跑。
4. **登录态敏感**：后台 cookie / 扫码登录别在聊天里明文发。

## 登录方案（层1 前置，三选一）
> 本沙箱无法自动复用登录（见上）。以下方案在你**本机**执行。

- **A. 一次性有头登录（最稳，推荐）**：
  ```bash
  agent-browser --headed --profile ~/.wechat-harvest open "https://mp.weixin.qq.com/"
  # 你在弹出的浏览器里扫码/账号登录
  agent-browser --profile ~/.wechat-harvest auth save wechat-mp
  ```
  之后无头复用：`agent-browser --profile ~/.wechat-harvest ...`（会话由 agent-browser 实时捕获，绕过 Keychain）。
- **B. 你开着带远程调试的 Chrome（精确复用登录，免重登）**：
  ```bash
  # 你先关掉普通 Chrome，用调试端口启动（加载你的真实 Profile 2，登录态在）：
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    --remote-debugging-port=9222 \
    --user-data-dir="$HOME/Library/Application Support/Google/Chrome/Profile 2" \
    --no-sandbox
  # 然后二货接管：
  agent-browser --auto-connect open "https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_list&action=list"
  ```
  > 真实 Chrome 在本沙箱因 sandbox init 失败起不来；**在你本机正常**。沙箱里加 `--no-sandbox` 也救不了 network/GPU，故只能本机跑。
- **C. 你直接粘贴 URL 清单（最省事，跳过层1浏览器）**：`harvest.py add <urls...>` 批量导入。适合不想开浏览器的场景。

## 层1：URL 采集（全历史）

### 一键采集脚本 collect_urls.py（推荐）
本 skill 自带 `collect_urls.py`，自动翻页/滚动抽全部文章 URL，**无需手动抄链接**。流程：
1. 一次性安装 + 登录（方案 A）：
   ```bash
   npm install -g agent-browser && agent-browser install
   agent-browser --headed --profile ~/.wechat-harvest open "https://mp.weixin.qq.com/"
   # 弹窗扫码/账号登录后，另开终端：
   agent-browser --profile ~/.wechat-harvest auth save wechat-mp
   ```
2. 跑采集：`python3 collect_urls.py` → 产出 `urls.txt`（去重，含全部 `mp.weixin.qq.com/s?__biz=` 文章链接；连续两页无新增或到 `WB_MAX_PAGES` 默认 200 即停）。
3. 把 `urls.txt` 贴给二货跑层2+层3；或本地 `python3 harvest.py add $(cat urls.txt)` 入清单后再交由二货。
> 脚本机制：`get html`+正则抽 URL（只收 `mp.weixin.qq.com/s?__biz=`）、`find text <候选> click` 翻页、`scroll` 兜底无限滚动。微信无公开历史 API，登录态必须你本机提供，**沙箱跑不了层1**。

### 手动采集（备用）
选登录方案 A/B 后：
1. 打开「已发表内容」：`https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_list&action=list&lang=zh_CN&count=10`
2. `agent-browser snapshot -i` 定位文章列表与「下一页」；循环翻页提取每条 `mp.weixin.qq.com/s?__biz=...` 链接 + 标题。
3. `python3 harvest.py add <urls...>` 去重入清单。
> 后台列表是 JS 渲染+翻页，纯 curl 拿不到，必须浏览器（方案 A/B）或你手动复制（方案 C）。

## 层2：入库 IMA（import_urls 批处理）
对 `harvest.py batch` 每批（≤10）调：
```
工具: mcp__ima-mcp__import_urls
参数: {"knowledge_base_id":"7498636917212532","folder_id":"","urls":["<url1>",...(≤10)]}
```
每批后 `python3 harvest.py record <url> <media_id>` 写回映射，直到 `harvest.py status` 显示「待导入: 0」。

## IMA map data（目标知识库，已定位 2026-08-27）
- **"map data" 是一个独立知识库（KB），不是某个库里的子文件夹**。id = `7498636917212532`（type 1001，个人知识库）。
- 定位方法（实测）：`get_knowledge_base_list` 用 `params:[{type:"KBT_MINE_KB", limit:50}]` 列全部"我的"库，第一个即 `id=7498636917212532, name="map data"`。
- 该库当前 `folder_number: 0`（无子文件夹），故采集时 `folder_id=""` 直接进库根。
- 查子文件夹如需：`get_knowledge_list` 用 `filters=[{filter_type:"MEDIA_TYPE_FILTER_TYPE", media_type_filter:{media_type:["FOLDER"]}}]`；注意 `current_path[].folder_number` 计数不可靠，以 FOLDER 过滤返回为准。
- ⚠️ 关于用户给的 `view="folders", name_keyword="map data", scope="all"` 查法：本环境 `get_knowledge_list` 的 schema **不支持** `view`/`name_keyword`/`scope`（会被拒为 additional properties），且返回结构是 `knowledge_list`（非 `source_docs`）。最终按真实 schema 用 `get_knowledge_base_list` 枚举出该 KB。结论：map data 归位用 `knowledge_base_id=7498636917212532` + `folder_id=""`。

## 层3：镜像资料库
入库 IMA 完成后触发 `ima-library-mirror`（已实测）：目标库 `7498636917212532`（map data），幂等。缺省落「我的文档」。

> 只想要"进 IMA"可跳层3；要"两个云同时有"就跑层3。

## 已知坑（必看，踩过）
- **agent-browser daemon 锁泄漏**：崩溃后 `~/.agent-browser/default.{pid,sock,stream,engine,version}` 与 profile 目录 `Singleton{Lock,Cookie,Socket}` 不清理，导致「daemon already running」且连到空/旧 profile。每次重跑前：
  ```bash
  pkill -9 -f agent-browser-darwin; pkill -9 -f chrome-headless-shell; pkill -9 -f "Google"
  rm -f ~/.agent-browser/default.* ; rm -f <profile>/Singleton*
  ```
  ⚠️ 残留 Chromium 进程 **comm 名是 "Google"**（命令行不含 "Google" 字样），pkill 要用二进制路径或 `"Google"`。**切勿杀用户正在用的 Chrome**（其 user-data-dir 为 `~/Library/Application Support/Google/Chrome`）。
- **复制 Profile 2 时登录态文件必须在 `<profile>/Default/` 下**（Cookies / Local Storage / Session Storage / Web Data / Preferences …），平铺在根目录 agent-browser 不识别。
- **headless 读不到 Keychain cookie**：复制 Cookies 文件 ≠ 能登录（headless shell 解不出密钥）。要用方案 A（实时捕获会话）或 B（真实 Chrome+调试端口）。
- **资料库写需客户端 token**：层3 在你本机跑。

## 本地产物
| 文件 | 作用 |
|---|---|
| `urls.txt` | 待导入 URL 清单（去重，支持 `#` 注释） |
| `harvest_map.json` | `{kb_id, kb_name, folder_id, imported:{url:{media_id,at}}}` 映射，幂等依据 |
| `fetch_article.py` | 兜底：agent-browser 渲染后存 HTML → 提取正文+下载 mmbiz 图（仅当 import_urls 图质量不足时用） |

## 绝不做
- 不回写 IMA 原文、不删资料库节点、不碰 Obsidian。
- 不伪造 URL：URL 只能来自你粘贴或后台实抓，不猜测。
- 不绕过微信风控做高频爬：触发验证码即停，交人工。
