"""Atomic, process-safe accounting for outbound model HTTP requests."""

import os
import sqlite3
from contextlib import closing
from pathlib import Path


def initialize_request_budget(filename, research_id, limit=100):
    """Create a new ledger or verify its immutable study identity."""
    path = Path(filename)
    if path.exists():
        with closing(sqlite3.connect(path, timeout=30)) as database:
            tables = {row[0] for row in database.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "budget_meta" not in tables:
                raise RuntimeError("existing request ledger has no study metadata")
            metadata = dict(database.execute(
                "SELECT key, value FROM budget_meta").fetchall())
            if metadata.get("research_id") != research_id:
                raise RuntimeError("request ledger belongs to another research ID")
            if int(metadata.get("limit", "-1")) != int(limit):
                raise RuntimeError("request ledger limit differs from the registered budget")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=30, isolation_level=None)) as database:
        database.execute("CREATE TABLE requests (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, "
                         "created_at TEXT DEFAULT CURRENT_TIMESTAMP, run_id TEXT)")
        database.execute("CREATE TABLE budget_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        database.executemany("INSERT INTO budget_meta (key, value) VALUES (?, ?)", [
            ("research_id", str(research_id)), ("limit", str(int(limit))),
        ])
        database.commit()


def reserve_request(kind: str, run_id=None) -> None:
    """Reserve one request before sending it; failed attempts still count."""
    filename = os.environ.get("OPENEVOLVE_REQUEST_BUDGET_DB")
    if not filename:
        if os.environ.get("TN_EXECUTION_MODE") == "container":
            raise RuntimeError("formal model requests require a persistent budget database")
        return
    path = Path(filename)
    if os.environ.get("TN_EXECUTION_MODE") == "container" and not path.is_file():
        raise RuntimeError("formal model requests require an existing persistent budget database")
    run_id = run_id or os.environ.get("TN_RUN_ID")
    if os.environ.get("TN_EXECUTION_MODE") == "container" and not run_id:
        raise RuntimeError("formal model requests require TN_RUN_ID")
    environment_limit = os.environ.get("OPENEVOLVE_REQUEST_LIMIT")
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=30, isolation_level=None)) as database:
        tables = {row[0] for row in database.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "budget_meta" not in tables:
            raise RuntimeError("request ledger has no immutable budget metadata")
        metadata = dict(database.execute(
            "SELECT key, value FROM budget_meta").fetchall())
        try:
            limit = int(metadata["limit"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("request ledger has an invalid budget limit") from exc
        if environment_limit is not None and int(environment_limit) != limit:
            raise RuntimeError("environment request limit differs from ledger limit")
        columns = {row[1] for row in database.execute("PRAGMA table_info(requests)")}
        if "requests" not in tables:
            raise RuntimeError("request ledger has no requests table")
        if "run_id" not in columns:
            database.execute("ALTER TABLE requests ADD COLUMN run_id TEXT")
        database.execute("BEGIN IMMEDIATE")
        used = database.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
        if used >= limit:
            database.rollback()
            raise RuntimeError(f"model HTTP request budget exhausted ({used}/{limit})")
        database.execute(
            "INSERT INTO requests (kind, run_id) VALUES (?, ?)", (kind, run_id)
        )
        database.commit()


def request_last_id(filename=None):
    """Read the last reserved request ID without changing the budget."""
    filename = filename or os.environ.get("OPENEVOLVE_REQUEST_BUDGET_DB")
    if not filename or not Path(filename).is_file():
        return 0
    with closing(sqlite3.connect(filename, timeout=30)) as database:
        exists = database.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='requests'"
        ).fetchone()
        if not exists:
            return 0
        return database.execute("SELECT COALESCE(MAX(id), 0) FROM requests").fetchone()[0]


def request_usage(filename=None, after_id=0, run_id=None):
    """Read durable request counts by ID range and optionally by run ID."""
    filename = filename or os.environ.get("OPENEVOLVE_REQUEST_BUDGET_DB")
    if not filename or not Path(filename).is_file():
        return {"total": 0, "by_kind": {}}
    with closing(sqlite3.connect(filename, timeout=30)) as database:
        columns = {row[1] for row in database.execute("PRAGMA table_info(requests)")}
        if "run_id" not in columns:
            if run_id is not None:
                raise RuntimeError("request database has no run_id column")
            rows = database.execute(
                "SELECT kind, COUNT(*) FROM requests WHERE id > ? GROUP BY kind ORDER BY kind",
                (after_id,),
            ).fetchall()
        elif run_id is not None:
            rows = database.execute(
                "SELECT kind, COUNT(*) FROM requests WHERE run_id = ? AND id > ? "
                "GROUP BY kind ORDER BY kind", (run_id, after_id)
            ).fetchall()
        else:
            rows = database.execute(
                "SELECT kind, COUNT(*) FROM requests WHERE id > ? GROUP BY kind ORDER BY kind",
                (after_id,),
            ).fetchall()
    counts = dict(rows)
    return {"total": sum(counts.values()), "by_kind": counts}
