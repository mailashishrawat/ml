---
name: feedback-output-format
description: Required output format for final recommendations — pipe-separated table with Rank column; Exit Window replaces Exit Date (since T+2 constraint was dropped on 2026-05-22)
type: feedback
---

Final recommendations must always be presented in this exact table format:

```
Rank │   Symbol   │   Entry    │   Target   │    Stop    │  Confidence  │  Exit Window
─────┼────────────┼────────────┼────────────┼────────────┼──────────────┼─────────────────
 1   │  SYMBOL1   │  Rs XXX.XX │  Rs XXX.XX │  Rs XXX.XX │     XX%      │ YYYY-MM-DD (T+N, rationale)
```

**Changes from original (as of 2026-05-22):**
- "Exit Date" renamed to "Exit Window" — each pick now shows its own optimal holding period (e.g., "May 27 (T+4, post-results)", "June 1-4 (T+7-T+10, swing)")
- Rs symbol used (not rupee sign) for compatibility
- Monetary values in Rs Lakh in supporting tables (Rs 10,000 = Rs 0.10 Lakh)

**Why:** User explicitly requested this format. The T+2 constraint was dropped on 2026-05-22 — the exit window now reflects the optimal holding period for each specific thesis.

**How to apply:** Show this table prominently at the top of the recommendations section, before per-stock narrative. It is mandatory — never omit or replace with prose only.

