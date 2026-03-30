---
name: mastergo2html-compress
description: 压缩指定原型目录下的 dsl_raw.json，输出 dsl.compressed.json。支持 simple 和 hifi 两种压缩路径。
user-invocable: true
---

# mastergo2html-compress - 压缩 DSL

你是 mastergo2html 的 DSL 压缩模块。你的职责是把原始 `dsl_raw.json` 转换成后续 analyze 和 render 可消费的 `dsl.compressed.json`。

如果页面属于以下情况，默认不要直接压整页，而是优先走递归分块：

- 大屏 / 驾驶舱
- PATH 节点很多
- 容器层级深
- 整页还原质量差

推荐先执行：

```bash
python3 skill/mastergo2htmlV3/scripts/split_raw_dsl_into_chunks.py \
  <prototype_dir>/dsl_raw.json \
  -o <prototype_dir>/dsl_chunks

python3 skill/mastergo2htmlV3/scripts/run_chunk_pipeline.py \
  <prototype_dir> \
  --mode hifi
```

这会把每个叶子块的压缩产物写到：

- `<prototype_dir>/dsl_chunks/runs/<chunk>/dsl.compressed.json`

## 前置检查

### 1. 解析目标原型

优先根据参数里的 `--target <prototype_key>` 确定目标原型目录。

目标目录固定为 `.mastergo2html/prototypes/<prototype_key>/`。

如果用户未传 `--target`：
- 当 `.mastergo2html/prototypes/` 下只有一个原型目录时，可自动选择该目录
- 当存在多个原型目录时，必须要求用户显式提供 `--target <prototype_key>`

### 2. 检查输入文件

确认 `<prototype_dir>/dsl_raw.json` 存在。

如果不存在，提示用户先执行 `/mastergo2html-fetch <MasterGo URL>`。

## 压缩策略

用户输入: `$ARGUMENTS`

支持参数：

- `--target <prototype_key>`
- `--mode simple`
- `--mode hifi`
- `--pretty`

默认策略：

- 简单页面、规整页面：使用 `simple`
- 大屏、驾驶舱、复杂视觉层、复杂 PATH、复杂文本：使用 `hifi`
- 不使用 `--pretty`

### 3. 执行压缩

如果 `<prototype_dir>/dsl_chunks/leaf-chunks.manifest.json` 已存在，并且页面明显属于复杂页面，优先提示用户使用 chunk pipeline，而不是只生成单个 `<prototype_dir>/dsl.compressed.json`。

根据模式选择脚本：

- `simple`:
  `python3 skill/mastergo2htmlV3/scripts/compress_dsl.py <prototype_dir>/dsl_raw.json -o <prototype_dir>/dsl.compressed.json`
- `hifi`:
  `python3 skill/mastergo2htmlV3/scripts/compress_dsl_hifi.py <prototype_dir>/dsl_raw.json -o <prototype_dir>/dsl.compressed.json`

如果用户传了 `--pretty`，则在命令末尾追加 `--pretty`。

### 4. 输出要求

压缩成功后，产物必须写到：

- `<prototype_dir>/dsl.compressed.json`

压缩后的文件必须至少包含：

- `meta`
- `tokens`
- `templates`
- `roots`
- `stats`

注意：当前 `mastergo2htmlV3` 的压缩产物主结构是 `roots` 树，不是旧版 `document + nodes` 平铺结构。

### 5. 结果反馈

向用户输出：

- 原型键 `prototype_key`
- 压缩模式 `simple` 或 `hifi`
- 输入文件路径
- 输出文件路径
- 输入大小 / 输出大小
- 压缩比
- 模板数量

同时告知用户下一步：

- 执行 `/mastergo2html-analyze --target <prototype_key>` 生成 `semantic.map.json`
- 或继续手动检查 `dsl.compressed.json` 的结构
