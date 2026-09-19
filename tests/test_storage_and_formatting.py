from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pm_life.formatting import chunk_trajectory, profile_counts
from pm_life.storage import SQLiteStore


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
            self.assertEqual(store.get_run("qq:group-a", "user", 1)["seed"], "seed-2")
            self.assertEqual(store.get_run("qq:group-a", "user", 2)["seed"], "seed-1")
            self.assertIsNone(store.get_run("qq:group-a", "user", 3))


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
