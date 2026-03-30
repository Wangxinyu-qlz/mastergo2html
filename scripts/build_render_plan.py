#!/usr/bin/env python3
"""Compile render.plan.json from explicit semantic/component/alignment decisions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pipeline_utils import (
    infer_prototype_key_from_meta,
    load_json,
    normalize_prototype_key,
    now_iso,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("compressed", type=Path, help="Path to dsl.compressed.json")
    parser.add_argument("semantic", type=Path, help="Path to semantic.map.json")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Path to render.plan.json")
    parser.add_argument("--structure", type=Path, help="Optional path to page.structure.json")
    parser.add_argument("--component-map", type=Path, help="Optional path to component.map.json")
    parser.add_argument("--alignment", type=Path, help="Optional path to alignment.rules.json")
    parser.add_argument(
        "--mode",
        choices=["semantic-first", "hifi", "static"],
        default="semantic-first",
        help="Plan strategy mode",
    )
    parser.add_argument("--pretty", action="store_true", help="Write formatted JSON")
    return parser.parse_args()


def resolve_optional_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return load_json(path)


def class_name(value: str, fallback: str) -> str:
    import re

    text = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", value or "")
    text = text.replace("_", "-").replace("/", "-").replace(":", "-")
    text = re.sub(r"[^a-zA-Z0-9-]+", "-", text).strip("-").lower()
    return text or fallback


def resolve_prototype_key(
    compressed: dict[str, Any],
    semantic: dict[str, Any],
    structure: dict[str, Any],
) -> str:
    meta = compressed.get("meta") or {}
    semantic_meta = semantic.get("meta") or {}
    structure_meta = structure.get("meta") or {}
    return str(
        normalize_prototype_key(meta.get("prototypeKey"))
        or normalize_prototype_key(semantic_meta.get("prototypeKey"))
        or normalize_prototype_key(structure_meta.get("prototypeKey"))
        or infer_prototype_key_from_meta(meta)
        or infer_prototype_key_from_meta(semantic_meta)
        or infer_prototype_key_from_meta(structure_meta)
        or "unknown"
    )


def explicit_zone_decisions(semantic: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for item in semantic.get("zoneDecisions") or []:
        zone_id = str(item.get("zoneId") or "")
        root_node_id = str(item.get("rootNodeId") or "")
        if zone_id:
            indexed[f"zone:{zone_id}"] = item
        if root_node_id:
            indexed[f"root:{root_node_id}"] = item
    return indexed


def explicit_component_map(semantic: dict[str, Any], component_map: dict[str, Any]) -> dict[str, dict[str, Any]]:
    resolved: dict[str, dict[str, Any]] = {}
    for item in component_map.get("mappings") or component_map.get("mappingDrafts") or []:
        node_id = str(item.get("nodeId") or "")
        if node_id and str(item.get("decisionState") or "") == "resolved":
            resolved[node_id] = item
    for item in semantic.get("componentMappings") or []:
        node_id = str(item.get("nodeId") or "")
        if node_id:
            resolved[node_id] = {
                "nodeId": node_id,
                "zoneId": str(item.get("zoneId") or ""),
                "library": str(item.get("library") or ""),
                "libraryComponent": str(item.get("libraryComponent") or ""),
                "componentType": str(item.get("componentType") or ""),
                "props": item.get("props") or {},
                "styleOverrides": item.get("styleOverrides") or {},
                "decisionState": "resolved",
            }
    return resolved


def collect_extra_css_rules(
    semantic: dict[str, Any],
    component_map_entries: dict[str, dict[str, Any]],
    alignment: dict[str, Any],
) -> list[Any]:
    rules: list[Any] = []
    page_decisions = semantic.get("pageDecisions") or {}
    rules.extend(page_decisions.get("extraCssRules") or [])
    for entry in component_map_entries.values():
        rules.extend(((entry.get("styleOverrides") or {}).get("rules") or []))
    rules.extend(alignment.get("globalCssRules") or [])
    for rule in alignment.get("rules") or []:
        rules.extend(rule.get("cssRules") or [])
    return rules


def build_plan(
    compressed: dict[str, Any],
    semantic: dict[str, Any],
    structure: dict[str, Any],
    component_map: dict[str, Any],
    alignment: dict[str, Any],
    mode: str,
) -> dict[str, Any]:
    roots = compressed.get("roots") or []
    prototype_key = resolve_prototype_key(compressed, semantic, structure)
    root_node_id = str(roots[0].get("id") or "") if roots else ""
    root_component_id = f"cmp_{class_name(root_node_id or prototype_key, 'page-root')}"
    zone_decisions = explicit_zone_decisions(semantic)
    component_entries = explicit_component_map(semantic, component_map)
    node_mapping_by_id = {
        str(item.get("nodeId") or ""): item
        for item in (semantic.get("nodeMappings") or [])
        if item.get("nodeId")
    }

    framework_plan: list[dict[str, Any]] = []
    layout_plans: list[dict[str, Any]] = []
    detail_plans: list[dict[str, Any]] = []
    component_plans: list[dict[str, Any]] = []
    node_plans: list[dict[str, Any]] = []
    library_plans: list[dict[str, Any]] = []
    manual_zones: list[dict[str, Any]] = []
    asset_plans: list[dict[str, Any]] = []
    alignment_plans: list[dict[str, Any]] = list(alignment.get("rules") or [])

    for zone in structure.get("zones") or []:
        zone_id = str(zone.get("zoneId") or "")
        root_id = str(zone.get("rootNodeId") or "")
        decision = zone_decisions.get(f"zone:{zone_id}") or zone_decisions.get(f"root:{root_id}") or {}
        phase = str(decision.get("phase") or "")
        if phase in {"framework", "layout", "detail"}:
            base = {
                "zoneId": zone_id,
                "rootNodeId": root_id,
                "bounds": zone.get("bounds") or [0, 0, 0, 0],
                "renderer": str(decision.get("renderer") or f"zone-{phase}"),
            }
            if phase == "framework":
                framework_plan.append(base)
            elif phase == "layout":
                layout_plans.append({**base, "layoutFacts": (zone.get("layoutFacts") or {})})
            else:
                detail_plans.append(base)
        component_plan = decision.get("componentPlan")
        if isinstance(component_plan, dict) and component_plan:
            component_plans.append(
                {
                    "componentId": str(component_plan.get("componentId") or f"cmp_{zone_id}"),
                    "rootNodeId": root_id,
                    "renderer": str(component_plan.get("renderer") or ""),
                    "phase": str(component_plan.get("phase") or phase or ""),
                    "html": component_plan.get("html") or {},
                    "layoutDecision": component_plan.get("layoutDecision") or {},
                    "children": zone.get("children") or [],
                    "preferredLibrary": str(component_plan.get("preferredLibrary") or ""),
                }
            )
        if isinstance(decision.get("manualZone"), dict):
            manual_zone = decision.get("manualZone") or {}
            manual_zones.append(
                {
                    "zoneId": zone_id,
                    "rootNodeId": root_id,
                    "reason": str(manual_zone.get("reason") or "manual-zone"),
                    "strategy": str(manual_zone.get("strategy") or "manual-zone"),
                }
            )

    for node_id, mapping in node_mapping_by_id.items():
        render_decision = mapping.get("renderDecision")
        component_decision = component_entries.get(node_id) or {}
        if not isinstance(render_decision, dict):
            render_decision = {}
        renderer = str(render_decision.get("renderer") or "")
        if not renderer and component_decision.get("libraryComponent"):
            renderer = "library-host"
        if not renderer:
            continue
        html_plan = render_decision.get("html") or {}
        node_plan = {
            "nodeId": node_id,
            "renderer": renderer,
            "phase": str(render_decision.get("phase") or ""),
            "html": html_plan,
            "layoutDecision": render_decision.get("layoutDecision") or {},
            "stylePolicy": render_decision.get("stylePolicy") or {},
            "library": str(component_decision.get("library") or "custom"),
            "libraryComponent": str(component_decision.get("libraryComponent") or ""),
            "props": component_decision.get("props") or {},
            "componentType": str(component_decision.get("componentType") or ""),
            "styleOverrides": component_decision.get("styleOverrides") or {},
        }
        node_plans.append(node_plan)
        if component_decision.get("library") and component_decision.get("libraryComponent"):
            library_plans.append(
                {
                    "nodeId": node_id,
                    "zoneId": str(component_decision.get("zoneId") or mapping.get("zoneId") or ""),
                    "library": str(component_decision.get("library") or ""),
                    "libraryComponent": str(component_decision.get("libraryComponent") or ""),
                    "componentType": str(component_decision.get("componentType") or ""),
                    "props": component_decision.get("props") or {},
                    "styleOverrides": component_decision.get("styleOverrides") or {},
                    "mountStrategy": str(component_decision.get("mountStrategy") or "vue-runtime-cdn"),
                }
            )
        asset_decision = render_decision.get("assetPlan")
        if isinstance(asset_decision, dict) and asset_decision:
            asset_plans.append({"nodeId": node_id, **asset_decision})

    if not framework_plan and root_node_id:
        framework_plan.append(
            {
                "zoneId": "page-root",
                "rootNodeId": root_node_id,
                "bounds": roots[0].get("box") or [0, 0, 0, 0],
                "renderer": "zone-shell",
            }
        )

    page_decisions = semantic.get("pageDecisions") or {}
    return {
        "version": "mastergo2html.render-plan.v3",
        "meta": {
            "prototypeKey": prototype_key,
            "generatedAt": now_iso(),
            "mode": mode,
            "sourceCompressed": "dsl.compressed.json",
            "sourceSemantic": "semantic.map.json",
            "sourceStructure": "page.structure.json" if structure else "",
            "sourceComponentMap": "component.map.json" if component_map else "",
            "sourceAlignment": "alignment.rules.json" if alignment else "",
        },
        "entry": {
            "rootComponentId": root_component_id,
            "rootNodeId": root_node_id,
            "output": "output/index.html",
        },
        "uiLibraryPolicy": page_decisions.get("uiLibraryPolicy") or {},
        "strategies": page_decisions.get("strategies") or {},
        "extraCssRules": collect_extra_css_rules(semantic, component_entries, alignment),
        "frameworkPlan": framework_plan,
        "layoutPlans": layout_plans,
        "detailPlans": detail_plans,
        "libraryPlans": library_plans,
        "alignmentPlans": alignment_plans,
        "componentPlans": component_plans,
        "nodePlans": node_plans,
        "assetPlans": asset_plans,
        "manualZones": manual_zones,
    }


def main() -> None:
    args = parse_args()
    structure_path = args.structure or args.compressed.resolve().with_name("page.structure.json")
    component_map_path = args.component_map or args.compressed.resolve().with_name("component.map.json")
    alignment_path = args.alignment or args.compressed.resolve().with_name("alignment.rules.json")

    compressed = load_json(args.compressed)
    semantic = load_json(args.semantic)
    structure = resolve_optional_json(structure_path)
    component_map = resolve_optional_json(component_map_path)
    alignment = resolve_optional_json(alignment_path)
    result = build_plan(compressed, semantic, structure, component_map, alignment, args.mode)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(
        result,
        ensure_ascii=False,
        indent=2 if args.pretty else None,
        separators=None if args.pretty else (",", ":"),
    )
    args.output.write_text(rendered + ("\n" if args.pretty else ""), encoding="utf-8")
    print(
        json.dumps(
            {
                "compressed": str(args.compressed).replace("\\", "/"),
                "semantic": str(args.semantic).replace("\\", "/"),
                "structure": str(structure_path).replace("\\", "/") if structure_path.exists() else None,
                "componentMap": str(component_map_path).replace("\\", "/") if component_map_path.exists() else None,
                "alignment": str(alignment_path).replace("\\", "/") if alignment_path.exists() else None,
                "output": str(args.output).replace("\\", "/"),
                "mode": args.mode,
                "frameworkPlanCount": len(result["frameworkPlan"]),
                "layoutPlanCount": len(result["layoutPlans"]),
                "detailPlanCount": len(result["detailPlans"]),
                "libraryPlanCount": len(result["libraryPlans"]),
                "alignmentPlanCount": len(result["alignmentPlans"]),
                "manualZoneCount": len(result["manualZones"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
