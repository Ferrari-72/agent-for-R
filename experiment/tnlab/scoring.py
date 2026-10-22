"""Validate a candidate path, then score it with cotengra."""

from dataclasses import dataclass
from math import prod

import cotengra as ctg


@dataclass(frozen=True)
class Score:
    cost: int
    peak_elements: int


def validate_path(case, path):
    """Reject malformed or incomplete dynamic-position pairwise paths."""
    if not isinstance(path, (tuple, list)) or len(path) != len(case["inputs"]) - 1:
        raise ValueError("path must have exactly n-1 steps")
    active = [frozenset((i,)) for i in range(len(case["inputs"]))]
    clean = []
    for step in path:
        if (not isinstance(step, (tuple, list)) or len(step) != 2
                or any(type(i) is not int for i in step)):
            raise ValueError("each step must be a pair of integer positions")
        left, right = step
        if left == right or min(step) < 0 or max(step) >= len(active):
            raise ValueError("step references an invalid or repeated tensor")
        merged = active[left] | active[right]
        for index in sorted(step, reverse=True):
            active.pop(index)
        active.append(merged)
        clean.append((left, right))
    if active != [frozenset(range(len(case["inputs"])))]:
        raise ValueError("path is incomplete")
    return tuple(clean)


def score_path(case, path):
    path = validate_path(case, path)
    tree = ctg.ContractionTree.from_path(
        case["inputs"], case["output"], case["sizes"],
        path=path, check=True, autocomplete=False,
    )
    peak = max(prod(case["sizes"][label] for label in tensor)
               for tensor in case["inputs"])
    peak = max(peak, int(tree.max_size()))
    return Score(cost=int(tree.contraction_cost()), peak_elements=peak)
