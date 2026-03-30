#!/usr/bin/env python3
"""Shared helpers for the mastergo2htmlV3 pipeline."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any], pretty: bool = True) -> None:
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered + ("\n" if pretty else ""), encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def slugify(value: str, fallback: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", value or "")
    text = text.replace("_", "-").replace("/", "-").replace(":", "-")
    text = re.sub(r"[^a-zA-Z0-9-]+", "-", text).strip("-").lower()
    return text or fallback


def normalize_prototype_key(value: Any) -> str:
    text = str(value or "").strip()
    return "" if not text or text.lower() == "unknown" else text


def infer_prototype_key_from_meta(meta: dict[str, Any]) -> str:
    for candidate in (
        meta.get("prototypeKey"),
        meta.get("prototype_key"),
        meta.get("source"),
        meta.get("sourceCompressed"),
    ):
        text = str(candidate or "").replace("\\", "/")
        if not text:
            continue
        match = re.search(r"/prototypes/([^/]+)/", text)
        if match:
            return match.group(1)
    return ""


def collect_nodes(roots: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    nodes: list[dict[str, Any]] = []
    parents: dict[str, dict[str, Any]] = {}

    def walk(node: dict[str, Any]) -> None:
        nodes.append(node)
        for child in node.get("children") or []:
            child_id = str(child.get("id") or "")
            if child_id:
                parents[child_id] = node
            walk(child)

    for root in roots:
        walk(root)
    return nodes, parents


def node_box(node: dict[str, Any]) -> tuple[float, float, float, float]:
    box = node.get("box") or [0, 0, 0, 0]
    padded = list(box[:4]) + [0] * max(0, 4 - len(box))
    return tuple(float(v or 0) for v in padded[:4])  # type: ignore[return-value]


def first_text(node: dict[str, Any]) -> str:
    text = node.get("text") or {}
    value = text.get("value")
    if isinstance(value, str):
        return value.strip()
    return ""


def flatten_text(node: dict[str, Any]) -> str:
    parts: list[str] = []

    def walk(current: dict[str, Any]) -> None:
        value = first_text(current)
        if value:
            parts.append(value)
        for child in current.get("children") or []:
            walk(child)

    walk(node)
    return " ".join(part for part in parts if part).strip()


def infer_layout_mode(node: dict[str, Any]) -> str:
    children = node.get("children") or []
    if len(children) < 2:
        return "absolute"
    boxes = [node_box(child) for child in children]
    xs = [round(box[0], 1) for box in boxes]
    ys = [round(box[1], 1) for box in boxes]
    same_row = len(set(ys)) <= max(2, len(ys) // 3)
    same_col = len(set(xs)) <= max(2, len(xs) // 3)
    if same_row and not same_col:
        return "row"
    if same_col and not same_row:
        return "column"
    unique_xs = len(set(xs))
    unique_ys = len(set(ys))
    if unique_xs >= 2 and unique_ys >= 2:
        return "grid"
    return "absolute"

