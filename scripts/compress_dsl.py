#!/usr/bin/env python3
"""Convert a MasterGo-exported DSL JSON into a model-friendly render DSL.

Goals:
- Keep geometry, typography, colors, vectors, and container hierarchy for
  high-fidelity regeneration.
- Reduce token waste by normalizing numeric values and collapsing verbose
  structures.
- Promote repeated subtrees into reusable templates so models can focus on
  structure instead of duplicate payloads.
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
    out = {}
    for source_key, target_key in mapping.items():
        value = flex_info.get(source_key)
        if value not in (None, "", "auto"):
            out[target_key] = round_number(value)
    return out or None


def normalize_style_tokens(styles: dict[str, Any]) -> dict[str, Any]:
    colors: dict[str, Any] = {}
    fonts: dict[str, Any] = {}
    others: dict[str, Any] = {}
    for key, value in styles.items():
        if key.startswith("paint_"):
            colors[key] = value
        elif key.startswith("font_"):
            fonts[key] = value
        else:
            others[key] = value
    return {
        "colors": colors,
        "fonts": fonts,
        "misc": others,
    }


def normalize_text_runs(node: dict[str, Any]) -> dict[str, Any]:
    runs = node.get("text", [])
    colors = node.get("textColor", [])
    if len(runs) == 1 and len(colors) <= 1:
        out = {
            "value": runs[0].get("text", "") if runs else "",
            "font": runs[0].get("font") if runs else None,
        }
        if colors:
            out["color"] = colors[0].get("color")
        return out
    segments = []
    for index, run in enumerate(runs):
        segment: dict[str, Any] = {
            "text": run.get("text", ""),
            "font": run.get("font"),
        }
        if index < len(colors):
            segment["color"] = colors[index].get("color")
        segments.append(segment)
    return {"segments": segments}


def make_short_hash(payload: Any, *, size: int = 10) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(encoded.encode("utf-8")).hexdigest()[:size]


def collect_visual_style(node: dict[str, Any]) -> dict[str, Any] | None:
    style_keys = [
        "opacity",
        "overflow",
        "clipContent",
        "blendMode",
        "shadow",
        "shadows",
        "boxShadow",
        "stroke",
        "strokeColor",
        "strokeWidth",
        "border",
        "gradient",
        "backgroundImage",
        "mask",
        "maskType",
        "blur",
        "backdropBlur",
        "filters",
    ]
    out = {}
    for key in style_keys:
        if key in node and node[key] not in (None, "", [], {}):
            out[key] = round_deep(node[key])
    return out or None


def collect_text_style(node: dict[str, Any]) -> dict[str, Any] | None:
    text_style_keys = [
        "textAlignVertical",
        "lineClamp",
        "ellipsis",
        "maxLines",
        "paragraphSpacing",
        "baselineShift",
    ]
    out = {}
    for key in text_style_keys:
        if key in node and node[key] not in (None, "", [], {}):
            out[key] = round_deep(node[key])
    return out or None


def make_vector_key(path_list: list[dict[str, Any]]) -> str:
    payload = json.dumps(path_list, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def normalize_path_asset(path_list: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_segments = []
    for segment in path_list:
        normalized = {"d": segment.get("data", "")}
        if segment.get("fill") is not None:
            normalized["fill"] = segment["fill"]
        normalized_segments.append(normalized)
    return {"segments": normalized_segments}


def subtree_signature(node: dict[str, Any]) -> str:
    def _sig(current: dict[str, Any]) -> Any:
        node_type = current.get("type")
        base: dict[str, Any] = {
            "type": node_type,
            "box": [
                round_number(current.get("layoutStyle", {}).get("width", 0)),
                round_number(current.get("layoutStyle", {}).get("height", 0)),
            ],
        }
        if current.get("fill") is not None:
            base["fill"] = current["fill"]
        if current.get("borderRadius") is not None:
            base["radius"] = current["borderRadius"]
        if current.get("text"):
            base["text_font"] = [item.get("font") for item in current.get("text", [])]
            base["text_len"] = [len(item.get("text", "")) for item in current.get("text", [])]
        if current.get("textColor"):
            base["text_color"] = [item.get("color") for item in current.get("textColor", [])]
        if current.get("path"):
            base["path"] = normalize_path_asset(current["path"])
        flex = compact_flex(current.get("flexContainerInfo"))
        if flex:
            base["flex"] = flex
        children = current.get("children", [])
        if children:
            base["children"] = [_sig(child) for child in children]
        return base

    return json.dumps(_sig(node), ensure_ascii=False, sort_keys=True)


def count_descendants(node: dict[str, Any]) -> int:
    return 1 + sum(count_descendants(child) for child in node.get("children", []))


class RenderDslConverter:
    def __init__(self, source: dict[str, Any], source_path: Path) -> None:
        self.source = source
        self.source_path = source_path
        self.vectors: dict[str, dict[str, Any]] = {}
        self.vector_aliases: dict[str, str] = {}
        self.signature_counts: Counter[str] = Counter()
        self.signature_nodes: dict[str, dict[str, Any]] = {}
        self.template_ids: dict[str, str] = {}
        self.template_meta: dict[str, dict[str, Any]] = {}

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

    def collect_signatures(self) -> None:
        def walk(node: dict[str, Any]) -> None:
            signature = subtree_signature(node)
            self.signature_counts[signature] += 1
            self.signature_nodes.setdefault(signature, node)
            for child in node.get("children", []):
                walk(child)

        for root in self.source["dsl"].get("nodes", []):
            walk(root)

    def build_template_catalog(self) -> None:
        candidates: list[tuple[int, int, str]] = []
        for signature, count in self.signature_counts.items():
            node = self.signature_nodes[signature]
            size = count_descendants(node)
            if count >= 2 and size >= 4 and node.get("children"):
                candidates.append((size * count, size, signature))
        candidates.sort(reverse=True)

        for index, (_, size, signature) in enumerate(candidates, start=1):
            template_id = f"tpl_{index}"
            self.template_ids[signature] = template_id
            node = self.signature_nodes[signature]
            self.template_meta[template_id] = {
                "signature": signature,
                "count": self.signature_counts[signature],
                "size": size,
                "name": node.get("name"),
            }

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
            template_id = self.template_ids[signature]
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
                "use": template_id,
                "name": node.get("name"),
                "box": compact_box(node.get("layoutStyle", {})),
                "sourceId": node.get("id"),
            }

        node_type = node.get("type", "").lower()
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
            out["radius"] = node["borderRadius"]
        visual_style = collect_visual_style(node)
        if visual_style:
            out["style"] = visual_style
        flex = compact_flex(node.get("flexContainerInfo"))
        if flex:
            out["flex"] = flex
        if node_type == "text":
            out["text"] = normalize_text_runs(node)
            if node.get("textAlign"):
                out["align"] = node["textAlign"]
            if node.get("textMode"):
                out["mode"] = node["textMode"]
            text_style = collect_text_style(node)
            if text_style:
                out["textStyle"] = text_style
        elif node_type == "path":
            out["vector"] = self.ensure_vector(node.get("path", []))
        children = node.get("children", [])
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
        templates = {}
        for template_id, meta in self.template_meta.items():
            node = self.signature_nodes[meta["signature"]]
            template_body = self.normalize_node(
                node,
                inside_template=True,
                template_root_signature=meta["signature"],
                path_segments=[template_id],
                scope=f"template:{template_id}",
            )
            body = copy.deepcopy(template_body)
            body["box"] = [0, 0, body["box"][2], body["box"][3]]
            templates[template_id] = {
                "name": meta["name"],
                "count": meta["count"],
                "tree": body,
            }
        return templates

    def convert(self) -> dict[str, Any]:
        self.collect_signatures()
        self.build_template_catalog()
        styles = normalize_style_tokens(self.source["dsl"].get("styles", {}))
        roots = [
            self.normalize_node(
                node,
                path_segments=[f"roots[{index}]"],
                scope=f"root:{index}",
            )
            for index, node in enumerate(self.source["dsl"].get("nodes", []))
        ]

        result = {
            "format": "render-dsl@1",
            "meta": {
                "source": str(self.source_path).replace("\\", "/"),
                "sourceRules": self.source.get("rules", []),
                "componentDocumentLinks": self.source.get("componentDocumentLinks", []),
            },
            "compressionRules": [
                "Keep frame/layer/text/path hierarchy and relative coordinates.",
                "Round numeric geometry to 2 decimals and coerce integer-like floats to ints.",
                "Collapse single-run text and textColor arrays into scalar text payloads.",
                "Deduplicate vector path payloads into assets.vectors and reference them by id.",
                "Promote repeated subtrees with 4+ descendants into templates and use instance nodes.",
                "Drop source-only fields such as id and empty children arrays.",
            ],
            "tokens": styles,
            "assets": {
                "vectors": self.vectors,
            },
            "templates": self.build_templates(),
            "roots": roots,
            "stats": {
                "sourceNodeCount": sum(
                    count_descendants(node) for node in self.source["dsl"].get("nodes", [])
                ),
                "templateCount": len(self.template_meta),
                "vectorCount": len(self.vectors),
            },
        }
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Path to source DSL JSON")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("docs/render-dsl.json"),
        help="Path to output render DSL JSON",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Write formatted JSON instead of compact JSON",
    )
    args = parser.parse_args()

    source = normalize_source_payload(json.loads(args.input.read_text(encoding="utf-8")))
    converter = RenderDslConverter(source, args.input)
    result = converter.convert()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.pretty:
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
    else:
        rendered = json.dumps(result, ensure_ascii=False, separators=(",", ":"))

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
