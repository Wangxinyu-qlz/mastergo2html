---
name: mastergo2htmlV3
description: >-
  MasterGo 原型图还原 HTML 的事实提取 + 模型决策 + 计划执行工作流。
version: 3.1.0
---

# mastergo2html

`mastergo2htmlV3` 现在按三层职责工作：

1. 脚本只提取事实
2. 模型负责组件映射、语义判断、样式恢复和渲染决策
3. 渲染器只执行 `render.plan.json`

## 标准流程

### 常规页面

1. `/mastergo2html-setup`
2. `/mastergo2html-fetch <url>`
3. `/mastergo2html-compress --target <prototype_key>`
4. `/mastergo2html-structure --target <prototype_key>`
5. `/mastergo2html-analyze --target <prototype_key>`
6. `/mastergo2html-plan --target <prototype_key>`
7. `/mastergo2html-render --target <prototype_key>`

### 复杂页面 / 大屏 / 驾驶舱 / PATH 密集页面

1. `/mastergo2html-setup`
2. `/mastergo2html-fetch <url>`
3. `python3 skill/mastergo2htmlV3/scripts/split_raw_dsl_into_chunks.py <prototype_dir>/dsl_raw.json -o <prototype_dir>/dsl_chunks`
4. `python3 skill/mastergo2htmlV3/scripts/run_chunk_pipeline.py <prototype_dir> --mode hifi`

其中第 4 步会对 `leaf-chunks.manifest.json` 中的叶子块逐块执行：

- `compress`
- `structure`
- `analyze`
- `plan`
- `render`
- `assemble`

产物集中写入：

- `<prototype_dir>/dsl_chunks/chunk.tree.json`
- `<prototype_dir>/dsl_chunks/leaf-chunks.manifest.json`
- `<prototype_dir>/dsl_chunks/chunk-pipeline.manifest.json`
- `<prototype_dir>/dsl_chunks/runs/<chunk>/...`
- `<prototype_dir>/output/assembled.html`

## 当前边界

### `structure`

输出 `page.structure.json` 和 `structure.md`。

只负责：
- 页面根节点、容器区块、层级、包围盒、布局候选
- 文本摘要、节点顺序、组件边界候选

不负责：
- 推断区块角色
- 推断 `Element Plus` 偏好
- 推断 `manual zone`
- 推断 `framework/layout/detail`

### `analyze`

输出 `semantic.map.json` 和 `analysis.md`。

只负责：
- 节点和区块事实
- 节点到区块的映射
- 文本事实、布局事实、重复模板事实

允许模型在 `semantic.map.json` 中显式补充：
- `pageDecisions`
- `zoneDecisions`
- `componentMappings`
- `nodeMappings[].renderDecision`

也允许模型先产出规则文件，再由脚本通过 `--rules` 执行。

### `plan`

输出：
- `component.map.json`
- `alignment.rules.json`
- `render.plan.json`

其中：
- `build_component_map.py` 只输出组件映射事实，或透传模型已写入的显式映射
- `build_component_map.py` 也可执行模型产出的规则文件，例如方向规则
- `build_alignment_rules.py` 只输出对齐事实
- `build_render_plan.py` 只编译显式决策，不再自己猜组件、猜样式、猜手工区

### `render`

输入：
- `dsl.compressed.json`
- `render.plan.json`

只负责：
- 执行 `componentPlans / nodePlans / libraryPlans / assetPlans / manualZones`
- 执行 `extraCssRules` 和显式 `styleOverrides`
- 仅当 plan 显式声明时执行 `merged-svg`

不负责：
- 根据组件类型自动补样式
- 根据节点名字猜 `Element Plus`
- 在公共层生成页面专项修复
- 自动把 vector group 合并成单个 SVG

## 推荐的模型决策入口

模型应基于事实产物做决策，并把结果写回：

- `semantic.map.json`
  - `pageDecisions`
  - `zoneDecisions`
  - `componentMappings`
  - `nodeMappings[].renderDecision`
- `component.map.json`
  - `mappings[].library`
  - `mappings[].libraryComponent`
  - `mappings[].props`
  - `mappings[].styleOverrides`
- `alignment.rules.json`
  - `rules[].cssDeclarations`
  - `rules[].cssRules`

## `render.plan.json` Renderer Contract

`componentPlans[].renderer` 和 `nodePlans[].renderer` 当前允许的常见值：

- `container`
- `text`
- `library-host`
- `zone-shell`
- `zone-layout`
- `zone-detail`
- `merged-svg`

其中 `merged-svg` 的约束是：

- 只能由模型在 plan 中显式声明
- renderer 不会再自动推断任何节点应该合并为 SVG
- 适用于纯视觉图形或确认应拍平成单个 SVG 的子树

## 关键原则

- 公共脚本不写组件专项特判
- 公共脚本不写页面专项特判
- 公共渲染器不根据组件类型自动决定样式
- 所有公共组件库覆写都必须来自显式 plan
- 对复杂原型优先先递归切块，再逐块进入后续流程，而不是整页直接送入模型
