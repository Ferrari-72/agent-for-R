"""Generate the versioned circuit benchmark before running any candidates."""

import hashlib
import json
from pathlib import Path

from tnlab.instances import circuit, lattice

ROOT = Path(__file__).resolve().parent


def build_sets():
    develop = [circuit(qubits, depth, seed)
               for qubits in (4, 5) for depth in (1, 2, 3)
               for seed in (31, 32)]
    final = [circuit(qubits, depth, seed)
             for qubits in (6, 7) for depth in (2, 3)
             for seed in (51, 52)]
    transfer = [lattice(rows, cols, seed)
                for rows, cols in ((3, 3), (3, 4), (4, 4))
                for seed in (61, 62)]
    return {"develop_v2.json": develop, "final_v2.json": final,
            "transfer_v2.json": transfer}


def main():
    data = ROOT / "data"
    data.mkdir(exist_ok=True)
    manifest = {}
    for name, cases in build_sets().items():
        encoded = (json.dumps(cases, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        target = data / name
        if target.exists() and target.read_bytes() != encoded:
            raise RuntimeError(f"frozen benchmark differs: {target}")
        target.write_bytes(encoded)
        manifest[name] = {"cases": len(cases), "sha256": hashlib.sha256(encoded).hexdigest()}
    target = data / "manifest_v2.json"
    encoded = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    if target.exists() and target.read_bytes() != encoded:
        raise RuntimeError("frozen benchmark manifest differs")
    target.write_bytes(encoded)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
