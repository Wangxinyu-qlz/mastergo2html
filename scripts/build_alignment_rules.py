#!/usr/bin/env python3
"""Extract alignment facts from compressed DSL for model-driven planning."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pipeline_utils import (
    collect_nodes,
    infer_prototype_key_from_meta,
    load_json,
    node_box,
    normalize_prototype_key,
    now_iso,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("compressed", type=Path, help="Path to dsl.compressed.json")
    parser.add_argument("component_map", type=Path, help="Path to component.map.json")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Path to alignment.rules.json")
    parser.add_argument("--pretty", action="store_true", help="Write formatted JSON")
    return parser.parse_args()


def build_alignment_facts(compressed: dict[str, Any], component_map: dict[str, Any]) -> dict[str, Any]:
    roots = compressed.get("roots") or []
    nodes, parents = collect_nodes(roots)
    by_id = {str(node.get("id") or ""): node for node in nodes}
    prototype_key = str(
        normalize_prototype_key((compressed.get("meta") or {}).get("prototypeKey"))
        or infer_prototype_key_from_meta(compressed.get("meta") or {})
        or "unknown"
    )

    component_entries = {
        str(item.get("nodeId") or ""): item
        for item in (component_map.get("mappings") or component_map.get("mappingDrafts") or [])
        if item.get("nodeId")
    }

    items: list[dict[str, Any]] = []
    for node_id, entry in component_entries.items():
        node = by_id.get(node_id)
        if node is None:
            continue
        parent = parents.get(node_id)
        x, y, width, height = node_box(node)
        child_metrics = []
        for child in node.get("children") or []:
            cx, cy, cw, ch = node_box(child)
            child_metrics.append(
                {
                    "nodeId": str(child.get("id") or ""),
                    "kind": str(child.get("kind") or ""),
                    "box": [cx, cy, cw, ch],
                    "hasVector": bool(child.get("vector")),
                    "hasChildren": bool(child.get("children")),
                    "textLength": len(str(((child.get("text") or {}).get("value")) or "")),
                }
            )
        items.append(
            {
                "nodeId": node_id,
                "parentNodeId": str((parent or {}).get("id") or ""),
                "box": [x, y, width, height],
                "center": [x + width / 2, y + height / 2],
                "childCount": len(node.get("children") or []),
                "childMetrics": child_metrics,
                "componentDraft": {
                    "componentType": str(entry.get("componentType") or ""),
                    "library": str(entry.get("library") or ""),
                    "libraryComponent": str(entry.get("libraryComponent") or ""),
                },
            }
        )

    return {
        "version": "mastergo2html.alignment-facts.v1",
        "meta": {
            "prototypeKey": prototype_key,
            "generatedAt": now_iso(),
            "sourceCompressed": "dsl.compressed.json",
            "sourceComponentMap": "component.map.json",
        },
        "items": items,
        "checks": [
            "position-top-consistency",
            "container-size-consistency",
            "cross-axis-alignment",
            "svg-viewport-mismatch",
            "optical-center-offset",
        ],
        "rules": [],
    }


def main() -> None:
    args = parse_args()
    payload = build_alignment_facts(load_json(args.compressed), load_json(args.component_map))
    write_json(args.output, payload, pretty=args.pretty or True)
    print(
        json.dumps(
            {
                "output": str(args.output).replace("\\", "/"),
                "itemCount": len(payload.get("items") or []),
                "ruleCount": len(payload.get("rules") or []),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
