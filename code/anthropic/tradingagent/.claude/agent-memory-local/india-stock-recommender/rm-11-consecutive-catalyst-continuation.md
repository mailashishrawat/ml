---
name: rm-11-consecutive-catalyst-continuation
description: RM-11 template — 2 consecutive ≥8% sessions on ≥2x vol with RSI<85 (or <78 for vol 2-10x) = institutional wave, NOT exhaustion. RSI cap raised from 78→85 after Jun 19 validation (NIACL Wilder RSI=81.5 vs SMA=70.2 — 11pt gap caused incorrect classification).
metadata:
  type: feedback
---

When a stock posts TWO consecutive sessions of ≥8% gain, both on volume ≥2× 20d avg, and RSI (Wilder, 14-period) is still below the applicable cap, treat it as **RM-11: Consecutive Catalyst Continuation** — confidence base 90, propose entry on next 1-2% dip. Do NOT auto-classify day 2 as NEWS_PRICED_IN (RM-9).

**RSI caps (use Wilder smoothing only — see Rule RSI-1):**
- Day-1 vol ≥10× avg: RSI cap **85** (large institutional wave absorbs RSI overshoot)
- Day-1 vol 2–10× avg: RSI cap **78** (standard institutional confirmation)
- Above respective cap: revert to RM-9 EXHAUSTION

**Why cap was raised from 78 → 85 (Jun 20 2026 update):** Run #34 (Jun 22) quoted NIACL RSI as 70.2 — but this was SMA-smoothed RSI. Wilder RSI at Jun 19 close was **81.5**. The 12-point gap caused an incorrect RM-11 classification that survived into the final pick (NIACL recommended @ Rs196-198 on Jun 22). At 12.5x then 7x volume on Day 1/2, the institutional wave is large enough that RSI overshooting 78 is a feature (absorption), not exhaustion. The key distinguishing test: does vol STAY elevated Day 2 (continuation) or COLLAPSE (Sub-Rule 26f climax)?

**Why original rule was created:** NIACL Jun 18-19: Day 1 +12.2% on 12.5x vol classified NEWS_PRICED_IN, pullback watchlist Rs165-170. Day 2: another +12.4% on 7x vol, closed Rs200.90 — continuation. Pullback thesis was wrong; institutional buying wave was the reality.

**How to apply:** In Step 2.3, before classifying any day-2 mover as RM-9, check the RM-11 gate:
1. Both sessions ≥8% close-to-close gain.
2. Both sessions volume ≥2× 20d avg.
3. Wilder RSI < applicable cap (85 if Day-1 vol ≥10×; 78 if Day-1 vol 2-10×).
4. Both sessions closed in upper 40% of intraday range (no distribution wick).

**CRITICAL: Always use Wilder RSI (Rule RSI-1). SMA RSI reads 8-12 points lower and causes cap breaches to go undetected.**

Related: [[feedback-rsi-wilder-standard]], [[feedback-no-double-penalty-thin-vol-digestion]], [[watchlist-persistence-rule]].
