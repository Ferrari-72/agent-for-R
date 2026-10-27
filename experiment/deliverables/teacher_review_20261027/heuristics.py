"""Editable path-search prototypes; standard library only, no solver wrappers.

The three search policies are deliberately separate. Shared helpers implement
original-leaf identity, hyperedge boundaries and dynamic-position path encoding.
Work limits are engineering defaults, not measured performance recommendations.
"""
from __future__ import annotations

import math
import random

MAX_TENSORS = 256
MAX_CACHED_GROUPS = 20000


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low}, {high}]")
    return value


class Problem:
    """Represent original leaves and labels by separate integer bit masks."""

    def __init__(self, inputs, output, sizes):
        terms = tuple(tuple(term) for term in inputs)
        output = tuple(output)
        _integer(len(terms), "tensor count", 2, MAX_TENSORS)
        if any(any(type(x) is not str for x in term) or len(set(term)) != len(term)
               for term in terms):
            raise ValueError("inputs require unique string labels; traces unsupported")
        if any(type(x) is not str for x in output) or len(set(output)) != len(output):
            raise ValueError("output requires unique string labels")
        labels = sorted(set().union(*map(set, terms)))
        if set(sizes) != set(labels) or not set(output) <= set(labels):
            raise ValueError("sizes and output must match input labels")
        for value in sizes.values():
            _integer(value, "dimension", 1, 2**64 - 1)
        self.n = len(terms)
        self.full = (1 << self.n) - 1
        self.dimensions = tuple(sizes[x] for x in labels)
        index = {label: i for i, label in enumerate(labels)}
        self.inputs = tuple(sum(1 << index[x] for x in term) for term in terms)
        self.output = sum(1 << index[x] for x in output)
        self.incidence = tuple(sum(1 << leaf for leaf, term in enumerate(terms) if x in term)
                               for x in labels)
        self.weights = tuple(math.log2(d) for d in self.dimensions)
        # cotengra 0.8.3 excludes single-input reductions from binary-tree cost.
        # Keep raw input sizes for the peak, but use effective boundary legs.
        self._legs = {}
        self._volumes = {0: 1}
        self.input_peak = max(self.volume(term) for term in self.inputs)

    def volume(self, labels):
        cached = self._volumes.get(labels)
        if cached is not None:
            return cached
        value = 1
        todo = labels
        while todo:
            bit = todo & -todo
            value *= self.dimensions[bit.bit_length() - 1]
            todo ^= bit
        if len(self._volumes) < MAX_CACHED_GROUPS:
            self._volumes[labels] = value
        return value

    def legs(self, group):
        cached = self._legs.get(group)
        if cached is not None:
            return cached
        # Effective legs retain a label iff needed by output or outside it.
        # Unary local sums are excluded from cotengra's binary-tree FLOPs.
        outside = self.full ^ group
        result = 0
        for i, incidence in enumerate(self.incidence):
            if incidence & group and (incidence & outside or self.output & (1 << i)):
                result |= 1 << i
        if len(self._legs) < MAX_CACHED_GROUPS:
            self._legs[group] = result
        return result

    def join(self, left, right):
        return (self.volume(self.legs(left) | self.legs(right)),
                self.volume(self.legs(left | right)))

    def tree_stats(self, tree):
        def visit(node):
            if type(node) is int:
                return 1 << node, 0, self.volume(self.inputs[node])
            left, a, pa = visit(node[0])
            right, b, pb = visit(node[1])
            cost, size = self.join(left, right)
            return left | right, a + b + cost, max(pa, pb, size)
        group, cost, peak = visit(tree)
        if group != self.full:
            raise ValueError("tree must cover every original input")
        return cost, peak


def tree_to_path(tree, n):
    """Postorder original-leaf tree -> current operand positions, append result."""
    active = [1 << i for i in range(n)]
    path = []
    seen = set()

    def visit(node):
        if type(node) is int:
            if not 0 <= node < n or node in seen:
                raise ValueError("invalid or repeated original leaf")
            seen.add(node)
            return 1 << node
        if type(node) is not tuple or len(node) != 2:
            raise ValueError("binary tree required")
        left, right = visit(node[0]), visit(node[1])
        i, j = active.index(left), active.index(right)
        path.append((min(i, j), max(i, j)))
        for index in sorted((i, j), reverse=True):
            active.pop(index)
        active.append(left | right)
        return left | right

    visit(tree)
    if len(seen) != n or len(path) != n - 1:
        raise ValueError("incomplete tree")
    return path


def _balanced(leaves):
    if len(leaves) == 1:
        return leaves[0]
    midpoint = len(leaves) // 2
    return _balanced(leaves[:midpoint]), _balanced(leaves[midpoint:])


def _rank(cost, peak, peak_limit):
    return (max(0, peak - peak_limit) if peak_limit is not None else 0, cost, peak)


def _peak_limit(value):
    if value is not None:
        _integer(value, "peak_limit", 1, 2**63 - 1)
    return value


def recursive_hypergraph_partition(inputs, output, sizes, *, seed=0, cutoff=4,
                                    refinement_sweeps=4, partition_trials=2,
                                    peak_limit=None):
    """Balanced dimension-weighted hyperedge cuts; exact tiny-subtree search.

    Each hyperedge contributes its weight once to a cut, regardless of arity.
    This is a small editable partition heuristic, not a KaHyPar implementation.
    """
    problem = Problem(inputs, output, sizes)
    _integer(seed, "seed", 0, 2**64 - 1)
    _integer(cutoff, "cutoff", 2, 6)
    _integer(refinement_sweeps, "refinement_sweeps", 0, 16)
    _integer(partition_trials, "partition_trials", 1, 8)
    peak_limit = _peak_limit(peak_limit)
    rng = random.Random(seed)
    exact = {}

    def small(group):
        if group in exact:
            return exact[group]
        if group.bit_count() == 1:
            answer = [(group.bit_length() - 1, 0,
                       problem.volume(problem.inputs[group.bit_length() - 1]))]
        else:
            first = group & -group
            answer = []
            left = (group - 1) & group
            while left:
                right = group ^ left
                if right and left & first:
                    cost, size = problem.join(left, right)
                    for a, ca, pa in small(left):
                        for b, cb, pb in small(right):
                            candidate = ((a, b), ca + cb + cost, max(pa, pb, size))
                            if any(old[1] <= candidate[1] and old[2] <= candidate[2]
                                   for old in answer):
                                continue
                            answer[:] = [old for old in answer
                                         if not (candidate[1] <= old[1] and candidate[2] <= old[2])]
                            answer.append(candidate)
                left = (left - 1) & group
        exact[group] = answer
        return answer

    def recurse(group):
        if group.bit_count() <= cutoff:
            return min(small(group), key=lambda item: _rank(*item[1:], peak_limit))[0]
        leaves = [i for i in range(problem.n) if group & (1 << i)]
        minimum = max(1, len(leaves) // 4)

        def objective(left):
            right = group ^ left
            cut = sum(weight for incidence, weight in zip(problem.incidence, problem.weights)
                      if incidence & left and incidence & right)
            return cut + abs(left.bit_count() - right.bit_count()) / len(leaves)

        best = None
        for trial_index in range(partition_trials):
            order = leaves.copy()
            rng.shuffle(order)
            if trial_index == 0:
                # A connected traversal avoids starting every cut as scattered
                # random islands. The remaining trials retain random starts.
                pending = set(leaves)
                traversal = []
                for start in order:
                    if start not in pending:
                        continue
                    queue = [start]
                    pending.remove(start)
                    for node in queue:
                        traversal.append(node)
                        neighbors = 0
                        for incidence in problem.incidence:
                            if incidence & (1 << node):
                                neighbors |= incidence & group
                        for neighbor in order:
                            if neighbor in pending and neighbors & (1 << neighbor):
                                pending.remove(neighbor)
                                queue.append(neighbor)
                order = traversal
            left = sum(1 << i for i in order[:len(leaves) // 2])
            score = objective(left)
            for _ in range(refinement_sweeps):
                rng.shuffle(order)
                changed = False
                for node in order:
                    proposed = left ^ (1 << node)
                    if not minimum <= proposed.bit_count() <= len(leaves) - minimum:
                        continue
                    trial = objective(proposed)
                    if trial < score:
                        left, score, changed = proposed, trial, True
                if not changed:
                    break
            # Normalize side identity so ties are deterministic.
            left = min(left, group ^ left)
            candidate = (objective(left), left)
            if best is None or candidate < best:
                best = candidate
        left = best[1]
        return recurse(left), recurse(group ^ left)

    return tree_to_path(recurse(problem.full), problem.n)


def tree_search_annealing(inputs, output, sizes, *, seed=0, steps=128,
                          temperature=0.5, peak_limit=None):
    """Seeded binary reassociation rotations, log-cost acceptance, best retained."""
    problem = Problem(inputs, output, sizes)
    _integer(seed, "seed", 0, 2**64 - 1)
    _integer(steps, "steps", 0, 4096)
    if type(temperature) not in (int, float) or not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("temperature must be positive and finite")
    peak_limit = _peak_limit(peak_limit)
    rng = random.Random(seed)
    current = best = _balanced(tuple(range(problem.n)))
    current_stats = best_stats = problem.tree_stats(current)

    def energy(stats):
        cost, peak = stats
        violation = max(0.0, math.log(peak) - math.log(peak_limit)) if peak_limit else 0.0
        return math.log(cost + 1) + 8.0 * violation

    for step in range(steps):
        eligible = []

        def collect(node, address=()):
            if type(node) is int:
                return
            if type(node[0]) is tuple or type(node[1]) is tuple:
                eligible.append((address, node))
            collect(node[0], address + (0,))
            collect(node[1], address + (1,))

        collect(current)
        if not eligible:
            break
        address, node = rng.choice(eligible)
        left, right = node
        proposals = []
        if type(left) is tuple:
            a, b = left
            proposals.extend(((a, (b, right)), (b, (a, right))))
        if type(right) is tuple:
            a, b = right
            proposals.extend((((left, a), b), ((left, b), a)))
        replacement = rng.choice(proposals)

        def replace(root, route):
            if not route:
                return replacement
            side = route[0]
            children = list(root)
            children[side] = replace(children[side], route[1:])
            return tuple(children)

        candidate = replace(current, address)
        stats = problem.tree_stats(candidate)
        if _rank(*stats, peak_limit) < _rank(*best_stats, peak_limit):
            best, best_stats = candidate, stats
        delta = energy(stats) - energy(current_stats)
        temp = temperature * (0.02 ** (step / max(1, steps - 1)))
        if delta <= 0 or math.log(max(rng.random(), 1e-300)) < -delta / temp:
            current, current_stats = candidate, stats
    return tree_to_path(best, problem.n)


def budgeted_beam_search(inputs, output, sizes, *, seed=0, width=8,
                         max_expansions=256, peak_limit=None, diagnostics=None):
    """Beam over exact leaf partitions with bounded expansion and full incumbent.

    Always retain a complete balanced-tree fallback. A truncated state is never
    returned. States with equal partitions retain nondominated (cost, peak)
    histories before beam pruning. This pruning gives no optimality guarantee.
    """
    problem = Problem(inputs, output, sizes)
    _integer(seed, "seed", 0, 2**64 - 1)
    _integer(width, "width", 1, 64)
    _integer(max_expansions, "max_expansions", 0, 100000)
    peak_limit = _peak_limit(peak_limit)
    incumbent = _balanced(tuple(range(problem.n)))
    incumbent_stats = problem.tree_stats(incumbent)
    # State: canonical partition, matching trees, accumulated cost, historical peak.
    beam = [(tuple(1 << i for i in range(problem.n)), tuple(range(problem.n)),
             0, problem.input_peak)]
    expansions = 0
    completed = 0
    incumbent_replaced = False
    while beam and expansions < max_expansions:
        pool = {}
        # Spread work over remaining depths so the first quadratic pair layer
        # cannot consume every expansion before a searched tree is completed.
        remaining_depth = len(beam[0][0]) - 1
        layer_stop = expansions + max(1, (max_expansions - expansions) // remaining_depth)
        for partition, trees, total, peak in beam:
            for i in range(len(partition)):
                for j in range(i + 1, len(partition)):
                    if expansions >= layer_stop:
                        break
                    expansions += 1
                    cost, size = problem.join(partition[i], partition[j])
                    merged = partition[i] | partition[j]
                    joined_tree = (trees[i], trees[j])
                    items = [(part, tree) for k, (part, tree) in enumerate(zip(partition, trees))
                             if k not in (i, j)] + [(merged, joined_tree)]
                    items.sort(key=lambda item: item[0])
                    parts, forest = tuple(x[0] for x in items), tuple(x[1] for x in items)
                    state = (parts, forest, total + cost, max(peak, size))
                    if len(parts) == 1:
                        completed += 1
                        if _rank(*state[2:], peak_limit) < _rank(*incumbent_stats, peak_limit):
                            incumbent, incumbent_stats = forest[0], state[2:]
                            incumbent_replaced = True
                        continue
                    frontier = pool.setdefault(parts, [])
                    if any(old[2] <= state[2] and old[3] <= state[3] for old in frontier):
                        continue
                    frontier[:] = [old for old in frontier
                                   if not (state[2] <= old[2] and state[3] <= old[3])]
                    frontier.append(state)
                if expansions >= layer_stop:
                    break
            if expansions >= layer_stop:
                break
        candidates = [state for frontier in pool.values() for state in frontier]
        # Remaining merges each cost >= 1. This weak bound is not used to claim
        # global optimality; finite width and budget still discard candidates.
        beam = sorted(candidates, key=lambda s: (
            max(0, s[3] - peak_limit) if peak_limit else 0,
            s[2] + len(s[0]) - 1, s[3], s[0], repr(s[1])))[:width]
    if diagnostics is not None:
        diagnostics.update(expansions=expansions, complete_states=completed,
                           used_initial_incumbent=not incumbent_replaced,
                           cost=incumbent_stats[0], peak_elements=incumbent_stats[1])
    return tree_to_path(incumbent, problem.n)


def find_path(inputs, output, sizes, seed=0):
    """Compatibility entrypoint; each route has a separate wrapper in this pack."""
    return recursive_hypergraph_partition(inputs, output, sizes, seed=seed)
