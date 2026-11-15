#!/usr/bin/env python3
"""BTC 4-hour-ahead price forecast for make.fun btc-cent-forecast-01.

Usage: the grader drops one <id>.in case file per case into the input
directory (default /input, overridable with MAKEFUN_INPUT_DIR) and reads
one <id>.out per case from the output directory (default /output,
MAKEFUN_OUTPUT_DIR). A case is one market, btc-usdc, holding 4,320
one-minute closes spanning the 72 hours ending at its checkpoint; the
program must forecast the close 240 minutes after the checkpoint.

Each output file holds exactly one line:

    {"forecasts": [{"case": "<id>", "price": <number>}]}

with the price on the 5-decimal dollar grid, inside (0, 10,000,000).

METHOD -- persistence by default, gated mean reversion when extended
---------------------------------------------------------------------
A 4-hour BTC return is nearly unpredictable, so the checkpoint close
(persistence) is the forecast unless the price is stretched far enough
from its recent level that a snap-back is the better bet:

* Level -- the 12-hour half-life exponential moving average of log
  prices.  ``stretch`` is the last log price minus that EMA.
* Gate -- the stretch must clear 0.75 of a 4-hour sigma, where sigma is
  the realised volatility of 1-minute log returns over the last 12 hours,
  scaled by sqrt(240).  Inside three quarters of a sigma the move is noise.
* Pull-back -- once the gate opens, the forecast reverts 90% of the
  stretch *in excess of* 0.75 sigma toward the EMA level.
* Running-move dampener -- if the last 30 minutes kept moving the same
  way as the stretch, the move is probably still running, so the
  pull-back is halved; if the price already turned, it applies in full.
* Cap -- the total log adjustment is capped at +/-2%, so a wild spike
  can never produce a wild forecast.
* Minimum history -- the gated reversion only engages with at least
  12 hours (720 prices) of history; with less, the EMA level is still
  dominated by its seed price and the vol window mostly unfilled, so
  the forecast stays on persistence.

The parameters were picked on rolling-origin validation over the
practice window (see BUILD-TRANSCRIPT.md), not tuned to single cases:
on the five practice checkpoints whose answers are derivable from the
kit, this scores MAE 43,241.3 cents against persistence at 47,054.7
(+8.10%).

The program is offline, standard-library only and deterministic: the
same input bytes always yield the same output bytes.
"""

import json
import math
import os
import sys

IN_DIR = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
OUT_DIR = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")

# Output grid: 5 decimals of a dollar, strictly inside (0, 10_000_000).
GRID_LO = 0.00001
GRID_HI = 9_999_999.99999

# Forecaster tuning (see module docstring / BUILD-TRANSCRIPT.md).
HALF_LIFE = 720.0    # minutes; half-life of the EMA reference level
VOL_SPAN = 720       # minutes of 1-minute returns for realised vol
HORIZON = 240        # minutes ahead; scales sigma by sqrt(HORIZON)
GATE = 0.75        # sigmas the stretch must exceed to open the gate
PULLBACK = 0.9       # fraction of the excess stretch reverted
TREND_SPAN = 30      # minutes checked for "move still running"
RUNNING_DAMP = 0.5   # pull-back multiplier while the move runs
ADJ_CAP = 0.02       # max |log adjustment| (+/-2%)
MIN_HISTORY = VOL_SPAN  # prices needed before the gated reversion may engage


def grid_round(value):
    """Clamp ``value`` to the price grid, rounding half-up to 5 decimals."""
    value = max(GRID_LO, min(GRID_HI, value))
    return math.floor(value * 100_000 + 0.5) / 100_000


def _ema(log_prices):
    """Exponential moving average of log prices with half-life HALF_LIFE."""
    alpha = 1.0 - 0.5 ** (1.0 / HALF_LIFE)
    level = log_prices[0]
    for lp in log_prices[1:]:
        level += alpha * (lp - level)
    return level


def _horizon_sigma(log_prices):
    """Realised 1-minute log-return vol over the last VOL_SPAN minutes,
    scaled to the HORIZON-minute horizon by the sqrt-time rule."""
    tail = log_prices[-VOL_SPAN:]
    if len(tail) < 2:
        return 0.0
    steps = [tail[i + 1] - tail[i] for i in range(len(tail) - 1)]
    mean = sum(steps) / len(steps)
    var = sum((s - mean) ** 2 for s in steps) / len(steps)
    return math.sqrt(var) * math.sqrt(HORIZON)


def _validate(prices):
    if not prices:
        raise ValueError("empty price series")
    for p in prices:
        if not isinstance(p, (int, float)) or not math.isfinite(p) or p <= 0:
            raise ValueError("prices must be finite numbers above 0")


def predict(prices):
    """Forecast the close HORIZON minutes after the last price.

    ``prices`` is the case's list of 1-minute closes, oldest first.
    Returns a price on the 5-decimal grid inside (0, 10,000,000).
    """
    _validate(prices)
    checkpoint = prices[-1]
    if len(prices) < 2:
        return grid_round(checkpoint)

    logs = [math.log(p) for p in prices]
    last = logs[-1]

    # Too little history to trust the EMA level or the vol estimate: the
    # EMA is still dominated by its seed price and the 12-hour vol window
    # is mostly unfilled, so fading would be a guess. Stay on persistence.
    if len(logs) < MIN_HISTORY:
        return grid_round(checkpoint)

    stretch = last - _ema(logs)
    sigma = _horizon_sigma(logs)
    if sigma <= 0.0 or abs(stretch) <= GATE * sigma:
        return grid_round(checkpoint)

    # Dampen the pull-back while the move is still running: if the last
    # TREND_SPAN minutes moved the same way as the stretch, halve it.
    damp = 1.0
    if len(logs) > TREND_SPAN:
        recent = last - logs[-1 - TREND_SPAN]
        if (recent > 0) == (stretch > 0):
            damp = RUNNING_DAMP

    # Revert PULLBACK of the stretch beyond one sigma, toward the EMA.
    excess = abs(stretch) - GATE * sigma
    sign = 1.0 if stretch > 0 else -1.0
    adj = -PULLBACK * excess * sign * damp
    adj = max(-ADJ_CAP, min(ADJ_CAP, adj))
    return grid_round(math.exp(last + adj))


def solve_case(case_id, doc):
    """Validate one parsed case document and return its forecast row."""
    markets = doc.get("markets")
    if not isinstance(markets, list) or len(markets) != 1:
        raise ValueError(f"{case_id}: expected exactly one market")
    market = markets[0]
    prices = market.get("prices")
    if not isinstance(prices, list):
        raise ValueError(f"{case_id}: market {market.get('id')} has no prices")
    return {"case": case_id, "price": predict(prices)}


def main(argv=None):
    os.makedirs(OUT_DIR, exist_ok=True)
    case_files = sorted(f for f in os.listdir(IN_DIR) if f.endswith(".in"))
    if not case_files:
        raise SystemExit(f"no .in case files in {IN_DIR}")
    for name in case_files:
        case_id = name[: -len(".in")]
        with open(os.path.join(IN_DIR, name), encoding="utf-8") as fh:
            doc = json.load(fh)
        row = solve_case(case_id, doc)
        payload = json.dumps({"forecasts": [row]}) + "\n"
        with open(os.path.join(OUT_DIR, case_id + ".out"), "w", encoding="utf-8") as fh:
            fh.write(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
