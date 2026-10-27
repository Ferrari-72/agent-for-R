"""Offline Linux smoke of existing patch guard and public candidate exports.

Only caller-pinned source files are loaded. No prompt rendering, provider, model,
research data, configuration or request ledger is used. Inert package namespaces
let the guard import the exact pure code_utils module without package startup.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
import types

HERE = Path(__file__).resolve().parent
SOURCE_NAMES = ("check_patches.py", "heuristics.py", "export_candidates.py",
                "prototype_validate.py", "render_candidate_prompts.py", "code_utils.py")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def load(name, filename=None):
    spec = importlib.util.spec_from_file_location(name, HERE / (filename or name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def contract():
    sys.path.insert(0, "/")
    for name in ("openevolve", "openevolve.utils"):
        namespace = types.ModuleType(name)
        namespace.__path__ = []
        sys.modules[name] = namespace
    pure = load("openevolve.utils.code_utils", "code_utils.py")
    sys.modules["openevolve.utils.code_utils"] = pure
    return load("render_candidate_prompts")


def block(search, replacement):
    return f"<<<<<<< SEARCH\n{search.rstrip()}\n=======\n{replacement.rstrip()}\n>>>>>>> REPLACE"


def interior(source):
    return source.split("# EVOLVE-BLOCK-START\n", 1)[1].rsplit("# EVOLVE-BLOCK-END", 1)[0].rstrip()


def workers(request):
    if request["mode"] == "candidate":
        namespace = {"__name__": "offline_candidate"}
        exec(compile(request["source"], "<patched-public-candidate>", "exec"), namespace)
        paths = []
        for case in request["cases"]:
            inputs = [frozenset(term) for term in case["inputs"]]
            output, sizes = frozenset(case["output"]), dict(case["sizes"])
            before = copy.deepcopy((inputs, output, sizes))
            paths.append(namespace["find_path"](inputs, output, sizes, seed=0))
            assert before == (inputs, output, sizes)
        return {"paths": paths}
    if request["mode"] == "score":
        import math
        import cotengra as ctg
        oracle = load("prototype_validate")
        scores = []
        for case, path in zip(request["cases"], request["paths"], strict=True):
            own = oracle.own_score(case, path)
            tree = ctg.ContractionTree.from_path(case["inputs"], case["output"], case["sizes"],
                                                path=path, check=True, autocomplete=False)
            trusted = (int(tree.contraction_cost()), max(int(tree.max_size()),
                       max(math.prod(case["sizes"][x] for x in term) for term in case["inputs"])))
            assert own == trusted
            scores.append({"cost": own[0], "peak_elements": own[1]})
        return {"scores": scores}
    raise ValueError("unsupported worker mode")


def main():
    guard = contract()
    exporter = load("export_candidates")
    oracle = load("prototype_validate")
    sources = exporter.export((HERE / "heuristics.py").read_text(encoding="utf-8"))
    cases = oracle.fixtures()
    checks, errors, calls, examples, rejected = [], [], [], [], []

    def check(name, action):
        try:
            checks.append({"name": name, "status": "passed", "detail": action()})
        except Exception as exc:
            checks.append({"name": name, "status": "failed"})
            errors.append({"name": name, "type": type(exc).__name__, "message": str(exc)[:2000]})

    def call(request):
        started = time.perf_counter()
        done = subprocess.run([sys.executable, "-I", "-B", str(HERE / "check_patches.py"), "--worker"],
                              input=json.dumps(request).encode(), capture_output=True, timeout=10)
        calls.append({"mode": request["mode"], "returncode": done.returncode,
                      "process_wall_seconds": time.perf_counter() - started})
        if done.returncode:
            raise AssertionError(done.stderr.decode(errors="replace")[:2000])
        return json.loads(done.stdout)

    local = {
        "partition": ("            return cut + abs(left.bit_count() - right.bit_count()) / len(leaves)",
                      "            return cut + 2 * abs(left.bit_count() - right.bit_count()) / len(leaves)"),
        "tree": ("        temp = temperature * (0.02 ** (step / max(1, steps - 1)))",
                 "        temp = temperature * (0.05 ** (step / max(1, steps - 1)))"),
        "beam": ("            s[2] + len(s[0]) - 1, s[3], s[0], repr(s[1])))[:width]",
                 "            s[2] + 2 * (len(s[0]) - 1), s[3], s[0], repr(s[1])))[:width]"),
    }
    routes = list(sources)
    sizes = {}
    for route, parent in sources.items():
        guard._validate_program(parent)
        sizes[route] = {"source_characters": len(parent), "source_utf8_bytes": len(parent.encode()),
                        "source_lines": len(parent.splitlines()), "source_sha256": digest(parent.encode())}
        target = exporter.ROUTES[route]
        node = next(n for n in ast.parse(parent).body if isinstance(n, ast.FunctionDef) and n.name == target)
        function = "\n".join(parent.splitlines()[node.lineno - 1:node.end_lineno])
        replacement = (f"def {target}(inputs, output, sizes, *, seed=0):\n"
                       "    problem = Problem(inputs, output, sizes)\n"
                       "    _integer(seed, 'seed', 0, 2**64 - 1)\n"
                       "    leaves = tuple(reversed(range(problem.n)))\n"
                       "    return tree_to_path(_balanced(leaves), problem.n)")
        next_route = routes[(routes.index(route) + 1) % len(routes)]
        patches = {"local_decision": block(*local[route]),
                   "replace_search_function": block(function, replacement),
                   "replace_entire_region": block(interior(parent), interior(sources[next_route]))}
        for kind, response in patches.items():
            def positive(route=route, parent=parent, kind=kind, response=response, next_route=next_route):
                child = guard.check_candidate_diff(parent, response)
                if kind == "replace_entire_region":
                    assert child == sources[next_route]
                first = call({"mode": "candidate", "source": child, "cases": cases})
                second = call({"mode": "candidate", "source": child, "cases": cases})
                assert first["paths"] == second["paths"], "fresh-process path mismatch"
                scored = call({"mode": "score", "cases": cases, "paths": first["paths"]})
                example = {"route": route, "kind": kind, "response": response,
                           "response_characters": len(response), "response_utf8_bytes": len(response.encode()),
                           "response_lines": len(response.splitlines()),
                           "response_sha256": digest(response.encode()), "child_sha256": digest(child.encode()),
                           "case_count": len(cases), "paths": first["paths"], "scores": scored["scores"]}
                examples.append(example)
                return {key: example[key] for key in ("response_characters", "response_utf8_bytes", "case_count")}
            check(route + "/" + kind, positive)

        old, new = local[route]
        valid = patches["local_decision"]
        entry = "def find_path(inputs, output, sizes, seed=0):"
        invalid = {
            "prose": "Here is the patch:\n" + valid,
            "fence": "```python\n" + valid + "\n```",
            "two_blocks": valid + "\n" + valid,
            "unmatched_search": block("not_in_parent_12345 = 0", "not_in_parent_12345 = 1"),
            "ambiguous_search": block("return", "yield"),
            "outside_region": block("# EVOLVE-BLOCK-START", "# changed marker"),
            "no_op": block(old, old),
            "signature": block(entry, "def find_path(inputs, output, sizes, seed=1):"),
            "syntax": block(old, "this is not valid python !"),
            "truncated": valid.removesuffix(">>>>>>> REPLACE"),
        }
        for kind, response in invalid.items():
            def negative(route=route, kind=kind, response=response, parent=parent):
                try:
                    guard.check_candidate_diff(parent, response)
                except (ValueError, SyntaxError) as exc:
                    rejected.append({"route": route, "kind": kind, "exception": type(exc).__name__,
                                     "message": str(exc)[:500]})
                    return {"exception": type(exc).__name__}
                raise AssertionError("invalid patch accepted")
            check(route + "/reject/" + kind, negative)

    report = {"schema_version": 1, "purpose": "public-offline-patch-compatibility",
              "status": "passed" if not errors else "failed", "checks": checks,
              "checks_passed": sum(x["status"] == "passed" for x in checks), "checks_total": len(checks),
              "errors": errors, "exports": sizes, "examples": examples, "rejections": rejected,
              "subprocesses": calls, "fixture_ids": [x["id"] for x in cases],
              "source_sha256": {name: digest((HERE / name).read_bytes()) for name in SOURCE_NAMES},
              "model_requests": 0, "tokenizer_measured": False, "formal_research_data_accessed": False,
              "limitations": ["Exercises exact guard functions, not the OpenEvolve worker/provider pipeline.",
                              "Inert package namespaces avoid executing provider-bearing package initializers.",
                              "Characters and UTF-8 bytes are not token counts; no 2048-token fit claim.",
                              "Function replacement is a protocol demonstration, not an improved heuristic.",
                              "Only existing public handwritten fixtures are executed; no formal research sample.",
                              "One shared resource-limited container is not an arbitrary-code security sandbox."]}
    print(json.dumps(report, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    if "--worker" in sys.argv:
        print(json.dumps(workers(json.load(sys.stdin)), sort_keys=True))
    else:
        raise SystemExit(main())
