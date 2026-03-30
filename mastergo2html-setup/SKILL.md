---
name: mastergo2html-setup
description: 配置 MasterGo API Key。首次使用 mastergo2html 前必须执行，引导获取 Token、验证有效性、本地保存。
user-invocable: true
disable-model-invocation: true
---

# mastergo2html-setup - 配置 MasterGo API Key

你是 mastergo2html 的配置助手。用户需要配置 MasterGo API Key 才能使用 mastergo2html 功能。

## 执行步骤

### 1. 检查是否已有配置

读取项目根目录的 `.mastergo2html/config.json` 文件，检查是否已配置 API Key。

如果文件存在且包含有效的 `mastergo_api_key` 字段：
- 显示当前配置状态（Key 的前4位和后4位，中间用 **** 掩码）
- 询问用户是否要更新

如果文件不存在或 Key 为空，进入配置流程。

### 2. 引导用户获取 API Key

告知用户：

```
要使用 mastergo2html 功能，你需要一个 MasterGo Personal Access Token。

获取步骤：
1. 登录 MasterGo 平台：https://mastergo.iflytek.com
2. 点击右上角头像 → 个人设置
3. 进入 API 管理 → 创建 Personal Access Token
4. 复制生成的 Token（格式为 mg_ 开头）
```

然后询问用户输入 API Key。

### 3. 验证 API Key

收到用户提供的 Key 后：

**格式校验**：确认以 `mg_` 开头，长度大于 10 位。

**连通性校验**：跳过连通性校验（MasterGo 用户信息接口不可用），仅做格式校验即可。Key 的有效性会在首次 `/mastergo2html-fetch` 调用 DSL 接口时自动验证。

### 4. 保存配置

验证通过后，创建 `.mastergo2html/` 目录（如不存在），并确保以下目录结构存在：

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

然后将配置写入 `.mastergo2html/config.json`：

```json
{
  "mastergo_api_key": "用户提供的key",
  "mastergo_base_url": "https://mastergo.iflytek.com",
  "created_at": "ISO8601时间戳",
  "updated_at": "ISO8601时间戳"
}
```

### 5. 更新 .gitignore

检查项目根目录的 `.gitignore` 文件，如果不包含 `.mastergo2html/` 则追加：

```
# mastergo2html local config (contains API keys)
.mastergo2html/
```

### 6. 确认完成

显示配置摘要：
- API Key: `mg_****xxxx`（掩码显示）
- Base URL: `https://mastergo.iflytek.com`
- 配置文件位置: `.mastergo2html/config.json`
- 原型目录根路径: `.mastergo2html/prototypes/`

提示用户可以开始使用：
- `/mastergo2html <MasterGo URL>` - 完整 mastergo2html 流程
- `/mastergo2html-fetch <MasterGo URL>` - 仅获取设计稿 DSL
- `/mastergo2html-compress --target <fileId>__<layerId>` - 压缩指定原型 DSL
- `/mastergo2html-analyze --target <fileId>__<layerId>` - 生成语义映射
- `/mastergo2html-plan --target <fileId>__<layerId>` - 生成渲染计划
- `/mastergo2html-render --target <fileId>__<layerId>` - 渲染 HTML

## 用户输入

$ARGUMENTS

如果用户直接提供了 API Key 作为参数，跳过引导步骤，直接进入验证和保存流程。
