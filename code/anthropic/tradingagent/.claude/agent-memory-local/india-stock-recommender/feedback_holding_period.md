---
name: feedback-holding-period
description: User dropped T+2 exit rule — use optimal holding period per thesis (T+4 for pre-results, T+7-T+10 for swing, T+5-T+8 for catalyst-dependent). All rules that block 5%+ opportunities must be relaxed.
type: feedback
---

The T+2 exit constraint is DROPPED. Each recommendation specifies its own optimal holding window based on the thesis. The goal is 5%+ gain; the holding period is whatever best achieves that.

**Why:** T+2 was the single largest limiter of pipeline profitability. Stocks with a strong 1-2 week thesis (FII accumulation, pre-results positioning, dispute resolution) were consistently excluded or under-targeted because T+2 capped them. WAAREEENER with 10x FII accumulation scored 0/2 on T+2 but has a credible +11-15% path over 1-2 weeks. SUZLON pre-Q4-results was excluded at 74% under T+2 framework but qualifies at 92% with a T+4 hold. The user's explicit goal is 5%+ profit; we should surface it regardless of holding period.

**Related rule drops also effective:**
1. Leaderboard penalties DROPPED — T+2 losses are irrelevant for swing holds. Leaderboard is now informational only.
2. RSI ceiling relaxed to >82 (was >75). RSI 75-82 is valid with a confirmed catalyst.
3. Earnings timing discount DROPPED — pre-results positive thesis is a catalyst, not a risk.
4. All monetary values in Rs Lakh format (Rs 10,000 = Rs 0.10 Lakh).

**Holding period mapping by thesis type:**
- Pre-results positioning: T+4 to T+6 (hold through announcement + reaction day)
- FII accumulation / structural story: T+7 to T+14 (swing; institutions take time)
- Dispute/event-driven catalyst: T+5 to T+10 (hold until catalyst fires)
- RSI recovery + sector momentum: T+2 to T+4 (original short-term framework; still valid)
- Breakout + volume (Pattern H): T+2 to T+5 (momentum; stop if volume fades)

**How to apply:**
- For each pick, first ask: "What is the optimal holding period for THIS thesis?"
- Set exit window to match. Do not force every thesis into T+2.
- Show the "Exit Window" in the recommendations table instead of a fixed exit date.
- Trailing stops are appropriate for swing holds once the stock moves +5% toward target.

**Confidence threshold:** Still strictly > 78%. Rule relaxations are about expanding candidate universe and holding flexibility — not about lowering the conviction bar.
