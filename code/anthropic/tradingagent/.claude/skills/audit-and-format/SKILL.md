---
name: audit-and-format
description: Phase F of the india-stock-recommender pipeline. Haiku phase that runs the closed-loop learning steps in strict order — F.1 Step 4.6 NSE-wide self-audit (Chartink T-0 top-25 fetch + pattern attribution + PATTERN VOTE LEDGER upvote), F.2 Step 4.5 miss audit (consumes 4.6.2's top-25, classifies vs yesterday's recommendation, generates rule-update proposals for MISS_ANALYZE), F.3 token cost report, F.4 RULES LEDGER update (upvote/downvote/status recompute), F.5 daily_recommendations.json append, F.6 Step 4.7b stockparam_final.csv (39-col superset written via Haiku sub-agent). Only phase that writes the RULES LEDGER + basestock.json anchor-registry changes. Use when the india-stock-recommender agent enters Phase F, or when the user asks to "run audit", "update rules ledger", "run miss audit", "run self-audit", "close out today's session".
allowed-tools: Read, Bash, Edit, Write, Grep, Glob, Agent, WebFetch
---

# Phase F — Audit + Format + Ledger (Haiku parent + multi-way fan-out, hard 4-min cap)

## Config load (mandatory, first action)

**Load `data/config.json` before any other work.** Chartink scan clauses, tag-collision guard rules, pattern-attribution thresholds, vote-ledger tag thresholds, miss-audit lookbacks, and ledger-update caps — all authoritative in JSON.

Sub-paths this skill reads:
- **Wall-time / fan-out**: `config.wall_time_budgets_min.phase_f` (4 min), `config.fan_out_shard_counts.phase_f_attribution_shards` (5), `.phase_f_attribution_gainers_per_shard` (5)
- **Chartink T-0 fetch**: `config.chartink.scan_clause_t0`, `.csrf_endpoint`, `.process_endpoint`, `.csrf_header_name`, `.top_n` (25)
- **Universe / liquidity**: `config.universe.eval_universe_daily_top25_size` (25), `.liquidity_gate_close_x_volume_min` (1e7)
- **F.1 tag contract**: emit rows with `tag == "t0_5pct_liq1cr"` (constant, not config — schema invariant)
- **4.6.3 Pattern attribution**: `config.phase_f.pattern_attribution.*` (lookback, coil params, RSI sweep, RM-4/7/8 params, sector breadth)
- **4.6.4 Vote ledger tags**: `config.phase_f.pattern_vote_ledger.*` (priority/high_conviction/normal/stale/cooling thresholds, L10/L30 lookbacks)
- **4.5 Miss audit**: `config.phase_f.miss_audit.correctly_picked_rank_max` (3), `.validation_case_backtest_sessions` (30), `.fp_rate_threshold_pct` (50)
- **F.4 Ledger update**: `config.phase_f.ledger_update.high_conviction_net_threshold` (8), `.review_net_threshold` (-3), `.single_run_vote_cap_magnitude` (5)
- **F.6 stockparam_final**: `config.phase_f.stockparam_final.*` (26 base cols, 39 total, sort order)

On load failure: halt, log `CONFIG_LOAD_FAILURE`, do NOT write sentinel.

Pass the loaded config to every fan-out shard (F.1, F.6, attribution shards, F.2, F.3, F.5) as read-only input. F.4 RULES LEDGER write runs in Sonnet parent (single-writer barrier) and reads config directly.

**Speed / parallelism (Jul 4 2026 expanded fan-out patch — Run #40 F.1+F.2+F.6 took 7.5 min serial):**
- Hard wall-time cap **4 min** (was 5 min) via **multi-way fan-out**:
  - **Layer 1 (t=0):** launch F.1 (Chartink T-0 fetch) ∥ F.6 (stockparam_final build) as 2 concurrent Haiku sub-agents in a single Agent tool-block. Neither depends on the other.
  - **Layer 2 (t=F.1 completes):** F.1's 4.6.3 pattern-attribution over 25 gainers fans out as **5 Haiku shards × 5 gainers each** in one tool-block.
  - **Layer 3 (t=F.1+attribution completes):** launch F.2 (Step 4.5 miss audit — consumes F.1's `phase_f1_top10.json`) ∥ F.3 (token cost aggregation — consumes phase JSONs, no F.1 dep) ∥ F.5 (`daily_recommendations.json` append — consumes `phase_e_validated.json` only) as 3 concurrent Haiku shards.
  - **Layer 4 (barrier — serialized single-writer):** F.4 RULES LEDGER edit (must be serial — single-writer to agent file), final `out/<DATE>.txt` write, sentinel.
- **Inline-in-parent (skip fan-out):** if the 25-gainer list is empty (Chartink outage → NSE fallback returned <5), run F.1's attribution inline. F.2/F.3/F.5 always parallelize if all inputs are present.

**Fan-out invariants:** F.4 RULES LEDGER edit MUST be serialized (single-writer). F.6 must complete before F.4 to allow stockparam_final rows to reflect finalized ledger state — enforce with a Layer 3 barrier before Layer 4.


**Sentinel:** `.cache/run/<DATE>/phase_f_done`
**Inputs:** `phase_e_validated.json` + `phase_c_candidates.json` + draft `out/<DATE>.txt`
**Outputs:** Final `out/<DATE>.txt` (PHASE F block with F.1/F.2/F.6 inline tables appended, then STOCK SCRIPT block, then FINAL RUN RECAP block — all after the Phase A→E blocks the validation skill wrote) + updated `pattern_notes.md` + updated RULES LEDGER in `india-stock-recommender.md` + updated `daily_recommendations.json` + appended `out/stockparam_final.csv`

## Output structure of `out/<DATE>.txt` (PHASE-WISE — matches console contract)

The validation skill (Phase E) already wrote the header + PHASE A→E blocks, each with its tables inline. This phase appends, in order:

```
━━━ PHASE F — audit-and-format · <status> ━━━
  F.1 (was "Step 4.6") — NSE-WIDE SELF-AUDIT
    4.6.2 top-25 by Close×Volume       [FULL 25-row inline table]
    4.6.3 pattern attribution           [inline notes]
    4.6.5 UGD force-adds                [inline]
  F.2 (was "Step 4.5") — POST-RUN MISS AUDIT
    histogram (CORRECTLY_EXCLUDED / NEWS_SHOCK / MISS_ANALYZE)   [inline]
    per MISS_ANALYZE detail             [inline]
  F.3 — TOKEN USAGE & COST             [inline block]
  F.6 (was "Step 4.7") — DAILY PARAMETER LOG
    STEP 4.7b — Appended N rows ...      [inline line]
  Rules re-weighted this run: <N> (internal ledger updated on disk — NOT shown)

========================================================================
STOCK SCRIPT — <DATE>          ← the LAST extra block, after PHASE F
========================================================================
  <final BUY picks entry/target/stop table>  OR  *** ZERO-PICK DAY ***
  RSI-REV recommended: <n> (<symbols>) — <disposition>
  WATCHLIST (carry) ...
  ZERO-PICK RATIONALE (if 0 picks)

========================================================================
FINAL RUN RECAP
========================================================================
  A · ...   B · ...   C · ...   D · ...   E · ...   F · ...   (last-3-lines per phase)
```

**Hard rules for this structure:**
- The old standalone `STEP 4.6 / STEP 4.5 / STEP 4.7` top-level `=====` sections are RETIRED. Their content moves INSIDE the PHASE F block as F.1 / F.2 / F.6 sub-sections with tables inline.
- STOCK SCRIPT is the **last extra block, printed AFTER the PHASE F block** (not inside any phase) — it is the headline recommendation.
- FINAL RUN RECAP is the final block after STOCK SCRIPT.
- RULES LEDGER is INTERNAL: never print the vote table; emit only the one-line "Rules re-weighted this run: N (internal)" note inside the PHASE F block.

**Tool budget:**
1. Read `phase_e_validated.json`.
2. Chartink T-0 fetch (F.1).
3. Fetch missing OHLCV for top-25 gainers not yet in `data/stockparam.csv` (compute 26-col row via Kite MCP → append; historical backfill only for symbols new to stockparam).
4. Compute miss audit + pattern attribution.
5–6. Append the F.1 (4.6) + F.2 (4.5) sub-sections INSIDE the PHASE F block of `out/<DATE>.txt` (tables inline).
7. Update `pattern_notes.md` (PATTERN VOTE LEDGER + HIT DATES only).
8. Read RULES LEDGER between markers in agent file.
9. Write updated RULES LEDGER back (ONLY writes to agent file this phase).
10. Step 4.7b Haiku sub-agent — write `out/stockparam_final.csv`.
11. Append the F.3 TOKEN USAGE + F.6 (4.7) sub-sections inside the PHASE F block; then write the standalone STOCK SCRIPT block and FINAL RUN RECAP block after it.
12. Sentinel `phase_f_done` + `daily_recommendations.json` update.

## Sub-step order (STRICT — 4.6 before 4.5 because 4.5.1 consumes 4.6.2's top-25)

### F.1 — Step 4.6 NSE-wide self-audit (runs FIRST)

**4.6.1 — Chartink T-0 fetch (no sub-agent):**
```
scan_clause=( {cash} ( latest close > 1 day ago close * 1.05 and latest close * latest volume > 10000000 ) )
```
CSRF handshake: GET `chartink.com/screener/past-2-says-5-increment` → capture `XSRF-TOKEN` cookie + `<meta csrf-token>`. POST `/screener/process` with `X-CSRF-TOKEN` only (never `X-XSRF-TOKEN` — 419). Parse `{data: [{sr, name, nsecode, bsecode, close, per_chg, volume}, ...]}`.

**Note vs Phase A.0:** A.0 already fetched **T-1** top-25 for today's universe. F.1 fetches **T-0** top-25 for TODAY's audit against yesterday's picks. Different clause, different purpose.

**Fallback:** non-200 or empty → NSE `live-analysis-variations?index=gainers` (cookie-primed). Log `CHARTINK_API_GAP`. Do NOT append fallback to `data/dailygainers.csv` (poisons series).

**4.6.1b (mandatory):** Append today's top-25 to `data/dailygainers.csv` (idempotent on `(date, symbol)`, tag `t0_5pct_liq1cr` — MANDATORY exact string; NEVER shorten to `t0_5pct` or empty). **Hard no-overwrite rule (added 2026-07-03):** F.1 rows always have `date == T-0` (today's run date). A.0 T-1 rows always have `date == T-1` with `tag == "t1_5pct_liq1cr"`. If F.1 detects an existing row with `(date == T-0, tag == "t1_5pct_liq1cr")` or `(date == T-1, tag == "t0_5pct_liq1cr")`, that is a schema violation — abort with `PHASE_F_DAILYGAINERS_TAG_COLLISION` and do NOT write. This is the guard against the Jul 3 2026 drift where F.1 silently overwrote A.0's write.

**4.6.1c — F.1 exit assertion:** after append, verify:
```python
df = pd.read_csv("data/dailygainers.csv")
assert df[(df.date == T_0_DATE) & (df.tag == "t0_5pct_liq1cr")].shape[0] >= 1, "F1_WRITE_MISSING"
assert df[df.tag.isin(["t0_5pct_liq1cr","t1_5pct_liq1cr","t0_5pct_liq1cr_nse_fallback","t1_5pct_liq1cr_nse_fallback"]).eq(False) & df.date.ge(T_1_DATE)].shape[0] == 0, "F1_UNTAGGED_ROWS_DETECTED"
```
On failure: halt Phase F, do NOT write `phase_f_done` sentinel.

**4.6.2 — Sort top 25 by Close × Volume.** Scan clause guarantees `pct_change >5.0` AND `close_x_volume >1e7` — defensively assert; flag `CHARTINK_CLAUSE_ANOMALY` and abort if violated. Output table (consumed by F.2 / Step 4.5.1):
```
Rank | Symbol | LTP | Chg% | Volume | Value(Cr) | In Anchor? | Picked?
```

**4.6.3 — Pattern attribution per top-25 mover (5-shard Haiku fan-out).** Partition the 25 gainers into 5 shards of 5 symbols each and spawn 5 Haiku sub-agents in a single Agent tool-block. Each shard filters `data/stockparam.csv` on `symbol == sym AND date >= T-30` for its 5 symbols and evaluates:

| Setup | Output |
|---|---|
| Coil within 7% of 20d high, 3 non-declining closes (1 dip ≤0.5% OK if last>first), vol ≥0.6× avg, RSI 55–72 | `RM-8 / Rule 80 PREDICTED` |
| Pre-move RSI 35→55 sweep + rising vol | `RM-3 PREDICTED` |
| RSI>50 for 30+d, dipped 5–12%, first green day vol ≥0.7× | `RM-4 / Pattern d PREDICTED` |
| Earnings/order beat in last 2 sessions + RSI <75 | `RM-7 / Pattern j PREDICTED` |
| 5+ session range coil + today range ≥1.5× avg + vol ≥1.3× | `RM-8 PREDICTED` |
| Sector breadth: ≥2 peers also up >3% same session | `Pattern SB PREDICTED` |
| Defence breakout | `Pattern h PREDICTED` |
| Step 1.5 news catalyst | `Pattern j / RM-5 PREDICTED` |
| Post-CA base | `Pattern CA-1 PREDICTED` |
| None match | `UNRECOGNIZED — candidate new pattern` |

**4.6.4 — PATTERN VOTE LEDGER update** (in `pattern_notes.md` between `<!-- ledger-start -->` / `<!-- ledger-end -->`):
1. Increment `Hits_Total`, append today's date to `## PATTERN HIT DATES`.
2. Recompute `Hits_L10` (last 10 trading sessions), `Hits_L30` (last 30). Set `Last_Hit_Date = today`.
3. Append winner+% to `Recent_Winners` (keep last 5).
4. Non-firing patterns: no hit changes.
5. Recompute tags for ALL patterns every run:

| Condition | Tag | Phase C modifier |
|---|---|---|
| Hits_L10 ≥5 | PRIORITY | Force-scan even if not flagged. Conf +3 (cap 92) |
| Hits_L10 ≥3 | HIGH_CONVICTION | Conf +2 (cap 92) |
| Hits_L10 1–2 AND Hits_L30 ≥3 | NORMAL | No modifier |
| Hits_L30 = 0 | STALE | Conf −3 on next fire. Never retire |
| Hits_L10 = 0 AND Hits_L30 1–2 | COOLING | No modifier; flag "cooling — verify" in Phase C |

**4.6.5 — Universe Gap Detection (UGD):**

| Bucket | Definition | Action |
|---|---|---|
| LEGITIMATE_EXCLUSION | Fails ≥1 Step 1 rule (b–f) | Log; no action |
| STALE_SCREENING | Now passes all rules | Force-add to `basestock.json` with `active: true, gap_added: true, source: UGD-<DATE>`. **Mandatory 60d backfill to `data/stockparam.csv`** via Kite→yfinance→NSE 3-tier (compute all 26 cols per historical session; PANAMAPET Jun 19-class blindspot) |
| THEMATIC_BLINDSPOT | Fails a rule but basket peer of universe member | Log to `pattern_notes.md → THEMATIC_GAPS`. Recurs 3+ in 10 sessions → force-add regardless |
| API_COVERAGE_GAP | Not in NSE bucket but verified via Kite | Log `NSE_API_GAP`; no action |

**4.6.5b RETIRED 2026-07-02** — superseded by Phase A.0 daily universe (writes to `data/dailygainers.csv`, not `basestock.json`).

**4.6.6 — New pattern candidates:** log UNRECOGNIZED movers to `pattern_notes.md → UNRECOGNIZED_MOVERS`. 3+ shared-signature within 30 sessions → propose new RM template (conf base 75, promote to named RM-N only after human review).

Append the complete 4.6 content as the **F.1 sub-section inside the PHASE F block** of `out/<DATE>.txt` (the full 25-row table stays inline). Do NOT emit a standalone `STEP 4.6` top-level section.

### F.2 — Step 4.5 Post-Run Miss Audit

CONSUMES 4.6.2's top-25 (already computed in F.1). Do NOT re-scan.

**4.5.1** — read top-25 from F.1, enrich with `In Universe?` (basestock membership) and `Vol/20d-Avg` (join on `data/stockparam.csv`).

**4.5.2 — Classify each ≥5% gainer vs yesterday's recommendation:**

| Bucket | Definition | Action |
|---|---|---|
| CORRECTLY_PICKED | In yesterday's main picks (rank 1-3) | ✅ hit |
| CORRECTLY_WATCHLISTED | In yesterday's watchlist with trigger that fired today | ✅ verify trigger logic |
| CORRECTLY_EXCLUDED | Rejected for documented sound reason (RSI>80, R:R<1.5, BE, news-priced-in, etc.); move today doesn't invalidate | ✅ rule worked |
| NEWS_SHOCK_UNFLAGGABLE | News-driven AND not in yesterday's Step 1.5 AND no actionable chart yesterday | ✅ external catalyst |
| MISS_ANALYZE | None of above — setup was present, not flagged/excluded for sound reason | ❗ 4.5.3 |

Ambiguous → default to MISS_ANALYZE.

**4.5.3 — Per MISS_ANALYZE:**
```
--- MISS: <SYMBOL> ---
1. PRE-MOVE SETUP: dist_20dH, range_last_5d, vol_last_3d/20d, RSI+trajectory, MA5/MA20, sector, Step 1.5 overlap
2. WHY MISSED: a. RULE GAP / b. THRESHOLD TOO STRICT / c. SCAN INCOMPLETE / d. CHART READ MISJUDGED
3. PROPOSED RULE UPDATE: rule name+step, verbatim trigger, conf base+cap, expiry, memory refs
4. VALIDATION CASE: 30-session recompute on this stock + 2 siblings; FP rate <50%
```

Recurring root-cause across runs → write feedback memory under `.claude/agent-memory-local/india-stock-recommender/` + append `MEMORY.md` pointer. Single occurrence → `pattern_notes.md` only.

If `out/<YESTERDAY>.txt` missing → log `PRIOR_RUN_NOT_FOUND` and run only 4.5.1.

**Hard rules:** never lower thresholds without 30-session FP check; never contradict a memory without naming it; run on 0-pick days; never mutate yesterday's record.

Append the complete 4.5 content as the **F.2 sub-section inside the PHASE F block** (histogram + MISS_ANALYZE detail inline). Do NOT emit a standalone `STEP 4.5` top-level section.

### F.3 — Token Cost Report

Append `=== TOKEN USAGE & COST ===` as the **F.3 sub-section inside the PHASE F block**. Tally tool calls from all phase JSONs. Format:
```
=== TOKEN USAGE & COST ===
Screener (Haiku):   X in / Y out / ₹Z
Analyzer (Opus):    X in / Y out / ₹Z
Validator (Sonnet): X in / Y out / ₹Z
Formatter (Haiku):  X in / Y out / ₹Z
TOTAL: ₹Z (~$Z USD)
```

### F.4 — RULES LEDGER Update

**Only write to agent file this phase.** Read `india-stock-recommender.md` between `<!-- rules-ledger-start -->` and `<!-- rules-ledger-end -->`. Update procedure:
1. For each CORRECTLY_EXCLUDED / CORRECTLY_PICKED outcome: identify Rule IDs that fired → Upvotes+1, recompute Net, Last_Updated=today.
2. For each MISS_ANALYZE outcome: identify blocking Rule ID → Downvotes+1, recompute Net.
3. Recompute Status per thresholds: Net ≥+8 → HIGH_CONVICTION; Net ≤−3 → REVIEW; else ACTIVE.
4. Write back the FULL updated table between markers. No other content changed.
5. Cap single-run vote shifts at ±5 per rule.

### F.5 — daily_recommendations.json update (extended schema Jul 4 2026)

Append today's validated picks as a new daily-record object to the list. Per-symbol data is stored as parallel dicts keyed by symbol (matching the existing `entry_prices` / `targets` / `patterns` shape). **New fields Jul 4 2026 for the unified scoring model + future weight learning:**

Schema (per daily record — new fields marked `NEW`):

```json
{
  "date": "YYYY-MM-DD",
  "recommendations": ["SYM1", "SYM2"],
  "entry_prices":     {"SYM1": ..., ...},
  "targets":          {"SYM1": ..., ...},
  "stop_losses":      {"SYM1": ..., ...},
  "t2_exit_date":     "YYYY-MM-DD",
  "patterns":         {"SYM1": ["RM-1","pattern_j"], ...},

  "confidence_scores":   {"SYM1": 92, ...},            // NEW — canonical final score per scoring-model
  "score_breakdowns":    {"SYM1": {...}, ...},          // NEW — full breakdown per scoring-model Section 6
  "templates":           {"SYM1": "RM-1", ...},         // NEW — canonical single template
  "rm_classifications":  {"SYM1": "MOMENTUM_CONTINUATION", ...},  // NEW
  "catalyst_tiers":      {"SYM1": "T1", ...},           // NEW — T1/T2/T3/None from Phase B
  "uptrend_states":      {"SYM1": "STRONG_UP", ...},    // NEW — Rule UT-1 output

  // Realized-outcome fields — populated later by the (future) backtest sub-agent
  // once T+exit-date has elapsed. Written as null on initial F.5 append.
  "realized_return_pcts": {"SYM1": null, ...},          // NEW — filled T+exit-date
  "hit_targets":          {"SYM1": null, ...},           // NEW — bool
  "days_to_outcomes":     {"SYM1": null, ...}            // NEW — int
}
```

**Write rules:**
- F.5 writes ALL new fields on every append. Values come from `phase_e_validated.json → validated[i]`. The three realized-outcome maps are seeded with `null` per symbol; a later backtest sub-agent fills them after the exit date.
- `patterns[sym]` continues to hold the multi-pattern list (for display + audit trails). `templates[sym]` is the single canonical scoring-model template (RM-1..12 or Pattern-K). They may overlap (`patterns[sym][0] == templates[sym]` is typical) but templates is authoritative for scoring.
- **Back-compat:** historical records (pre-Jul-4-2026) do not have the new fields. Do NOT back-migrate them. Consumers (backtest sub-agent, refit script) MUST guard on `.get("score_breakdowns", {})` and skip old records without them.
- **Idempotency:** if a record with today's `date` already exists (rerun), overwrite it in place — do NOT append a duplicate.

**Substrate for future weight learning.** Once ≥60 sessions of appends have accumulated with `realized_return_pcts` populated (~180+ realized picks), a manual `scripts/refit_scoring_weights.py` run can perform logistic regression per scoring-model Section 7 and propose new weights. Not run in this phase — schema-only landing.

Append today's validated picks to the list; save.

### F.6 — Step 4.7b Final Parameter Log (Haiku sub-agent, MODEL-PINNED)

**Model:** Haiku only. Never Opus/Sonnet → halt with `STEP_4_7B_MODEL_ERROR`. Deterministic text extraction + column merge, no reasoning.

Runs AFTER F.4 so `ut_relax_applied` and `pipeline_decision` reflect finalized ledger state.

1. Read `data/stockparam.csv` filtered `date == T-1` → load 26-col rows.
2. Read `phase_b_macro.json` for 6 macro/narrative cols:
   - `catalyst_tag` from `news_catalysts[]` (T1/T2/T3); default `NONE`.
   - `sector_tailwind` from `tailwind_signals[]`; default `NONE`.
   - 4 narrative summaries (`microtrend_disruption_summary`, `global_overnight_cues_summary`, `news_and_trends_summary`, `structural_risk_summary`) — session default + per-symbol override where named.
3. Read `phase_c_candidates.json` (`rm_classification`, `rule_80_pass`, `watchlist_state`) + `phase_d_chart.json` (`chart_read_verdict`, `failing_rule`) + `phase_e_validated.json` (`ut_relax_applied`) + final picks (`pipeline_decision`).
4. Attach 13 additional cols per symbol. Symbols past Phase A only → macro from B, pipeline cols = defaults (`rm_classification=N/A`, `watchlist_state=NOT_ON`, `chart_read_verdict=NOT_EVALUATED`, `failing_rule=N/A`, `ut_relax_applied=NONE`, `pipeline_decision=NOT_EVALUATED`).
5. Append 39-col rows to `out/stockparam_final.csv` in `(date asc, symbol asc)` order. Header only on creation. CSV-escape narrative cols per RFC 4180.
6. **Consistency invariant:** first 26 cols must match `data/stockparam.csv` byte-for-byte. Mismatch → log `STEP_4_7_INTEGRITY_WARN` to `pattern_notes.md`, skip that row's `out/` write.

Emit `STEP 4.7b — Appended N rows for {date} (total M)` as a line in the **F.6 sub-section inside the PHASE F block** of `out/<DATE>.txt`.

## Console Print Contract (parent renders after skill returns; parent also renders FINAL RUN RECAP)

Parent renders the Phase F fixed-shape block after this skill returns, using the JSON summary emitted alongside the file writes. Skill returns raw data; parent formats. **After Phase F's block, parent additionally reprints the last 3 lines of every phase's block as the FINAL RUN RECAP.**

**Skill must emit `.cache/run/<DATE>/phase_f_summary.json` (NEW file, in addition to persistent artifacts) with fields for the block:**

| Block section | JSON field | Format |
|---|---|---|
| Metrics: 4.6.2 top-25 count | `top25_count` | int |
| Metrics: force-added symbols | `force_added_symbols[]` (4.6.5b — historical only; A.0 daily universe supersedes) | list |
| Metrics: miss-audit categories | `miss_audit_histogram` — `{CORRECTLY_PICKED, CORRECTLY_EXCLUDED, MISS_ANALYZE, ...}` | dict |
| Metrics: rule-ledger vote changes | `ledger_vote_changes[]` — `{rule_id, delta_up, delta_down, new_net, new_status}` | list |
| Metrics: stockparam_final rows appended | `stockparam_final_rows_appended` | int |
| Table: FULL T-0 4.6.2 top-25 | `top25_table[]` — `{rank, symbol, ltp, chg_pct, volume, value_cr, in_anchor, picked}` | 25 rows |
| Table: miss attribution (all 25) | `miss_attribution_table[]` — `{symbol, category, rule_fired_or_missed, note}` | 25 rows |
| Table: ledger vote table | `ledger_vote_changes[]` (above) | list |
| Warnings: F.1 assertion result | `f1_assertion_result` — `"PASS"` / `"FAIL: <reason>"` | string |
| Warnings: F.6 assertion result | `f6_assertion_result` — `"PASS"` / `"FAIL: <reason>"` (integrity check on first-26-cols match) | string |
| Warnings: tag-collision guard | `tag_collision_guard_result` — `"PASS"` / `"FAIL: <reason>"` (F.1 hard no-overwrite rule) | string |

**FINAL RUN RECAP contract:** The parent, after rendering the Phase F block, ALSO reprints the last 3 lines from EACH phase's block (A, B, C, D, E, F) stacked into a single at-a-glance summary. This skill's `phase_f_summary.json` MUST additionally include a `run_recap_last_lines` field — an array of `{phase, last_lines[3]}` per phase, read from that phase's cached JSON. This is the single call the parent uses to render the recap.

```json
{
  "run_recap_last_lines": [
    {"phase": "A", "last_lines": ["eval_universe: 87", "unrepairable: 0", "A.0 assertion: PASS"]},
    {"phase": "B", "last_lines": ["...", "...", "..."]},
    ...
  ]
}
```

**Assertion-failure halt:** On F.1 tag-collision or F.6 integrity-warn, do NOT write `phase_f_done` sentinel. Emit the failing assertion in the summary JSON; parent renders RED-marker (⚠) block.

## Related

- Parent agent: `india-stock-recommender.md` (owns RULES LEDGER, sentinel resume)
- Scoring formula (F.5 persists its output): `.claude/skills/scoring-model/SKILL.md`
- Upstream: `data-prep`, `macro-scan`, `pattern-scan`, `chart-gates`, `validation`
- Persistent artifacts written: `data/dailygainers.csv` (top-25/day), `data/stockparam.csv` (already written by Phase A), `out/stockparam_final.csv` (39-col superset), `pattern_notes.md`, RULES LEDGER, `daily_recommendations.json` (with score_breakdowns for future weight learning)
- Related memories: `[[step-4-5-consumes-4-6-2]]`, `[[step-4-6-nse-wide-self-audit]]`, `[[step-4-7-daily-parameter-log]]`, `[[stockparam-two-file-architecture]]`, `[[rule-4-6-5b-unconditional-force-add]]` (retired path)
