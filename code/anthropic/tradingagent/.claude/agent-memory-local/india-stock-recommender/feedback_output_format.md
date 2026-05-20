---
name: feedback-output-format
description: Required output format for final recommendations — pipe-separated table with Rank column
type: feedback
---

Final recommendations must always be presented in this exact table format:

```
Rank │   Symbol   │   Entry    │   Target   │    Stop    │  Confidence  │  Exit Date
─────┼────────────┼────────────┼────────────┼────────────┼──────────────┼────────────
 1   │  SYMBOL1   │  ₹XXX.XX   │  ₹XXX.XX   │  ₹XXX.XX   │     XX%      │ YYYY-MM-DD
```

**Why:** User explicitly requested this format.

**How to apply:** Show this table prominently at the top of the recommendations section, before per-stock narrative. It is mandatory — never omit or replace with prose only.
