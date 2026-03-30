#!/usr/bin/env python3
"""Build page.structure.json from compressed DSL roots."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pipeline_utils import (
    collect_nodes,
    first_text,
    flatten_text,
    infer_layout_mode,
    infer_prototype_key_from_meta,
    load_json,
    node_box,
    normalize_prototype_key,
    now_iso,
    slugify,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("compressed", type=Path, help="Path to dsl.compressed.json")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Path to page.structure.json")
    parser.add_argument("--markdown", type=Path, help="Optional path to structure.md")
    parser.add_argument("--pretty", action="store_true", help="Write formatted JSON")
    return parser.parse_args()


def direction_candidate(layout_mode: str) -> str | None:
    if layout_mode == "row":
        return "row"
    if layout_mode == "column":
        return "column"
    return None


def build_structure(compressed: dict[str, Any]) -> dict[str, Any]:
    roots = compressed.get("roots") or []
    nodes, _ = collect_nodes(roots)
    meta = compressed.get("meta") or {}
    prototype_key = str(
        normalize_prototype_key(meta.get("prototypeKey"))
        or infer_prototype_key_from_meta(meta)
        or "unknown"
    )
    root_frames: list[dict[str, Any]] = []
    zones: list[dict[str, Any]] = []
    component_boundaries: list[dict[str, Any]] = []
    layout_skeleton: list[dict[str, Any]] = []
    render_order: list[dict[str, Any]] = []
    used_zone_ids: set[str] = set()
    node_index = 0

    def make_zone_id(name: str, node_id: str) -> str:
        base = slugify(f"{name}-{node_id}", f"zone-{node_id.replace(':', '-')}")
        candidate = base
        suffix = 2
        while candidate in used_zone_ids:
            candidate = f"{base}-{suffix}"
            suffix += 1
        used_zone_ids.add(candidate)
        return candidate

    def is_zone_candidate(node: dict[str, Any], depth: int) -> bool:
        if depth == 0:
            return True
        kind = str(node.get("kind") or "")
        children = node.get("children") or []
        return kind in {"frame", "group", "instance"} and bool(children)

    def walk(node: dict[str, Any], depth: int, parent_zone_id: str | None) -> str | None:
        nonlocal node_index
        node_index += 1
        node_id = str(node.get("id") or "")
        name = str(node.get("name") or node_id)
        kind = str(node.get("kind") or "")
        x, y, width, height = node_box(node)
        children = node.get("children") or []
        layout_mode = infer_layout_mode(node)

        if not is_zone_candidate(node, depth):
            for child in children:
                walk(child, depth + 1, parent_zone_id)
            return None

        zone_id = make_zone_id(name, node_id)
        child_zone_ids: list[str] = []
        for child in children:
            child_zone_id = walk(child, depth + 1, zone_id)
            if child_zone_id:
                child_zone_ids.append(child_zone_id)

        flattened_text = flatten_text(node)
        zone = {
            "zoneId": zone_id,
            "rootNodeId": node_id,
            "parentZoneId": parent_zone_id,
            "children": child_zone_ids,
            "name": name,
            "kind": kind,
            "depth": depth,
            "nodeOrder": node_index,
            "bounds": [x, y, width, height],
            "childCount": len(children),
            "textSummary": {
                "firstText": first_text(node),
                "flattenedText": flattened_text,
                "textLength": len(flattened_text),
            },
            "layoutFacts": {
                "modeCandidate": layout_mode,
                "directionCandidate": direction_candidate(layout_mode),
                "childCount": len(children),
            },
            "candidateFlags": {
                "isRoot": depth == 0,
                "isLeafZone": not child_zone_ids,
                "hasText": bool(flattened_text),
                "hasVector": bool(node.get("vector")),
                "hasChildren": bool(children),
            },
        }
        zones.append(zone)
        component_boundaries.append(
            {
                "componentId": f"cmp_{zone_id}",
                "zoneId": zone_id,
                "rootNodeId": node_id,
                "name": name,
                "kind": kind,
                "depth": depth,
            }
        )
        layout_skeleton.append(
            {
                "zoneId": zone_id,
                "rootNodeId": node_id,
                "bounds": [x, y, width, height],
                "layoutFacts": {
                    "modeCandidate": layout_mode,
                    "directionCandidate": direction_candidate(layout_mode),
                },
            }
        )
        render_order.append(
            {
                "zoneId": zone_id,
                "depth": depth,
                "nodeOrder": node_index,
            }
        )
        return zone_id

    for root in roots:
        root_id = str(root.get("id") or "")
        root_zone = walk(root, 0, None)
        x, y, width, height = node_box(root)
        root_frames.append(
            {
                "rootNodeId": root_id,
                "name": str(root.get("name") or root_id),
                "bounds": [x, y, width, height],
                "zoneId": root_zone,
            }
        )

    render_order.sort(key=lambda item: (item["depth"], item["nodeOrder"], item["zoneId"]))
    return {
        "version": "mastergo2html.page-structure-facts.v1",
        "meta": {
            "prototypeKey": prototype_key,
            "generatedAt": now_iso(),
            "sourceCompressed": "dsl.compressed.json",
        },
        "page": {
            "name": str(roots[0].get("name") or prototype_key) if roots else prototype_key,
            "rootCount": len(roots),
            "nodeCount": len(nodes),
        },
        "rootFrames": root_frames,
        "zones": zones,
        "componentBoundaries": component_boundaries,
        "layoutSkeleton": layout_skeleton,
        "renderOrder": render_order,
        "specialRegions": [],
    }


def render_markdown(structure: dict[str, Any]) -> str:
    lines = ["# Page Structure Facts", ""]
    page = structure.get("page") or {}
    lines.append(f"- page: `{page.get('name', 'unknown')}`")
    lines.append(f"- rootCount: `{page.get('rootCount', 0)}`")
    lines.append(f"- nodeCount: `{page.get('nodeCount', 0)}`")
    lines.append("")
    lines.append("## Zones")
    lines.append("")
    for zone in structure.get("zones") or []:
        layout_facts = zone.get("layoutFacts") or {}
        lines.append(
            f"- `{zone['zoneId']}`: kind=`{zone['kind']}`, depth=`{zone['depth']}`, "
            f"layout=`{layout_facts.get('modeCandidate', 'unknown')}`"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    compressed = load_json(args.compressed)
    structure = build_structure(compressed)
    write_json(args.output, structure, pretty=args.pretty or True)
    markdown_path = args.markdown or args.output.with_name("structure.md")
    markdown_path.write_text(render_markdown(structure), encoding="utf-8")
    print(
        json.dumps(
            {
                "compressed": str(args.compressed).replace("\\", "/"),
                "output": str(args.output).replace("\\", "/"),
                "markdown": str(markdown_path).replace("\\", "/"),
                "zoneCount": len(structure.get("zones") or []),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
