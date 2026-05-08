---
name: User Profile - India Stock Recommender
description: User goals, preferences, and collaboration style for the Indian stock market pipeline
type: user
---

The user runs a quantitative Indian stock recommendation pipeline using Claude as the analysis engine. They want actionable mid-cap and small-cap NSE/BSE stock picks backed by fundamental screening, technical pattern recognition, and news validation.

Key preferences observed:
- Wants confidence-ranked output (top 5 final picks)
- Prefers PSU/government-capex-linked stocks given current India macro cycle
- Interested in pattern accuracy tracking across multiple runs (self-improvement loop)
- Working directory: /Users/I038849/Documents/Ashish/github.com/iimb/ml/code/anthropic/tradingagent/
- Environment is SAP corporate proxy — standard Anthropic model IDs fail; must use proxy IDs

**How to apply:** Tailor responses around Indian equity market context. When running subsequent pipeline iterations, check daily_recommendations.json to provide performance feedback. The user runs this on Thursdays (pre-weekend positioning day for Indian markets).
