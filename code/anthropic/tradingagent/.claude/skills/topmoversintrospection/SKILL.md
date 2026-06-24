---
name: topmoversintrospection
description: Audit the india-stock-recommender's rule ledger against the top 10 Chartink "5% in past 2 sessions" gainers (sorted by Value Traded = LTP × Volume). For each gainer, identify which existing rules in the ledger would have caught it or blocked it. Upvote rules that helped predict the move, downvote rules that produced false-negatives (blocked a legitimate setup) or false-positives. Apply the resulting +1/-1 vote changes directly to the RULES LEDGER table in .claude/agents/india-stock-recommender.md. Use when the user asks to "introspect top movers", "run topmoversintrospection", "audit rule ledger against Chartink gainers", "analyse Chartink 5% gainers", or invokes /topmoversintrospection directly.
argument-hint: "[scanner-url] (optional — defaults to https://chartink.com/screener/past-2-says-5-increment)"
allowed-tools: Read, Bash, Edit, Write, Grep, Glob, WebFetch, Agent
---

# Top Movers Introspection (Chartink-driven)

Audit the india-stock-recommender's **rule ledger** against the top 10 Chartink "5% in past 2 sessions" gainers, sorted by Value Traded. This is **complementary** to (not a replacement for) the existing `top-gainer-introspect` skill — that one uses NSE's `live-analysis-variations` API and focuses on pattern attribution; this one uses Chartink's "past 2 days 5% increment" screener and focuses on **rule ledger +1/-1 votes**.

The output is a set of edits to the RULES LEDGER table in `.claude/agents/india-stock-recommender.md`, plus a summary table printed to the user. **No new picks** are emitted — this is purely retrospective.

## Key difference vs `top-gainer-introspect`

| Aspect | `top-gainer-introspect` | `topmoversintrospection` (this skill) |
|---|---|---|
| Data source | NSE `live-analysis-variations?index=gainers` (today's gainers) | Chartink scanner (5%+ in *past 2 sessions*) |
| Universe | Today's gainers only | Any stock that moved 5%+ in either of last 2 sessions (catches Day-2 continuation candidates too) |
| Focus | Pattern attribution + universe gap detection | Rule ledger +1/-1 vote updates |
| Output | Memory writes + Step 4.6 ledger updates | Direct edit of RULES LEDGER table |
| Output gainer count | Top 10 by LTP × Vol | Top 10 by LTP × Vol |

## Inputs

- `$ARGUMENTS[0]` (optional): scanner URL. Defaults to `https://chartink.com/screener/past-2-says-5-increment`.
- Working directory: must be the trading agent project root (`/Users/I038849/Documents/Ashish/github.com/mailashishrawat/ml/code/anthropic/tradingagent/`).
- Agent definition: `.claude/agents/india-stock-recommender.md` (contains the RULES LEDGER table between `<!-- rules-ledger-start -->` / `<!-- rules-ledger-end -->`).

## Procedure

### Step 1 — Fetch Chartink top gainers (fan out subagent)

Spawn ONE subagent to fetch the scanner results. Use Agent tool with `subagent_type: general-purpose`:

```
Task: Fetch the top gainers from this Chartink screener: <SCANNER_URL>

This screener identifies NSE stocks that have moved 5%+ in past 2 sessions.

Steps:
1. WebFetch the URL to get the stock list. If WebFetch doesn't return the data
   (Chartink uses POST endpoint), try this curl approach:

   curl -s -X POST 'https://chartink.com/screener/process' \
     -H 'Content-Type: application/x-www-form-urlencoded' \
     -H 'X-Requested-With: XMLHttpRequest' \
     -H 'User-Agent: Mozilla/5.0' \
     --data-urlencode 'scan_clause=( {cash} ( latest close > 1 day ago close * 1.05 or 1 day ago close > 2 days ago close * 1.05 ) )'

   You may need to first GET the page to capture the CSRF token, then POST with it.
2. Alternatively, fetch the URL HTML, extract the embedded scan_clause, then POST.
3. Return raw rows with: Symbol | LTP | %Chg | Volume | Value Cr (LTP × Vol / 1e7)
4. Sort by Value Cr descending and return TOP 20 (we'll use top 10).
```

If the fetch fails, fall back to yfinance over the basestock.json universe + filter for ≥5% moves in last 2 sessions. Note `CHARTINK_API_GAP` in output.

### Step 2 — Read current rule ledger

Read `.claude/agents/india-stock-recommender.md` and extract the rule ledger table between `<!-- rules-ledger-start -->` and `<!-- rules-ledger-end -->`. Capture for each rule: Rule ID, Name, Step, Upvotes, Downvotes, Net, Last_Updated, Status, One-Line Summary.

### Step 3 — Fan out subagents to analyze gainers vs rules

Spawn **2 subagents in parallel** (5 gainers each) for efficiency. Each subagent receives:

- Its 5 gainers (symbol, %chg, volume, value Cr)
- The current rule ledger (compact form)
- Instructions to fetch 60 days of OHLCV via yfinance and compute pre-move setup at T-1 EOD

**Per-stock analysis template each subagent must produce:**

```
=== SYMBOL ===
Pre-move setup (T-1 EOD):
  - Wilder RSI 14: X.X (MANDATORY: use ewm(alpha=1/14, adjust=False), NOT SMA)
  - Vol on move day / 20d avg: X.Xx
  - Distance from 20d high: X.X%
  - MA5 distance: ±X.X%
  - Range trajectory last 3 sessions: expanding/coiling/declining
  - 3-day close trajectory: declining/non-declining/mixed
  - Recency (big-days/64): N
Pattern identified: RM-? / Pattern ? / UNRECOGNIZED
Rules that WOULD have flagged it as a buy: [list rule IDs]
Rules that WOULD have BLOCKED a legitimate setup (false negative): [list]
Rules that CORRECTLY excluded it (good filter): [list]
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
5. **Recompute Status** per these thresholds:
   - `Net ≥ +8` → `HIGH_CONVICTION`
   - `Net ≤ −3` → `REVIEW` (flag for tightening, loosening, or retirement)
   - Otherwise → `ACTIVE`
6. Update the One-Line Summary if a notable validation or failure case was added (append the date and stock as a brief reference).

Use the `Edit` tool with a precise `old_string` / `new_string` pair for each row. **Preserve table formatting exactly** — pipe alignment, column count, marker comments.

### Step 6 — Output to user

Print a concise summary to the user with these sections:

**1. Top 10 Gainers Table:**
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

- **Primary output**: Edited `.claude/agents/india-stock-recommender.md` (RULES LEDGER table only)
- **Optional log**: `out/<YYYY-MM-DD>-topmovers-introspect.txt` (full audit detail, gainer setups, per-rule reasoning). Only write if user asks for persistence or if 3+ rules flipped status this run.
- **No memory writes** (use `top-gainer-introspect` skill for that)
- **No picks emitted**

## Hard Rules

1. **Never retroactively claim a stock "was almost picked"** — only count votes that the rule genuinely would have fired or correctly stood aside given T-1 EOD data.
2. **Never propose a rule update that contradicts an existing memory** without explicitly naming the memory and arguing for supersession.
3. **Wilder RSI is mandatory** (Rule RSI-1). SMA-RSI produces 8-12pt lower values and will produce wrong RM-11 classifications.
4. **The audit must NOT** be used to backfill past recommendations records.
5. **Cap single-run vote shifts at ±5** per rule to prevent volatility.
6. **Status changes are recomputed from Net** — do not manually flag `REVIEW` or `HIGH_CONVICTION` without the Net crossing its threshold.
7. **Catalyst-driven moves (Pattern j) get NEUTRAL votes** on technical rules — those rules correctly stayed silent; the miss is a news-pipeline gap, not a technical-rule failure.

## Related skills and memories

- `top-gainer-introspect` — NSE API gainers, pattern attribution focus
- Rule ledger lives in `.claude/agents/india-stock-recommender.md` STEP 4.6 RULES LEDGER section
- `[[step-4-6-nse-wide-self-audit]]` — Step 4.6 audit framework
- `[[mandatory-chart-read-and-90-percent-threshold]]` — Step 2.7 gate framework
