---
name: feedback-breakout-pattern
description: Pattern H breakout/defense order momentum + Rule 26 chart confirmation — chart structure must validate fundamental thesis before entry; falling knife, distribution, double-top, and active downtrend rules
type: feedback
---

Add Pattern H (Breakout/Defense Order Momentum) to Step 2 analysis on every run. The screener was missing explosive short-term movers like APOLLO MICRO SYSTEMS (+17% in 2 days) because it only looked for RSI recovery and FII accumulation — not for breakout + catalyst combos.

**Why (Pattern H):** APOLLO MICRO surged 17% in 2 days while the pipeline recommended lower-conviction stocks. The root cause: no pattern was checking for (a) 52-week/6-month high breakouts with above-average volume AND (b) defense/space/government order catalysts for small-cap defense electronics names.

**How to apply (Pattern H — Breakout/Defense Order Momentum):**
- Every run: scan for stocks that broke above a significant resistance level (52-wk high, 6-month high) in the last 1-2 sessions with volume >= 1.5x 20-day avg.
- Every run: search for MoD procurement orders, ISRO/DRDO contracts, defense ministry approvals issued in the last 5 days for small-cap defense names.
- Key universe: APOLLO MICRO, MTAR, ZEN TECH, ASTRA MICROWAVE, PARAS DEFENCE, SIKA INTERPLANT, BHARAT DYNAMICS, CENTUM ELECTRONICS.
- Exception to RSI > 75 ceiling: if volume >= 2x avg AND a concrete government order exists AND RSI < 85, entry is still valid — momentum continuation is expected.
- Signal confidence tiers: breakout alone +10, breakout + defense order +20, breakout + order + sector tailwind +25.
- Also do a retrospective miss scan at the start of each run (stocks +8%+ last 2 days that were not recommended) — identify the trigger and add it as a new pattern or update existing ones.

---

## RULE 26 — CHART STRUCTURE MUST CONFIRM THESIS BEFORE ENTRY (added 2026-05-22)

**Why Rule 26 exists:** On May 22, 2026, the agent recommended WAAREEENER at 92% confidence based on FII 10x accumulation + US-China solar structural thesis. The user reviewed the chart and found: peaked ~Rs 3,500 early May, sharp cliff drop to Rs 3,000 on massive volume (institutional selling). Current Rs 3,043 was a tiny bounce, not a reversal. A fundamental catalyst alone cannot override chart-level distribution. Rule 26a would have caught this. WAAREEENER was removed. KPIL (Rs 2,300 Cr order win today, PAT +82% YoY, near 52w high, clean uptrend) replaced it as Pick 3.

**The Rule:**
A fundamental catalyst (FII accumulation, news catalyst, earnings growth) alone is NOT sufficient for entry if the price chart shows institutional distribution or a failed breakout. Chart structure must confirm the thesis.

### Sub-Rule 26a: Falling Knife Rule
- If a stock has dropped >8% in fewer than 5 sessions on ABOVE-average volume = institutional selling = falling knife = DO NOT ENTER.
- Wait condition: 3+ days of sideways price action with LOWER-than-average volume before re-entry.
- Overrides: Pattern G (FII accumulation), Pattern J (News catalyst), Pattern D (Institutional Dip) — chart rule takes precedence for entry timing.

### Sub-Rule 26b: Institutional Distribution Rule
- Distribution pattern = large volume on DOWN days + small volume on UP days = institutions selling into rallies.
- Accumulation pattern (safe) = larger volume on UP days + smaller volume on DOWN days = institutions buying dips.
- If distribution visible: reduce confidence -20 points; or remove if combined with falling knife.

### Sub-Rule 26c: Double-Top / Resistance Rejection Rule
- Two failed attempts to break a known resistance level = double-top = DO NOT enter at current price.
- Entry condition: confirmed close ABOVE resistance with volume >= 1.5x 20-day average.
- Confidence adjustment: double-top present = -15 confidence. Show as CONDITIONAL entry in report.
- HINDOILEXP example: Strong uptrend Rs 120 -> Rs 172-173 (March-May 2026), then double-top rejection at Rs 172-173. Entry conditional: only valid if Rs 173 breaks on volume.

### Sub-Rule 26d: Active Downtrend Disqualification (NEW — added 2026-05-27)

**Why Rule 26d was added:** On May 27, 2026, the agent recommended BEL (84%) and BPCL (82%) based on fundamental narratives (BEL: Q4 PAT +41%, FII 19.5%; BPCL: PE 5.68, Pattern Q margin reversal, "cup-and-handle"). The user reviewed both charts and found active downtrends with no confirmed reversals. The agent had described pattern labels that fit a bullish narrative but were not accurate to the current price action. BEL showed a V-bounce off lows followed by sharp pullback — still below all prior highs. BPCL showed a staircase downtrend; the "cup" right rim (Rs 304) was 22% below the left rim (Rs 391) — that is a downtrend channel, not a cup. Both picks are retroactively invalidated.

**The Rule:**
Before recommending ANY stock as a buy, the price action must show AT MINIMUM ONE of:
1. Price has closed above a prior swing high (trend change confirmation — first higher high after a downtrend).
2. At least 2-3 weeks of sideways consolidation above support with no new lows (base formation).
3. Higher lows AND higher highs sequence established on the daily chart (at least 2 higher lows + 1 higher high).

If a stock is in an active downtrend (lower highs, lower lows) with NONE of the three conditions met: it MUST NOT be recommended. Label it "WAIT — downtrend not confirmed reversed" and add to WATCHLIST with the specific price that would confirm one condition.

**Why:** (a) BEL/BPCL May 27 2026 — both in active downtrends, both recommended incorrectly. (b) Fundamental thesis (cheap PE, strong earnings, FII accumulation) does not create a buy signal if the price trend is still down. Institutions can have high holdings AND be reducing — the chart tells the truth about actual flow, not the percentage.

**How to apply:**
- Run this check AFTER Rule 26a/b/c, BEFORE confirming any pick.
- Check 4: Is the stock making lower highs AND lower lows on the daily chart?
  - If YES: Is Condition A met (closed above prior swing high)? If NO — disqualify.
  - If YES: Is Condition B met (2-3 weeks sideways, no new lows)? If NO — disqualify.
  - If YES: Is Condition C met (2 higher lows + 1 higher high confirmed)? If NO — disqualify.
  - If ALL NO: Remove from picks, label "WAIT — downtrend not confirmed reversed."
- Pattern label discipline: When using a chart pattern name (cup-and-handle, Wyckoff, recovery cycle), verify that (a) the CURRENT price is at the ideal entry point, not at the bottom of a downtrend labelled optimistically, and (b) the pattern has not failed (e.g., cup right rim > 10% below left rim = failed cup = downtrend channel).

### Application checklist (run before every recommendation):
1. Has stock dropped >8% in last 5 sessions on above-avg volume? YES = Falling Knife = remove.
2. Is volume pattern showing distribution (big vol on red days, small vol on green days)? YES = -20 confidence.
3. Visible double-top or resistance rejection at known level? YES = conditional entry only (-15 confidence).
4. Is stock in active downtrend (lower highs + lower lows) with NONE of conditions A/B/C met? YES = "WAIT — downtrend not confirmed reversed" = remove.
Only confirm pick if all four answers are NO (or confirmed base after knife drop / confirmed trend reversal).

**How to apply going forward:**
- Before confirming any Pattern G or Pattern J pick: run Rule 26 checklist (all 4 sub-rules).
- If falling knife detected: keep stock on WATCH LIST with note "wait for 3+ day base formation before re-entry."
- If active downtrend detected (Rule 26d): keep on WATCH LIST with note "WAIT — [specific price] above for Condition A, OR [number] weeks sideways for Condition B."
- Double-top stocks get CONDITIONAL entry label in report with explicit breakout price and volume requirement.
