---
name: mastergo2html-analyze
description: 提取压缩 DSL 的语义事实，输出 semantic.map.json 和 analysis.md。
user-invocable: true
---

# mastergo2html-analyze

`analyze` 阶段现在只做事实提取，不在公共脚本里做语义判断。

## 输入

- `<prototype_dir>/dsl.compressed.json`
- `<prototype_dir>/page.structure.json`

## 输出

- `<prototype_dir>/semantic.map.json`
- `<prototype_dir>/analysis.md`

## 脚本入口

```bash
python3 skill/mastergo2htmlV3/scripts/build_semantic_map.py \
  <prototype_dir>/dsl.compressed.json \
  <prototype_dir>/page.structure.json \
  --rules skill/mastergo2htmlV3/examples/direction-rules.example.json \
  -o <prototype_dir>/semantic.map.json
```

## 产物职责

`semantic.map.json` 默认只包含：
- `components`
- `componentHierarchy`
- `zoneMappings`
- `nodeMappings`
- `templates`
- `layoutFacts`
- `contentFacts`

其中 `nodeMappings` 是事实包，不是最终语义判断。

如果后续模型已经做出决策，可以显式写回：
- `pageDecisions`
- `zoneDecisions`
- `componentMappings`
- `nodeMappings[].renderDecision`

公共脚本不会自动生成这些字段。

如果模型已经生成规则文件，也可以通过 `--rules` 让脚本执行这些规则。
规则格式见：
- [RULES.md](/Users/a123/iflytek/project/JW-VizHub/skill/mastergo2htmlV3/examples/RULES.md)
- [direction-rules.example.json](/Users/a123/iflytek/project/JW-VizHub/skill/mastergo2htmlV3/examples/direction-rules.example.json)
