---
name: mastergo2html-structure
description: 从压缩 DSL 提取页面结构事实。
user-invocable: true
---

# mastergo2html-structure

`structure` 阶段只提取布局和容器事实。

## 输入

- `<prototype_dir>/dsl.compressed.json`

## 输出

- `<prototype_dir>/page.structure.json`
- `<prototype_dir>/structure.md`

## 脚本入口

```bash
python3 skill/mastergo2htmlV3/scripts/build_page_structure.py \
  <prototype_dir>/dsl.compressed.json \
  -o <prototype_dir>/page.structure.json
```

## 提取内容

- `rootFrames`
- `zones`
- `componentBoundaries`
- `layoutSkeleton`
- `renderOrder`

这些字段只描述：
- 层级
- 包围盒
- 布局候选
- 文本摘要
- 区块顺序

公共脚本不会在这个阶段推断：
- `role`
- `preferredLibrary`
- `renderPhase`
- `needsManualHandling`
