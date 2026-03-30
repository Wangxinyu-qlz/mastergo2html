#!/usr/bin/env python3
"""Assemble chunk-level HTML outputs back into a prototype-level preview page."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def format_px(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text if text else "0"


def resolve_root_bounds(tree: dict[str, Any]) -> list[float]:
    root = tree.get("root") or {}
    metrics = root.get("metrics") or {}
    bounds = metrics.get("bounds") or [0, 0, 1920, 1080]
    if len(bounds) != 4:
        return [0, 0, 1920, 1080]
    return [float(value) for value in bounds]


def build_chunk_index(leaf_manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for chunk in leaf_manifest.get("chunks") or []:
        for key in ("id", "path", "file"):
            value = chunk.get(key)
            if value:
                index[str(value)] = chunk
    return index


def choose_chunk(run: dict[str, Any], chunk_index: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [
        run.get("id"),
        run.get("path"),
        run.get("sourceChunk"),
    ]
    for value in candidates:
        if value is None:
            continue
        match = chunk_index.get(str(value))
        if match:
            return match
    return None


def build_html(
    *,
    prototype_name: str,
    root_bounds: list[float],
    chunk_frames: list[str],
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
    frames_html = "\n".join(chunk_frames)
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
}}
.chunk-frame {{
  position: absolute;
  display: block;
  border: 0;
  background: transparent;
  overflow: hidden;
}}
.assembly-caption {{
  position: absolute;
  left: 18px;
  top: 18px;
  z-index: 2;
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
  z-index: 2;
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
  </style>
</head>
<body>
  <main class="assembly-shell">
    <section class="assembly-caption">
      <div>{prototype_name}</div>
      <div>assembled from chunk HTML outputs</div>
      <div>stage: {format_px(root_width)} x {format_px(root_height)}</div>
    </section>
{warnings_html}    <section class="assembly-stage" data-prototype-name="{prototype_name}">
{frames_html}
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

    leaf_manifest = load_json(chunks_dir / "leaf-chunks.manifest.json")
    pipeline_manifest = load_json(chunks_dir / "chunk-pipeline.manifest.json")
    tree = load_json(chunks_dir / "chunk.tree.json")

    root_bounds = resolve_root_bounds(tree)
    prototype_name = (
        ((tree.get("root") or {}).get("name"))
        or ((leaf_manifest.get("meta") or {}).get("rootName"))
        or prototype_dir.name
    )

    chunk_index = build_chunk_index(leaf_manifest)
    chunk_frames: list[str] = []
    missing_chunks: list[str] = []

    for run in pipeline_manifest.get("runs") or []:
        if run.get("status") != "ok":
            missing_chunks.append(f"{run.get('name') or run.get('id')}: pipeline failed")
            continue
        chunk = choose_chunk(run, chunk_index)
        if not chunk:
            missing_chunks.append(f"{run.get('name') or run.get('id')}: no chunk metadata")
            continue

        bounds = chunk.get("bounds") or [0, 0, 0, 0]
        if len(bounds) != 4:
            missing_chunks.append(f"{run.get('name') or run.get('id')}: invalid bounds")
            continue
        left, top, width, height = [float(value) for value in bounds]

        html_path = Path(str(((run.get("artifacts") or {}).get("html")) or ""))
        if not html_path.exists():
            missing_chunks.append(f"{run.get('name') or run.get('id')}: html not found")
            continue

        rel_src = html_path.resolve().relative_to(prototype_dir).as_posix()
        iframe_src = f"../{rel_src}" if not rel_src.startswith("../") else rel_src
        label = chunk.get("name") or run.get("name") or run.get("id") or "chunk"
        chunk_frames.append(
            f'      <iframe class="chunk-frame" title="{label}" '
            f'src="{iframe_src}" loading="lazy" scrolling="no" '
            f'style="left:{format_px(left)}px;top:{format_px(top)}px;'
            f'width:{format_px(width)}px;height:{format_px(height)}px;"></iframe>'
        )

    html = build_html(
        prototype_name=prototype_name,
        root_bounds=root_bounds,
        chunk_frames=chunk_frames,
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
                "chunkCount": len(chunk_frames),
                "missingCount": len(missing_chunks),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
