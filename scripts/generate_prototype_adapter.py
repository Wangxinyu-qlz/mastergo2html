#!/usr/bin/env python3
"""Generate a minimal prototype-local adapter stub.

The public pipeline no longer generates heuristic prototype-specific fixes.
This script only preserves the adapter file contract for manual extension.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def to_class_name(prototype_key: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z]+", " ", prototype_key)
    parts = [part.capitalize() for part in cleaned.split() if part]
    core = "".join(parts) or "PrototypeAdapter"
    if not core[0].isalpha():
        core = f"Prototype{core}"
    return f"{core}Adapter"


def normalize_prototype_key(value: Any) -> str:
    text = str(value or "").strip()
    return "" if not text or text.lower() == "unknown" else text


def infer_prototype_key(compressed: dict[str, Any], semantic: dict[str, Any], plan: dict[str, Any]) -> str:
    for meta in (semantic.get("meta") or {}, plan.get("meta") or {}, compressed.get("meta") or {}):
        prototype_key = normalize_prototype_key(meta.get("prototypeKey"))
        if prototype_key:
            return prototype_key
    return "unknown"


def build_adapter_source(compressed: dict[str, Any], semantic: dict[str, Any], plan: dict[str, Any]) -> str:
    prototype_key = infer_prototype_key(compressed, semantic, plan)
    class_name = to_class_name(prototype_key)
    return f'''#!/usr/bin/env python3
"""Prototype-local adapter stub for {prototype_key}."""

from dsl_to_html_adapters import RenderDslHifiAdapter


class {class_name}(RenderDslHifiAdapter):
    """Manual extension point.

    Public scripts no longer write heuristic prototype-specific behavior here.
    Add overrides manually only when a reviewed prototype-local fix is required.
    """

    prototype_key = "{prototype_key}"
'''


def write_adapter(
    compressed_path: Path,
    semantic_path: Path,
    plan_path: Path,
    output_path: Path,
    overwrite: bool = False,
) -> Path:
    if output_path.exists() and not overwrite:
        return output_path
    source = build_adapter_source(
        load_json(compressed_path),
        load_json(semantic_path),
        load_json(plan_path),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(source, encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("compressed", type=Path)
    parser.add_argument("semantic", type=Path)
    parser.add_argument("plan", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--force", action="store_true", help="Overwrite existing adapter.py")
    args = parser.parse_args()
    output = write_adapter(args.compressed, args.semantic, args.plan, args.output, overwrite=args.force)
    print(json.dumps({"output": str(output).replace("\\", "/")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
