# BTC 4-hour forecast — make.fun `btc-cent-forecast-01`

Entry for *Forecast Bitcoin's price 4 hours ahead, 12 times over 48 hours*.
`main.py` (Python 3, standard library only, offline, deterministic) reads
each case's 4,320 one-minute BTC/USDC closes and forecasts the close 240
minutes after the checkpoint.

## How it forecasts

Default: **persistence** (the checkpoint close). Bitcoin's 4-hour return is
close to unpredictable, so the program only deviates from persistence when
the evidence for a snap-back is statistically meaningful — gated,
volatility-scaled mean reversion:

1. **Level** — a 12-hour half-life EMA of log prices; the deviation
   `dev = last log price − EMA` measures how extended the price is.
2. **Gate** — the deviation must exceed one 4-hour sigma (realised vol of
   1-minute log returns over the last 12 hours, scaled by √240). Inside one
   sigma the move is noise, so the forecast stays at persistence.
3. **Reversion** — when the gate opens, pull back 70% of the *excess*
   deviation (the part beyond one sigma) toward the EMA.
4. **Exhaustion** — if the last 30 minutes still moved in the direction of
   the deviation, the move is running, so the adjustment is halved; if the
   price already turned, the full adjustment applies.
5. **Cap** — the total log adjustment is capped at ±2%.

Output per case is exactly one line:
`{"forecasts": [{"case": "<id>", "price": <number>}]}` with the price on the
5-decimal grid inside (0, 10,000,000).

## Results on the practice cases

Practice answers are derived from the kit itself (case p0k's answer is the
checkpoint close of p0(k+1); p05's answer is not in the kit). MAE in cents
over the 5 derivable practice cases (p00–p04):

| | MAE (cents) |
|---|---:|
| This forecaster | **44,831.2** |
| Persistence baseline | 47,054.7 |
| Improvement | **+4.73%** |

Rolling-origin validation over the full practice window (16 non-overlapping
4-hour origins): 38,925.4 vs 41,768.3 cents (**+6.81%**), positive on every
consecutive stretch tested (+7.68%, +4.52%, +5.84%). See
[BUILD-TRANSCRIPT.md](BUILD-TRANSCRIPT.md) for the full method and numbers,
including the approaches that were tried and rejected (trend extrapolation,
un-gated EMA blends, momentum — all lose to persistence in trending
stretches).

## Run

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=tests/fixtures MAKEFUN_OUTPUT_DIR=out python3 main.py
```

In the grader, `/input` and `/output` are used by default. Runtime is about
10 ms per case (cap: 8,000 ms).

## Test

```sh
python3 -m unittest discover -s tests
```

9 tests: output format (exact keys, one row, price bounds, 5-decimal grid),
byte-identical determinism across two runs, runtime, practice MAE beating
persistence, and edge cases (flat prices, single price, short series,
spikes, invalid prices). Fixtures are the kit's six practice cases.

## License

MIT — see [LICENSE](LICENSE).
