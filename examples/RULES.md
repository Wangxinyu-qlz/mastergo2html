# Rules Schema

`build_semantic_map.py` 和 `build_component_map.py` 都支持可选参数：

```bash
--rules <rules.json>
```

当前支持的规则文件格式：

```json
{
  "version": "mastergo2html.direction-rules.v1",
  "directionRules": [
    {
      "ruleId": "instance-right-single",
      "priority": 100,
      "field": "instanceName",
      "match": {
        "containsAny": ["右"],
        "containsAll": ["图标"],
        "excludesAny": ["双右", "double-right"]
      },
      "assign": {
        "direction": "right",
        "variant": "single"
      }
    }
  ]
}
```

字段说明：

- `field`
  允许值：`instanceName`、`childNames`、`componentId`
- `priority`
  数值越大优先级越高
- `match.containsAny`
  任意命中即可
- `match.containsAll`
  必须全部命中
- `match.excludesAny`
  任意命中则该规则失效
- `assign.direction`
  当前建议值：`left`、`right`
- `assign.variant`
  当前建议值：`single`、`double`

执行结果：

- 不传 `--rules` 时，脚本只输出 `directionSources`
- 传入 `--rules` 时，脚本按规则生成 `directionFacts`
- 如果多条规则同时命中，会记录 `ruleMatches`
- 如果多条命中的 `direction` 或 `variant` 不一致，会标记冲突
