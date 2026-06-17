---
name: feedback-volatility-filter
description: Rule 26e — Volatility floor with annual 40/252 OR recent 12/64 OR-gate (recency-rescue, added 2026-06-17); proportional threshold for recently listed stocks (<252 trading days); enforced in Step 1 screener and Step 2.5 Price Action Gate; BEL/BPCL retroactively also fail this rule
type: feedback
---

Every stock recommended by the pipeline must pass a minimum volatility floor before being included in basestock.xlsx or confirmed as a final pick. Stocks that rarely move 3% in a single day are structurally incompatible with the user's daily profit target.

**Rule 26e — Volatility Floor (annual + recency OR-gate):**
A stock passes Rule 26e if EITHER the annual floor OR the recency floor is met. This is a HARD FILTER at two pipeline layers (Step 1 screener and Step 2.5 Price Action Gate).

A "high-vol day" (HV day) = any session with absolute close-to-close move >= 3%.

**Annual floor (primary):**
- Seasoned stocks (>=252 trading days of history): >=40 HV days in the last 252 trading days.
- Recently listed stocks (<252 trading days): proportional floor — required count = `ceil(available_trading_days / 252 * 40)`, with a hard absolute minimum of 10 HV days regardless of the ratio.
- Stocks with fewer than 30 trading days of total history cannot pass Rule 26e at all (insufficient data).

**Recency floor (added 2026-06-17 — recency-rescue):**
- A stock that FAILS the annual floor still passes Rule 26e if it has >=12 HV days in the last 64 trading days (~last quarter).
- 12/64 is intentionally stricter than strict proration of 40/252 (which would be ~10.2/64). This requires a stock to be ACTIVELY volatile NOW, not merely vol-active historically. The intent is to rescue stocks that were quiet all year but woke up in the last quarter on a fresh trend or news catalyst (e.g., a large-cap that just entered a multi-quarter uptrend).
- The recency floor does NOT replace the annual floor — it supplements it (OR-gate, not AND-gate).
- Stocks with fewer than 64 trading days of total history cannot use the recency rescue — they must pass the annual proportional floor.

**Combined pass logic:**
```
PASS if (annual_HV_count >= annual_threshold) OR (last_64d_HV_count >= 12)
FAIL otherwise
```

**Reporting convention:**
When reporting Rule 26e status, show both numerators when relevant. Examples:
- `26e PASS (annual 69/40)` — passes on annual floor alone (most common)
- `26e PASS (annual 32/40 FAIL, recency 14/64 RESCUE)` — failed annual but rescued by recency
- `26e FAIL (annual 32/40, recency 9/64)` — both fail
- `26e FAIL (annual 22/40, recency N/A — only 50 trading days)` — too short for recency rescue

Examples (annual floor):
- Stock with 126 trading days (6 months): required = ceil(126/252 * 40) = 20 days AND >= 10 absolute — so 20 days required.
- Stock with 60 trading days (3 months): required = ceil(60/252 * 40) = 10 days AND >= 10 absolute — so 10 days required.
- Stock with 252+ trading days: required = 40 days (unchanged).

Examples (recency rescue):
- LT (annual 17/252 FAIL) but suppose 13/64 in last quarter on a fresh trending phase → PASS via recency.
- TRENT (annual 32/247 FAIL) — if Jun-Aug 2026 logs 12+ HV days as AGM run-up + post-AGM volatility kicks in, would PASS via recency (currently around ~5-6/64, still FAIL).
- BAJFINANCE (annual 21/40 FAIL) — needs to log 12 HV days in 64 sessions to qualify; currently nowhere close.

**Top-100 ranking for Step 1:**
Use the NORMALIZED rate — `High_Vol_Day_Count / Available_Trading_Days` — as the sort key so recently listed stocks (which have fewer available days) compete fairly with seasoned stocks. Retain the top 100 by normalized rate after all other filters are applied.

**New columns added to basestock.xlsx going forward:**
- `High_Vol_Day_Count`: count of >=3% move days over available trading history (use 252 cap for seasoned stocks)
- `Available_Trading_Days`: actual trading days of history available (capped at 252 for the volatility calculation)
- `High_Vol_Day_Rate`: `High_Vol_Day_Count / Available_Trading_Days` — used for top-100 ranking
- `1Y_Return_Pct`: 1-year price return percentage
- `52W_Range_Pct`: (52w_high - 52w_low) / 52w_low * 100

**Why:** "Stocks like BEL/BPCL have hardly moved 3% in a year. This automatically disqualifies them from our target of achieving 5% a day. We should look for the top 100 stocks that had maximum stretch of 3% rise as one of the criteria." The proportional extension for recent listings was added because Pattern S stocks (recent IPOs) cannot have 252-day history by definition — disqualifying them entirely would contradict the user's explicit intent to evaluate Pattern S candidates on whatever data is available.

Mathematical implication: the user's daily target is 5% per position per day. A stock that rarely moves 3% in a single day cannot deliver 5% in the swing window the pipeline uses. Selecting low-volatility stocks is structurally incompatible with the profit goal — not merely a suboptimal choice, but a mathematical impossibility at the target timeframe.

**How to apply:**
- Step 1 (weekly screener): After applying market cap, turnover, and profit growth filters, determine `Available_Trading_Days` for each candidate. Apply the correct threshold tier (seasoned vs. recently listed vs. <30 days). Calculate `High_Vol_Day_Rate` and rank descending — retain top 100.
- Step 2 (pattern analysis): Before finalising any pick, confirm the stock passes its tier-appropriate volatility threshold. If not, remove — even if news catalyst, FII accumulation, or Pattern S criteria are otherwise fully met.
- Step 2.5 gate: Treat this as Condition D in the Price Action Gate checklist, after conditions A (Rule 26a falling knife), B (Rule 26b distribution), and C (Rule 26d active downtrend). For Pattern S candidates (recent IPOs), use the proportional threshold — do not disqualify solely because they have fewer than 252 days of history.

**BEL/BPCL retroactive failure:**
Both stocks recommended in Run #16 (2026-05-27) and retroactively invalidated under Rule 26d ALSO fail Rule 26e:
- BEL: 1-year return ~+3% only — almost certainly fewer than 40 days with >=3% single-day moves.
- BPCL: 1-year return ~-4.5% with persistently low intraday range — almost certainly fails.
These stocks now carry TWO reasons for disqualification: `INVALID_RULE_26D` and `LOW_VOLATILITY_RULE_26E`.

See [[feedback-breakout-pattern]] for Rule 26a/b/c/d context. Rule 26e is the fifth sub-rule of the Rule 26 chart/structure gate.
