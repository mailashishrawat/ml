---
name: India Stock Pipeline - Project Context
description: Architecture, model IDs, working directory, file paths, and run history for the Indian stock recommendation pipeline (updated May 19, 2026)
type: project
---

Pipeline runs from: /Users/I038849/Documents/Ashish/github.com/mailashishrawat/ml/code/anthropic/tradingagent/

**Why:** The environment is a SAP corporate proxy. Standard Anthropic model IDs return 400. The correct model IDs for this environment are:
- Haiku:  anthropic--claude-4.5-haiku
- Opus:   anthropic--claude-4.6-opus  
- Sonnet: anthropic--claude-4.5-sonnet

**How to apply:** Always use these proxy model IDs when running the pipeline in this environment.

**MANDATORY PIPELINE STEP 3 -- Previous Recommendations Exit Analysis:**
Always include Step 3 between pattern analysis and final recommendations. Format as a table:
| Symbol | Entry | Exit | P&L % | Result | Notes |
This must show all stocks from the previous day's batch with their exit prices and outcome.

Persistent files generated each run:
- basestock.json -- monthly screened stock universe (openpyxl not installed; JSON fallback)
- pattern_notes.md -- cumulative pattern observations and accuracy tracking
- duopoly_pairs.json -- discovered Indian market duopoly pairs (13 pairs as of May 19)
- daily_recommendations.json -- logged recommendations with entry prices/targets/stops
- step2_output.json -- last analysis output
- final_report.txt -- formatted output report

Run history:
- Run 1: 2026-05-08 (Thu) -- IRCON, BHEL, INOXWIND, HAL, KPTL. T+2 +4.3%. HAL +13.2% star.
- Run 2: 2026-05-11 (Mon) -- PERSISTENT, DATAPATTERNS, NAVINFLUORINE, KECINTL, CGPOWER. T+2 -3.1%.
- Run 3: 2026-05-12 (Tue) -- HINDOILEXP, PARAS, MAZDOCK, PERSISTENT, WAAREE. T+2 exit May 14: -3.47%.
- Run 4: 2026-05-13 (Wed) -- HINDOILEXP, MAZDOCK, DATAPATTERNS, PERSISTENT, INOXWIND. T+2 exit May 15: -0.38%.
- Run 5: 2026-05-14 (Thu) -- HINDOILEXP, MAZDOCK, INOXWIND, BEL, WAAREEENER. T+2 exit May 18: -2.72%.
- Run 7: 2026-05-15 (Fri run 2) -- HINDOILEXP, MAZDOCK, BEL, PIIND, BHEL. T+2 exit May 19: +0.18%.
- Run 8: 2026-05-15 (Fri run 3) -- HINDOILEXP, MAZDOCK, BEL, PIIND, BHEL. T+2 exit May 19: +0.46%.
- Run 9: 2026-05-18 (Mon) -- HAL, ONGC, MAZDOCK, GRSE, PIIND. T+2 exit May 19: +2.03% (4/5 wins).
- Run 10: 2026-05-19 (Mon week 3) -- HAL, PIIND, WAAREEENER, INOXWIND, ONGC. T+2 exit May 21.

Key macro developments by date:
- May 8-12: Iran-USA war onset. WTI $99-103. Defense and E&P outperform.
- May 13-15: India-Pakistan anniversary defense posture. Modi "WFH" speech. Gold falling.
- May 16-18: Trump-Xi Level 4 "friend" language. NIFTYIT -1.99% structural sell. Pattern K gold -3.5%.
- May 18: Nifty -1.22%. Naval triplet dip (Pattern P). COCHINSHIP -6.98%.
- May 19: Trump PAUSED Iran strike ("on hold"). NIFTYIT +3.51% (3rd consecutive green). IT caution lifted.
  Petrol near Rs99/litre = OMC margin reversal. HINDOILEXP struck (B-80/HPCL dispute).
  WAAREEENER extreme oversold recovery (RSI 20.5->recovery). PIIND pre-earnings.

Data sources confirmed working (May 19, 2026):
- screener.in/company/<SYMBOL>/ -- best source for PE, 52w range, financials, price
- investing.com -- WTI crude, gold, NASDAQ, S&P 500
- oilprice.com -- WTI/Brent prices, Iran news
- businesstoday.in -- India market news, Nifty, sector data
- aljazeera.com/news -- geopolitical news
- goldprice.org -- gold price (navigation only, use investing.com instead)
- finance.yahoo.com/markets/ -- US indices

Data sources that fail or are unreliable:
- moneycontrol.com -- blocked
- reuters.com -- blocked
- bbc.com -- blocked
- economictimes.indiatimes.com -- blocked
- livemint.com -- blocked
- marketwatch.com -- blocked
- screener.in/company/NAVINFLUORINE/ -- 404
- screener.in/company/KECINTL/ -- 404 (use KPIL for KEC/Kalpataru)
- DATAPATTERNS screener -- sometimes 404

Next exits pending:
- May 19 batch (Run 10): exits due May 21, 2026 (Wednesday)
  HAL (entry Rs4,323), PIIND (entry Rs3,164), WAAREEENER (entry Rs3,045), INOXWIND (entry Rs96.90), ONGC (entry Rs295)

Critical portfolio rules:
- Standard position size: Rs10,000 per stock (never reduce; drop the stock instead)
- Max 5 stocks per batch
- Exit T+2 (skip weekends and NSE holidays)
- Confidence threshold for final output: strictly > 70
- Leaderboard adjustments: +10 for 100% win rate, -10 for 0% win rate, -15 for stocks 1/5 or worse
- DROP RULE: 0% win rate = exclude until first WIN recorded
- PERMANENT EXCLUDE: 0 wins with 4+ appearances = never re-enter
