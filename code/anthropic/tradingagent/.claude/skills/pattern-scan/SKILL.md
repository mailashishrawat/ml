---
name: pattern-scan
description: Phase C of the india-stock-recommender pipeline. Sonnet sub-agent that runs Recent Movers Scan on the eval_universe (identifies momentum-continuation vs news-priced-in vs low-conviction moves), executes mandatory Watchlist Persistence & Framing Audit (Rule 82 GOCOLORS-class silent-drop fix), performs Pattern Recognition against RM-1 through RM-12 templates, applies Rule UT-1 uptrend classification and UT-RELAX-1..5 relaxations, evaluates the full pattern catalog (a–k, MC), applies Phase B modifiers (hard_excludes, catalysts, tailwinds) and RULES LEDGER confidence modifiers. Produces `phase_c_candidates.json` with stocks scoring >85 (proceed to Phase D) and 78–85 (watchlist). Use when the india-stock-recommender agent enters Phase C, or when the user asks to "run pattern scan", "check RM templates", "audit watchlist", "classify recent movers".
allowed-tools: Read, Bash, Edit, Write, Grep, Glob, WebFetch
---

# Phase C — Pattern Scan (Sonnet parent, Haiku shard fan-out — hard 6-min cap)

## Config load (mandatory, first action)

**Load `data/config.json` before any other work.** Every RM template base, pattern boost, RSI cap, vol ratio, pullback threshold, UT-1/UT-RELAX parameter, and Rule 80/82 threshold in this file is authoritative in `data/config.json`. Numbers inline below are illustrative documentation.

Sub-paths this skill reads (heavily used — this is the most config-dense phase):
- **Wall-time / fan-out**: `config.wall_time_budgets_min.phase_c` (6 min), `config.fan_out_shard_counts.phase_c_pattern_scan_shards` (6), `.phase_c_pattern_scan_shard_wall_time_sec` (90 s), `config.phase_c.eval_universe_fan_out_threshold` (20), `.max_proposed_candidates` (5), `.caching_lookback_sessions` (60)
- **2.1 Recent movers**: `config.phase_c.recent_movers_threshold_pct` (5), `.recent_movers_lookback_sessions` (5), `.recent_movers_consecutive_sessions_threshold` (2), `.recent_mover_classification.*` (momentum_vol_ratio_min, momentum_rsi_max, news_priced_in_vol_ratio_min, news_priced_in_single_move_pct, news_priced_in_rsi_min, low_conviction_vol_ratio_max, momentum_climax_single_move_pct)
- **2.3 RM templates**: `config.phase_c.template_base_conf.{RM-1..12, Pattern-K}`, `config.phase_c.template_cap.*`, and per-template gates `config.phase_c.rm1.*` through `.rm12.*` plus `.pattern_k.*`
- **2.3b Rule RSI-REV**: `config.phase_c.rsi_reversion.*` — `basket` (43 symbols), `entry_mode` (cross_up_through_50), `buy_rsi_cross` (50), `sell_rsi_min` (65), `reject_gates`, `base_conf`, `conf_cap`, `tier`
- **UT-1 uptrend detector**: `config.phase_c.ut1.*` (lookback, pivot windows, HH/HL thresholds, MA slope, sideways proximity)
- **UT-RELAX 1..5**: `config.phase_c.ut_relax.gating_states`, `.relax_1.*`, `.relax_2.*`, `.relax_3.*`, `.relax_4.*`, `.relax_5.*`
- **Rule 80 pre-breakout**: `config.phase_c.rule80.*`
- **Rule 82 watchlist**: `config.phase_c.rule82_watchlist.*`
- **Scoring model** (delegated to `scoring-model` skill): `config.scoring.*` — pattern boosts, macro boosts, ledger boosts, penalties, NDP floor, publish thresholds, template caps

On load failure: halt, log `CONFIG_LOAD_FAILURE`, do NOT write sentinel.

Pass the loaded config dict to every Haiku shard as read-only input.

**Speed / parallelism (Jul 4 2026 expanded fan-out patch — Run #40 baseline 31 min → target ≤6 min):**
- Wall-time cap **6 min** (was 8 min). On exceed → kill remaining shards, mark unfinished symbols `SCAN_INCOMPLETE`, continue with partial results.
- **Haiku shard fan-out (mandatory when eval_universe > 20):** partition eval_universe into 6 shards of ≤15 symbols each; each Haiku shard runs 2.1 recent-movers classification + 2.3 RM-1..12 template match + UT-1 detection + UT-RELAX evaluation and emits its shard's candidate JSON. Rules 2.1/2.3/UT-1 are numeric threshold checks — deterministic, no reasoning, Haiku-safe. Launch all 6 shards in a single Agent tool-block. Per-shard cap 90 s.
- **Sonnet parent** only handles: 2.2 watchlist audit (session-critical, mandatory table with narrative — never sharded, cross-symbol view for Rule 82), Phase B modifier merging, `conf_modifier_applied` snap, final narrative composition for candidates with `conf > 85`, and `pattern_notes.md` updates.
- **Inline-in-parent skip (eval_universe ≤ 20):** run all templates inline; shard spawn overhead exceeds win.
- **Watchlist audit is NEVER sharded** — must run as a single pass in the Sonnet parent (rule 82 framing reset requires cross-symbol view).


**Sentinel:** `.cache/run/<DATE>/phase_c_done`
**Inputs:** `.cache/run/<DATE>/phase_a_context.json` + `.cache/run/<DATE>/phase_b_macro.json`
**Output:** `.cache/run/<DATE>/phase_c_candidates.json`

## Scoring (unified — see `scoring-model` skill)

**All confidence scores in this phase are computed via the unified formula in `.claude/skills/scoring-model/SKILL.md`.** Never invent a total by narrative addition. Every candidate emits `confidence_score` (int) AND `score_breakdown` (JSON per Section 6 of scoring-model). Numeric boosts shown in the tables below (Sections 2.1, 2.3, 2.4, "Phase B modifiers", "RULES LEDGER modifiers") are the **weight-table entries** — the formula consumes them; it does NOT sum them by hand across categories. Each category contributes at most one term via `max()` (per scoring-model Section 3); penalties stack via sum.

Each Haiku shard, after classifying a symbol, populates the `evidence` dict (Section 1 of scoring-model), calls the reference `compute_confidence(evidence)` inline, and emits `(confidence_score, score_breakdown)`. Sonnet parent verifies invariants: `pattern_base + recent_mover + pattern_boost + macro_boost + ledger_boost + penalty == breakdown.raw`; `final == min(cap, max(floor, raw))`. Any shard result violating these invariants is rejected with `SCORE_BREAKDOWN_INTEGRITY_FAIL`.

**Stock list:** Union of Phase A `pre_filter[*].symbol` + Phase B `news_catalysts[*].symbol` where `force_add_to_phase_c: true`, minus Phase B `hard_excludes`. Expected ≤20 stocks.

**Data source:** `data/stockparam.csv` is the sole per-stock source of truth. All lookbacks are `df[(df.symbol == sym) & (df.date >= start) & (df.date <= end)]` slices, NOT raw OHLC file reads (`.cache/ohlc/*.csv` retired 2026-07-02).

**Tool budget:**
1–2. Read Phase A + Phase B JSONs.
3. Load `data/stockparam.csv` filtered to eval_universe symbols + last 60 sessions (single pandas read).
4. **Haiku shard fan-out** — spawn 6 Haiku sub-agents (`subagent_type: general-purpose`, `model: haiku`, ≤15 symbols each) running 2.1 + 2.3 + UT-1 + UT-RELAX in parallel. Each shard receives the stockparam.csv slice for its symbols + phase_b_macro.json (hard_excludes, catalysts, tailwinds) and returns `{shard_id, candidates: [...], recent_movers_table: [...]}`. Fan-out itself = 1 tool call from parent budget. Skip fan-out when eval_universe ≤ 20 — run inline.
5. Watchlist Persistence & Framing Audit (2.2) — Sonnet parent, single pass over prior-run watchlist symbols (never sharded).
6. Merge shard results, apply Phase B modifiers, apply RULES LEDGER conf modifiers, compose narrative reasons for `conf > 85` candidates.
7. Write `phase_c_candidates.json`.
8. Update `pattern_notes.md` (missed-move log).
9. Write sentinel `phase_c_done`.

Return ≤5 stocks conf >85 (78–85 → watchlist candidates, not pipeline picks).

**STOCKS CARRIED FORWARD line (mandatory in console output):**
```
STOCKS CARRIED FORWARD (C -> D):  IN: 146 -> OUT: 4  (KAYNES, SYRMA, SCI, MCX)
  See disposition summary above for full 146-stock breakdown.
```
The disposition summary MUST be printed before this line so the reader can reconcile 146 → 4 without apparent mismatch.

**Mandatory pre-picks retrospective:** find stocks that moved +8%+ in last 2 sessions NOT in prior recommendations; for each: identify present signals (RSI/vol/sector news/breakout/earnings/defense order/state-visit MoU), the blocking rule, log "MISSED MOVE" to `pattern_notes.md`.

## 2.1 — Recent Movers Scan (mandatory)

Filter `data/stockparam.csv` on `symbol IN eval_universe AND date >= T-5`. Identify ≥5% (close-to-close `pct_change`) movers in EITHER of last 2 sessions. Classify:

| Bucket | Trigger | Action |
|---|---|---|
| MOMENTUM_CONTINUATION | Vol ≥1.5× 20d avg AND RSI <75 AND no +10% single-bar climax | Force to pattern analysis, Pattern MC +20 conf base. Enter on continuation, do NOT wait for pullback |
| NEWS_PRICED_IN | Vol ≥3× 20d avg OR single-session +8%+ OR RSI >80 | −10 conf; `news_priced_in: true`; watchlist w/ pullback trigger (2–3 sessions) |
| LOW_CONVICTION_MOVE | Vol <1.0× 20d avg (thin) | Ignore. Note in output. |

Emit table `RECENT MOVERS: Symbol | Session | Move% | Vol/Avg | RSI | Classification | Action` BEFORE main picks.

## 2.2 — Watchlist Persistence & Framing Audit (MANDATORY, GOCOLORS-class fix)

Every prior-run watchlist symbol MUST appear in this session's `WATCHLIST_AUDIT` table. Silent drops = pipeline error → `watchlist_audit_pass: false`, formatter surfaces `WATCHLIST DROP ERROR — investigate before publishing`.

Load last 20 sessions from `data/stockparam.csv` per prior watchlist item (`symbol == w AND date >= T-20`), emit:
```
WATCHLIST_AUDIT: Symbol | Original_Zone | Zone_State | Sessions_Carried | Sessions_Above_Zone_High | Sessions_Below_Zone_Low | Trigger_State | Action
```

- **Zone_State**: `IN_ZONE` / `ABOVE` / `BELOW` relative to zone_low..zone_high.
- **Trigger_State**: `WAITING` / `FIRED` (→ chart-gates) / `RUNAWAY` (Rule 82) / `EXPIRED_STOP` / `EXPIRED_TIME` (Sessions_Carried ≥10) / `POST_STOP_REENTRY` (Rule 81).
- **Action**: `CARRY` / `PROMOTE_TO_STEP_2_7` / `FRAME_RESET` / `EXPIRE`.

**Rule 82 — Framing Reset (RUNAWAY handling):** If `Sessions_Above_Zone_High ≥ 5` AND each of those 5 closes was strictly above the prior-session intraday high (`each_close_gt_prior_intraday_high: true`), reclassify from pullback-entry to **RM-1 running breakout continuation**:
- `base_low` = min(20-session-prior lowest close, original zone_high)
- `entry` = T-1 close or pullback to MA5 within 1.5%
- `stop` = max(MA20, 5-session swing low)
- `target` = `latest_close + (latest_close − base_low)` (1× measured move) OR next unbroken resistance, whichever closer
- Route recomputed candidate to Step 2.3 → chart-gates. FRAME_RESET does NOT auto-qualify — must still clear chart read on recomputed levels.

Evidence per stock: `{original_watchlist_zone, sessions_above_zone_high, closes_above_zone_high, each_close_gt_prior_intraday_high, recomputed_entry, recomputed_stop, recomputed_target, target_source, rr, action}`.

If `each_close_gt_prior_intraday_high: false` → keep as `CARRY` (sideways drift, no reset).

## 2.3 — Recent Mover Pattern Recognition (after 2.1)

For EVERY ≥5% mover (2 sessions), read stockparam.csv slice `symbol == sym AND date >= T-60` (single filter per symbol). Compute from those rows: 20d/50d/52w highs (`.high.rolling(20/50/252).max()`), distance to resistance/support (% and ATR from `atr_14` col), 5-session vol profile via `vol_ratio_20d`, RSI trajectory last 7 sessions from `rsi_wilder_14` col (35→55 sweep? 55–70 grind? 75+ exhaustion?), `ma5`/`ma20` distance from their cols, prior 3–5 sessions coil vs pullback (range trajectory from `high - low`), sector-index correlation (external), Step 1.5 catalyst overlap (from `phase_b_macro.json`).

Map to ONE template:

| Template | Signature | Conf | Action |
|---|---|---|---|
| **RM-1: Breakout Day 1** | Close > 20d/50d/52w high on vol ≥1.5×, RSI 55–72, range expanding, MA5 <5% below | 88 | Entry on next dip to breakout (no chase) |
| **RM-2: Breakout Day 2** | Day after RM-1, vol ≥0.8×, no distribution, holding above breakout | 90 | Entry today |
| **RM-3: Support Test + Hold** | Pullback into breakout zone or 5/20MA, intraday low taps support, close green/flat, vol <0.8× | 91 | Entry today (GOCOLORS Jun 1 template) |
| **RM-4: Pattern D Dip Recovery** | Was RSI>50 for 30+d, dipped 5–12%, first green day vol ≥0.7×, RSI 45–58 | 89 | Entry today (PARAS Jun 3 template) |
| **RM-5: News Gap & Go** | Step 1.5 NEWS_CATALYST, vol ≥2×, RSI 50–72, sector aligned | 87 | Entry on 1–2d digestion if RSI <75 |
| **RM-6: Sector Rotation Lag** | Peer/leader at new highs, this stock laggard, vol ≥0.8× | 86 | Immediate entry |
| **RM-7: Earnings/Order Beat** | Move tied to earnings/order in last 2 sessions, RSI <75, no climax | 88 | Entry today if no +10% climax; else wait |
| **RM-8: Coiling Breakout** | 5+ session range-bound coil w/ declining vol, today range ≥1.5×, vol ≥1.3× | 87 | Entry today |
| **RM-9: Failed (REJECT)** | RSI >80 OR single +10% climax w/ no follow-through OR distribution vol on up day | — | Do NOT propose; watchlist w/ explicit re-entry trigger |
| **RM-10: Unrecognized** | Fits no template | — | Log to `pattern_notes.md` as candidate new pattern |
| **RM-11: Consec Catalyst Continuation** | Two CONSECUTIVE ≥8% sessions + vol ≥2× on BOTH + RSI <85 + no intraday dist wick (close in upper 40% both). RSI cap: Day-1 vol ≥10× → cap 85; Day-1 vol 2–10× → cap 78. Overrides NEWS_PRICED_IN. NIACL Jun 18–19 validated. | 90 | Entry today on 1–2% dip |
| **RM-12: Continuation Pullback in Uptrend** | Rule UT-1 `∈ {STRONG_UP, UP}` + 5–18% pullback from 20d high + close within 4% below rising MA20 + recovery close > prior intraday high + vol ≥0.8× median + RSI 35–72 + Rules 77/78/26f/46c-or-46d PASS. ATHER/GOCOLORS/ADANIENT archetypes. Aggressive-tier; ~35–40% FP rate accepted, chart-gates R:R is safety net. | 78 base | Entry today. Cap 85 (no cat) / 87 (T2) / 88 (T1) |

Route all propose-templates (RM-1..8, 11, 12) to chart-gates. Chart-gates R:R ≥`config.phase_d.gate_46c.rr_minimum_threshold` (1.2; uptrend 1.1) + >85% conf gates apply. Step 2.3 only ensures the candidate is seen.

## 2.3b — Rule RSI-REV: RSI Mean-Reversion Buy (43-stock basket, 2026-07-10)

**Runs for EVERY eval_universe symbol that is in `config.phase_c.rsi_reversion.basket` — independent of the ≥5% recent-mover filter** (a basket stock at RSI 48 with no recent move still fires this). This is the user-requested rule of 2026-07-10.

For each basket symbol, read its latest TWO stockparam.csv rows (current + prior session):
1. **Trigger (CROSS-UP through 50, `entry_mode: cross_up_through_50`):** if `prev_session.rsi_wilder_14 ≤ config.phase_c.rsi_reversion.buy_rsi_cross` (50) **AND** `current_session.rsi_wilder_14 > 50` → RSI just crossed up through 50 (the bounce is starting) → the symbol is **ALWAYS added to `candidates[]`** with `pattern: "RSI-REV"`, `tier: "aggressive_watchlist"`, `base_conf: 78` (cap 85). **A basket stock that has been sitting below 50 for days does NOT trigger** — only the single session RSI first pokes back above 50 fires it. A stock still ≤50 today does NOT trigger. **When a symbol triggers, adding it is unconditional** so the user can see it flow through.
2. **Reject-gate pass (can only REJECT, never upgrade):** evaluate `config.phase_c.rsi_reversion.reject_gates` against the same slice:
   - `rule_77_confirmed_downtrend` (3+LH ∧ 2+LL, UT-RELAX-4 threshold if in uptrend) → REJECT reason `RSI-REV_REJECT_DOWNTREND`
   - `ut1_state_DOWN` (Rule UT-1 == DOWN) → REJECT reason `RSI-REV_REJECT_UT1_DOWN`
   - `rule_26f_one_bar_climax` → REJECT `RSI-REV_REJECT_CLIMAX`
   - `rule_78_distribution_day` → REJECT `RSI-REV_REJECT_DISTRIBUTION`
   - `rule_79_BE_segment` → REJECT `RSI-REV_REJECT_BE`
   If any gate fires: set `proceed_to_phase_d: false`, `rsi_rev_verdict: "REJECTED"`, populate `reject_reason`. The candidate STILL APPEARS in the output and in the STOCKS CARRIED FORWARD table with its reject reason — **never silently dropped** (agent §1b-STOCKS). If all gates PASS: `proceed_to_phase_d: true`, `rsi_rev_verdict: "BUY"`.
   - **REVERSAL_PENDING carry (`config.phase_c.rsi_reversion.reversal_pending_watchlist`, 2026-07-13 user-requested):** a cross-up-through-50 rejected **only** by a *trend-not-yet-confirmed* gate — `reject_reason ∈ {RSI-REV_REJECT_DOWNTREND, RSI-REV_REJECT_UT1_DOWN}` (i.e. gate ∈ `reversal_pending_watchlist.trigger_gates`) — has already turned its RSI up; it is blocked purely because the trend has not confirmed. Do NOT drop it: set `watchlist_status: "REVERSAL_PENDING"`, `sessions_carried: 1` (or prior +1 if already carried), and **add it to `watchlist_candidates[]`** so it reaches the published WATCHLIST with a machine-checkable re-entry trigger (`Rule 77 clears — LH/LL below threshold — OR UT-1 flips to SIDEWAYS/UP, AND RSI still > 50`). Auto-drop when `sessions_carried > reversal_pending_watchlist.max_sessions_carried` (3) OR RSI closes back below `reversal_pending_watchlist.drop_rsi` (45) — the bounce failed. **Structural rejects — `RSI-REV_REJECT_CLIMAX / _DISTRIBUTION / _BE` — are NOT carried** (those signal the bounce itself is unsafe, not merely unconfirmed); they stay in the disposition table only.
3. **Estimated target (RSI≥65 exit):** compute the approximate close at which `rsi_wilder_14` would reach `sell_rsi_min` (65). Estimate via the price gain needed to lift the 14-period Wilder RSI from current to 65 (use recent avg up/down moves from the slice, or an ATR-14 proxy). Report as `target_est` with `target_basis: "rsi65_estimate"` — flag it an estimate, not a hard resistance level. Entry = latest close; stop = min(MA5, recent swing low) or −8% floor, whichever tighter.
4. **Evidence:** emit `rsi_rev: {rsi14, prev_rsi14, entry_mode: "cross_up_through_50", buy_cross: 50, sell_target_rsi: 65, ut1_state, rule77_verdict, target_est, gates: [{gate, verdict}]}`.

**Emit an RSI-REV table** before main picks: `Symbol | RSI-14 | UT1 | Rule77 | Verdict(BUY/REJECTED) | Reject Reason | Watchlist(—/REVERSAL_PENDING) | Entry | Target_est | proceed_to_D`. List every basket symbol that triggered RSI≤50, whether BUY or REJECTED. Trend-only rejects show `REVERSAL_PENDING` in the Watchlist column and MUST also appear in `watchlist_candidates[]`.

**Caveat (carry into rationale):** RSI-REV is REVIEW-status — its cross-up backtest win-rate (95.4%, 35-of-43 names perfect over 1yr; `config.phase_c.rsi_reversion._backtest_crossup`) is a bull-year + selection-bias artifact (basket chosen because it won in-sample). It is an aggressive-watchlist signal capped at 85, does not auto-publish above cap, and must clear chart-gates like any other candidate.

Emit `RECENT MOVER PROPOSALS: Symbol | Move% (2d) | Template | Pattern Logic | Entry | Stop | Target | R:R | Conf | Proposed?` BEFORE main picks.

## Rule UT-1 — Uptrend State Detector

For each stock, filter `data/stockparam.csv` on `symbol == sym AND date >= T-60`. The `ut1_state`, `hh_count`, `hl_count`, `ma20_slope_pct` cols are **already pre-computed** in stockparam.csv rows — read the latest row directly. If a stock's latest row is stale (should not happen post-Phase A cache repair), fall back to on-demand recompute:

- **Pivots**: window 7 (high/low > 3 sessions before AND 3 after) — from `high` / `low` cols in the 60-session slice.
- **HH count**: pivot highs strictly > immediately-prior pivot high.
- **HL count**: symmetric on pivot lows.
- **MAs**: read `ma20`, `ma50`, `ma200` from the latest row (already computed).

Classify (first match wins):

| State | Condition |
|---|---|
| STRONG_UP | HH ≥3 AND HL ≥3 AND MA20 > MA50 > MA200 AND close > MA50 AND MA20 slope (10 sess) > 0 |
| UP | HH ≥2 AND HL ≥2 AND MA20 > MA50 AND close > MA50 |
| SIDEWAYS | Neither UP nor DOWN; MA20 within ±2% of MA50 |
| DOWN | LH ≥3 AND LL ≥3 AND MA20 < MA50 AND close < MA50 |

Emit `uptrend_state, hh_count, hl_count, ma20, ma50, ma200, ma20_slope_pct` per stock. RM-12 requires `∈ {STRONG_UP, UP}`; else fall through to RM-4 or RM-9.

RM-12 conf formula: base 78 +5 (STRONG_UP) +3/+2/0 (T1/T2/none catalyst) +2 (recovery vol ≥1.2× median) −5 (pullback >12%). Cap 85/87/88 (no/T2/T1).

RM-12 hard gates (all PASS required): UT-1 STRONG_UP or UP; pullback depth 5–18%; close > MA20 −4%; recovery close > prior intraday high; recovery vol ≥0.8× 20d median; RSI 35–72; Rule 77, 78, sub-26f, 46c/d PASS; R:R ≥ `config.phase_d.gate_46c.rr_minimum_threshold_uptrend` (1.1, uptrend by definition).

Emit `rm12_gates[]` with `computed_values, threshold, verdict` per gate.

## Rule UT-RELAX — Uptrend Relaxations (Jul 1 2026, empirically calibrated)

**Gating condition:** fire ONLY when `uptrend_state ∈ {STRONG_UP, UP}`. DOWN/SIDEWAYS → standard rules, no relaxation. Basis: 97% of pipeline misses May 21–Jul 1 were in an uptrend (89/92).

- **Relax-1 (R:R floor)** — standard `ut_relax.relax_1.rr_floor_standard` (1.2) → **`rr_floor_relaxed` (1.1)** when uptrend AND recovery vol ≥1.2× median. (Both lowered 2026-07-14: 1.5→1.2 standard, 1.2→1.1 uptrend.)
- **Relax-2 (RSI ceiling)** — STRONG_UP + MA20 slope ≥+0.5% + T-1 vol ≥1.5×: standard cap 80 → **84**; RM-1/RM-11 cap 85 → **87** (only when T-1 vol ≥3× median). RSI 80–84 no longer auto-FAIL; proceeds to chart-gates. If all other gates PASS but RSI in 80–84, capped at conf 84 (watchlist, not main pick unless ≥85%).
- **Relax-3 (26e recency)** — Tier-A default 8/64 → **6/64** when uptrend AND ≥15/20 closes above MA50. Annual 40/252 unchanged. Tiers B/C unchanged.
- **Relax-4 (Rule 77 downtrend gate)** — 3+LH ∧ 2+LL threshold → **4+LH ∧ 3+LL** in uptrend. Narrows to genuine reversals, not retracements.
- **Relax-5 (publish threshold)** — strictly >85 → **≥84** when STRONG_UP + all chart-gates PASS + T1/T2 catalyst.

**Never relaxed even in STRONG_UP** (pattern-break detectors, not trend metrics): Rule 78 (distribution day), 77c (post-52wH cooldown), sub-26f (climax), 79 (BE segment), 46b (decelerating staircase), 82 framing hardening, annual 40/252 vol floor.

Evidence: every stock with a relaxation applied emits `ut_relax_applied: [Relax-N]` with `uptrend_state`, `computed_values` (ma20_slope_pct, vol_ratio, closes_above_ma50_count, hh_count, hl_count), pre-relaxation vs post-relaxation verdicts. Ledger downvotes each Relax-N per stopped-out post-relax pick; if aggregate downvotes exceed upvotes over 30 sessions, that Relax-N reverts to pre-Jul-1 standard automatically.

## 2.4 — Pattern catalog

**Scoring note.** The numeric boosts in this table are **weight-table entries** consumed by the `scoring-model` formula (see top of this file for the "Scoring" section). They are NOT summed by hand — the formula applies `max()` within the pattern-boost category (per scoring-model Section 3), so a stock matching Pattern g + Pattern j + Pattern h gets only the highest single boost, not the sum. Every shard populates the `evidence` dict and calls `compute_confidence()`.

| ID | Name | Signature |
|---|---|---|
| a | Duopoly | `duopoly_pairs.json` — if one peer rose but other hasn't, flag lag as BUY |
| b | RSI ceiling | Never recommend RSI >75 (exception: Pattern h breakout + gov order + RSI <85) |
| c | RSI recovery | Crossed RSI 45 from below RSI 30 within last 2 days |
| d | Strong-stock dip | RSI>50 for 30+d, dipped, recovering above RSI 45 (institutional strength) |
| e | Product-launch excitement | Recent launch + genuine consumer buzz; validate with news |
| f | Trending sector | EV, Solar, Green Energy, AI infra, Semis, Space Tech |
| g | FII accumulation | 3+ consec Q rise → +5; 4+ Q → +10; FII+promoter stable → +15 |
| h | Breakout + defense order | Break 52w/6m high on vol ≥1.5×; defense order +20 conf. Universe: APOLLO MICRO, MTAR, ZEN TECH, ASTRA MICROWAVE, PARAS DEFENCE, SIKA INTERPLANT, BHARAT DYNAMICS, CENTUM ELECTRONICS |
| i | Self-discovered | Document in `pattern_notes.md` with accuracy score |
| j | News catalyst | Listed in Step 1.5 NEWS CATALYSTS. Boosts: single +15, breakout+vol1.5× +25, state-visit partnership +25, healthy RSI 40–65 +20. If moved >8% on news → `news_priced_in: true`, halve boost. RSI exception up to 80 |
| k | Pattern S — IPO/post-listing reversal | 6–24m listed, +20% from IPO then 8–20% correction over 6–10 sessions, down-day vol below avg, RSI 38–50, reclaims 5MA, recovery vol ≥1.0×, no negative news 30d. Base 72, cap 80 (88 w/ LPI). **LPI (+8):** 4+ Q of loss improvement + revenue growing + first profitable Q within 3 Q. Universe: named force-includes |
| MC | Momentum continuation | MOMENTUM_CONTINUATION from 2.1. Higher HH/LL, no distribution, RSI <75, vol ≥1.5× on move. +20 conf base. Enter on continuation, no pullback wait. HFCL May 22 validated |

**Self-discovered:** repeated RM-10 with follow-through → propose new RM template, track in `pattern_notes.md` with accuracy score before promotion.

## Phase B modifiers to confidence

**All entries here are `evidence` dict inputs to the scoring-model formula, NOT hand-summed to `confidence_score`.**

- `hard_excludes` → remove before any analysis (not a scoring input; a filter)
- `caution_flags` → `evidence.caution_flag = true` → −15 (Section 2f penalty)
- `tailwind_signals` → `evidence.tailwind_conf_boost = +10 or +15` (Section 2d macro category, max with AI_TAILWIND)
- `ai_disruption_status == "AI_TAILWIND"` AND stock ∈ IT hard-list → `evidence.ai_tailwind_applies_to_it = true` → +15 (Section 2d, max with tailwind_conf_boost)
- `ai_disruption_status == "AI_DISRUPTION_RISK"` → gates IT stock inclusion (filter, not score)
- `gold_caution` → informational flag; no scoring input
- `us_market_status` → informational flag; no scoring input

## RULES LEDGER confidence modifiers (from Phase A `rules_ledger_snapshot`)

**All entries here are `evidence` dict inputs to the scoring-model formula, NOT hand-added to `confidence_score`.**

- Any Rule ID fired for this candidate has Status = PRIORITY → `evidence.has_priority_rule = true` → +3 (Section 2e)
- Any Rule ID fired has Status = HIGH_CONVICTION → `evidence.has_high_conviction_rule = true` → +2
- Any Rule ID fired has Status = STALE → `evidence.has_stale_rule = true` → −3
- These three ledger flags are combined via `max()` (strongest single signal wins) — see scoring-model Section 3.

Log the fired Rule IDs and their ledger status in `signals_fired[]` (Section 6 of scoring-model) so the audit trail is preserved. Example: `"ledger:HIGH_CONVICTION:46d"`.

## Output JSON

```json
[{
  "symbol": "SYMBOL", "company_name": "Name",
  "template": "RM-1",
  "patterns_matched": ["RM-1","pattern_j","pattern_mc"],
  "rm_classification": "MOMENTUM_CONTINUATION",
  "catalyst_tier": "T1",
  "uptrend_state": "STRONG_UP",
  "rsi": 48.2, "fii_holding_trend": [7.2,8.1,9.4,10.8], "fii_consecutive_quarters_increasing": 4,
  "news_catalyst": null, "news_catalyst_source": null, "news_priced_in": false,
  "recent_mover": true,
  "recent_move_pct": 6.3, "recent_move_volume_vs_avg": 2.1,
  "confidence_score": 92,
  "score_breakdown": {
    "template": "RM-1",
    "pattern_base": 88,
    "recent_mover": 20,
    "pattern_boost": 15,
    "macro_boost": 10,
    "ledger_boost": 2,
    "penalty": 0,
    "raw": 135,
    "cap_applied": 92,
    "floor_applied": 88,
    "final": 92,
    "signals_fired": ["template:RM-1","rm_class:MOMENTUM_CONTINUATION","pattern_j_single_catalyst","tailwind:EV_POLICY:+10","ledger:HIGH_CONVICTION:46d"]
  },
  "reason": "...",
  "proceed_to_phase_d": true,
  "conf_modifier_applied": "+2 (Pattern h HIGH_CONVICTION)"
}]
```

**Fields added Jul 4 2026 for unified scoring:** `template` (canonical single pattern template — RM-1..12 or Pattern-K); `rm_classification` (from Section 2.1); `catalyst_tier` (T1/T2/T3/None from Phase B); `uptrend_state` (from Rule UT-1); `score_breakdown` (mandatory — every candidate MUST emit the full breakdown per scoring-model Section 6). See `.claude/skills/scoring-model/SKILL.md` for the formula.


Top-level fields: `candidates: [...]` (array above), `watchlist_candidates: []` (stocks scoring 78–85, for watchlist output), `stocks_scanned: N`, `watchlist_audit_pass: bool`, `recent_movers_table: []` (all ≥5% movers from 2.1), `watchlist_audit_table: []` (all prior watchlist symbols per Rule 82 — no truncation), `rm10_misses: []`, `universe_gaps: []`, `watchlist_drop_errors: []` (only when `watchlist_audit_pass: false`).

Update `pattern_notes.md` after picks.

## Console Print Contract (parent renders after skill returns)

Parent renders a fixed-shape summary block after this skill returns, using the JSON below. Skill returns raw data; parent formats.

**Fields required in `phase_c_candidates.json` for the block:**

| Block section | JSON field | Format |
|---|---|---|
| Metrics: eval_universe scanned | `stocks_scanned` | int |
| Metrics: proceed_to_phase_d count | count of `candidates[?proceed_to_phase_d==true]` | int |
| Metrics: watchlist_candidates count | `watchlist_candidates` (len) | int |
| Metrics: watchlist_audit_pass | `watchlist_audit_pass` | bool |
| **Disposition summary** | `disposition_summary` | object (see below) |
| Table: 2.1 RECENT MOVERS (ALL ≥5% movers, no truncation) | `recent_movers_table[]` — rows `{symbol, session, move_pct, vol_vs_avg, rsi, classification, action}` (top-level array — NEW top-level export from shard aggregation) | array |
| Table: Watchlist audit (ALL prior symbols, Rule 82) | `watchlist_audit_table[]` — rows `{symbol, original_zone, zone_state, sessions_carried, sessions_above_zone_high, sessions_below_zone_low, trigger_state, action}` (top-level — NEW) | array |
| Table: Main candidates + templates + one-line rationale | `candidates[]` filtered `proceed_to_phase_d==true` | array |
| Warnings: RM-10 misses | `rm10_misses[]` (add — NEW) | list |
| Warnings: universe gaps | `universe_gaps[]` (add — NEW) | list |
| Warnings: silent-drop errors | If `watchlist_audit_pass==false` → emit `watchlist_drop_errors[]` | list |

**Disposition summary (mandatory — closes the stock-count gap):**

Every stock in `eval_universe` must appear in exactly one bucket. Sum of all buckets must equal `stocks_scanned`. Emit as `disposition_summary` object AND render as a printed block in the Phase C console output immediately after the metrics line:

```
C · STOCK DISPOSITION (146 in → 146 accounted)
  rsi_rev_triggered    :  19  (2 BUY → D, 17 rejected)
  rm12_triggered       :   2  (2 → D)
  wpr_carries          :   4  (0 fired, 4 carry)
  recent_movers_no_tmpl:   8  (≥5% move, no template match — logged RM-10)
  no_signal            : 113  (scanned, no template threshold cleared)
  ─────────────────────────────
  total                : 146  ✓
```

JSON shape:
```json
"disposition_summary": {
  "total": 146,
  "rsi_rev_triggered": {"count": 19, "buy": 2, "rejected": 17},
  "rm12_triggered": {"count": 2, "proceed_to_d": 2},
  "wpr_carries": {"count": 4, "fired": 0, "carry": 4},
  "other_templates_triggered": {"count": 0, "by_template": {}},
  "recent_movers_no_template": {"count": 8},
  "no_signal": {"count": 113},
  "checksum_ok": true
}
```

`checksum_ok` = true when `rsi_rev_triggered.count + rm12_triggered.count + wpr_carries.count + other_templates_triggered.count + recent_movers_no_template.count + no_signal.count == total`. If false → emit `DISPOSITION_CHECKSUM_FAIL` warning before publishing.

**On sentinel-resume:** parent reads `phase_c_candidates.json` and renders `(cached)` block from these arrays — skill JSON must be self-sufficient for reprinting.

## Related

- Parent agent: `india-stock-recommender.md`
- Scoring formula (MANDATORY reference): `.claude/skills/scoring-model/SKILL.md` — every `confidence_score` in this phase MUST be computed via `compute_confidence(evidence)` and MUST emit `score_breakdown`
- Upstream: `data-prep`, `macro-scan`
- Downstream: `chart-gates` (reads `phase_c_candidates.json` filtered to `proceed_to_phase_d: true`)
- Related memories: `[[watchlist-persistence-rule]]`, `[[watchlist-runaway-audit-fix]]`, `[[uptrend-relaxations-empirical]]`, `[[rm12-continuation-pullback]]`, `[[feedback-pre-breakout-scanner-rule-80]]`
