#!/usr/bin/env python3
"""Extract component mapping facts or normalize explicit model decisions."""

from __future__ import annotations

import argparse
import json
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
    slugify,
    write_json,
)


def load_rule_payload(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    payload = load_json(path)
    payload["_source"] = str(path).replace("\\", "/")
    return payload


def extract_direction_sources(node: dict[str, Any]) -> dict[str, Any]:
    child_names = [str(child.get("name") or "") for child in (node.get("children") or [])]
    component_id = str(node.get("componentId") or "")
    instance_name = str(node.get("name") or "")
    return {
        "componentId": component_id,
        "componentInfo": node.get("componentInfo") if isinstance(node.get("componentInfo"), dict) else {},
        "instanceName": instance_name,
        "childNames": child_names,
    }


def match_rule_text(value: str, rule: dict[str, Any]) -> bool:
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("compressed", type=Path, help="Path to dsl.compressed.json")
    parser.add_argument("structure", type=Path, help="Path to page.structure.json")
    parser.add_argument("semantic", type=Path, help="Path to semantic.map.json")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Path to component.map.json")
    parser.add_argument("--rules", type=Path, help="Optional path to model-authored rules JSON")
    parser.add_argument("--pretty", action="store_true", help="Write formatted JSON")
    return parser.parse_args()


def resolve_explicit_decision(node_id: str, semantic: dict[str, Any]) -> dict[str, Any]:
    for item in semantic.get("componentMappings") or []:
        if str(item.get("nodeId") or "") == node_id:
            return item
    for item in semantic.get("nodeMappings") or []:
        if str(item.get("nodeId") or "") == node_id:
            decision = item.get("componentDecision")
            if isinstance(decision, dict):
                return decision
    return {}


def build_component_facts(
    compressed: dict[str, Any],
    structure: dict[str, Any],
    semantic: dict[str, Any],
    rule_payload: dict[str, Any],
) -> dict[str, Any]:
    roots = compressed.get("roots") or []
    nodes, parents = collect_nodes(roots)
    zone_by_root = {
        str(item.get("rootNodeId") or ""): item
        for item in (structure.get("zones") or [])
        if item.get("rootNodeId")
    }
    prototype_key = str(
        normalize_prototype_key((compressed.get("meta") or {}).get("prototypeKey"))
        or infer_prototype_key_from_meta(compressed.get("meta") or {})
        or "unknown"
    )
    direction_rules = [
        item for item in (rule_payload.get("directionRules") or []) if isinstance(item, dict)
    ]

    drafts: list[dict[str, Any]] = []
    direction_facts: list[dict[str, Any]] = []
    icon_structure_facts: list[dict[str, Any]] = []
    for node in nodes:
        node_id = str(node.get("id") or "")
        if not node_id:
            continue
        explicit = resolve_explicit_decision(node_id, semantic)
        x, y, width, height = node_box(node)
        zone = zone_by_root.get(node_id)
        drafts.append(
            {
                "mappingId": slugify(f"mapping-{node_id}", f"mapping-{node_id.replace(':', '-')}"),
                "nodeId": node_id,
                "zoneId": str((zone or {}).get("zoneId") or ""),
                "library": str(explicit.get("library") or ""),
                "libraryComponent": str(explicit.get("libraryComponent") or ""),
                "componentType": str(explicit.get("componentType") or ""),
                "props": explicit.get("props") or {},
                "theme": explicit.get("theme") or {},
                "decisionState": "resolved" if explicit else "pending",
                "facts": {
                    "kind": str(node.get("kind") or ""),
                    "name": str(node.get("name") or ""),
                    "text": first_text(node),
                    "flattenedText": flatten_text(node),
                    "box": [x, y, width, height],
                    "childCount": len(node.get("children") or []),
                    "hasVector": bool(node.get("vector")),
                    "fillToken": str(node.get("fill") or ""),
                    "effectToken": str((node.get("style") or {}).get("effect") or ""),
                    "strokeColorToken": str((node.get("style") or {}).get("strokeColor") or ""),
                    "fontToken": str(((node.get("text") or {}).get("font")) or ""),
                    "textColorToken": str(((node.get("text") or {}).get("color")) or ""),
                    "parentNodeId": str((parents.get(node_id) or {}).get("id") or ""),
                    "sourceComponentId": str(node.get("componentId") or ""),
                    "sourceComponentInfo": node.get("componentInfo") if isinstance(node.get("componentInfo"), dict) else {},
                    "directionSources": extract_direction_sources(node),
                    "iconStructureFacts": extract_icon_structure_facts(node),
                },
            }
        )
        direction_fact = apply_direction_rules(drafts[-1]["facts"]["directionSources"], direction_rules)
        if direction_fact:
            direction_facts.append({"nodeId": node_id, **direction_fact})
        icon_fact = drafts[-1]["facts"]["iconStructureFacts"]
        if icon_fact.get("isIconCandidate"):
            icon_structure_facts.append({"nodeId": node_id, **icon_fact})

    return {
        "version": "mastergo2html.component-facts.v1",
        "meta": {
            "prototypeKey": prototype_key,
            "generatedAt": now_iso(),
            "sourceCompressed": "dsl.compressed.json",
            "sourceStructure": "page.structure.json",
            "sourceSemantic": "semantic.map.json",
        },
        "directionRulesMeta": {
            "source": str(rule_payload.get("_source") or ""),
            "ruleCount": len(direction_rules),
        },
        "mappingDrafts": drafts,
        "mappings": drafts,
        "directionFacts": direction_facts,
        "iconStructureFacts": icon_structure_facts,
        "stats": {
            "mappingCount": len(drafts),
            "resolvedCount": sum(1 for item in drafts if item["decisionState"] == "resolved"),
        },
    }


def main() -> None:
    args = parse_args()
    payload = build_component_facts(
        load_json(args.compressed),
        load_json(args.structure),
        load_json(args.semantic),
        load_rule_payload(args.rules),
    )
    write_json(args.output, payload, pretty=args.pretty or True)
    print(
        json.dumps(
            {
                "output": str(args.output).replace("\\", "/"),
                "mappingCount": payload["stats"]["mappingCount"],
                "resolvedCount": payload["stats"]["resolvedCount"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
