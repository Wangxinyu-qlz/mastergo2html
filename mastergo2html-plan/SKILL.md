---
name: mastergo2html-plan
description: 基于事实产物和显式模型决策编译 render.plan.json。
user-invocable: true
---

# mastergo2html-plan

`plan` 阶段不再在公共脚本里猜组件、猜样式、猜对齐策略。

如果目标原型已经先做了递归分块，则 `plan` 阶段应按块执行，而不是整页执行。
推荐直接使用：

```bash
python3 skill/mastergo2htmlV3/scripts/run_chunk_pipeline.py \
  <prototype_dir> \
  --mode hifi \
  --stages plan
```

这会读取 `<prototype_dir>/dsl_chunks/leaf-chunks.manifest.json`，并在每个 chunk run 目录下生成：

- `component.map.json`
- `alignment.rules.json`
- `render.plan.json`

## 输入

- `<prototype_dir>/dsl.compressed.json`
- `<prototype_dir>/page.structure.json`
- `<prototype_dir>/semantic.map.json`

## 事实脚本

```bash
python3 skill/mastergo2htmlV3/scripts/build_component_map.py \
  <prototype_dir>/dsl.compressed.json \
  <prototype_dir>/page.structure.json \
  <prototype_dir>/semantic.map.json \
  --rules skill/mastergo2htmlV3/examples/direction-rules.example.json \
  -o <prototype_dir>/component.map.json

python3 skill/mastergo2htmlV3/scripts/build_alignment_rules.py \
  <prototype_dir>/dsl.compressed.json \
  <prototype_dir>/component.map.json \
  -o <prototype_dir>/alignment.rules.json
```

这两个脚本默认只输出事实，或透传已经显式写入的决策。
如果传入 `--rules`，脚本只执行规则，不在公共层推断。

## 计划编译

```bash
python3 skill/mastergo2htmlV3/scripts/build_render_plan.py \
  <prototype_dir>/dsl.compressed.json \
  <prototype_dir>/semantic.map.json \
  --structure <prototype_dir>/page.structure.json \
  --component-map <prototype_dir>/component.map.json \
  --alignment <prototype_dir>/alignment.rules.json \
  -o <prototype_dir>/render.plan.json
```

`build_render_plan.py` 只编译这些显式输入：
- `semantic.map.json.pageDecisions`
- `semantic.map.json.zoneDecisions`
- `semantic.map.json.componentMappings`
- `semantic.map.json.nodeMappings[].renderDecision`
- `component.map.json` 里 `decisionState=resolved` 的映射
- `alignment.rules.json.rules`

如果没有显式决策，输出会保持最小化，不会由公共脚本代替模型拍脑袋补全。

## Renderer 字段约束

`render.plan.json` 中：

- `componentPlans[].renderer`
- `nodePlans[].renderer`
- `componentPlans[].layoutDecision`
- `nodePlans[].layoutDecision`

允许显式使用 `merged-svg`。

含义：
- 当前节点或组件根允许被渲染器压成单个 SVG

边界：
- plan 明确写了 `merged-svg` 或 `mergeAsSvg: true` 时，渲染器一定会合并
- 对纯矢量子树，公共脚本也会自动补一条 `renderer: "merged-svg"` 的 node plan
- 对非纯矢量 group，仍然不会自动猜测合并

`layoutDecision` 也必须由模型显式写入，公共脚本不会自动推断。

当前渲染器支持的显式布局决策：

- `positioning.mode = "center-in-parent"`
  含义：当前节点在父容器中按自身 box 尺寸居中
- `contentAlignment.mode = "center-children-bounds"`
  含义：当前节点内部内容按子内容包围盒做居中修正

可选字段：

- `axis`: `x` / `y` / `both`
- `scope`: `direct-children` / `vector-leaves`

示例：

```json
{
  "nodeId": "n_4731ac816c",
  "renderer": "dom",
  "layoutDecision": {
    "positioning": { "mode": "center-in-parent", "axis": "both" },
    "contentAlignment": { "mode": "center-children-bounds", "axis": "both", "scope": "direct-children" }
  }
}
```
