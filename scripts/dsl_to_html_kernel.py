#!/usr/bin/env python3
"""Generic HTML renderer kernel for normalized DSL trees."""

from __future__ import annotations

import html
import json
import math
import os
import re
from pathlib import Path
from typing import Any


PATH_NUMBER_RE = re.compile(r"-?\d*\.?\d+(?:e[-+]?\d+)?", re.IGNORECASE)
BOX_SHADOW_RE = re.compile(
    r"^(?:(inset)\s+)?"
    r"(-?\d*\.?\d+)px\s+"
    r"(-?\d*\.?\d+)px\s+"
    r"(\d*\.?\d+)px"
    r"(?:\s+(-?\d*\.?\d+)px)?"
    r"\s+(.+?)$",
    re.IGNORECASE,
)


def append_px(value: Any) -> str:
    if value in (None, "", "auto"):
        return "auto"
    if isinstance(value, (int, float)):
        return f"{value}px"
    return str(value)


def escape_attr(value: Any) -> str:
    return html.escape(str(value), quote=True)


def sanitize_token(token_id: str) -> str:
    return token_id.replace(":", "-").replace("/", "-").replace(" ", "-").lower()


def infer_font_weight(style_value: Any) -> str:
    text = str(style_value or "").lower()
    if "bold" in text:
        return "700"
    if "medium" in text:
        return "500"
    if "light" in text:
        return "300"
    return "400"


def sanitize_css_value(value: str) -> str:
    return value.replace("NaN%", "0%").replace("NaN", "0")


def _get_style(node: dict[str, Any], key: str) -> Any:
    if key in node:
        return node.get(key)
    return (node.get("style") or {}).get(key)


def split_css_args(value: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for ch in value:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(ch)
    if current:
        parts.append("".join(current).strip())
    return parts


def parse_linear_gradient(value: str) -> tuple[dict[str, str], list[tuple[str, str]]] | None:
    value = sanitize_css_value(value).strip()
    if not value.startswith("linear-gradient(") or not value.endswith(")"):
        return None
    inner = value[len("linear-gradient("):-1]
    parts = split_css_args(inner)
    if len(parts) < 2:
        return None
    angle = 180.0
    start_idx = 0
    if parts[0].endswith("deg"):
        try:
            angle = float(parts[0][:-3])
            start_idx = 1
        except ValueError:
            pass
    rad = math.radians((angle - 90) % 360)
    x1 = 50 - math.cos(rad) * 50
    y1 = 50 - math.sin(rad) * 50
    x2 = 50 + math.cos(rad) * 50
    y2 = 50 + math.sin(rad) * 50
    stops: list[tuple[str, str]] = []
    raw_stops = parts[start_idx:]
    for index, stop in enumerate(raw_stops):
        pieces = stop.rsplit(" ", 1)
        if len(pieces) == 2 and pieces[1].endswith("%"):
            color, offset = pieces[0].strip(), pieces[1].strip()
        else:
            offset = f"{0 if len(raw_stops) == 1 else round(index * 100 / (len(raw_stops) - 1), 2)}%"
            color = stop.strip()
        stops.append((color, offset))
    return {
        "x1": f"{x1:.2f}%",
        "y1": f"{y1:.2f}%",
        "x2": f"{x2:.2f}%",
        "y2": f"{y2:.2f}%",
    }, stops


def parse_radial_gradient(value: str) -> tuple[dict[str, str], list[tuple[str, str]]] | None:
    value = sanitize_css_value(value).strip()
    if not value.startswith("radial-gradient(") or not value.endswith(")"):
        return None
    inner = value[len("radial-gradient("):-1]
    parts = split_css_args(inner)
    if len(parts) < 2:
        return None
    descriptor = parts[0]
    start_idx = 1
    attrs = {
        "cx": "50%",
        "cy": "50%",
        "r": "50%",
        "fx": "50%",
        "fy": "50%",
    }
    match = re.search(
        r"(?P<rx>\d*\.?\d+%)\s+(?P<ry>\d*\.?\d+%)\s+at\s+(?P<cx>\d*\.?\d+%)\s+(?P<cy>\d*\.?\d+%)",
        descriptor,
    )
    if match:
        attrs["cx"] = match.group("cx")
        attrs["cy"] = match.group("cy")
        attrs["fx"] = match.group("cx")
        attrs["fy"] = match.group("cy")
        rx = float(match.group("rx").rstrip("%"))
        ry = float(match.group("ry").rstrip("%"))
        attrs["r"] = f"{max(rx, ry):.2f}%"
    else:
        start_idx = 0
    stops: list[tuple[str, str]] = []
    raw_stops = parts[start_idx:]
    for index, stop in enumerate(raw_stops):
        pieces = stop.rsplit(" ", 1)
        if len(pieces) == 2 and pieces[1].endswith("%"):
            color, offset = pieces[0].strip(), pieces[1].strip()
        else:
            offset = f"{0 if len(raw_stops) == 1 else round(index * 100 / (len(raw_stops) - 1), 2)}%"
            color = stop.strip()
        stops.append((color, offset))
    return attrs, stops


def parse_length_or_percent(value: str, start: float, length: float) -> float:
    text = str(value or "").strip()
    if text.endswith("%"):
        try:
            return start + length * float(text[:-1]) / 100.0
        except ValueError:
            return start
    try:
        return float(text)
    except ValueError:
        return start


def radial_radius_to_user_space(value: str, width: float, height: float) -> float:
    text = str(value or "").strip()
    if text.endswith("%"):
        try:
            return max(width, height) * float(text[:-1]) / 100.0
        except ValueError:
            return max(width, height)
    try:
        return float(text)
    except ValueError:
        return max(width, height)


def flatten_box_shadow(effect_values: list[str]) -> list[str]:
    merged: dict[str, list[str]] = {}
    ordered: list[str] = []
    for raw in effect_values:
        if ":" not in raw:
            continue
        prop, value = raw.split(":", 1)
        prop = prop.strip()
        value = value.strip().rstrip(";")
        if prop not in merged:
            merged[prop] = []
            ordered.append(prop)
        if value:
            merged[prop].append(value)
    lines: list[str] = []
    for prop in ordered:
        values = merged[prop]
        if not values:
            continue
        css_value = ", ".join(values) if prop == "box-shadow" else values[-1]
        lines.append(f"{prop}: {css_value};")
    return lines


def parse_box_shadow(value: str) -> dict[str, Any] | None:
    match = BOX_SHADOW_RE.match(value.strip())
    if not match:
        return None
    inset, x, y, blur, spread, color = match.groups()
    return {
        "inset": bool(inset),
        "x": float(x),
        "y": float(y),
        "blur": float(blur),
        "spread": float(spread or 0),
        "color": sanitize_css_value(color.strip()),
    }


def color_to_rgba(color: str) -> tuple[float, float, float, float]:
    text = sanitize_css_value(color).strip()
    if text.startswith("rgba(") and text.endswith(")"):
        parts = [part.strip() for part in text[5:-1].split(",")]
        if len(parts) == 4:
            return (
                float(parts[0]) / 255,
                float(parts[1]) / 255,
                float(parts[2]) / 255,
                float(parts[3]),
            )
    if text.startswith("rgb(") and text.endswith(")"):
        parts = [part.strip() for part in text[4:-1].split(",")]
        if len(parts) == 3:
            return (
                float(parts[0]) / 255,
                float(parts[1]) / 255,
                float(parts[2]) / 255,
                1.0,
            )
    if text.startswith("#"):
        value = text[1:]
        if len(value) == 3:
            value = "".join(ch * 2 for ch in value)
        if len(value) == 6:
            return (
                int(value[0:2], 16) / 255,
                int(value[2:4], 16) / 255,
                int(value[4:6], 16) / 255,
                1.0,
            )
    return (1.0, 1.0, 1.0, 1.0)


def rgba_to_matrix_values(color: str) -> str:
    r, g, b, a = color_to_rgba(color)
    return f"0 0 0 0 {r} 0 0 0 0 {g} 0 0 0 0 {b} 0 0 0 {a} 0"


def path_bounds_from_d(path_data: str) -> tuple[float, float, float, float] | None:
    numbers = [float(token) for token in PATH_NUMBER_RE.findall(path_data)]
    if len(numbers) < 2:
        return None
    xs = numbers[0::2]
    ys = numbers[1::2]
    if not xs or not ys:
        return None
    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)
    return min_x, min_y, max(max_x - min_x, 1.0), max(max_y - min_y, 1.0)


class BaseDslHtmlAdapter:
    """Adapter interface between arbitrary DSL payloads and the generic renderer."""

    css_prefix = "dsl"
    html_lang = "zh-CN"

    def normalize(self, payload: dict[str, Any]) -> dict[str, Any]:
        return payload

    def get_roots(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        return data.get("roots", [])

    def get_title(self, data: dict[str, Any]) -> str:
        roots = self.get_roots(data)
        if roots and roots[0].get("name"):
            return str(roots[0]["name"])
        return str(data.get("format", "dsl-html"))

    def get_base_css(self) -> str:
        prefix = self.css_prefix
        return f"""
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; width: 100%; height: 100%; overflow: hidden; }}
body {{
  background: #000;
  color: #fff;
  font-family: "AlibabaPuHuiTi", "PingFang SC", "Microsoft YaHei", sans-serif;
}}
.{prefix}-shell {{
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  position: relative;
  background: #000;
}}
.{prefix}-stage {{
  position: absolute;
  left: 50%;
  top: 50%;
  isolation: isolate;
  transform-origin: center center;
  will-change: transform;
}}
.{prefix}-node {{
  position: absolute;
  overflow: visible;
}}
.{prefix}-frame,
.{prefix}-group,
.{prefix}-layer,
.{prefix}-instance {{
  display: block;
}}
.{prefix}-text {{
  margin: 0;
  padding: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  text-rendering: geometricPrecision;
}}
.{prefix}-vector {{
  display: block;
  overflow: visible;
}}
.{prefix}-vector > svg {{
  display: block;
  width: 100%;
  height: 100%;
  overflow: visible;
}}
.{prefix}-vector > img {{
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
}}
.{prefix}-library-host {{
  display: flex;
  align-items: center;
  justify-content: stretch;
}}
.{prefix}-library-host > .{prefix}-library-mount {{
  width: 100%;
  height: 100%;
}}
.{prefix}-manual-zone__inner {{
  width: calc(100% - 16px);
  min-height: calc(100% - 16px);
  margin: 8px;
  border: 1px dashed rgba(255, 180, 0, 0.65);
  background: rgba(255, 180, 0, 0.06);
  color: #ffd27a;
  display: grid;
  place-items: center;
  gap: 6px;
  text-align: center;
  padding: 8px;
  font: 12px/1.4 "SFMono-Regular", "Consolas", monospace;
}}
""".strip()

    def get_stage_size(self, data: dict[str, Any]) -> tuple[int, int]:
        width = 0
        height = 0
        for node in self.get_roots(data):
            x, y, w, h = [float(item) for item in node.get("box", [0, 0, 0, 0])]
            width = max(width, int(x + w))
            height = max(height, int(y + h))
        return width, height

    def get_children(self, node: dict[str, Any]) -> list[dict[str, Any]]:
        return node.get("children", []) or []

    def is_alpha_mask_node(self, node: dict[str, Any]) -> bool:
        return str(_get_style(node, "mask") or "").strip().lower() == "alpha"

    def get_mask_nodes(self, node: dict[str, Any]) -> list[dict[str, Any]]:
        return [child for child in self.get_children(node) if self.is_alpha_mask_node(child)]

    def get_render_children(self, node: dict[str, Any]) -> list[dict[str, Any]]:
        return [child for child in self.get_children(node) if not self.is_alpha_mask_node(child)]

    def get_node_id(self, node: dict[str, Any]) -> str:
        return str(node.get("id", ""))

    def get_node_name(self, node: dict[str, Any]) -> str:
        return str(node.get("name", ""))

    def get_node_kind(self, node: dict[str, Any]) -> str:
        return str(node.get("kind", "layer"))

    def has_vector(self, node: dict[str, Any]) -> bool:
        return bool(node.get("vector"))

    def is_vector_shape_leaf(self, node: dict[str, Any]) -> bool:
        return self.has_vector(node) or self.get_node_kind(node) in {"svg_ellipse"}

    def is_pure_vector_art_group(self, node: dict[str, Any], data: dict[str, Any]) -> bool:
        kind = self.get_node_kind(node)
        if kind not in {"group", "frame", "instance"}:
            return False
        if self.is_vector_shape_leaf(node):
            return False
        if self.get_manual_zone(node, data) or self.get_asset_plan(node, data) or self.get_library_plan(node, data):
            return False
        children = self.get_children(node)
        if not children:
            return False

        vector_leaf_count = 0

        def walk(current: dict[str, Any]) -> bool:
            nonlocal vector_leaf_count
            if self.is_vector_shape_leaf(current):
                vector_leaf_count += 1
                return True
            current_kind = self.get_node_kind(current)
            if current_kind == "text":
                return False
            nested = self.get_children(current)
            if current_kind not in {"group", "frame", "instance"} or not nested:
                return False
            return all(walk(child) for child in nested)

        return all(walk(child) for child in children) and vector_leaf_count > 0

    def get_svg_bounds(self, node: dict[str, Any], d_values: list[str] | None = None) -> tuple[float, float, float, float]:
        if d_values:
            bounds = [path_bounds_from_d(d) for d in d_values]
            bounds = [item for item in bounds if item is not None]
            if bounds:
                min_x = min(item[0] for item in bounds)
                min_y = min(item[1] for item in bounds)
                max_x = max(item[0] + item[2] for item in bounds)
                max_y = max(item[1] + item[3] for item in bounds)
                return min_x, min_y, max(max_x - min_x, 1.0), max(max_y - min_y, 1.0)
        x, y, w, h = node.get("box", [0, 0, 0, 0])
        return float(x or 0), float(y or 0), max(float(w or 0), 1.0), max(float(h or 0), 1.0)

    def build_svg_paint_ref(
        self,
        *,
        node_id: str,
        defs: list[str],
        fill: str,
        gradient_id: str,
        bounds: tuple[float, float, float, float],
    ) -> str:
        fill = fill.strip()
        min_x, min_y, width, height = bounds
        if fill.startswith("linear-gradient("):
            parsed = parse_linear_gradient(fill)
            if not parsed:
                return "#8DD2FF"
            attrs, stops = parsed
            x1 = parse_length_or_percent(attrs["x1"], min_x, width)
            y1 = parse_length_or_percent(attrs["y1"], min_y, height)
            x2 = parse_length_or_percent(attrs["x2"], min_x, width)
            y2 = parse_length_or_percent(attrs["y2"], min_y, height)
            stop_markup = "".join(
                f'<stop offset="{escape_attr(offset)}" stop-color="{escape_attr(color)}"></stop>'
                for color, offset in stops
            )
            defs.append(
                f'<linearGradient id="{escape_attr(gradient_id)}" gradientUnits="userSpaceOnUse" '
                f'x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}">{stop_markup}</linearGradient>'
            )
            return f"url(#{gradient_id})"
        if fill.startswith("radial-gradient("):
            parsed = parse_radial_gradient(fill)
            if not parsed:
                return "transparent"
            attrs, stops = parsed
            cx = parse_length_or_percent(attrs["cx"], min_x, width)
            cy = parse_length_or_percent(attrs["cy"], min_y, height)
            fx = parse_length_or_percent(attrs["fx"], min_x, width)
            fy = parse_length_or_percent(attrs["fy"], min_y, height)
            r = radial_radius_to_user_space(attrs["r"], width, height)
            stop_markup = "".join(
                f'<stop offset="{escape_attr(offset)}" stop-color="{escape_attr(color)}"></stop>'
                for color, offset in stops
            )
            defs.append(
                f'<radialGradient id="{escape_attr(gradient_id)}" gradientUnits="userSpaceOnUse" '
                f'cx="{cx}" cy="{cy}" r="{r}" fx="{fx}" fy="{fy}">{stop_markup}</radialGradient>'
            )
            return f"url(#{gradient_id})"
        return fill

    def build_shape_fill_markup(
        self,
        *,
        node: dict[str, Any],
        data: dict[str, Any],
        defs: list[str],
        segment_index: int,
        fill_values: list[str],
        bounds: tuple[float, float, float, float] | None = None,
    ) -> list[str]:
        node_id = self.get_node_id(node) or "node"
        paint_bounds = bounds or self.get_svg_bounds(node)
        rendered: list[str] = []
        for fill_index, fill_value in enumerate(fill_values):
            gradient_id = f"{node_id}-grad-{segment_index}-{fill_index}"
            rendered.append(
                self.build_svg_paint_ref(
                    node_id=node_id,
                    defs=defs,
                    fill=fill_value,
                    gradient_id=gradient_id,
                    bounds=paint_bounds,
                )
            )
        return rendered

    def should_merge_group_as_svg(self, node: dict[str, Any], data: dict[str, Any]) -> bool:
        node_plan = self.get_node_plan(node, data) or {}
        component_plan = self.get_component_plan(node, data) or {}
        if str(node_plan.get("renderer") or "") == "merged-svg":
            return True
        if str(component_plan.get("renderer") or "") == "merged-svg":
            return True
        if bool(node_plan.get("mergeAsSvg")) or bool(component_plan.get("mergeAsSvg")):
            return True
        if self.is_pure_vector_art_group(node, data):
            return True
        return False

    def can_merge_group_as_svg(self, node: dict[str, Any], data: dict[str, Any]) -> bool:
        if not self.should_merge_group_as_svg(node, data):
            return False
        if self.has_vector(node):
            return False
        if self.get_manual_zone(node, data) or self.get_asset_plan(node, data):
            return False
        kind = self.get_node_kind(node)
        if kind not in {"group", "frame", "instance"}:
            return False
        children = self.get_children(node)
        if not children:
            return False

        def _mergeable(current: dict[str, Any]) -> bool:
            if self.is_vector_shape_leaf(current):
                return True
            if self.get_node_kind(current) not in {"group", "frame", "instance"}:
                return False
            nested = self.get_children(current)
            return bool(nested) and all(_mergeable(child) for child in nested)

        return all(_mergeable(child) for child in children)

    def get_render_plan(self, data: dict[str, Any]) -> dict[str, Any]:
        return data.get("renderPlan") or {}

    def get_render_context(self, data: dict[str, Any]) -> dict[str, Any]:
        return data.get("__renderContext") or {}

    def get_node_index(self, data: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return (self.get_render_context(data).get("nodeIndex") or {})

    def get_parent_index(self, data: dict[str, Any]) -> dict[str, str]:
        return (self.get_render_context(data).get("parentIndex") or {})

    def get_node_by_id(self, node_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        return self.get_node_index(data).get(node_id)

    def get_parent_node(self, node: dict[str, Any], data: dict[str, Any]) -> dict[str, Any] | None:
        parent_id = str(self.get_parent_index(data).get(self.get_node_id(node)) or "")
        if not parent_id:
            return None
        return self.get_node_by_id(parent_id, data)

    def get_component_plan(self, node: dict[str, Any], data: dict[str, Any]) -> dict[str, Any] | None:
        node_id = self.get_node_id(node)
        for item in self.get_render_plan(data).get("componentPlans", []) or []:
            if str(item.get("rootNodeId") or "") == node_id:
                return item
        return None

    def get_node_plan(self, node: dict[str, Any], data: dict[str, Any]) -> dict[str, Any] | None:
        node_id = self.get_node_id(node)
        for item in self.get_render_plan(data).get("nodePlans", []) or []:
            if str(item.get("nodeId") or "") == node_id:
                return item
        return None

    def get_layout_decision(self, node: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        decision: dict[str, Any] = {}
        component_plan = self.get_component_plan(node, data) or {}
        node_plan = self.get_node_plan(node, data) or {}
        if isinstance(component_plan.get("layoutDecision"), dict):
            decision.update(component_plan.get("layoutDecision") or {})
        if isinstance(node_plan.get("layoutDecision"), dict):
            decision.update(node_plan.get("layoutDecision") or {})
        return decision

    def get_manual_zone(self, node: dict[str, Any], data: dict[str, Any]) -> dict[str, Any] | None:
        node_id = self.get_node_id(node)
        for item in self.get_render_plan(data).get("manualZones", []) or []:
            if str(item.get("rootNodeId") or "") == node_id:
                return item
        return None

    def get_asset_plan(self, node: dict[str, Any], data: dict[str, Any]) -> dict[str, Any] | None:
        node_id = self.get_node_id(node)
        for item in self.get_render_plan(data).get("assetPlans", []) or []:
            if str(item.get("nodeId") or "") == node_id:
                return item
        return None

    def get_asset_output_path(self, asset_plan: dict[str, Any], data: dict[str, Any]) -> Path | None:
        output_path = str(asset_plan.get("outputPath") or "").strip()
        if not output_path:
            return None
        prototype_dir = str(self.get_render_context(data).get("prototypeDir") or "").strip()
        if not prototype_dir:
            return None
        return Path(prototype_dir) / output_path

    def get_asset_src(self, asset_path: Path, data: dict[str, Any]) -> str:
        output_dir = str(self.get_render_context(data).get("outputDir") or "").strip()
        if not output_dir:
            return asset_path.name
        return os.path.relpath(asset_path, output_dir).replace("\\", "/")

    def get_library_plan(self, node: dict[str, Any], data: dict[str, Any]) -> dict[str, Any] | None:
        node_id = self.get_node_id(node)
        for item in self.get_render_plan(data).get("libraryPlans", []) or []:
            if str(item.get("nodeId") or "") == node_id:
                return item
        node_plan = self.get_node_plan(node, data) or {}
        if str(node_plan.get("library") or "") != "custom" and node_plan.get("libraryComponent"):
            return {
                "nodeId": node_id,
                "library": node_plan.get("library"),
                "libraryComponent": node_plan.get("libraryComponent"),
                "componentType": node_plan.get("componentType"),
                "props": node_plan.get("props") or {},
                "mountStrategy": "vue-runtime-cdn",
            }
        return None

    def get_alignment_plans(self, node: dict[str, Any], data: dict[str, Any]) -> list[dict[str, Any]]:
        node_id = self.get_node_id(node)
        return [
            item
            for item in self.get_render_plan(data).get("alignmentPlans", []) or []
            if str(item.get("nodeId") or "") == node_id
        ]

    def build_attrs(self, node: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        attrs = {
            "class": f'{self.css_prefix}-node {self.css_prefix}-{self.get_node_kind(node)}',
            "data-node-id": self.get_node_id(node),
            "data-node-name": self.get_node_name(node),
        }
        class_names = [str(attrs["class"])]
        component_plan = self.get_component_plan(node, data)
        node_plan = self.get_node_plan(node, data)
        manual_zone = self.get_manual_zone(node, data)
        library_plan = self.get_library_plan(node, data)
        alignment_plans = self.get_alignment_plans(node, data)
        if component_plan:
            html_plan = component_plan.get("html") or {}
            if html_plan.get("className"):
                class_names.append(str(html_plan["className"]))
            if component_plan.get("renderer"):
                attrs["data-component-renderer"] = str(component_plan["renderer"])
            if component_plan.get("phase"):
                attrs["data-render-phase"] = str(component_plan["phase"])
        if node_plan:
            html_plan = node_plan.get("html") or {}
            if html_plan.get("className"):
                class_names.append(str(html_plan["className"]))
            if node_plan.get("renderer"):
                attrs["data-node-renderer"] = str(node_plan["renderer"])
            if node_plan.get("phase"):
                attrs["data-render-phase"] = str(node_plan["phase"])
        if library_plan:
            attrs["data-library"] = str(library_plan.get("library") or "")
            attrs["data-library-component"] = str(library_plan.get("libraryComponent") or "")
            class_names.append(f"{self.css_prefix}-library-host")
        if alignment_plans:
            attrs["data-alignment-rules"] = ",".join(
                str(item.get("ruleType") or "") for item in alignment_plans if item.get("ruleType")
            )
        if manual_zone:
            attrs["data-manual-zone"] = str(manual_zone.get("zoneId") or self.get_node_id(node))
            class_names.append(f"{self.css_prefix}-manual-zone")
        attrs["class"] = " ".join(dict.fromkeys(part for part in class_names if part))
        return attrs

    def get_html_tag(self, node: dict[str, Any], data: dict[str, Any]) -> str:
        node_plan = self.get_node_plan(node, data)
        if node_plan:
            html_plan = node_plan.get("html") or {}
            tag = str(html_plan.get("tag") or "").strip()
            if tag:
                return tag
        component_plan = self.get_component_plan(node, data)
        if component_plan:
            html_plan = component_plan.get("html") or {}
            tag = str(html_plan.get("tag") or "").strip()
            if tag:
                return tag
        return "div"

    def render_token_vars(self, data: dict[str, Any]) -> str:
        colors = data.get("tokens", {}).get("colors", {})
        fonts = data.get("tokens", {}).get("fonts", {})
        lines = [":root {"]
        for token_id, token in colors.items():
            values = token.get("value") or []
            if not values:
                continue
            first = values[0]
            if isinstance(first, str):
                lines.append(f"  --{sanitize_token(token_id)}: {sanitize_css_value(first)};")
        for token_id, token in fonts.items():
            font = token.get("value") or {}
            if font.get("family"):
                lines.append(f'  --{sanitize_token(token_id)}-family: "{font["family"]}";')
            if font.get("size") is not None:
                lines.append(f"  --{sanitize_token(token_id)}-size: {append_px(font['size'])};")
        lines.append("}")
        return "\n".join(lines)

    def build_css_rule(self, node: dict[str, Any], data: dict[str, Any]) -> str:
        node_id = self.get_node_id(node)
        x, y, w, h = node.get("box", [0, 0, 0, 0])
        layout_decision = self.get_layout_decision(node, data)
        positioning = layout_decision.get("positioning") or {}
        if str(positioning.get("mode") or "") == "center-in-parent":
            parent = self.get_parent_node(node, data)
            if parent:
                _, _, pw, ph = parent.get("box", [0, 0, 0, 0])
                axis = str(positioning.get("axis") or "both")
                if axis in {"x", "both"}:
                    x = (float(pw or 0) - float(w or 0)) / 2.0
                if axis in {"y", "both"}:
                    y = (float(ph or 0) - float(h or 0)) / 2.0
        lines = [f'[data-node-id="{node_id}"] {{']
        if self.is_alpha_mask_node(node):
            lines.append("  display: none;")
            lines.append("}")
            return "\n".join(lines)
        lines.append(f"  left: {append_px(x)};")
        lines.append(f"  top: {append_px(y)};")
        lines.append(f"  width: {append_px(w)};")
        lines.append(f"  height: {append_px(h)};")

        fills = self.resolve_fill_list(data, _get_style(node, "fill"))
        if fills:
            image_layers = [value for value in fills if value.startswith("url(")]
            if image_layers:
                lines.append(f"  background-image: {', '.join(image_layers)};")
                lines.append("  background-repeat: no-repeat;")
                lines.append("  background-size: 100% 100%;")
                lines.append("  background-position: center;")
            gradient_layers = [value for value in fills if not value.startswith("url(")]
            if gradient_layers and self.get_node_kind(node) != "text":
                lines.append(f"  background: {', '.join(gradient_layers)};")

        radius = _get_style(node, "radius")
        if radius is not None:
            lines.append(f"  border-radius: {radius};")

        style = node.get("style") or {}
        opacity = _get_style(node, "opacity")
        if opacity not in (None, ""):
            lines.append(f"  opacity: {opacity};")
        stroke_color = self.resolve_fill_list(data, _get_style(node, "strokeColor"))
        stroke_width = _get_style(node, "strokeWidth")
        if stroke_color and stroke_width not in (None, "", 0, "0"):
            lines.append(
                f"  border: {stroke_width} {_get_style(node, 'strokeType') or 'solid'} {stroke_color[0]};"
            )
            if _get_style(node, "strokeAlign") == "inside":
                lines.append(f"  box-shadow: inset 0 0 0 {stroke_width} {stroke_color[0]};")

        effect_token = _get_style(node, "effect")
        if effect_token and self.should_apply_effect(node, data):
            lines.extend(
                f"  {rule}" for rule in flatten_box_shadow(self.resolve_effect(data, effect_token))
            )

        lines.extend(self.vector_css_overrides(node, data))
        lines.extend(self.node_css_overrides(node, data))
        lines.extend(self.plan_css_overrides(node, data))

        if self.get_node_kind(node) == "text":
            lines.extend(self.build_text_css(node, data))

        lines.append("}")
        return "\n".join(lines)

    def build_alpha_mask_css(self, node: dict[str, Any], data: dict[str, Any]) -> list[str]:
        mask_nodes = self.get_mask_nodes(node)
        if not mask_nodes:
            return []
        mask = mask_nodes[0]
        kind = self.get_node_kind(mask)
        x, y, w, h = mask.get("box", [0, 0, 0, 0])

        # 只在必要时添加overflow: hidden
        # 对于某些情况（如头像容器），overflow: hidden可能会遮挡内容
        lines = []

        if kind == "svg_ellipse":
            cx = float(x or 0) + float(w or 0) / 2.0
            cy = float(y or 0) + float(h or 0) / 2.0
            rx = max(float(w or 0) / 2.0, 0.0)
            ry = max(float(h or 0) / 2.0, 0.0)
            lines.append(f"  clip-path: ellipse({append_px(rx)} {append_px(ry)} at {append_px(cx)} {append_px(cy)});")
            lines.append(
                f"  -webkit-clip-path: ellipse({append_px(rx)} {append_px(ry)} at {append_px(cx)} {append_px(cy)});"
            )
            return lines
        if kind in {"layer", "frame", "group", "instance"} and not self.has_vector(mask):
            top = max(float(y or 0), 0.0)
            left = max(float(x or 0), 0.0)
            right = max(float(node.get('box', [0, 0, 0, 0])[2] or 0) - (float(x or 0) + float(w or 0)), 0.0)
            bottom = max(float(node.get('box', [0, 0, 0, 0])[3] or 0) - (float(y or 0) + float(h or 0)), 0.0)
            radius = _get_style(mask, "radius")
            if radius is not None:
                lines.append(
                    f"  clip-path: inset({append_px(top)} {append_px(right)} {append_px(bottom)} {append_px(left)} round {radius});"
                )
                lines.append(
                    f"  -webkit-clip-path: inset({append_px(top)} {append_px(right)} {append_px(bottom)} {append_px(left)} round {radius});"
                )
            elif top or right or bottom or left:
                lines.append(
                    f"  clip-path: inset({append_px(top)} {append_px(right)} {append_px(bottom)} {append_px(left)});"
                )
                lines.append(
                    f"  -webkit-clip-path: inset({append_px(top)} {append_px(right)} {append_px(bottom)} {append_px(left)});"
                )
            return lines
        return lines

    def collect_relative_boxes(
        self,
        node: dict[str, Any],
        *,
        scope: str,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
    ) -> list[tuple[float, float, float, float]]:
        boxes: list[tuple[float, float, float, float]] = []
        children = self.get_children(node)
        if scope == "direct-children":
            for child in children:
                x, y, w, h = child.get("box", [0, 0, 0, 0])
                boxes.append((float(x or 0), float(y or 0), float(w or 0), float(h or 0)))
            return boxes
        for child in children:
            x, y, w, h = child.get("box", [0, 0, 0, 0])
            abs_x = offset_x + float(x or 0)
            abs_y = offset_y + float(y or 0)
            if scope == "vector-leaves" and self.has_vector(child):
                boxes.append((abs_x, abs_y, float(w or 0), float(h or 0)))
                continue
            boxes.extend(self.collect_relative_boxes(child, scope=scope, offset_x=abs_x, offset_y=abs_y))
        return boxes

    def render_layout_decision_css(self, node: dict[str, Any], data: dict[str, Any]) -> list[str]:
        layout_decision = self.get_layout_decision(node, data)
        content_alignment = layout_decision.get("contentAlignment") or {}
        if str(content_alignment.get("mode") or "") != "center-children-bounds":
            return []
        children = self.get_children(node)
        if not children:
            return []
        scope = str(content_alignment.get("scope") or "direct-children")
        boxes = self.collect_relative_boxes(node, scope=scope)
        if not boxes:
            return []
        _, _, width, height = node.get("box", [0, 0, 0, 0])
        min_x = min(item[0] for item in boxes)
        min_y = min(item[1] for item in boxes)
        max_x = max(item[0] + item[2] for item in boxes)
        max_y = max(item[1] + item[3] for item in boxes)
        content_width = max_x - min_x
        content_height = max_y - min_y
        axis = str(content_alignment.get("axis") or "both")
        shift_x = ((float(width or 0) - content_width) / 2.0 - min_x) if axis in {"x", "both"} else 0.0
        shift_y = ((float(height or 0) - content_height) / 2.0 - min_y) if axis in {"y", "both"} else 0.0
        if abs(shift_x) < 0.0001 and abs(shift_y) < 0.0001:
            return []
        rules: list[str] = []
        for child in children:
            child_id = self.get_node_id(child)
            x, y, _, _ = child.get("box", [0, 0, 0, 0])
            declarations: dict[str, str] = {}
            if axis in {"x", "both"}:
                declarations["left"] = append_px(float(x or 0) + shift_x)
            if axis in {"y", "both"}:
                declarations["top"] = append_px(float(y or 0) + shift_y)
            rules.append(
                self.render_css_rule(
                    {
                        "selector": f'[data-node-id="{child_id}"]',
                        "declarations": declarations,
                    }
                )
            )
        return [rule for rule in rules if rule]

    def should_apply_effect(self, node: dict[str, Any], data: dict[str, Any]) -> bool:
        """
        判断是否应该应用效果。
        默认返回True，由子类或adapter根据具体需求覆盖此方法。
        """
        return True

    def resolve_fill_list(self, data: dict[str, Any], token_id: str | None) -> list[str]:
        if not token_id:
            return []
        token = data.get("tokens", {}).get("colors", {}).get(token_id, {})
        values = token.get("value") or []
        rendered: list[str] = []
        for value in values:
            if isinstance(value, str):
                rendered.append(sanitize_css_value(value))
            elif isinstance(value, dict) and value.get("url"):
                rendered.append(f'url("{value["url"]}")')
        return rendered

    def resolve_effect(self, data: dict[str, Any], token_id: str) -> list[str]:
        token = data.get("tokens", {}).get("effects", {}).get(token_id, {})
        return [str(value) for value in (token.get("value") or [])]

    def resolve_font(self, data: dict[str, Any], token_id: str | None) -> dict[str, Any]:
        if not token_id:
            return {}
        return (data.get("tokens", {}).get("fonts", {}).get(token_id) or {}).get("value") or {}

    def build_text_css(self, node: dict[str, Any], data: dict[str, Any]) -> list[str]:
        lines = ["  display: flex;", "  align-items: center;"]
        align = node.get("align")
        if align == "center":
            lines.append("  justify-content: center;")
            lines.append("  text-align: center;")
        elif align == "right":
            lines.append("  justify-content: flex-end;")
            lines.append("  text-align: right;")
        else:
            lines.append("  justify-content: flex-start;")
            lines.append("  text-align: left;")

        font = self.resolve_font(data, (node.get("text") or {}).get("font"))
        if font.get("family"):
            family = font["family"]
            lines.append(
                f'  font-family: "{family}", "PingFang SC", "Microsoft YaHei", sans-serif;'
            )
        if font.get("size") is not None:
            lines.append(f"  font-size: {append_px(font['size'])};")
        lines.append(f"  font-weight: {infer_font_weight(font.get('style'))};")
        if font.get("lineHeight") not in (None, "auto", "-1", -1):
            lines.append(f"  line-height: {append_px(font['lineHeight'])};")
        if font.get("letterSpacing") not in (None, "auto", "%"):
            lines.append(f"  letter-spacing: {append_px(font['letterSpacing'])};")

        colors = self.resolve_fill_list(data, (node.get("text") or {}).get("color"))
        if colors:
            if any("gradient(" in color for color in colors):
                lines.append(f"  background: {', '.join(colors)};")
                lines.append("  -webkit-background-clip: text;")
                lines.append("  background-clip: text;")
                lines.append("  -webkit-text-fill-color: transparent;")
                lines.append("  color: transparent;")
            else:
                lines.append(f"  color: {colors[0]};")

        if node.get("mode") == "single-line":
            lines.append("  white-space: nowrap;")

        node_plan = self.get_node_plan(node, data)
        if node_plan:
            style_policy = node_plan.get("stylePolicy") or {}
            if style_policy.get("preserveLineBreaks"):
                lines.append("  white-space: pre-wrap;")
            if style_policy.get("nowrap") is False:
                lines.append("  white-space: pre-wrap;")
            elif style_policy.get("nowrap") is True:
                lines.append("  white-space: nowrap;")

        lines.extend(self.text_css_overrides(node, data))
        return lines

    def text_css_overrides(self, node: dict[str, Any], data: dict[str, Any]) -> list[str]:
        return []

    def render_text(self, node: dict[str, Any], data: dict[str, Any]) -> str:
        return html.escape((node.get("text") or {}).get("value", ""))

    def should_render_vector(self, node: dict[str, Any], data: dict[str, Any]) -> bool:
        return True

    def get_vector_path_attrs(
        self,
        node: dict[str, Any],
        data: dict[str, Any],
        segment_index: int,
        segment: dict[str, Any],
    ) -> list[str]:
        return []

    def skip_vector_segment(
        self,
        node: dict[str, Any],
        data: dict[str, Any],
        segment_index: int,
        segment: dict[str, Any],
    ) -> bool:
        return False

    def build_vector_svg(self, node: dict[str, Any], data: dict[str, Any]) -> str:
        if not self.should_render_vector(node, data):
            return ""
        vectors = data.get("assets", {}).get("vectors", {})
        vector = vectors.get(node.get("vector", ""), {})
        min_x, min_y, view_width, view_height = self.get_vector_view_box(node, data)
        paths: list[str] = []
        defs: list[str] = []
        grouped_segments: dict[str, list[tuple[int, str, list[str]]]] = {}
        segment_order: list[str] = []
        for segment_index, segment in enumerate(vector.get("segments", [])):
            if self.skip_vector_segment(node, data, segment_index, segment):
                continue
            raw_d = str(segment.get("d") or "")
            path_attrs = self.get_vector_path_attrs(node, data, segment_index, segment)
            fill_values = self.resolve_fill_list(data, segment.get("fill")) or ["transparent"]
            group_key = json.dumps({"fill": fill_values, "attrs": path_attrs}, ensure_ascii=False, sort_keys=True)
            if group_key not in grouped_segments:
                grouped_segments[group_key] = []
                segment_order.append(group_key)
            grouped_segments[group_key].append((segment_index, raw_d, path_attrs))
        for group_key in segment_order:
            items = grouped_segments[group_key]
            segment_index = items[0][0]
            d_values = [item[1] for item in items if item[1]]
            path_attrs = items[0][2]
            extra_attrs = f" {' '.join(path_attrs)}" if path_attrs else ""
            d = escape_attr(" ".join(d_values))
            fill_values = json.loads(group_key)["fill"] or ["transparent"]
            bounds = self.get_svg_bounds(node, d_values)
            for fill in self.build_shape_fill_markup(
                node=node,
                data=data,
                defs=defs,
                segment_index=segment_index,
                fill_values=fill_values,
                bounds=bounds,
            ):
                paths.append(
                    f'<path d="{d}" fill="{escape_attr(fill)}" fill-rule="evenodd" clip-rule="evenodd"{extra_attrs}></path>'
                )
        defs_markup = f'<defs>{"".join(defs)}</defs>' if defs else ""
        return (
            f'<svg viewBox="{min_x} {min_y} {view_width} {view_height}" xmlns="http://www.w3.org/2000/svg" '
            f'preserveAspectRatio="none" shape-rendering="geometricPrecision">{defs_markup}{"".join(paths)}</svg>'
        )

    def get_vector_view_box(self, node: dict[str, Any], data: dict[str, Any]) -> tuple[float, float, float, float]:
        vectors = data.get("assets", {}).get("vectors", {})
        vector = vectors.get(node.get("vector", ""), {})
        bounds: list[tuple[float, float, float, float]] = []
        for segment in vector.get("segments", []):
            path_data = str(segment.get("d") or "")
            path_bounds = path_bounds_from_d(path_data)
            if path_bounds is not None:
                bounds.append(path_bounds)
        if bounds:
            min_x = min(item[0] for item in bounds)
            min_y = min(item[1] for item in bounds)
            max_x = max(item[0] + item[2] for item in bounds)
            max_y = max(item[1] + item[3] for item in bounds)
            return min_x, min_y, max(max_x - min_x, 1.0), max(max_y - min_y, 1.0)
        _, _, width, height = node.get("box", [0, 0, 0, 0])
        return 0.0, 0.0, max(float(width or 0), 1.0), max(float(height or 0), 1.0)

    def build_svg_filter_markup(self, filter_id: str, effect_values: list[str]) -> str:
        lines = [
            f'<filter id="{escape_attr(filter_id)}" filterUnits="userSpaceOnUse" '
            'color-interpolation-filters="sRGB" x="-100%" y="-100%" width="300%" height="300%">'
        ]
        has_effect = False
        blend_input = "SourceGraphic"
        inset_index = 0
        shadow_index = 0
        for raw in effect_values:
            if ":" not in raw:
                continue
            prop, value = raw.split(":", 1)
            prop = prop.strip()
            value = value.strip().rstrip(";")
            if prop in {"filter", "backdrop-filter"} and "blur" in value:
                match = re.search(r"blur\(([\d\.]+)px\)", value)
                if match:
                    std_dev = max(float(match.group(1)) / 2.0, 0.001)
                    lines.append(
                        f'<feGaussianBlur in="{blend_input}" stdDeviation="{std_dev}" result="blur_{shadow_index}"/>'
                    )
                    blend_input = f"blur_{shadow_index}"
                    has_effect = True
                    shadow_index += 1
                continue
            if prop != "box-shadow":
                continue
            shadow = parse_box_shadow(value)
            if not shadow:
                continue
            has_effect = True
            color_matrix = rgba_to_matrix_values(str(shadow["color"]))
            std_dev = max(float(shadow["blur"]) / 2.0, 0.001)
            dx = float(shadow["x"])
            dy = float(shadow["y"])
            if shadow["inset"]:
                inset_index += 1
                lines.extend(
                    [
                        f'<feColorMatrix in="{blend_input}" type="matrix" result="hardAlpha" '
                        'values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 127 0"/>',
                        f'<feOffset dx="{dx}" dy="{dy}"/>',
                        f'<feGaussianBlur stdDeviation="{std_dev}"/>',
                        '<feComposite in2="hardAlpha" operator="arithmetic" k2="-1" k3="1"/>',
                        f'<feColorMatrix type="matrix" values="{color_matrix}"/>',
                        f'<feBlend mode="normal" in2="{blend_input}" result="effect{inset_index}_innerShadow"/>',
                    ]
                )
                blend_input = f"effect{inset_index}_innerShadow"
            else:
                shadow_index += 1
                lines.append(
                    f'<feDropShadow in="{blend_input}" dx="{dx}" dy="{dy}" stdDeviation="{std_dev}" '
                    f'flood-color="{escape_attr(str(shadow["color"]))}" '
                    f'flood-opacity="{color_to_rgba(str(shadow["color"]))[3]}" '
                    f'result="effect{shadow_index}_dropShadow"/>'
                )
                blend_input = f"effect{shadow_index}_dropShadow"
        if not has_effect:
            return ""
        lines.append("</filter>")
        return "".join(lines)

    def build_vector_group_markup(
        self,
        node: dict[str, Any],
        data: dict[str, Any],
        defs: list[str],
        *,
        is_root: bool = False,
    ) -> str:
        vectors = data.get("assets", {}).get("vectors", {})
        x, y, _, _ = node.get("box", [0, 0, 0, 0])
        local_x = 0.0 if is_root else float(x or 0)
        local_y = 0.0 if is_root else float(y or 0)

        if self.has_vector(node):
            vector = vectors.get(node.get("vector", ""), {})
            path_markup: list[str] = []
            node_id = self.get_node_id(node) or "node"
            effect_token = str(_get_style(node, "effect") or "")
            filter_attr = ""
            if effect_token:
                filter_id = f"{node_id}-filter"
                filter_markup = self.build_svg_filter_markup(filter_id, self.resolve_effect(data, effect_token))
                if filter_markup:
                    defs.append(filter_markup)
                    filter_attr = f' filter="url(#{escape_attr(filter_id)})"'
            grouped_segments: dict[str, list[tuple[int, str, list[str]]]] = {}
            segment_order: list[str] = []
            for segment_index, segment in enumerate(vector.get("segments", [])):
                if self.skip_vector_segment(node, data, segment_index, segment):
                    continue
                raw_d = str(segment.get("d") or "")
                path_attrs = self.get_vector_path_attrs(node, data, segment_index, segment)
                fill_values = self.resolve_fill_list(data, segment.get("fill")) or ["transparent"]
                group_key = json.dumps({"fill": fill_values, "attrs": path_attrs}, ensure_ascii=False, sort_keys=True)
                if group_key not in grouped_segments:
                    grouped_segments[group_key] = []
                    segment_order.append(group_key)
                grouped_segments[group_key].append((segment_index, raw_d, path_attrs))
            for group_key in segment_order:
                items = grouped_segments[group_key]
                segment_index = items[0][0]
                d_values = [item[1] for item in items if item[1]]
                path_attrs = items[0][2]
                extra_attrs = f" {' '.join(path_attrs)}" if path_attrs else ""
                d = escape_attr(" ".join(d_values))
                fill_values = json.loads(group_key)["fill"] or ["transparent"]
                bounds = self.get_svg_bounds(node, d_values)
                for fill in self.build_shape_fill_markup(
                    node=node,
                    data=data,
                    defs=defs,
                    segment_index=segment_index,
                    fill_values=fill_values,
                    bounds=bounds,
                ):
                    path_markup.append(
                        f'<path d="{d}" fill="{escape_attr(fill)}" fill-rule="evenodd" clip-rule="evenodd"{extra_attrs}></path>'
                    )
            transform = f' transform="translate({local_x} {local_y})"' if local_x or local_y else ""
            return f"<g{transform}{filter_attr}>{''.join(path_markup)}</g>"

        if self.get_node_kind(node) == "svg_ellipse":
            node_id = self.get_node_id(node) or "node"
            effect_token = str(_get_style(node, "effect") or "")
            filter_attr = ""
            if effect_token:
                filter_id = f"{node_id}-filter"
                filter_markup = self.build_svg_filter_markup(filter_id, self.resolve_effect(data, effect_token))
                if filter_markup:
                    defs.append(filter_markup)
                    filter_attr = f' filter="url(#{escape_attr(filter_id)})"'
            _, _, width, height = node.get("box", [0, 0, 0, 0])
            rx = max(float(width or 0) / 2.0, 0.0)
            ry = max(float(height or 0) / 2.0, 0.0)
            fill_values = self.resolve_fill_list(data, _get_style(node, "fill")) or ["transparent"]
            ellipse_bounds = (0.0, 0.0, max(float(width or 0), 1.0), max(float(height or 0), 1.0))
            rendered_fills = self.build_shape_fill_markup(
                node=node,
                data=data,
                defs=defs,
                segment_index=0,
                fill_values=fill_values,
                bounds=ellipse_bounds,
            )
            stroke_values = self.resolve_fill_list(data, _get_style(node, "strokeColor"))
            rendered_strokes = self.build_shape_fill_markup(
                node=node,
                data=data,
                defs=defs,
                segment_index=1,
                fill_values=stroke_values,
                bounds=ellipse_bounds,
            ) if stroke_values else []
            stroke = rendered_strokes[0] if rendered_strokes else "none"
            stroke_width = str(_get_style(node, "strokeWidth") or "0").replace("px", "")
            ellipses = [
                f'<ellipse cx="{rx}" cy="{ry}" rx="{rx}" ry="{ry}" fill="{escape_attr(fill)}" '
                f'stroke="{escape_attr(stroke)}" stroke-width="{escape_attr(stroke_width)}"></ellipse>'
                for fill in rendered_fills
            ]
            transform = f' transform="translate({local_x} {local_y})"' if local_x or local_y else ""
            return f"<g{transform}{filter_attr}>{''.join(ellipses)}</g>"

        child_markup = [
            self.build_vector_group_markup(child, data, defs)
            for child in self.get_render_children(node)
        ]
        child_markup = [item for item in child_markup if item]
        if not child_markup:
            return ""
        effect_token = str(_get_style(node, "effect") or "")
        filter_attr = ""
        if effect_token:
            node_id = self.get_node_id(node) or "group"
            filter_id = f"{node_id}-filter"
            filter_markup = self.build_svg_filter_markup(filter_id, self.resolve_effect(data, effect_token))
            if filter_markup:
                defs.append(filter_markup)
                filter_attr = f' filter="url(#{escape_attr(filter_id)})"'
        transform = f' transform="translate({local_x} {local_y})"' if local_x or local_y else ""
        return f"<g{transform}{filter_attr}>{''.join(child_markup)}</g>"

    def build_group_svg(self, node: dict[str, Any], data: dict[str, Any]) -> str:
        min_x, min_y, view_width, view_height = self.get_group_view_box(node, data)
        defs: list[str] = []
        body = self.build_vector_group_markup(node, data, defs, is_root=True)
        if min_x or min_y:
            body = f'<g transform="translate({-min_x} {-min_y})">{body}</g>'
        defs_markup = f'<defs>{"".join(defs)}</defs>' if defs else ""
        # 使用geometricPrecision以改善边框渲染质量
        return (
            f'<svg viewBox="0 0 {view_width} {view_height}" xmlns="http://www.w3.org/2000/svg" '
            f'preserveAspectRatio="none" shape-rendering="geometricPrecision">{defs_markup}{body}</svg>'
        )

    def get_group_view_box(self, node: dict[str, Any], data: dict[str, Any]) -> tuple[float, float, float, float]:
        boxes: list[tuple[float, float, float, float]] = []

        def walk(current: dict[str, Any], offset_x: float, offset_y: float, is_root_node: bool) -> None:
            x, y, _, _ = current.get("box", [0, 0, 0, 0])
            local_x = offset_x + (0.0 if is_root_node else float(x or 0))
            local_y = offset_y + (0.0 if is_root_node else float(y or 0))
            if self.has_vector(current):
                min_x, min_y, width, height = self.get_vector_view_box(current, data)
                boxes.append((local_x + min_x, local_y + min_y, width, height))
                return
            if self.get_node_kind(current) == "svg_ellipse":
                _, _, width, height = current.get("box", [0, 0, 0, 0])
                boxes.append((local_x, local_y, float(width or 0), float(height or 0)))
                return
            for child in self.get_render_children(current):
                walk(child, local_x, local_y, False)

        walk(node, 0.0, 0.0, True)
        if boxes:
            min_x = min(item[0] for item in boxes)
            min_y = min(item[1] for item in boxes)
            max_x = max(item[0] + item[2] for item in boxes)
            max_y = max(item[1] + item[3] for item in boxes)
            return min_x, min_y, max(max_x - min_x, 1.0), max(max_y - min_y, 1.0)
        _, _, width, height = node.get("box", [0, 0, 0, 0])
        return 0.0, 0.0, max(float(width or 0), 1.0), max(float(height or 0), 1.0)

    def render_vector(self, node: dict[str, Any], data: dict[str, Any]) -> str:
        svg_markup = self.build_vector_svg(node, data)
        if not svg_markup:
            return ""
        asset_plan = self.get_asset_plan(node, data)
        if asset_plan and str(asset_plan.get("type") or "") == "svg":
            output_path = self.get_asset_output_path(asset_plan, data)
            if output_path:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(svg_markup, encoding="utf-8")
                src = self.get_asset_src(output_path, data)
                return f'<img src="{escape_attr(src)}" alt="" loading="lazy" />'
        return svg_markup

    def vector_css_overrides(self, node: dict[str, Any], data: dict[str, Any]) -> list[str]:
        if self.can_merge_group_as_svg(node, data):
            return ["  overflow: hidden;"]
        return []

    def node_css_overrides(self, node: dict[str, Any], data: dict[str, Any]) -> list[str]:
        return self.build_alpha_mask_css(node, data)

    def plan_css_overrides(self, node: dict[str, Any], data: dict[str, Any]) -> list[str]:
        lines: list[str] = []
        manual_zone = self.get_manual_zone(node, data)
        if manual_zone:
            lines.extend(
                [
                    "  outline: 1px dashed rgba(255, 180, 0, 0.65);",
                    "  outline-offset: -1px;",
                    "  display: flex;",
                    "  align-items: center;",
                    "  justify-content: center;",
                    "  background: rgba(255, 180, 0, 0.08);",
                ]
            )
        asset_plan = self.get_asset_plan(node, data)
        if asset_plan and str(asset_plan.get("type") or "") in {"svg", "image"}:
            lines.append("  overflow: hidden;")
        library_plan = self.get_library_plan(node, data)
        if library_plan:
            lines.extend(
                [
                    "  display: flex;",
                    "  align-items: stretch;",
                    "  justify-content: stretch;",
                ]
            )
        for alignment_plan in self.get_alignment_plans(node, data):
            for declaration in alignment_plan.get("cssDeclarations") or []:
                declaration_text = str(declaration).strip().rstrip(";")
                if declaration_text:
                    lines.append(f"  {declaration_text};")
        return lines

    def render_manual_zone(self, node: dict[str, Any], data: dict[str, Any]) -> str:
        manual_zone = self.get_manual_zone(node, data) or {}
        zone_id = str(manual_zone.get("zoneId") or self.get_node_id(node))
        reason = str(manual_zone.get("reason") or "manual-zone")
        strategy = str(manual_zone.get("strategy") or "replace-with-handcrafted-html")
        return (
            f'<div class="{escape_attr(self.css_prefix)}-manual-zone__inner">'
            f'<strong>{html.escape(zone_id)}</strong>'
            f'<span>{html.escape(reason)}</span>'
            f'<code>{html.escape(strategy)}</code>'
            f'</div>'
        )

    def render_library_host(self, node: dict[str, Any], data: dict[str, Any]) -> str:
        library_plan = self.get_library_plan(node, data) or {}
        component_name = str(library_plan.get("libraryComponent") or "")
        props = library_plan.get("props") or {}
        payload = escape_attr(component_name)
        props_json = escape_attr(json.dumps(props, ensure_ascii=False))
        return (
            f'<div class="{escape_attr(self.css_prefix)}-library-mount" '
            f'data-library-component="{payload}" '
            f"data-library-props='{props_json}'></div>"
        )

    def render_stage_script(self, width: int, height: int) -> str:
        stage_class = f"{self.css_prefix}-stage"
        return f"""
    (() => {{
      const stage = document.querySelector('.{stage_class}');
      if (!stage) return;
      const stageWidth = {width};
      const stageHeight = {height};
      function fitStage() {{
        const scaleX = window.innerWidth / stageWidth;
        const scaleY = window.innerHeight / stageHeight;
        const scale = Math.min(scaleX, scaleY);
        stage.style.transform = `translate(-50%, -50%) scale(${{scale}})`;
      }}
      fitStage();
      window.addEventListener('resize', fitStage);
    }})();
""".rstrip()

    def get_extra_css(self, data: dict[str, Any]) -> str:
        plan = self.get_render_plan(data)
        lines: list[str] = []
        for item in plan.get("extraCssRules", []) or []:
            rendered = self.render_css_rule(item)
            if rendered:
                lines.append(rendered)
        for item in plan.get("componentPlans", []) or []:
            node = self.get_node_by_id(str(item.get("rootNodeId") or ""), data)
            if node:
                lines.extend(self.render_layout_decision_css(node, data))
        for item in plan.get("nodePlans", []) or []:
            node = self.get_node_by_id(str(item.get("nodeId") or ""), data)
            if node:
                lines.extend(self.render_layout_decision_css(node, data))
        for item in plan.get("libraryPlans", []) or []:
            for rule in ((item.get("styleOverrides") or {}).get("rules") or []):
                rendered = self.render_css_rule(rule)
                if rendered:
                    lines.append(rendered)
        return "\n".join(lines)

    def render_css_rule(self, rule: Any) -> str:
        if isinstance(rule, str):
            return rule.strip()
        if not isinstance(rule, dict):
            return ""
        selector = str(rule.get("selector") or "").strip()
        declarations = rule.get("declarations") or {}
        raw_lines = rule.get("lines") or []
        media = str(rule.get("media") or "").strip()
        body_lines: list[str] = []
        if selector and isinstance(declarations, dict):
            body_lines.append(f"{selector} {{")
            for key, value in declarations.items():
                body_lines.append(f"  {key}: {value};")
            body_lines.append("}")
        elif raw_lines:
            body_lines.extend(str(line) for line in raw_lines if str(line).strip())
        rendered = "\n".join(body_lines).strip()
        if not rendered:
            return ""
        if media:
            return f"{media} {{\n{rendered}\n}}"
        return rendered

    def render_stage_overlay(self, data: dict[str, Any]) -> str:
        return ""

    def render_extra_script(self, data: dict[str, Any]) -> str:
        library_plans = self.get_render_plan(data).get("libraryPlans", []) or []
        if not library_plans:
            return ""
        prefix = self.css_prefix
        return f"""
    (() => {{
      const hosts = Array.from(document.querySelectorAll('.{prefix}-library-host > .{prefix}-library-mount'));
      if (!hosts.length) return;

      function boot() {{
        if (!window.Vue || !window.ElementPlus) return false;
        const {{ createApp, h }} = window.Vue;
        hosts.forEach((host) => {{
          if (host.dataset.mounted === '1') return;
          const componentName = host.dataset.libraryComponent;
          const propsText = host.dataset.libraryProps || '{{}}';
          const props = JSON.parse(propsText);
          const component = window.ElementPlus[componentName];
          if (!component) return;
          const app = createApp({{
            render() {{
              return h(component, props);
            }},
          }});
          app.use(window.ElementPlus);
          app.mount(host);
          host.dataset.mounted = '1';
        }});
        return true;
      }}

      function loadScript(src, onload) {{
        const script = document.createElement('script');
        script.src = src;
        script.onload = onload;
        document.head.appendChild(script);
      }}

      function loadStyle(href) {{
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = href;
        link.dataset.elementPlus = '1';
        document.head.appendChild(link);
      }}

      if (!document.querySelector('link[data-element-plus]')) {{
        loadStyle('https://unpkg.com/element-plus/dist/index.css');
      }}
      if (boot()) return;
      loadScript('https://unpkg.com/vue@3/dist/vue.global.prod.js', () => {{
        if (boot()) return;
        loadScript('https://unpkg.com/element-plus/dist/index.full.min.js', () => {{
          boot();
        }});
      }});
    }})();
""".rstrip()


class GenericDslHtmlRenderer:
    """HTML renderer that delegates DSL-specific logic to an adapter."""

    def __init__(self, payload: dict[str, Any], adapter: BaseDslHtmlAdapter) -> None:
        self.adapter = adapter
        self.data = adapter.normalize(payload)
        context = dict(self.data.get("__renderContext") or {})
        node_index: dict[str, dict[str, Any]] = {}
        parent_index: dict[str, str] = {}

        def walk(node: dict[str, Any], parent_id: str = "") -> None:
            node_id = str(node.get("id") or "")
            if node_id:
                node_index[node_id] = node
                if parent_id:
                    parent_index[node_id] = parent_id
            for child in adapter.get_render_children(node):
                walk(child, node_id)

        for root in adapter.get_roots(self.data):
            walk(root)
        context["nodeIndex"] = node_index
        context["parentIndex"] = parent_index
        self.data["__renderContext"] = context
        self.css_rules: list[str] = [adapter.get_base_css()]

    def render(self) -> str:
        width, height = self.adapter.get_stage_size(self.data)
        prefix = self.adapter.css_prefix
        self.css_rules.append(f".{prefix}-stage {{ width: {width}px; height: {height}px; }}")
        body = "\n".join(self.render_node(root, depth=3) for root in self.adapter.get_roots(self.data))
        stage_overlay = self.adapter.render_stage_overlay(self.data)
        if stage_overlay:
            body = "\n".join(part for part in [body, stage_overlay] if part)
        title = html.escape(self.adapter.get_title(self.data))
        extra_css = self.adapter.get_extra_css(self.data)
        css_parts = [self.adapter.render_token_vars(self.data), *self.css_rules]
        if extra_css:
            css_parts.append(extra_css)
        css = "\n\n".join(part for part in css_parts if part)
        script_parts = [self.adapter.render_stage_script(width, height), self.adapter.render_extra_script(self.data)]
        script = "\n".join(part for part in script_parts if part)
        return f"""<!DOCTYPE html>
<html lang="{escape_attr(self.adapter.html_lang)}">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title}</title>
  <style>
{css}
  </style>
</head>
<body>
  <main class="{prefix}-shell">
    <div class="{prefix}-stage" data-format="{escape_attr(self.data.get("format", ""))}">
{body}
    </div>
  </main>
  <script>
{script}
  </script>
</body>
</html>
"""

    def render_node(self, node: dict[str, Any], depth: int) -> str:
        indent = "  " * depth
        if self.adapter.is_alpha_mask_node(node):
            return ""
        attrs = self.adapter.build_attrs(node, self.data)
        classes = str(attrs.get("class", ""))
        if self.adapter.has_vector(node) or self.adapter.can_merge_group_as_svg(node, self.data):
            attrs["class"] = f"{classes} {self.adapter.css_prefix}-vector".strip()
        attr_text = "".join(
            f' {key}="{escape_attr(value)}"' for key, value in attrs.items() if value != ""
        )
        self.css_rules.append(self.adapter.build_css_rule(node, self.data))
        tag = self.adapter.get_html_tag(node, self.data)

        content = ""
        kind = self.adapter.get_node_kind(node)
        if self.adapter.get_manual_zone(node, self.data):
            content = self.adapter.render_manual_zone(node, self.data)
        elif self.adapter.get_library_plan(node, self.data):
            content = self.adapter.render_library_host(node, self.data)
        elif kind == "text":
            content = self.adapter.render_text(node, self.data)
        elif self.adapter.has_vector(node):
            content = self.adapter.render_vector(node, self.data)
        elif self.adapter.can_merge_group_as_svg(node, self.data):
            content = self.adapter.build_group_svg(node, self.data)
        else:
            children = self.adapter.get_render_children(node)
            if children:
                rendered = [self.render_node(child, depth + 1) for child in children]
                rendered = [item for item in rendered if item]
                if rendered:
                    content = "\n" + "\n".join(rendered) + f"\n{indent}"
        return f"{indent}<{tag}{attr_text}>{content}</{tag}>"
