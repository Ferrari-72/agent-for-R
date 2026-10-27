"""Finite public engineering fixtures; no study split, value tensors or dataset IO.

This independently testable generator is not connected to research admission or
restricted materialization. Domain-separated SHA256 draws pin the topology order.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json

VERSION = "tensor-topology-pilot-v1"


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low}, {high}]")


def _keep(family, shape, attempt, ordinal):
    payload = json.dumps([VERSION, family, shape, attempt, ordinal],
                         ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).digest()[0] % 4 < 3


def circuit(qubits, depth, attempt):
    """Alternating disjoint adjacent gates; omitted gates add no identity tensor."""
    _integer(qubits, "qubits", 2, 20)
    _integer(depth, "depth", 1, 12)
    _integer(attempt, "attempt", 0, 999)
    wires = [f"wire_{q}" for q in range(qubits)]
    inputs = [[wire] for wire in wires]
    placements = []
    ordinal = 0
    for layer in range(depth):
        for q in range(layer % 2, qubits - 1, 2):
            keep = _keep("circuit", [qubits, depth], attempt, ordinal)
            ordinal += 1
            if not keep:
                continue
            left, right = f"gate_{layer}_{q}_left", f"gate_{layer}_{q}_right"
            inputs.append([wires[q], wires[q + 1], left, right])
            wires[q], wires[q + 1] = left, right
            placements.append([layer, q, q + 1])
    if not placements:
        return None, {"rejection": "no_two_qubit_gates", "eligible_gates": ordinal}
    labels = {x for term in inputs for x in term}
    case = {"inputs": inputs, "output": wires, "sizes": {x: 2 for x in sorted(labels)}}
    return case, {"eligible_gates": ordinal, "retained_gates": placements,
                  "qubits": qubits, "depth": depth}


def lattice(rows, cols, attempt):
    """Row-major vertices; at each vertex draw its right then downward edge."""
    _integer(rows, "rows", 2, 5)
    _integer(cols, "cols", 2, 5)
    _integer(attempt, "attempt", 0, 999)
    count = rows * cols
    edges = []
    ordinal = 0
    for r in range(rows):
        for c in range(cols):
            for nr, nc in ((r, c + 1), (r + 1, c)):
                if nr >= rows or nc >= cols:
                    continue
                if _keep("lattice", [rows, cols], attempt, ordinal):
                    edges.append((r * cols + c, nr * cols + nc))
                ordinal += 1
    adjacency = [set() for _ in range(count)]
    for a, b in edges:
        adjacency[a].add(b)
        adjacency[b].add(a)
    reached = {0}
    queue = [0]
    for node in queue:
        for neighbor in sorted(adjacency[node] - reached):
            reached.add(neighbor)
            queue.append(neighbor)
    if len(reached) != count:
        return None, {"rejection": "disconnected", "eligible_edges": ordinal,
                      "retained_edges": [list(edge) for edge in edges]}
    output = [f"physical_{i}" for i in range(count)]
    inputs = [[x] for x in output]
    for i, (a, b) in enumerate(edges):
        inputs[a].append(f"bond_{i}")
        inputs[b].append(f"bond_{i}")
    labels = {x for term in inputs for x in term}
    case = {"inputs": inputs, "output": output, "sizes": {x: 2 for x in sorted(labels)}}
    return case, {"eligible_edges": ordinal, "retained_edges": [list(edge) for edge in edges],
                  "rows": rows, "cols": cols}


def validate(case, family, shape, metadata):
    """Check independent incidence/arity identities rather than solver scores."""
    terms, output, sizes = case["inputs"], case["output"], case["sizes"]
    counts = Counter(x for term in terms for x in term)
    assert set(counts) == set(sizes) and set(output) <= set(counts)
    assert len(output) == len(set(output))
    assert all(len(term) == len(set(term)) for term in terms)
    assert all(type(d) is int and d == 2 for d in sizes.values())
    assert all(count == (1 if x in output else 2) for x, count in counts.items())
    if family == "circuit":
        q, depth = shape
        assert len(output) == q
        assert len(terms) == q + len(metadata["retained_gates"])
        assert all(len(term) == 1 for term in terms[:q])
        assert all(len(term) == 4 for term in terms[q:])
        seen = set()
        wires = [term[0] for term in terms[:q]]
        assert len(set(wires)) == q
        produced = set(wires)
        assert metadata["retained_gates"] == sorted(metadata["retained_gates"])
        for term, (layer, a, b) in zip(terms[q:], metadata["retained_gates"]):
            assert 0 <= layer < depth and b == a + 1 and 0 <= a < b < q
            assert a % 2 == layer % 2
            assert (layer, a) not in seen and (layer, b) not in seen
            seen.update(((layer, a), (layer, b)))
            assert term[:2] == [wires[a], wires[b]]
            assert len(set(term[2:]) - produced) == 2
            produced.update(term[2:])
            wires[a], wires[b] = term[2:]
        assert output == wires
        assert len(sizes) == q + 2 * len(metadata["retained_gates"])
        assert metadata["eligible_gates"] == sum(len(range(layer % 2, q - 1, 2))
                                                   for layer in range(depth))
    elif family == "lattice":
        rows, cols = shape
        assert len(output) == len(terms) == rows * cols
        assert all(output[i] in term for i, term in enumerate(terms))
        assert all(1 < len(term) <= 5 for term in terms)
        assert len(set(map(tuple, metadata["retained_edges"]))) == len(metadata["retained_edges"])
        assert len(sizes) == len(terms) + len(metadata["retained_edges"])
        assert metadata["eligible_edges"] == rows * (cols - 1) + (rows - 1) * cols
        adjacency = [set() for _ in terms]
        for a, b in metadata["retained_edges"]:
            assert 0 <= a < b < len(terms)
            assert (b == a + 1 and a // cols == b // cols) or b == a + cols
            shared = set(terms[a]) & set(terms[b])
            assert len(shared) == 1 and not shared.intersection(output)
            adjacency[a].add(b)
            adjacency[b].add(a)
        reached, queue = {0}, [0]
        for node in queue:
            for neighbor in sorted(adjacency[node] - reached):
                reached.add(neighbor)
                queue.append(neighbor)
        assert len(reached) == len(terms)
    else:
        raise ValueError("unsupported engineering family")
    return {"tensors": len(terms), "indices": len(sizes), "outputs": len(output),
            "max_input_elements": max(2 ** len(term) for term in terms)}
