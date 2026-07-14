---
name: validation
description: Phase E of the india-stock-recommender pipeline. Sonnet sub-agent that runs cross-validation (negative news last 7d, US market status, industry trend, AI disruption/tailwind, gold check) and INDEPENDENTLY re-derives every chart-gate `computed_values` from raw OHLCV — must NOT read chart-gates prose. If validator's `nearest_unbroken_resistance` or Rule 46d evaluation differs from chart-gates → `chart_conflict: true`, default to FAIL (SCHNEIDER Jun 30 origin). Emits `phase_e_validated.json` and writes draft `out/<DATE>.txt` as phase-wise blocks (PHASE A→E, tables inline in each block; PHASE F + STOCK SCRIPT + FINAL RUN RECAP appended later by audit-and-format). Use when the india-stock-recommender agent enters Phase E, or when the user asks to "run validation", "double-check chart read for X", "verify final_recommendation gate".
allowed-tools: Read, Bash, Edit, Write, Grep, Glob, WebSearch, WebFetch
---

# Phase E — Validation + Draft Output (Sonnet parent + per-candidate Haiku fan-out, hard 2-min cap)

## Config load (mandatory, first action)

**Load `data/config.json` before any other work.** Publish thresholds, AI hard-exclude list, gold caution move, exit-date calendar, negative-news lookback — all authoritative in JSON.

Sub-paths this skill reads:
- **Wall-time / fan-out**: `config.wall_time_budgets_min.phase_e` (2 min), `config.fan_out_shard_counts.phase_e_validation_per_candidate` (true), `.phase_e_shard_wall_time_sec` (90 s), `.phase_e_fan_out_threshold` (2)
- **Publish thresholds** (mirrored from scoring-model): `config.phase_e.publish_threshold_standard` (85), `.publish_threshold_ut_relax_5` (84), `.watchlist_conf_min` (78), `.watchlist_conf_max` (85), `.reject_threshold` (78), `.max_final_picks` (3)
- **3.3.a Negative news**: `config.phase_e.check_3_3_a_negative_news_lookback_days` (7)
- **3.3.d AI disruption gate**: `config.phase_e.check_3_3_d_ai_hard_exclude_list` (IT ticker list)
- **3.3.e Gold caution**: `config.phase_e.check_3_3_e_gold_caution_move_pct_5d` (2)
- **3.3.f Chart re-run**: `config.phase_e.check_3_3_f_chart_validation_lookback_sessions` (10)
- **Exit-date rules**: `config.phase_e.exit_date_default_trading_days` (2), `.nse_holidays_2026` (list)

On load failure: halt, log `CONFIG_LOAD_FAILURE`, do NOT write sentinel.

Pass the loaded config to every per-candidate Haiku shard as read-only input.

**Speed / parallelism (Jul 4 2026 expanded fan-out patch):**
- Hard wall-time cap **2 min** (was 3 min).
- **Per-candidate Haiku fan-out:** when Phase D emits ≥2 candidates with `proceed_to_phase_e: true`, spawn 1 Haiku sub-agent per candidate in a single Agent tool-block. Each shard runs all 5 cross-validation checks (a–e) + the independent chart re-run (f) on its symbol, returning a `validated[i]` JSON entry. Sonnet parent aggregates + composes the draft output.
- **Checks 3.3.b (US market), 3.3.d (AI disruption), 3.3.e (gold)** are session-level (read from `phase_b_macro.json` — no per-candidate work). Sonnet parent handles these once and passes the resolved flags to each shard as read-only inputs — shards do NOT re-fetch macro.
- **Checks 3.3.a (negative news, per-symbol) + 3.3.c (industry trend, per-sector) + 3.3.f (chart re-run, per-symbol)** are per-candidate — these are what each Haiku shard runs.
- **Inline-in-parent (skip fan-out):** ≤1 candidate → run inline. Shard spawn overhead exceeds parallel win at that size.
- **Independent-recompute invariant preserved:** each shard MUST re-derive gate `computed_values` from raw OHLCV in `data/stockparam.csv` — must NOT read `phase_d_chart.json` prose. Sonnet parent flags `chart_conflict: true` on any per-shard vs Phase D verdict divergence.

**Sentinel:** `.cache/run/<DATE>/phase_e_done`
**Inputs:** `.cache/run/<DATE>/phase_b_macro.json` + `.cache/run/<DATE>/phase_d_chart.json`
**Outputs:** `.cache/run/<DATE>/phase_e_validated.json` + draft `out/<DATE>.txt` (phase-wise blocks PHASE A→E, tables inline; Phase F block + STOCK SCRIPT appended later by audit-and-format)

## Scoring pass-through (unified — see `scoring-model` skill)

**Phase E does NOT recompute confidence.** Each candidate's `confidence_score` and `score_breakdown` were computed by Phase C via the `scoring-model` formula. This phase reads them through Phase D's output (Phase D preserves them; chart-gate FAILs simply route to watchlist without touching the score). Validation:

- Reads `confidence_score` + `score_breakdown` from `phase_d_chart.json → chart_results[i]` (which inherited from `phase_c_candidates.json`).
- Emits both fields unchanged in `phase_e_validated.json → validated[i]`.
- **Applies publish threshold** per `scoring-model` Section 5:
  - Standard: `confidence_score > 85` → main pick candidate
  - UT-RELAX-5: `confidence_score ≥ 84` when `uptrend_state == STRONG_UP AND all_chart_gates_pass AND catalyst_tier in {T1, T2}`
  - Watchlist: `78 ≤ confidence_score ≤ 85`
- Any per-candidate confidence recomputation is forbidden — if evidence changed (e.g. Phase B refetch surfaces a new caution_flag), the fix is to re-run Phase C, not to patch the score here.


**Tool budget:**
1. Read Phase B output (resolve session-level flags: `us_market_status`, `ai_disruption_status`, `gold_caution`).
2. Read Phase D output (candidate list + prior gate verdicts — used ONLY for `chart_conflict` comparison, never as source of `computed_values`).
3. **Fan out N Haiku shards** (one per Phase D candidate with `proceed_to_phase_e: true`), single Agent tool-block. Each shard runs 3.3.a/c/f in-shard; fan-out = 1 tool call from parent budget. Skip when ≤1 candidate. **Per-shard cap 90 s.**
4. Parent aggregates shard JSONs, applies session-level flags (b/d/e from step 1), computes `chart_conflict` per candidate, writes `phase_e_validated.json`.
5. Write draft `out/<DATE>.txt` + sentinel `phase_e_done`.

**Per-shard prompt template (Haiku):**
```
Symbol: <SYMBOL>
Phase D verdict: <verdict summary — for chart_conflict comparison only, NOT for reading computed_values>
data/stockparam.csv slice (last 10 sessions raw OHLC): <slice>

Tasks:
1. Web-search for negative news about <SYMBOL> in the last 7d (SEBI/CCI/fraud/mgmt change/earnings miss/legal). Return negative_news bool + reason.
2. Assess industry trend for <SYMBOL>'s sector: is it "fading" (declining revenues, regulatory headwind, obsolescence)? Return industry_trend {growing|stable|fading}.
3. Independently re-derive every chart-gate computed_values from the raw OHLC slice above. Compute: nearest_unbroken_resistance, Rule 46d 6-condition status, R:R ratio. Compare to Phase D verdict — if disagreement, set chart_conflict: true, default to FAIL.

Return JSON: {"symbol": "<SYMBOL>", "negative_news": bool, "negative_news_reason": str|null, "industry_trend": str, "chart_validation_pass": bool, "chart_validation_notes": str, "chart_conflict": bool, "recomputed_rr": float, "recomputed_target": float, "recomputed_stop": float}
Cap 90 s.
```

## 3.3 — Cross-validation checks (per stock with `proceed_to_phase_e: true`)

- **a. Negative news (last 7d)** — SEBI/CCI, fraud, mgmt change, earnings miss, legal → `final_recommendation: false`.
- **b. US market** — read Phase B `us_market_status` — no new fetch. If negative → `US_MARKET_CAUTION` flag (not exclusion unless combined with other negatives).
- **c. Industry trend** — "fading" (declining revenues, regulatory headwind, obsolescence) → `final_recommendation: false`.
- **d. AI disruption / tailwind** — read Phase B `ai_disruption_status` — no new fetch. If `AI_TAILWIND` active (current: Jensen Huang Jun 2026), remove disruption flag. If `AI_DISRUPTION_RISK` active, hard-exclude IT: TCS, INFOSYS, WIPRO, HCLTECH, LTIMINDTREE, COFORGE, MPHASIS, KPIT, MASTEK, HEXAWARE, PERSISTENT.
- **e. Gold check** — read Phase B `gold_caution` — no new fetch. If >+2% in 5d → `GOLD_CAUTION` flag on all picks.
- **f. Chart validation (INDEPENDENT re-run of Phase D)** — filter `data/stockparam.csv` on `symbol == sym AND date >= T-10`. Independently re-derive every gate's `computed_values` from raw OHLC cols (`open`, `high`, `low`, `close`, `volume`) — NOT from the derived indicator cols that Phase D also read (avoid inheriting Phase D's shape). **MUST NOT read Phase D's prose or output.** If validator's `nearest_unbroken_resistance` or Rule 46d evaluation differs from Phase D → flag `chart_conflict: true`, default to FAIL. SCHNEIDER Jun 30 origin: validator inherited "PASS" framing instead of recomputing from raw OHLC.

`final_recommendation: true` requires ALL of: no negative news, industry not fading, no AI disruption risk, `chart_validation_pass: true`, `chart_conflict: false` (or resolved to FAIL).

## Draft `out/<DATE>.txt` — PHASE-WISE blocks (PHASE A → E), tables inline in each block

**The file mirrors the console contract exactly: one block per phase (A→F), and WITHIN each phase, rule-wise / data tables printed INLINE inside that block.** No section/step layout. Phase E writes blocks A→E; Phase F (audit-and-format) appends the PHASE F block + the standalone STOCK SCRIPT + FINAL RUN RECAP.

Header + Phases A–E are written here. Each phase block is delimited by a `━━━` rule and carries its full data table inline (never a bare count, never deferred to an appendix). Structure:

```
========================================================================
INDIA STOCK RECOMMENDER — DAILY OUTPUT — <DATE> (session <SESSION>)
Reporting format: phase-wise A->F + inline per-rule/data tables (ledger internal)
========================================================================

━━━ PHASE A — data-prep · <status> ━━━
  <eval_universe, backfill, A.0 assertion, source split>
  STOCKS CARRIED FORWARD (A -> B):  IN: n -> OUT: m   [+ one-word drop reasons]

━━━ PHASE B — macro-scan · <status> ━━━
  HARD_EXCLUDES / CAUTION / TAILWINDS / NEWS_CATALYSTS counts + AI_TAILWIND flag
  MACRO TREND & DISRUPTION ALERT  ← paste Phase B `trend_alert_report` verbatim (was "Section 1")
  STOCKS CARRIED FORWARD (B -> C):  IN: n -> OUT: m

━━━ PHASE C — pattern-scan · <status> ━━━
  eval_universe scanned / proceed_to_D / watchlist / watchlist_audit_pass
  --- PER-RULE STOCK OUTPUT ---  (one INLINE sub-table per rule that fired)
    > RULE RSI-REV — <triggered> -> <buy>/<rejected>    [full inline table: Symbol|RSI14|UT1|Rule77|Verdict|Reason|Entry|Target|EstGain]
       => RSI-REV recommended: <n> (<symbols>)
    > RULE RM-12 / RM-x — <n> triggered -> <n> proceed_to_D    [full inline table]
    > RULE 80 / WPR — <carries> -> <fired>, <silent drops>   [full inline table]
  STOCKS CARRIED FORWARD (C -> D):  IN: n -> OUT: m   [+ drop reasons]

━━━ PHASE D — chart-gates · <status> ━━━
  candidates_in / PASS / FAIL (+ fail histogram)
  [full inline table: Symbol|Verdict|Fail reason]
  STOCKS CARRIED FORWARD (D -> E):  IN: n -> OUT: m

━━━ PHASE E — validation · <status> ━━━
  final picks / publish threshold / UT-RELAX flag / ZERO-PICK marker if 0
  TRADE PARAMETERS  (final_recommendation==true only, conf strictly >85, max 3)   [inline table]
  PER-STOCK DETAIL  (screening ✅/❌, patterns, validation, P/E, RSI, close, vol, mktcap, gain%, 10-day sparkline)   [inline per pick]
  WATCHLIST  (Phase C 78–85 conf + Phase D excluded_price_action + RSI-REV REVERSAL_PENDING carries, each w/ machine-readable re-entry trigger)   [inline table]
  STOCKS CARRIED FORWARD (E -> F):  <picks> picks; <n> watchlist carried
```

**Content mapping from the old section layout (content unchanged, only relocated):**
- Old *Section 1 (Trend Alert Report)* → PHASE B block, "MACRO TREND & DISRUPTION ALERT" (paste `trend_alert_report` verbatim).
- Old *Section 2 (Trade Parameters Table)* → PHASE E block, "TRADE PARAMETERS" inline table.
- Old *Section 3 (Per-stock details)* → PHASE E block, "PER-STOCK DETAIL" inline.
- Old *Section 4 (Watchlist)* → PHASE E block, "WATCHLIST" inline table.
- Old *Section 5 (token cost placeholder)* → removed here; Phase F emits it inside the PHASE F block.

**Phase A/C/D block content:** Phase E does NOT recompute A/C/D metrics — read them from `phase_a_*.json` / `phase_c_candidates.json` / `phase_d_chart.json` and render each phase's block (with its inline table) verbatim from those JSONs, so the draft is a faithful phase-wise trace even though this skill runs at Phase E. If a prior-phase JSON is missing, render that block as `(cached — see console)` rather than omitting it.

**Trade-params rules (unchanged):**
- **UT-RELAX-5:** publish threshold relaxes to ≥84 when STRONG_UP + all chart-gates PASS + T1/T2 catalyst.
- **Never reduce position size** — remove marginal picks entirely.
- **0-pick day is expected on most days.** Do not pad. Do not lower confidence to fit. On a 0-pick day the PHASE E block shows `*** ZERO-PICK DAY ***` and the TRADE PARAMETERS table reads "(no rows — nothing cleared Phase D)".
- 85% threshold applies universally (standard, large-cap trending, Pattern O, all combinations). Event-driven notes surface as watchlist only if below 85%.

```
Rank │ Symbol │  Entry  │  Target  │  Stop   │ Conf │ Exit Date
─────┼────────┼─────────┼──────────┼─────────┼──────┼──────────
 1   │ SYM1   │ ₹XXX.XX │ ₹XXX.XX  │ ₹XXX.XX │  XX% │ YYYY-MM-DD
```

### Exit-date rules

Default T+2 trading days. Never Saturday, Sunday, or NSE holiday. NSE 2026 holidays: Jan 26, Feb 19, Mar 14, Apr 1, Apr 10, Apr 14, Apr 18, May 1, Aug 15, Aug 27, Oct 2, Oct 20, Oct 21, Nov 5, Dec 25. Roll forward to next valid trading day if T+2 falls on a holiday.

## `phase_e_validated.json` schema

```json
{
  "run_date": "YYYY-MM-DD",
  "validated": [{
    "symbol": "UNOMINDA",
    "template": "RM-1",
    "rm_classification": "MOMENTUM_CONTINUATION",
    "catalyst_tier": "T1",
    "uptrend_state": "STRONG_UP",
    "negative_news": false, "negative_news_reason": null,
    "us_market_status": "positive", "industry_trend": "growing",
    "ai_disruption_risk": false, "gold_caution": false,
    "chart_validation_pass": true, "chart_validation_notes": "…",
    "chart_conflict": false,
    "final_recommendation": true, "confidence_score": 90,
    "score_breakdown": {
      "template": "RM-1",
      "pattern_base": 88, "recent_mover": 20, "pattern_boost": 15,
      "macro_boost": 10, "ledger_boost": 2, "penalty": 0,
      "raw": 135, "cap_applied": 92, "floor_applied": 88, "final": 92,
      "signals_fired": ["template:RM-1","rm_class:MOMENTUM_CONTINUATION","pattern_j_single_catalyst","tailwind:EV_POLICY:+10","ledger:HIGH_CONVICTION:46d"]
    },
    "entry": 1148.0, "target": 1280.0, "stop": 1063.0, "rr_ratio": 1.55,
    "exit_date": "2026-06-27", "rank": 1,
    "one_line_rationale": "RM-1 breakout + T1 EV catalyst, R:R 1.55, 3-day exit",
    "ut_relax_applied": []
  }],
  "final_picks_count": 1,
  "confidence_range": {"min": 90, "max": 90},
  "publish_threshold_applied": 85,
  "zero_pick_rationale": null,
  "watchlist_count": 4,
  "draft_output_written": true
}
```

**Fields added Jul 4 2026 for unified scoring pass-through:** `template`, `rm_classification`, `catalyst_tier`, `uptrend_state`, `score_breakdown` — all read from `phase_d_chart.json` (which inherited them from `phase_c_candidates.json`) and passed through unchanged. Validation NEVER mutates `score_breakdown`.

## Console Print Contract (parent renders after skill returns)

Parent renders a fixed-shape summary block after this skill returns, using the JSON below. Skill returns raw data; parent formats.

**Fields required in `phase_e_validated.json` for the block:**

| Block section | JSON field | Format |
|---|---|---|
| Metrics: final picks proposed | `final_picks_count` | int |
| Metrics: confidence range | `confidence_range` — `{min, max}` (add — NEW) | dict |
| Metrics: publish threshold applied | `publish_threshold_applied` — `85` or `84` (UT-RELAX-5) (add — NEW) | int |
| Table: FINAL PICKS (or zero-pick day rationale) | `validated[?final_recommendation==true]` — `{symbol, entry, stop, target, rr_ratio, confidence_score, one_line_rationale}` (add `one_line_rationale` — NEW) | list |
| Warnings: zero-pick day rationale | If `final_picks_count == 0` → emit `zero_pick_rationale` string (add — NEW) | string |
| Warnings: UT-RELAX flags | `validated[].ut_relax_applied` — surface non-empty values (add — NEW) | list |

**On sentinel-resume:** parent reads `phase_e_validated.json` and renders `(cached)` block. JSON must be self-sufficient for reprinting.

## Related

- Parent agent: `india-stock-recommender.md`
- Scoring formula (referenced for publish threshold + pass-through): `.claude/skills/scoring-model/SKILL.md`
- Upstream: `chart-gates` (reads `phase_d_chart.json`), `macro-scan` (reads `phase_b_macro.json`)
- Downstream: `audit-and-format` (Phase F) — persists `score_breakdown` + template + rm_classification + catalyst_tier to `daily_recommendations.json`
- Related memories: `[[schneider-jun30-chart-read-fix]]`, `[[feedback_ai_tailwind_it_stocks]]`, `[[mandatory-chart-read-and-90-percent-threshold]]`
