DATA INSIGHT (from alerts)

Many alerts are in trend_regime = DOWNTREND (~half).

A dangerous cluster exists: DOWNTREND + vol_regime = HIGH.

Score distribution clusters around 70 and 80, so a minimum score threshold will meaningfully reduce noise.

PRIMARY GOAL
Refine V2 gating rules to:

Enforce a minimum score filter

Hard-block mean reversion LONG alerts in the toxic regime: DOWNTREND + HIGH volatility

In downtrends (but NOT toxic), require a higher score threshold

Keep news risk as annotation unless it’s deterministic (earnings block placeholder only)

Ensure all decisions are logged with reasons and visible in reports




v2_gate:
min_price: 5.0
min_avg_dollar_volume_20d: 20000000
min_score: 70
max_score_in_panic: 999 # keep placeholder, not used unless panic exists
block_downtrend_high_vol: true
downtrend_min_score: 80
allow_weak_downtrend: true
strict_earnings_block: false
htf_timeframe: "4h"

IMPORTANT:

IMPLEMENTATION: V2 GATE UPGRADE

In src/v2/gate.py, extend evaluate_gate() to accept score and apply new rules.

Gate inputs:
evaluate_gate(symbol, timeframe, setup_name, direction, features, score, gate_config) -> GateResult

Required features for evaluation:

last_price

avg_dollar_volume_20d

trend_regime

vol_regime

chop_regime (if unavailable, mark NOT_EVALUATED)

(optional) news_risk

NEW RULES (apply in order)

Missing inputs:

If any required feature is missing OR score is None => NOT_EVALUATED reason MISSING_FEATURES

Existing hard exclusions:

last_price < min_price => NO_GO PENNY_STOCK

avg_dollar_volume_20d < min_avg_dollar_volume_20d => NO_GO ILLIQUID

vol_regime == PANIC => NO_GO PANIC_VOL

trend_regime == STRONG_DOWN and vol_regime in {HIGH, PANIC} => NO_GO FALLING_KNIFE_REGIME

New min score filter (V2 only):

if score < min_score => NO_GO LOW_SCORE

Toxic regime hard block (this is the key improvement):
If block_downtrend_high_vol == true AND:

trend_regime in {DOWNTREND, WEAK_DOWN, STRONG_DOWN} AND vol_regime == HIGH
=> NO_GO DOWNTREND_HIGH_VOL_BLOCK

Downtrend stricter threshold (non-toxic only):
If trend_regime in {DOWNTREND, WEAK_DOWN} AND vol_regime in {NORMAL}:

if score < downtrend_min_score => NO_GO DOWNTREND_SCORE_TOO_LOW

else GO with scrutiny_level=HIGH

Allowed baseline (non-downtrend):
GO if trend in {NEUTRAL, UPTREND, WEAK_UP, STRONG_UPTREND} AND vol in {NORMAL, HIGH}

BUT if vol == HIGH, return GO with scrutiny_level=HIGH (not blocked)

else scrutiny_level=NORMAL

Otherwise:
NO_GO REGIME_BLOCK

Gate tags must always include:

trend_regime, vol_regime, chop_regime
Also include score in tags for easier reporting.

C) ENGINE ROUTING (LIVE RUNNER)

Modify src/runner/live_runner.py (or wherever alerts are emitted) so:


When engine.mode=shadow:
Evaluate the normal alert logic exactly as today.
For each emitted V1 alert:

compute V2 gate decision using the alert score + features

log to gate_decisions table


When engine.mode=v2:
Before evaluating/sending an alert:

compute V2 gate decision

if gate != GO: log gate_decision, skip emitting alert

if gate == GO: emit alert, store in v2_alerts, and include gate metadata + reason codes in payload json

IMPORTANT:

V2 must be gate-first.



D) SQLITE LOGGING

Ensure gate_decisions logging includes the new reason codes:

LOW_SCORE

DOWNTREND_HIGH_VOL_BLOCK

DOWNTREND_SCORE_TOO_LOW

Ensure v2_alerts stores:

score

gate_status

reasons_json

scrutiny_level

tags_json

Do not modify existing alerts tables. Add or extend tables only.

E) REPORTING IMPROVEMENTS

Update the existing V2 report CLI (python -m src.v2.report) to include:

Total GO vs NO_GO counts

NO_GO reason counts (top 10)

Breakdown:

trend_regime x vol_regime counts (GO only)

A new line for:

“Blocked by DOWNTREND_HIGH_VOL_BLOCK: <count>”

Optional:
Write a CSV reports/v2_gate_breakdown.csv with columns:

reason

count

pct

F) TESTS (NO NETWORK)

Add unit tests in tests/:

test_gate_min_score_blocks

score=60 => NO_GO LOW_SCORE

test_gate_blocks_downtrend_high_vol

trend_regime=DOWNTREND, vol_regime=HIGH, score=90 => NO_GO DOWNTREND_HIGH_VOL_BLOCK

test_gate_downtrend_requires_higher_score

trend_regime=DOWNTREND, vol_regime=NORMAL, score=75 => NO_GO DOWNTREND_SCORE_TOO_LOW

score=85 => GO with scrutiny HIGH

test_gate_normal_regime_allows

trend_regime=NEUTRAL, vol_regime=NORMAL, score=70 => GO

test_missing_features_fail_closed

score=None or missing trend_regime => NOT_EVALUATED MISSING_FEATURES





test_shadow_logs_gate_but_does_not_suppress

mock notifier send called once

gate_decisions written

test_v2_suppresses_on_nogo

when NO_GO, notifier send is not called

gate_decision logged

Run full test suite and ensure it passes.

DELIVERABLES

PR summary (modules changed, config keys added)


Tests must pass

Now implement all changes with minimal diffs and run the full test suite.

