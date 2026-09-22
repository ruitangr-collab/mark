---
name: share-html-conversation-recovery
description: 从 WorkBuddy 分享链接（www.workbuddy.link/p/<nodeId> 或 *.workbuddy.link/p/<nodeId>）完整恢复对话原文，用于"找回这段对话""继续上次那个任务""这段对话讲到哪了"。分享页是 JS 渲染的空壳，直接抓 HTML 或 WebFetch 都拿不到正文，必须走静态资源直取。当用户给出 workbuddy.link 分享链接并要求找回/恢复/继续其中的对话时触发。
version: 1.0.0
agent_created: true
allowed-tools: Bash, Read, Write
---

# 从分享链接恢复 WorkBuddy 对话原文

## 为什么不能直接抓

`https://www.workbuddy.link/p/<nodeId>` 返回的只是一个 3-4KB 的 bootstrap 空壳，正文由前端 JS 异步加载。**WebFetch 和 `curl` 直接抓页面都只能拿到空壳**，必须走下面的静态资源直取路径。

## 三步直取

### Step 1：抓 HTML，从 bootstrap 里取 nodeId 与资源地址

```bash
curl -sL "https://www.workbuddy.link/p/<nodeId>" -o /tmp/share.html
grep -o 'window.__PUBLISH_BOOTSTRAP__=.*' /tmp/share.html
```

HTML 末尾的 `<script>` 里有 `window.__PUBLISH_BOOTSTRAP__`，形如：

```json
{"nodeId":"XXX","artifact":{"artifacts":[{"path":"conversation-data.json"},{"path":"index.html"},{"path":"janus.data.json"}],"url":"https://workbuddy-space-static.codebuddy.work/page/XXX/0/","creator":"..."},"userInfo":{}}
```

关键字段：
- `artifact.url` —— 静态资源根目录（含结尾的 `/0/` 版本号）
- `artifact.artifacts[].path` —— 该页面包含的资源文件

### Step 2：直接下载 conversation-data.json

```bash
curl -sL "https://workbuddy-space-static.codebuddy.work/page/<nodeId>/0/conversation-data.json" -o /tmp/conv.json
```

拿到的是完整结构化对话，通常几十到几百 KB。

### Step 3：解析

JSON 顶层结构：

| 字段 | 含义 |
|---|---|
| `version` | 数据格式版本 |
| `name` | 对话标题（如"巴图 与 WorkBuddy 的对话"） |
| `assistantName` | 助手名 |
| `messages[]` | 消息数组 |
| `artifactMap` | 产出的文件映射 |

每条 message：

| 字段 | 含义 |
|---|---|
| `messageType` | `user` / `assistant` |
| `createTime` | 毫秒时间戳 |
| `conversationId` | 会话 ID |
| `content[]` | 内容块数组 |

content 块类型：

| type | 说明 | 导出建议 |
|---|---|---|
| `text` | **对外可见的正文**，就是用户和助手实际看到的回复 | 必须导出 |
| `reasoning` | 思考过程，含大量有价值的判断依据、被否决的方案、风险分析 | 强烈建议导出 |
| `tool-call` | 工具调用及结果 | 按需；导出时截断以免过长 |

导出脚本：

```bash
node -e "
const fs=require('fs');
const d=JSON.parse(fs.readFileSync('/tmp/conv.json','utf8'));
const dt=t=>new Date(t).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});
let out=[];
for(const m of d.messages){
  out.push('===== '+m.messageType.toUpperCase()+' | '+dt(m.createTime)+' =====');
  for(const c of (m.content||[])){
    if(c.type==='text') out.push('\n[TEXT]\n'+c.text);
    else if(c.type==='reasoning') out.push('\n[REASONING]\n'+c.text);
    else if(c.type==='tool-call') out.push('\n[TOOL] '+(c.toolName||c.name||'')+' :: '+JSON.stringify(c.input||c.args||{}).slice(0,500));
  }
  out.push('');
}
fs.writeFileSync('/tmp/conv_dump.txt', out.join('\n'));
"
```

## 恢复之后该做什么

拿到原文只是第一步。用户要的通常是**接着干**，所以：

1. **先核对上轮的交付物是否还在**——`ls` 一下上轮提到的输出路径，别假设它存在。
2. **核对仓库/工作区状态**——上轮可能留了一堆未提交的改动（`git status`），这些往往就是"未完成的下一步"。
3. **把上轮的判断当成假设去验证，别当成结论沿用**。上轮说"第一批无环境依赖"，实际扫一遍才发现有硬编码本机路径。凡是要对外发布/交付的东西，重新扫一遍。
4. **找出真正的断点**：读最后一轮 assistant 的 `[REASONING]`，里面通常明确写了"还差什么""等你确认什么"。

## 坑

- `curl` 带上 `-L`，分享域可能有跳转。
- 版本号 `/0/` 来自 `artifact.url`，不要自己编；同一 nodeId 重新发布可能变成 `/1/`。
- 消息数可能远少于预期——分享页可能是**在某个中间时刻**生成的快照，不代表对话就此结束。核对 `messages.length` 和最后一条的时间戳。
- `tool-call` 块里工具名可能是空字段，导出时要容错（试 `toolName` / `name`）。
