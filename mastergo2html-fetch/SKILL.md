---
name: mastergo2html-fetch
description: 从 MasterGo 获取设计稿 DSL 数据。支持短链和 fileId/layerId 两种输入，优先将短链解析为 fileId/layerId 后再落盘保存 DSL。
user-invocable: true
---

# mastergo2html-fetch - 从 MasterGo 获取设计稿 DSL 数据

你是 mastergo2html 的数据获取模块。根据用户提供的 MasterGo 短链或文件 URL，先解析出 `fileId` 和 `layerId`，再调用可落盘保存的 DSL 获取路径，把 DSL 数据写入工作目录。

## 前置检查

### 1. 检查配置文件

检查 `.mastergo2html/config.json` 是否存在。

如果配置文件不存在或 API Key 为空，提示用户先执行 `/mastergo2html-setup` 配置 API Key。

## 执行步骤

### 2. 调用 Python 脚本获取 DSL

用户输入: $ARGUMENTS

直接使用 `scripts/fetch_mastergo.py` 脚本获取设计稿数据：

```bash
python3 scripts/fetch_mastergo.py "$ARGUMENTS"
```

**脚本功能**：
- 自动解析 MasterGo URL，提取 fileId 和 layerId
- 读取 `.mastergo2html/config.json` 中的 API Key
- 尝试多个 API 端点获取 DSL 数据
- 自动创建原型目录并保存数据

**支持的 URL 格式**：
- `https://mastergo.iflytek.com/file/{fileId}?layer_id={layerId}`
- `https://mastergo.iflytek.com/file/{fileId}?page_id={pageId}&layer_id={layerId}`

### 3. 处理脚本输出

### 3. 处理脚本输出

**成功**：脚本会自动创建目录结构并保存数据：

```text
.mastergo2html/
├── config.json
└── prototypes/
    └── <fileId>__<layerId>/
        ├── dsl_raw.json          # 原始 DSL 数据
        ├── fetch_meta.json       # 获取元数据
        └── (后续流程产物...)
```

脚本输出示例：
```
Fetching MasterGo design:
  File ID: 184567064862635
  Layer ID: 219:01256

Fetching data from MasterGo API...
  Trying: https://mastergo.iflytek.com/api/file/...
  ✓ Success!

✓ Data fetched successfully!
  Prototype key: 184567064862635__21901256
  Saved to: .mastergo2html/prototypes/184567064862635__21901256
  DSL size: 45525 bytes
```

**失败**：脚本会尝试多个 API 端点，如果全部失败会提示：
- API Key 可能无效，建议执行 `/mastergo2html-setup` 重新配置
- 文件或图层不存在，检查 URL 是否正确
- 网络错误或 MasterGo 服务端问题

### 4. DSL 数据预览

### 4. DSL 数据预览

成功获取后，读取 `fetch_meta.json` 获取原型信息，然后使用 Read 工具读取 `dsl_raw.json` 的前 100 行内容输出给用户预览，让用户直观看到 DSL 的实际数据结构。

### 5. 提示下一步

告知用户：
- DSL 数据已保存到 `.mastergo2html/prototypes/<prototype_key>/dsl_raw.json`
- 原型元数据已保存到 `.mastergo2html/prototypes/<prototype_key>/fetch_meta.json`
- 下一步可以执行：
  - `/mastergo2html-compress --target <prototype_key>` 压缩 DSL 数据
  - 或直接使用完整流程处理
