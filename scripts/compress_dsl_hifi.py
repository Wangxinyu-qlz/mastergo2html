#!/usr/bin/env python3
"""Compress MasterGo DSL for LLM-driven high-fidelity reconstruction.

This is a conservative compressor for complex cockpit / dashboard designs.
It keeps more visual information than `convert_mastergo_to_render_dsl.py` and
uses stricter template extraction to avoid over-generalizing non-identical
subtrees.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


def normalize_source_payload(source: dict[str, Any]) -> dict[str, Any]:
    dsl = source.get("dsl")
    if isinstance(dsl, dict):
        return source

    styles = source.get("styles")
    nodes = source.get("nodes")
    components = source.get("components")
    if isinstance(styles, dict) and isinstance(nodes, list):
        normalized = dict(source)
        normalized["dsl"] = {
            "styles": styles,
            "nodes": nodes,
            "components": components if isinstance(components, dict) else {},
        }
        return normalized
    return source


def round_number(value: Any) -> Any:
    if isinstance(value, float):
        rounded = round(value, 2)
        if rounded.is_integer():
            return int(rounded)
        return rounded
    return value


def round_deep(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: round_deep(item) for key, item in value.items()}
    if isinstance(value, list):
        return [round_deep(item) for item in value]
    return round_number(value)


def compact_box(layout_style: dict[str, Any]) -> list[Any]:
    return [
        round_number(layout_style.get("relativeX", 0)),
        round_number(layout_style.get("relativeY", 0)),
        round_number(layout_style.get("width", 0)),
        round_number(layout_style.get("height", 0)),
    ]


def compact_flex(flex_info: dict[str, Any] | None) -> dict[str, Any] | None:
    if not flex_info:
        return None
    mapping = {
        "flexDirection": "dir",
        "justifyContent": "justify",
        "alignItems": "align",
        "mainSizing": "main",
        "crossSizing": "cross",
        "gap": "gap",
    }
    out: dict[str, Any] = {}
    for source_key, target_key in mapping.items():
        value = flex_info.get(source_key)
        if value not in (None, "", "auto"):
            out[target_key] = round_deep(value)
    return out or None


def normalize_style_tokens(styles: dict[str, Any]) -> dict[str, Any]:
    colors: dict[str, Any] = {}
    fonts: dict[str, Any] = {}
    effects: dict[str, Any] = {}
    others: dict[str, Any] = {}
    for key, value in styles.items():
        if key.startswith("paint_"):
            colors[key] = round_deep(value)
        elif key.startswith("font_"):
            fonts[key] = round_deep(value)
        elif key.startswith("effect_"):
            effects[key] = round_deep(value)
        else:
            others[key] = round_deep(value)
    return {
        "colors": colors,
        "fonts": fonts,
        "effects": effects,
        "misc": others,
    }


def normalize_text_runs(node: dict[str, Any]) -> dict[str, Any]:
    runs = node.get("text", []) or []
    colors = node.get("textColor", []) or []
    segments: list[dict[str, Any]] = []
    for index, run in enumerate(runs):
        segment: dict[str, Any] = {
            "text": run.get("text", ""),
            "font": run.get("font"),
        }
        if index < len(colors) and colors[index].get("color") is not None:
            segment["color"] = colors[index].get("color")
        segments.append(segment)
    if len(segments) == 1:
        one = segments[0]
        return {
            "value": one.get("text", ""),
            "font": one.get("font"),
            "color": one.get("color"),
            "segments": segments,
        }
    return {"segments": segments}


def make_short_hash(payload: Any, *, size: int = 10) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(encoded.encode("utf-8")).hexdigest()[:size]


def normalize_path_asset(path_list: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_segments = []
    for segment in path_list:
        normalized_segment = {"d": segment.get("data", "")}
        for key in ("fill", "strokeColor", "strokeWidth", "strokeAlign", "strokeType", "opacity", "effect"):
            if segment.get(key) not in (None, "", [], {}):
                normalized_segment[key] = round_deep(segment.get(key))
        normalized_segments.append(normalized_segment)
    return {"segments": normalized_segments}


def collect_visual_style(node: dict[str, Any]) -> dict[str, Any] | None:
    style_keys = [
        "opacity",
        "overflow",
        "clipContent",
        "blendMode",
        "mask",
        "maskType",
        "strokeColor",
        "strokeWidth",
        "strokeAlign",
        "strokeType",
        "effect",
        "shadow",
        "shadows",
        "boxShadow",
        "stroke",
        "border",
        "gradient",
        "backgroundImage",
        "blur",
        "backdropBlur",
        "filters",
    ]
    out: dict[str, Any] = {}
    for key in style_keys:
        if key in node and node[key] not in (None, "", [], {}):
            out[key] = round_deep(node[key])
    return out or None


def make_vector_key(path_list: list[dict[str, Any]]) -> str:
    payload = json.dumps(path_list, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def count_descendants(node: dict[str, Any]) -> int:
    return 1 + sum(count_descendants(child) for child in node.get("children", []) or [])


def subtree_has_sensitive_visuals(node: dict[str, Any]) -> bool:
    if node.get("effect") not in (None, "", [], {}):
        return True
    if node.get("mask") not in (None, "", [], {}):
        return True
    for child in node.get("children", []) or []:
        if subtree_has_sensitive_visuals(child):
            return True
    return False


def subtree_signature(node: dict[str, Any]) -> str:
    def _sig(current: dict[str, Any]) -> Any:
        base: dict[str, Any] = {
            "type": current.get("type"),
            "name": current.get("name"),
            "box": compact_box(current.get("layoutStyle", {}))[2:],
            "fill": current.get("fill"),
            "effect": current.get("effect"),
            "opacity": current.get("opacity"),
            "mask": current.get("mask"),
            "strokeColor": current.get("strokeColor"),
            "strokeWidth": current.get("strokeWidth"),
            "strokeType": current.get("strokeType"),
            "strokeAlign": current.get("strokeAlign"),
            "borderRadius": current.get("borderRadius"),
        }
        if current.get("text"):
            base["text"] = [
                {
                    "text": item.get("text", ""),
                    "font": item.get("font"),
                }
                for item in current.get("text", []) or []
            ]
        if current.get("textColor"):
            base["textColor"] = [item.get("color") for item in current.get("textColor", []) or []]
        if current.get("path"):
            base["path"] = normalize_path_asset(current.get("path", []))
        flex = compact_flex(current.get("flexContainerInfo"))
        if flex:
            base["flex"] = flex
        children = current.get("children", []) or []
        if children:
            base["children"] = [_sig(child) for child in children]
        return base

    return json.dumps(_sig(node), ensure_ascii=False, sort_keys=True)


class HifiDslCompressor:
    def __init__(self, source: dict[str, Any], source_path: Path) -> None:
        self.source = source
        self.source_path = source_path
        self.vectors: dict[str, dict[str, Any]] = {}
        self.vector_aliases: dict[str, str] = {}
        self.signature_counts: Counter[str] = Counter()
        self.signature_nodes: dict[str, dict[str, Any]] = {}
        self.template_ids: dict[str, str] = {}
        self.template_meta: dict[str, dict[str, Any]] = {}

    def collect_signatures(self) -> None:
        def walk(node: dict[str, Any]) -> None:
            signature = subtree_signature(node)
            self.signature_counts[signature] += 1
            self.signature_nodes.setdefault(signature, node)
            for child in node.get("children", []) or []:
                walk(child)

        for root in self.source.get("dsl", {}).get("nodes", []):
            walk(root)

    def build_template_catalog(self) -> None:
        candidates: list[tuple[int, int, str]] = []
        for signature, count in self.signature_counts.items():
            node = self.signature_nodes[signature]
            size = count_descendants(node)
            has_children = bool(node.get("children"))
            has_safe_visuals = not subtree_has_sensitive_visuals(node)
            if count >= 2 and size >= 4 and has_children and has_safe_visuals:
                candidates.append((size * count, size, signature))
        candidates.sort(reverse=True)

        for index, (_, size, signature) in enumerate(candidates, start=1):
            template_id = f"tpl_{index}"
            node = self.signature_nodes[signature]
            self.template_ids[signature] = template_id
            self.template_meta[template_id] = {
                "signature": signature,
                "count": self.signature_counts[signature],
                "size": size,
                "name": node.get("name"),
            }

    def make_node_id(
        self,
        node: dict[str, Any],
        *,
        scope: str,
        path_segments: list[str],
        signature: str,
        kind: str,
    ) -> str:
        payload = {
            "scope": scope,
            "path": path_segments,
            "kind": kind,
            "sourceId": node.get("id"),
            "name": node.get("name"),
            "signature": signature,
            "box": compact_box(node.get("layoutStyle", {})),
        }
        return f"n_{make_short_hash(payload)}"

    def ensure_vector(self, path_list: list[dict[str, Any]]) -> str:
        key = make_vector_key(path_list)
        alias = self.vector_aliases.get(key)
        if alias:
            return alias
        alias = f"vec_{len(self.vectors) + 1}"
        self.vector_aliases[key] = alias
        self.vectors[alias] = normalize_path_asset(path_list)
        return alias

    def normalize_node(
        self,
        node: dict[str, Any],
        *,
        inside_template: bool = False,
        template_root_signature: str | None = None,
        path_segments: list[str] | None = None,
        scope: str = "root",
    ) -> dict[str, Any]:
        path_segments = path_segments or []
        signature = subtree_signature(node)
        should_template = (
            not inside_template
            and signature in self.template_ids
            and signature != template_root_signature
        )
        if should_template:
            node_id = self.make_node_id(
                node,
                scope=scope,
                path_segments=path_segments,
                signature=signature,
                kind="instance",
            )
            return {
                "id": node_id,
                "kind": "instance",
                "use": self.template_ids[signature],
                "name": node.get("name"),
                "box": compact_box(node.get("layoutStyle", {})),
                "sourceId": node.get("id"),
            }

        node_type = str(node.get("type", "")).lower()
        node_id = self.make_node_id(
            node,
            scope=scope,
            path_segments=path_segments,
            signature=signature,
            kind=node_type or "node",
        )
        out: dict[str, Any] = {
            "id": node_id,
            "kind": node_type,
            "name": node.get("name"),
            "box": compact_box(node.get("layoutStyle", {})),
        }
        if node.get("id"):
            out["sourceId"] = node["id"]
        if node.get("componentId") not in (None, "", [], {}):
            out["componentId"] = node["componentId"]
        if node.get("componentInfo") not in (None, "", [], {}):
            out["componentInfo"] = round_deep(node["componentInfo"])
        if node.get("fill") is not None:
            out["fill"] = node["fill"]
        if node.get("borderRadius") is not None:
            out["radius"] = round_deep(node["borderRadius"])
        style = collect_visual_style(node)
        if style:
            out["style"] = style
        flex = compact_flex(node.get("flexContainerInfo"))
        if flex:
            out["flex"] = flex
        if node_type == "text":
            out["text"] = normalize_text_runs(node)
            if node.get("textAlign"):
                out["align"] = node["textAlign"]
            if node.get("textMode"):
                out["mode"] = node["textMode"]
        elif node_type == "path":
            out["vector"] = self.ensure_vector(node.get("path", []) or [])
        elif node_type == "svg_ellipse":
            # keep original fill/stroke/effect in style + node box; no vector reduction
            pass
        children = node.get("children", []) or []
        if children:
            out["children"] = [
                self.normalize_node(
                    child,
                    inside_template=inside_template,
                    template_root_signature=template_root_signature,
                    path_segments=[*path_segments, f"children[{index}]"],
                    scope=scope,
                )
                for index, child in enumerate(children)
            ]
        return out

    def build_templates(self) -> dict[str, Any]:
        templates: dict[str, Any] = {}
        for template_id, meta in self.template_meta.items():
            node = self.signature_nodes[meta["signature"]]
            body = self.normalize_node(
                node,
                inside_template=True,
                template_root_signature=meta["signature"],
                path_segments=[template_id],
                scope=f"template:{template_id}",
            )
            normalized_body = copy.deepcopy(body)
            normalized_body["box"] = [0, 0, normalized_body["box"][2], normalized_body["box"][3]]
            templates[template_id] = {
                "name": meta["name"],
                "count": meta["count"],
                "size": meta["size"],
                "tree": normalized_body,
            }
        return templates

    def convert(self) -> dict[str, Any]:
        self.collect_signatures()
        self.build_template_catalog()
        styles = normalize_style_tokens(self.source.get("dsl", {}).get("styles", {}))
        roots = [
            self.normalize_node(node, path_segments=[f"roots[{index}]"], scope=f"root:{index}")
            for index, node in enumerate(self.source.get("dsl", {}).get("nodes", []))
        ]
        return {
            "format": "render-dsl-hifi@1",
            "meta": {
                "source": str(self.source_path).replace("\\", "/"),
                "sourceRules": self.source.get("rules", []),
                "componentDocumentLinks": self.source.get("componentDocumentLinks", []),
                "intent": "hifi-dashboard-reconstruction",
            },
            "compressionRules": [
                "Keep original hierarchy and relative geometry.",
                "Keep visual-critical fields: fill, effect, opacity, mask, strokeColor, strokeWidth, strokeType, strokeAlign, borderRadius.",
                "Keep text runs instead of collapsing them away.",
                "Deduplicate PATH payloads into assets.vectors without dropping segment-level visual fields.",
                "Only promote highly repeated, large subtrees into templates.",
                "Do not remove fields that materially affect cockpit/dashboard rendering.",
            ],
            "tokens": styles,
            "assets": {"vectors": self.vectors},
            "templates": self.build_templates(),
            "roots": roots,
            "stats": {
                "sourceNodeCount": sum(count_descendants(node) for node in self.source.get("dsl", {}).get("nodes", [])),
                "templateCount": len(self.template_meta),
                "vectorCount": len(self.vectors),
            },
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Path to source DSL JSON")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Path to output hifi DSL JSON")
    parser.add_argument("--pretty", action="store_true", help="Write formatted JSON")
    args = parser.parse_args()

    source = normalize_source_payload(json.loads(args.input.read_text(encoding="utf-8")))
    result = HifiDslCompressor(source, args.input).convert()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None, separators=None if args.pretty else (",", ":"))
    args.output.write_text(rendered, encoding="utf-8")

    source_bytes = len(args.input.read_bytes())
    output_bytes = len(args.output.read_bytes())
    ratio = round(output_bytes / source_bytes, 3) if source_bytes else 0
    print(
        json.dumps(
            {
                "input": str(args.input).replace("\\", "/"),
                "output": str(args.output).replace("\\", "/"),
                "source_bytes": source_bytes,
                "output_bytes": output_bytes,
                "ratio": ratio,
                "template_count": result["stats"]["templateCount"],
                "vector_count": result["stats"]["vectorCount"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
