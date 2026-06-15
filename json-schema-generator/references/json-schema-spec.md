# JSON Schema Draft 2020-12 关键规范参考

## 基础关键字

| 关键字 | 用途 | 示例值 |
|--------|------|--------|
| `$schema` | 声明使用的 JSON Schema 版本 | `"https://json-schema.org/draft/2020-12/schema"` |
| `$id` | Schema 的唯一标识符（可选） | `"https://example.com/user.schema.json"` |
| `title` | Schema 标题 | `"用户注册表单"` |
| `description` | Schema 描述 | `"用于验证用户注册数据的 JSON Schema"` |
| `type` | 根类型/字段类型 | `"object"`, `"string"`, `"number"`, `"integer"`, `"boolean"`, `"array"`, `"null"` |
| `properties` | 定义对象的属性集合 | `{ "name": { "type": "string" } }` |
| `required` | 必填字段数组 | `["name", "email"]` |
| `additionalProperties` | 是否允许未定义的额外属性 | `false`（禁止） / `true`（允许） |

## 字符串约束

| 关键字 | 用途 | 示例 |
|--------|------|------|
| `minLength` | 最小长度 | `1` |
| `maxLength` | 最大长度 | `100` |
| `pattern` | 正则表达式匹配 | `"^[a-zA-Z0-9_]+$"` |
| `format` | 内建格式校验 | `"email"`, `"uri"`, `"date"`, `"date-time"`, `"ipv4"`, `"ipv6"`, `"hostname"`, `"uuid"`, `"uri-reference"`, `"json-pointer"`, `"relative-json-pointer"`, `"regex"`, `"time"`, `"duration"` |
| `enum` | 枚举值约束 | `["male", "female", "other"]` |

## 数值约束

| 关键字 | 用途 | 示例 |
|--------|------|------|
| `minimum` | 最小值（包含） | `0` |
| `maximum` | 最大值（包含） | `150` |
| `exclusiveMinimum` | 最小值（不包含） | `0` |
| `exclusiveMaximum` | 最大值（不包含） | `150` |
| `multipleOf` | 倍数约束 | `0.01`（两位小数） |
| `default` | 默认值 | `18` |

## 数组约束

| 关键字 | 用途 | 示例 |
|--------|------|------|
| `items` | 定义数组元素 Schema | `{ "type": "string" }` |
| `prefixItems` | 按位置定义数组元素 Schema | `[{ "type": "number" }, { "type": "string" }]` |
| `minItems` | 最小元素个数 | `1` |
| `maxItems` | 最大元素个数 | `10` |
| `uniqueItems` | 元素是否必须唯一 | `true` |
| `contains` | 数组是否至少包含一个匹配元素 | `{ "type": "number" }` |

## 组合 Schema

| 关键字 | 用途 |
|--------|------|
| `allOf` | 必须同时满足所有子 Schema |
| `anyOf` | 只需满足任意一个子 Schema |
| `oneOf` | 必须恰好满足一个子 Schema |
| `not` | 不能满足该子 Schema |
| `if` / `then` / `else` | 条件判断逻辑 |

## 通用元数据

| 关键字 | 用途 | 示例 |
|--------|------|------|
| `examples` | 示例数据数组 | `["张三", "李四"]` |
| `const` | 固定值约束 | `"v1.0"` |
| `default` | 默认值 | `true` |

## 字段命名规范

- 使用 camelCase 命名（首字母小写驼峰）：`userName`、`emailAddress`、`phoneNumber`
- Object 的 property key 也推荐 camelCase
- Schema 顶层用 snake_case 命名文件：`user_registration.schema.json`

## 生成输出模板

每次输出需包含以下三个部分：

### 1. JSON Schema（代码块，json 语言标注）
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.com/xxx.schema.json",
  "title": "...",
  "description": "...",
  "type": "object",
  "properties": { ... },
  "required": [...]
}
```

### 2. 示例数据（代码块，json 语言标注）
至少一条合法数据、一条非法数据，并附说明。

### 3. 校验说明（Markdown 表格）
逐字段列出名称、类型、是否必填、约束条件、format、备注。
