"""Generate and load immutable benchmark instances."""

import json
from pathlib import Path

import cotengra as ctg
import quimb.tensor as qtn

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def normalize(name, family, inputs, output, sizes, source):
    """Use one JSON representation for every source library."""
    inputs = [list(x) for x in inputs]
    output = list(output)
    sizes = {str(k): int(v) for k, v in sizes.items()}
    if len(inputs) < 2 or len(set(output)) != len(output):
        raise ValueError("invalid tensor network")
    labels = [label for tensor in inputs for label in tensor]
    if any(len(set(tensor)) != len(tensor) for tensor in inputs):
        raise ValueError("traces inside one tensor are unsupported")
    if set(labels) != set(sizes) or not set(output) <= set(labels):
        raise ValueError("index sizes or output do not match inputs")
    if any(size < 1 for size in sizes.values()):
        raise ValueError("all index sizes must be positive")
    return {"name": name, "family": family, "inputs": inputs,
            "output": output, "sizes": sizes, "source": source}


def lattice(rows, cols, seed):
    equation = ctg.utils.lattice_equation([rows, cols], seed=seed)
    inputs, output, _, sizes = equation
    return normalize(f"lattice_{rows}x{cols}_s{seed}", "lattice", inputs,
                     output, sizes, {"generator": "cotengra.utils.lattice_equation",
                                     "rows": rows, "cols": cols, "seed": seed})


def circuit(qubits, depth, seed):
    circ = qtn.circ_ansatz_1D_brickwork(qubits, depth, seed=seed)
    inputs, output, sizes = circ.psi.get_inputs_output_size_dict()
    return normalize(f"circuit_{qubits}q_d{depth}_s{seed}", "circuit", inputs,
                     output, sizes, {"generator": "quimb.tensor.circ_ansatz_1D_brickwork",
                                     "qubits": qubits, "depth": depth, "seed": seed,
                                     "quantity": "full_state", "gate_contract": "library_default"})


def write_fixed_sets():
    DATA.mkdir(exist_ok=True)
    sets = {
        "develop.json": [lattice(2, 2, 11), lattice(2, 3, 12),
                         circuit(3, 1, 13), circuit(3, 2, 14)],
        "holdout.json": [lattice(3, 3, 21), circuit(4, 2, 22)],
    }
    for filename, cases in sets.items():
        (DATA / filename).write_text(
            json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return sets


def load_cases(name="develop.json"):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


if __name__ == "__main__":
    for filename, cases in write_fixed_sets().items():
        print(filename, [(case["name"], len(case["inputs"])) for case in cases])
