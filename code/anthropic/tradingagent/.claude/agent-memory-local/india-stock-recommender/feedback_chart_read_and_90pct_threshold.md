---
name: feedback-chart-read-and-90pct-threshold
description: Mandatory Step 2.7 chart read gate before final list; confidence threshold raised from >78% to >90%; 88% large-cap cap superseded; 0-pick days are the expected outcome
metadata:
  type: feedback
---

## Rule: Mandatory Step 2.7 Chart Read (hard gate, no exceptions)

Every candidate that passes Step 2.5 must pass Step 2.7 before it can enter the final
recommendation list. The chart read is not optional, not waivable, and not overridable
by confidence score or catalyst strength.

The chart read evaluates seven mandatory items:

1. Sub-Rule 26f (one-bar climax + stall): single session +10%+ followed by 1-2 sessions
   flat/down with vol < 0.4x 20d avg = CLIMAX EXHAUSTION. FAIL.
2. Rule 46b (decelerating staircase): 3+ consecutive closes with shrinking daily range
   AND vol < 0.2x throughout = DECELERATING-STAIRCASE EXHAUSTION. FAIL.
3. Daily range trajectory over last 3 closes: EXPANDING / STEADY / COMPRESSING.
4. Volume trajectory over last 3 sessions: RISING / FLAT / DRYING UP.
5. Distance from MA5 + momentum direction (ACCELERATING or COOLING).
6. Distance to nearest resistance vs. proposed target. Target requiring 2+ additional +5%
   resistance breaks is unrealistic -- revise to nearest realistic resistance.
7. R:R on the REVISED realistic target (not the optimistic one) must be >= 1.5:1.
   Below 1.5:1 = FAIL regardless of all other factors.

Output: PASS or FAIL + one-paragraph honest tape read.
FAIL = watchlist with re-entry trigger only.

**Why:** NETWEB (Jun 2, 2026) was at 84% confidence and passed all prior gates. User
chart review found a vertical +14.7% one-bar spike (Sub-Rule 26f) followed by 2 sessions
of 0.20x volume -- climax exhaustion, not breakout continuation. HFCL (Jun 2, 2026) was
at 87% confidence. User identified decelerating-staircase pattern (Rule 46b): daily
increments +2, +1 with 0.08x volume. R:R on revised Rs 189 target = 0.86:1 (below 1.5:1).
Both picks were removed/downgraded by manual chart read. This gate makes the chart read
mandatory and systematic so no future pick bypasses it.

**How to apply:** Run Step 2.7 for every Step 2.5 passer, every run, every pattern type.
Do not shortcut for "obvious" candidates. A FAIL here is permanent for that run -- the
stock joins the watchlist with a specific re-entry trigger.

---

## Rule: Confidence Threshold Raised to >90%

Only stocks with confidence STRICTLY GREATER THAN 90% qualify for the final recommendation list.
Stocks at 78-90% are watchlist-only, never main picks.

This supersedes ALL prior threshold rules and caps:
- The >78% threshold used in runs 1-19: superseded.
- The 88% large-cap cap from the Large-Cap Rule for trending sectors ([[large-cap-rule-trending-sectors]]): superseded. Large-cap picks also need >90%.
- Pattern O AI/Cloud Infra Universe ([[pattern-o-ai-cloud-infra-universe]]) picks: >90% required.
- Event-driven notes (TRENT AGM, etc.): watchlist if below 90%, never main picks.

The 0-pick day is the EXPECTED outcome on most days. Ship 0 if nothing clears 90%.
Do not pad. Do not lower confidence to fit. Do not "round up" an 89% to qualify.

**Why:** After 19 runs, the pipeline was generating marginal picks at 78-87% that failed
post-entry chart review. HFCL at 87% failed the chart read on Jun 2 (Rule 46b + R:R 0.86:1).
NETWEB at 84% failed the chart read (Sub-Rule 26f). Both would have been recommended under
the >78% rule. The threshold raise, combined with the mandatory chart read gate, means only
stocks that are BOTH high-conviction AND showing clean tape action reach the list.
False positives are costly. Zero picks is not a failure -- it is the system working correctly.

**How to apply:** At Step 4 (Result Formatting), filter to confidence > 90 AND chart_read = PASS.
If the filtered list is empty, output 0 picks with a brief explanation of why no stock
cleared both gates. Never state "no picks today" apologetically -- state it as expected.
