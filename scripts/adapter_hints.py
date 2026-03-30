#!/usr/bin/env python3
"""Compatibility helpers for adapter hints.

This module no longer infers prototype-specific hints in public scripts.
It only preserves file-shape compatibility for older callers.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def infer_adapter_hints(
    compressed: dict[str, Any],
    semantic: dict[str, Any],
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    explicit = semantic.get("adapterHints")
    if isinstance(explicit, dict):
        rules = explicit.get("rules")
        if isinstance(rules, list):
            return {
                "version": str(explicit.get("version") or "mastergo2html.adapter-hints.v1"),
                "generatedAt": str(explicit.get("generatedAt") or now_iso()),
                **{key: value for key, value in explicit.items() if key not in {"version", "generatedAt"}},
                "rules": rules,
            }
    return {
        "version": "mastergo2html.adapter-hints.v1",
        "generatedAt": now_iso(),
        "rules": [],
    }


def render_adapter_hints_section(hints: dict[str, Any]) -> str:
    lines = ["## Adapter Hints", ""]
    rules = hints.get("rules") or []
    if not rules:
        lines.append("- 当前公共脚本不再推断 adapter hints。")
        return "\n".join(lines).rstrip() + "\n"
    for rule in rules:
        hint_type = str(rule.get("hintType") or "unknown")
        node_ids = [str(item) for item in (rule.get("nodeIds") or []) if str(item)]
        lines.append(f"- `{hint_type}`: `{len(node_ids)}` 个节点")
    return "\n".join(lines).rstrip() + "\n"


def upsert_analysis_adapter_hints(analysis_text: str, hints: dict[str, Any]) -> str:
    section = render_adapter_hints_section(hints).strip()
    pattern = re.compile(r"^## Adapter Hints\s*$.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)
    if pattern.search(analysis_text):
        updated = pattern.sub(section + "\n\n", analysis_text).rstrip() + "\n"
    else:
        updated = analysis_text.rstrip() + "\n\n" + section + "\n"
    return updated


def sync_adapter_hints_files(
    compressed_path: Path,
    semantic_path: Path,
    analysis_path: Path,
    plan_path: Path | None = None,
) -> dict[str, Any]:
    semantic = load_json(semantic_path)
    hints = infer_adapter_hints({}, semantic, None)
    semantic["adapterHints"] = hints
    write_json(semantic_path, semantic)
    if analysis_path.exists():
        analysis_text = analysis_path.read_text(encoding="utf-8")
    else:
        analysis_text = "# Analysis\n"
    analysis_path.write_text(upsert_analysis_adapter_hints(analysis_text, hints), encoding="utf-8")
    return hints
