---
name: top-gainer-introspect
description: Introspect the india-stock-recommender prediction model against NSE's top 10 daily gainers (sorted by Volume × Last Close). For each gainer, decide whether the agent's existing patterns/rules would have predicted it. Upvote rules/patterns that did, downvote those that didn't, and apply the resulting rule changes to the agent definition file. Use when the user asks to "analyse top gainers", "verify the prediction model", "audit pattern accuracy against today's gainers", or invokes /top-gainer-introspect directly.
argument-hint: "[YYYY-MM-DD] (optional — defaults to last NSE trading day)"
allowed-tools: Read, Bash, Edit, Write, Grep, Glob, WebFetch
---

# Top Gainer Introspect

Audit the india-stock-recommender's prediction model against the NSE-wide top 10 gainers (>5%, sorted by Value Traded = LTP × Volume). For each gainer, classify whether existing patterns/rules predicted it. Upvote winning patterns, downvote losing/silent patterns, and apply rule changes to the agent file.

The output is a single report appended to `out/<DATE>-introspect.txt` AND a set of edits to `.claude/agents/india-stock-recommender.md`, `pattern_notes.md`, and the agent's memory directory. **No new picks** are emitted — this skill is purely retrospective.

## Inputs

- `$ARGUMENTS[0]` (optional): target date `YYYY-MM-DD`. If absent, use the most recent file in `out/` matching `YYYY-MM-DD.txt` and use that date's gainers (or fall back to the latest trading session if data is fresh).
- Working directory: must be `/Users/I038849/Documents/Ashish/github.com/mailashishrawat/ml/code/anthropic/tradingagent/` (the trading agent project root).
- Agent definition: `.claude/agents/india-stock-recommender.md`
- Ledger: `pattern_notes.md` between `<!-- ledger-start -->` / `<!-- ledger-end -->`
- Memory dir: `.claude/agent-memory-local/india-stock-recommender/`

## Procedure

### 1. Resolve target date and prior run

- Parse `$ARGUMENTS[0]` if given; otherwise pick the most recent `out/YYYY-MM-DD.txt`.
- Read that run output to extract: existing top-10 gainers table (Step 4.6.2), pattern attribution (Step 4.6.3), the recommendations made, and the watchlist.
- If no prior run output exists for the date, fetch the gainers fresh — see step 2.

### 2. Fetch NSE top 10 (if not in prior run)

If the prior run already produced the table, reuse it. Otherwise fetch via the NSE public API per the agent's Step 4.6.1 instructions (cookie-priming + `live-analysis-variations?index=gainers`). On API failure, fall back to yfinance batch fetch over the basestock universe + the well-known mid/small-cap names from `pattern_notes.md`.

Sort by `value_cr = ltp × volume / 1e7`, filter `pct_change > 5.0`, cap top 10.

### 3. Pattern-prediction validation (per gainer)

For each top-10 gainer, fetch 60 days of OHLCV (yfinance, `<SYM>.NS`) and compute:

- Wilder RSI (14-period) — **MANDATORY use** `ewm(alpha=1/14, adjust=False)`, NOT `rolling(14).mean()`. See Rule RSI-1.
  ```python
  delta = closes.diff()
  gain = delta.clip(lower=0)
  loss = (-delta).clip(lower=0)
  avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
  avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
  rsi = 100 - (100 / (1 + avg_gain / avg_loss))
  ```
- 20d avg volume, vol/avg ratio for the move day and prior day
- Distance from MA5 / MA20 / 20d high / 52w high
- 2-day, 5-day cumulative move
- Range close position (close − low) / (high − low) for last 2 sessions
- Pre-move setup signature: coiling / pullback / fresh-leg

Then classify the move against the agent's pattern catalog (a–k, MC, RM-1 through RM-11, h, S, O, Pattern j/SB/CA-1, Rule 80). Use the table in Step 4.6.3 of the agent file as the matching key. Each gainer goes into one of:

| Bucket | Definition |
|---|---|
| `PREDICTED_AND_PICKED` | Pattern fired AND the run actually issued a pick or fired-watchlist trigger |
| `PREDICTED_BUT_GATED` | Pattern fired but Step 2.7 / 3.1 gates correctly blocked it (e.g., RSI ceiling, R:R fail, BE-segment) |
| `PREDICTED_BUT_MISSED` | Pattern fired and gates passed — but the run did not issue the pick. Pipeline failure. |
| `UNPREDICTED_BUT_PREDICTABLE` | No existing pattern fired but a clear pre-move setup is visible in retrospect (e.g., basket member outside universe, news-catalyst not scanned). Rule gap. |
| `UNPREDICTED_AND_UNPREDICTABLE` | News shock / corporate action / extreme-vol anomaly that no rule could reasonably catch. Document, don't blame. |
| `LEGITIMATE_EXCLUSION` | Stock fails Step 1 screening rules genuinely (volatility floor, micro-cap, penny). Do not propose changes. |

### 4. Catalyst check (mandatory for ambiguous classifications)

For any gainer in `UNPREDICTED_BUT_PREDICTABLE` or where pattern attribution is unclear, attempt a news catalyst check before concluding. Use WebFetch against:

- `https://www.tijorifinance.com/company/<slug>/`
- `https://www.screener.in/company/<SYM>/`

Look for: divestment / OFS / DRHP / earnings beat / order win / regulatory action / FII block deal / management commentary. Real catalysts that the agent's Step 1.5 macro scan should have caught belong in the `THEMATIC_BLINDSPOT` or `RULE_GAP` rule-update buckets. Pure rumor moves stay `UNPREDICTED_AND_UNPREDICTABLE`.

### 5. Pattern Vote Tally — upvote and downvote

Open `pattern_notes.md` and locate the ledger between `<!-- ledger-start -->` and `<!-- ledger-end -->`.

**For every pattern that fired in step 3 attribution AND the gainer's classification is `PREDICTED_AND_PICKED` or `PREDICTED_BUT_GATED`:**

- Increment `Hits_Total` by 1
- Append today's date to that pattern's row in `## PATTERN HIT DATES`
- Recompute `Hits_L10` (count dates within last 10 trading sessions)
- Recompute `Hits_L30` (count dates within last 30 trading sessions)
- Append the winning stock + % move to `Recent_Winners` (keep last 5, drop oldest)
- Set `Last_Hit_Date` = run date

**For every pattern that fired but landed in `PREDICTED_BUT_MISSED`:**

- Same as above, BUT also flag the pattern with a `_pipeline_miss_count` annotation in `pattern_notes.md` under a new `## PATTERN PIPELINE MISSES` section. If pipeline_miss_count reaches 3 for the same pattern across distinct stocks → write a feedback memory file flagging the gates that swallowed the pick.

**For every pattern in the ledger that did NOT fire today AND did not fire any of the last 10 sessions (`Hits_L10 == 0`):**

- Recompute its tag per the rules table in Step 4.6.4.3 of the agent file:
  - `Hits_L30 == 0` → `STALE`
  - `Hits_L10 == 0 AND Hits_L30 1–2` → `COOLING`
- Tags downgrade automatically — no separate "downvote" mechanic. The downvote IS the silence.

**For every gainer in `UNPREDICTED_BUT_PREDICTABLE`:**

- Log under `pattern_notes.md` → `## UNRECOGNIZED_MOVERS` with: symbol, date, %move, vol/avg, RSI, sector, suspected pattern, and proposed rule update.
- If 3+ similar setups appear within 30 sessions → propose a new RM-N template in `## PROPOSED_PATTERNS`.

### 6. Recompute tags for every pattern

After updating hits, re-evaluate the tag for ALL patterns in the ledger using the table from the agent's Step 4.6.4.3:

| Condition | Tag | Confidence modifier |
|---|---|---|
| Hits_L10 ≥ 5 | `PRIORITY` | +3 (cap 92) |
| Hits_L10 ≥ 3 | `HIGH_CONVICTION` | +2 (cap 92) |
| Hits_L10 1–2 AND Hits_L30 ≥ 3 | `NORMAL` | 0 |
| Hits_L10 = 0 AND Hits_L30 1–2 | `COOLING` | 0 (flag in output) |
| Hits_L30 = 0 | `STALE` | −3 next time it fires |

Tag changes go into the run report. Tags that change from `STALE`/`COOLING` upward are promoted; tags going downward are demoted. Both are noted in the report.

### 7. Apply rule changes to the agent file

Only modify the agent file when at least one of these conditions holds:

- A pattern accumulated `pipeline_miss_count >= 3` → tighten or relax the gate that swallowed the pick. Cite the specific Step 2.7 check and the exact value before/after. Reference the affected memory.
- An `UNPREDICTED_BUT_PREDICTABLE` gainer reveals a thematic basket gap → add a new basket section near the existing `Power equipment / grid infra basket` and `Chemicals / specialty materials basket` blocks in Step 1 of the agent file. Force-add the seed member with `gap_added: true` and an OHLC backfill directive.
- A pattern's tag stays `STALE` for 30+ sessions → remove its confidence modifier from Step 2 (do NOT delete the pattern; mark `active: false`).
- A new RM-N template hits 3 confirmed wins in pattern_notes.md → add a new row in the RM template table in Step 2.3 of the agent file.
- An RSI/threshold gate misclassified ≥2 stocks in this run → propose the threshold update with the validation table (per the agent's `4.5.3 — Validation Case` template). Apply only if false-positive rate < 50%.

For every agent-file edit:

1. Read the affected section first.
2. Make the smallest, most-targeted edit possible. Do not rewrite the file.
3. Update `MEMORY.md` index with a one-line pointer for any new memory file.
4. Add a one-line entry to `pattern_notes.md` under a new `## INTROSPECT_RUN_<DATE>` section noting the edit and the reasoning.

### 8. Output report

Write the run report to `out/<DATE>-introspect.txt` with these sections:

```
================================================================================
TOP-GAINER INTROSPECT — <DATE>
================================================================================

1. NSE TOP 10 (>5%, sorted by Value Traded):
[full table — Rank | Symbol | LTP | Chg% | Volume | Value Cr | InUniv | Picked]

2. PER-GAINER PATTERN ATTRIBUTION + VERDICT:
Symbol | Predicting Pattern(s) | Wilder RSI | Vol/Avg | Bucket | Notes
[per-stock]

3. CATALYST CHECK (for ambiguous):
[per-stock catalyst lookup result]

4. PATTERN VOTE TALLY:
   UPVOTES (fired correctly):
     - <pattern>: hits L10 N->M, tag X->Y
   DOWNGRADED TAGS (silent ≥10 / ≥30 sessions):
     - <pattern>: tag X->Y
   PIPELINE MISSES (pattern fired, gates swallowed):
     - <symbol> via <pattern> via gate <name>
   UNRECOGNIZED:
     - <symbol> — proposed new template <RM-N> (or "log only")

5. AGENT FILE EDITS APPLIED:
   - File: <path>
     Section: <heading>
     Change: <diff summary>
     Rationale: <link to bucket from step 3 + validation row>

6. MEMORY WRITES:
   - Path: <relative path>
     Summary: <one line>

7. LEDGER SNAPSHOT (post-update):
[paste updated ledger table]

8. NEXT-RUN HEADS-UP:
   - Tags promoted to PRIORITY: [list]
   - Patterns now STALE: [list]
   - New thematic baskets added: [list]
```

## Hard rules

- **Never** retroactively rewrite a prior run's recommendation list. Yesterday's picks are immutable.
- **Never** demote a pattern below `STALE` or delete it from the ledger. Patterns can revive.
- **Never** propose a confidence-threshold lowering without the 30-session false-positive validation per the agent's Step 4.5.3 template.
- **Always** use Wilder RSI per Rule RSI-1. SMA RSI is wrong and reads 8-12 points lower in strong uptrends.
- **Always** cap auto-edits to the smallest possible diff. If a change requires rewriting a section, write a memory file and link it instead.
- **Always** log to `pattern_notes.md` under `## INTROSPECT_RUN_<DATE>` so future runs can audit what changed.

## Related agent rules

- Step 4.6 (NSE-Wide Self-Audit & Pattern Upvote) in `.claude/agents/india-stock-recommender.md` — this skill operationalizes Step 4.6 as a standalone, on-demand command that is normally only run inline at end-of-day.
- Rule RSI-1 (Wilder smoothing) — `.claude/agent-memory-local/india-stock-recommender/feedback_rsi_wilder_standard.md`
- RM-11 cap-tier rule — `.claude/agent-memory-local/india-stock-recommender/rm-11-consecutive-catalyst-continuation.md`
- UGD OHLC backfill rule — `.claude/agent-memory-local/india-stock-recommender/ugd-ohlc-backfill-rule.md`
- Watchlist persistence — `.claude/agent-memory-local/india-stock-recommender/feedback_watchlist_persistence.md`
