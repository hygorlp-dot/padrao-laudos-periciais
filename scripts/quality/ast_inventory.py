"""Policy-free source reading and AST parsing primitives."""
from __future__ import annotations

import ast


def module_name(path: str) -> str:
    value = path[:-3].replace("/", ".")
    return value[:-9] if value.endswith(".__init__") else value


def parse_source(path: str, source: str) -> ast.AST:
    if not isinstance(source, str):
        raise TypeError(f"source must be text: {path}")
    return ast.parse(source, filename=path)
