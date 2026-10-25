"""Exercise isolation boundaries against the built candidate image."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

from tnlab.execution import ROOT, ResourceLimitError, run_candidate

CASE = {"name": "isolation", "inputs": [["a", "b"], ["b", "c"]],
        "output": ["a", "c"], "sizes": {"a": 2, "b": 2, "c": 2}}


def main():
    if os.environ.get("TN_EXECUTION_MODE") != "container":
        raise RuntimeError("set TN_EXECUTION_MODE=container")
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        file = Path(directory) / "candidate.py"
        file.write_text('''def find_path(inputs, output, sizes, seed=0):
    import json, os, socket
    from pathlib import Path
    try:
        Path('/probe-write').write_text('x')
        writable = True
    except OSError:
        writable = False
    try:
        socket.create_connection(('1.1.1.1', 443), timeout=1)
        network = True
    except OSError:
        network = False
    print(json.dumps({'final_v3_visible': Path('/data/final_v3.json').exists(),
                      'key_visible': 'OPENAI_API_KEY' in os.environ,
                      'root_writable': writable, 'network': network}))
    return [(0, 1)]
''', encoding="utf-8")
        answer, _ = run_candidate(file, CASE)
        checks = json.loads(answer["stdout"])
        assert checks == {"final_v3_visible": False, "key_visible": False,
                          "root_writable": False, "network": False}, checks
        file.write_text('''def find_path(inputs, output, sizes, seed=0):
    import time
    time.sleep(30)
    return [(0, 1)]
''', encoding="utf-8")
        try:
            run_candidate(file, CASE, timeout=1)
        except subprocess.TimeoutExpired:
            pass
        else:
            raise AssertionError("time limit did not stop the candidate")
        file.write_text('''def find_path(inputs, output, sizes, seed=0):
    data = bytearray(600 * 1024 * 1024)
    for index in range(0, len(data), 4096):
        data[index] = 1
    return [(0, 1)]
''', encoding="utf-8")
        try:
            run_candidate(file, CASE)
        except ResourceLimitError:
            pass
        else:
            raise AssertionError("memory limit did not stop the candidate")
        file.write_text('''def find_path(inputs, output, sizes, seed=0):
    import __main__, time
    __main__._invoke.__defaults__ = (lambda: 0,)
    time.sleep(0.3)
    return [(0, 1)]
''', encoding="utf-8")
        answer, _ = run_candidate(file, CASE)
        if answer["search_seconds"] < 0.3:
            raise AssertionError("candidate changed the trusted search timer")
    print("container isolation, timeout, memory limit, and trusted timer verified")


if __name__ == "__main__":
    main()
