#!/usr/bin/env python3
"""Assemble chunk-level HTML outputs back into a prototype-level preview page."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


STYLE_RE = re.compile(r"<style[^>]*>(.*?)</style>", re.IGNORECASE | re.DOTALL)
BODY_RE = re.compile(r"<body[^>]*>(.*?)</body>", re.IGNORECASE | re.DOTALL)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def format_px(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text if text else "0"


def resolve_root_bounds(tree: dict[str, Any]) -> list[float]:
    root = tree.get("root") or {}
    metrics = root.get("metrics") or {}
    bounds = metrics.get("absoluteBounds") or metrics.get("bounds") or [0, 0, 1920, 1080]
    if len(bounds) != 4:
        return [0, 0, 1920, 1080]
    return [float(value) for value in bounds]


def build_chunk_index(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for chunk in manifest.get("chunks") or []:
        for key in ("id", "path", "file"):
            value = chunk.get(key)
            if value:
                index[str(value)] = chunk
    return index


def choose_chunk(run: dict[str, Any], chunk_index: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for value in (run.get("id"), run.get("path"), run.get("sourceChunk")):
        if value is None:
            continue
        match = chunk_index.get(str(value))
        if match:
            return match
    return None


def extract_div_inner(text: str, marker: str) -> str | None:
    start = text.find(marker)
    if start < 0:
        return None
    open_end = text.find(">", start)
    if open_end < 0:
        return None
    pos = open_end + 1
    depth = 1
    while depth > 0:
        next_open = text.find("<div", pos)
        next_close = text.find("</div>", pos)
        if next_close < 0:
            return None
        if next_open != -1 and next_open < next_close:
            open_tag_end = text.find(">", next_open)
            if open_tag_end < 0:
                return None
            depth += 1
            pos = open_tag_end + 1
            continue
        depth -= 1
        if depth == 0:
            return text[open_end + 1:next_close]
        pos = next_close + len("</div>")
    return None


def sanitize_chunk_css(css_text: str) -> str:
    patterns = [
        r"html,\s*body\s*\{.*?\}",
        r"body\s*\{.*?\}",
        r"\.hifi-shell\s*\{.*?\}",
        r"\.hifi-stage\s*\{.*?\}",
    ]
    sanitized = css_text
    for pattern in patterns:
        sanitized = re.sub(pattern, "", sanitized, flags=re.DOTALL)
    return sanitized.strip()


def extract_chunk_artifacts(html_path: Path) -> tuple[str, str]:
    text = html_path.read_text(encoding="utf-8")
    body_match = BODY_RE.search(text)
    if not body_match:
        raise ValueError(f"Missing <body> in {html_path}")
    body_text = body_match.group(1)
    stage_inner = extract_div_inner(body_text, '<div class="hifi-stage"')
    if stage_inner is None:
        raise ValueError(f"Missing .hifi-stage in {html_path}")
    styles = [sanitize_chunk_css(item) for item in STYLE_RE.findall(text)]
    combined_style = "\n\n".join(item for item in styles if item)
    return combined_style, stage_inner.strip()


def build_html(
    *,
    prototype_name: str,
    root_bounds: list[float],
    chunk_styles: list[str],
    chunk_markup: list[str],
    missing_chunks: list[str],
) -> str:
    _, _, root_width, root_height = root_bounds
    warnings_html = ""
    if missing_chunks:
        items = "\n".join(f"        <li>{item}</li>" for item in missing_chunks)
        warnings_html = (
            "      <aside class=\"assembly-warning\">\n"
            "        <strong>Missing chunks</strong>\n"
            "        <ul>\n"
            f"{items}\n"
            "        </ul>\n"
            "      </aside>\n"
        )
    style_text = "\n\n".join(chunk_styles)
    markup_text = "\n".join(chunk_markup)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{prototype_name} - assembled</title>
  <style>
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; min-height: 100%; }}
body {{
  overflow: hidden;
  background:
    radial-gradient(circle at top, rgba(23, 56, 112, 0.55), rgba(5, 12, 26, 0.96) 48%),
    linear-gradient(180deg, #071121 0%, #030812 100%);
  color: #d6ebff;
  font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
}}
.assembly-shell {{
  position: relative;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
}}
.assembly-stage {{
  position: absolute;
  left: 50%;
  top: 50%;
  width: {format_px(root_width)}px;
  height: {format_px(root_height)}px;
  transform-origin: center center;
  will-change: transform;
  overflow: visible;
}}
.assembly-chunk {{
  position: absolute;
  overflow: visible;
}}
.assembly-caption {{
  position: absolute;
  left: 18px;
  top: 18px;
  z-index: 10;
  padding: 10px 12px;
  border-radius: 10px;
  backdrop-filter: blur(10px);
  background: rgba(4, 14, 34, 0.58);
  border: 1px solid rgba(121, 193, 255, 0.18);
  font-size: 12px;
  line-height: 1.5;
}}
.assembly-warning {{
  position: absolute;
  right: 18px;
  top: 18px;
  z-index: 10;
  max-width: 360px;
  padding: 10px 12px;
  border-radius: 10px;
  backdrop-filter: blur(10px);
  background: rgba(52, 10, 10, 0.78);
  border: 1px solid rgba(255, 158, 158, 0.28);
  font-size: 12px;
}}
.assembly-warning ul {{
  margin: 8px 0 0;
  padding-left: 18px;
}}

{style_text}
  </style>
</head>
<body>
  <main class="assembly-shell">
    <section class="assembly-caption">
      <div>{prototype_name}</div>
      <div>assembled from inline chunk DOM</div>
      <div>stage: {format_px(root_width)} x {format_px(root_height)}</div>
    </section>
{warnings_html}    <section class="assembly-stage" data-prototype-name="{prototype_name}">
{markup_text}
    </section>
  </main>
  <script>
    (() => {{
      const shell = document.querySelector('.assembly-shell');
      const stage = document.querySelector('.assembly-stage');
      if (!shell || !stage) return;

      const baseWidth = {root_width};
      const baseHeight = {root_height};

      const fitStage = () => {{
        const scale = Math.min(
          shell.clientWidth / baseWidth,
          shell.clientHeight / baseHeight
        );
        stage.style.transform = `translate(-50%, -50%) scale(${{scale}})`;
      }};

      fitStage();
      window.addEventListener('resize', fitStage, {{ passive: true }});
    }})();
  </script>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prototype_dir", type=Path, help="Prototype directory")
    parser.add_argument(
        "--chunks-dir",
        type=Path,
        help="Chunk directory. Defaults to <prototype_dir>/dsl_chunks",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output HTML path. Defaults to <prototype_dir>/output/assembled.html",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    prototype_dir = args.prototype_dir.resolve()
    chunks_dir = (args.chunks_dir or (prototype_dir / "dsl_chunks")).resolve()
    output_path = (args.output or (prototype_dir / "output" / "assembled.html")).resolve()

    chunk_manifest = load_json(chunks_dir / "leaf-chunks.manifest.json")
    pipeline_manifest = load_json(chunks_dir / "chunk-pipeline.manifest.json")
    tree = load_json(chunks_dir / "chunk.tree.json")

    root_bounds = resolve_root_bounds(tree)
    prototype_name = (
        ((tree.get("root") or {}).get("name"))
        or ((chunk_manifest.get("meta") or {}).get("rootName"))
        or prototype_dir.name
    )

    chunk_index = build_chunk_index(chunk_manifest)
    chunk_styles: list[str] = []
    chunk_markup: list[str] = []
    missing_chunks: list[str] = []

    for run in pipeline_manifest.get("runs") or []:
        if run.get("status") != "ok":
            missing_chunks.append(f"{run.get('name') or run.get('id')}: pipeline failed")
            continue
        chunk = choose_chunk(run, chunk_index)
        if not chunk:
            missing_chunks.append(f"{run.get('name') or run.get('id')}: no chunk metadata")
            continue

        bounds = chunk.get("absoluteBounds") or chunk.get("bounds") or [0, 0, 0, 0]
        if len(bounds) != 4:
            missing_chunks.append(f"{run.get('name') or run.get('id')}: invalid bounds")
            continue
        left, top, width, height = [float(value) for value in bounds]

        html_path = Path(str(((run.get("artifacts") or {}).get("html")) or ""))
        if not html_path.exists():
            missing_chunks.append(f"{run.get('name') or run.get('id')}: html not found")
            continue

        try:
            style_text, body_markup = extract_chunk_artifacts(html_path)
        except ValueError as exc:
            missing_chunks.append(str(exc))
            continue

        if style_text:
            chunk_styles.append(style_text)

        label = chunk.get("name") or run.get("name") or run.get("id") or "chunk"
        chunk_markup.append(
            f'      <section class="assembly-chunk" data-chunk-name="{label}" '
            f'data-chunk-kind="{chunk.get("kind") or "leaf"}" '
            f'style="left:{format_px(left)}px;top:{format_px(top)}px;'
            f'width:{format_px(width)}px;height:{format_px(height)}px;">'
            f"{body_markup}</section>"
        )

    html = build_html(
        prototype_name=prototype_name,
        root_bounds=root_bounds,
        chunk_styles=chunk_styles,
        chunk_markup=chunk_markup,
        missing_chunks=missing_chunks,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")

    print(
        json.dumps(
            {
                "prototypeDir": str(prototype_dir).replace("\\", "/"),
                "chunksDir": str(chunks_dir).replace("\\", "/"),
                "output": str(output_path).replace("\\", "/"),
                "chunkCount": len(chunk_markup),
                "missingCount": len(missing_chunks),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
