---
name: json-schema-generator
description: 根据用户的自然语言描述，自动生成符合 JSON Schema Draft 2020-12 规范的完整 Schema 文件。适用于 API 接口设计、前端表单校验、数据配置文件定义、跨系统数据交换协定等场景。当用户提出生成 JSON Schema、定义数据结构、设计接口字段、写一个 Schema 校验等需求时触发。支持嵌套对象、数组、枚举、必填字段、格式校验（email、uri、date 等），输出包含 Schema 文件和示例数据。
version: 1.0.0
author: 由 WorkBuddy 自动创建
agent_created: true
---

# JSON Schema 生成器

## 概述

此技能用于将自然语言描述的数据结构需求，自动转换为符合 **JSON Schema Draft 2020-12** 规范的完整 Schema 定义。每次输出包含三部分：JSON Schema 本身、与 Schema 匹配的示例数据（含合法示例与非法示例）、以及逐字段的校验说明表格。

## 适用场景

触发此技能的典型场景包括但不限于：

- **API 接口设计**：定义请求体或响应体的数据结构 Schema，供前后端联调与文档生成使用
- **前端表单校验**：为注册表单、配置页面、数据录入页面生成前端可消费的校验规则
- **配置文件定义**：为项目配置文件（如 app.json、config.yaml 对应的 JSON 格式）输出严谨的 Schema 约束
- **数据交换协定**：在微服务、消息队列、第三方对接等场景中，输出标准的 JSON Schema 作为数据契约

当用户的请求中出现以下关键词或意图时，优先使用此技能：

- 「生成 JSON Schema」「定义数据结构」「设计字段」「写 Schema」「做校验规则」
- 用自然语言描述了一个对象的字段组成（如"一个用户对象，包含…"）

## 工作流

按照以下五个步骤，依次完成从解析到输出的全过程。

### 第一步：解析自然语言描述

从用户的输入中提取与数据结构相关的关键信息，忽略无关的闲聊或背景叙述。

具体操作：

1. 定位用户描述的「主体对象」是什么（例如：用户、订单、文章、配置项）
2. 识别用户给出的字段列表，包括名称、类型暗示、约束说明
3. 若用户描述存在歧义（例如只说「年龄」但未说明类型），按照默认策略推断（见下方「边界情况处理」）
4. 若用户描述中存在不支持的类型或特殊需求，按照对应策略提示用户

### 第二步：识别字段名、类型、约束与嵌套关系

对第一步收集到的信息做结构化整理，建立字段清单。

具体操作：

1. **字段命名**：将中文字段名转换为 camelCase 英文名（例如「用户名」→ `userName`，「电子邮箱」→ `email`），同时保留原始中文字段名写入 `description` 字段
2. **类型推导**：
   - 出现「名称」「描述」「标题」「地址」「内容」→ `string`
   - 出现「年龄」「数量」「个数」「次数」→ `integer`
   - 出现「价格」「金额」「比率」「百分比」「评分」→ `number`
   - 出现「是否」「开关」「真假」→ `boolean`
   - 出现「列表」「标签」「集合」「数组」→ `array`
   - 出现「包含」「对象」「嵌套」→ `object`
3. **约束提取**：
   - 出现「必填」「必须」「不能为空」→ 加入 `required` 数组
   - 出现「最多/最少 N 个字」「长度不超过 N」→ 设置 `minLength` / `maxLength`
   - 出现「范围」「介于」「N 到 M 之间」→ 设置 `minimum` / `maximum`
   - 出现「邮箱」「网址」「日期」「日期时间」「UUID」→ 设置对应的 `format`
   - 出现「只能选」「枚举」「可选值」→ 设置 `enum`
   - 出现「正则」「匹配模式」→ 设置 `pattern`
4. **嵌套关系**：若描述了对象包含子对象或对象数组，识别嵌套层级，创建嵌套 `properties` 或 `items` Schema

### 第三步：生成 JSON Schema（严格符合 Draft 2020-12）

基于第二步整理的字段清单，生成符合 JSON Schema Draft 2020-12 规范的定义。

必须遵循的规则：

1. `$schema` 固定为 `"https://json-schema.org/draft/2020-12/schema"`
2. 根 `type` 为 `"object"`
3. 所有字段定义在 `properties` 下
4. 必填字段收集到 `required` 数组
5. 默认设置 `"additionalProperties": false` 以禁止未定义字段（除非用户明确要求允许额外字段）
6. `$id` 使用示例域名格式（如 `"https://example.com/user.schema.json"`），并在说明中提醒用户替换
7. 每个字段均包含 `description` 字段，保留用户原始语义

格式校验（`format`）支持以下内建值：

- `"email"` — 电子邮箱
- `"uri"` — URI 地址
- `"date"` — 日期（如 `2026-06-15`）
- `"date-time"` — 日期时间（ISO 8601）
- `"ipv4"` / `"ipv6"` — IP 地址
- `"hostname"` — 主机名
- `"uuid"` — UUID
- `"uri-reference"` — URI 引用（相对路径）
- `"regex"` — 正则表达式字符串

详细规范参考见 `references/json-schema-spec.md`。

### 第四步：生成匹配的示例数据

为生成的 Schema 生成至少两条示例数据。

规则：

1. **至少一条合法示例**：严格通过 Schema 所有约束的数据，标为「✅ 合法示例」
2. **至少一条非法示例**：故意违反某条约束的数据，标为「❌ 非法示例」，并注明违反的规则
3. 示例数据使用 JSON 格式，放在代码块中
4. 示例数据中的字段名与 Schema 的 `properties` 键名一致
5. 示例数据应合理且贴近真实场景，避免使用 `"string"`、`123` 等无意义占位值

### 第五步：输出校验说明和使用建议

生成一份 Markdown 表格，逐字段列出校验信息，并附上使用建议。

**校验说明表格**必须包含以下列：

| 字段名 | 中文名 | 类型 | 必填 | 约束条件 | 格式 | 备注 |
|--------|--------|------|------|----------|------|------|

表格后附带使用建议段落，内容包括：

- 如何将此 Schema 集成到项目（代码示例：Ajv 用法 / Python jsonschema 用法）
- 自定义提醒：$id 需要替换为实际域名、additionalProperties 策略可根据需要调整
- 版本兼容性说明

## 输入输出约束

### 输入格式

支持以下两种输入形式：

**形式一：自然语言描述（推荐）**

```
一个用户注册表单，包含以下字段：
- 用户名（必填，2-20 个字符）
- 电子邮箱（必填，需符合邮箱格式）
- 密码（必填，至少 8 位）
- 年龄（选填，1-150 之间的整数）
- 兴趣标签（选填，字符串数组，每个标签 1-20 字）
```

**形式二：简单字段列表**

```
用户名: string, required, minLength=2, maxLength=20
邮箱: string, required, format=email
密码: string, required, minLength=8
```

两种形式均可，技能会自动识别并处理。

### 输出格式

每次输出固定包含以下三个部分，按顺序呈现：

1. **JSON Schema** — 符合 Draft 2020-12 规范的完整 Schema，放入 `json` 代码块
2. **示例数据** — 合法示例与非法示例各至少一条，放入 `json` 代码块并标注说明
3. **校验说明表格** — 逐字段说明的 Markdown 表格，后附使用建议

## 示例模板

### 示例一：用户注册表单

**输入：**

> 一个用户注册表单，包含用户名（必填，2-20 个字符）、电子邮箱（必填，邮箱格式）、密码（必填，至少 8 位）、年龄（选填，1-150 之间的整数）、兴趣标签（选填，字符串数组，每个标签 1-20 字）

**输出：**

**1. JSON Schema**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.com/user-registration.schema.json",
  "title": "用户注册表单",
  "description": "用户注册时提交的数据结构校验 Schema",
  "type": "object",
  "properties": {
    "userName": {
      "type": "string",
      "description": "用户名",
      "minLength": 2,
      "maxLength": 20
    },
    "email": {
      "type": "string",
      "description": "电子邮箱",
      "format": "email"
    },
    "password": {
      "type": "string",
      "description": "密码",
      "minLength": 8
    },
    "age": {
      "type": "integer",
      "description": "年龄",
      "minimum": 1,
      "maximum": 150,
      "default": 18
    },
    "tags": {
      "type": "array",
      "description": "兴趣标签",
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 20
      },
      "maxItems": 10
    }
  },
  "required": ["userName", "email", "password"],
  "additionalProperties": false
}
```

**2. 示例数据**

```json
// ✅ 合法示例 — 所有必填字段完整，约束全部满足
{
  "userName": "张三",
  "email": "zhangsan@example.com",
  "password": "MyP@ssw0rd",
  "age": 28,
  "tags": ["前端开发", "摄影", "骑行"]
}

// ❌ 非法示例 — 用户名太短（少于 2 个字符），缺少 email 字段，密码不满足最小长度
{
  "userName": "张",
  "password": "123",
  "age": 200,
  "tags": ["这是一个超过二十个字的标签内容用来测试约束"]
}
```

**3. 校验说明**

| 字段名 | 中文名 | 类型 | 必填 | 约束条件 | 格式 | 备注 |
|--------|--------|------|------|----------|------|------|
| `userName` | 用户名 | string | 是 | minLength=2, maxLength=20 | — | 不允许纯空格，可结合 pattern 增强 |
| `email` | 电子邮箱 | string | 是 | — | email | 依赖 JSON Schema 校验器内建 email 规则 |
| `password` | 密码 | string | 是 | minLength=8 | — | 实际生产建议增加复杂度 pattern |
| `age` | 年龄 | integer | 否 | minimum=1, maximum=150 | — | 默认值 18 |
| `tags` | 兴趣标签 | array | 否 | maxItems=10, 元素 minLength=1, maxLength=20 | — | 数组元素类型为 string |

**使用建议：**

```javascript
// Node.js 中使用 Ajv 进行校验
import Ajv from 'ajv';
import addFormats from 'ajv-formats';

const ajv = new Ajv({ allErrors: true });
addFormats(ajv);
const validate = ajv.compile(schema);
const valid = validate(data);
if (!valid) console.log(validate.errors);
```

```python
# Python 中使用 jsonschema 库进行校验
import jsonschema

try:
    jsonschema.validate(instance=data, schema=schema)
    print("校验通过")
except jsonschema.ValidationError as e:
    print(f"校验失败: {e.message}")
```

---

### 示例二：结构化文档管理

**输入：**

> 设计一个文档管理对象，包含：
> - 文档名称（必填，1-200 字）
> - 文档版本（必填，格式为 v主版本.次版本，比如 v1.2）
> - 创建时间（必填，ISO 8601 日期时间）
> - 存储地址（必填，合法的 URI）
> - 文档分类（必填，只能选「技术文档」「产品文档」「运维文档」「其他」）
> - 作者信息（选填，嵌套对象，包含姓名和工号两个必填字段，工号为 4-6 位数字）
> - 关联文档（选填，文档 URI 的数组，至少 1 个）

**输出：**

**1. JSON Schema**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.com/document-management.schema.json",
  "title": "结构化文档管理",
  "description": "文档管理系统的核心数据结构校验 Schema",
  "type": "object",
  "properties": {
    "docName": {
      "type": "string",
      "description": "文档名称",
      "minLength": 1,
      "maxLength": 200
    },
    "docVersion": {
      "type": "string",
      "description": "文档版本",
      "pattern": "^v\\d+\\.\\d+$"
    },
    "createdAt": {
      "type": "string",
      "description": "创建时间",
      "format": "date-time"
    },
    "storageUri": {
      "type": "string",
      "description": "存储地址",
      "format": "uri"
    },
    "docCategory": {
      "type": "string",
      "description": "文档分类",
      "enum": ["技术文档", "产品文档", "运维文档", "其他"]
    },
    "author": {
      "type": "object",
      "description": "作者信息",
      "properties": {
        "authorName": {
          "type": "string",
          "description": "作者姓名"
        },
        "employeeId": {
          "type": "string",
          "description": "工号",
          "pattern": "^\\d{4,6}$"
        }
      },
      "required": ["authorName", "employeeId"],
      "additionalProperties": false
    },
    "relatedDocs": {
      "type": "array",
      "description": "关联文档",
      "items": {
        "type": "string",
        "format": "uri"
      },
      "minItems": 1
    }
  },
  "required": ["docName", "docVersion", "createdAt", "storageUri", "docCategory"],
  "additionalProperties": false
}
```

**2. 示例数据**

```json
// ✅ 合法示例 — 含完整的嵌套作者对象与关联文档数组
{
  "docName": "微服务架构设计指南",
  "docVersion": "v2.3",
  "createdAt": "2026-06-15T10:30:00+08:00",
  "storageUri": "https://docs.internal.example.com/arch/msa-guide",
  "docCategory": "技术文档",
  "author": {
    "authorName": "李四",
    "employeeId": "0823"
  },
  "relatedDocs": [
    "https://docs.internal.example.com/ref/api-spec",
    "https://docs.internal.example.com/ref/deploy-guide"
  ]
}

// ❌ 非法示例 — 文档版本格式错误（缺少 v 前缀），分类不在枚举范围内，关联文档为空数组
{
  "docName": "部署手册",
  "docVersion": "1.0",
  "createdAt": "2026-06-15",
  "storageUri": "not-a-valid-uri",
  "docCategory": "财务文档",
  "author": {
    "authorName": "王五",
    "employeeId": "12"
  },
  "relatedDocs": []
}
```

**3. 校验说明**

| 字段名 | 中文名 | 类型 | 必填 | 约束条件 | 格式 | 备注 |
|--------|--------|------|------|----------|------|------|
| `docName` | 文档名称 | string | 是 | minLength=1, maxLength=200 | — | — |
| `docVersion` | 文档版本 | string | 是 | pattern=`^v\d+\.\d+$` | — | 如 v1.0、v2.3 |
| `createdAt` | 创建时间 | string | 是 | — | date-time | ISO 8601 格式 |
| `storageUri` | 存储地址 | string | 是 | — | uri | 完整的 URI 地址 |
| `docCategory` | 文档分类 | string | 是 | enum 四选一 | — | 技术/产品/运维/其他 |
| `author` | 作者信息 | object | 否 | 嵌套对象，含 authorName 和 employeeId | — | 两个子字段均为必填 |
| `relatedDocs` | 关联文档 | array | 否 | minItems=1, 元素需为 uri | — | 关联文档的地址数组 |

**使用建议：**

将 `$id` 替换为项目实际的 Schema 发布地址。`docVersion` 的正则 `^v\d+\.\d+$` 不支持语义化版本中的补丁号，如需支持 `v1.2.3` 格式，修改为 `^v\d+\.\d+(\.\d+)?$`。

---

## 边界情况处理

### 模糊描述的默认处理策略

当用户的描述不够精确时，按照以下默认值处理：

| 模糊情况 | 默认处理 |
|----------|----------|
| 提到了字段名但未说明类型 | 若中文名包含「名/称/标题/说明/地址/内容」→ 默认 `string`；含「数/量/额」→ 默认 `number` |
| 未说明是否必填 | 默认设为**非必填**（不加入 `required` 数组） |
| 未说明数组元素类型 | 默认 `string` |
| 未说明数值范围 | 不设 `minimum` / `maximum`，只保留类型约束 |
| 未说明字符串长度 | 不设 `minLength` / `maxLength`，只保留类型约束 |
| 字段名使用中文 | 保留中文作为 `description`，将属性 key 转换为语义接近的 camelCase 英文名 |

### 不支持的类型如何处理

JSON Schema Draft 2020-12 支持的类型：`string`、`number`、`integer`、`boolean`、`array`、`object`、`null`。

若用户提到了以上七种之外的类型需求（例如「二进制数据」「文件」「富文本 HTML」「Blob」），处理方式：

1. **生成 Schema 时使用 `string` 类型兜底**，并在 `description` 中注明实际类型
2. **在校验说明表格的备注列中明确提示**：「JSON Schema 不直接支持此类型，已用 string 兜底，实际应用中需在业务逻辑层额外校验」
3. **向用户建议替代方案**：例如用 base64 字符串表示二进制、用 string 存储 HTML 内容等

### 超大 Schema 的分段策略

若用户描述的数据结构包含超过 **15 个顶层字段**或超过 **3 层嵌套**，采取分段输出：

1. **先输出根 Schema 框架**：包含所有顶层字段的类型和简要描述，但不展开嵌套对象的 properties
2. **逐个输出嵌套对象 Schema**：每个嵌套对象作为一个独立的 $defs 引用输出
3. **最后输出汇总**：将根 Schema + $defs 合并为完整输出

分段时在每段输出后等待用户确认(`继续`)，再输出下一段，避免单次回复过长。

### 其他边界情况

- **空对象**：用户只说「一个用户对象」但未提供任何字段 → 输出一个仅含 `$schema` 和 `type: "object"` 的空 Schema，并提示用户补充字段
- **循环引用**：若描述中存在自引用（如「文件夹包含子文件夹列表，子文件夹也是文件夹对象」）→ 使用 `$ref` 指向 `$defs` 实现循环引用，而不是内联展开
- **字段名冲突**：若不同嵌套层级中有同名字段 → 分别独立处理，不合并

## 参考资源

- `references/json-schema-spec.md`：JSON Schema Draft 2020-12 常用关键字速查表，包含类型约束、字符串格式、数值范围、数组规则、组合 Schema 等详细定义。在生成 Schema 过程中对关键字拿不准时，加载此文件作为参考。
