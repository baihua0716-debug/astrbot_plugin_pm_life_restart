from __future__ import annotations

import itertools
import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Worker:
    def __init__(self) -> None:
        self.process = subprocess.Popen(
            ["node", str(ROOT / "engine" / "worker.js")],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        self.serial = 0

    def request(self, action: str, **data):
        self.serial += 1
        request_id = str(self.serial)
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        self.process.stdin.write(
            json.dumps({"id": request_id, "action": action, **data}, ensure_ascii=False)
            + "\n"
        )
        self.process.stdin.flush()
        response = json.loads(self.process.stdout.readline())
        self.assert_id(response, request_id)
        return response

    @staticmethod
    def assert_id(response, request_id: str) -> None:
        if response.get("id") != request_id:
            raise AssertionError(response)

    def close(self) -> None:
        self.process.terminate()
        self.process.wait(timeout=5)


class EngineEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.worker = Worker()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.worker.close()

    def test_full_life_and_inheritance(self) -> None:
        ping = self.worker.request("ping")
        self.assertTrue(ping["ok"], ping)

        seed = "e2e-fixed-seed"
        draw = self.worker.request("draw", profile={}, seed=seed)
        self.assertTrue(draw["ok"], draw)
        talents = draw["result"]["talents"]
        self.assertEqual(len(talents), 15)

        prepared = None
        indexes = None
        for candidate in itertools.combinations(range(1, 16), 4):
            response = self.worker.request(
                "prepare", profile={}, seed=seed, indexes=list(candidate)
            )
            if response["ok"]:
                prepared = response["result"]
                indexes = list(candidate)
                break
        self.assertIsNotNone(prepared)
        assert prepared is not None and indexes is not None

        remaining = prepared["points"]
        values = []
        for _ in range(4):
            value = min(15, remaining)
            values.append(value)
            remaining -= value
        allocation = dict(zip(("CHR", "INT", "STR", "MNY"), values))
        simulated = self.worker.request(
            "simulate",
            profile={},
            seed=seed,
            indexes=indexes,
            allocation=allocation,
        )
        self.assertTrue(simulated["ok"], simulated)
        result = simulated["result"]
        self.assertGreater(len(result["trajectory"]), 0)
        self.assertIn("SUM", result["summary"])
        self.assertEqual(json.loads(result["profile"]["times"]), 1)

        talent = result["selected"][0]
        inherited = self.worker.request(
            "inherit", profile=result["profile"], talentId=talent["id"]
        )
        self.assertTrue(inherited["ok"], inherited)
        self.assertEqual(
            json.loads(inherited["result"]["profile"]["extendTalent"]),
            talent["id"],
        )


if __name__ == "__main__":
    unittest.main()
