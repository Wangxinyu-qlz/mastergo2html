#!/usr/bin/env python3
"""Render any DSL JSON to HTML through the generic kernel plus adapter layer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dsl_to_html_adapters import infer_adapter_name, load_adapter
from dsl_to_html_kernel import GenericDslHtmlRenderer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Path to any DSL JSON file")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Output HTML path")
    parser.add_argument("--plan", type=Path, help="Optional path to render.plan.json")
    parser.add_argument(
        "--adapter",
        help="Built-in adapter name, Python module, or adapter .py file. Defaults to format-based inference.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if args.plan:
        payload["renderPlan"] = json.loads(args.plan.read_text(encoding="utf-8"))
    output_path = args.output.resolve()
    prototype_dir = args.plan.resolve().parent if args.plan else output_path.parent
    payload["__renderContext"] = {
        "outputPath": str(output_path).replace("\\", "/"),
        "outputDir": str(output_path.parent).replace("\\", "/"),
        "prototypeDir": str(prototype_dir).replace("\\", "/"),
    }
    adapter_spec = args.adapter
    if not adapter_spec:
        prototype_adapter = prototype_dir / "adapter.py"
        if prototype_adapter.exists():
            adapter_spec = str(prototype_adapter)
    adapter = load_adapter(adapter_spec, payload)
    html_text = GenericDslHtmlRenderer(payload, adapter).render()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html_text, encoding="utf-8")
    print(
        json.dumps(
            {
                "input": str(args.input).replace("\\", "/"),
                "output": str(args.output).replace("\\", "/"),
                "plan": str(args.plan).replace("\\", "/") if args.plan else None,
                "adapter": adapter_spec or infer_adapter_name(payload),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
