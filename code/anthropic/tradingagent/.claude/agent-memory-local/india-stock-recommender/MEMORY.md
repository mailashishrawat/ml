# Agent Memory Index — India Stock Recommender

- [Pipeline Project Context](project_pipeline.md) — Pipeline architecture, model IDs, working dir, first run date
- [Market Pattern Notes](project_patterns.md) — Patterns identified, duopoly pairs, accuracy observations
- [User Profile](user_profile.md) — User goals and collaboration preferences
- [Position Sizing & Count Rule](feedback_position_sizing.md) — Max 3 picks (not 5), confidence > 78, never reduce position size, drop the stock instead
- [Output Format](feedback_output_format.md) — Final recommendations always in: Rank │ Symbol │ Entry │ Target │ Stop │ Confidence │ Exit Date
- [Breakout/Momentum Pattern](feedback_breakout_pattern.md) — Pattern H: defense order + volume breakout; added after APOLLO MICRO +17% miss; retrospective miss scan mandatory each run
- [News Catalyst Scanning](feedback_news_catalysts.md) — Pattern J + Step 1.5 must scan ET/BS/Mint/MC daily for state-visit MoUs, govt orders, USFDA; added after TATACOMM-ASML miss
