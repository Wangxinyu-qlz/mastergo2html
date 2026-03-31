---
name: mastergo2html-render
description: 基于 render.plan.json 执行 HTML 渲染。
user-invocable: true
---

# mastergo2html-render

`render` 阶段现在只执行 plan，不做公共层语义推断和组件专项样式推断。

如果复杂页面已经先做了递归分块，优先按 render chunks 逐块 render：

```bash
python3 skill/mastergo2htmlV3/scripts/run_chunk_pipeline.py \
  <prototype_dir> \
  --mode hifi \
  --stages render
```

或一次性执行完整 chunk pipeline：

```bash
python3 skill/mastergo2htmlV3/scripts/run_chunk_pipeline.py \
  <prototype_dir> \
  --mode hifi
```

对应 chunk 产物会写到：

- `<prototype_dir>/dsl_chunks/runs/<chunk>/render.plan.json`
- `<prototype_dir>/dsl_chunks/runs/<chunk>/output/index.html`
- `<prototype_dir>/output/assembled.html`

其中：

- `leaf` chunk 渲染复杂子树本体
- `base` chunk 渲染父层背景、容器和未下钻的剩余节点
- `assembled.html` 会把各 chunk 的 HTML 片段内联组装，不使用 `iframe`

如果需要只做组装，不重跑各块渲染，可以单独执行：

```bash
python3 skill/mastergo2htmlV3/scripts/run_chunk_pipeline.py \
  <prototype_dir> \
  --mode hifi \
  --stages assemble
```

## 输入

- `<prototype_dir>/dsl.compressed.json`
- `<prototype_dir>/render.plan.json`

## 脚本入口

```bash
python3 skill/mastergo2htmlV3/scripts/render_any_dsl_to_html.py \
  <prototype_dir>/dsl.compressed.json \
  --plan <prototype_dir>/render.plan.json \
  -o <prototype_dir>/output/index.html
```

## 渲染职责

渲染器只执行：
- `frameworkPlan`
- `layoutPlans`
- `detailPlans`
- `componentPlans`
- `nodePlans`
- `libraryPlans`
- `assetPlans`
- `manualZones`
- `extraCssRules`
- `libraryPlans[].styleOverrides`
- `alignmentPlans[].cssDeclarations / cssRules`
- `componentPlans[].layoutDecision`
- `nodePlans[].layoutDecision`

如果某个 `componentPlan` 或 `nodePlan` 显式声明：
- `renderer: "merged-svg"`
- 或 `mergeAsSvg: true`

渲染器才会把对应 vector group 合并成单个 SVG。

另外，如果某个节点是纯矢量子树（只有 vector leaf / 结构容器，没有文本或普通 DOM 叶子），渲染器也会自动走同一条 `merged-svg` fast-path。

如果某个 `componentPlan` 或 `nodePlan` 显式声明 `layoutDecision`，渲染器会按该决策覆写定位或内容对齐。

当前支持：

- `positioning.mode = "center-in-parent"`
- `contentAlignment.mode = "center-children-bounds"`

渲染器不会：
- 根据节点名称猜组件库组件
- 根据组件类型自动生成弹层样式
- 在公共层注入页面专项修复
- 对非纯矢量 group 自动猜测是否应合并成 SVG

当 `libraryPlans` 非空时，仍会按 plan 挂载 Vue 3 + `Element Plus` CDN 组件。
