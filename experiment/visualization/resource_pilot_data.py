"""Pure result validation and descriptive summaries; no solver or renderer imports."""
from __future__ import annotations

import math
from statistics import median

METRICS = ("cost", "algorithm_wall_seconds", "peak_elements")


def number(row, key):
    value = row.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a finite nonnegative number or null")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{key} must be a finite nonnegative number or null")
    return value


def validate(report):
    if report.get("schema_version") != 1 or isinstance(report.get("schema_version"), bool):
        raise ValueError("resource-pilot schema_version 1 is required")
    rows = report.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("report must contain a non-empty rows list")
    identities = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("each row must be an object")
        for key in ("solver", "case_id", "status"):
            if not isinstance(row.get(key), str) or not row[key]:
                raise ValueError(f"each row requires a non-empty {key}")
        repeat = row.get("repeat")
        if isinstance(repeat, bool) or not isinstance(repeat, int) or repeat < 0:
            raise ValueError("repeat must be a nonnegative integer")
        identity = row["case_id"], row["solver"], repeat
        if identity in identities:
            raise ValueError("duplicate case/solver/repeat row")
        identities.add(identity)
        for metric in (*METRICS, "process_wall_seconds", "max_rss_kib"):
            number(row, metric)
        if successful(row):
            if any(number(row, metric) is None for metric in METRICS):
                raise ValueError("successful rows require cost, peak and algorithm time")
            if row["cost"] <= 0 or row["peak_elements"] <= 0:
                raise ValueError("successful costs and peaks must be positive")
    return rows


def successful(row):
    return row.get("status") in ("ok", "success")


def summarize(rows):
    groups = {}
    for row in rows:
        solver = row.get("solver")
        if not isinstance(solver, str) or not solver:
            raise ValueError("each row must have a non-empty solver")
        bucket = groups.setdefault(solver, {"rows": 0, "successes": 0,
                                           **{key: [] for key in METRICS}})
        bucket["rows"] += 1
        if not successful(row):
            continue
        bucket["successes"] += 1
        for key in METRICS:
            value = number(row, key)
            if value is not None:
                bucket[key].append(value)
    result = {}
    for solver, bucket in groups.items():
        result[solver] = {"rows": bucket["rows"], "successes": bucket["successes"]}
        for key in METRICS:
            result[solver][key + "_median"] = median(bucket[key]) if bucket[key] else None
    return result
