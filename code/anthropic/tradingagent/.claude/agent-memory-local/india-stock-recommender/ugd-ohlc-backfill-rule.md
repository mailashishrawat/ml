---
name: ugd-ohlc-backfill-rule
description: When Step 4.6.5 force-adds a stock via UGD, immediately backfill 60 days of OHLCV to .cache/ohlc/ — without it, next session's Step 2 pattern scan is blind to the new addition.
metadata:
  type: feedback
---

Any stock force-added to `basestock.json` via Step 4.6.5 UGD (Universe Gap Detection) MUST get an immediate 60-day OHLCV backfill via yfinance to `.cache/ohlc/<SYMBOL>.csv` and an `_meta.json` update. Without the cache, the stock is invisible to the next session's Step 2 pattern recognition pass (Rule 80 coil scan, RM-1 through RM-11, etc.) — only the symbol is in the universe, not the price history needed to recognize a setup.

**Why:** PANAMAPET was UGD-added on Jun 18 (after a prior >5% move). On Jun 19 it ran +20% to ₹489.90 (₹513 Cr value traded — top-4 NSE gainer). The Jun 19 run could not pattern-recognize the setup because there was no T-1 cache for PANAMAPET — the symbol was in `basestock.json` but the OHLC pull would have had to fetch fresh, and the run-time sequence didn't reach for it. Result: predictable +20% miss.

**How to apply:** Modify Step 4.6.5 UGD action (STALE_SCREENING bucket especially):
1. Force-add symbol to `basestock.json`.
2. **Same step, before exiting Step 4.6:** call `yf.Ticker("{SYMBOL}.NS").history(period="60d")` → write CSV to `.cache/ohlc/<SYMBOL>.csv`.
3. Update `.cache/ohlc/_meta.json` with `last_fetched_date` = today.
4. Log in 4.6.7 output: "OHLC_BACKFILL: <SYMBOL> 60d cached (N rows)".

If yfinance fetch fails, log `OHLC_BACKFILL_FAIL — <SYMBOL>` and retry at start of next session before Step 2.

Related: [[step-4-6-nse-wide-self-audit]] (Step 4.6.5 host), [[feedback-pre-breakout-scanner-rule-80]] (the pattern scanner that needs the cache).
