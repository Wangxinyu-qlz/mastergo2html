#!/usr/bin/env python3
"""Build semantic.map.json as a factual extraction artifact."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pipeline_utils import (
    collect_nodes,
    first_text,
    flatten_text,
    infer_prototype_key_from_meta,
    load_json,
    node_box,
    normalize_prototype_key,
    now_iso,
    write_json,
)


def load_rule_payload(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    payload = load_json(path)
    payload["_source"] = str(path).replace("\\", "/")
    return payload


def extract_direction_sources(node: dict[str, Any]) -> dict[str, Any]:
    component_id = str(node.get("componentId") or "")
    component_info = node.get("componentInfo")
    instance_name = str(node.get("name") or "")
    child_names = [str(child.get("name") or "") for child in (node.get("children") or [])]
    return {
        "componentId": component_id,
        "componentInfo": component_info if isinstance(component_info, dict) else {},
        "instanceName": instance_name,
        "childNames": child_names,
    }


def analyze_effect_decision(
    node: dict[str, Any],
    compressed: dict[str, Any],
    facts: dict[str, Any],
) -> dict[str, Any] | None:
    """
    分析节点的effect，决定是否应该跳过某些效果。
    只针对 filter: blur 做智能过滤，保留 backdrop-filter 和 box-shadow。
    """
    effect_token = facts.get("effectToken", "")
    if not effect_token:
        return None

    # 获取effect的实际值
    effects = compressed.get("tokens", {}).get("effects", {})
    effect_data = effects.get(effect_token, {})
    effect_values = effect_data.get("value", [])

    # 检查是否包含 filter: blur（不包括 backdrop-filter）
    has_filter_blur = any(
        "filter:" in str(v) and "blur" in str(v).lower() and "backdrop" not in str(v).lower()
        for v in effect_values
    )

    if not has_filter_blur:
        return None

    # 获取节点信息
    kind = facts.get("kind", "")
    box = facts.get("box", [0, 0, 0, 0])
    width = float(box[2]) if len(box) > 2 else 0
    height = float(box[3]) if len(box) > 3 else 0

    skip_reasons = []

    # 规则1: 文字节点不应用 filter: blur
    if kind == "text":
        skip_reasons.append("文字节点不应有filter:blur效果")

    # 规则2: 细线条（宽或高 < 2px）跳过 filter: blur
    if width < 2 or height < 2:
        skip_reasons.append(f"细线条元素({width:.1f}x{height:.1f}px)不应有filter:blur")

    # 规则3: 细长条（长宽比 > 10）检查blur强度
    if width > 0 and height > 0:
        aspect_ratio = max(width, height) / min(width, height)
        if aspect_ratio > 10:
            for effect_str in effect_values:
                if "filter:" in str(effect_str) and "blur" in str(effect_str).lower():
                    import re
                    match = re.search(r"blur\(([\d\.]+)px\)", str(effect_str))
                    if match:
                        blur_value = float(match.group(1))
                        min_size = min(width, height)
                        if blur_value >= min_size * 0.5:
                            skip_reasons.append(
                                f"细长条元素(比例{aspect_ratio:.1f})的blur({blur_value}px)过强"
                            )

    # 规则4: 小面积元素（< 100px²）检查blur强度
    area = width * height
    if area < 100:
        for effect_str in effect_values:
            if "filter:" in str(effect_str) and "blur" in str(effect_str).lower():
                import re
                match = re.search(r"blur\(([\d\.]+)px\)", str(effect_str))
                if match:
                    blur_value = float(match.group(1))
                    min_size = min(width, height)
                    if blur_value >= min_size * 0.25:
                        skip_reasons.append(
                            f"小元素({area:.0f}px²)的blur({blur_value}px)相对过强"
                        )

    if skip_reasons:
        return {
            "skipEffects": True,
            "reason": "; ".join(skip_reasons),
            "effectToken": effect_token,
            "effectValues": effect_values,
        }

    return None



    normalized = value.lower()
    match = rule.get("match") or {}
    contains_any = [str(item).lower() for item in (match.get("containsAny") or []) if str(item)]
    contains_all = [str(item).lower() for item in (match.get("containsAll") or []) if str(item)]
    excludes_any = [str(item).lower() for item in (match.get("excludesAny") or []) if str(item)]
    if contains_any and not any(token in normalized for token in contains_any):
        return False
    if contains_all and not all(token in normalized for token in contains_all):
        return False
    if excludes_any and any(token in normalized for token in excludes_any):
        return False
    return True


def apply_direction_rules(sources: dict[str, Any], rules: list[dict[str, Any]]) -> dict[str, Any] | None:
    field_map = {
        "instanceName": str(sources.get("instanceName") or ""),
        "componentId": str(sources.get("componentId") or ""),
        "childNames": " ".join(str(item) for item in (sources.get("childNames") or [])),
    }
    matches: list[dict[str, Any]] = []
    for rule in sorted(rules, key=lambda item: int(item.get("priority") or 0), reverse=True):
        field = str(rule.get("field") or "")
        value = field_map.get(field, "")
        if not value or not match_rule_text(value, rule):
            continue
        assign = rule.get("assign") or {}
        matches.append(
            {
                "ruleId": str(rule.get("ruleId") or ""),
                "field": field,
                "value": value,
                "direction": str(assign.get("direction") or ""),
                "variant": str(assign.get("variant") or ""),
            }
        )
    if not matches:
        return None
    directions = {item["direction"] for item in matches if item["direction"]}
    variants = {item["variant"] for item in matches if item["variant"]}
    primary = matches[0]
    return {
        **sources,
        "directionKeyword": primary["direction"],
        "variantKeyword": primary["variant"],
        "directionConflict": len(directions) > 1,
        "variantConflict": len(variants) > 1,
        "ruleMatches": matches,
        "isDirectionalCandidate": True,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("compressed", type=Path, help="Path to dsl.compressed.json")
    parser.add_argument("structure", type=Path, help="Path to page.structure.json")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Path to semantic.map.json")
    parser.add_argument("--markdown", type=Path, help="Optional path to analysis.md")
    parser.add_argument("--rules", type=Path, help="Optional path to model-authored rules JSON")
    parser.add_argument("--pretty", action="store_true", help="Write formatted JSON")
    return parser.parse_args()


def build_zone_indexes(zones: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(zone.get("rootNodeId") or ""): zone
        for zone in zones
        if zone.get("rootNodeId")
    }


def build_templates(nodes: list[dict[str, Any]], parents: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for node in nodes:
        node_id = str(node.get("id") or "")
        if not node_id:
            continue
        parent = parents.get(node_id)
        if parent is None:
            continue
        name = str(node.get("name") or "")
        kind = str(node.get("kind") or "")
        _, _, width, height = node_box(node)
        grouped[(str(parent.get("id") or ""), name, f"{kind}:{width}:{height}")].append(node_id)
    templates: list[dict[str, Any]] = []
    for index, ((parent_id, name, signature), node_ids) in enumerate(sorted(grouped.items()), start=1):
        if len(node_ids) < 3:
            continue
        templates.append(
            {
                "templateId": f"tpl_{index:02d}",
                "parentNodeId": parent_id,
                "signature": signature,
                "name": name,
                "instanceNodeIds": node_ids,
            }
        )
    return templates


def collect_vector_leaf_boxes(node: dict[str, Any], offset_x: float = 0.0, offset_y: float = 0.0) -> list[dict[str, Any]]:
    x, y, width, height = node_box(node)
    abs_x = offset_x + x
    abs_y = offset_y + y
    if node.get("vector"):
        return [
            {
                "nodeId": str(node.get("id") or ""),
                "box": [abs_x, abs_y, width, height],
            }
        ]
    leaves: list[dict[str, Any]] = []
    for child in node.get("children") or []:
        leaves.extend(collect_vector_leaf_boxes(child, abs_x, abs_y))
    return leaves


def direct_icon_members(node: dict[str, Any]) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    for child in node.get("children") or []:
        leaves = collect_vector_leaf_boxes(child)
        if not leaves:
            continue
        x, y, width, height = node_box(child)
        members.append(
            {
                "nodeId": str(child.get("id") or ""),
                "kind": str(child.get("kind") or ""),
                "name": str(child.get("name") or ""),
                "box": [x, y, width, height],
                "vectorLeafCount": len(leaves),
                "vectorLeafBoxes": [item["box"] for item in leaves],
            }
        )
    return members


def summarize_icon_member(node: dict[str, Any]) -> dict[str, Any]:
    x, y, width, height = node_box(node)
    leaves = collect_vector_leaf_boxes(node)
    return {
        "nodeId": str(node.get("id") or ""),
        "kind": str(node.get("kind") or ""),
        "name": str(node.get("name") or ""),
        "box": [x, y, width, height],
        "vectorLeafCount": len(leaves),
        "vectorLeafBoxes": [item["box"] for item in leaves],
    }


def resolved_icon_members(node: dict[str, Any]) -> list[dict[str, Any]]:
    members = direct_icon_members(node)
    if len(members) != 1:
        return members
    only_child = (node.get("children") or [None])[0]
    if not isinstance(only_child, dict):
        return members
    nested_members = direct_icon_members(only_child)
    if len(nested_members) < 2:
        return members
    return [summarize_icon_member(child) for child in (only_child.get("children") or []) if collect_vector_leaf_boxes(child)]


def extract_icon_structure_facts(node: dict[str, Any]) -> dict[str, Any]:
    vector_leaves = collect_vector_leaf_boxes(node)
    if not vector_leaves:
        return {
            "isIconCandidate": False,
            "structureType": "",
            "groupSize": [0, 0],
            "memberCount": 0,
            "memberBoxes": [],
        }
    x, y, width, height = node_box(node)
    members = resolved_icon_members(node)
    if not members:
        members = [
            {
                "nodeId": item["nodeId"],
                "kind": "vector-leaf",
                "name": "",
                "box": item["box"],
                "vectorLeafCount": 1,
                "vectorLeafBoxes": [item["box"]],
            }
            for item in vector_leaves
        ]
    is_group = len(members) > 1 or any((item.get("vectorLeafCount") or 0) > 1 for item in members)
    return {
        "isIconCandidate": True,
        "structureType": "icon-group" if is_group else "single-icon",
        "groupSize": [width, height],
        "memberCount": len(members),
        "memberBoxes": [item["box"] for item in members],
        "members": members,
        "vectorLeafCount": len(vector_leaves),
        "vectorLeafBoxes": [item["box"] for item in vector_leaves],
        "bounds": [x, y, width, height],
    }


def build_semantic_map(
    compressed: dict[str, Any],
    structure: dict[str, Any],
    rule_payload: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    roots = compressed.get("roots") or []
    nodes, parents = collect_nodes(roots)
    zones = structure.get("zones") or []
    zone_by_root = build_zone_indexes(zones)
    zone_component_by_id = {
        str(item.get("zoneId") or ""): str(item.get("componentId") or "")
        for item in (structure.get("componentBoundaries") or [])
        if item.get("zoneId")
    }
    meta = compressed.get("meta") or {}
    prototype_key = str(
        normalize_prototype_key(meta.get("prototypeKey"))
        or normalize_prototype_key((structure.get("meta") or {}).get("prototypeKey"))
        or infer_prototype_key_from_meta(meta)
        or infer_prototype_key_from_meta(structure.get("meta") or {})
        or "unknown"
    )

    def find_zone_for_node(node_id: str) -> dict[str, Any] | None:
        current_id = node_id
        while current_id:
            zone = zone_by_root.get(current_id)
            if zone is not None:
                return zone
            parent = parents.get(current_id)
            current_id = str(parent.get("id") or "") if parent else ""
        return None

    zone_mappings: list[dict[str, Any]] = []
    node_mappings: list[dict[str, Any]] = []
    layout_facts: list[dict[str, Any]] = []
    content_facts: list[dict[str, Any]] = []
    direction_facts: list[dict[str, Any]] = []
    icon_structure_facts: list[dict[str, Any]] = []
    direction_rules = [
        item for item in (rule_payload.get("directionRules") or []) if isinstance(item, dict)
    ]

    for zone in zones:
        layout = zone.get("layoutFacts") or {}
        layout_facts.append(
            {
                "zoneId": str(zone.get("zoneId") or ""),
                "nodeId": str(zone.get("rootNodeId") or ""),
                "modeCandidate": str(layout.get("modeCandidate") or ""),
                "directionCandidate": layout.get("directionCandidate"),
                "childCount": int(layout.get("childCount") or 0),
            }
        )

    for node in nodes:
        node_id = str(node.get("id") or "")
        if not node_id:
            continue
        zone = find_zone_for_node(node_id)
        zone_id = str((zone or {}).get("zoneId") or "")
        component_id = zone_component_by_id.get(zone_id, "")
        parent = parents.get(node_id) or {}
        x, y, width, height = node_box(node)
        flattened = flatten_text(node)
        node_mapping = {
            "nodeId": node_id,
            "zoneId": zone_id,
            "componentId": component_id,
            "decisionState": "pending",
            "facts": {
                "name": str(node.get("name") or ""),
                "kind": str(node.get("kind") or ""),
                "box": [x, y, width, height],
                "depth": int((zone or {}).get("depth") or 0),
                "childCount": len(node.get("children") or []),
                "hasVector": bool(node.get("vector")),
                "hasText": bool(first_text(node)),
                "firstText": first_text(node),
                "flattenedText": flattened,
                "textLength": len(flattened),
                "parentNodeId": str(parent.get("id") or ""),
                "fillToken": str(node.get("fill") or ""),
                "effectToken": str((node.get("style") or {}).get("effect") or ""),
                "strokeColorToken": str((node.get("style") or {}).get("strokeColor") or ""),
                "fontToken": str(((node.get("text") or {}).get("font")) or ""),
                "textColorToken": str(((node.get("text") or {}).get("color")) or ""),
                "textMode": str(node.get("mode") or ""),
                "align": str(node.get("align") or ""),
                "sourceComponentId": str(node.get("componentId") or ""),
                "sourceComponentInfo": node.get("componentInfo") if isinstance(node.get("componentInfo"), dict) else {},
                "directionSources": extract_direction_sources(node),
                "iconStructureFacts": extract_icon_structure_facts(node),
            },
        }

        # 分析effect并生成renderDecision
        effect_decision = analyze_effect_decision(node, compressed, node_mapping["facts"])
        if effect_decision:
            node_mapping["renderDecision"] = effect_decision

        node_mappings.append(node_mapping)
        direction_fact = apply_direction_rules(node_mapping["facts"]["directionSources"], direction_rules)
        if direction_fact:
            direction_facts.append({"nodeId": node_id, **direction_fact})
        icon_fact = node_mapping["facts"]["iconStructureFacts"]
        if icon_fact.get("isIconCandidate"):
            icon_structure_facts.append({"nodeId": node_id, **icon_fact})
        zone_mappings.append({"nodeId": node_id, "zoneId": zone_id})
        if first_text(node):
            content_facts.append(
                {
                    "nodeId": node_id,
                    "zoneId": zone_id,
                    "text": first_text(node),
                    "flattenedText": flattened,
                    "textLength": len(flattened),
                    "lineCount": first_text(node).count("\n") + 1,
                    "hasDigit": any(char.isdigit() for char in first_text(node)),
                }
            )

    semantic = {
        "version": "mastergo2html.semantic-facts.v1",
        "meta": {
            "prototypeKey": prototype_key,
            "generatedAt": now_iso(),
            "sourceCompressed": "dsl.compressed.json",
            "sourceStructure": "page.structure.json",
        },
        "page": {
            "name": str((structure.get("page") or {}).get("name") or prototype_key),
            "rootCount": int((structure.get("page") or {}).get("rootCount") or 0),
            "nodeCount": int((structure.get("page") or {}).get("nodeCount") or len(nodes)),
        },
        "components": [
            {
                "componentId": str(item.get("componentId") or ""),
                "zoneId": str(item.get("zoneId") or ""),
                "rootNodeId": str(item.get("rootNodeId") or ""),
                "name": str(item.get("name") or ""),
                "kind": str(item.get("kind") or ""),
                "depth": int(item.get("depth") or 0),
            }
            for item in (structure.get("componentBoundaries") or [])
        ],
        "componentHierarchy": [
            {
                "zoneId": str(zone.get("zoneId") or ""),
                "parentZoneId": str(zone.get("parentZoneId") or ""),
                "children": list(zone.get("children") or []),
            }
            for zone in zones
        ],
        "zoneMappings": zone_mappings,
        "nodeMappings": node_mappings,
        "templates": build_templates(nodes, parents),
        "layoutFacts": layout_facts,
        "contentFacts": content_facts,
        "directionRulesMeta": {
            "source": str(rule_payload.get("_source") or ""),
            "ruleCount": len(direction_rules),
        },
        "directionFacts": direction_facts,
        "iconStructureFacts": icon_structure_facts,
        "adapterHints": {
            "version": "mastergo2html.adapter-hints.v1",
            "generatedAt": now_iso(),
            "rules": [],
        },
        "exceptions": [],
    }
    return semantic, render_analysis_markdown(compressed, structure, semantic)


def render_component_tree(zones: list[dict[str, Any]]) -> str:
    children_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    roots: list[dict[str, Any]] = []
    for zone in zones:
        zone_id = str(zone.get("zoneId") or "")
        parent_id = str(zone.get("parentZoneId") or "")
        if parent_id and parent_id != zone_id:
            children_by_parent[parent_id].append(zone)
        else:
            roots.append(zone)

    def render_node(zone: dict[str, Any], prefix: str, is_last: bool) -> list[str]:
        zone_id = str(zone.get("zoneId") or "")
        connector = "└── " if is_last else "├── "
        label = f"{zone.get('name') or zone_id} ({zone.get('kind') or 'node'})"
        lines = [f"{prefix}{connector}{label}"]
        next_prefix = prefix + ("    " if is_last else "│   ")
        children = children_by_parent.get(zone_id, [])
        for index, child in enumerate(children):
            lines.extend(render_node(child, next_prefix, index == len(children) - 1))
        return lines

    lines: list[str] = []
    for index, zone in enumerate(roots):
        lines.extend(render_node(zone, "", index == len(roots) - 1))
    return "\n".join(lines) if lines else "└── PageRoot (frame)"


def render_analysis_markdown(
    compressed: dict[str, Any],
    structure: dict[str, Any],
    semantic: dict[str, Any],
) -> str:
    lines = ["# Semantic Facts", ""]
    page = structure.get("page") or {}
    lines.append(f"- page: `{page.get('name', 'unknown')}`")
    lines.append(f"- prototypeKey: `{(semantic.get('meta') or {}).get('prototypeKey', 'unknown')}`")
    lines.append(f"- generatedAt: `{(semantic.get('meta') or {}).get('generatedAt', '')}`")
    lines.append("")
    lines.append("## Zone Tree")
    lines.append("")
    lines.append("```text")
    lines.append(render_component_tree(structure.get("zones") or []))
    lines.append("```")
    lines.append("")
    lines.append("## Facts Summary")
    lines.append("")
    lines.append(f"- components: `{len(semantic.get('components') or [])}`")
    lines.append(f"- nodeMappings: `{len(semantic.get('nodeMappings') or [])}`")
    lines.append(f"- zoneMappings: `{len(semantic.get('zoneMappings') or [])}`")
    lines.append(f"- templates: `{len(semantic.get('templates') or [])}`")
    lines.append(f"- directionFacts: `{len(semantic.get('directionFacts') or [])}`")
    lines.append(f"- iconStructureFacts: `{len(semantic.get('iconStructureFacts') or [])}`")
    lines.append("")
    token_groups = compressed.get("tokens") or {}
    lines.append("## Design Tokens")
    lines.append("")
    lines.append(f"- colors: `{len((token_groups.get('colors') or {}))}`")
    lines.append(f"- fonts: `{len((token_groups.get('fonts') or {}))}`")
    lines.append(f"- effects: `{len((token_groups.get('effects') or {}))}`")
    lines.append("")
    text_counter = Counter("text" if item.get("facts", {}).get("hasText") else "non-text" for item in (semantic.get("nodeMappings") or []))
    lines.append("## Node Facts")
    lines.append("")
    for key, value in sorted(text_counter.items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")
    lines.append("## Direction Facts")
    lines.append("")
    direction_facts = semantic.get("directionFacts") or []
    if not direction_facts:
        lines.append("- none")
    else:
        for item in direction_facts[:12]:
            lines.append(
                f"- node=`{item.get('nodeId', '')}`, componentId=`{item.get('componentId', '')}`, "
                f"direction=`{item.get('directionKeyword', '')}`, variant=`{item.get('variantKeyword', '')}`"
            )
    lines.append("")
    lines.append("## Icon Structure Facts")
    lines.append("")
    icon_facts = semantic.get("iconStructureFacts") or []
    if not icon_facts:
        lines.append("- none")
    else:
        for item in icon_facts[:12]:
            lines.append(
                f"- node=`{item.get('nodeId', '')}`, type=`{item.get('structureType', '')}`, "
                f"memberCount=`{item.get('memberCount', 0)}`, groupSize=`{item.get('groupSize', [])}`"
            )
    lines.append("")
    lines.append("## Adapter Hints")
    lines.append("")
    lines.append("- 当前公共脚本不再推断 adapter hints；如需特殊处理，应由模型显式写入语义或计划产物。")
    lines.append("")
    lines.append("## Stats")
    lines.append("")
    stats = compressed.get("stats") or {}
    lines.append(f"- nodeCount: `{stats.get('nodeCount', len(semantic.get('nodeMappings') or []))}`")
    lines.append(f"- templateCount: `{len(semantic.get('templates') or [])}`")
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    compressed = load_json(args.compressed)
    structure = load_json(args.structure)
    semantic, analysis_md = build_semantic_map(compressed, structure, load_rule_payload(args.rules))
    write_json(args.output, semantic, pretty=args.pretty or True)
    markdown_path = args.markdown or args.output.with_name("analysis.md")
    markdown_path.write_text(analysis_md, encoding="utf-8")
    print(
        json.dumps(
            {
                "compressed": str(args.compressed).replace("\\", "/"),
                "structure": str(args.structure).replace("\\", "/"),
                "output": str(args.output).replace("\\", "/"),
                "markdown": str(markdown_path).replace("\\", "/"),
                "componentCount": len(semantic.get("components") or []),
                "nodeMappingCount": len(semantic.get("nodeMappings") or []),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
