---
name: feedback-position-sizing
description: User rule on position sizing and recommendation count — max 3 picks, never reduce position, drop the stock instead
type: feedback
---

Never reduce position size for a stock. Every recommendation uses the standard ₹10,000 position. Maximum 3 stocks per day (reduced from 5 on 2026-05-20 after sustained negative P&L).

**Why:** (1) User explicitly instructed — if a stock doesn't meet full conviction, remove it, don't dilute. (2) After 10 runs, overall P&L was -₹1,809 (-0.55%). Too many marginal 4th and 5th picks dragged performance. Fewer, higher-conviction bets is the explicit strategy shift. (3) User cited APOLLO MICRO missing as evidence the screener was casting too wide a net on mediocre stocks while missing momentum breakouts.

**How to apply:**
- Maximum 3 stocks in final output. Never pad to reach 3.
- Confidence threshold for final output is strictly > 78 (raised from 70).
- If only 1 or 2 stocks meet the bar, show only those. Showing 1 great pick is better than adding 2 marginal ones.
- 3 is the ceiling, not a target.
