#!/usr/bin/env python3
"""Check that cross-module imports go through each module's public surface.

The rule: a module may import from another module's `__init__.py`, and from
nowhere else inside it. `from ..storage.parquet_writer import Row` couples the
caller to an implementation detail, so changing that file's internals breaks
callers that were written against a contract they were never shown.

This is the mechanical half of docs/ARCHITECTURE.md §3. The prose states the
rule; this is what makes it hold when nobody is reading the prose.

It also rejects a dependency cycle, because a cycle means one of the two
modules is in the wrong layer and no ordering can make them independent.

Exit 0 on success, 1 with a list of violations otherwise.
"""

from __future__ import annotations

import ast
import sys
from collections import defaultdict
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
PACKAGE = SRC / "robinhood_lp_v2"

#: The layer order from docs/ARCHITECTURE.md §2. Lower may import lower.
#: Modules not listed here are unclassified and only checked for cycles.
LAYERS: dict[str, int] = {
    "storage": 0,
    "protocol": 1,
    "rpc": 2,
    "replay": 2,
    "features": 2,
    "backtest": 3,
    "strategy": 3,
    "risk": 3,
    "application": 4,
    "cli": 5,
}


def _modules() -> dict[str, Path]:
    return {
        path.relative_to(SRC).with_suffix("").as_posix().replace("/", "."): path
        for path in sorted(SRC.rglob("*.py"))
    }


def _is_private(name: str) -> bool:
    return name.startswith("_") and not name.startswith("__")


def check_direct_imports(paths: dict[str, Path]) -> list[str]:
    """Flag imports that reach past a module's public surface."""
    violations: list[str] = []
    for path in paths.values():
        if path.name == "__init__.py":
            continue
        name = path.relative_to(SRC).with_suffix("").as_posix().replace("/", ".")
        own = name.rsplit(".", 1)[0] if "." in name else ""
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                target = node.module or ""
                resolved = _resolve(own, target, node.level)
                if resolved is None:
                    continue
                if _is_private(node.module or ""):
                    violations.append(
                        f"{path.relative_to(SRC)}: imports private name "
                        f"'{node.module}' — a module's __all__ is its contract"
                    )
    return violations


def _resolve(own: str, target: str, level: int) -> str | None:
    """Return the dotted module a `from ... import` reaches, if any."""
    if level == 0:
        # Absolute import. Only relative imports can reach a sibling module.
        return None
    base = own.split(".") if own else []
    trimmed = base[: len(base) - (level - 1)] if level > 1 else base
    parts = [*trimmed, *(target.split(".") if target else [])]
    return ".".join(p for p in parts if p)


def check_layers(edges: dict[str, set[str]]) -> list[str]:
    violations = []
    for src, targets in edges.items():
        src_layer = LAYERS.get(src)
        for dst in targets:
            dst_layer = LAYERS.get(dst)
            if src_layer is None or dst_layer is None:
                continue
            if dst_layer > src_layer:
                violations.append(
                    f"{src} (layer {src_layer}) imports {dst} (layer {dst_layer}) "
                    f"— dependencies point downward only"
                )
    return violations


#: Three-colour depth-first search. Module level so the names are not locals
#: of check_cycles, where a visitor closure would need them passed in.
WHITE, GREY, BLACK = 0, 1, 2


def check_cycles(edges: dict[str, set[str]]) -> list[str]:
    """Report dependency cycles. A cycle means a layering mistake upstream."""
    colour: dict[str, int] = defaultdict(int)
    stack: list[str] = []
    found: list[str] = []

    def visit(node: str) -> None:
        colour[node] = GREY
        stack.append(node)
        for nxt in sorted(edges.get(node, ())):
            if colour[nxt] == GREY:
                cycle = " -> ".join([*stack[stack.index(nxt) :], nxt])
                found.append(cycle)
            elif colour[nxt] == WHITE:
                visit(nxt)
        stack.pop()
        colour[node] = BLACK

    for node in sorted(edges):
        if colour[node] == WHITE:
            visit(node)
    return found


def module_edges(paths: dict[str, Path]) -> dict[str, set[str]]:
    """Top-level module dependency graph, ignoring intra-module imports."""
    edges: dict[str, set[str]] = defaultdict(set)
    for name, path in paths.items():
        top = name.split(".")[0]
        if "__init__" in name:
            top = name.rsplit(".__init__", 1)[0]
        own = name.rsplit(".", 1)[0] if "." in name else ""
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level == 0:
                continue
            target = _resolve(own, node.module or "", node.level)
            if not target:
                continue
            other = target.split(".")[0]
            if other and other != top and (SRC / "robinhood_lp_v2" / other).is_dir():
                edges[top].add(other)
    return edges


def main() -> int:
    if not PACKAGE.is_dir():
        print(f"not found: {PACKAGE}", file=sys.stderr)
        return 1

    paths = _modules()
    edges = module_edges(paths)

    violations = check_direct_imports(paths) + check_layers(edges)
    cycles = check_cycles(edges)

    for cycle in cycles:
        print(f"dependency cycle: {cycle}", file=sys.stderr)
    for v in violations:
        print(v, file=sys.stderr)

    if cycles or violations:
        print(
            f"\n{len(cycles)} cycle(s), {len(violations)} violation(s).\n"
            f"See docs/ARCHITECTURE.md §3.",
            file=sys.stderr,
        )
        return 1

    print(f"boundaries ok — {len(paths)} modules, {len(edges)} with edges")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
