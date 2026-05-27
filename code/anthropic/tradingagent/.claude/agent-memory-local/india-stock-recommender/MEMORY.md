# Agent Memory Index — India Stock Recommender

- [Pipeline Project Context](project_pipeline.md) — Pipeline architecture, model IDs, working dir, first run date
- [Market Pattern Notes](project_patterns.md) — Patterns identified, duopoly pairs, accuracy observations
- [User Profile](user_profile.md) — User goals and collaboration preferences
- [Position Sizing & Count Rule](feedback_position_sizing.md) — Max 3 picks, confidence > 78, never reduce position size, drop the stock instead
- [Holding Period & Rule Relaxations](feedback_holding_period.md) — T+2 dropped; use optimal window per thesis; leaderboard penalties dropped; RSI ceiling at >82 only; earnings discount dropped
- [Monetary Format](feedback_lakh_format.md) — All monetary values in Rs Lakh format (Rs 10,000 = Rs 0.10 Lakh)
- [Output Format](feedback_output_format.md) — Final recommendations always in: Rank │ Symbol │ Entry │ Target │ Stop │ Confidence │ Exit Window
- [Breakout/Momentum Pattern + Rule 26](feedback_breakout_pattern.md) — Pattern H: defense order + volume breakout; RSI ceiling >82 only; RULE 26: chart must confirm thesis (falling knife 26a, distribution 26b, double-top 26c, active downtrend 26d, volatility floor 26e — BEL/BPCL May 27 retroactive invalidation under 26d AND 26e)
- [Volatility Floor Rule 26e](feedback_volatility_filter.md) — Proportional threshold: seasoned stocks >=40 days/252; recent listings ceil(avail/252*40) with 10-day floor; <30 days auto-fail; top 100 by normalized rate; Condition D in Step 2.5; BEL/BPCL fail
- [News Catalyst Scanning](feedback_news_catalysts.md) — Pattern J + Step 1.5 must scan ET/BS/Mint/MC daily for state-visit MoUs, govt orders, USFDA; added after TATACOMM-ASML miss
- [Pattern S — IPO/Post-Listing Reversal + LPI Sub-Pattern](pattern_S_ipo_reversal.md) — ATHER trade (May 22-26 2026); exhaustion low on recently listed stocks; LPI sub-pattern +8 boost when 4+ quarters of loss narrowing; SWIGGY (80) and FIRSTCRY (82) are active WATCH candidates
- [Basestock cadence + no-cap rule](feedback_basestock_cadence.md) — basestock.json regenerates monthly (not weekly); read as-is until next_regeneration_due; no top-N cap, keep every stock passing all rules
