"""Reuse the audited public engineering topology helper without policy changes."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("engineering_topology", Path(__file__).with_name("engineering_topology.py"))
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
circuit = helper.circuit
lattice = helper.lattice
validate = helper.validate
VERSION = helper.VERSION
