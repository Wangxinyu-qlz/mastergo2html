#!/usr/bin/env python3
"""Run the mastergo2htmlV3 pipeline over recursively split raw DSL chunks."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent.parent.parent
DEFAULT_RULES = SCRIPT_DIR.parent / "examples" / "direction-rules.example.json"


def slugify(value: str, fallback: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", value or "")
    text = text.replace("_", "-").replace("/", "-").replace(":", "-")
    text = re.sub(r"[^a-zA-Z0-9-]+", "-", text).strip("-").lower()
    return text or fallback


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any], pretty: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
    )
    path.write_text(rendered + ("\n" if pretty else ""), encoding="utf-8")


def run_command(args: list[str], *, cwd: Path) -> dict[str, Any]:
    completed = subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "args": args,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def stage_enabled(enabled: set[str], stage: str) -> bool:
    return "all" in enabled or stage in enabled


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "prototype_dir",
        type=Path,
        help="Prototype directory, e.g. .mastergo2html/prototypes/<prototype_key>",
    )
    parser.add_argument(
        "--chunks-dir",
        type=Path,
        help="Chunk directory. Defaults to <prototype_dir>/dsl_chunks",
    )
    parser.add_argument(
        "--mode",
        choices=("simple", "hifi"),
        default="hifi",
        help="Compression mode for each chunk",
    )
    parser.add_argument(
        "--stages",
        nargs="+",
        default=["all"],
        choices=("all", "compress", "structure", "analyze", "plan", "render", "assemble"),
        help="Stages to execute",
    )
    parser.add_argument(
        "--rules",
        type=Path,
        default=DEFAULT_RULES,
        help="Rules file passed to analyze/component-map stages",
    )
    parser.add_argument(
        "--force-resplit",
        action="store_true",
        help="Rebuild chunk manifests from prototype_dir/dsl_raw.json before running the chunk pipeline",
    )
    parser.add_argument(
        "--split-args",
        nargs="*",
        default=[],
        help="Extra args forwarded to split_raw_dsl_into_chunks.py when --force-resplit is used",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Abort the pipeline when a chunk stage fails",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Write pretty printed manifest files",
    )
    return parser.parse_args()


def ensure_chunks(args: argparse.Namespace, prototype_dir: Path, chunks_dir: Path) -> None:
    leaf_manifest = chunks_dir / "leaf-chunks.manifest.json"
    if leaf_manifest.exists() and not args.force_resplit:
        return
    raw_dsl = prototype_dir / "dsl_raw.json"
    if not raw_dsl.exists():
        raise SystemExit(f"Missing raw DSL: {raw_dsl}")
    split_script = SCRIPT_DIR / "split_raw_dsl_into_chunks.py"
    command = [
        sys.executable,
        str(split_script),
        str(raw_dsl),
        "-o",
        str(chunks_dir),
        *args.split_args,
    ]
    result = run_command(command, cwd=ROOT_DIR)
    if result["returncode"] != 0:
        raise SystemExit(
            "Failed to build chunk manifests.\n"
            f"stdout:\n{result['stdout']}\n"
            f"stderr:\n{result['stderr']}"
        )


def build_stage_commands(
    run_dir: Path,
    *,
    mode: str,
    rules: Path,
    render: bool,
) -> list[tuple[str, list[str]]]:
    compress_script = SCRIPT_DIR / ("compress_dsl_hifi.py" if mode == "hifi" else "compress_dsl.py")
    commands: list[tuple[str, list[str]]] = [
        (
            "compress",
            [
                sys.executable,
                str(compress_script),
                str(run_dir / "dsl_raw.json"),
                "-o",
                str(run_dir / "dsl.compressed.json"),
            ],
        ),
        (
            "structure",
            [
                sys.executable,
                str(SCRIPT_DIR / "build_page_structure.py"),
                str(run_dir / "dsl.compressed.json"),
                "-o",
                str(run_dir / "page.structure.json"),
            ],
        ),
        (
            "analyze",
            [
                sys.executable,
                str(SCRIPT_DIR / "build_semantic_map.py"),
                str(run_dir / "dsl.compressed.json"),
                str(run_dir / "page.structure.json"),
                "--rules",
                str(rules),
                "-o",
                str(run_dir / "semantic.map.json"),
            ],
        ),
        (
            "plan",
            [
                sys.executable,
                str(SCRIPT_DIR / "build_component_map.py"),
                str(run_dir / "dsl.compressed.json"),
                str(run_dir / "page.structure.json"),
                str(run_dir / "semantic.map.json"),
                "--rules",
                str(rules),
                "-o",
                str(run_dir / "component.map.json"),
            ],
        ),
        (
            "plan",
            [
                sys.executable,
                str(SCRIPT_DIR / "build_alignment_rules.py"),
                str(run_dir / "dsl.compressed.json"),
                str(run_dir / "component.map.json"),
                "-o",
                str(run_dir / "alignment.rules.json"),
            ],
        ),
        (
            "plan",
            [
                sys.executable,
                str(SCRIPT_DIR / "build_render_plan.py"),
                str(run_dir / "dsl.compressed.json"),
                str(run_dir / "semantic.map.json"),
                "--structure",
                str(run_dir / "page.structure.json"),
                "--component-map",
                str(run_dir / "component.map.json"),
                "--alignment",
                str(run_dir / "alignment.rules.json"),
                "-o",
                str(run_dir / "render.plan.json"),
            ],
        ),
    ]
    if render:
        commands.append(
            (
                "render",
                [
                    sys.executable,
                    str(SCRIPT_DIR / "render_any_dsl_to_html.py"),
                    str(run_dir / "dsl.compressed.json"),
                    "--plan",
                    str(run_dir / "render.plan.json"),
                    "-o",
                    str(run_dir / "output" / "index.html"),
                ],
            )
        )
    return commands


def prepare_run_dir(chunk_file: Path, run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(chunk_file, run_dir / "dsl_raw.json")


def run_assemble_stage(
    *,
    prototype_dir: Path,
    chunks_dir: Path,
    enabled_stages: set[str],
) -> dict[str, Any] | None:
    if not stage_enabled(enabled_stages, "assemble"):
        return None
    command = [
        sys.executable,
        str(SCRIPT_DIR / "assemble_chunk_html.py"),
        str(prototype_dir),
        "--chunks-dir",
        str(chunks_dir),
        "-o",
        str(prototype_dir / "output" / "assembled.html"),
    ]
    return run_command(command, cwd=ROOT_DIR)


def main() -> None:
    args = parse_args()
    prototype_dir = args.prototype_dir.resolve()
    chunks_dir = (args.chunks_dir or (prototype_dir / "dsl_chunks")).resolve()
    ensure_chunks(args, prototype_dir, chunks_dir)

    leaf_manifest = load_json(chunks_dir / "leaf-chunks.manifest.json")
    chunk_entries = leaf_manifest.get("chunks") or []
    run_root = chunks_dir / "runs"
    run_root.mkdir(parents=True, exist_ok=True)

    enabled_stages = set(args.stages)
    pipeline_entries: list[dict[str, Any]] = []
    rules_path = args.rules.resolve()

    for entry in chunk_entries:
        chunk_file = Path(str(entry["file"]))
        if not chunk_file.is_absolute():
            chunk_file = ROOT_DIR / chunk_file
        run_slug = slugify(str(entry["name"]), str(entry["id"]).replace(":", "-"))
        run_dir = run_root / f"{int(entry['index']):03d}-{run_slug}-{str(entry['id']).replace(':', '-')}"
        prepare_run_dir(chunk_file, run_dir)

        stage_results: list[dict[str, Any]] = []
        failed = False
        commands = build_stage_commands(
            run_dir,
            mode=args.mode,
            rules=rules_path,
            render=stage_enabled(enabled_stages, "render"),
        )
        for stage_name, command in commands:
            if not stage_enabled(enabled_stages, stage_name):
                continue
            result = run_command(command, cwd=ROOT_DIR)
            stage_results.append(
                {
                    "stage": stage_name,
                    "command": command,
                    "returncode": result["returncode"],
                    "stdout": result["stdout"],
                    "stderr": result["stderr"],
                }
            )
            if result["returncode"] != 0:
                failed = True
                if args.stop_on_error:
                    break

        pipeline_entries.append(
            {
                "index": entry["index"],
                "id": entry["id"],
                "name": entry["name"],
                "path": entry["path"],
                "sourceChunk": str(chunk_file).replace("\\", "/"),
                "runDir": str(run_dir).replace("\\", "/"),
                "status": "failed" if failed else "ok",
                "stages": stage_results,
                "artifacts": {
                    "raw": str((run_dir / "dsl_raw.json")).replace("\\", "/"),
                    "compressed": str((run_dir / "dsl.compressed.json")).replace("\\", "/"),
                    "structure": str((run_dir / "page.structure.json")).replace("\\", "/"),
                    "semantic": str((run_dir / "semantic.map.json")).replace("\\", "/"),
                    "componentMap": str((run_dir / "component.map.json")).replace("\\", "/"),
                    "alignment": str((run_dir / "alignment.rules.json")).replace("\\", "/"),
                    "renderPlan": str((run_dir / "render.plan.json")).replace("\\", "/"),
                    "html": str((run_dir / "output" / "index.html")).replace("\\", "/"),
                },
            }
        )
        if failed and args.stop_on_error:
            break

    manifest = {
        "version": "mastergo2html.chunk-pipeline.v1",
        "meta": {
            "prototypeDir": str(prototype_dir).replace("\\", "/"),
            "chunksDir": str(chunks_dir).replace("\\", "/"),
            "mode": args.mode,
            "stages": sorted(enabled_stages),
            "rules": str(rules_path).replace("\\", "/"),
            "chunkCount": len(chunk_entries),
            "runCount": len(pipeline_entries),
        },
        "runs": pipeline_entries,
    }
    write_json(chunks_dir / "chunk-pipeline.manifest.json", manifest, pretty=args.pretty or True)
    assemble_result = run_assemble_stage(
        prototype_dir=prototype_dir,
        chunks_dir=chunks_dir,
        enabled_stages=enabled_stages,
    )
    if assemble_result is not None:
        manifest["assembly"] = {
            "stage": "assemble",
            "command": assemble_result["args"],
            "returncode": assemble_result["returncode"],
            "stdout": assemble_result["stdout"],
            "stderr": assemble_result["stderr"],
            "artifacts": {
                "html": str((prototype_dir / "output" / "assembled.html")).replace("\\", "/"),
            },
        }
        write_json(chunks_dir / "chunk-pipeline.manifest.json", manifest, pretty=args.pretty or True)
    print(
        json.dumps(
            {
                "prototypeDir": str(prototype_dir).replace("\\", "/"),
                "chunksDir": str(chunks_dir).replace("\\", "/"),
                "runCount": len(pipeline_entries),
                "failedCount": sum(1 for item in pipeline_entries if item["status"] != "ok"),
                "manifest": str((chunks_dir / "chunk-pipeline.manifest.json")).replace("\\", "/"),
                "assembledHtml": (
                    str((prototype_dir / "output" / "assembled.html")).replace("\\", "/")
                    if assemble_result is not None and assemble_result["returncode"] == 0
                    else None
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
