---
name: topmoversintrospection
description: Audit the india-stock-recommender's rule ledger against the top 25 Chartink T-0 gainers (sorted by Value Traded = LTP × Volume, with Rs 1 crore liquidity gate). For each gainer, identify which existing rules in the ledger would have caught it or blocked it. Upvote rules that helped predict the move, downvote rules that produced false-negatives (blocked a legitimate setup) or false-positives. Apply the resulting +1/-1 vote changes directly to the RULES LEDGER table in .claude/agents/india-stock-recommender.md. Use when the user asks to "introspect top movers", "run topmoversintrospection", "audit rule ledger against Chartink gainers", "analyse Chartink 5% gainers", or invokes /topmoversintrospection directly.
argument-hint: "[scanner-url] (optional — defaults to https://chartink.com/screener/past-2-says-5-increment)"
allowed-tools: Read, Bash, Edit, Write, Grep, Glob, WebFetch, Agent
---

# Top Movers Introspection (Chartink-driven, standalone rule-ledger audit)

## Config load (mandatory, first action)

**Load `data/config.json` before any other work.** Chartink scan clause, tag string, top-N, shard counts, vote-cap magnitude — all authoritative in JSON.

Sub-paths this skill reads:
- **Chartink**: `config.chartink.scan_clause_t0`, `.csrf_endpoint`, `.process_endpoint`, `.csrf_header_name`, `.top_n` (25), `.sort_by`
- **Liquidity gate**: `config.universe.liquidity_gate_close_x_volume_min` (1e7)
- **Fan-out**: `config.fan_out_shard_counts.topmoversintrospection_shards` (5), `.topmoversintrospection_gainers_per_shard` (5)
- **Ledger vote cap**: `config.phase_f.ledger_update.single_run_vote_cap_magnitude` (5) — single-run vote shift cap per rule
- **Ledger status thresholds**: `config.phase_f.ledger_update.high_conviction_net_threshold` (8), `.review_net_threshold` (-3)
- **Rule 26e volatility floor** (for pre-move setup): `config.screening.volatility_floor_annual_days` (40), `.volatility_floor_annual_window` (252), `.volatility_floor_tier_a_64sessions` (8)
- **All ledger-eligible rule parameters** (referenced by Opus shards when computing pre-move setup): `config.phase_c.*`, `config.phase_d.*`, `config.rules_ledger.rsi_wilder_period` (14)

On load failure: halt this skill, print `CONFIG_LOAD_FAILURE — <reason>`, do NOT proceed to any of the numbered Steps 1–6. RULES LEDGER stays untouched.

Pass the loaded config to every Opus shard as read-only input. Shards use it to compute pre-move setups (RSI, vol ratios, distance-to-52wH, etc.) with the same parameters the live pipeline uses.

Audit the india-stock-recommender's **rule ledger** against the top 25 Chartink gainers that closed UP ≥5% today with ≥Rs 1 crore traded value, sorted by Value Traded (LTP × Volume). This is the **standalone / on-demand** counterpart to Phase F.1 of the pipeline — same Chartink T-0 fetch, same `data/dailygainers.csv` append contract (with `tag == "t0_5pct_liq1cr"`), same tag-collision guard, but standalone: no dependency on prior Phase A/B/C/D/E outputs, no memory writes, no picks.

The output is (a) a set of edits to the RULES LEDGER table in `.claude/agents/india-stock-recommender.md` (between `<!-- rules-ledger-start -->` / `<!-- rules-ledger-end -->`), (b) an append to `data/dailygainers.csv` (top-25 T-0 rows tagged `t0_5pct_liq1cr`), and (c) a summary table printed to the user. **No new picks** are emitted — this is purely retrospective.

## Relationship to Phase F.1

| Aspect | Phase F.1 (in-pipeline) | `topmoversintrospection` (this skill, standalone) |
|---|---|---|
| Trigger | Runs automatically as part of daily pipeline | User invokes on demand: `/topmoversintrospection` |
| Prerequisites | Phase A–E must have completed | None — starts fresh |
| Data source | Chartink T-0 ≥5% + liquidity gate | Same |
| `data/dailygainers.csv` tag | `t0_5pct_liq1cr` | Same (identical contract) |
| Tag-collision guard | Yes (F.1 hard rule) | Yes (identical) |
| Focus | 4.6 self-audit (pattern attribution + rule-ledger update) inside a larger phase | Rule ledger +1/-1 votes only |
| Output gainer count | Top 25 by LTP × Vol | Same |
| Memory writes | Yes (via MISS_ANALYZE in F.2) | No (retrospective only) |
| Basestock mutation | No (4.6.5b retired) | No (4.6.5b retired) |

## Inputs

- `$ARGUMENTS[0]` (optional): scanner URL. Defaults to `https://chartink.com/screener/past-2-says-5-increment`.
- Working directory: must be the trading agent project root (`/Users/I038849/Documents/Ashish/github.com/mailashishrawat/ml/code/anthropic/tradingagent/`).
- Agent definition: `.claude/agents/india-stock-recommender.md` (contains the RULES LEDGER table between `<!-- rules-ledger-start -->` / `<!-- rules-ledger-end -->`).

## Procedure

### Step 1 — Fetch Chartink top gainers (fan out subagent)

Spawn ONE subagent to fetch the scanner results. Use Agent tool with `subagent_type: general-purpose` and `model: opus` (deeper reasoning required for parsing the screener response and reconciling against the basestock universe fallback):

```
Task: Fetch the top gainers from this Chartink screener: <SCANNER_URL>

This screener identifies NSE stocks that closed UP ≥5% today (T-0 only).

Steps:
1. GET https://chartink.com/screener/past-2-says-5-increment to capture:
   - XSRF-TOKEN cookie (URL-decode it for the header value)
   - laravel_session cookie (may or may not be set)
   - <meta name="csrf-token" content="..."> from the HTML
2. POST to https://chartink.com/screener/process with:
   - Cookie jar carrying XSRF-TOKEN (+ laravel_session if present)
   - Header: X-CSRF-TOKEN: <meta csrf-token content>   (do NOT also send X-XSRF-TOKEN — that returns 419)
   - Header: X-Requested-With: XMLHttpRequest
   - Header: Content-Type: application/x-www-form-urlencoded
   - Header: User-Agent: Mozilla/5.0
   - Body: scan_clause=( {cash} ( latest close > 1 day ago close * 1.05 and latest close * latest volume > 10000000 ) )

   *** CRITICAL — this is T-0-ONLY (latest close > 1 day ago close * 1.05).
   Do NOT use the OR variant ("latest close > 1 day ago close * 1.05 or 1 day ago close > 2 days ago close * 1.05")
   — that includes stocks that qualified only on yesterday's leg and can appear
   with NEGATIVE %chg today (e.g. gave back after a T-1 spike). The audit must
   be on stocks actually up ≥5% TODAY.

   The `latest close * latest volume > 10000000` clause filters out illiquid names
   (Close×Volume must exceed Rs 1 crore of traded value today). This is a hard
   liquidity gate applied at the scanner layer — do not remove or relax. ***

3. Parse JSON response. Each row has: sr, name, nsecode, bsecode, close, per_chg, volume.
4. Compute Value Cr = close × volume / 1e7.
5. Sort by Close × Volume DESCENDING and take TOP 25.
```

If the fetch fails, fall back to yfinance over the basestock.json universe + filter for ≥5% moves today. Note `CHARTINK_API_GAP` in output.

### Step 1.5 — Append top 25 to `data/dailygainers.csv` (MANDATORY every run — aligned with Phase F.1 contract)

Immediately after Step 1 succeeds, append the top-25 rows to `data/dailygainers.csv` in the project root. This file is append-only immutable — it becomes the historical substrate for backtesting rule proposals AND the source of truth Phase A reads for prior-day universe.

**This skill's Chartink fetch is the same as Phase F.1 in the pipeline (T-0 top-25).** All F.1 contracts apply: exact `tag` value, tag-collision guard, hard exit assertion.

**Schema (create with header if the file does not exist) — 8 columns:**
```
date,rank,symbol,ltp,pct_chg,volume,value_cr,tag
```

- `date` = today's date in YYYY-MM-DD (T-0)
- `rank` = 1..25 (top-25 by Close × Volume)
- `symbol` = NSE ticker (nsecode field)
- `ltp` = close from Chartink response
- `pct_chg` = per_chg (positive only after Step 1 filter)
- `volume` = volume (integer)
- `value_cr` = ltp × volume / 1e7, 2-decimal
- `tag` = **`t0_5pct_liq1cr`** (MANDATORY exact string — NEVER shorten to `t0_5pct` or leave empty; the tag is the sole discriminator between T-0 F.1/this-skill rows and A.0's T-1 rows in the same file; empty or wrong tag = pipeline error). Fallback path (NSE `live-analysis-variations` after `CHARTINK_API_GAP`): tag = `t0_5pct_liq1cr_nse_fallback` — do NOT tag as clean `t0_5pct_liq1cr` (different clause poisons the series).

**Tag-collision hard guard (added 2026-07-03):** Before appending, verify no schema violation exists:
- If an existing row has `(date == today, tag == "t1_5pct_liq1cr")` — that's an A.0 write for the WRONG date (T-1 tag on T-0 date). Abort with `PHASE_F_DAILYGAINERS_TAG_COLLISION`, do NOT write.
- If an existing row has `(date == T-1, tag == "t0_5pct_liq1cr")` — that's a T-0 tag on a T-1 date. Same schema violation, abort.

**Idempotency rule:** If a row with the same `(date, symbol, tag)` already exists in the file, DO NOT append (previous invocation this session already logged it). Read the CSV, filter out same-date+same-tag rows before appending. Never rewrite the file — append-only.

**F.1 exit assertion (HARD GATE):** after append, verify:
```python
import pandas as pd
df = pd.read_csv("data/dailygainers.csv")
today = "<T-0 YYYY-MM-DD>"
t1_yday = "<T-1 YYYY-MM-DD>"
assert df[(df.date == today) & (df.tag == "t0_5pct_liq1cr")].shape[0] >= 1, "F1_WRITE_MISSING — top-25 T-0 rows did not land"
# no untagged / mistagged rows past T-1
mask = df.date.ge(t1_yday) & ~df.tag.isin(["t0_5pct_liq1cr","t1_5pct_liq1cr","t0_5pct_liq1cr_nse_fallback","t1_5pct_liq1cr_nse_fallback"])
assert mask.sum() == 0, f"F1_UNTAGGED_ROWS_DETECTED — {mask.sum()} rows"
```
On assertion failure: halt this skill, print the diagnostic, do NOT proceed to Step 2. The RULES LEDGER stays untouched.

**Failure mode (Chartink):** If Chartink fetch failed (CHARTINK_API_GAP), fall back to NSE `live-analysis-variations?index=gainers` (cookie-primed). Tag those rows `t0_5pct_liq1cr_nse_fallback` — never as clean `t0_5pct_liq1cr`.

Use Bash with a small Python snippet:
```bash
python3 - <<'PY'
import csv, os, sys
from datetime import date, timedelta
path = "data/dailygainers.csv"
today = date.today().isoformat()
yday = (date.today() - timedelta(days=1)).isoformat()  # approximate; NSE-calendar T-1 preferred
top25 = [
  # (rank, symbol, ltp, pct_chg, volume, value_cr) tuples from Step 1
]

# Tag-collision guard
if os.path.exists(path):
    with open(path) as f:
        for row in csv.DictReader(f):
            if row["date"] == today and row["tag"] == "t1_5pct_liq1cr":
                sys.exit("PHASE_F_DAILYGAINERS_TAG_COLLISION: T-1 tag on T-0 date")
            if row["date"] == yday and row["tag"] == "t0_5pct_liq1cr":
                sys.exit("PHASE_F_DAILYGAINERS_TAG_COLLISION: T-0 tag on T-1 date")

existing = set()
if os.path.exists(path):
    with open(path) as f:
        for row in csv.DictReader(f):
            existing.add((row["date"], row["symbol"], row["tag"]))
header_needed = not os.path.exists(path)
with open(path, "a", newline="") as f:
    w = csv.writer(f)
    if header_needed:
        w.writerow(["date","rank","symbol","ltp","pct_chg","volume","value_cr","tag"])
    for rank, sym, ltp, pct, vol, val in top25:
        if (today, sym, "t0_5pct_liq1cr") in existing:
            continue
        w.writerow([today, rank, sym, ltp, pct, vol, val, "t0_5pct_liq1cr"])
PY
```

Print `Appended N rows to data/dailygainers.csv with tag=t0_5pct_liq1cr` (or `Skipped — already logged today`).

### Step 2 — Read current rule ledger

Read `.claude/agents/india-stock-recommender.md` and extract the rule ledger table between `<!-- rules-ledger-start -->` and `<!-- rules-ledger-end -->`. Capture for each rule: Rule ID, Name, Step, Upvotes, Downvotes, Net, Last_Updated, Status, One-Line Summary.

### Step 3 — Fan out subagents to analyze gainers vs rules

Spawn **5 subagents in parallel** (5 gainers each × 5 shards = 25 gainers) for efficiency. **All subagents MUST use `model: opus`** — the analysis requires careful pattern attribution, distinguishing genuine rule failures from coincidental moves, and reasoning about which rules would have fired given T-1 EOD data alone. Sonnet has shown a tendency to over-apply rule fixes without backtest evidence; Opus's deeper reasoning materially improves vote-tally accuracy.

Use Agent tool with `subagent_type: general-purpose` and `model: opus` for each. Each subagent receives:

- Its 5 gainers (symbol, %chg, volume, value Cr)
- The current rule ledger (compact form) — enumerate ALL ACTIVE + REVIEW + HIGH_CONVICTION rules; SUPERSEDED rules (e.g. 4.6.5b) are informational only, no votes
- Instructions to fetch 60 days of OHLCV via yfinance (or read from `data/stockparam.csv` if the symbol has coverage) and compute pre-move setup at T-1 EOD

**Rules eligible for +1/-1 voting (from `.claude/agents/india-stock-recommender.md` RULES LEDGER, as of Jul 3 2026):**

- Universe/data: `RSI-1`, `PM-1`, `CA-1`, `CA-2`, `A.2`, `4.7`
- Pre-filter/screening: `26e`, `Sub-26f`, `26g`, `46b`, `46c`, `46d`, `77`, `77b`, `77c`, `77d`, `78`, `78b`, `79`, `80`, `81`, `82`
- Pattern templates: `RM11-RSI`, `RM11-INS`, `RM-12`
- Trend classifier + relaxations: `UT-1`, `UT-RELAX-1`, `UT-RELAX-2`, `UT-RELAX-3`, `UT-RELAX-4`, `UT-RELAX-5`
- Watchlist / composition: `WPR`, `NDP`, `NEWS-CAT`
- **SUPERSEDED (no votes):** `4.6.5b` — replaced by Phase A.0 daily universe. If a gainer would have triggered 4.6.5b, note it as "would have force-added under retired rule" but DO NOT cast a vote on 4.6.5b.

**Per-stock analysis template each subagent must produce:**

```
=== SYMBOL ===
Pre-move setup (T-1 EOD):
  - Wilder RSI 14: X.X (MANDATORY: use ewm(alpha=1/14, adjust=False), NOT SMA — Rule RSI-1)
  - Vol on move day / 20d avg: X.Xx
  - Distance from 20d high: X.X%
  - Distance from 52w high: X.X%
  - MA5 distance: ±X.X%
  - Range trajectory last 3 sessions: expanding/coiling/declining
  - 3-day close trajectory: declining/non-declining/mixed
  - Recency (big-days/64): N; annual (big-days/252): N
  - Rule UT-1 state: STRONG_UP / UP / SIDEWAYS / DOWN (HH count, HL count, MA20 slope %)
  - Post-52wH cooldown (Rule 77c) applicable? Y/N (peak-day close ≥3% below intraday high?)
  - Distribution day (Rule 78) in last 10 sessions? Y/N
  - BE segment (Rule 79)? Y/N
  - Series/short-history flags: Y/N
Pattern identified: RM-1..12 / Pattern a-k / MC / UNRECOGNIZED
Catalyst (from macro-scan T-1 news): T1 / T2 / T3 / NONE (Rule NEWS-CAT)
Rule UT-RELAX applicability: [Relax-1..5] — which relaxations WOULD have fired given UT-1 state?
Rules that WOULD have flagged it as a buy: [list rule IDs]
Rules that WOULD have BLOCKED a legitimate setup (false negative): [list]
Rules that CORRECTLY excluded it (good filter): [list]
Rule 46d fresh-high exemption applicable? Y/N (6-condition check: <1.5% of 52wH, vol ≥1.5×, reversal <2%, RM-1/11/WPR-P1, T1/T2 catalyst, 77/77c/78/79/sub-26f/46b all PASS)
Verdict: UPVOTE rules X, Y / DOWNVOTE rules A, B / NEUTRAL
```

**Wilder RSI code template (subagents MUST use this — Rule RSI-1):**

```python
import yfinance as yf
df = yf.Ticker(f"{symbol}.NS").history(period="60d")
closes = df["Close"]
delta = closes.diff()
gain = delta.clip(lower=0)
loss = (-delta).clip(lower=0)
avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
rsi = 100 - (100 / (1 + avg_gain / avg_loss))
```

### Step 4 — Consolidate votes

Aggregate +1/-1 votes across all 10 gainers per rule. A rule may receive multiple votes from different gainers — count them all. Build a consolidated tally:

```
| Rule | Upvotes | Downvotes | Reason summary |
|------|---------|-----------|---------------|
| 80   | 1       | -4        | Vol≥0.8x gate kills coil signal (ROTO 0.48x, RAMCOSYS 0.17x); 5% distance too tight; RSI 55-72 too narrow |
| 82   | +4      | 0         | Caught running breakouts cleanly (JSWINFRA, PGIL, AETHER, RAMCOSYS) |
| WPR  | +3      | 0         | Pullback re-entry textbook on KPRMILL, AETHER, PGIL |
...
```

Cap any single-rule single-run vote shift at **±5** to prevent rapid swings. If a rule earns 6+ votes one way in a single run, cap at 5 and note "saturated this run" in the audit output.

### Step 5 — Apply ledger edits

For each rule with non-zero net vote change:

1. Locate the rule's row in the ledger table.
2. Update `Upvotes` and `Downvotes` columns (add to existing counts).
3. Recompute `Net = Upvotes − Downvotes`.
4. Set `Last_Updated = <today>` (YYYY-MM-DD).
5. **Recompute Status** per these thresholds (must match the RULES LEDGER procedure in the agent file):
   - `Net ≥ +8` → `HIGH_CONVICTION`
   - `Net ≤ −3` → `REVIEW` (flag for tightening, loosening, or retirement)
   - Otherwise → `ACTIVE`
   - **Exception:** rules explicitly marked `SUPERSEDED` (e.g. `4.6.5b`) do not receive votes and their Status stays `SUPERSEDED`. Skip.
6. Update the One-Line Summary if a notable validation or failure case was added (append the date and stock as a brief reference).

Use the `Edit` tool with a precise `old_string` / `new_string` pair for each row. **Preserve table formatting exactly** — pipe alignment, column count, marker comments (`<!-- rules-ledger-start -->` / `<!-- rules-ledger-end -->`).

### Step 6 — Output to user

Print a concise summary to the user with these sections:

**1. Top 25 Gainers Table:**
```
| Rank | Symbol | %Chg | Value (Cr) | Pattern |
|------|--------|------|-----------|---------|
| 1    | ...    | ...  | ...       | ...     |
```

**2. Vote Tally:**
```
| Rule | Δ Upvotes | Δ Downvotes | New Net | Status Change |
|------|-----------|-------------|---------|---------------|
```

**3. Key Findings:**
- 2–4 bullets on the most significant rule shifts (e.g., "Rule 80 dropped to -1, flagged REVIEW — three failure modes documented...")
- Any new proposed rules emerging from UNRECOGNIZED patterns (write them as Rule 80b / 80c / etc. suggestions, do NOT auto-add to ledger)
- Any blindspots (e.g., "Pattern j news-catalyst gap: TCIEXP +16.6% had no technical setup, pure news pop")

## Output Files

- **Primary output**: Edited `.claude/agents/india-stock-recommender.md` (RULES LEDGER table only, between `<!-- rules-ledger-start -->` / `<!-- rules-ledger-end -->` — no other content touched).
- **Historical append (MANDATORY every run)**: `data/dailygainers.csv` — top-25 T-0 gainers appended with `tag=t0_5pct_liq1cr`. Append-only, idempotent by (date, symbol, tag). Substrate for backtest of rule proposals against actual gainer distributions AND read by Phase A of the daily pipeline.
- **Optional log**: `out/<YYYY-MM-DD>-topmovers-introspect.txt` (full audit detail, gainer setups, per-rule reasoning). Only write if user asks for persistence or if 3+ rules flipped status this run.
- **No memory writes** — memory writes are the province of `audit-and-format` (Phase F) MISS_ANALYZE flow.
- **No picks emitted** — introspection is retrospective only.
- **No `basestock.json` mutation** — 4.6.5b force-add path is retired; Phase A.0 daily universe supersedes.

## Related skills and memories

- Parent pipeline: `.claude/agents/india-stock-recommender.md` — RULES LEDGER table between `<!-- rules-ledger-start -->` / `<!-- rules-ledger-end -->`
- Sibling skill (in-pipeline): `audit-and-format` — Phase F.1 runs the same Chartink T-0 fetch and writes the same `data/dailygainers.csv` rows with the same tag contract. This skill is the standalone/on-demand version.
- Data substrate: `data/stockparam.csv` (sole per-stock source of truth; use for pre-move setup computation when the symbol is covered)
- Related memories: `[[step-4-6-nse-wide-self-audit]]`, `[[mandatory-chart-read-and-90-percent-threshold]]`, `[[dailygainers-tag-contract]]`, `[[eval-universe-daily-plus-anchors]]`, `[[rule-4-6-5b-unconditional-force-add]]` (retired path), `[[uptrend-relaxations-empirical]]`, `[[rm12-continuation-pullback]]`, `[[rule-46d-breakout-to-fresh-high-exemption]]`

## Hard Rules

1. **Never retroactively claim a stock "was almost picked"** — only count votes that the rule genuinely would have fired or correctly stood aside given T-1 EOD data.
2. **Never propose a rule update that contradicts an existing memory** without explicitly naming the memory and arguing for supersession.
3. **Wilder RSI is mandatory** (Rule RSI-1). SMA-RSI produces 8-12pt lower values and will produce wrong RM-11 classifications.
4. **The audit must NOT** be used to backfill past recommendations records.
5. **Cap single-run vote shifts at ±5** per rule to prevent volatility.
6. **Status changes are recomputed from Net** — do not manually flag `REVIEW` or `HIGH_CONVICTION` without the Net crossing its threshold.
7. **Catalyst-driven moves (Pattern j / RM-5 / NEWS-CAT) get NEUTRAL votes** on technical rules — those rules correctly stayed silent; the miss is a news-pipeline gap, not a technical-rule failure. May, however, upvote `NEWS-CAT` if a T1/T2 catalyst was correctly flagged in Phase B and would have led to a pick.
8. **Never vote on SUPERSEDED rules** — `4.6.5b` is retired (Phase A.0 daily universe supersedes). Note "would have force-added under retired rule" in the analysis but no vote.
9. **`data/dailygainers.csv` tag contract is inviolable**: every T-0 row written by this skill has `tag == "t0_5pct_liq1cr"` (or `t0_5pct_liq1cr_nse_fallback` on Chartink outage). Never write empty tags, never overwrite A.0's T-1 rows (tag-collision guard aborts the run).
10. **Assertion failure = halt**: if the F.1 exit assertion fires (F1_WRITE_MISSING or F1_UNTAGGED_ROWS_DETECTED or PHASE_F_DAILYGAINERS_TAG_COLLISION), print the diagnostic and STOP. Do not proceed to Step 2/3/4/5. The RULES LEDGER stays untouched.
11. **UT-RELAX rules vote symmetrically**: upvote a UT-RELAX-N when it correctly enabled a legitimate T1/T2-catalyst uptrend pick that a stricter threshold would have missed; downvote when it enabled a pick that failed. Never vote if UT-1 state was not STRONG_UP/UP (relaxations gate on that).

## Related skills and memories

- `top-gainer-introspect` — NSE API gainers, pattern attribution focus
- Rule ledger lives in `.claude/agents/india-stock-recommender.md` STEP 4.6 RULES LEDGER section
- `[[step-4-6-nse-wide-self-audit]]` — Step 4.6 audit framework
- `[[mandatory-chart-read-and-90-percent-threshold]]` — Step 2.7 gate framework
