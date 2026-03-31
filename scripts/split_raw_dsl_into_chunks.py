#!/usr/bin/env python3
"""Split a raw MasterGo DSL tree into smaller structural chunks.

The script works on raw DSL payloads shaped like:
{
  "styles": {...},
  "nodes": [...],
  "components": {...}
}

It identifies structural FRAME/GROUP nodes, recursively splits oversized chunks,
and writes:
- chunk.manifest.json: summary and restore order
- chunk.tree.json: recursive chunk tree with split decisions
- leaf-chunks.manifest.json: final non-overlapping leaf chunks for restoration
- chunks/<index>-<slug>.json: raw DSL subtree files
- chunks.md: human-readable structure report
"""

from __future__ import annotations

import argparse
import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def slugify(value: str, fallback: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", value or "")
    text = text.replace("_", "-").replace("/", "-").replace(":", "-")
    text = re.sub(r"[^a-zA-Z0-9-]+", "-", text).strip("-").lower()
    return text or fallback


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any], *, pretty: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
    )
    path.write_text(rendered + ("\n" if pretty else ""), encoding="utf-8")


def node_box(node: dict[str, Any]) -> list[float]:
    layout = node.get("layoutStyle") or {}
    return [
        float(layout.get("relativeX", 0) or 0),
        float(layout.get("relativeY", 0) or 0),
        float(layout.get("width", 0) or 0),
        float(layout.get("height", 0) or 0),
    ]


def node_box_absolute(node: dict[str, Any], offset_x: float = 0.0, offset_y: float = 0.0) -> list[float]:
    x, y, width, height = node_box(node)
    return [offset_x + x, offset_y + y, width, height]


def count_text_chars(node: dict[str, Any]) -> int:
    total = 0
    for item in node.get("text") or []:
        total += len(str(item.get("text") or ""))
    for child in node.get("children") or []:
        total += count_text_chars(child)
    return total


def flatten_text(node: dict[str, Any]) -> str:
    parts: list[str] = []

    def walk(current: dict[str, Any]) -> None:
        for item in current.get("text") or []:
            text = str(item.get("text") or "").strip()
            if text:
                parts.append(text)
        for child in current.get("children") or []:
            walk(child)

    walk(node)
    return " ".join(parts).strip()


def count_descendants(node: dict[str, Any]) -> int:
    return 1 + sum(count_descendants(child) for child in node.get("children") or [])


def count_types(node: dict[str, Any], target_type: str) -> int:
    total = 1 if str(node.get("type") or "") == target_type else 0
    for child in node.get("children") or []:
        total += count_types(child, target_type)
    return total


def max_depth(node: dict[str, Any]) -> int:
    children = node.get("children") or []
    if not children:
        return 0
    return 1 + max(max_depth(child) for child in children)


def first_text(node: dict[str, Any]) -> str:
    text = flatten_text(node)
    if len(text) <= 40:
        return text
    return text[:37] + "..."


def has_visual_payload(node: dict[str, Any]) -> bool:
    return bool(
        node.get("path")
        or node.get("fill") is not None
        or node.get("effect")
        or node.get("strokeColor")
        or node.get("text")
    )


def child_type_counts(node: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for child in node.get("children") or []:
        kind = str(child.get("type") or "UNKNOWN")
        counts[kind] = counts.get(kind, 0) + 1
    return counts


RAW_VECTOR_TYPES = {
    "PATH",
    "VECTOR",
    "LINE",
    "SVG_ELLIPSE",
    "SVG_POLYGON",
    "BOOLEAN_OPERATION",
    "STAR",
    "REGULAR_POLYGON",
    "LAYER",
}

RAW_STRUCTURAL_TYPES = {"FRAME", "GROUP", "INSTANCE", "COMPONENT", "COMPONENT_SET"}


def vector_subtree_metrics(node: dict[str, Any]) -> dict[str, Any]:
    vector_count = 0
    text_count = 0
    structural_count = 0
    other_count = 0

    def walk(current: dict[str, Any], *, include_self: bool) -> None:
        nonlocal vector_count, text_count, structural_count, other_count
        if include_self:
            kind = str(current.get("type") or "UNKNOWN")
            if kind == "TEXT":
                text_count += 1
            elif kind in RAW_STRUCTURAL_TYPES:
                structural_count += 1
            elif kind in RAW_VECTOR_TYPES:
                vector_count += 1
            else:
                other_count += 1
        for child in current.get("children") or []:
            walk(child, include_self=True)

    walk(node, include_self=False)
    drawable_count = vector_count + other_count
    vector_density = (vector_count / drawable_count) if drawable_count else 0.0
    return {
        "vectorNodeCount": vector_count,
        "textNodeCount": text_count,
        "structuralNodeCount": structural_count,
        "otherNodeCount": other_count,
        "drawableNodeCount": drawable_count,
        "vectorDensity": round(vector_density, 5),
        "isPureVectorArt": bool(vector_count and text_count == 0 and other_count == 0),
    }


def is_atomic_visual_subtree(node: dict[str, Any]) -> bool:
    descendants = count_descendants(node)
    if descendants < 4:
        return False
    if node.get("flexContainerInfo"):
        return False
    metrics = vector_subtree_metrics(node)
    if metrics["isPureVectorArt"]:
        return True
    if metrics["textNodeCount"] > 0:
        return False
    visual_count = metrics["vectorNodeCount"]
    structural_count = metrics["structuralNodeCount"]
    # Keep dense vector/icon/chart groups intact instead of splitting by raw counts.
    return bool(visual_count >= 3 and metrics["vectorDensity"] >= 0.85 and descendants >= max(4, structural_count + 1))


def structural_score(node: dict[str, Any], depth: int) -> int:
    kind = str(node.get("type") or "")
    children = node.get("children") or []
    descendants = count_descendants(node)
    text_count = count_types(node, "TEXT")
    group_count = count_types(node, "GROUP")
    frame_count = count_types(node, "FRAME")
    path_count = count_types(node, "PATH")
    child_counts = child_type_counts(node)
    mixed = len(child_counts)

    score = 0
    if kind == "FRAME":
        score += 5
    elif kind == "GROUP":
        score += 3
    else:
        return 0

    if not children:
        return 0

    score += min(len(children), 8)
    score += min(descendants // 3, 8)
    score += min(text_count, 4)
    score += min(group_count + frame_count, 6)
    if mixed >= 3:
        score += 4
    elif mixed == 2:
        score += 2

    if path_count >= max(8, descendants // 2):
        score -= 4
    if depth <= 1:
        score += 2
    if len(children) == 1 and not text_count:
        score -= 4
    return score


def is_chunk_candidate(node: dict[str, Any], depth: int, min_descendants: int) -> bool:
    kind = str(node.get("type") or "")
    children = node.get("children") or []
    if kind not in {"FRAME", "GROUP"} or not children:
        return False
    descendants = count_descendants(node)
    if descendants < min_descendants:
        return False
    if is_atomic_visual_subtree(node):
        return True

    child_counts = child_type_counts(node)
    if kind == "FRAME":
        if any(key in child_counts for key in ("FRAME", "GROUP", "TEXT")):
            return True
        return structural_score(node, depth) >= 9

    if any(key in child_counts for key in ("FRAME", "GROUP")):
        return True
    if count_types(node, "TEXT") >= 2 and descendants >= min_descendants:
        return True
    return structural_score(node, depth) >= 10


@dataclass
class Candidate:
    node: dict[str, Any]
    depth: int
    path: str
    score: int
    kind: str = "leaf"
    absolute_bounds: list[float] | None = None


def collect_candidates(root: dict[str, Any], min_descendants: int) -> list[Candidate]:
    candidates: list[Candidate] = []

    def walk(node: dict[str, Any], depth: int, path: str) -> None:
        if depth > 0 and is_chunk_candidate(node, depth, min_descendants):
            candidates.append(
                Candidate(
                    node=node,
                    depth=depth,
                    path=path,
                    score=structural_score(node, depth),
                )
            )
        for index, child in enumerate(node.get("children") or []):
            walk(child, depth + 1, f"{path}/children[{index}]")

    walk(root, 0, "roots[0]")
    return candidates


def select_chunks(root: dict[str, Any], min_descendants: int) -> list[Candidate]:
    selected: list[Candidate] = []

    def walk(node: dict[str, Any], depth: int, path: str) -> None:
        if depth > 0 and is_chunk_candidate(node, depth, min_descendants):
            selected.append(
                Candidate(
                    node=node,
                    depth=depth,
                    path=path,
                    score=structural_score(node, depth),
                )
            )
            return
        for index, child in enumerate(node.get("children") or []):
            walk(child, depth + 1, f"{path}/children[{index}]")

    walk(root, 0, "roots[0]")
    return selected


def area_ratio(node: dict[str, Any], root_box: list[float]) -> float:
    _, _, width, height = node_box(node)
    root_area = max(root_box[2], 1.0) * max(root_box[3], 1.0)
    node_area = max(width, 0.0) * max(height, 0.0)
    return 0.0 if root_area <= 0 else node_area / root_area


def has_structural_children(node: dict[str, Any]) -> bool:
    children = node.get("children") or []
    counts = child_type_counts(node)
    if any(kind in counts for kind in ("FRAME", "GROUP")):
        return True
    return len(children) >= 3 and count_types(node, "TEXT") >= 2


def make_metrics(node: dict[str, Any], root_box: list[float], absolute_x: float, absolute_y: float) -> dict[str, Any]:
    vector_metrics = vector_subtree_metrics(node)
    return {
        "bounds": node_box(node),
        "absoluteBounds": node_box_absolute(node, absolute_x, absolute_y),
        "childCount": len(node.get("children") or []),
        "descendantCount": count_descendants(node),
        "maxDepth": max_depth(node),
        "textNodeCount": count_types(node, "TEXT"),
        "groupNodeCount": count_types(node, "GROUP"),
        "frameNodeCount": count_types(node, "FRAME"),
        "pathNodeCount": count_types(node, "PATH"),
        "textCharCount": count_text_chars(node),
        "childTypeCounts": child_type_counts(node),
        "areaRatio": round(area_ratio(node, root_box), 5),
        "hasStructuralChildren": has_structural_children(node),
        "hasVisualPayload": has_visual_payload(node),
        "vectorNodeCount": vector_metrics["vectorNodeCount"],
        "vectorDensity": vector_metrics["vectorDensity"],
        "isAtomicVectorArt": vector_metrics["isPureVectorArt"],
    }


def should_split_node(
    node: dict[str, Any],
    *,
    depth: int,
    root_box: list[float],
    min_descendants: int,
    split_descendants: int,
    split_paths: int,
    split_children: int,
    split_depth: int,
    split_structural_nodes: int,
    split_text_nodes: int,
    min_area_ratio: float,
) -> tuple[bool, dict[str, Any], list[str]]:
    metrics = make_metrics(node, root_box, absolute_x=0.0, absolute_y=0.0)
    reasons: list[str] = []
    if is_atomic_visual_subtree(node):
        return False, metrics, ["atomicVisualSubtree"]
    if metrics["descendantCount"] > split_descendants:
        reasons.append(f"descendantCount>{split_descendants}")
    if metrics["pathNodeCount"] > split_paths:
        reasons.append(f"pathNodeCount>{split_paths}")
    if metrics["childCount"] > split_children:
        reasons.append(f"childCount>{split_children}")
    if metrics["maxDepth"] > split_depth:
        reasons.append(f"maxDepth>{split_depth}")
    if metrics["groupNodeCount"] + metrics["frameNodeCount"] > split_structural_nodes:
        reasons.append(f"structuralNodeCount>{split_structural_nodes}")
    if metrics["textNodeCount"] > split_text_nodes:
        reasons.append(f"textNodeCount>{split_text_nodes}")

    too_small = (
        metrics["areaRatio"] < min_area_ratio
        or metrics["bounds"][2] < 80
        or metrics["bounds"][3] < 80
    )
    enough_size = metrics["descendantCount"] >= min_descendants
    can_split = metrics["hasStructuralChildren"] and not too_small and enough_size
    return bool(reasons) and can_split, metrics, reasons


def select_direct_children(node: dict[str, Any], path: str, min_descendants: int) -> list[Candidate]:
    candidates: list[Candidate] = []
    for index, child in enumerate(node.get("children") or []):
        child_path = f"{path}/children[{index}]"
        if is_chunk_candidate(child, 1, min_descendants):
            candidates.append(
                Candidate(
                    node=child,
                    depth=1,
                    path=child_path,
                    score=structural_score(child, 1),
                )
            )
    return candidates


def build_chunk_tree(
    node: dict[str, Any],
    *,
    path: str,
    depth: int,
    root_box: list[float],
    min_descendants: int,
    split_descendants: int,
    split_paths: int,
    split_children: int,
    split_depth: int,
    split_structural_nodes: int,
    split_text_nodes: int,
    min_area_ratio: float,
    absolute_x: float = 0.0,
    absolute_y: float = 0.0,
) -> dict[str, Any]:
    split, metrics, reasons = should_split_node(
        node,
        depth=depth,
        root_box=root_box,
        min_descendants=min_descendants,
        split_descendants=split_descendants,
        split_paths=split_paths,
        split_children=split_children,
        split_depth=split_depth,
        split_structural_nodes=split_structural_nodes,
        split_text_nodes=split_text_nodes,
        min_area_ratio=min_area_ratio,
    )
    metrics["absoluteBounds"] = node_box_absolute(node, absolute_x, absolute_y)
    tree = {
        "id": str(node.get("id") or ""),
        "name": str(node.get("name") or ""),
        "type": str(node.get("type") or ""),
        "path": path,
        "depth": depth,
        "score": structural_score(node, depth),
        "metrics": metrics,
        "decision": {
            "shouldSplit": split,
            "reasons": reasons,
        },
        "children": [],
    }
    if not split:
        return tree

    direct_children = select_direct_children(node, path, min_descendants)
    if not direct_children:
        tree["decision"]["shouldSplit"] = False
        tree["decision"]["reasons"] = [*reasons, "noDirectStructuralChildren"]
        return tree

    tree["children"] = [
        build_chunk_tree(
            child.node,
            path=child.path,
            depth=depth + 1,
            root_box=root_box,
            min_descendants=min_descendants,
            split_descendants=split_descendants,
            split_paths=split_paths,
            split_children=split_children,
            split_depth=split_depth,
            split_structural_nodes=split_structural_nodes,
            split_text_nodes=split_text_nodes,
            min_area_ratio=min_area_ratio,
            absolute_x=absolute_x + node_box(child.node)[0],
            absolute_y=absolute_y + node_box(child.node)[1],
        )
        for child in direct_children
    ]
    return tree


def zero_chunk_root(node: dict[str, Any]) -> dict[str, Any]:
    cloned = copy.deepcopy(node)
    layout = copy.deepcopy(cloned.get("layoutStyle") or {})
    layout["relativeX"] = 0
    layout["relativeY"] = 0
    cloned["layoutStyle"] = layout
    return cloned


def lookup_node_by_path(root: dict[str, Any], path: str) -> dict[str, Any]:
    if path == "roots[0]":
        return root
    current = root
    for index_text in re.findall(r"children\[(\d+)\]", path):
        current = (current.get("children") or [])[int(index_text)]
    return current


def chunk_summary(candidate: Candidate, index: int) -> dict[str, Any]:
    node = candidate.node
    descendants = count_descendants(node)
    absolute_bounds = candidate.absolute_bounds or node_box(node)
    relative_bounds = node_box(node)
    vector_metrics = vector_subtree_metrics(node)
    summary = {
        "index": index,
        "id": str(node.get("id") or ""),
        "name": str(node.get("name") or ""),
        "type": str(node.get("type") or ""),
        "kind": candidate.kind,
        "depth": candidate.depth,
        "path": candidate.path,
        "score": candidate.score,
        "bounds": relative_bounds,
        "absoluteBounds": absolute_bounds,
        "normalizedBounds": [0, 0, relative_bounds[2], relative_bounds[3]],
        "childCount": len(node.get("children") or []),
        "descendantCount": descendants,
        "maxDepth": max_depth(node),
        "textNodeCount": count_types(node, "TEXT"),
        "groupNodeCount": count_types(node, "GROUP"),
        "frameNodeCount": count_types(node, "FRAME"),
        "pathNodeCount": count_types(node, "PATH"),
        "vectorNodeCount": vector_metrics["vectorNodeCount"],
        "vectorDensity": vector_metrics["vectorDensity"],
        "isAtomicVectorArt": vector_metrics["isPureVectorArt"],
        "childTypeCounts": child_type_counts(node),
        "textPreview": first_text(node),
    }
    return summary


def write_chunk_files(
    source: dict[str, Any],
    selected: list[Candidate],
    out_dir: Path,
) -> list[dict[str, Any]]:
    chunk_entries: list[dict[str, Any]] = []
    chunks_dir = out_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    for index, candidate in enumerate(selected, start=1):
        node = zero_chunk_root(candidate.node)
        name = str(node.get("name") or f"chunk-{index}")
        node_id = str(node.get("id") or f"chunk-{index}").replace(":", "-")
        filename = f"{index:03d}-{slugify(name, node_id)}-{node_id}.json"
        chunk_path = chunks_dir / filename
        payload = {
            "styles": source.get("styles") or {},
            "components": source.get("components") or {},
            "nodes": [node],
            "chunkMeta": chunk_summary(candidate, index),
        }
        write_json(chunk_path, payload, pretty=True)
        entry = chunk_summary(candidate, index)
        entry["file"] = str(chunk_path).replace("\\", "/")
        chunk_entries.append(entry)
    return chunk_entries


def build_render_chunks(
    node: dict[str, Any],
    *,
    path: str,
    depth: int,
    absolute_x: float,
    absolute_y: float,
    root_box: list[float],
    min_descendants: int,
    split_descendants: int,
    split_paths: int,
    split_children: int,
    split_depth: int,
    split_structural_nodes: int,
    split_text_nodes: int,
    min_area_ratio: float,
) -> list[Candidate]:
    split, _, _ = should_split_node(
        node,
        depth=depth,
        root_box=root_box,
        min_descendants=min_descendants,
        split_descendants=split_descendants,
        split_paths=split_paths,
        split_children=split_children,
        split_depth=split_depth,
        split_structural_nodes=split_structural_nodes,
        split_text_nodes=split_text_nodes,
        min_area_ratio=min_area_ratio,
    )
    if not split:
        _, _, width, height = node_box(node)
        return [
            Candidate(
                node=node,
                depth=depth,
                path=path,
                score=structural_score(node, depth),
                kind="leaf",
                absolute_bounds=[absolute_x, absolute_y, width, height],
            )
        ]

    direct_children = select_direct_children(node, path, min_descendants)
    if not direct_children:
        _, _, width, height = node_box(node)
        return [
            Candidate(
                node=node,
                depth=depth,
                path=path,
                score=structural_score(node, depth),
                kind="leaf",
                absolute_bounds=[absolute_x, absolute_y, width, height],
            )
        ]

    selected_paths = {item.path for item in direct_children}
    residual_children = [
        child
        for index, child in enumerate(node.get("children") or [])
        if f"{path}/children[{index}]" not in selected_paths
    ]

    chunks: list[Candidate] = []
    if has_visual_payload(node) or residual_children:
        base_node = copy.deepcopy(node)
        base_node["children"] = residual_children
        _, _, width, height = node_box(node)
        chunks.append(
            Candidate(
                node=base_node,
                depth=depth,
                path=path,
                score=structural_score(node, depth),
                kind="base",
                absolute_bounds=[absolute_x, absolute_y, width, height],
            )
        )

    for child in direct_children:
        child_x, child_y, _, _ = node_box(child.node)
        chunks.extend(
            build_render_chunks(
                child.node,
                path=child.path,
                depth=depth + 1,
                absolute_x=absolute_x + child_x,
                absolute_y=absolute_y + child_y,
                root_box=root_box,
                min_descendants=min_descendants,
                split_descendants=split_descendants,
                split_paths=split_paths,
                split_children=split_children,
                split_depth=split_depth,
                split_structural_nodes=split_structural_nodes,
                split_text_nodes=split_text_nodes,
                min_area_ratio=min_area_ratio,
            )
        )
    return chunks


def render_markdown(
    source_path: Path,
    root: dict[str, Any],
    all_candidates: list[Candidate],
    chunk_entries: list[dict[str, Any]],
) -> str:
    lines = [
        "# DSL Chunk Report",
        "",
        f"- source: `{source_path.as_posix()}`",
        f"- page: `{root.get('name') or root.get('id')}`",
        f"- selectedChunks: `{len(chunk_entries)}`",
        f"- candidateChunks: `{len(all_candidates)}`",
        "",
        "## Selected Chunks",
        "",
    ]
    for entry in chunk_entries:
        lines.append(
            f"- `{entry['index']:03d}` `{entry['type']}` `{entry['name']}` "
            f"id=`{entry['id']}` depth=`{entry['depth']}` descendants=`{entry['descendantCount']}` "
            f"score=`{entry['score']}`"
        )
    lines.extend(["", "## Candidate Nodes", ""])
    for index, candidate in enumerate(sorted(all_candidates, key=lambda item: (item.depth, -item.score)), start=1):
        summary = chunk_summary(candidate, index)
        lines.append(
            f"- `{summary['type']}` `{summary['name']}` id=`{summary['id']}` "
            f"path=`{summary['path']}` descendants=`{summary['descendantCount']}` score=`{summary['score']}`"
        )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Path to raw dsl json")
    parser.add_argument(
        "-o",
        "--out-dir",
        type=Path,
        help="Output directory. Defaults to <input-dir>/chunks",
    )
    parser.add_argument(
        "--min-descendants",
        type=int,
        default=6,
        help="Minimum subtree size for chunk selection",
    )
    parser.add_argument("--split-descendants", type=int, default=60, help="Split when descendant count exceeds this")
    parser.add_argument("--split-paths", type=int, default=30, help="Split when PATH node count exceeds this")
    parser.add_argument("--split-children", type=int, default=10, help="Split when direct child count exceeds this")
    parser.add_argument("--split-depth", type=int, default=3, help="Split when subtree depth exceeds this")
    parser.add_argument(
        "--split-structural-nodes",
        type=int,
        default=8,
        help="Split when GROUP+FRAME count exceeds this",
    )
    parser.add_argument("--split-text-nodes", type=int, default=12, help="Split when TEXT count exceeds this")
    parser.add_argument(
        "--min-area-ratio",
        type=float,
        default=0.03,
        help="Do not recurse below this page-relative area ratio",
    )
    parser.add_argument("--pretty", action="store_true", help="Keep manifest pretty printed")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = load_json(args.input)
    roots = source.get("nodes") or []
    if len(roots) != 1 or not isinstance(roots[0], dict):
        raise SystemExit("Expected raw DSL with exactly one root node in nodes[]")

    root = roots[0]
    out_dir = args.out_dir or args.input.with_suffix("").with_name(f"{args.input.stem}.chunks")
    root_box = node_box(root)
    all_candidates = collect_candidates(root, args.min_descendants)
    selected = select_chunks(root, args.min_descendants)
    chunk_tree = build_chunk_tree(
        root,
        path="roots[0]",
        depth=0,
        root_box=root_box,
        min_descendants=args.min_descendants,
        split_descendants=args.split_descendants,
        split_paths=args.split_paths,
        split_children=args.split_children,
        split_depth=args.split_depth,
        split_structural_nodes=args.split_structural_nodes,
        split_text_nodes=args.split_text_nodes,
        min_area_ratio=args.min_area_ratio,
    )
    render_candidates = build_render_chunks(
        root,
        path="roots[0]",
        depth=0,
        absolute_x=0.0,
        absolute_y=0.0,
        root_box=root_box,
        min_descendants=args.min_descendants,
        split_descendants=args.split_descendants,
        split_paths=args.split_paths,
        split_children=args.split_children,
        split_depth=args.split_depth,
        split_structural_nodes=args.split_structural_nodes,
        split_text_nodes=args.split_text_nodes,
        min_area_ratio=args.min_area_ratio,
    )
    chunk_entries = write_chunk_files(source, render_candidates, out_dir)
    candidate_entries = [
        chunk_summary(candidate, index)
        for index, candidate in enumerate(
            sorted(all_candidates, key=lambda item: (item.depth, -item.score)),
            start=1,
        )
    ]

    manifest = {
        "version": "mastergo2html.raw-dsl-chunks.v1",
        "meta": {
            "source": str(args.input).replace("\\", "/"),
            "rootName": root.get("name"),
            "rootId": root.get("id"),
            "minDescendants": args.min_descendants,
            "splitDescendants": args.split_descendants,
            "splitPaths": args.split_paths,
            "splitChildren": args.split_children,
            "splitDepth": args.split_depth,
            "splitStructuralNodes": args.split_structural_nodes,
            "splitTextNodes": args.split_text_nodes,
            "minAreaRatio": args.min_area_ratio,
            "selectedChunkCount": len(chunk_entries),
            "renderChunkCount": len(chunk_entries),
            "candidateChunkCount": len(all_candidates),
        },
        "rootSummary": {
            "type": root.get("type"),
            "descendantCount": count_descendants(root),
            "bounds": node_box(root),
            "textPreview": first_text(root),
        },
        "chunks": chunk_entries,
        "candidates": candidate_entries,
    }
    write_json(out_dir / "chunk.manifest.json", manifest, pretty=args.pretty or True)
    write_json(
        out_dir / "leaf-chunks.manifest.json",
        {
        "version": "mastergo2html.raw-dsl-render-chunks.v2",
        "meta": manifest["meta"],
        "chunks": chunk_entries,
        },
        pretty=True,
    )
    write_json(
        out_dir / "chunk.tree.json",
        {
            "version": "mastergo2html.raw-dsl-chunk-tree.v1",
            "meta": manifest["meta"],
            "root": chunk_tree,
        },
        pretty=True,
    )
    (out_dir / "chunks.md").write_text(
        render_markdown(args.input, root, all_candidates, chunk_entries),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "input": str(args.input).replace("\\", "/"),
                "outDir": str(out_dir).replace("\\", "/"),
                "selectedChunkCount": len(chunk_entries),
                "candidateChunkCount": len(all_candidates),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
