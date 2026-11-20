import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "permgraph.db"

IMPLIED_RELATIONS: dict[str, tuple[str, ...]] = {
    "viewer": ("viewer", "editor", "owner"),
    "editor": ("editor", "owner"),
    "owner": ("owner",),
    "member": ("member", "admin", "owner"),
    "admin": ("admin", "owner"),
}


@dataclass(frozen=True)
class CheckOutcome:
    allowed: bool
    revision: int
    cache_hit: bool
    path: list[str]


class PermGraphEngine:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._cache: dict[tuple[int, str, str, str, str, str], tuple[bool, list[str]]] = {}
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS relation_tuples (
                    object_ns TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    subject_ns TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    subject_relation TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (object_ns, object_id, relation, subject_ns, subject_id, subject_relation)
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tuple_lookup ON relation_tuples(object_ns, object_id, relation);"
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value INTEGER NOT NULL
                )
                """
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO metadata (key, value) VALUES ('revision', 1);"
            )
            self._conn.commit()

    def current_revision(self) -> int:
        row = self._conn.execute("SELECT value FROM metadata WHERE key = 'revision'").fetchone()
        return int(row["value"]) if row else 1

    def write_tuple(
        self,
        object_ns: str,
        object_id: str,
        relation: str,
        subject_ns: str,
        subject_id: str,
        subject_relation: str = "",
    ) -> int:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO relation_tuples
                (object_ns, object_id, relation, subject_ns, subject_id, subject_relation)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (object_ns, object_id, relation, subject_ns, subject_id, subject_relation),
            )
            self._conn.execute("UPDATE metadata SET value = value + 1 WHERE key = 'revision';")
            self._conn.commit()
            self._cache.clear()
            return self.current_revision()

    def delete_tuple(
        self,
        object_ns: str,
        object_id: str,
        relation: str,
        subject_ns: str,
        subject_id: str,
        subject_relation: str = "",
    ) -> int:
        with self._lock:
            self._conn.execute(
                """
                DELETE FROM relation_tuples
                WHERE object_ns = ? AND object_id = ? AND relation = ?
                  AND subject_ns = ? AND subject_id = ? AND subject_relation = ?
                """,
                (object_ns, object_id, relation, subject_ns, subject_id, subject_relation),
            )
            self._conn.execute("UPDATE metadata SET value = value + 1 WHERE key = 'revision';")
            self._conn.commit()
            self._cache.clear()
            return self.current_revision()

    def check(
        self,
        object_ns: str,
        object_id: str,
        permission: str,
        subject_ns: str,
        subject_id: str,
    ) -> CheckOutcome:
        with self._lock:
            rev = self.current_revision()
            cache_key = (rev, object_ns, object_id, permission, subject_ns, subject_id)
            cached = self._cache.get(cache_key)
            if cached is not None:
                return CheckOutcome(allowed=cached[0], revision=rev, cache_hit=True, path=cached[1])

            path = self._resolve(
                object_ns=object_ns,
                object_id=object_id,
                permission=permission,
                subject_ns=subject_ns,
                subject_id=subject_id,
                visited=frozenset(),
            )
            allowed = path is not None
            resolved_path = path or []
            if len(self._cache) >= 10000:
                self._cache.clear()
            self._cache[cache_key] = (allowed, resolved_path)
            return CheckOutcome(allowed=allowed, revision=rev, cache_hit=False, path=resolved_path)

    def _resolve(
        self,
        object_ns: str,
        object_id: str,
        permission: str,
        subject_ns: str,
        subject_id: str,
        visited: frozenset[tuple[str, str, str]],
    ) -> list[str] | None:
        state = (object_ns, object_id, permission)
        if state in visited:
            return None
        next_visited = visited | {state}

        implied = IMPLIED_RELATIONS.get(permission, (permission,))

        # 1. Evaluate direct subjects and userset rewrites (e.g., team:platform#member)
        for rel in implied:
            rows = self._conn.execute(
                """
                SELECT subject_ns, subject_id, subject_relation
                FROM relation_tuples
                WHERE object_ns = ? AND object_id = ? AND relation = ?
                """,
                (object_ns, object_id, rel),
            ).fetchall()

            for r in rows:
                s_ns = r["subject_ns"]
                s_id = r["subject_id"]
                s_rel = r["subject_relation"]

                if s_rel == "" and s_ns == subject_ns and s_id == subject_id:
                    return [f"{object_ns}:{object_id}#{rel} -> {subject_ns}:{subject_id}"]

                if s_rel != "":
                    sub_path = self._resolve(
                        object_ns=s_ns,
                        object_id=s_id,
                        permission=s_rel,
                        subject_ns=subject_ns,
                        subject_id=subject_id,
                        visited=next_visited,
                    )
                    if sub_path is not None:
                        return [f"{object_ns}:{object_id}#{rel} -> {s_ns}:{s_id}#{s_rel}"] + sub_path

        # 2. Traverse hierarchical parent containers (e.g., doc -> folder -> org)
        if permission in ("viewer", "editor", "owner"):
            parent_rows = self._conn.execute(
                """
                SELECT subject_ns, subject_id
                FROM relation_tuples
                WHERE object_ns = ? AND object_id = ? AND relation = 'parent'
                """,
                (object_ns, object_id),
            ).fetchall()

            for pr in parent_rows:
                p_ns = pr["subject_ns"]
                p_id = pr["subject_id"]
                parent_path = self._resolve(
                    object_ns=p_ns,
                    object_id=p_id,
                    permission=permission,
                    subject_ns=subject_ns,
                    subject_id=subject_id,
                    visited=next_visited,
                )
                if parent_path is not None:
                    return [f"{object_ns}:{object_id}#{permission} (inherits parent {p_ns}:{p_id})"] + parent_path

        return None

    def stats(self) -> dict[str, int]:
        with self._lock:
            count = self._conn.execute("SELECT COUNT(*) AS c FROM relation_tuples").fetchone()["c"]
            return {
                "total_tuples": int(count),
                "current_revision": self.current_revision(),
                "cached_decisions": len(self._cache),
            }
