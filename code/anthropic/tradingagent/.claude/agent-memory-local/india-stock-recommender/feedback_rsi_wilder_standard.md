---
name: feedback-rsi-wilder-standard
description: All RSI computations must use Wilder smoothing (alpha=1/14, adjust=False). SMA RSI reads 8-12 points lower and causes RM-11 cap breaches to go undetected. Validated: NIACL Jun 19 SMA-RSI=70.2 vs Wilder-RSI=81.5.
metadata:
  type: feedback
---

All RSI values in the pipeline must use **Wilder's smoothing method** (14-period), not simple moving average (SMA).

**Why:** In Run #34 (Jun 22), NIACL RSI was quoted as 70.2 at Jun 19 close, which passed the RM-11 cap of 78. The actual Wilder RSI at that close was 81.5 — an 11-point gap. This caused the pipeline to recommend NIACL entry @ Rs196-198 for Jun 22 under RM-11, when the correct Wilder RSI would have required the RM-11 extended cap check (Day-1 vol ≥10× → cap 85, still valid; but the mis-stated RSI created a false narrative in the run output). The root cause: `rolling(14).mean()` on gains/losses gives SMA-RSI; production code must use `ewm(alpha=1/14, adjust=False)`.

**How to apply:** In any step that computes or references RSI (Step 2, Step 2.3 RM-11 gate, Step 2.7 RSI ceiling checks, Step 3.1, Step 3.2, Step 4.6 pattern attribution):

Use this code template:
```python
delta = closes.diff()
gain = delta.clip(lower=0)
loss = (-delta).clip(lower=0)
avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
rsi = 100 - (100 / (1 + avg_gain / avg_loss))
```

Do NOT use `rolling(14).mean()` or `ewm(com=13)` for RSI. These are incorrect and produce systematically lower values during strong uptrends.

**Sanity check:** After computing RSI, verify: if a stock has moved +25% in 2 sessions, its Wilder RSI should be in the 75-85 range, not 68-72. Values in the 68-72 range after such moves are a sign of SMA-RSI being used.

Related: [[rm-11-consecutive-catalyst-continuation]] (the RM-11 RSI cap was adjusted as a consequence of this finding).
