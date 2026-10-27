"""Export three standalone, fully editable candidates without running a search."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROUTES = {
    "partition": "recursive_hypergraph_partition",
    "tree": "tree_search_annealing",
    "beam": "budgeted_beam_search",
}


def export(source):
    """Keep shared correctness utilities and one independent search policy."""
    module = ast.parse(source)
    lines = source.splitlines(keepends=True)
    result = {}
    for route, target in ROUTES.items():
        chunks = []
        for node in module.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "find_path" or (node.name in ROUTES.values() and node.name != target):
                    continue
            chunks.append("".join(lines[node.lineno - 1:node.end_lineno]))
        entry = ("def find_path(inputs, output, sizes, seed=0):\n"
                 f"    return {target}(inputs, output, sizes, seed=seed)\n")
        result[route] = ("# EVOLVE-BLOCK-START\n" + "\n\n".join(chunks)
                         + "\n\n" + entry + "# EVOLVE-BLOCK-END\n")
        ast.parse(result[route])
    return result


if __name__ == "__main__":
    print(json.dumps(export(Path(__file__).with_name("heuristics.py").read_text(encoding="utf-8")),
                     sort_keys=True))
