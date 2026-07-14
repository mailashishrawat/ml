---
name: chart-gates
description: Phase D of the india-stock-recommender pipeline. Sonnet sub-agent that executes STEP 3.1 Price Action Hard Gate (no downtrend, trend change confirmed, no distribution volume, volatility floor) and STEP 3.2 Chart Read (Sub-26f climax, 46b decelerating staircase, range/volume trajectory, 26g MA5 distance, Rule 77 downtrend gate, 77c post-52wH cooldown, 78 distribution day, 79 BE segment, 46c R:R nearest_unbroken_resistance, 46d fresh-high breakout exemption). Every gate emits machine-checkable evidence JSON with `computed_values`, `threshold`, `verdict`. First FAIL short-circuits. FAIL routes to watchlist, never overridden. Use when the india-stock-recommender agent enters Phase D, or when the user asks to "run chart gates", "check chart-read gates for X", "recompute R:R", "verify 46d exemption".
allowed-tools: Read, Bash, Edit, Write, Grep, Glob, mcp__kite__get_historical_data
---

# Phase D — Chart Gates (Sonnet parent, Haiku fan-out per candidate, hard 3-min cap)

## Config load (mandatory, first action)

**Load `data/config.json` before any other work.** All chart-gate thresholds (Sub-26f climax move, 46b vol ratios, 26g MA5 distance, Rule 77/77c/78/79 gates, 46c R:R minimum, 46d 6-condition exemption) are authoritative in JSON.

Sub-paths this skill reads:
- **Wall-time / fan-out**: `config.wall_time_budgets_min.phase_d` (3 min), `config.fan_out_shard_counts.phase_d_chart_gates_per_candidate` (true), `.phase_d_shard_wall_time_sec` (90 s), `.phase_d_fan_out_threshold` (3), `config.phase_d.caching_lookback_sessions` (60)
- **3.1 Hard gates**: `config.phase_d.hard_gate_3_1.*` (downtrend lookback, reversal confirmation, distribution vol, down-days lookback)
- **3.2 Gates**: `config.phase_d.gate_sub_26f.*`, `.gate_46b.*`, `.gate_26g.*`, `.gate_77.*`, `.gate_77c.*`, `.gate_78.*`, `.gate_79.*`, `.gate_46c.*`, `.gate_46d.*`
- **Volatility floor (shared with Phase A)**: `config.screening.volatility_floor_annual_days`, `.volatility_floor_annual_window`

On load failure: halt, log `CONFIG_LOAD_FAILURE`, do NOT write sentinel.

Pass the loaded config to every per-candidate Haiku shard as read-only input.

**Speed / parallelism (Jul 4 2026 expanded fan-out patch):**
- **3-min wall-time cap** (was 5 min).
- **Haiku fan-out per candidate (MANDATORY when candidates ≥ 3):** spawn 1 Haiku sub-agent per candidate in a single Agent tool-block (`subagent_type: general-purpose`, `model: haiku`), each running the full 3.1 + 3.2 gate suite on that symbol's stockparam.csv slice. Gates are all numeric threshold checks — no reasoning, Haiku-safe. Per-shard cap 90 s.
- **≤2 candidates** → run inline in Sonnet parent (spawn overhead > win).
- **Sonnet parent** only aggregates the evidence JSONs and composes the `excluded_price_action` narrative for FAIL routes. Optional intraday Kite fetches (`interval="5minute"`) are also fanned out one-per-candidate when session is open.


**Sentinel:** `.cache/run/<DATE>/phase_d_done`
**Input:** `.cache/run/<DATE>/phase_c_candidates.json`
**Output:** `.cache/run/<DATE>/phase_d_chart.json`

**Data source:** `data/stockparam.csv` is the sole per-stock source of truth. Chart-read lookbacks are `df[(df.symbol == sym) & (df.date >= start) & (df.date <= end)]` slices. `.cache/ohlc/*.csv` retired 2026-07-02.

**Tool budget:**
1. Read Phase C output.
2. Load `data/stockparam.csv` filtered to candidates with `proceed_to_phase_d: true` + last 60 sessions each (1 pandas read).
3–5. Chart-read computation passes (one per stock) + optional up-to-3 Kite intraday fetches.
6–7. Compute all gates from stockparam.csv slices.
8. Write `phase_d_chart.json` + sentinel.

**Optional intraday read** (if session open): `mcp__kite__get_historical_data` with `interval="5minute"`, `from_date="<DATE> 09:15:00"`, `to_date="<DATE> <CURRENT_TIME>"`. Intraday data is NOT persisted to stockparam.csv (stockparam is daily-grain only). One call per candidate.

## 3.1 — Price Action Hard Gate

For each candidate, filter `data/stockparam.csv` on `symbol == sym AND date >= T-60`. Verify ALL:

- **A — No active downtrend** — no LH+LL over last 15–30 sessions. Fail: `FAIL_DOWNTREND`.
- **C — No distribution volume** — avg vol on last 5 down-days < 20d avg. Above-avg red-day vol = institutional selling. Fail: `FAIL_DISTRIBUTION_VOLUME`.

Gate B (trend change confirmed) and Gate D (volatility floor) removed — eval_universe is sourced from market movers where these are redundant.

Fail → remove; list in `excluded_price_action` with re-entry watch level (e.g. "BEL: close above Rs 436"). Excluded → watchlist only.

## 3.2 — Chart Read (Mandatory, No Exceptions)

No exceptions — including news catalysts, large-caps, Pattern S/LPI, force-includes.

### Chart-read gates (all must PASS)

| Rule | Trigger | Threshold / verdict |
|---|---|---|
| **Sub-26f** | Single session ≥`gate_sub_26f.climax_single_session_pct` (25%) then 1–2 flat/down sessions | vol <`gate_sub_26f.vol_ratio_followon_max` (0.4)× 20d avg → CLIMAX EXHAUSTION, FAIL |
| **46b** | 3+ consecutive closes with shrinking daily increment | vol <0.2× throughout → DECELERATING-STAIRCASE EXHAUSTION, FAIL |
| **Range trajectory** (last 3 closes) | EXPANDING / STEADY / COMPRESSING | Compressing after extended move → confirm vol before PASS |
| **Volume trajectory** (last 3 sessions) | RISING / FLAT / DRYING UP | Drying near target = no buyers. Exempt: conf >85% → flag, don't auto-FAIL |
| **26g (MA5 distance)** | Extended above MA5 >1.0% with cooling momentum | Revise target to nearest resistance. Exempt: RM-1 running breakout continuation, RM-11 Day-2 (log but don't FAIL) |
| **77 (downtrend, STLTECH Jun 16)** | Last 7 sessions | 3+ consecutive LOWER intraday highs after 20d-peak AND 2+ lower intraday lows AND close < peak_close → CONFIRMED DOWNTREND, FAIL. Watchlist trigger requires structural reversal (HH+HL pair + close above prior peak on ≥1.0× vol), not just a price level |
| **77c (post-52wH cooldown, SCHNEIDER Jun 30)** | Recent peak = fresh 52wH AND peak_close ≥3% below intraday high | Require **3 stabilization sessions** before RM-4 qualifies. Stabilization = trading session (holidays/circuit-days don't count) AND close within ±2.0% of T-1 AND range <2× 20d avg range AND vol <1.5× 20d avg. V-bounce (+5%+) or capitulation (−3%−) does NOT qualify. Emit `session_classifications[]`. |
| **78 (distribution day, STLTECH Jun 16)** | Peak day closed ≥5% below intraday high on vol ≥1.5× | BLOW-OFF/DISTRIBUTION. Cooldown ≥10 sessions OR new closing high above dist-day high on vol ≥1.5× |
| **79 (BE segment)** | `series: "BE"` OR `-BE` suffix | Auto-block from picks + morning-alerts. Delivery-only, ≥T+5 |
| **46c (R:R, HARD GATE)** | `nearest_unbroken_resistance` algorithm (below) | `(target_for_rr − entry) / (entry − stop) ≥ gate_46c.rr_minimum_threshold` (1.2; uptrend floor `rr_minimum_threshold_uptrend` = 1.1) else FAIL |
| **46d (fresh-high breakout exemption)** | ALL 6 conditions (below) | Replace resistance with `measured_move_target = 14wH + (14wH − base_low)` (or `measured_move_base_extension_pct` = 6% extension floor if base <`base_amplitude_min_pct` = 8%) |

### `nearest_unbroken_resistance` algorithm

Filter `data/stockparam.csv` on `symbol == sym AND date >= T-config.phase_d.gate_46c.nearest_unbroken_resistance_lookback_sessions` (60). Candidates: (a) 52wH (max of `high` col over last `gate_46c.fifty_two_week_high_lookback_sessions` = 252 sessions); (b) prior swing highs where intraday `high` was followed within `gate_46c.resistance_prior_fail_within_sessions` (3) sessions by `close ≥ gate_46c.resistance_prior_fail_close_below_pct` (3%) below (failed peaks); (c) round-number levels (multiples of `gate_46c.resistance_round_number_multiples` = [50,100,500] within ±`gate_46c.resistance_round_number_window_pct` = 5% of current). Filter to candidates **above** current price. **Broken** = subsequent close ≥`gate_46c.resistance_broken_close_pct` (1.0%) above on `vol_ratio_20d ≥ gate_46c.resistance_broken_vol_ratio` (1.5); otherwise unbroken. `nearest_unbroken_resistance` = lowest unbroken candidate. If proposed target > this, auto-revise target down to it for R:R (optimistic target may appear as narrative "stretch target"). Emit `nearest_unbroken_resistance` + `resistance_source`. **All numeric thresholds authoritative in `config.phase_d.gate_46c` — never hard-code.**

### Rule 46d — 6-condition fresh-high breakout exemption

**Fresh-high basis = 14-week high (~70 sessions), lowered from 52wH on 2026-07-14 (user).** The 14-week high (`14wH` = max of `high` col over last `config.phase_d.gate_46d.fresh_high_lookback_sessions` = 70 sessions) is NOT valid resistance when a stock is breaking out to a fresh 14-week high on catalyst volume. All 6 must hold on entry candle T-1:

1. T-1 close within `close_to_fresh_high_max_pct` (1.5%) of the **14-week high** (or above).
2. T-1 volume ≥1.5× 20d median.
3. T-1 intraday reversal <2% (i.e. close near high).
4. Pattern ∈ {RM-1 running breakout, RM-11 Day-2, WPR-P1 FIRED this session}.
5. Active T1/T2 catalyst via macro-scan NEWS-CAT (structural policy / regulatory / group-level — NOT generic sector).
6. Rules 77, 77c, 78, 79, sub-26f, 46b ALL PASS.

When ALL 6 hold: `measured_move_target = 14wH + (14wH − base_low)` where `base_low` = min of `close` col in 20 sessions PRIOR to breakout leg (= last session where price crossed above base mid-point). If base amplitude <8%, fall back to `14wH * 1.06` (6% extension floor). Emit `rule_46d_exemption_active: true`, `fresh_high_basis: "14week"`, `measured_move_target`, `base_low`, `base_amplitude_pct`. R:R computed against `measured_move_target` (not the 14wH).

**IMPORTANT — this is a loosening.** A 14-week-high breakout can still sit below unbroken supply from 4–12 months ago. 46d only exempts the *stock breaking a 14wH*; for every non-46d candidate, Rule 46c's `nearest_unbroken_resistance` (60-session lookback) is unchanged and still finds that older resistance. So the R:R discipline is not removed globally — it is bypassed only for genuine 14wH breakouts meeting all 6 conditions.

Guardrail: 46d never overrides 77c, and **77c's post-52wH cooldown remains 52wH-based** (downside gates are never relaxed). If 77c requires stabilization sessions and they're not met, 46d does not fire.

### Output — machine-checkable evidence JSON (mandatory)

Prose verdicts are **not accepted**. Every gate emits `computed_values` with actual arrays/numbers from OHLCV.

```json
{
  "stock": "SCHNEIDER",
  "step_3_2_verdict": "FAIL",
  "failing_rule": "77c",
  "gates": [
    {"rule_id": "Sub-26f", "computed_values": {"max_single_session_pct": 8.86, "vol_ratio_followon": 2.24}, "threshold": "single >10% AND followon vol <0.4x", "verdict": "PASS"},
    {"rule_id": "77", "computed_values": {"peak_date": "2026-06-24", "peak_high": 1468.7, "post_peak_highs": [1399.0, 1468.8], "post_peak_lows": [1331.1, 1320.0], "lower_high_count": 1, "lower_low_count": 2, "current_close": 1453.6, "peak_close": 1373.9}, "threshold": "3+ LH AND 2+ LL AND close < peak_close", "verdict": "PASS (LH<3)"},
    {"rule_id": "77c", "computed_values": {"fresh_52wH_date": "2026-06-24", "stabilization_sessions": 0, "session_classifications": [{"date":"2026-06-25","pct":-2.81,"range_vs_avg":1.18,"stabilization":false},{"date":"2026-06-29","pct":+8.86,"range_vs_avg":2.41,"stabilization":false}]}, "threshold": "≥3 stabilization sessions", "verdict": "FAIL — 0 of 3"},
    {"rule_id": "46c", "computed_values": {"proposed_entry": 1453.6, "nearest_unbroken_resistance": 1468.7, "resistance_source": "2026-06-24 intraday high (failed peak)", "revised_target": 1468.7, "stop": 1380, "rr": 0.20}, "threshold": 1.5, "verdict": "FAIL — R:R 0.20 < 1.5"}
  ]
}
```

**Evidence rules:**
- Every gate: `computed_values` = actual arrays/numbers, not summary phrases.
- `verdict` derivable from `computed_values + threshold` by any later reader.
- If `lower_high_count: 0` contradicts `post_peak_highs` array, entire run fails audit.
- First FAIL short-circuits: record as `failing_rule`, stop evaluating (but still emit remaining gate array).
- ANY gate FAIL → `step_3_2_verdict: FAIL` → route to watchlist. Never overridden by confidence, catalyst strength, etc.

Plus a one-paragraph honest read referencing the failing rule's `computed_values` directly.

## `phase_d_chart.json` schema

```json
{
  "run_date": "YYYY-MM-DD",
  "stocks_evaluated": 3,
  "failure_reason_histogram": {"FAIL_77c": 1, "FAIL_46c": 0},
  "chart_results": [{
    "symbol": "HFCL",
    "step31_pass": true, "step31_fail_reason": null,
    "chart_read_pass": true,
    "chart_read_notes": "Range expanding, vol flat, MA5 within 0.8%, target Rs230 cleared by single resistance",
    "intraday_read": "Step-up tape, zero red bars, vol 3.2x opening pace — supports entry",
    "rule77_fired": false, "rule78_fired": false, "rule79_fired": false,
    "sub26f_fired": false, "rule46b_fired": false,
    "nearest_unbroken_resistance": 230.0, "resistance_source": "2026-05-14 failed peak",
    "rule_46d_exemption_active": false, "measured_move_target": null, "base_low": null, "base_amplitude_pct": null,
    "revised_target": 230.0, "revised_stop": 185.0, "rr_ratio": 2.46,
    "gates": [...],
    "proceed_to_phase_e": true
  }],
  "excluded_price_action": [
    {"symbol": "TARIL", "fail_reason": "FAIL_DOWNTREND", "reentry_trigger": "close above Rs618 + higher-low confirmation"}
  ]
}
```

## Console Print Contract (parent renders after skill returns)

Parent renders a fixed-shape summary block after this skill returns, using the JSON below. Skill returns raw data; parent formats.

**Fields required in `phase_d_chart.json` for the block:**

| Block section | JSON field | Format |
|---|---|---|
| Metrics: candidates_in | `stocks_evaluated` | int |
| Metrics: pass count | count of `chart_results[?proceed_to_phase_e==true]` | int |
| Metrics: fail count | count of `chart_results[?proceed_to_phase_e==false]` + `excluded_price_action` (len) | int |
| Metrics: primary failure reasons | `failure_reason_histogram` — `{"FAIL_77c": 1, "FAIL_46c": 2, ...}` (add — NEW) | dict |
| Table: per-candidate per-rule verdict | `chart_results[].gates[]` — each `{rule_id, computed_values, threshold, verdict}`; parent renders one row per (candidate, rule) with failing rules highlighted | nested array |
| Warnings: 46d exemption details | `chart_results[?rule_46d_exemption_active==true].{symbol, measured_move_target, base_low, base_amplitude_pct}` (add these fields to the top-level of `chart_results[]` for easy scan — NEW) | list |
| Warnings: R:R against nearest_unbroken_resistance | `chart_results[].{symbol, nearest_unbroken_resistance, resistance_source, rr_ratio}` — surface where `rr_ratio < 1.5` (add fields — NEW) | list |

**On sentinel-resume:** parent reads `phase_d_chart.json` and renders `(cached)` block. JSON must be self-sufficient for reprinting.

## Related

- Parent agent: `india-stock-recommender.md`
- Upstream: `pattern-scan` (reads `phase_c_candidates.json` filtered to `proceed_to_phase_d: true`)
- Downstream: `validation` (independent chart re-run + news/US market checks)
- Related memories: `[[schneider-jun30-chart-read-fix]]`, `[[stltech-jun16-downtrend-miss]]`, `[[rule-46d-breakout-to-fresh-high-exemption]]`, `[[mandatory-chart-read-and-90-percent-threshold]]`
