---
name: feedback-watchlist-persistence
description: Step 2.2 Watchlist Persistence Rule — re-evaluate all prior watchlist triggers before organic analysis every session; fired triggers get first priority; formalized after GOCOLORS +23.9% miss
metadata:
  type: feedback
---

## Rule: Step 2.2 Watchlist Re-evaluation (Mandatory, Every Session)

Before running any organic pattern analysis (Step 2), re-evaluate ALL prior watchlist
items from daily_recommendations.json against their stated machine-readable trigger
conditions. If a trigger has fired, route the stock FIRST into Step 2.7 before any
organic candidates.

**Why:** GOCOLORS was watchlisted May 27 (7.35x vol spike at Rs 254 low). The trigger
"hold at Rs 320-325 support on low vol" fired Jun 1 (close Rs 325, vol 0.56x). Pipeline
Run 18 focused on HFCL/LLOYDSME and never re-checked GOCOLORS against its trigger.
Result: Jun 4 close Rs 402.60 = +23.9% missed in 3 sessions from Jun1 entry.
This was the RM-3 (Support Test + Hold) template — the cleanest, lowest-risk entry type.

**How to apply:**
1. Before Step 2 organic analysis: read `watchlist` section from last 10 entries in daily_recommendations.json
2. For each watchlist item, evaluate trigger condition against current OHLCV data
3. If trigger fired: immediately add to Step 2 candidates with PRIORITY flag and route to Step 2.7
4. If trigger not fired: carry forward (max 10 sessions). After 10 sessions, expire and log.
5. A fired trigger that passes Step 2.7 gets precedence over organic picks.
6. Each watchlist item must have a machine-readable trigger (specific price level + volume condition).
   Vague triggers like "watch for reversal" are not actionable — reject during watchlist creation.

**Carry-forward rules:**
- High-quality setup (conf > 88% at trigger): carry 10 sessions
- Medium-quality (conf 80-88%): carry 8 sessions
- Low-quality (conf < 80%): carry 5 sessions
- Price discovery setups (like GOCOLORS multi-leg): carry 8 sessions

**Why:** GOCOLORS Jun1 entry at Rs 325 = RM-3 Support Test + Hold. Vol 0.56x (no distribution).
RSI ~52 (healthy). Stop Rs 295. Target Rs 380+. R:R 2.5:1. This was a 91%+ confidence setup
that was simply never looked at. The watchlist entry existed but was not systematically checked.
