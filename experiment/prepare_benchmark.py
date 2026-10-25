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


def build_formal_sets():
    final = [circuit(qubits, depth, seed)
             for qubits in (6, 7, 8) for depth in (2, 3)
             for seed in (151, 152)]
    transfer = [lattice(rows, cols, seed)
                for rows, cols in ((3, 5), (4, 5), (5, 5))
                for seed in (161, 162)]
    return {"final_v3.json": final, "transfer_v3.json": transfer}


def main():
    data = ROOT / "data"
    data.mkdir(exist_ok=True)
    v2_sets = build_sets()
    v3_sets = build_formal_sets()
    all_sets = {**v2_sets, **v3_sets}
    manifest = {}
    for name, cases in all_sets.items():
        encoded = (json.dumps(cases, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        target = data / name
        if target.exists() and target.read_bytes() != encoded:
            raise RuntimeError(f"frozen benchmark differs: {target}")
        target.write_bytes(encoded)
        manifest[name] = {"cases": len(cases), "sha256": hashlib.sha256(encoded).hexdigest()}
    for version, sets in (("v2", v2_sets), ("v3", v3_sets)):
        version_manifest = {name: manifest[name] for name in sets}
        target = data / f"manifest_{version}.json"
        encoded = (json.dumps(version_manifest, indent=2) + "\n").encode()
        if target.exists() and target.read_bytes() != encoded:
            raise RuntimeError(f"frozen benchmark manifest differs: {target}")
        target.write_bytes(encoded)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
