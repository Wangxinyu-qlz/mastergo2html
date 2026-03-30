#!/usr/bin/env python3
"""Built-in adapters and adapter loading for the generic DSL HTML kernel."""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from typing import Any

from dsl_to_html_kernel import BaseDslHtmlAdapter


class NormalizedDslAdapter(BaseDslHtmlAdapter):
    """Pass-through adapter for already-normalized DSL payloads."""


class RenderDslHifiAdapter(BaseDslHtmlAdapter):
    """Adapter for render-dsl-hifi@1 payloads."""

    css_prefix = "hifi"

    def get_base_css(self) -> str:
        return """
* { box-sizing: border-box; }
html, body { margin: 0; width: 100%; height: 100%; overflow: hidden; }
body {
  background: #000;
  color: #fff;
  font-family: "AlibabaPuHuiTi", "PingFang SC", "Microsoft YaHei", sans-serif;
}
.hifi-shell {
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  position: relative;
  background: #000;
}
.hifi-stage {
  position: absolute;
  left: 50%;
  top: 50%;
  isolation: isolate;
  transform-origin: center center;
  will-change: transform;
}
.hifi-node {
  position: absolute;
  overflow: visible;
}
.hifi-frame,
.hifi-group,
.hifi-layer,
.hifi-instance {
  display: block;
}
.hifi-text {
  margin: 0;
  padding: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  text-rendering: geometricPrecision;
}
.hifi-vector {
  display: block;
  overflow: visible;
}
.hifi-vector > svg {
  display: block;
  width: 100%;
  height: 100%;
  overflow: visible;
}
""".strip()

    def _get_parent_index(self, data: dict[str, Any]) -> dict[str, dict[str, Any]]:
        parent_index = data.get("__adapterParentIndex")
        if isinstance(parent_index, dict):
            return parent_index

        parent_index = {}

        def walk(node: dict[str, Any]) -> None:
            for child in node.get("children") or []:
                parent_index[str(child.get("id") or "")] = node
                walk(child)

        for root in self.get_roots(data):
            walk(root)

        data["__adapterParentIndex"] = parent_index
        return parent_index

    def _get_parent_node(self, node: dict[str, Any], data: dict[str, Any]) -> dict[str, Any] | None:
        return self._get_parent_index(data).get(self.get_node_id(node))

    def text_css_overrides(self, node: dict[str, Any], data: dict[str, Any]) -> list[str]:
        return []

    def render_text(self, node: dict[str, Any], data: dict[str, Any]) -> str:
        return super().render_text(node, data)

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

    def vector_css_overrides(self, node: dict[str, Any], data: dict[str, Any]) -> list[str]:
        return []

    def node_css_overrides(self, node: dict[str, Any], data: dict[str, Any]) -> list[str]:
        return []


BUILTIN_ADAPTERS = {
    "normalized": NormalizedDslAdapter,
    "render-dsl-hifi": RenderDslHifiAdapter,
}


def infer_adapter_name(payload: dict[str, Any]) -> str:
    format_name = str(payload.get("format", ""))
    if format_name.startswith("render-dsl-hifi@"):
        return "render-dsl-hifi"
    return "normalized"


def _load_adapter_from_module(module: Any) -> BaseDslHtmlAdapter:
    if hasattr(module, "build_adapter"):
        adapter = module.build_adapter()
    elif hasattr(module, "ADAPTER"):
        adapter = module.ADAPTER
    else:
        raise ValueError("adapter module must expose build_adapter() or ADAPTER")
    if not isinstance(adapter, BaseDslHtmlAdapter):
        raise TypeError("adapter must inherit from BaseDslHtmlAdapter")
    return adapter


def load_adapter(spec: str | None, payload: dict[str, Any]) -> BaseDslHtmlAdapter:
    adapter_name = spec or infer_adapter_name(payload)
    adapter_cls = BUILTIN_ADAPTERS.get(adapter_name)
    if adapter_cls is not None:
        return adapter_cls()

    if adapter_name.endswith(".py"):
        module_path = Path(adapter_name).expanduser().resolve()
        module_spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
        if module_spec is None or module_spec.loader is None:
            raise ValueError(f"failed to load adapter file: {module_path}")
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        return _load_adapter_from_module(module)

    module = importlib.import_module(adapter_name)
    return _load_adapter_from_module(module)
