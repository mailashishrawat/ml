# Agent Memory Index — India Stock Recommender

- [Pipeline Project Context](project_pipeline.md) — Pipeline architecture, model IDs, working dir, first run date
- [Market Pattern Notes](project_patterns.md) — Patterns identified, duopoly pairs, accuracy observations
- [User Profile](user_profile.md) — User goals and collaboration preferences
- [Position Sizing & Count Rule](feedback_position_sizing.md) — Max 3 picks, confidence > 78, never reduce position size, drop the stock instead
- [Holding Period & Rule Relaxations](feedback_holding_period.md) — T+2 dropped; use optimal window per thesis; leaderboard penalties dropped; RSI ceiling at >82 only; earnings discount dropped
- [Monetary Format](feedback_lakh_format.md) — All monetary values in Rs Lakh format (Rs 10,000 = Rs 0.10 Lakh)
- [Output Format](feedback_output_format.md) — Final recommendations always in: Rank │ Symbol │ Entry │ Target │ Stop │ Confidence │ Exit Window
- [Breakout/Momentum Pattern + Rule 26](feedback_breakout_pattern.md) — Pattern H: defense order + volume breakout; RSI ceiling >82 only; RULE 26: chart must confirm thesis (falling knife, distribution, double-top rules)
- [News Catalyst Scanning](feedback_news_catalysts.md) — Pattern J + Step 1.5 must scan ET/BS/Mint/MC daily for state-visit MoUs, govt orders, USFDA; added after TATACOMM-ASML miss
