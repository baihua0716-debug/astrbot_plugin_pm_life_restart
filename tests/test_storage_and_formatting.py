from __future__ import annotations

import json
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

from pm_life.formatting import chunk_trajectory, profile_counts
from pm_life.storage import SQLiteStore, build_scope_key


class StorageTests(unittest.TestCase):
    def test_group_scoped_profiles_and_history_pruning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "test.sqlite3", history_limit=2)
            for index in range(3):
                store.complete_run(
                    "qq:group-a",
                    "user",
                    {"times": json.dumps(index + 1)},
                    {"phase": "inherit", "options": []},
                    f"seed-{index}",
                    {"selected": [], "allocation": {}},
                    {"SUM": {"value": index}},
                    [{"age": index, "text": f"{index}岁：测试"}],
                )
            self.assertEqual(
                json.loads(store.get_profile("qq:group-a", "user")["times"]), 3
            )
            self.assertEqual(store.get_profile("qq:group-b", "user"), {})
            self.assertEqual(build_scope_key("qq", "group-a", "user"), "qq:group-a")
            private_scope = build_scope_key("qq", None, "user")
            self.assertEqual(private_scope, "qq:private:user")
            self.assertEqual(store.get_profile(private_scope, "user"), {})
            self.assertEqual(store.get_run("qq:group-a", "user", 1)["seed"], "seed-2")
            self.assertEqual(store.get_run("qq:group-a", "user", 2)["seed"], "seed-1")
            self.assertIsNone(store.get_run("qq:group-a", "user", 3))

            store.save_session(private_scope, "user", {"phase": "talent"})
            store.delete_user_data("qq:group-a", "user")
            self.assertEqual(store.get_profile("qq:group-a", "user"), {})
            self.assertIsNone(store.get_session("qq:group-a", "user"))
            self.assertIsNone(store.get_run("qq:group-a", "user", 1))
            self.assertEqual(
                store.get_session(private_scope, "user"), {"phase": "talent"}
            )

    def test_recent_session_expires_without_deleting_save(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "test.sqlite3")
            scope = "qq:group-a"
            user = "user"
            session = {"phase": "inherit", "options": []}
            store.save_session(scope, user, session)
            self.assertEqual(store.get_recent_session(scope, user, 600), session)
            self.assertIsNone(store.get_recent_session(scope, "other", 600))

            with closing(sqlite3.connect(store.path)) as db:
                db.execute(
                    "UPDATE sessions SET updated_at=? WHERE group_id=? AND user_id=?",
                    (int(time.time()) - 601, scope, user),
                )
                db.commit()
            self.assertIsNone(store.get_recent_session(scope, user, 600))
            self.assertEqual(store.get_session(scope, user), session)

            store.save_session(scope, user, session)
            self.assertEqual(store.get_recent_session(scope, user, 600), session)


class FormattingTests(unittest.TestCase):
    def test_chunking_and_profile_counts(self) -> None:
        chunks = chunk_trajectory(
            [{"text": f"{age}岁：" + "内容" * 100} for age in range(20)],
            max_chars=500,
        )
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 500 for chunk in chunks))
        counts = profile_counts(
            {
                "times": "3",
                "ATLT": "[1,2]",
                "AEVT": "[3]",
                "ACHV": "[[4,123]]",
            }
        )
        self.assertEqual(counts["times"], 3)
        self.assertEqual(counts["talents"], 2)


if __name__ == "__main__":
    unittest.main()
