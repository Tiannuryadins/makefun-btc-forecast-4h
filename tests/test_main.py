"""Tests for main.py (stdlib only).

Run: python3 -m unittest discover -s tests

Fixtures are the kit's six practice cases (tests/fixtures/p00.in..p05.in).
The kit ships no answers, so practice answers are derived: the six
checkpoints are 4 hours apart and each answer is the close 240 minutes
after its checkpoint, i.e. case p0k's answer is the checkpoint close
(last price) of case p0(k+1). That covers p00..p04; p05's answer lies
beyond every case in the kit and is not derivable, so scoring uses p00..p04.
"""

import json
import math
import os
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures")
sys.path.insert(0, ROOT)

import main  # noqa: E402

IDS = ["p00", "p01", "p02", "p03", "p04", "p05"]


def read_case(case_id):
    with open(os.path.join(FIX, case_id + ".in"), encoding="utf-8") as fh:
        return json.load(fh)


def checkpoint_closes():
    return {c: read_case(c)["markets"][0]["prices"][-1] for c in IDS}


def expected_answers():
    """Actual close 240 min after each checkpoint, for p00..p04."""
    closes = checkpoint_closes()
    return {f"p0{i}": closes[f"p0{i + 1}"] for i in range(5)}


def run_entry(input_dir, output_dir):
    env = dict(os.environ)
    env["MAKEFUN_INPUT_DIR"] = input_dir
    env["MAKEFUN_OUTPUT_DIR"] = output_dir
    return subprocess.run(
        [sys.executable, os.path.join(ROOT, "main.py")],
        env=env, capture_output=True, text=True, timeout=60,
    )


class FormatTests(unittest.TestCase):
    def test_output_files_match_contract(self):
        with tempfile.TemporaryDirectory() as out:
            proc = run_entry(FIX, out)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            for case_id in IDS:
                path = os.path.join(out, case_id + ".out")
                self.assertTrue(os.path.exists(path), "missing " + path)
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
                self.assertEqual(text.count("\n"), 1, "must be one line")
                self.assertTrue(text.endswith("\n"))
                doc = json.loads(text)
                self.assertEqual(list(doc), ["forecasts"])
                self.assertEqual(len(doc["forecasts"]), 1)
                row = doc["forecasts"][0]
                self.assertEqual(list(row), ["case", "price"])
                self.assertEqual(row["case"], case_id)
                price = row["price"]
                self.assertIsInstance(price, (int, float))
                self.assertTrue(math.isfinite(price))
                self.assertTrue(0 < price < 10_000_000)
                # On the 5-decimal grid (float noise tolerated).
                self.assertLess(abs(price * 1e5 - round(price * 1e5)), 1e-3)

    def test_two_runs_produce_identical_bytes(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            self.assertEqual(run_entry(FIX, d1).returncode, 0)
            self.assertEqual(run_entry(FIX, d2).returncode, 0)
            for case_id in IDS:
                with open(os.path.join(d1, case_id + ".out"), "rb") as fh:
                    first = fh.read()
                with open(os.path.join(d2, case_id + ".out"), "rb") as fh:
                    second = fh.read()
                self.assertEqual(first, second, case_id + " differs")

    def test_fast_enough_for_the_cap(self):
        with tempfile.TemporaryDirectory() as out:
            start = time.perf_counter()
            proc = run_entry(FIX, out)
            elapsed = time.perf_counter() - start
            self.assertEqual(proc.returncode, 0, proc.stderr)
            # Cap is 8,000 ms per case; 6 cases in one process must be far under.
            self.assertLess(elapsed, 8.0, f"6 cases took {elapsed:.2f}s")


class ForecastTests(unittest.TestCase):
    def test_practice_mae_beats_persistence(self):
        answers = expected_answers()
        mine, base = [], []
        for case_id, actual in answers.items():
            prices = read_case(case_id)["markets"][0]["prices"]
            mine.append(abs(main.predict(prices) - actual) * 100)
            base.append(abs(prices[-1] - actual) * 100)
        mae = sum(mine) / len(mine)
        pmae = sum(base) / len(base)
        self.assertLess(mae, pmae,
                        f"forecaster MAE {mae:.1f} not below persistence {pmae:.1f}")

    def test_flat_series_is_persistence(self):
        self.assertEqual(main.predict([50000.0] * 4320), 50000.0)

    def test_one_price_only(self):
        self.assertEqual(main.predict([12345.67891]), 12345.67891)

    def test_short_series_returns_a_valid_price(self):
        price = main.predict([70000.0 + i for i in range(50)])
        self.assertTrue(0 < price < 10_000_000)

    def test_end_spike_pulls_back_within_cap(self):
        # A +10% spike on the last minute must pull back toward the level
        # but never by more than the 2% adjustment cap.
        series = [70000.0] * 4319 + [77000.0]
        price = main.predict(series)
        self.assertLess(price, 77000.0)
        # Tolerance must exceed one output-grid step (1e-5): the forecast
        # lands exactly on the -2% cap and 5-decimal rounding can shave up
        # to half a step off the cap boundary.
        self.assertGreaterEqual(price, 77000.0 * math.exp(-0.02) - 1e-4)

    def test_invalid_inputs_raise(self):
        with self.assertRaises(ValueError):
            main.predict([])
        with self.assertRaises(ValueError):
            main.predict([70000.0, float("nan")])
        with self.assertRaises(ValueError):
            main.predict([70000.0, -5.0])


if __name__ == "__main__":
    unittest.main()
