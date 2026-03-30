---
name: mastergo2html-fetch
description: 从 MasterGo 获取设计稿 DSL 数据。支持短链和 fileId/layerId 两种输入，优先将短链解析为 fileId/layerId 后再落盘保存 DSL。
user-invocable: true
---

# mastergo2html-fetch - 从 MasterGo 获取设计稿 DSL 数据

你是 mastergo2html 的数据获取模块。根据用户提供的 MasterGo 短链或文件 URL，先解析出 `fileId` 和 `layerId`，再调用可落盘保存的 DSL 获取路径，把 DSL 数据写入工作目录。

## 前置检查

### 1. 读取配置

读取 `.d2c/config.json`，获取 `mastergo_api_key` 和 `mastergo_base_url`。

如果配置文件不存在或 Key 为空，提示用户先执行 `/d2c-setup` 配置 API Key。

### 2. 解析用户输入

用户输入: $ARGUMENTS

从用户输入中提取 MasterGo URL。支持以下格式：
- 完整 URL: `https://mastergo.iflytek.com/file/{fileId}?layer_id={layerId}`
- 也可能直接提供 `fileId` 和 `layerId`

**URL 解析规则**：
- **fileId**: 从 URL 路径 `/file/{fileId}` 中提取（正则：`/file/([^/?]+)`）
- **layerId**: 从 URL 查询参数 `layer_id` 中提取，**URL 解码后，如果包含 `/`（复合路径），只取第一个 `/` 之前的部分**。例如：`97%3A3583%2F748%3A18916` → 解码为 `97:3583/748:18916` → 最终取 `97:3583`

如果缺少 `fileId` 或 `layerId`，提示用户提供完整信息。

## 执行步骤

### 3. 调用 MasterGo API 获取 DSL

使用 curl 调用 MasterGo 的 DSL 接口：

```bash
curl -s \
  -H "X-MG-UserAccessToken: <api_key>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  "https://mastergo.iflytek.com/mcp/dsl?fileId=<fileId>&layerId=<layerId>"
```

**注意**：
- 认证头为 `X-MG-UserAccessToken`（不是 Bearer）
- 端点为 `GET /mcp/dsl`，参数通过 query string 传递
- 响应是完整的 DSL JSON 对象

### 4. 处理响应

**成功**：为当前原型创建独立目录，目录名固定为 `<fileId>__<layerId>`，整体结构如下：

```text
.mastergo2html/
├── config.json
└── prototypes/
    └── <fileId>__<layerId>/
        ├── dsl_raw.json
        ├── fetch_meta.json
        ├── dsl.compressed.json
        ├── semantic.map.json
        ├── render.plan.json
        ├── analysis.md
        └── output/
```

将 DSL 数据保存到 `.mastergo2html/prototypes/<fileId>__<layerId>/dsl_raw.json`，同时保存元数据到 `.mastergo2html/prototypes/<fileId>__<layerId>/fetch_meta.json`：

```json
{
  "file_id": "提取的fileId",
  "layer_id": "提取的layerId",
  "prototype_key": "<fileId>__<layerId>",
  "prototype_dir": ".mastergo2html/prototypes/<fileId>__<layerId>",
  "source_url": "原始MasterGo URL",
  "fetched_at": "ISO8601时间戳",
  "dsl_size_bytes": DSL数据大小,
  "node_count": 顶层节点数量估算
}
```

**失败**：根据错误码提示：
- 401/403: API Key 无效或过期，建议执行 `/mastergo2html-setup` 重新配置
- 404: 文件或图层不存在，检查 URL 是否正确
- 500: MasterGo 服务端错误，稍后重试
- 网络错误: 检查网络连接

### 6. DSL 数据预览

成功获取后，直接使用 Read 工具读取 `.mastergo2html/prototypes/<fileId>__<layerId>/dsl_raw.json` 的前 200 行内容输出给用户预览，让用户直观看到 DSL 的实际数据结构。同时说明文件总大小和原型目录。

### 7. 提示下一步

告知用户：
- DSL 数据已保存到 `.mastergo2html/prototypes/<fileId>__<layerId>/dsl_raw.json`
- 原型元数据已保存到 `.mastergo2html/prototypes/<fileId>__<layerId>/fetch_meta.json`
- 执行 `/mastergo2html-compress --target <fileId>__<layerId>` 压缩 DSL 数据
