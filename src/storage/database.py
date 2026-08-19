"""Database client abstraction for Cloudflare D1 (Pyodide compatible)."""

import logging
from typing import Any, List, Optional, Dict

logger = logging.getLogger("worker.storage.database")

class D1Database:
    """Wraps Cloudflare D1 database binding with safe async query helpers."""
    def __init__(self, d1_binding: Any = None):
        self.db = d1_binding

    @property
    def is_available(self) -> bool:
        """Returns True if D1 binding is attached and ready."""
        return self.db is not None

    async def execute(self, sql: str, *params) -> bool:
        """Executes an INSERT/UPDATE/DELETE query safely."""
        if not self.is_available:
            return False
        try:
            stmt = self.db.prepare(sql)
            if params:
                stmt = stmt.bind(*params)
            await stmt.run()
            return True
        except Exception as e:
            logger.error(f"D1 execute error: {e}")
            return False

    async def fetch_one(self, sql: str, *params) -> Optional[Dict[str, Any]]:
        """Executes a query and returns the first row as a Python dictionary, or None."""
        if not self.is_available:
            return None
        try:
            stmt = self.db.prepare(sql)
            if params:
                stmt = stmt.bind(*params)
            row = await stmt.first()
            if row is None:
                return None
            if hasattr(row, "to_py"):
                return dict(row.to_py())
            if isinstance(row, dict):
                return row
            return dict(row)
        except Exception as e:
            logger.error(f"D1 fetch_one error: {e}")
            return None

    async def fetch_all(self, sql: str, *params) -> List[Dict[str, Any]]:
        """Executes a query and returns all matching rows as Python dictionaries."""
        if not self.is_available:
            return []
        try:
            stmt = self.db.prepare(sql)
            if params:
                stmt = stmt.bind(*params)
            res = await stmt.all()
            if res is None:
                return []
            if isinstance(res, dict) and "results" in res:
                results = res["results"]
            else:
                results = getattr(res, "results", res)
            if hasattr(results, "to_py"):
                results = results.to_py()
            out = []
            for r in results:
                if hasattr(r, "to_py"):
                    out.append(dict(r.to_py()))
                elif isinstance(r, dict):
                    out.append(r)
                else:
                    out.append(dict(r))
            return out
        except Exception as e:
            logger.error(f"D1 fetch_all error: {e}")
            return []
