from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


def build_scope_key(
    platform: str | None, group_id: str | None, user_id: str
) -> str:
    """Build a stable save scope while preserving existing group save keys."""
    platform_key = str(platform or "qq")
    if group_id:
        return f"{platform_key}:{group_id}"
    return f"{platform_key}:private:{user_id}"


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


class SQLiteStore:
    def __init__(self, path: Path, history_limit: int = 10) -> None:
        self.path = Path(path)
        self.history_limit = max(1, int(history_limit))
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connection() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                    group_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    profile_json TEXT NOT NULL,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (group_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    group_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    session_json TEXT NOT NULL,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (group_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    seed TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    summary_json TEXT NOT NULL,
                    trajectory_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_runs_owner
                    ON runs(group_id, user_id, id DESC);
                PRAGMA user_version=1;
                """
            )
            columns = {row["name"] for row in db.execute("PRAGMA table_info(runs)")}
            if "details_json" not in columns:
                db.execute(
                    "ALTER TABLE runs ADD COLUMN details_json TEXT NOT NULL DEFAULT '{}'"
                )

    def get_profile(self, group_id: str, user_id: str) -> dict[str, str]:
        with self._lock, self._connection() as db:
            row = db.execute(
                "SELECT profile_json FROM profiles WHERE group_id=? AND user_id=?",
                (group_id, user_id),
            ).fetchone()
        value = _load(row["profile_json"] if row else None, {})
        return value if isinstance(value, dict) else {}

    def get_session(self, group_id: str, user_id: str) -> dict[str, Any] | None:
        with self._lock, self._connection() as db:
            row = db.execute(
                "SELECT session_json FROM sessions WHERE group_id=? AND user_id=?",
                (group_id, user_id),
            ).fetchone()
        value = _load(row["session_json"] if row else None, None)
        return value if isinstance(value, dict) else None

    def save_session(
        self, group_id: str, user_id: str, session: dict[str, Any]
    ) -> None:
        now = int(time.time())
        with self._lock, self._connection() as db:
            db.execute(
                """
                INSERT INTO sessions(group_id,user_id,session_json,updated_at)
                VALUES(?,?,?,?)
                ON CONFLICT(group_id,user_id) DO UPDATE SET
                    session_json=excluded.session_json,
                    updated_at=excluded.updated_at
                """,
                (group_id, user_id, _dump(session), now),
            )

    def clear_session(self, group_id: str, user_id: str) -> None:
        with self._lock, self._connection() as db:
            db.execute(
                "DELETE FROM sessions WHERE group_id=? AND user_id=?",
                (group_id, user_id),
            )

    def delete_user_data(self, group_id: str, user_id: str) -> None:
        """Delete one user's profile, pending session, and run history in a scope."""
        with self._lock, self._connection() as db:
            owner = (group_id, user_id)
            db.execute("DELETE FROM runs WHERE group_id=? AND user_id=?", owner)
            db.execute("DELETE FROM sessions WHERE group_id=? AND user_id=?", owner)
            db.execute("DELETE FROM profiles WHERE group_id=? AND user_id=?", owner)

    def save_profile_and_session(
        self,
        group_id: str,
        user_id: str,
        profile: dict[str, str],
        session: dict[str, Any] | None,
    ) -> None:
        now = int(time.time())
        with self._lock, self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """
                INSERT INTO profiles(group_id,user_id,profile_json,updated_at)
                VALUES(?,?,?,?)
                ON CONFLICT(group_id,user_id) DO UPDATE SET
                    profile_json=excluded.profile_json,
                    updated_at=excluded.updated_at
                """,
                (group_id, user_id, _dump(profile), now),
            )
            if session is None:
                db.execute(
                    "DELETE FROM sessions WHERE group_id=? AND user_id=?",
                    (group_id, user_id),
                )
            else:
                db.execute(
                    """
                    INSERT INTO sessions(group_id,user_id,session_json,updated_at)
                    VALUES(?,?,?,?)
                    ON CONFLICT(group_id,user_id) DO UPDATE SET
                        session_json=excluded.session_json,
                        updated_at=excluded.updated_at
                    """,
                    (group_id, user_id, _dump(session), now),
                )

    def complete_run(
        self,
        group_id: str,
        user_id: str,
        profile: dict[str, str],
        session: dict[str, Any],
        seed: str,
        details: dict[str, Any],
        summary: dict[str, Any],
        trajectory: list[dict[str, Any]],
    ) -> int:
        now = int(time.time())
        with self._lock, self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """
                INSERT INTO profiles(group_id,user_id,profile_json,updated_at)
                VALUES(?,?,?,?)
                ON CONFLICT(group_id,user_id) DO UPDATE SET
                    profile_json=excluded.profile_json,
                    updated_at=excluded.updated_at
                """,
                (group_id, user_id, _dump(profile), now),
            )
            db.execute(
                """
                INSERT INTO sessions(group_id,user_id,session_json,updated_at)
                VALUES(?,?,?,?)
                ON CONFLICT(group_id,user_id) DO UPDATE SET
                    session_json=excluded.session_json,
                    updated_at=excluded.updated_at
                """,
                (group_id, user_id, _dump(session), now),
            )
            cursor = db.execute(
                """
                INSERT INTO runs(group_id,user_id,created_at,seed,details_json,summary_json,trajectory_json)
                VALUES(?,?,?,?,?,?,?)
                """,
                (
                    group_id,
                    user_id,
                    now,
                    seed,
                    _dump(details),
                    _dump(summary),
                    _dump(trajectory),
                ),
            )
            run_id = int(cursor.lastrowid)
            db.execute(
                """
                DELETE FROM runs
                WHERE group_id=? AND user_id=? AND id NOT IN (
                    SELECT id FROM runs
                    WHERE group_id=? AND user_id=?
                    ORDER BY id DESC LIMIT ?
                )
                """,
                (group_id, user_id, group_id, user_id, self.history_limit),
            )
        return run_id

    def get_run(
        self, group_id: str, user_id: str, position: int = 1
    ) -> dict[str, Any] | None:
        position = max(1, int(position))
        with self._lock, self._connection() as db:
            row = db.execute(
                """
                SELECT id,created_at,seed,details_json,summary_json,trajectory_json
                FROM runs WHERE group_id=? AND user_id=?
                ORDER BY id DESC LIMIT 1 OFFSET ?
                """,
                (group_id, user_id, position - 1),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "seed": row["seed"],
            "details": _load(row["details_json"], {}),
            "summary": _load(row["summary_json"], {}),
            "trajectory": _load(row["trajectory_json"], []),
        }
